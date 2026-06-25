from __future__ import annotations

from typing import Tuple

from app.conversation.constants import (
    STEP_ABSCHLEPPDIENST,
    STEP_BAUJAHR,
    STEP_FAHRBEREIT,
    STEP_FAHRZEUG,
    STEP_FOLLOWUP,
    STEP_KILOMETERSTAND,
    STEP_NAME,
    STEP_PROBLEM,
    STEP_QUOTE_ANLIEGEN,
    STEP_QUOTE_FAHRZEUG,
    STEP_QUOTE_NAME,
    STEP_QUOTE_TELEFON,
    STEP_TELEFON,
)
from app.models import IntakeState


def controlled_fallback_reply() -> str:
    return (
        "Ich bin kein freier KI-Chat, sondern helfe bei Werkstatt-Anfragen.\n\n"
        "Bitte wählen Sie kurz aus, wobei ich helfen soll:\n"
        "- Problem melden\n"
        "- Kostenvoranschlag anfragen\n"
        "- Anfrage zu einem bestehenden Ticket\n"
        "- Allgemeine Frage"
    )


def handle_unclear_request(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:
    active_steps = {
        STEP_FAHRZEUG,
        STEP_BAUJAHR,
        STEP_KILOMETERSTAND,
        STEP_PROBLEM,
        STEP_FAHRBEREIT,
        STEP_ABSCHLEPPDIENST,
        STEP_FOLLOWUP,
        STEP_TELEFON,
        STEP_NAME,
        STEP_QUOTE_ANLIEGEN,
        STEP_QUOTE_FAHRZEUG,
        STEP_QUOTE_TELEFON,
        STEP_QUOTE_NAME,
    }
    if (state.step or "").strip().lower() not in active_steps:
        state.mode = "unknown"
    state.last_user_message = user_message
    return state, controlled_fallback_reply(), False
