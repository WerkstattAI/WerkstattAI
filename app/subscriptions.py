from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import default_workshop_id, get_conn


ACTIVE_STATUSES = {"active", "trialing", "past_due"}
BLOCKED_STATUSES = {"inactive", "canceled", "expired"}


def _normalize_workshop_id(workshop_id: str | None = None) -> str:
    return (workshop_id or default_workshop_id()).strip() or default_workshop_id()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_left(value: str | None) -> int | None:
    expires_at = _parse_dt(value)
    if not expires_at:
        return None
    seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return max(0, int((seconds + 86399) // 86400))


def _row_to_subscription(row: Any, workshop_id: str) -> dict[str, Any]:
    status = str(row["subscription_status"] or "inactive").strip().lower()
    trial_ends_at = row["trial_ends_at"]
    subscription_ends_at = row["subscription_ends_at"]
    is_active = status == "active" or status == "past_due"

    if status == "trialing":
        trial_end = _parse_dt(trial_ends_at)
        is_active = bool(trial_end and trial_end >= datetime.now(timezone.utc))

    if status in BLOCKED_STATUSES:
        is_active = False

    return {
        "workshop_id": workshop_id,
        "plan": row["subscription_plan"] or "starter",
        "status": status,
        "trial_ends_at": trial_ends_at,
        "subscription_ends_at": subscription_ends_at,
        "trial_days_left": _days_left(trial_ends_at),
        "is_active": is_active,
    }


def get_subscription(workshop_id: str | None = None) -> dict[str, Any]:
    wid = _normalize_workshop_id(workshop_id)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                subscription_plan,
                subscription_status,
                trial_ends_at,
                subscription_ends_at
            FROM workshops
            WHERE id = ?
            LIMIT 1
            """,
            (wid,),
        ).fetchone()

    if not row:
        return {
            "workshop_id": wid,
            "plan": "starter",
            "status": "inactive",
            "trial_ends_at": None,
            "subscription_ends_at": None,
            "trial_days_left": None,
            "is_active": False,
        }

    return _row_to_subscription(row, wid)


def is_subscription_active(workshop_id: str | None = None) -> bool:
    return bool(get_subscription(workshop_id).get("is_active"))
