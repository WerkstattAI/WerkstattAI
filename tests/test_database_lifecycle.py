from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import app.db as db


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="werkstattai-db-lifecycle-"))
        self.path = Path(self.directory) / "lifecycle.sqlite"
        self.stack.enter_context(patch.dict(os.environ, {"WERKSTATTAI_SQLITE_PATH": str(self.path)}))
        self.stack.enter_context(patch.object(db, "settings", replace(db.settings, database_url=None)))
        with self.connection() as conn:
            conn.execute("CREATE TABLE entries (value TEXT)")

    def connection(self):
        conn = db.get_conn()
        # Keep a live reference and close it even if a regression assertion fails.
        self.addCleanup(conn.close)
        return conn

    def assert_closed(self, conn):
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            conn.execute("SELECT 1")

    def test_context_commits_closes_and_allows_immediate_file_removal(self):
        with self.connection() as conn:
            conn.execute("INSERT INTO entries VALUES ('committed')")
        self.assert_closed(conn)
        with self.connection() as reader:
            self.assertEqual(reader.execute("SELECT value FROM entries").fetchone()[0], "committed")
        # On Windows this also proves that no file handle survives context exit.
        self.path.unlink()
        self.assertFalse(self.path.exists())

    def test_context_rolls_back_and_closes_on_base_exception(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.connection() as conn:
                conn.execute("INSERT INTO entries VALUES ('rolled back')")
                raise KeyboardInterrupt
        self.assert_closed(conn)
        with self.connection() as reader:
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)

    def test_context_closes_when_commit_fails(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection() as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
                conn.execute("""CREATE TABLE children (parent_id INTEGER REFERENCES parents(id)
                                DEFERRABLE INITIALLY DEFERRED)""")
                conn.execute("INSERT INTO children VALUES (123)")
        self.assert_closed(conn)

    def test_borrowed_contexts_do_not_close_or_commit_outer_transaction(self):
        with db.atomic_database() as outer:
            raw = outer.connection
            self.addCleanup(raw.close)
            with db.get_conn() as borrowed:
                self.assertIs(borrowed, outer)
                borrowed.execute("INSERT INTO entries VALUES ('shared')")
                borrowed.commit()
            with closing(db.get_conn()) as borrowed:
                self.assertIs(borrowed, outer)
            with db.atomic_database() as nested:
                self.assertIs(nested, outer)
                self.assertEqual(nested.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 1)
            with closing(sqlite3.connect(self.path)) as observer:
                self.assertEqual(observer.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)
        self.assert_closed(raw)
        with self.connection() as reader:
            self.assertEqual(reader.execute("SELECT value FROM entries").fetchone()[0], "shared")

    def test_outer_transaction_rolls_back_and_closes_after_nested_exception(self):
        with self.assertRaisesRegex(RuntimeError, "transaction rolled back"):
            with db.atomic_database() as outer:
                raw = outer.connection
                self.addCleanup(raw.close)
                try:
                    with db.get_conn() as borrowed:
                        borrowed.execute("INSERT INTO entries VALUES ('rolled back')")
                        raise ValueError("nested failure")
                except ValueError:
                    pass
                self.assertEqual(outer.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 1)
        self.assert_closed(raw)
        with self.connection() as reader:
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
