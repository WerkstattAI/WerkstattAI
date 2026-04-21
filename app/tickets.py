from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from app.db import get_conn
from app.models import IntakeState

_LOCK = threading.Lock()

ALLOWED_STATUS = {"offen", "in_bearbeitung", "erledigt", "archiviert"}
ALLOWED_PRIORITY = {"niedrig", "normal", "hoch"}
ALLOWED_REQUEST_TYPE = {"service", "diagnose", "notfall"}


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


def _bool_to_db(value: Any) -> Optional[int]:
    if value is None:
        return None
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

    if not obj.get("created_at"):
        obj["created_at"] = _now_iso()

    if not obj.get("updated_at"):
        obj["updated_at"] = obj["created_at"]

    obj["status"] = _normalize_status(obj.get("status"))
    obj["priority"] = _normalize_priority(obj.get("priority"))
    obj["request_type"] = _normalize_request_type(obj.get("request_type"))

    if obj.get("followup_questions") is None or not isinstance(obj.get("followup_questions"), list):
        obj["followup_questions"] = []

    if obj.get("followup_answers") is None or not isinstance(obj.get("followup_answers"), list):
        obj["followup_answers"] = []

    if obj.get("notes") is None or not isinstance(obj.get("notes"), list):
        obj["notes"] = []

    if not obj.get("kunde_name") and obj.get("name"):
        obj["kunde_name"] = obj.get("name")

    if not obj.get("name") and obj.get("kunde_name"):
        obj["name"] = obj.get("kunde_name")

    return obj


def _row_to_ticket_dict(row: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "ticket_id": row["ticket_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "priority": row["priority"],
        "request_type": row["request_type"],
        "fahrzeug": row["fahrzeug"],
        "baujahr": row["baujahr"],
        "kilometerstand": row["kilometerstand"],
        "fahrbereit": _db_to_bool(row["fahrbereit"]),
        "abschleppdienst": _db_to_bool(row["abschleppdienst"]),
        "problem": row["problem"],
        "name": row["name"],
        "kunde_name": row["kunde_name"],
        "telefon": row["telefon"],
        "followup_questions": _safe_json_loads(row["followup_questions_json"], []),
        "followup_answers": _safe_json_loads(row["followup_answers_json"], []),
        "notes": _safe_json_loads(row["notes_json"], []),
    }

    return _normalize_ticket_record(obj)


def _next_sequence_for_today(today: str) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ticket_id
            FROM tickets
            WHERE ticket_id LIKE ?
            """,
            (f"WS-{today}-%",),
        ).fetchall()

    count = 0
    for row in rows:
        ticket_id = str(row["ticket_id"] or "")
        if ticket_id.startswith(f"WS-{today}-"):
            count += 1

    return count + 1


def generate_ticket_id() -> str:
    """
    Format: WS-YYYYMMDD-0001
    """
    today = datetime.now().strftime("%Y%m%d")

    with _LOCK:
        seq = _next_sequence_for_today(today)
        return f"WS-{today}-{seq:04d}"


def save_ticket(state: IntakeState) -> str:
    """
    Speichert ein Ticket in SQLite
    und gibt die ticket_id zurück.
    """
    ticket_id = state.ticket_id or generate_ticket_id()
    now_iso = _now_iso()
    kunde_name = state.name

    record: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "created_at": now_iso,
        "updated_at": now_iso,

        # Workflow
        "status": "offen",
        "request_type": _normalize_request_type(state.request_type),
        "priority": _normalize_priority(state.priority),

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

    with _LOCK:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    ticket_id,
                    created_at,
                    updated_at,
                    status,
                    priority,
                    request_type,
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
                    notes_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["ticket_id"],
                    record["created_at"],
                    record["updated_at"],
                    record["status"],
                    record["priority"],
                    record["request_type"],
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
                ),
            )
            conn.commit()

    return ticket_id


def load_all_tickets() -> list[dict[str, Any]]:
    """
    Lädt alle Tickets aus SQLite.
    """
    with _LOCK:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tickets
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()

    return [_row_to_ticket_dict(row) for row in rows]


def list_latest_tickets(limit: int = 50) -> list[dict[str, Any]]:
    """
    Gibt die neuesten Tickets zurück.
    Hard-Limit: 500
    """
    safe_limit = max(0, min(int(limit), 500))

    with _LOCK:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tickets
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    return [_row_to_ticket_dict(row) for row in rows]


def normalize_phone_for_search(phone: str) -> str:
    """
    Normalisiert Telefonnummern für tolerante Suche:
    - entfernt Leerzeichen, Bindestriche, Klammern usw.
    - behält nur Ziffern
    """
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def find_tickets_by_phone(phone: str) -> list[dict[str, Any]]:
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

    with _LOCK:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE telefon IS NOT NULL
                ORDER BY created_at DESC, id DESC
                """
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


def find_latest_ticket_by_phone(phone: str) -> Optional[dict[str, Any]]:
    """
    Gibt das neueste Ticket zu einer Telefonnummer zurück.
    """
    matches = find_tickets_by_phone(phone)
    return matches[0] if matches else None


def find_ticket_by_id(ticket_id: str) -> Optional[dict[str, Any]]:
    """
    Sucht ein Ticket anhand der Ticket-ID.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        return None

    with _LOCK:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE ticket_id = ?
                LIMIT 1
                """,
                (tid,),
            ).fetchone()

    if not row:
        return None

    return _row_to_ticket_dict(row)


