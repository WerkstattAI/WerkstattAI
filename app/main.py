from __future__ import annotations

import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError

from app.ai_service import polish_reply_de
from app.auth import decode_session_token, is_dashboard_path, login_redirect_url
from app.config import settings
from app.db import (
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
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return user
    return decode_session_token(request.cookies.get("werkstattai_session"))


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


def process_chat_message(
    *,
    workshop_id: str,
    session_id: str,
    message: str | None,
    channel: str,
    phone: str | None = None,
) -> ChatResponse:
    if not is_subscription_active(workshop_id):
        raise HTTPException(
            status_code=402,
            detail="WerkstattAI ist fuer diese Werkstatt nicht aktiv.",
        )

    state = load_session_state(session_id, workshop_id=workshop_id)
    state.workshop_id = workshop_id

    new_state, reply, done = next_step(state, message)
    new_state.workshop_id = workshop_id

    reply = polish_reply_de(reply)

    if done and not new_state.ticket_id:
        new_state.source = channel
        ticket_id = save_ticket(new_state, workshop_id=workshop_id)
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

    return ChatResponse(
        reply=reply,
        done=done,
        data=_dump_state(new_state),
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
    workshop_id = _normalize_workshop_id(payload.workshop_id)
    session_id = whatsapp_session_id(payload.from_phone)
    control = get_whatsapp_conversation_control(
        workshop_id=workshop_id,
        customer_phone=payload.from_phone,
    )
    active_ticket_id = str(control.get("active_ticket_id") or "").strip() or None

    if payload.text:
        save_whatsapp_message(
            workshop_id=workshop_id,
            phone_number_id=None,
            customer_phone=payload.from_phone,
            direction="inbound",
            message_type="text",
            text=payload.text,
            ticket_id=active_ticket_id,
            status="received",
            payload={"test_payload": True},
        )

    if control.get("mode") == "manual":
        return WhatsAppWebhookResponse(
            reply="Nachricht wurde für die manuelle Bearbeitung gespeichert.",
            done=False,
            session_id=session_id,
            workshop_id=workshop_id,
            data={
                "handling_mode": "manual",
                "active_ticket_id": active_ticket_id,
            },
        )

    response = process_chat_message(
        workshop_id=workshop_id,
        session_id=session_id,
        message=payload.text,
        channel="whatsapp",
        phone=payload.from_phone,
    )

    response_ticket_id = _response_ticket_id(response) or active_ticket_id
    save_whatsapp_message(
        workshop_id=workshop_id,
        phone_number_id=None,
        customer_phone=payload.from_phone,
        direction="outbound",
        message_type="text",
        text=response.reply,
        ticket_id=response_ticket_id,
        status="sent_local",
        payload={"test_payload": True},
    )

    return WhatsAppWebhookResponse(
        reply=response.reply,
        done=response.done,
        session_id=session_id,
        workshop_id=workshop_id,
        data=response.data,
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
    access_token = str(settings.whatsapp_access_token or "").strip()
    payload = {
        "source": "webhook",
        "reply_to_wa_message_id": reply_to_wa_message_id,
        "local_only": True,
    }
    status = "sent_local"
    wa_message_id = None
    meta_status_code = None
    meta_error = None

    if access_token and phone_number_id:
        send_result = send_whatsapp_text_message(
            phone_number_id=phone_number_id,
            customer_phone=customer_phone,
            text=text,
            access_token=access_token,
            graph_api_version=settings.whatsapp_graph_api_version,
        )
        status = (
            "sent"
            if send_result.ok
            else ("failed" if send_result.status_code is not None else "unknown")
        )
        wa_message_id = send_result.wa_message_id
        meta_status_code = send_result.status_code
        meta_error = send_result.error
        payload = {
            "source": "webhook",
            "reply_to_wa_message_id": reply_to_wa_message_id,
            "local_only": False,
            "meta_status_code": send_result.status_code,
            "meta_response": send_result.payload,
            "meta_error": send_result.error,
        }

    save_whatsapp_message(
        workshop_id=workshop_id,
        phone_number_id=phone_number_id,
        customer_phone=customer_phone,
        direction="outbound",
        message_type="text",
        text=text,
        wa_message_id=wa_message_id,
        ticket_id=ticket_id,
        status=status,
        payload=payload,
    )

    return {
        "status": status,
        "wa_message_id": wa_message_id,
        "meta_status_code": meta_status_code,
        "meta_error": meta_error,
    }


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

    for message in messages:
        workshop_id = find_workshop_id_by_whatsapp_phone_number_id(message.phone_number_id)
        if not workshop_id:
            ignored += 1
            continue

        save_whatsapp_event(
            workshop_id=workshop_id,
            phone_number_id=message.phone_number_id,
            display_phone_number=message.display_phone_number,
            wa_message_id=message.message_id,
            from_phone=message.from_phone,
            event_type="message",
            message_type=message.message_type,
            text=message.text,
            payload=message.raw,
        )

        control = get_whatsapp_conversation_control(
            workshop_id=workshop_id,
            customer_phone=message.from_phone,
        )
        active_ticket_id = str(control.get("active_ticket_id") or "").strip() or None

        is_new_message = save_whatsapp_message(
            workshop_id=workshop_id,
            phone_number_id=message.phone_number_id,
            customer_phone=message.from_phone,
            direction="inbound",
            message_type=message.message_type,
            text=message.text,
            wa_message_id=message.message_id,
            ticket_id=active_ticket_id,
            status="received",
            payload=message.raw,
        )
        if not is_new_message:
            ignored += 1
            continue

        if control.get("mode") == "manual":
            manual_pending += 1
            manual_messages.append(
                {
                    "message_id": message.message_id,
                    "workshop_id": workshop_id,
                    "customer_phone": message.from_phone,
                    "message_type": message.message_type,
                    "active_ticket_id": active_ticket_id,
                    "action": "saved_for_manual_reply",
                }
            )
            continue

        if message.message_type != "text" or not message.text:
            ignored += 1
            continue

        session_id = whatsapp_session_id(message.from_phone)
        response = process_chat_message(
            workshop_id=workshop_id,
            session_id=session_id,
            message=message.text,
            channel="whatsapp",
            phone=message.from_phone,
        )
        latest_control = get_whatsapp_conversation_control(
            workshop_id=workshop_id,
            customer_phone=message.from_phone,
        )
        if latest_control.get("mode") == "manual":
            manual_pending += 1
            manual_messages.append(
                {
                    "message_id": message.message_id,
                    "workshop_id": workshop_id,
                    "customer_phone": message.from_phone,
                    "message_type": message.message_type,
                    "active_ticket_id": latest_control.get("active_ticket_id"),
                    "action": "manual_takeover_before_assistant_reply",
                }
            )
            continue
        response_ticket_id = _response_ticket_id(response) or active_ticket_id
        send_info = _save_or_send_whatsapp_reply(
            workshop_id=workshop_id,
            phone_number_id=message.phone_number_id,
            customer_phone=message.from_phone,
            text=response.reply,
            ticket_id=response_ticket_id,
            reply_to_wa_message_id=message.message_id,
        )
        if response_ticket_id:
            try:
                set_whatsapp_conversation_control(
                    workshop_id=workshop_id,
                    customer_phone=message.from_phone,
                    mode="assistant",
                    active_ticket_id=response_ticket_id,
                )
            except Exception:
                logger.exception(
                    "Could not persist WhatsApp assistant ticket control for workshop=%s phone=%s",
                    workshop_id,
                    message.from_phone,
                )
        processed += 1
        replies.append(
            {
                "message_id": message.message_id,
                "session_id": session_id,
                "workshop_id": workshop_id,
                "reply": response.reply,
                "done": response.done,
                "send_status": send_info["status"],
                "outbound_wa_message_id": send_info["wa_message_id"],
                "handling_mode": "assistant",
                "active_ticket_id": response_ticket_id,
            }
        )

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
def chat(payload: ChatRequest) -> ChatResponse:
    # Anonymous /assistant traffic is always demo traffic unless a workshop
    # was explicitly selected through its customer-chat link.
    workshop_id = demo_workshop_id() if payload.workshop_id is None else payload.workshop_id.strip()
    if not workshop_id:
        raise HTTPException(status_code=404, detail="Werkstatt wurde nicht gefunden.")
    return process_chat_message(
        workshop_id=workshop_id,
        session_id=payload.session_id,
        message=payload.message,
        channel=payload.channel,
        phone=payload.phone,
    )


# Wrap the complete ASGI application so headers also cover errors and CORS responses.
api = app
app = secure_application(api, settings)
