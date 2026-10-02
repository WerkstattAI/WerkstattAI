from __future__ import annotations

import os
import json
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.security import hash_password
from app.security_config import validate_new_admin_password


WHATSAPP_CONVERSATION_MODES = frozenset({"assistant", "manual"})
_UNSET_ACTIVE_TICKET = object()
_UNSET_PENDING_QUESTION = object()
_TRANSACTION_CONNECTION: ContextVar[Any] = ContextVar("werkstattai_transaction", default=None)


class _SQLiteConnection(sqlite3.Connection):
    """Own the connection as well as the transaction when used in a with block."""

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class _TransactionConnection:
    """Let existing helpers share an outer transaction without committing/closing it."""

    def __init__(self, connection: Any):
        self.connection = connection
        self.rollback_only = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.rollback_only = True

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def commit(self):
        pass

    def close(self):
        pass

    def rollback(self):
        self.rollback_only = True


@contextmanager
def atomic_database():
    """Commit database-only business processing together, including nested helpers.

    SQLite takes its write reservation up front. PostgreSQL callers additionally
    lock the relevant conversation row. Never hold this transaction across HTTP.
    """
    current = _TRANSACTION_CONNECTION.get()
    if current is not None:
        try:
            yield current
        except BaseException:
            current.rollback_only = True
            raise
        return
    connection = get_conn()
    shared = _TransactionConnection(connection)
    token = _TRANSACTION_CONNECTION.set(shared)
    try:
        if not settings.database_url:
            connection.execute("BEGIN IMMEDIATE")
        yield shared
        if shared.rollback_only:
            raise RuntimeError("Nested database operation failed; transaction rolled back")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        _TRANSACTION_CONNECTION.reset(token)
        connection.close()


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
    """Return an owned connection, or borrow the current atomic transaction.

    Owned connections must be closed explicitly or through their context manager.
    Borrowed connections are closed only by the outer atomic_database() scope.
    """
    shared = _TRANSACTION_CONNECTION.get()
    if shared is not None:
        return shared
    if settings.database_url:
        return PostgresConnection(settings.database_url)

    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)

    conn = sqlite3.connect(_db_path(), factory=_SQLiteConnection)
    conn.row_factory = sqlite3.Row
    return conn


def default_workshop_id() -> str:
    return settings.default_workshop_id


