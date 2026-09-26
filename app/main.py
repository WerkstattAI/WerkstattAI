from __future__ import annotations

import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError

from app.ai_service import polish_reply_de
from app.auth import decode_session_token, get_current_user, is_dashboard_path, login_redirect_url
from app.customer_access import CustomerAccess, normalize_customer_phone
from app.customer_sessions import bound_web_session
from app.customer_handoff import receive_customer_message
from app.config import settings
from app.db import (
    atomic_database,
    get_conn,
    lock_communication_scope,
    default_workshop_id,
    demo_workshop_id,
    get_whatsapp_conversation_control,
    init_db,
    set_whatsapp_conversation_control,
)
from app.conversation_sessions import load_session_state, save_session_state
from app.conversation.router import next_step
from app.models import (
    ChatRequest,
    ChatResponse,
    IntakeState,
    WhatsAppWebhookRequest,
    WhatsAppWebhookResponse,
)
from app.tickets import (
    find_ticket_by_id,
    list_latest_tickets,
    save_ticket,
    update_ticket_status,
)
from app.subscriptions import get_subscription, is_subscription_active
from app.whatsapp import (
    parse_meta_messages,
    parse_meta_statuses,
    save_whatsapp_event,
    save_whatsapp_message,
    send_whatsapp_text_message,
    update_whatsapp_message_status,
    verify_signature,
)
from app.web import router as web_router
from app.workshops import find_workshop_id_by_whatsapp_phone_number_id
from app.http_security import secure_application
from app.security_config import MAX_MESSAGE_LENGTH, is_production, validate_security_settings
from app.privacy_routes import router as privacy_router

logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title=settings.app_name,
    default_response_class=UTF8JSONResponse,
    docs_url=None if is_production(settings) else "/docs",
    redoc_url=None if is_production(settings) else "/redoc",
    openapi_url=None if is_production(settings) else "/openapi.json",
)

