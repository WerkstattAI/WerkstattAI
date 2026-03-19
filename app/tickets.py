from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models import IntakeState

_LOCK = threading.Lock()

ALLOWED_STATUS = {"offen", "in_bearbeitung", "erledigt", "archiviert"}
ALLOWED_PRIORITY = {"niedrig", "normal", "hoch"}
ALLOWED_REQUEST_TYPE = {"service", "diagnose", "notfall"}


def _project_root() -> str:
    # app/tickets.py -> app -> Projekt-Root
    return os.path.dirname(os.path.dirname(__file__))


def _data_dir() -> str:
    return os.path.join(_project_root(), "data")


def _tickets_path() -> str:
    return os.path.join(_data_dir(), "tickets.jsonl")


def _ensure_data_dir() -> None:
    os.makedirs(_data_dir(), exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _safe_json_loads(line: str) -> Optional[dict[str, Any]]:
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


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


def _next_sequence_for_today(lines: list[str], today: str) -> int:
    """
    Zählt, wie viele Tickets bereits heute existieren,
    und liefert die nächste laufende Nummer.
    today: YYYYMMDD
    """
    count = 0
    for line in lines:
        obj = _safe_json_loads(line)
        if not obj:
            continue

        ticket_id = str(
            obj.get("ticket_id")
            or obj.get("_id")
            or obj.get("id")
            or ""
        )

        if ticket_id.startswith(f"WS-{today}-"):
            count += 1

    return count + 1


def generate_ticket_id() -> str:
    """
    Format: WS-YYYYMMDD-0001
    """
    _ensure_data_dir()
    path = _tickets_path()
    today = datetime.now().strftime("%Y%m%d")

    with _LOCK:
        lines = _read_lines(path)
        seq = _next_sequence_for_today(lines, today)
        return f"WS-{today}-{seq:04d}"


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

    if obj.get("followup_questions") is None:
        obj["followup_questions"] = []

    if obj.get("followup_answers") is None:
        obj["followup_answers"] = []

    if not obj.get("kunde_name") and obj.get("name"):
        obj["kunde_name"] = obj.get("name")

    if not obj.get("name") and obj.get("kunde_name"):
        obj["name"] = obj.get("kunde_name")

    return obj


def save_ticket(state: IntakeState) -> str:
    """
    Speichert ein Ticket in data/tickets.jsonl
    und gibt die ticket_id zurück.
    """
    _ensure_data_dir()
    path = _tickets_path()

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

        # Kontakt
        "name": kunde_name,
        "kunde_name": kunde_name,
        "telefon": state.telefon,
    }

    record = _normalize_ticket_record(record)

    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return ticket_id


def load_all_tickets() -> list[dict[str, Any]]:
    """
    Lädt alle Tickets aus data/tickets.jsonl.
    """
    _ensure_data_dir()
    path = _tickets_path()

    with _LOCK:
        lines = _read_lines(path)

    items: list[dict[str, Any]] = []
    for line in lines:
        obj = _safe_json_loads(line)
        if not obj:
            continue
        items.append(_normalize_ticket_record(obj))

    return items


def list_latest_tickets(limit: int = 50) -> list[dict[str, Any]]:
    """
    Gibt die neuesten Tickets zurück.
    Hard-Limit: 500
    """
    safe_limit = max(0, min(int(limit), 500))
    items = load_all_tickets()
    items.reverse()
    return items[:safe_limit]


def find_ticket_by_id(ticket_id: str) -> Optional[dict[str, Any]]:
    """
    Sucht ein Ticket anhand der Ticket-ID.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        return None

    items = load_all_tickets()
    for obj in items:
        current_id = str(
            obj.get("ticket_id")
            or obj.get("_id")
            or obj.get("id")
            or ""
        ).strip()

        if current_id == tid:
            return obj

    return None


def update_ticket_status(ticket_id: str, new_status: str) -> dict[str, Any]:
    """
    Aktualisiert den Ticket-Status und updated_at in der JSONL-Datei.
    Gibt das aktualisierte Ticket zurück.
    """
    tid = (ticket_id or "").strip()
    if not tid:
        raise ValueError("ticket_id ist leer")

    status = _normalize_status(new_status)
    if status not in ALLOWED_STATUS:
        raise ValueError(f"Ungültiger Status: {new_status}")

    _ensure_data_dir()
    path = _tickets_path()

    with _LOCK:
        lines = _read_lines(path)
        items: list[dict[str, Any]] = []
        updated_ticket: Optional[dict[str, Any]] = None

        for line in lines:
            obj = _safe_json_loads(line)
            if not obj:
                continue

            obj = _normalize_ticket_record(obj)
            current_id = str(
                obj.get("ticket_id")
                or obj.get("_id")
                or obj.get("id")
                or ""
            ).strip()

            if current_id == tid:
                obj["status"] = status
                obj["updated_at"] = _now_iso()
                updated_ticket = obj

            items.append(obj)

        if not updated_ticket:
            raise KeyError("Ticket nicht gefunden")

        with open(path, "w", encoding="utf-8") as f:
            for obj in items:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    return updated_ticket


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