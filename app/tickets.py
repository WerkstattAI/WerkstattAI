from __future__ import annotations

import json
import uuid
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, Optional

from app.db import atomic_database, default_workshop_id, get_conn, is_postgres, lock_communication_scope
from app.models import IntakeState
from app.communication import (
    CONVERSATION_STATES, MESSAGE_PURPOSES, PURPOSE_SENDERS, conversation_mode,
    normalize_ticket_notes, open_customer_questions, pending_workshop_question,
    validate_workshop_message,
)


ALLOWED_STATUS = {"offen", "in_bearbeitung", "erledigt", "archiviert"}
ALLOWED_PRIORITY = {"niedrig", "normal", "hoch"}
ALLOWED_REQUEST_TYPE = {"service", "diagnose", "notfall", "kostenvoranschlag"}
ALLOWED_NOTE_TYPE = {"internal_note", "customer_message", "customer_reply", "assistant_message"}
ALLOWED_SOURCE = {"web_chat", "whatsapp", "direktannahme"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_status(value: Any) -> str:
    """
    Vereinheitlicht Statuswerte aus alten und neuen Versionen.
    """
    status = str(value or "").strip().lower()

    if status == "geschlossen":
        return "erledigt"

    if status in ALLOWED_STATUS:
        return status

    return "offen"


def _normalize_priority(value: Any) -> str:
    """
    Neue Prioritäten:
    - niedrig
    - normal
    - hoch

    Alte Fallbacks:
    - dringend -> hoch
    - notfall -> hoch
    """
    priority = str(value or "").strip().lower()

    if priority == "dringend":
        return "hoch"

    if priority == "notfall":
        return "hoch"

    if priority in ALLOWED_PRIORITY:
        return priority

    return "normal"


def _normalize_request_type(value: Any) -> Optional[str]:
    request_type = str(value or "").strip().lower()

    if request_type in ALLOWED_REQUEST_TYPE:
        return request_type

    return None


def _normalize_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    if source in ALLOWED_SOURCE:
        return source
    return "web_chat"


def _safe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default

    if isinstance(value, (list, dict)):
        return value

    text = str(value).strip()
    if not text:
        return default

    try:
        return json.loads(text)
    except Exception:
        return default


def _normalize_note_type(value: Any, text: str = "") -> str:
    note_type = str(value or "").strip().lower()
    if note_type in ALLOWED_NOTE_TYPE:
        return note_type

    normalized_text = str(text or "").strip().lower()
    if normalized_text.startswith("kundenfrage über den chat:"):
        return "customer_message"

    return "internal_note"


def _normalize_note(note: dict[str, Any]) -> dict[str, Any]:
    text = str(note.get("text", "")).strip()
    created_at = str(note.get("created_at", "") or "").strip() or _now_iso()

    return {
        **note,
        "type": _normalize_note_type(note.get("type"), text),
        "text": text,
        "created_at": created_at,
    }


def _bool_to_db(value: Any) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"ja", "yes", "true", "1"}:
            return 1
        if normalized in {"nein", "no", "false", "0"}:
            return 0

    return 1 if bool(value) else 0


