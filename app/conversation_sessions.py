from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.db import default_workshop_id, get_conn
from app.models import IntakeState


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _state_to_dict(state: IntakeState) -> dict[str, Any]:
    if hasattr(state, "model_dump"):
        return state.model_dump()
    return state.dict()


def _state_from_dict(data: dict[str, Any]) -> IntakeState:
    return IntakeState(**data)


def _storage_session_id(session_id: str, workshop_id: str) -> str:
    return f"{workshop_id}:{session_id}"


def load_session_state(session_id: str, workshop_id: str | None = None) -> IntakeState:
    sid = (session_id or "").strip()
    if not sid:
        return IntakeState()

    wid = str(workshop_id or default_workshop_id()).strip() or default_workshop_id()
    storage_sid = _storage_session_id(sid, wid)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT state_json
            FROM conversation_sessions
            WHERE session_id = ? AND workshop_id = ?
            LIMIT 1
            """,
            (storage_sid, wid),
        ).fetchone()

        if not row:
            row = conn.execute(
                """
                SELECT state_json
                FROM conversation_sessions
                WHERE session_id = ? AND workshop_id = ?
                LIMIT 1
                """,
                (sid, wid),
            ).fetchone()

    if not row:
        return IntakeState()

    try:
        data = json.loads(row["state_json"])
    except Exception:
        return IntakeState()

    if not isinstance(data, dict):
        return IntakeState()

    try:
        state = _state_from_dict(data)
        state.workshop_id = state.workshop_id or wid
        return state
    except Exception:
        return IntakeState()


def save_session_state(
    session_id: str,
    state: IntakeState,
    *,
    workshop_id: str | None = None,
    channel: str = "web_chat",
    phone: str | None = None,
) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return

    now = _now_iso()
    wid = str(workshop_id or state.workshop_id or default_workshop_id()).strip() or default_workshop_id()
    state.workshop_id = wid
    storage_sid = _storage_session_id(sid, wid)
    state_json = json.dumps(_state_to_dict(state), ensure_ascii=False)
    normalized_channel = (channel or "web_chat").strip() or "web_chat"
    normalized_phone = (phone or getattr(state, "telefon", None) or "").strip() or None

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversation_sessions (
                session_id,
                workshop_id,
                channel,
                phone,
                state_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                workshop_id = excluded.workshop_id,
                channel = excluded.channel,
                phone = excluded.phone,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                storage_sid,
                wid,
                normalized_channel,
                normalized_phone,
                state_json,
                now,
                now,
            ),
        )
        conn.commit()