def lock_communication_scope(conn, workshop_id: str) -> None:
    """Use one short transaction lock before ticket/control row locks on PostgreSQL."""
    if is_postgres():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("communication:" + workshop_id,))


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
        # Never infer ownership from a freely entered contact number, including
        # historical tickets. Only trusted transports supply this on creation.
        _add_column_if_missing(conn, "tickets", "verified_customer_phone", "TEXT")
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
        _add_column_if_missing(conn, "whatsapp_messages", "customer_message_at", "TEXT")
        # Existing rows are complete: deployment must never replay old conversations.
        _add_column_if_missing(conn, "whatsapp_messages", "processing_state", "TEXT NOT NULL DEFAULT 'complete'")
        _add_column_if_missing(conn, "whatsapp_messages", "reply_to_wa_message_id", "TEXT")
        _add_column_if_missing(conn, "whatsapp_messages", "dispatch_state", "TEXT NOT NULL DEFAULT 'complete'")
        _add_column_if_missing(conn, "whatsapp_messages", "dispatch_started_at", "TEXT")
        # A historical in-flight row has no trustworthy start time. Start a fresh
        # recovery grace period once, instead of treating it as immediately stale.
        conn.execute("""UPDATE whatsapp_messages SET dispatch_started_at = ?
                        WHERE dispatch_state = 'sending' AND dispatch_started_at IS NULL""",
                     (datetime.now(timezone.utc).isoformat(),))
        _add_column_if_missing(conn, "whatsapp_messages", "control_revision", "INTEGER")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_reply_source
            ON whatsapp_messages(workshop_id, reply_to_wa_message_id)
            WHERE direction = 'outbound' AND reply_to_wa_message_id IS NOT NULL
        """)
        # Recover trustworthy event times from old signed webhook payloads.
        # Rows without a valid Meta timestamp remain closed until a new message.
        from app.whatsapp import customer_message_datetime
        import json
        for message in conn.execute("""
            SELECT id, payload_json FROM whatsapp_messages
            WHERE direction = 'inbound' AND customer_message_at IS NULL
        """).fetchall():
            try:
                payload = json.loads(message["payload_json"] or "{}")
                timestamp = customer_message_datetime(payload.get("timestamp")) if isinstance(payload, dict) else None
            except (TypeError, ValueError):
                timestamp = None
            if timestamp:
                conn.execute("UPDATE whatsapp_messages SET customer_message_at = ? WHERE id = ?",
                             (timestamp, message["id"]))

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
        _add_column_if_missing(conn, "whatsapp_conversation_controls", "revision", "INTEGER NOT NULL DEFAULT 0")
        _migrate_customer_communication(conn)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS privacy_operations (
                id TEXT PRIMARY KEY,
                workshop_id TEXT NOT NULL,
                actor_hash TEXT NOT NULL,
                action TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_privacy_operations_created ON privacy_operations(created_at)")
        conn.commit()


def _migrate_customer_communication(conn) -> None:
    """Portable, additive migration; semantic history remains in ticket notes."""
    from app.communication import conversation_mode, normalize_ticket_notes, open_customer_questions

    ticket_state_added = not _column_exists(conn, "tickets", "conversation_state")
    _add_column_if_missing(conn, "tickets", "conversation_state", "TEXT NOT NULL DEFAULT 'assistant_active'")
    control_state_added = not _column_exists(conn, "whatsapp_conversation_controls", "conversation_state")
    _add_column_if_missing(conn, "whatsapp_conversation_controls", "conversation_state", "TEXT NOT NULL DEFAULT 'assistant_active'")
    _add_column_if_missing(conn, "whatsapp_conversation_controls", "pending_workshop_question_id", "TEXT")
    _add_column_if_missing(conn, "whatsapp_messages", "message_id", "TEXT")
    if control_state_added:
        conn.execute("""UPDATE whatsapp_conversation_controls SET conversation_state =
                        CASE WHEN mode = 'manual' THEN 'workshop_active' ELSE 'assistant_active' END""")
    for row in conn.execute("SELECT workshop_id, ticket_id, notes_json, customer_question_open, conversation_state FROM tickets").fetchall():
        try:
            old_notes = json.loads(row["notes_json"] or "[]")
        except (ValueError, TypeError):
            # Preserve malformed historical content rather than silently erase it.
            continue
        if not isinstance(old_notes, list) or any(not isinstance(note, dict) for note in old_notes):
            # Do not discard opaque/malformed historical entries during upgrade.
            continue
        notes = normalize_ticket_notes(old_notes, workshop_id=row["workshop_id"], ticket_id=row["ticket_id"],
                                       legacy_question_open=bool(row["customer_question_open"]))
        questions_open = int(bool(open_customer_questions({"notes": notes})))
        state = row["conversation_state"]
        if ticket_state_added:
            manual = conn.execute("""SELECT 1 FROM whatsapp_conversation_controls
                                     WHERE workshop_id = ? AND active_ticket_id = ? AND mode = 'manual' LIMIT 1""",
                                  (row["workshop_id"], row["ticket_id"])).fetchone()
            state = "waiting_for_workshop" if questions_open else "workshop_active" if manual else "assistant_active"
        if old_notes != notes or questions_open != row["customer_question_open"] or state != row["conversation_state"]:
            conn.execute("""UPDATE tickets SET notes_json = ?, customer_question_open = ?, conversation_state = ?
                            WHERE workshop_id = ? AND ticket_id = ?""",
                         (json.dumps(notes, ensure_ascii=False), questions_open, state, row["workshop_id"], row["ticket_id"]))
    # Controls only own the state for conversations without a linked ticket.
    for row in conn.execute("""SELECT c.workshop_id, c.customer_phone, t.conversation_state
                               FROM whatsapp_conversation_controls c JOIN tickets t
                               ON t.workshop_id = c.workshop_id AND t.ticket_id = c.active_ticket_id""").fetchall():
        conn.execute("""UPDATE whatsapp_conversation_controls SET conversation_state = ?, mode = ?
                        WHERE workshop_id = ? AND customer_phone = ?""",
                     (row["conversation_state"], conversation_mode(row["conversation_state"]),
                      row["workshop_id"], row["customer_phone"]))
    for row in conn.execute("SELECT id, workshop_id, direction FROM whatsapp_messages WHERE message_id IS NULL OR message_id = ''").fetchall():
        identity = json.dumps([row["workshop_id"], row["direction"], row["id"]], separators=(",", ":"))
        conn.execute("UPDATE whatsapp_messages SET message_id = ? WHERE workshop_id = ? AND id = ?",
                     ("legacy-wa-" + uuid.uuid5(uuid.NAMESPACE_URL, identity).hex, row["workshop_id"], row["id"]))
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_messages_message_id
                    ON whatsapp_messages(workshop_id, message_id) WHERE message_id IS NOT NULL""")


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
    """Read the canonical ticket state or the unassigned conversation state."""
    from app.communication import conversation_mode, pending_workshop_question
    from app.tickets import _row_to_ticket_dict

    wid, phone = _normalize_whatsapp_conversation_scope(workshop_id=workshop_id, customer_phone=customer_phone)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM whatsapp_conversation_controls WHERE workshop_id = ? AND customer_phone = ?",
                           (wid, phone)).fetchone()
        result = dict(row) if row else {
            "workshop_id": wid, "customer_phone": phone, "mode": "assistant",
            "conversation_state": "assistant_active", "active_ticket_id": None,
            "pending_workshop_question_id": None, "revision": 0, "created_at": None, "updated_at": None,
        }
        if result.get("active_ticket_id"):
            ticket_row = conn.execute("SELECT * FROM tickets WHERE workshop_id = ? AND ticket_id = ?",
                                      (wid, result["active_ticket_id"])).fetchone()
            if ticket_row:
                ticket = _row_to_ticket_dict(ticket_row)
                result["conversation_state"] = ticket["conversation_state"]
                pending = pending_workshop_question(ticket)
                result["pending_workshop_question_id"] = pending["message_id"] if pending else None
    result["mode"] = conversation_mode(result["conversation_state"])
    return result