def _db_to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _normalize_ticket_record(obj: dict[str, Any]) -> dict[str, Any]:
    """
    Stellt sicher, dass Tickets immer Kernfelder haben,
    auch wenn sie aus älteren Versionen stammen.
    """
    obj = dict(obj)

    ticket_id = str(
        obj.get("ticket_id")
        or obj.get("_id")
        or obj.get("id")
        or ""
    ).strip()

    if ticket_id:
        obj["ticket_id"] = ticket_id

    obj["workshop_id"] = str(obj.get("workshop_id") or default_workshop_id()).strip() or default_workshop_id()

    if not obj.get("created_at"):
        obj["created_at"] = _now_iso()

    if not obj.get("updated_at"):
        obj["updated_at"] = obj["created_at"]

    obj["status"] = _normalize_status(obj.get("status"))
    obj["priority"] = _normalize_priority(obj.get("priority"))
    obj["request_type"] = _normalize_request_type(obj.get("request_type"))
    obj["source"] = _normalize_source(obj.get("source"))
    legacy_question_open = bool(obj.get("customer_question_open"))

    if obj.get("followup_questions") is None or not isinstance(obj.get("followup_questions"), list):
        obj["followup_questions"] = []

    if obj.get("followup_answers") is None or not isinstance(obj.get("followup_answers"), list):
        obj["followup_answers"] = []

    if obj.get("notes") is None or not isinstance(obj.get("notes"), list):
        obj["notes"] = []
    else:
        obj["notes"] = normalize_ticket_notes(obj["notes"], workshop_id=obj["workshop_id"],
                                               ticket_id=ticket_id, legacy_question_open=legacy_question_open)
    obj["customer_question_open"] = bool(open_customer_questions(obj))
    obj["open_customer_questions"] = open_customer_questions(obj)
    obj["conversation_state"] = str(obj.get("conversation_state") or "assistant_active")

    if not obj.get("kunde_name") and obj.get("name"):
        obj["kunde_name"] = obj.get("name")

    if not obj.get("name") and obj.get("kunde_name"):
        obj["name"] = obj.get("kunde_name")

    return obj


def _row_to_ticket_dict(row: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "workshop_id": row["workshop_id"],
        "ticket_id": row["ticket_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "priority": row["priority"],
        "request_type": row["request_type"],
        "source": row["source"],
        "customer_question_open": _db_to_bool(row["customer_question_open"]),
        "conversation_state": row["conversation_state"],
        "fahrzeug": row["fahrzeug"],
        "baujahr": row["baujahr"],
        "kilometerstand": row["kilometerstand"],
        "fahrbereit": _db_to_bool(row["fahrbereit"]),
        "abschleppdienst": _db_to_bool(row["abschleppdienst"]),
        "problem": row["problem"],
        "name": row["name"],
        "kunde_name": row["kunde_name"],
        "telefon": row["telefon"],
        "verified_customer_phone": row["verified_customer_phone"],
        "followup_questions": _safe_json_loads(row["followup_questions_json"], []),
        "followup_answers": _safe_json_loads(row["followup_answers_json"], []),
        "notes": _safe_json_loads(row["notes_json"], []),
    }

    return _normalize_ticket_record(obj)


def _next_sequence_for_today(today: str) -> int:
    """Reserve a number atomically across threads and application processes.

    Seed a new day's counter from existing tickets for backwards compatibility.
    Committing the reservation before inserting the ticket allows harmless gaps,
    but prevents two requests from receiving the same number.
    """
    with closing(get_conn()) as conn:
        existing = conn.execute(
            """
            SELECT last_value FROM ticket_sequences WHERE ticket_date = ?
            """,
            (today,),
        ).fetchone()
        initial_value = 1
        if existing is None:
            prefix = f"WS-{today}-"
            rows = conn.execute(
                "SELECT ticket_id FROM tickets WHERE ticket_id LIKE ?",
                (prefix + "%",),
            ).fetchall()
            numbers = [
                int(str(row["ticket_id"])[len(prefix):])
                for row in rows
                if str(row["ticket_id"])[len(prefix):].isascii()
                and str(row["ticket_id"])[len(prefix):].isdigit()
            ]
            initial_value = max(numbers, default=0) + 1

        row = conn.execute(
            """
            INSERT INTO ticket_sequences (ticket_date, last_value)
            VALUES (?, ?)
            ON CONFLICT(ticket_date) DO UPDATE SET
                last_value = ticket_sequences.last_value + 1
            RETURNING last_value
            """,
            (today, initial_value),
        ).fetchone()
        conn.commit()
    return int(row["last_value"])


def generate_ticket_id(workshop_id: str | None = None) -> str:
    """
    Format: WS-YYYYMMDD-0001
    """
    today = datetime.now().strftime("%Y%m%d")

    seq = _next_sequence_for_today(today)
    return f"WS-{today}-{seq:04d}"


def save_ticket(state: IntakeState, workshop_id: str | None = None, *, verified_customer_phone: str | None = None) -> str:
    """
    Speichert ein Ticket in SQLite
    und gibt die ticket_id zurück.
    """
    wid = str(workshop_id or state.workshop_id or default_workshop_id()).strip() or default_workshop_id()
    state.workshop_id = wid
    ticket_id = state.ticket_id or generate_ticket_id(wid)
    now_iso = _now_iso()
    kunde_name = state.name

    record: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "workshop_id": wid,
        "created_at": now_iso,
        "updated_at": now_iso,

        # Workflow
        "status": "offen",
        "request_type": _normalize_request_type(state.request_type),
        "priority": _normalize_priority(state.priority),
        "source": _normalize_source(state.source),
        "customer_question_open": False,

        # Fahrzeugdaten
        "fahrzeug": state.fahrzeug,
        "baujahr": state.baujahr,
        "kilometerstand": state.kilometerstand,

        # Fahrzustand
        "fahrbereit": state.fahrbereit,
        "abschleppdienst": state.abschleppdienst,

        # Problem
        "problem": state.problem,

        # Follow-ups
        "followup_questions": state.followup_questions or [],
        "followup_answers": state.followup_answers or [],

        # Interne Notizen
        "notes": [],

        # Kontakt
        "name": kunde_name,
        "kunde_name": kunde_name,
        "telefon": state.telefon,
    }

    record = _normalize_ticket_record(record)

    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO tickets (
                workshop_id,
                ticket_id,
                created_at,
                updated_at,
                status,
                priority,
                request_type,
                source,
                customer_question_open,
                fahrzeug,
                baujahr,
                kilometerstand,
                fahrbereit,
                abschleppdienst,
                problem,
                name,
                kunde_name,
                telefon,
                followup_questions_json,
                followup_answers_json,
                notes_json,
                verified_customer_phone
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["workshop_id"],
                record["ticket_id"],
                record["created_at"],
                record["updated_at"],
                record["status"],
                record["priority"],
                record["request_type"],
                record["source"],
                _bool_to_db(record["customer_question_open"]),
                record["fahrzeug"],
                record["baujahr"],
                record["kilometerstand"],
                _bool_to_db(record["fahrbereit"]),
                _bool_to_db(record["abschleppdienst"]),
                record["problem"],
                record["name"],
                record["kunde_name"],
                record["telefon"],
                json.dumps(record["followup_questions"], ensure_ascii=False),
                json.dumps(record["followup_answers"], ensure_ascii=False),
                json.dumps(record["notes"], ensure_ascii=False),
                verified_customer_phone,
            ),
        )
        conn.commit()

    return ticket_id


