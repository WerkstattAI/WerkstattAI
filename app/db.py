from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.security import hash_password
from app.security_config import validate_new_admin_password


WHATSAPP_CONVERSATION_MODES = frozenset({"assistant", "manual"})
_UNSET_ACTIVE_TICKET = object()


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))


def _data_dir() -> str:
    return os.path.join(_project_root(), "data")


def _db_path() -> str:
    override = str(os.getenv("WERKSTATTAI_SQLITE_PATH") or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(_data_dir(), "werkstattai.db")


def _trial_ends_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=settings.trial_days)).isoformat()


class PostgresConnection:
    def __init__(self, database_url: str):
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(database_url, row_factory=dict_row)

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type:
            self._conn.rollback()
        self._conn.close()

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        return self._conn.execute(self._convert_placeholders(sql), params)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def is_postgres() -> bool:
    return bool(settings.database_url)


def get_conn() -> sqlite3.Connection | PostgresConnection:
    if settings.database_url:
        return PostgresConnection(settings.database_url)

    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def default_workshop_id() -> str:
    return settings.default_workshop_id


def demo_workshop_id() -> str:
    return settings.demo_workshop_id.strip()


def _column_exists(conn: sqlite3.Connection | PostgresConnection, table: str, column: str) -> bool:
    if is_postgres():
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = ? AND column_name = ?
            LIMIT 1
            """,
            (table, column),
        ).fetchone()
        return bool(row)

    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection | PostgresConnection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    if not demo_workshop_id() or demo_workshop_id() == default_workshop_id().strip():
        raise ValueError("DEMO_WORKSHOP_ID muss sich von DEFAULT_WORKSHOP_ID unterscheiden.")
    if not is_postgres():
        os.makedirs(os.path.dirname(_db_path()), exist_ok=True)

    ticket_pk = "BIGSERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"

    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workshops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                email TEXT,
                opening_hours TEXT,
                services TEXT,
                pricing_info TEXT,
                towing_info TEXT,
                subscription_plan TEXT NOT NULL DEFAULT 'starter',
                subscription_status TEXT NOT NULL DEFAULT 'trialing',
                trial_ends_at TEXT,
                subscription_ends_at TEXT,
                whatsapp_phone_number_id TEXT,
                whatsapp_display_phone_number TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _add_column_if_missing(conn, "workshops", "services", "TEXT")
        _add_column_if_missing(conn, "workshops", "pricing_info", "TEXT")
        _add_column_if_missing(conn, "workshops", "towing_info", "TEXT")
        _add_column_if_missing(conn, "workshops", "subscription_plan", "TEXT NOT NULL DEFAULT 'starter'")
        _add_column_if_missing(conn, "workshops", "subscription_status", "TEXT NOT NULL DEFAULT 'trialing'")
        _add_column_if_missing(conn, "workshops", "trial_ends_at", "TEXT")
        _add_column_if_missing(conn, "workshops", "subscription_ends_at", "TEXT")
        _add_column_if_missing(conn, "workshops", "whatsapp_phone_number_id", "TEXT")
        _add_column_if_missing(conn, "workshops", "whatsapp_display_phone_number", "TEXT")
        _add_column_if_missing(conn, "workshops", "is_demo", "INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                workshop_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        existing_admin = conn.execute(
            "SELECT email FROM users WHERE email = ?", (settings.dashboard_admin_email.strip().lower(),)
        ).fetchone()
        if not existing_admin:
            validate_new_admin_password(settings)

        conn.execute(
            """
            INSERT INTO users (
                email,
                password_hash,
                workshop_id,
                role
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (
                settings.dashboard_admin_email.strip().lower(),
                hash_password(settings.dashboard_admin_password),
                default_workshop_id(),
                settings.dashboard_admin_role,
            ),
        )

        conn.execute(
            """
            INSERT INTO workshops (
                id,
                name,
                subscription_plan,
                subscription_status,
                trial_ends_at,
                whatsapp_phone_number_id
            )
            VALUES (
                ?,
                'Meine Werkstatt',
                'starter',
                'trialing',
                ?,
                ?
            )
            ON CONFLICT(id) DO NOTHING
            """,
            (
                default_workshop_id(),
                _trial_ends_at(),
                settings.whatsapp_default_phone_number_id,
            ),
        )

        # The legacy default ID may contain real customer data. Keep it intact
        # and create a separate tenant for the public demo without login or WhatsApp.
        conn.execute(
            """
            INSERT INTO workshops (
                id, name, address, email, opening_hours, services,
                pricing_info, towing_info, subscription_status, is_demo
            )
            VALUES (?, 'WerkstattAI Demo', 'Musterstraße 1, 12345 Musterstadt',
                'kontakt@example.invalid',
                'Montag bis Freitag: 09:00-17:00; Samstag: 09:00-14:00; Sonntag: geschlossen',
                'Inspektion, Reifenwechsel, Autoreparaturen',
                'Beispieldaten: Preise werden in dieser Demo nicht verbindlich angeboten.',
                'Beispieldaten: In dieser Demo wird kein Abschleppdienst beauftragt.',
                'active', 1)
            ON CONFLICT(id) DO NOTHING
            """,
            (demo_workshop_id(),),
        )
        demo = conn.execute(
            "SELECT is_demo, whatsapp_phone_number_id FROM workshops WHERE id = ?",
            (demo_workshop_id(),),
        ).fetchone()
        demo_user = conn.execute(
            "SELECT email FROM users WHERE workshop_id = ? LIMIT 1",
            (demo_workshop_id(),),
        ).fetchone()
        if not demo["is_demo"] or demo["whatsapp_phone_number_id"] or demo_user:
            raise ValueError("DEMO_WORKSHOP_ID ist bereits mit einem Produktivkonto verknüpft.")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id {ticket_pk},
                workshop_id TEXT NOT NULL DEFAULT 'demo-werkstatt',
                ticket_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                request_type TEXT,

                fahrzeug TEXT,
                baujahr TEXT,
                kilometerstand TEXT,

                fahrbereit INTEGER,
                abschleppdienst INTEGER,

                problem TEXT,

                name TEXT,
                kunde_name TEXT,
                telefon TEXT,
                customer_question_open INTEGER NOT NULL DEFAULT 0,

                followup_questions_json TEXT NOT NULL DEFAULT '[]',
                followup_answers_json TEXT NOT NULL DEFAULT '[]',
                notes_json TEXT NOT NULL DEFAULT '[]'
            )
            """.format(ticket_pk=ticket_pk)
        )

        _add_column_if_missing(
            conn,
            "tickets",
            "workshop_id",
            "TEXT NOT NULL DEFAULT 'demo-werkstatt'",
        )
        _add_column_if_missing(
            conn,
            "tickets",
            "source",
            "TEXT NOT NULL DEFAULT 'web_chat'",
        )
        _add_column_if_missing(
            conn,
            "tickets",
            "customer_question_open",
            "INTEGER NOT NULL DEFAULT 0",
        )
        conn.execute(
            """
            UPDATE tickets
            SET workshop_id = ?
            WHERE workshop_id IS NULL OR workshop_id = ''
            """,
            (default_workshop_id(),),
        )
        conn.execute(
            """
            UPDATE tickets
            SET source = 'web_chat'
            WHERE source IS NULL OR source = ''
            """
        )

        conn.execute(
            """
            UPDATE tickets
            SET customer_question_open = 0
            WHERE customer_question_open IS NULL
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_ticket_id
            ON tickets(ticket_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_workshop_id
            ON tickets(workshop_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_created_at
            ON tickets(created_at DESC)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_status
            ON tickets(status)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_priority
            ON tickets(priority)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_limit_buckets (
                bucket_key TEXT PRIMARY KEY,
                hits INTEGER NOT NULL,
                expires_at BIGINT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rate_limit_expiry ON rate_limit_buckets(expires_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_sequences (
                ticket_date TEXT PRIMARY KEY,
                last_value BIGINT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                session_id TEXT PRIMARY KEY,
                workshop_id TEXT NOT NULL DEFAULT 'demo-werkstatt',
                channel TEXT NOT NULL DEFAULT 'web_chat',
                phone TEXT,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        _add_column_if_missing(
            conn,
            "conversation_sessions",
            "workshop_id",
            "TEXT NOT NULL DEFAULT 'demo-werkstatt'",
        )
        conn.execute(
            """
            UPDATE conversation_sessions
            SET workshop_id = ?
            WHERE workshop_id IS NULL OR workshop_id = ''
            """,
            (default_workshop_id(),),
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_sessions_workshop_id
            ON conversation_sessions(workshop_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated_at
            ON conversation_sessions(updated_at DESC)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_sessions_phone
            ON conversation_sessions(phone)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_events (
                id {ticket_pk},
                workshop_id TEXT NOT NULL,
                phone_number_id TEXT,
                display_phone_number TEXT,
                wa_message_id TEXT,
                from_phone TEXT,
                event_type TEXT NOT NULL,
                message_type TEXT,
                text TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """.format(ticket_pk=ticket_pk)
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_events_workshop_id
            ON whatsapp_events(workshop_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_events_wa_message_id
            ON whatsapp_events(wa_message_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id {ticket_pk},
                workshop_id TEXT NOT NULL,
                phone_number_id TEXT,
                customer_phone TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'text',
                text TEXT,
                wa_message_id TEXT,
                ticket_id TEXT,
                status TEXT NOT NULL DEFAULT 'received',
                payload_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """.format(ticket_pk=ticket_pk)
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_workshop_phone
            ON whatsapp_messages(workshop_id, customer_phone, created_at)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_ticket_id
            ON whatsapp_messages(workshop_id, ticket_id)
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_messages_unique_wa_id
            ON whatsapp_messages(workshop_id, direction, wa_message_id)
            WHERE wa_message_id IS NOT NULL
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_conversation_controls (
                workshop_id TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'assistant'
                    CHECK (mode IN ('assistant', 'manual')),
                active_ticket_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (workshop_id, customer_phone)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_conversation_controls_ticket
            ON whatsapp_conversation_controls(workshop_id, active_ticket_id)
            """
        )

        conn.commit()


def _normalize_whatsapp_control_phone(customer_phone: str) -> str:
    digits = "".join(character for character in str(customer_phone or "") if character.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = f"49{digits[1:]}"
    if not digits:
        raise ValueError("customer_phone is required")
    return digits


def _normalize_whatsapp_conversation_scope(
    *,
    workshop_id: str,
    customer_phone: str,
) -> tuple[str, str]:
    wid = str(workshop_id or "").strip()
    if not wid:
        raise ValueError("workshop_id is required")
    return wid, _normalize_whatsapp_control_phone(customer_phone)


def get_whatsapp_conversation_control(
    *,
    workshop_id: str,
    customer_phone: str,
) -> dict[str, Any]:
    """Return the tenant-scoped WhatsApp mode, defaulting to assistant mode."""
    wid, phone = _normalize_whatsapp_conversation_scope(
        workshop_id=workshop_id,
        customer_phone=customer_phone,
    )

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                workshop_id,
                customer_phone,
                mode,
                active_ticket_id,
                created_at,
                updated_at
            FROM whatsapp_conversation_controls
            WHERE workshop_id = ? AND customer_phone = ?
            LIMIT 1
            """,
            (wid, phone),
        ).fetchone()

    if row:
        return dict(row)

    return {
        "workshop_id": wid,
        "customer_phone": phone,
        "mode": "assistant",
        "active_ticket_id": None,
        "created_at": None,
        "updated_at": None,
    }


def set_whatsapp_conversation_control(
    *,
    workshop_id: str,
    customer_phone: str,
    mode: str,
    active_ticket_id: str | None | object = _UNSET_ACTIVE_TICKET,
) -> dict[str, Any]:
    """Persist a tenant-scoped WhatsApp mode and optionally change its ticket link.

    Omitting ``active_ticket_id`` preserves an existing ticket link. Passing
    ``None`` explicitly clears it.
    """
    wid, phone = _normalize_whatsapp_conversation_scope(
        workshop_id=workshop_id,
        customer_phone=customer_phone,
    )
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in WHATSAPP_CONVERSATION_MODES:
        raise ValueError("mode must be 'assistant' or 'manual'")

    ticket_was_provided = active_ticket_id is not _UNSET_ACTIVE_TICKET
    normalized_ticket_id: str | None = None
    if ticket_was_provided:
        normalized_ticket_id = str(active_ticket_id or "").strip() or None

    with get_conn() as conn:
        if normalized_ticket_id:
            ticket = conn.execute(
                """
                SELECT 1
                FROM tickets
                WHERE workshop_id = ? AND ticket_id = ?
                LIMIT 1
                """,
                (wid, normalized_ticket_id),
            ).fetchone()
            if not ticket:
                raise ValueError("active_ticket_id does not belong to workshop_id")

        if ticket_was_provided:
            conn.execute(
                """
                INSERT INTO whatsapp_conversation_controls (
                    workshop_id,
                    customer_phone,
                    mode,
                    active_ticket_id
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workshop_id, customer_phone) DO UPDATE SET
                    mode = excluded.mode,
                    active_ticket_id = excluded.active_ticket_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (wid, phone, normalized_mode, normalized_ticket_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO whatsapp_conversation_controls (
                    workshop_id,
                    customer_phone,
                    mode
                )
                VALUES (?, ?, ?)
                ON CONFLICT(workshop_id, customer_phone) DO UPDATE SET
                    mode = excluded.mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (wid, phone, normalized_mode),
            )
        conn.commit()

    return get_whatsapp_conversation_control(
        workshop_id=wid,
        customer_phone=phone,
    )
