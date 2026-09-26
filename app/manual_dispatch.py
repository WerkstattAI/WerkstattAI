"""Durable manual sends: reserve once, pause before HTTP, finalize afterwards."""
from __future__ import annotations

import json
import re
import uuid
from typing import Callable

from app.db import atomic_database, get_whatsapp_conversation_control, set_whatsapp_conversation_control
from app.tickets import (add_ticket_note, find_ticket_by_id, finalize_ticket_message_delivery,
                         set_ticket_conversation_state, validate_workshop_message)
from app.whatsapp import (WhatsAppSendResult, _lock_conversation, save_whatsapp_message,
                          whatsapp_customer_service_window_for_phone)


def send_workshop_message(*, workshop_id: str, customer_phone: str, phone_number_id: str,
                         text: str, purpose: str, reply_to_message_id: str | None,
                         message_id: str | None, ticket_id: str | None,
                         send: Callable[[], WhatsAppSendResult], source: str,
                         user: str | None = None, message_type: str = "text",
                         template_metadata: dict | None = None) -> WhatsAppSendResult:
    mid = message_id or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9:_-]{8,128}", mid):
        raise ValueError("Ungültige Nachrichtenkennung. Bitte das Formular neu öffnen.")
    if purpose not in {"workshop_answer", "workshop_question", "workshop_notification"}:
        raise ValueError("Bitte einen gültigen Nachrichtenzweck auswählen.")
    with atomic_database() as conn:
        _lock_conversation(conn, workshop_id, customer_phone)
        if not ticket_id:
            ticket_id = get_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone).get("active_ticket_id")
        old = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND message_id = ?",
                           (workshop_id, mid)).fetchone()
        if old:
            metadata = json.loads(old["payload_json"] or "{}")
            if (old["customer_phone"] != customer_phone or old["ticket_id"] != ticket_id or
                    old["text"] != text or metadata.get("purpose") != purpose or
                    (reply_to_message_id and metadata.get("reply_to_message_id") != reply_to_message_id)):
                raise ValueError("Diese Nachrichtenkennung wurde bereits für einen anderen Inhalt verwendet.")
            return WhatsAppSendResult(old["status"] in {"sent", "delivered", "read", "sent_local"},
                                      metadata.get("meta_status_code"), old["wa_message_id"],
                                      metadata.get("meta_response") or {},
                                      metadata.get("meta_error") or "Bereits reservierter Versand; nicht erneut gesendet.")
        if conn.execute("SELECT 1 FROM whatsapp_messages WHERE workshop_id = ? AND customer_phone = ? "
                        "AND direction = 'outbound' AND dispatch_state = 'sending' LIMIT 1",
                        (workshop_id, customer_phone)).fetchone():
            raise ValueError("Für diese Unterhaltung läuft bereits ein Versand oder dessen Abschluss ist unklar. Bitte zuerst den Verlauf prüfen.")
        if message_type == "text" and not whatsapp_customer_service_window_for_phone(workshop_id=workshop_id, customer_phone=customer_phone)["service_window_open"]:
            raise ValueError("Das 24-Stunden-Kundenfenster ist geschlossen. Bitte eine freigegebene Vorlage verwenden.")
        ticket = find_ticket_by_id(ticket_id, workshop_id) if ticket_id else None
        if ticket_id and not ticket:
            raise ValueError("Ticket wurde nicht gefunden.")
        target = validate_workshop_message(ticket, purpose=purpose, reply_to_message_id=reply_to_message_id) if ticket else None
        if not ticket and purpose == "workshop_answer":
            raise ValueError("Eine Antwort benötigt eine konkrete offene Kundenfrage in einem Ticket.")
        previous = get_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone)
        previous_ticket_state = ticket.get("conversation_state") if ticket else None
        set_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone,
                                          conversation_state="workshop_active", active_ticket_id=ticket_id or previous.get("active_ticket_id"))
        if ticket:
            add_ticket_note(ticket_id, text, workshop_id=workshop_id, sender_role="workshop", purpose=purpose,
                            message_id=mid, reply_to_message_id=target, delivery_status="pending")
        elif purpose == "workshop_question":
            set_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone,
                                              conversation_state="waiting_for_customer", pending_workshop_question_id=mid)
        claim = get_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone)
        metadata = {"source": source, "user": user, "message_id": mid, "sender_role": "workshop", "purpose": purpose,
                    "requires_human_action": False, "reply_to_message_id": target, "resolved_at": None}
        metadata.update(template_metadata or {})
        save_whatsapp_message(workshop_id=workshop_id, customer_phone=customer_phone, phone_number_id=phone_number_id,
                              direction="outbound", text=text, ticket_id=ticket_id, status="unknown", message_id=mid,
                              dispatch_state="sending", payload=metadata, message_type=message_type)
    try:
        result = send()
    except Exception as exc:
        result = WhatsAppSendResult(False, None, None, {}, str(exc))
    status = "sent" if result.ok else ("failed" if result.status_code is not None else "unknown")
    with atomic_database() as conn:
        _lock_conversation(conn, workshop_id, customer_phone)
        current = get_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone)
        if ticket:
            finalize_ticket_message_delivery(ticket_id, mid, status, workshop_id=workshop_id)
        metadata.update(meta_status_code=result.status_code, meta_response=result.payload, meta_error=result.error)
        conn.execute("UPDATE whatsapp_messages SET wa_message_id = ?, status = ?, dispatch_state = 'complete', payload_json = ? "
                     "WHERE workshop_id = ? AND message_id = ?",
                     (result.wa_message_id, status, json.dumps(metadata, ensure_ascii=False), workshop_id, mid))
        # A failure must not undo a newer employee action or a customer response.
        if status == "failed" and current["revision"] == claim["revision"]:
            if ticket and previous_ticket_state:
                set_ticket_conversation_state(ticket_id, previous_ticket_state, workshop_id)
            set_whatsapp_conversation_control(workshop_id=workshop_id, customer_phone=customer_phone,
                                              conversation_state=previous["conversation_state"],
                                              active_ticket_id=previous.get("active_ticket_id"),
                                              pending_workshop_question_id=previous.get("pending_workshop_question_id"))
    return result