def load_all_tickets(workshop_id: str | None = None) -> list[dict[str, Any]]:
    """
    Lädt alle Tickets aus SQLite.
    """
    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (wid,),
        ).fetchall()

    return [_row_to_ticket_dict(row) for row in rows]


def list_latest_tickets(limit: int = 50, workshop_id: str | None = None) -> list[dict[str, Any]]:
    """
    Gibt die neuesten Tickets zurück.
    Hard-Limit: 500
    """
    safe_limit = max(0, min(int(limit), 500))
    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (wid, safe_limit),
        ).fetchall()

    return [_row_to_ticket_dict(row) for row in rows]


def normalize_phone_for_search(phone: str) -> str:
    """
    Normalisiert Telefonnummern für tolerante Suche:
    - entfernt Leerzeichen, Bindestriche, Klammern usw.
    - behält nur Ziffern
    """
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())

    if digits.startswith("00") and len(digits) > 4:
        digits = digits[2:]

    if digits.startswith("49") and len(digits) >= 10:
        return digits

    if digits.startswith("0") and len(digits) >= 8:
        return f"49{digits[1:]}"

    # Deutsche Mobilnummern werden oft ohne fuehrende 0 notiert.
    if digits.startswith(("15", "16", "17")) and 10 <= len(digits) <= 11:
        return f"49{digits}"

    return digits