def update_ticket_status(ticket_id: str, new_status: str) -> dict[str, Any]:
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

    with _LOCK:
        with get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE tickets
                SET status = ?, updated_at = ?
                WHERE ticket_id = ?
                """,
                (status, now_iso, tid),
            )

            if cur.rowcount == 0:
                raise KeyError("Ticket nicht gefunden")

            conn.commit()

            row = conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE ticket_id = ?
                LIMIT 1
                """,
                (tid,),
            ).fetchone()

    if not row:
        raise KeyError("Ticket nicht gefunden")

    return _row_to_ticket_dict(row)


def add_ticket_note(ticket_id: str, note_text: str) -> dict[str, Any]:
    """
    Fügt einem Ticket eine interne Notiz hinzu
    und aktualisiert updated_at.
    """
    tid = (ticket_id or "").strip()
    text = (note_text or "").strip()

    if not tid:
        raise ValueError("ticket_id ist leer")

    if not text:
        raise ValueError("note_text ist leer")

    now_iso = _now_iso()

    with _LOCK:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE ticket_id = ?
                LIMIT 1
                """,
                (tid,),
            ).fetchone()

            if not row:
                raise KeyError("Ticket nicht gefunden")

            notes = _safe_json_loads(row["notes_json"], [])
            if not isinstance(notes, list):
                notes = []

            notes.append(
                {
                    "text": text,
                    "created_at": now_iso,
                }
            )

            conn.execute(
                """
                UPDATE tickets
                SET notes_json = ?, updated_at = ?
                WHERE ticket_id = ?
                """,
                (
                    json.dumps(notes, ensure_ascii=False),
                    now_iso,
                    tid,
                ),
            )
            conn.commit()

            updated_row = conn.execute(
                """
                SELECT *
                FROM tickets
                WHERE ticket_id = ?
                LIMIT 1
                """,
                (tid,),
            ).fetchone()

    if not updated_row:
        raise KeyError("Ticket nicht gefunden")

    return _row_to_ticket_dict(updated_row)


def archive_ticket(ticket_id: str) -> dict[str, Any]:
    """
    Archiviert ein Ticket (status -> archiviert).
    Erlaubt nur für erledigte Tickets.
    """
    t = find_ticket_by_id(ticket_id)
    if not t:
        raise KeyError("Ticket nicht gefunden")

    if _normalize_status(t.get("status")) != "erledigt":
        raise ValueError("Nur erledigte Tickets können archiviert werden")

    return update_ticket_status(ticket_id, "archiviert")