from __future__ import annotations

from typing import Tuple

from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.fallback import handle_unclear_request
from app.conversation.general_question import handle_general_question, stored_workshop_answer
from app.conversation.extractors import has_problem_content, lower, normalize, is_cancel_command, extract_phone
from app.workshops import get_workshop
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    INTENT_QUOTE_REQUEST,
    INTENT_UNCLEAR,
    detect_intent,
    has_explicit_new_request_choice,
    has_explicit_ticket_context,
    is_active_intake_step,
    is_active_quote_step,
)
from app.conversation.new_request import handle_new_request, copy_state, fresh_intake_state_from, pending_intake_question
from app.conversation.quote_request import handle_quote_request, pending_quote_question
from app.customer_access import CustomerAccess
from app.models import IntakeState


def next_step(
    state: IntakeState,
    user_message: str | None,
    *,
    customer_access: CustomerAccess | None = None,
    message_id: str | None = None,
) -> Tuple[IntakeState, str, bool]:
    """
    Zentraler Router für alle Konversationen.

    Entscheidet basierend auf Intent:
    - Problem melden (Intake Flow)
    - Anfrage zu einem bestehenden Ticket
    - Allgemeine Frage
    """

    msg = normalize(user_message or "")
    active = not state.ticket_id and (
        (state.mode == "new" and is_active_intake_step(state.step)) or
        (state.mode == "quote" and is_active_quote_step(state.step))
    )
    if active and is_cancel_command(msg):
        return fresh_intake_state_from(state, mode="unknown"), "Die Aufnahme ist abgebrochen. Sie können jederzeit ein neues Anliegen melden.", False
    if active and stored_workshop_answer(msg, {}) is not None:
        answer = stored_workshop_answer(msg, get_workshop(state.workshop_id))
        if answer:
            question = pending_quote_question(state) if state.mode == "quote" else pending_intake_question(state)
            return copy_state(state), answer + "\n\n" + question, False

    if state.pending_request_message:
        pending = state.pending_request_message
        state = copy_state(state)
        state.pending_request_message = None
        if has_explicit_new_request_choice(msg) or lower(msg).strip(" .!?") in {"neu", "neues", "neues ticket"}:
            # Classify the buffered request without the completed intake's mode.
            fresh = fresh_intake_state_from(state, mode="unknown")
            if detect_intent(fresh, pending) == INTENT_QUOTE_REQUEST:
                return handle_quote_request(fresh, pending)
            return handle_new_request(fresh, pending)
        if lower(msg).strip(" .!?") in {"ergänzung", "ergaenzung", "zum bestehenden ticket", "bestehendes ticket"}:
            return handle_existing_ticket(state, pending, customer_access=customer_access, message_id=message_id)
        state.pending_request_message = pending
        return state, "Neues Anliegen oder Ergänzung zum bestehenden Ticket?", False

    intent = detect_intent(state, user_message)
    if (state.ticket_id and intent == INTENT_EXISTING_TICKET and has_problem_content(msg)
            and "?" not in msg and not has_explicit_ticket_context(msg)
            and not any(word in lower(msg) for word in ("ergänz", "ergaenz", "zusätzlich", "zusaetzlich", "auch", "noch"))):
        new_state = copy_state(state)
        new_state.pending_request_message = msg
        return new_state, "Ist das ein neues Anliegen oder eine Ergänzung zum bestehenden Ticket?", False

    if intent == INTENT_NEW_REQUEST:
        return handle_new_request(state, user_message)

    if intent == INTENT_EXISTING_TICKET:
        return handle_existing_ticket(state, user_message, customer_access=customer_access, message_id=message_id)

    if intent == INTENT_GENERAL_QUESTION:
        return handle_general_question(state, user_message)

    if intent == INTENT_QUOTE_REQUEST:
        return handle_quote_request(state, user_message)

    if intent == INTENT_UNCLEAR:
        if extract_phone(msg):
            return copy_state(state), "Möchten Sie ein neues Anliegen melden oder den Status eines bestehenden Tickets abfragen?", False
        return handle_unclear_request(state, user_message)

    return handle_unclear_request(state, user_message)
