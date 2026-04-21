from __future__ import annotations

from typing import Tuple

from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.general_question import handle_general_question
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    detect_intent,
)
from app.conversation.new_request import handle_new_request
from app.models import IntakeState


def next_step(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:
    """
    Zentraler Router für alle Konversationen.

    Entscheidet basierend auf Intent:
    - Neue Anfrage (Intake Flow)
    - Bestehendes Ticket
    - Allgemeine Frage
    """

    intent = detect_intent(state, user_message)

    if intent == INTENT_NEW_REQUEST:
        return handle_new_request(state, user_message)

    if intent == INTENT_EXISTING_TICKET:
        return handle_existing_ticket(state, user_message)

    if intent == INTENT_GENERAL_QUESTION:
        return handle_general_question(state, user_message)

    # Fallback → neue Anfrage
    return handle_new_request(state, user_message)