from __future__ import annotations

import os
import sqlite3


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


def init_db() -> None:
    os.makedirs(_data_dir(), exist_ok=True)

    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

                followup_questions_json TEXT NOT NULL DEFAULT '[]',
                followup_answers_json TEXT NOT NULL DEFAULT '[]',
                notes_json TEXT NOT NULL DEFAULT '[]'
            )
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

        conn.commit()