def find_tickets_by_phone(phone: str, workshop_id: str | None = None) -> list[dict[str, Any]]:
    """
    Sucht Tickets tolerant anhand der Telefonnummer.

    Beispiele:
    - 0176 1234567
    - 0176-1234567
    - +49 176 1234567

    Für MVP laden wir passende Kandidaten aus SQLite
    und vergleichen dann normalisiert in Python.
    """
    normalized_query = normalize_phone_for_search(phone)
    if len(normalized_query) < 7:
        return []

    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ? AND telefon IS NOT NULL
            ORDER BY created_at DESC, id DESC
            """,
            (wid,),
        ).fetchall()

    matches: list[dict[str, Any]] = []

    for row in rows:
        ticket = _row_to_ticket_dict(row)
        ticket_phone = normalize_phone_for_search(ticket.get("telefon", ""))

        if not ticket_phone:
            continue

        if (
            ticket_phone == normalized_query
            or normalized_query in ticket_phone
            or ticket_phone in normalized_query
        ):
            matches.append(ticket)

    return matches


def find_latest_ticket_by_phone(phone: str, workshop_id: str | None = None) -> Optional[dict[str, Any]]:
    """
    Gibt das neueste Ticket zu einer Telefonnummer zurück.
    """
    matches = find_tickets_by_phone(phone, workshop_id=workshop_id)
    return matches[0] if matches else None


def find_ticket_by_id(ticket_id: str, workshop_id: str | None = None) -> Optional[dict[str, Any]]:
    """
    Sucht ein Ticket anhand der Ticket-ID.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        return None

    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()

    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ? AND ticket_id = ?
            LIMIT 1
            """,
            (wid, tid),
        ).fetchone()

    if not row:
        return None

    return _row_to_ticket_dict(row)


def update_ticket_status(ticket_id: str, new_status: str, workshop_id: str | None = None) -> dict[str, Any]:
    """
    Aktualisiert den Ticket-Status und updated_at in SQLite.
    Gibt das aktualisierte Ticket zurück.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        raise ValueError("ticket_id ist leer")

    status = _normalize_status(new_status)
    if status not in ALLOWED_STATUS:
        raise ValueError(f"Ungültiger Status: {new_status}")

    now_iso = _now_iso()
    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()

    with closing(get_conn()) as conn:
        cur = conn.execute(
            """
            UPDATE tickets
            SET status = ?, updated_at = ?
            WHERE workshop_id = ? AND ticket_id = ?
            """,
            (status, now_iso, wid, tid),
        )

        if cur.rowcount == 0:
            raise KeyError("Ticket nicht gefunden")

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ? AND ticket_id = ?
            LIMIT 1
            """,
            (wid, tid),
        ).fetchone()

    if not row:
        raise KeyError("Ticket nicht gefunden")

    return _row_to_ticket_dict(row)


def add_ticket_note(
    ticket_id: str,
    note_text: str,
    note_type: str = "internal_note",
    workshop_id: str | None = None,
    *,
    sender_role: str | None = None,
    purpose: str | None = None,
    requires_human_action: bool | None = None,
    message_id: str | None = None,
    reply_to_message_id: str | None = None,
    delivery_status: str | None = None,
) -> dict[str, Any]:
    """Append one semantic message, resolving only an explicitly targeted question."""
    tid = (ticket_id or "").strip()
    text = (note_text or "").strip()

    if not tid:
        raise ValueError("ticket_id ist leer")

    if not text:
        raise ValueError("note_text ist leer")

    now_iso = _now_iso()
    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()
    normalized_note_type = _normalize_note_type(note_type, text)
    purpose = purpose or {"internal_note": "internal_note", "customer_message": "customer_question",
                          "customer_reply": "workshop_notification", "assistant_message": "automatic_answer"}[normalized_note_type]
    if purpose not in MESSAGE_PURPOSES:
        raise ValueError("Ungültiger Nachrichtenzweck")
    sender_role = sender_role or PURPOSE_SENDERS[purpose]
    if sender_role != PURPOSE_SENDERS[purpose]:
        raise ValueError("Absender und Nachrichtenzweck passen nicht zusammen")
    normalized_note_type = ("internal_note" if purpose == "internal_note" else
                            {"customer": "customer_message", "workshop": "customer_reply",
                             "assistant": "assistant_message"}[sender_role])
    if delivery_status not in {None, "pending", "sent", "unknown", "failed"}:
        raise ValueError("Ungültiger Versandstatus")
    if delivery_status and sender_role != "workshop":
        raise ValueError("Versandstatus ist nur für Werkstattnachrichten zulässig")
    if purpose == "customer_question" and requires_human_action is False:
        raise ValueError("Eine offene Kundenfrage erfordert eine Werkstattaktion")
    requires_human_action = (purpose == "customer_question" if requires_human_action is None
                             else bool(requires_human_action))
    mid = str(message_id or uuid.uuid4().hex).strip()
    if not mid or len(mid) > 256:
        raise ValueError("Ungültige Nachrichten-ID")

    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        row = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ? AND ticket_id = ?
            LIMIT 1
            """ + (" FOR UPDATE" if is_postgres() else ""),
            (wid, tid),
        ).fetchone()

        if not row:
            raise KeyError("Ticket nicht gefunden")

        ticket = _row_to_ticket_dict(row)
        notes = ticket["notes"]
        for existing in notes:
            if existing["message_id"] == mid:
                if (existing["text"] != text or existing["purpose"] != purpose
                        or existing["sender_role"] != sender_role
                        or (reply_to_message_id and existing.get("reply_to_message_id") != reply_to_message_id)):
                    raise ValueError("Nachrichten-ID wurde bereits für eine andere Nachricht verwendet")
                return ticket
        target = str(reply_to_message_id or "").strip() or None
        if sender_role == "workshop" and purpose != "internal_note":
            target = validate_workshop_message(ticket, purpose, target)
        elif target:
            target_note = next((note for note in notes if note["message_id"] == target), None)
            if target_note is None:
                raise ValueError("Antwortziel gehört nicht zu diesem Ticket")
            if sender_role == "customer" and (target_note["purpose"] != "workshop_question"
                                               or target_note.get("delivery_status") == "failed"
                                               or target_note.get("response_cancelled_at")):
                raise ValueError("Kundenantwort benötigt eine Werkstattfrage als Ziel")
            if sender_role == "customer" and any(note.get("sender_role") == "customer"
                                                 and note.get("reply_to_message_id") == target for note in notes):
                raise ValueError("Diese Werkstattfrage wurde bereits beantwortet")

        note = {"type": normalized_note_type, "text": text, "created_at": now_iso,
                "message_id": mid, "sender_role": sender_role, "purpose": purpose,
                "requires_human_action": requires_human_action, "reply_to_message_id": target,
                "resolved_at": None}
        if delivery_status:
            note["delivery_status"] = delivery_status
        notes.append(note)
        if purpose == "workshop_answer" and delivery_status in {None, "sent"}:
            next(item for item in notes if item["message_id"] == target)["resolved_at"] = now_iso
        state = ticket["conversation_state"]
        if purpose == "workshop_question" and delivery_status != "failed":
            state = "waiting_for_customer"
        elif sender_role == "workshop" and purpose != "internal_note" and delivery_status != "failed":
            state = ("waiting_for_customer" if pending_workshop_question(ticket) else
                     "waiting_for_workshop" if open_customer_questions(ticket) else "workshop_active")
        elif sender_role == "customer" and target:
            state = "waiting_for_workshop" if open_customer_questions(ticket) else "workshop_active"
        elif sender_role == "customer" and requires_human_action:
            state = "waiting_for_workshop"

        conn.execute(
            """
            UPDATE tickets
            SET notes_json = ?, updated_at = ?, customer_question_open = ?
            WHERE workshop_id = ? AND ticket_id = ?
            """,
            (
                json.dumps(notes, ensure_ascii=False),
                now_iso,
                _bool_to_db(bool(open_customer_questions(ticket))),
                wid,
                tid,
            ),
        )
        _set_ticket_state_in_transaction(conn, wid, tid, state)
        conn.commit()

        updated_row = conn.execute(
            """
            SELECT *
            FROM tickets
            WHERE workshop_id = ? AND ticket_id = ?
            LIMIT 1
            """,
            (wid, tid),
        ).fetchone()

    if not updated_row:
        raise KeyError("Ticket nicht gefunden")

    return _row_to_ticket_dict(updated_row)


