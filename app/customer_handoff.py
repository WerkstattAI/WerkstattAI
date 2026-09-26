"""Store customer input while a workshop owns the conversation."""
from app.communication import open_customer_questions, pending_workshop_question
from app.tickets import add_ticket_note, set_ticket_conversation_state


def receive_customer_message(ticket: dict, text: str, *, workshop_id: str, message_id: str | None = None) -> dict:
    from app.conversation.existing_ticket import _is_customer_question
    pending = pending_workshop_question(ticket) if ticket.get("conversation_state") == "waiting_for_customer" else None
    target = pending.get("message_id") if pending else None
    is_question = not target and _is_customer_question(text)
    result = add_ticket_note(ticket["ticket_id"], text, workshop_id=workshop_id,
                             sender_role="customer", purpose="customer_question" if is_question else "customer_information",
                             requires_human_action=True, reply_to_message_id=target, message_id=message_id)
    if target:
        result = set_ticket_conversation_state(ticket["ticket_id"],
                                               "waiting_for_workshop" if open_customer_questions(result) else "workshop_active",
                                               workshop_id)
    return result