def set_whatsapp_conversation_control(
    *,
    workshop_id: str,
    customer_phone: str,
    mode: str | None = None,
    conversation_state: str | None = None,
    active_ticket_id: str | None | object = _UNSET_ACTIVE_TICKET,
    pending_workshop_question_id: str | None | object = _UNSET_PENDING_QUESTION,
) -> dict[str, Any]:
    """Change canonical ownership; legacy mode is a compatibility projection.

    An explicit state is preferred. Old callers passing assistant/manual retain
    their meaning, but only the explicit assistant action may resume automation.
    """
    from app.communication import CONVERSATION_STATES, conversation_mode
    from app.tickets import _set_ticket_state_in_transaction

    wid, phone = _normalize_whatsapp_conversation_scope(workshop_id=workshop_id, customer_phone=customer_phone)
    if mode is not None and mode not in WHATSAPP_CONVERSATION_MODES:
        raise ValueError("mode must be 'assistant' or 'manual'")
    if conversation_state is not None and conversation_state not in CONVERSATION_STATES:
        raise ValueError("Invalid conversation_state")
    if conversation_state is not None and mode is not None and conversation_mode(conversation_state) != mode:
        raise ValueError("mode and conversation_state disagree")
    if conversation_state is None and mode is None:
        raise ValueError("mode or conversation_state is required")
    state = conversation_state or ("assistant_active" if mode == "assistant" else "workshop_active")
    projected_mode = conversation_mode(state)
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        if state == "assistant_active":
            sending = conn.execute("""SELECT 1 FROM whatsapp_messages
                                      WHERE workshop_id = ? AND customer_phone = ? AND direction = 'outbound'
                                        AND dispatch_state = 'sending' LIMIT 1""", (wid, phone)).fetchone()
            if sending:
                raise ValueError("Eine Nachricht wird gerade versendet. Bitte danach den Assistenten aktivieren.")
        previous = conn.execute("SELECT * FROM whatsapp_conversation_controls WHERE workshop_id = ? AND customer_phone = ?" +
                                (" FOR UPDATE" if is_postgres() else ""), (wid, phone)).fetchone()
        previous = dict(previous) if previous else {}
        tid = (previous.get("active_ticket_id") if active_ticket_id is _UNSET_ACTIVE_TICKET
               else str(active_ticket_id or "").strip() or None)
        pending = (previous.get("pending_workshop_question_id") if pending_workshop_question_id is _UNSET_PENDING_QUESTION
                   else str(pending_workshop_question_id or "").strip() or None)
        if tid:
            ticket = conn.execute("SELECT 1 FROM tickets WHERE workshop_id = ? AND ticket_id = ?" +
                                  (" FOR UPDATE" if is_postgres() else ""), (wid, tid)).fetchone()
            if not ticket:
                raise ValueError("active_ticket_id does not belong to workshop_id")
            _set_ticket_state_in_transaction(conn, wid, tid, state)
            pending = None  # A linked ticket owns the question ledger.
        if state == "assistant_active":
            pending = None
        conn.execute("""
            INSERT INTO whatsapp_conversation_controls
                (workshop_id, customer_phone, mode, conversation_state, active_ticket_id, pending_workshop_question_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workshop_id, customer_phone) DO UPDATE SET
                mode = excluded.mode, conversation_state = excluded.conversation_state,
                active_ticket_id = excluded.active_ticket_id,
                pending_workshop_question_id = excluded.pending_workshop_question_id,
                revision = whatsapp_conversation_controls.revision + 1, updated_at = CURRENT_TIMESTAMP
            """, (wid, phone, projected_mode, state, tid, pending))
    return get_whatsapp_conversation_control(workshop_id=wid, customer_phone=phone)
