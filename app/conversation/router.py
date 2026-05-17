from __future__ import annotations

from typing import Tuple

from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.fallback import handle_unclear_request
from app.conversation.general_question import handle_general_question
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    INTENT_QUOTE_REQUEST,
    INTENT_UNCLEAR,
    detect_intent,
)
from app.conversation.new_request import handle_new_request
from app.conversation.quote_request import handle_quote_request
from app.models import IntakeState


def next_step(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:
    """
    Zentraler Router für alle Konversationen.

    Entscheidet basierend auf Intent:
    - Problem melden (Intake Flow)
    - Anfrage zu einem bestehenden Ticket
    - Allgemeine Frage
    """

    intent = detect_intent(state, user_message)

    if intent == INTENT_NEW_REQUEST:
        return handle_new_request(state, user_message)

    if intent == INTENT_EXISTING_TICKET:
        return handle_existing_ticket(state, user_message)

    if intent == INTENT_GENERAL_QUESTION:
        return handle_general_question(state, user_message)

    if intent == INTENT_QUOTE_REQUEST:
        return handle_quote_request(state, user_message)

    if intent == INTENT_UNCLEAR:
        return handle_unclear_request(state, user_message)

    return handle_unclear_request(state, user_message)