def _set_ticket_state_in_transaction(conn, workshop_id: str, ticket_id: str, state: str) -> None:
    if state not in CONVERSATION_STATES:
        raise ValueError("Ungültiger Gesprächszustand")
    previous = conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?",
                            (workshop_id, ticket_id)).fetchone()
    if not previous:
        raise KeyError("Ticket nicht gefunden")
    if state == "assistant_active":
        sending = conn.execute("""SELECT 1 FROM whatsapp_messages
                                  WHERE workshop_id = ? AND direction = 'outbound' AND dispatch_state = 'sending'
                                    AND (ticket_id = ? OR customer_phone IN (
                                        SELECT customer_phone FROM whatsapp_conversation_controls
                                        WHERE workshop_id = ? AND active_ticket_id = ?)) LIMIT 1""",
                               (workshop_id, ticket_id, workshop_id, ticket_id)).fetchone()
        if sending:
            raise ValueError("Eine Nachricht wird gerade versendet. Bitte danach den Assistenten aktivieren.")
        ticket = _row_to_ticket_dict(previous)
        answered = {note.get("reply_to_message_id") for note in ticket["notes"]
                    if note.get("sender_role") == "customer" and note.get("reply_to_message_id")}
        changed = False
        for note in ticket["notes"]:
            if (note["purpose"] == "workshop_question" and note["message_id"] not in answered
                    and not note.get("response_cancelled_at")):
                note["response_cancelled_at"] = _now_iso()
                changed = True
        if changed:
            conn.execute("UPDATE tickets SET notes_json = ? WHERE workshop_id = ? AND ticket_id = ?",
                         (json.dumps(ticket["notes"], ensure_ascii=False), workshop_id, ticket_id))
    if previous["conversation_state"] == state:
        return
    conn.execute("UPDATE tickets SET conversation_state = ?, updated_at = ? WHERE workshop_id = ? AND ticket_id = ?",
                 (state, _now_iso(), workshop_id, ticket_id))
    # Existing transport controls are a compatibility projection. Their revision
    # invalidates a prepared assistant send whenever canonical ownership changes.
    conn.execute("""UPDATE whatsapp_conversation_controls
                    SET conversation_state = ?, mode = ?, revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE workshop_id = ? AND active_ticket_id = ?""",
                 (state, conversation_mode(state), workshop_id, ticket_id))


