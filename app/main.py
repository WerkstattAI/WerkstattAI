from __future__ import annotations

from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.ai_service import polish_reply_de
from app.config import settings
from app.db import init_db
from app.logic import next_step
from app.models import ChatRequest, ChatResponse, IntakeState
from app.tickets import (
    find_ticket_by_id,
    list_latest_tickets,
    save_ticket,
    update_ticket_status,
)
from app.web import router as web_router


app = FastAPI(title=settings.app_name)

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


SESSIONS: Dict[str, IntakeState] = {}


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
def tickets(limit: int = 50):
    return {
        "items": list_latest_tickets(limit=limit),
        "limit": limit,
    }


@app.get("/tickets/{ticket_id}")
def ticket_by_id(ticket_id: str):
    item = find_ticket_by_id(ticket_id)
    if not item:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")
    return item


@app.patch("/tickets/{ticket_id}/status")
def patch_ticket_status(ticket_id: str, payload: StatusUpdate):
    try:
        normalized_status = _normalize_status(payload.status)
        updated = update_ticket_status(ticket_id, normalized_status)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Ticket nicht gefunden")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    state = SESSIONS.get(payload.session_id, IntakeState())

    new_state, reply, done = next_step(state, payload.message)

    reply = polish_reply_de(reply)

    if done and not new_state.ticket_id:
        ticket_id = save_ticket(new_state)
        new_state.ticket_id = ticket_id
        reply = (
            reply
            + f"\n\nTicket-Nr.: **{ticket_id}**\n"
            + "Bitte notieren Sie sich diese Nummer für Rückfragen."
        )

    SESSIONS[payload.session_id] = new_state

    return ChatResponse(
        reply=reply,
        done=done,
        data=_dump_state(new_state),
    )