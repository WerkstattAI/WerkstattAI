"""Store customer input while a workshop owns the conversation."""
import re

from app.communication import open_customer_questions, pending_workshop_question
from app.tickets import add_ticket_note, set_ticket_conversation_state


def _contains_followup_question(text: str) -> bool:
    """A linked answer needs question wording, not merely a decision keyword."""
    return "?" in text or bool(re.search(
        r"(?:^|[.!;:\n])\s*(?:wie|was|wer|wo|wann|warum|weshalb|wieso|welch\w*|"
        r"kann|könn\w*|koenn\w*|ist|sind|habt|haben|gibt|darf|dürf\w*|duerf\w*|soll|muss)\b",
        text.lower(),
    ))


def receive_customer_message(ticket: dict, text: str, *, workshop_id: str, message_id: str | None = None) -> dict:
    from app.conversation.existing_ticket import _is_customer_question
    pending = pending_workshop_question(ticket) if ticket.get("conversation_state") == "waiting_for_customer" else None
    target = pending.get("message_id") if pending else None
    # Keep broad handoff rules for unlinked input; decision words alone in a
    # linked reply (e.g. a confirmation) do not constitute an additional question.
    is_question = _contains_followup_question(text) if target else _is_customer_question(text)
    result = add_ticket_note(ticket["ticket_id"], text, workshop_id=workshop_id,
                             sender_role="customer", purpose="customer_question" if is_question else "customer_information",
                             requires_human_action=True, reply_to_message_id=target, message_id=message_id)
    if target:
        result = set_ticket_conversation_state(ticket["ticket_id"],
                                               "waiting_for_workshop" if open_customer_questions(result) else "workshop_active",
                                               workshop_id)
    return result
