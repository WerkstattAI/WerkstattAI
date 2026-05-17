from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.ai_service import polish_reply_de
from app.auth import decode_session_token, is_dashboard_path, login_redirect_url
from app.config import settings
from app.db import default_workshop_id, init_db
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
from app.web import router as web_router


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title=settings.app_name,
    default_response_class=UTF8JSONResponse,
)

# ✅ NOWE — inicjalizacja bazy SQLite
@app.on_event("startup")
def on_startup():
    init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _normalize_phone_for_session(phone: str | None) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def whatsapp_session_id(phone: str | None) -> str:
    normalized_phone = _normalize_phone_for_session(phone)
    return f"whatsapp:{normalized_phone or 'unknown'}"


def process_chat_message(
    *,
    workshop_id: str,
    session_id: str,
    message: str | None,
    channel: str,
    phone: str | None = None,
) -> ChatResponse:
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


@app.post("/webhooks/whatsapp", response_model=WhatsAppWebhookResponse)
def whatsapp_webhook(payload: WhatsAppWebhookRequest) -> WhatsAppWebhookResponse:
    workshop_id = _normalize_workshop_id(payload.workshop_id)
    session_id = whatsapp_session_id(payload.from_phone)

    response = process_chat_message(
        workshop_id=workshop_id,
        session_id=session_id,
        message=payload.text,
        channel="whatsapp",
        phone=payload.from_phone,
    )

    return WhatsAppWebhookResponse(
        reply=response.reply,
        done=response.done,
        session_id=session_id,
        workshop_id=workshop_id,
        data=response.data,
    )


class StatusUpdate(BaseModel):
    status: str


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


@app.get("/tickets")
def tickets(limit: int = 50, workshop_id: str | None = None):
    wid = _normalize_workshop_id(workshop_id)
    return {
        "items": list_latest_tickets(limit=limit, workshop_id=wid),
        "limit": limit,
        "workshop_id": wid,
    }


@app.get("/tickets/{ticket_id}")
def ticket_by_id(ticket_id: str, workshop_id: str | None = None):
    item = find_ticket_by_id(ticket_id, workshop_id=_normalize_workshop_id(workshop_id))
    if not item:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    return item


@app.patch("/tickets/{ticket_id}/status")
def patch_ticket_status(ticket_id: str, payload: StatusUpdate, workshop_id: str | None = None):
    try:
        normalized_status = _normalize_status(payload.status)
        updated = update_ticket_status(
            ticket_id,
            normalized_status,
            workshop_id=_normalize_workshop_id(workshop_id),
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    workshop_id = _normalize_workshop_id(payload.workshop_id)
    return process_chat_message(
        workshop_id=workshop_id,
        session_id=payload.session_id,
        message=payload.message,
        channel=payload.channel,
        phone=payload.phone,
    )