def resolve_customer_information(ticket_id: str, message_id: str, workshop_id: str,
                                 *, user: str | None = None) -> dict[str, Any]:
    """Mark one reviewed customer information item, never a question or repair."""
    with atomic_database() as conn:
        lock_communication_scope(conn, workshop_id)
        row = conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?"
                           + (" FOR UPDATE" if is_postgres() else ""), (workshop_id, ticket_id)).fetchone()
        if not row:
            raise KeyError("Ticket nicht gefunden")
        ticket = _row_to_ticket_dict(row)
        note = next((note for note in ticket["notes"] if note["message_id"] == message_id), None)
        if (not note or note.get("sender_role") != "customer"
                or note.get("purpose") != "customer_information" or not note.get("requires_human_action")):
            raise ValueError("Nur eine Kundeninformation zur Bearbeitung kann bestätigt werden.")
        if not note.get("resolved_at"):
            now = _now_iso()
            note["resolved_at"] = now
            note["resolved_by"] = user
            conn.execute("UPDATE tickets SET notes_json = ?, updated_at = ? WHERE workshop_id = ? AND ticket_id = ?",
                         (json.dumps(ticket["notes"], ensure_ascii=False), now, workshop_id, ticket_id))
    return find_ticket_by_id(ticket_id, workshop_id)


