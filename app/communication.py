"""Shared message semantics; ticket notes are the canonical question ledger."""
from __future__ import annotations

import json
import uuid
from typing import Any


SENDER_ROLES = frozenset({"customer", "assistant", "workshop"})
MESSAGE_PURPOSES = frozenset({
    "intake_question", "automatic_answer", "customer_question", "customer_information",
    "workshop_answer", "workshop_question", "workshop_notification", "internal_note",
})
CONVERSATION_STATES = frozenset({
    "assistant_active", "waiting_for_workshop", "workshop_active", "waiting_for_customer",
})
PURPOSE_SENDERS = {
    "intake_question": "assistant", "automatic_answer": "assistant",
    "customer_question": "customer", "customer_information": "customer",
    "workshop_answer": "workshop", "workshop_question": "workshop",
    "workshop_notification": "workshop", "internal_note": "workshop",
}
STATE_LABELS = {
    "assistant_active": "Assistent aktiv", "waiting_for_workshop": "Wartet auf die Werkstatt",
    "workshop_active": "Werkstatt übernimmt", "waiting_for_customer": "Wartet auf den Kunden",
}
PURPOSE_LABELS = {
    "intake_question": "Auftragsaufnahme", "automatic_answer": "Automatische Antwort",
    "customer_question": "Kundenfrage", "customer_information": "Kundeninformation",
    "workshop_answer": "Antwort der Werkstatt", "workshop_question": "Frage an den Kunden",
    "workshop_notification": "Information der Werkstatt", "internal_note": "Interne Notiz",
}
SENDER_LABELS = {"customer": "Kunde", "assistant": "Assistent", "workshop": "Werkstatt-Team"}


def conversation_mode(state: str) -> str:
    return "assistant" if state == "assistant_active" else "manual"


def legacy_note_type(note: dict[str, Any]) -> str:
    value = str(note.get("type") or "").strip().lower()
    if value in {"internal_note", "customer_message", "customer_reply", "assistant_message"}:
        return value
    if str(note.get("text") or "").strip().lower().startswith("kundenfrage über den chat:"):
        return "customer_message"
    return "internal_note"


def normalize_ticket_notes(
    notes: Any, *, workshop_id: str, ticket_id: str,
    legacy_question_open: bool | None = None,
) -> list[dict[str, Any]]:
    """Add metadata without inventing a semantic reply target for old replies.

    A historical closed aggregate plus a later legacy reply can preserve an old
    closure, explicitly marked uncertain. It never produces a resolved_at or
    reply_to_message_id that the historical data cannot substantiate.
    """
    if not isinstance(notes, list):
        return []
    result = []
    for index, original in enumerate(notes):
        if not isinstance(original, dict):
            continue
        note = dict(original)
        note["text"] = str(note.get("text") or "").strip()
        note["created_at"] = str(note.get("created_at") or "").strip()
        note["type"] = legacy_note_type(note)
        if not note.get("message_id"):
            identity = json.dumps([workshop_id, ticket_id, index, note["text"], note["created_at"]],
                                  ensure_ascii=True, separators=(",", ":"))
            note["message_id"] = "legacy-" + uuid.uuid5(uuid.NAMESPACE_URL, identity).hex
        if note.get("purpose") not in MESSAGE_PURPOSES:
            note["purpose"] = {
                "customer_message": "customer_question", "customer_reply": "workshop_notification",
                "internal_note": "internal_note",
                "assistant_message": "automatic_answer",
            }[note["type"]]
            note["legacy_semantics_uncertain"] = True
        note["sender_role"] = PURPOSE_SENDERS[note["purpose"]]
        note["requires_human_action"] = bool(note.get("requires_human_action",
                                                     note["purpose"] == "customer_question"))
        note.setdefault("reply_to_message_id", None)
        note.setdefault("resolved_at", None)
        result.append(note)

    if legacy_question_open is False:
        last_old_reply = max((index for index, note in enumerate(result)
                              if note["type"] == "customer_reply" and note.get("legacy_semantics_uncertain")),
                             default=-1)
        for index, note in enumerate(result):
            if (index < last_old_reply and note["purpose"] == "customer_question"
                    and note.get("legacy_semantics_uncertain") and not note.get("resolved_at")):
                note["legacy_closed"] = True
                note["legacy_resolution_uncertain"] = True
    return result


def open_customer_questions(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    return [note for note in ticket.get("notes", []) if isinstance(note, dict)
            and note.get("sender_role") == "customer" and note.get("purpose") == "customer_question"
            and note.get("requires_human_action") and not note.get("resolved_at")
            and not note.get("legacy_closed")]


def pending_workshop_question(ticket: dict[str, Any]) -> dict[str, Any] | None:
    notes = ticket.get("notes") or []
    answered = {note.get("reply_to_message_id") for note in notes if isinstance(note, dict)
                and note.get("sender_role") == "customer" and note.get("reply_to_message_id")}
    for note in reversed(notes):
        if (isinstance(note, dict) and note.get("purpose") == "workshop_question"
                and note.get("message_id") not in answered and note.get("delivery_status") != "failed"
                and not note.get("response_cancelled_at")):
            return note
    return None


def validate_workshop_message(
    ticket: dict[str, Any], purpose: str, reply_to_message_id: str | None = None,
) -> str | None:
    if purpose not in {"workshop_answer", "workshop_question", "workshop_notification"}:
        raise ValueError("Bitte den Zweck der Nachricht auswählen.")
    target = str(reply_to_message_id or "").strip() or None
    if purpose != "workshop_answer":
        if target:
            raise ValueError("Ein Antwortziel ist nur bei einer Antwort auf eine Kundenfrage zulässig.")
        return None
    questions = open_customer_questions(ticket)
    if target is None and len(questions) == 1:
        target = questions[0]["message_id"]
    if target is None or not any(note["message_id"] == target for note in questions):
        raise ValueError("Bitte eine konkrete offene Kundenfrage als Antwortziel auswählen.")
    if any(note.get("purpose") == "workshop_answer" and note.get("reply_to_message_id") == target
           and note.get("delivery_status") in {"pending", "unknown"} for note in ticket.get("notes", [])):
        raise ValueError("Für diese Kundenfrage läuft bereits ein Versand oder dessen Ergebnis ist unklar.")
    return target