# ✅ NOWE — inicjalizacja bazy SQLite
@app.on_event("startup")
def on_startup():
    validate_security_settings(settings)
    init_db()


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, error: RequestValidationError):
    # Validation responses must not echo passwords or oversized user input.
    return UTF8JSONResponse(status_code=422, content={"detail": [
        {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]})


@app.middleware("http")
async def dashboard_auth_middleware(request, call_next):
    if is_dashboard_path(request.url.path):
        user = decode_session_token(request.cookies.get("werkstattai_session"))
        if not user:
            return RedirectResponse(url=login_redirect_url(request), status_code=303)
        request.state.user = user

    return await call_next(request)


app.include_router(web_router)
app.include_router(privacy_router)


def _dump_state(state: IntakeState) -> dict:
    """
    Kompatibel mit Pydantic v1 und v2.
    """
    if hasattr(state, "model_dump"):
        return state.model_dump()
    return state.dict()


def _normalize_status(status: str) -> str:
    """
    Vereinheitlicht Statuswerte.
    """
    value = (status or "").strip().lower()

    if value == "geschlossen":
        return "erledigt"

    allowed = {"offen", "in_bearbeitung", "erledigt", "archiviert"}
    if value not in allowed:
        raise ValueError(
            "Ungültiger Status. Erlaubt sind: offen, in_bearbeitung, erledigt"
        )

    return value


def _normalize_workshop_id(value: str | None = None) -> str:
    return (value or default_workshop_id()).strip() or default_workshop_id()


def _current_user_from_request(request: Request) -> dict | None:
    return get_current_user(request)


def _workshop_id_for_api_request(request: Request, value: str | None = None) -> str:
    user = _current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login erforderlich")

    role = str(user.get("role") or "").strip().lower()
    if role == "admin" and value:
        return _normalize_workshop_id(value)

    return _normalize_workshop_id(str(user.get("workshop_id") or ""))


def _normalize_phone_for_session(phone: str | None) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def whatsapp_session_id(phone: str | None) -> str:
    normalized_phone = _normalize_phone_for_session(phone)
    return f"whatsapp:{normalized_phone or 'unknown'}"


def _response_ticket_id(response: ChatResponse) -> str | None:
    ticket_id = response.data.get("ticket_id") if isinstance(response.data, dict) else None
    if ticket_id is None:
        return None
    return str(ticket_id).strip() or None


@atomic_database()
def process_chat_message(
    *,
    workshop_id: str,
    session_id: str,
    message: str | None,
    channel: str,
    phone: str | None = None,
    message_id: str | None = None,
) -> ChatResponse:
    lock_communication_scope(get_conn(), workshop_id)
    if not is_subscription_active(workshop_id):
        raise HTTPException(
            status_code=402,
            detail="WerkstattAI ist fuer diese Werkstatt nicht aktiv.",
        )

    verified_phone = normalize_customer_phone(phone) if channel == "whatsapp" else None
    if channel == "whatsapp" and not verified_phone:
        raise HTTPException(status_code=400, detail="Ungültiger WhatsApp-Absender")
    state = load_session_state(session_id, workshop_id=workshop_id, channel=channel)
    state.workshop_id = workshop_id

    access = CustomerAccess(
        workshop_id=workshop_id,
        allowed_ticket_ids=frozenset({state.ticket_id}) if channel == "web_chat" and state.ticket_id else frozenset(),
        verified_phone=verified_phone,
    )
    ticket = find_ticket_by_id(state.ticket_id, workshop_id) if state.ticket_id else None
    if ticket and access.allows(ticket) and ticket.get("conversation_state") != "assistant_active":
        if message and message.strip():
            ticket = receive_customer_message(ticket, message, workshop_id=workshop_id, message_id=message_id)
        # Manual workshop questions never become intake answers, even after a reload.
        return ChatResponse(reply="", done=False, data={**_dump_state(state),
            "conversation_state": ticket["conversation_state"],
            "workshop_messages": [n for n in ticket["notes"] if n.get("sender_role") == "workshop"
                                  and n.get("purpose") != "internal_note" and n.get("delivery_status") in {None, "sent"}]})
    new_state, reply, done = next_step(state, message, customer_access=access, message_id=message_id)
    new_state.workshop_id = workshop_id

    reply = polish_reply_de(reply)

    if done and not new_state.ticket_id:
        new_state.source = channel
        ticket_id = save_ticket(new_state, workshop_id=workshop_id, verified_customer_phone=verified_phone)
        new_state.ticket_id = ticket_id
        reply = (
            reply
            + f"\n\nTicket-Nr.: **{ticket_id}**\n"
            + "Bitte notieren Sie sich diese Nummer für Rückfragen."
        )

    save_session_state(
        session_id,
        new_state,
        workshop_id=workshop_id,
        channel=channel,
        phone=phone,
    )

    ticket = find_ticket_by_id(new_state.ticket_id, workshop_id) if new_state.ticket_id else None
    return ChatResponse(
        reply=reply,
        done=done,
        data={**_dump_state(new_state), "conversation_state": (ticket or {}).get("conversation_state", "assistant_active"),
              "workshop_messages": [n for n in (ticket or {}).get("notes", []) if n.get("sender_role") == "workshop"
                                    and n.get("purpose") != "internal_note" and n.get("delivery_status") in {None, "sent"}]},
    )


@app.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def whatsapp_webhook_verify(
    request: Request,
    mode: str | None = Query(None, alias="hub.mode"),
    verify_token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    return _verify_whatsapp_webhook_challenge(request, mode, verify_token, challenge)


@app.get("/meta/whatsapp", response_class=PlainTextResponse)
def whatsapp_webhook_verify_alt(
    request: Request,
    mode: str | None = Query(None, alias="hub.mode"),
    verify_token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    return _verify_whatsapp_webhook_challenge(request, mode, verify_token, challenge)


def _verify_whatsapp_webhook_challenge(
    request: Request,
    mode: str | None,
    verify_token: str | None,
    challenge: str | None,
) -> PlainTextResponse:
    expected = str(settings.whatsapp_verify_token or "").strip()
    provided = str(verify_token or "")
    logger.info(
        "WhatsApp webhook verify path=%s mode=%s challenge=%s token_len=%s expected_len=%s token_match=%s",
        request.url.path,
        mode,
        bool(challenge),
        len(provided),
        len(expected),
        bool(expected and provided == expected),
    )
    if mode == "subscribe" and expected and verify_token == expected and challenge:
        return PlainTextResponse(challenge)

    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


def _process_test_whatsapp_webhook(payload: WhatsAppWebhookRequest) -> WhatsAppWebhookResponse:
    """The local test format uses the same ownership/recording flow as Meta."""
    import uuid
    from datetime import datetime, timezone
    from app.whatsapp import (
        WhatsAppInboundMessage, WhatsAppSendResult, deliver_prepared_whatsapp_reply,
        prepare_whatsapp_inbound,
    )

    workshop_id = _normalize_workshop_id(payload.workshop_id)
    phone = normalize_customer_phone(payload.from_phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Ungültiger WhatsApp-Absender")
    session_id = whatsapp_session_id(phone)
    message_id = "local-test-" + uuid.uuid4().hex
    message = WhatsAppInboundMessage(
        phone_number_id="local-test", display_phone_number=None, from_phone=phone,
        message_id=message_id, timestamp=str(int(datetime.now(timezone.utc).timestamp())),
        message_type="text", text=payload.text, raw={"test_payload": True},
    )
    processed_response = None

    def process():
        nonlocal processed_response
        processed_response = process_chat_message(
            workshop_id=workshop_id, session_id=session_id, message=payload.text,
            channel="whatsapp", phone=phone, message_id="wa:" + message_id,
        )
        return processed_response

    outcome = prepare_whatsapp_inbound(workshop_id=workshop_id, message=message, process_message=process)
    reply = ""
    if outcome["action"] == "reply":
        delivery = deliver_prepared_whatsapp_reply(
            workshop_id=workshop_id, customer_phone=phone, reply_to_wa_message_id=message_id,
            send_message=lambda _: WhatsAppSendResult(True, 200, None, {"local_only": True}),
        )
        if not delivery.get("suppressed_reason"):
            reply = str(outcome["reply"].get("text") or "")
    control = get_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=phone)
    return WhatsAppWebhookResponse(
        reply=reply, done=processed_response.done if processed_response else False,
        session_id=session_id, workshop_id=workshop_id,
        data={**(processed_response.data if processed_response else {}),
              "handling_mode": control["mode"], "conversation_state": control["conversation_state"],
              "active_ticket_id": control.get("active_ticket_id")},
    )


def _save_or_send_whatsapp_reply(
    *,
    workshop_id: str,
    phone_number_id: str,
    customer_phone: str,
    text: str,
    ticket_id: str | None,
    reply_to_wa_message_id: str,
) -> dict:
    from app.whatsapp import WhatsAppSendResult, deliver_prepared_whatsapp_reply

    def send(prepared: dict):
        access_token = str(settings.whatsapp_access_token or "").strip()
        if not access_token:
            if not is_production(settings):
                return WhatsAppSendResult(True, 200, None, {"local_only": True})
            return WhatsAppSendResult(False, 503, None, {}, "WhatsApp access token is missing")
        return send_whatsapp_text_message(
            phone_number_id=str(prepared["phone_number_id"] or ""),
            customer_phone=prepared["customer_phone"],
            text=prepared["text"],
            access_token=access_token,
            graph_api_version=settings.whatsapp_graph_api_version,
        )

    return deliver_prepared_whatsapp_reply(
        workshop_id=workshop_id, customer_phone=customer_phone,
        reply_to_wa_message_id=reply_to_wa_message_id, send_message=send,
    )


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    if is_production(settings) and not settings.whatsapp_app_secret:
        raise HTTPException(status_code=403, detail="WhatsApp webhook is not configured")
    body = await request.body()
    if not verify_signature(
        body,
        request.headers.get("X-Hub-Signature-256"),
        settings.whatsapp_app_secret,
    ):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid WhatsApp payload")

    if "entry" not in payload:
        try:
            test_payload = WhatsAppWebhookRequest.model_validate(payload)
        except ValidationError:
            raise HTTPException(status_code=422, detail="Invalid WhatsApp test payload")
        return _process_test_whatsapp_webhook(test_payload)

    try:
        messages = parse_meta_messages(payload)
        statuses = parse_meta_statuses(payload)
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Invalid WhatsApp payload structure")
    if len(messages) + len(statuses) > 100 or any(len(message.text or "") > MAX_MESSAGE_LENGTH for message in messages):
        raise HTTPException(status_code=413, detail="WhatsApp payload exceeds the input limits")

    processed = 0
    ignored = 0
    status_updates = 0
    manual_pending = 0
    replies: list[dict] = []
    manual_messages: list[dict] = []

    for status_event in statuses:
        workshop_id = find_workshop_id_by_whatsapp_phone_number_id(status_event.phone_number_id)
        if not workshop_id:
            ignored += 1
            continue

        save_whatsapp_event(
            workshop_id=workshop_id,
            phone_number_id=status_event.phone_number_id,
            display_phone_number=status_event.display_phone_number,
            wa_message_id=status_event.wa_message_id,
            from_phone=status_event.recipient_phone,
            event_type="status",
            message_type=status_event.status,
            text=None,
            payload=status_event.raw,
        )

        if update_whatsapp_message_status(
            workshop_id=workshop_id,
            wa_message_id=status_event.wa_message_id,
            status=status_event.status,
            payload=status_event.raw,
        ):
            status_updates += 1
        else:
            ignored += 1

    from app.whatsapp import prepare_whatsapp_inbound
    import json

    for message in messages:
        workshop_id = find_workshop_id_by_whatsapp_phone_number_id(message.phone_number_id)
        if not workshop_id:
            ignored += 1
            continue
        session_id = whatsapp_session_id(message.from_phone)
        try:
            outcome = prepare_whatsapp_inbound(
                workshop_id=workshop_id, message=message,
                process_message=lambda: process_chat_message(
                    workshop_id=workshop_id, session_id=session_id,
                    message=message.text, channel="whatsapp", phone=message.from_phone,
                    message_id="wa:" + message.message_id,
                ),
            )
        except Exception:
            logger.exception("WhatsApp processing failed; the webhook can be retried")
            raise HTTPException(status_code=503, detail="WhatsApp processing temporarily unavailable")
        if outcome["action"] in {"duplicate", "ignored"}:
            ignored += 1
            continue
        if outcome["action"] == "manual":
            manual_pending += 1
            manual_messages.append({
                "message_id": message.message_id, "workshop_id": workshop_id,
                "customer_phone": message.from_phone, "message_type": message.message_type,
                "active_ticket_id": outcome.get("active_ticket_id"), "action": outcome["reason"],
            })
            continue
        prepared = outcome["reply"]
        send_info = _save_or_send_whatsapp_reply(
            workshop_id=workshop_id, phone_number_id=message.phone_number_id,
            customer_phone=message.from_phone, text=prepared["text"],
            ticket_id=prepared["ticket_id"], reply_to_wa_message_id=message.message_id,
        )
        if send_info.get("retry"):
            raise HTTPException(status_code=503, detail="WhatsApp delivery temporarily unavailable")
        if send_info.get("suppressed_reason"):
            manual_pending += 1
            manual_messages.append({
                "message_id": message.message_id, "workshop_id": workshop_id,
                "customer_phone": message.from_phone, "message_type": message.message_type,
                "active_ticket_id": prepared["ticket_id"], "action": send_info["suppressed_reason"],
            })
            continue
        processed += 1
        metadata = json.loads(prepared["payload_json"] or "{}")
        replies.append({
            "message_id": message.message_id, "session_id": session_id,
            "workshop_id": workshop_id, "reply": prepared["text"],
            "done": bool(metadata.get("done")), "send_status": send_info["status"],
            "outbound_wa_message_id": send_info["wa_message_id"],
            "handling_mode": get_whatsapp_conversation_control(
                workshop_id=workshop_id, customer_phone=message.from_phone,
            )["mode"],
            "active_ticket_id": prepared["ticket_id"],
        })

    return {
        "ok": True,
        "processed": processed,
        "ignored": ignored,
        "status_updates": status_updates,
        "manual_pending": manual_pending,
        "manual_messages": manual_messages,
        "replies": replies,
    }


@app.post("/meta/whatsapp")
async def whatsapp_webhook_alt(request: Request):
    return await whatsapp_webhook(request)


class StatusUpdate(BaseModel):
    status: str = Field(..., max_length=32)


@app.get("/")
def root():
    return {
        "ok": True,
        "app": settings.app_name,
        "message": "WerkstattAI läuft 🚀",
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": settings.app_name,
    }


@app.get("/subscription")
def subscription(request: Request, workshop_id: str | None = None):
    return get_subscription(_workshop_id_for_api_request(request, workshop_id))


@app.get("/tickets")
def tickets(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50, workshop_id: str | None = None):
    wid = _workshop_id_for_api_request(request, workshop_id)
    return {
        "items": list_latest_tickets(limit=limit, workshop_id=wid),
        "limit": limit,
        "workshop_id": wid,
    }


@app.get("/tickets/{ticket_id}")
def ticket_by_id(request: Request, ticket_id: str, workshop_id: str | None = None):
    item = find_ticket_by_id(ticket_id, workshop_id=_workshop_id_for_api_request(request, workshop_id))
    if not item:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    return item


@app.patch("/tickets/{ticket_id}/status")
def patch_ticket_status(
    request: Request,
    ticket_id: str,
    payload: StatusUpdate,
    workshop_id: str | None = None,
):
    try:
        normalized_status = _normalize_status(payload.status)
        updated = update_ticket_status(
            ticket_id,
            normalized_status,
            workshop_id=_workshop_id_for_api_request(request, workshop_id),
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request, response: Response) -> ChatResponse:
    # Anonymous /assistant traffic is always demo traffic unless a workshop
    # was explicitly selected through its customer-chat link.
    workshop_id = demo_workshop_id() if payload.workshop_id is None else payload.workshop_id.strip()
    if not workshop_id:
        raise HTTPException(status_code=404, detail="Werkstatt wurde nicht gefunden.")
    result = process_chat_message(
        workshop_id=workshop_id,
        session_id=bound_web_session(request, response, workshop_id, payload.session_id),
        message=payload.message,
        channel=payload.channel,
        phone=payload.phone,
    )
    # The browser needs only workflow status, not the complete persisted state.
    return ChatResponse(reply=result.reply, done=result.done, data={
        key: result.data.get(key) for key in ("step", "mode", "workshop_id", "ticket_id", "request_type", "priority", "conversation_state", "workshop_messages")
    })


# Wrap the complete ASGI application so headers also cover errors and CORS responses.
api = app
app = secure_application(api, settings)
