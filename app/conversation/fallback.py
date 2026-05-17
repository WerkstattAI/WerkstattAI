from __future__ import annotations

from typing import Tuple

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
    state.mode = "unknown"
    state.last_user_message = user_message
    return state, controlled_fallback_reply(), False
