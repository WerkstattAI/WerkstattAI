from __future__ import annotations

import os
import sqlite3

from app.config import settings
from app.security import hash_password


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))


def _data_dir() -> str:
    return os.path.join(_project_root(), "data")


def _db_path() -> str:
    return os.path.join(_data_dir(), "werkstattai.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(_data_dir(), exist_ok=True)

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def default_workshop_id() -> str:
    return settings.default_workshop_id


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    os.makedirs(_data_dir(), exist_ok=True)

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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _add_column_if_missing(conn, "workshops", "services", "TEXT")
        _add_column_if_missing(conn, "workshops", "pricing_info", "TEXT")
        _add_column_if_missing(conn, "workshops", "towing_info", "TEXT")

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

        conn.execute(
            """
            INSERT INTO users (
                email,
                password_hash,
                workshop_id,
                role
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                password_hash = excluded.password_hash,
                workshop_id = excluded.workshop_id,
                role = excluded.role,
                updated_at = CURRENT_TIMESTAMP
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
            INSERT OR IGNORE INTO workshops (
                id,
                name,
                address,
                phone,
                email,
                opening_hours,
                services,
                pricing_info,
                towing_info
            )
            VALUES (
                ?,
                'Meier Werkstatt Family',
                'Arnstorfer Str. 5',
                '123456789',
                'Meierfamily@hjh.de',
                'Montag bis Freitag: 09:00-17:00; Samstag: 09:00-14:00; Sonntag: geschlossen',
                'Autoreparaturen, Reifenwechsel, Polieren',
                'Aktuell gibt es noch keine festen Preisangaben. Die Werkstatt prueft Anfragen individuell und meldet sich mit einer Einschaetzung.',
                'Unsere Werkstatt kooperiert mit dem Abschleppdienst Mueller.'
            )
            """,
            (default_workshop_id(),),
        )

        conn.execute(
            """
            UPDATE workshops
            SET
                name = ?,
                address = ?,
                phone = ?,
                email = ?,
                opening_hours = ?,
                services = ?,
                pricing_info = ?,
                towing_info = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "Meier Werkstatt Family",
                "Arnstorfer Str. 5",
                "123456789",
                "Meierfamily@hjh.de",
                "Montag bis Freitag: 09:00-17:00; Samstag: 09:00-14:00; Sonntag: geschlossen",
                "Autoreparaturen, Reifenwechsel, Polieren",
                "Aktuell gibt es noch keine festen Preisangaben. Die Werkstatt prueft Anfragen individuell und meldet sich mit einer Einschaetzung.",
                "Unsere Werkstatt kooperiert mit dem Abschleppdienst Mueller.",
                default_workshop_id(),
            ),
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            """
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

        conn.commit()
