"""Explicit, audited resolution of abandoned outbound dispatch claims."""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

from app.db import atomic_database, get_conn, is_postgres, lock_communication_scope
from app.whatsapp import finalize_whatsapp_dispatch

STALE_DISPATCH_AFTER = timedelta(minutes=5)
STALE_DISPATCH_WARNING = (
    "Der Versandstatus ist unklar. Prüfen Sie den tatsächlichen Status bei Meta, bevor Sie fortfahren."
)


def _started_at(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Claims always use explicit UTC. Ambiguous legacy/corrupt values fail closed.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _stale(row: dict, now: datetime) -> bool:
    started = _started_at(row.get("dispatch_started_at"))
    return bool(
        row.get("direction") == "outbound"
        and row.get("dispatch_state") == "sending"
        and row.get("status") not in {"sent", "sent_local", "delivered", "read", "failed"}
        and started is not None
        and now - started >= STALE_DISPATCH_AFTER
    )


def _payload(row: dict) -> dict:
    try:
        value = json.loads(row.get("payload_json") or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _result(row: dict, *, finalized: bool) -> dict:
    return {**row, "payload": _payload(row), "finalized": finalized}


def dispatch_recovery_context(*, workshop_id: str, customer_phone: str | None = None,
                              ticket_id: str | None = None, now: datetime | None = None) -> dict:
    """Read-only: visiting a dashboard never changes claims or retries transport."""
    now = now or datetime.now(timezone.utc)
    params = [workshop_id]
    query = "SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND direction = 'outbound' AND dispatch_state = 'sending'"
    selectors = []
    if customer_phone:
        selectors.append("customer_phone = ?")
        params.append("".join(c for c in customer_phone if c.isdigit()))
    if ticket_id:
        selectors.append("ticket_id = ?")
        params.append(ticket_id)
    if selectors:
        query += " AND (" + " OR ".join(selectors) + ")"
    with closing(get_conn()) as conn:
        rows = [dict(row) for row in conn.execute(query + " ORDER BY id ASC", params).fetchall()]
    stale = []
    for row in rows:
        if _stale(row, now):
            stale.append({
                "message_id": row["message_id"], "ticket_id": row.get("ticket_id"),
                "customer_phone": row["customer_phone"], "text": row.get("text") or "",
                "purpose": _payload(row).get("purpose"),
                "dispatch_started_at": row["dispatch_started_at"],
                "created_at_display": _started_at(row["dispatch_started_at"]).strftime("%d.%m.%Y %H:%M UTC"),
            })
    return {"dispatch_blocked": bool(rows), "stale_dispatches": stale,
            "blocked_dispatch_phones": sorted({row["customer_phone"] for row in rows})}


def resolve_stale_dispatch(*, workshop_id: str, message_id: str, resolution: str,
                           actor_email: str, confirmed: bool) -> dict:
    """Caller supplies the authenticated identity; both claim and age are rechecked under lock."""
    if confirmed is not True:
        raise ValueError("Bitte die manuelle Klärung ausdrücklich bestätigen.")
    if resolution not in {"sent", "failed"}:
        raise ValueError("Ungültige Klärungsaktion.")
    if not actor_email or not actor_email.strip():
        raise ValueError("Für die Klärung ist ein angemeldeter Werkstattnutzer erforderlich.")
    with atomic_database() as conn:
        lock_communication_scope(conn, workshop_id)
        query = "SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND message_id = ?"
        row = conn.execute(query + (" FOR UPDATE" if is_postgres() else ""),
                           (workshop_id, message_id)).fetchone()
        if not row:
            raise ValueError("Nachricht wurde in dieser Werkstatt nicht gefunden.")
        record = dict(row)
        audit = _payload(record).get("manual_resolution")
        if record.get("dispatch_state") == "complete" and isinstance(audit, dict):
            if audit.get("resolution") == resolution:
                return _result(record, finalized=False)
            raise ValueError("Diese Nachricht wurde bereits anders geklärt. Bitte den Verlauf prüfen.")
        now = datetime.now(timezone.utc)
        if not _stale(record, now):
            raise ValueError("Nur ein weiterhin ungeklärter Versand nach mindestens fünf Minuten kann manuell geklärt werden.")
        result = finalize_whatsapp_dispatch(
            workshop_id=workshop_id, message_id=message_id, status=resolution,
            metadata_updates={"manual_resolution": {
                "resolution": resolution, "actor_email": actor_email.strip(),
                "resolved_at": now.isoformat(), "confirmed": True,
            }, "status_source": "manual_confirmation"},
        )
        updated = dict(conn.execute(query, (workshop_id, message_id)).fetchone())
        return _result(updated, finalized=result["finalized"])