def set_ticket_conversation_state(ticket_id: str, state: str, workshop_id: str | None = None) -> dict[str, Any]:
    wid = str(workshop_id or default_workshop_id()).strip()
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        row = conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?" +
                           (" FOR UPDATE" if is_postgres() else ""), (wid, ticket_id)).fetchone()
        if not row:
            raise KeyError("Ticket nicht gefunden")
        _set_ticket_state_in_transaction(conn, wid, ticket_id, state)
        return _row_to_ticket_dict(conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?",
                                               (wid, ticket_id)).fetchone())


def finalize_ticket_message_delivery(
    ticket_id: str, message_id: str, status: str, workshop_id: str | None = None,
    *, preserve_conversation_state: bool = False,
) -> dict[str, Any]:
    if status not in {"sent", "unknown", "failed"}:
        raise ValueError("Ungültiger abschließender Versandstatus")
    wid = str(workshop_id or default_workshop_id()).strip()
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        row = conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?" +
                           (" FOR UPDATE" if is_postgres() else ""), (wid, ticket_id)).fetchone()
        if not row:
            raise KeyError("Ticket nicht gefunden")
        ticket = _row_to_ticket_dict(row)
        note = next((item for item in ticket["notes"] if item["message_id"] == message_id), None)
        if note is None or note["sender_role"] != "workshop":
            raise ValueError("Werkstattnachricht gehört nicht zu diesem Ticket")
        if note.get("delivery_status") == status:
            return ticket
        if note.get("delivery_status") == "sent":
            raise ValueError("Eine versandte Nachricht kann nicht nachträglich erneut abgeschlossen werden")
        if note.get("delivery_status") == "failed":
            raise ValueError("Ein fehlgeschlagener Versand bleibt abgeschlossen; ein neuer Versuch benötigt eine neue Nachrichtenkennung")
        note["delivery_status"] = status
        now = _now_iso()
        if status == "sent" and note["purpose"] == "workshop_answer":
            target = next((item for item in ticket["notes"]
                           if item["message_id"] == note.get("reply_to_message_id")), None)
            if target is None or target["purpose"] != "customer_question":
                raise ValueError("Antwortziel gehört nicht zu diesem Ticket")
            target["resolved_at"] = target.get("resolved_at") or now
        conn.execute("""UPDATE tickets SET notes_json = ?, customer_question_open = ?, updated_at = ?
                        WHERE workshop_id = ? AND ticket_id = ?""",
                     (json.dumps(ticket["notes"], ensure_ascii=False), int(bool(open_customer_questions(ticket))),
                      now, wid, ticket_id))
        # Delivery completion never reopens waiting_for_customer: an inbound reply
        # may already have advanced the conversation while the HTTP call ran.
        if (not preserve_conversation_state and status == "sent" and note["purpose"] == "workshop_answer"
                and ticket["conversation_state"] == "waiting_for_workshop" and not open_customer_questions(ticket)):
            _set_ticket_state_in_transaction(conn, wid, ticket_id, "workshop_active")
        return _row_to_ticket_dict(conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?",
                                               (wid, ticket_id)).fetchone())


def archive_ticket(ticket_id: str, workshop_id: str | None = None) -> dict[str, Any]:
    """
    Archiviert ein Ticket (status -> archiviert).
    Erlaubt nur für erledigte Tickets.
    """
    t = find_ticket_by_id(ticket_id, workshop_id=workshop_id)
    if not t:
        raise KeyError("Ticket nicht gefunden")

    if _normalize_status(t.get("status")) != "erledigt":
        raise ValueError("Nur erledigte Tickets können archiviert werden")

    return update_ticket_status(ticket_id, "archiviert", workshop_id=workshop_id)
