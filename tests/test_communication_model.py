from __future__ import annotations

import gc
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

import test_conversation_flows  # noqa: F401 - isolated application settings
import app.db as db
from app.communication import normalize_ticket_notes, open_customer_questions, pending_workshop_question
from app.models import IntakeState
from app.tickets import (
    add_ticket_note, finalize_ticket_message_delivery, find_ticket_by_id, save_ticket,
    set_ticket_conversation_state, validate_workshop_message,
)


class CommunicationModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="werkstattai-communication-")
        self.environment = patch.dict(os.environ, {"WERKSTATTAI_SQLITE_PATH": os.path.join(self.temp.name, "test.db")})
        self.environment.start()
        db.init_db()
        self.wid = db.default_workshop_id()
        self.tid = save_ticket(IntakeState(name="Communication test", telefon="491701234567"), self.wid)

    def tearDown(self):
        self.environment.stop()
        gc.collect()
        self.temp.cleanup()

    def note(self, text, purpose, **kwargs):
        return add_ticket_note(self.tid, text, workshop_id=self.wid, purpose=purpose, **kwargs)

    def ticket(self):
        return find_ticket_by_id(self.tid, self.wid)

    def test_answer_resolves_only_its_target_and_never_changes_ticket_status(self):
        self.note("Preis?", "customer_question", message_id="q1")
        self.note("Dauer?", "customer_question", message_id="q2")
        ticket = self.note("Zwei Tage", "workshop_answer", reply_to_message_id="q2")
        self.assertEqual([note["message_id"] for note in open_customer_questions(ticket)], ["q1"])
        self.assertIsNone(ticket["notes"][0]["resolved_at"])
        self.assertTrue(ticket["notes"][1]["resolved_at"])
        self.assertTrue(ticket["customer_question_open"])
        self.assertEqual(ticket["status"], "offen")

    def test_information_preserves_questions_and_status(self):
        self.note("Preis?", "customer_question", message_id="q1")
        ticket = self.note("Wir haben Ihr Fahrzeug erhalten", "workshop_notification")
        self.assertEqual(ticket["status"], "offen")
        self.assertTrue(ticket["customer_question_open"])
        self.assertEqual(ticket["notes"][-1]["type"], "customer_reply")
        self.assertIsNone(ticket["notes"][-1]["reply_to_message_id"])

    def test_customer_information_can_require_work_without_opening_question(self):
        ticket = self.note("Bitte neue Telefonnummer nutzen", "customer_information", requires_human_action=True)
        self.assertFalse(ticket["customer_question_open"])
        self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")

    def test_automatic_answer_does_not_open_workshop_task(self):
        self.note("Status?", "customer_information", message_id="q", requires_human_action=False)
        ticket = self.note("Der Status ist offen", "automatic_answer", reply_to_message_id="q")
        self.assertFalse(ticket["customer_question_open"])
        self.assertEqual(ticket["conversation_state"], "assistant_active")
        self.assertEqual(ticket["notes"][-1]["type"], "assistant_message")

    def test_workshop_question_and_customer_response_are_linked(self):
        ticket = self.note("Dürfen wir den Filter wechseln?", "workshop_question", message_id="wq")
        self.assertEqual(ticket["conversation_state"], "waiting_for_customer")
        self.assertEqual(pending_workshop_question(ticket)["message_id"], "wq")
        ticket = self.note("Ja", "customer_information", reply_to_message_id="wq")
        self.assertEqual(ticket["conversation_state"], "workshop_active")
        self.assertIsNone(pending_workshop_question(ticket))
        self.assertFalse(ticket["customer_question_open"])

    def test_notification_does_not_cancel_pending_workshop_question(self):
        self.note("Ist das Kennzeichen korrekt?", "workshop_question", message_id="wq")
        ticket = self.note("Ihr Fahrzeug steht in der Halle", "workshop_notification")
        self.assertEqual(ticket["conversation_state"], "waiting_for_customer")
        self.assertEqual(pending_workshop_question(ticket)["message_id"], "wq")

    def test_answer_requires_unambiguous_open_question(self):
        with self.assertRaises(ValueError):
            self.note("Antwort", "workshop_answer")
        self.note("Preis?", "customer_question", message_id="q1")
        self.assertEqual(validate_workshop_message(self.ticket(), "workshop_answer"), "q1")
        self.note("Dauer?", "customer_question", message_id="q2")
        with self.assertRaises(ValueError):
            self.note("Antwort", "workshop_answer")
        with self.assertRaises(ValueError):
            self.note("Antwort", "workshop_answer", reply_to_message_id="foreign")
        with self.assertRaises(ValueError):
            self.note("Info", "workshop_notification", reply_to_message_id="q1")

    def test_pending_and_unknown_answer_reserve_but_do_not_resolve_question(self):
        self.note("Preis?", "customer_question", message_id="q")
        ticket = self.note("Hundert Euro", "workshop_answer", reply_to_message_id="q", message_id="a", delivery_status="pending")
        self.assertTrue(ticket["customer_question_open"])
        with self.assertRaises(ValueError):
            validate_workshop_message(ticket, "workshop_answer", "q")
        ticket = finalize_ticket_message_delivery(self.tid, "a", "unknown", self.wid)
        self.assertTrue(ticket["customer_question_open"])
        with self.assertRaises(ValueError):
            self.note("Nochmal", "workshop_answer", reply_to_message_id="q")
        ticket = finalize_ticket_message_delivery(self.tid, "a", "sent", self.wid)
        self.assertFalse(ticket["customer_question_open"])
        self.assertEqual(ticket["conversation_state"], "workshop_active")

    def test_definitive_failure_releases_question_reservation(self):
        self.note("Preis?", "customer_question", message_id="q")
        self.note("Hundert Euro", "workshop_answer", reply_to_message_id="q", message_id="a", delivery_status="pending")
        ticket = finalize_ticket_message_delivery(self.tid, "a", "failed", self.wid)
        self.assertTrue(ticket["customer_question_open"])
        self.assertEqual(validate_workshop_message(ticket, "workshop_answer", "q"), "q")

    def test_late_delivery_completion_does_not_discard_customer_response(self):
        self.note("Filter wechseln?", "workshop_question", message_id="wq", delivery_status="pending")
        self.note("Ja", "customer_information", reply_to_message_id="wq")
        ticket = finalize_ticket_message_delivery(self.tid, "wq", "sent", self.wid)
        self.assertEqual(ticket["conversation_state"], "workshop_active")
        self.assertIsNone(pending_workshop_question(ticket))

    def test_same_message_id_is_idempotent_but_conflicting_content_is_rejected(self):
        self.note("Preis?", "customer_question", message_id="same")
        self.note("Preis?", "customer_question", message_id="same")
        self.assertEqual(len(self.ticket()["notes"]), 1)
        with self.assertRaises(ValueError):
            self.note("Andere Nachricht", "customer_question", message_id="same")

    def test_ticket_state_is_canonical_for_controls_and_changes_revision(self):
        before = db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491701234567",
                                                       active_ticket_id=self.tid, mode="assistant")
        self.note("Dauer?", "customer_question")
        control = db.get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491701234567")
        self.assertEqual(control["conversation_state"], "waiting_for_workshop")
        self.assertEqual(control["mode"], "manual")
        self.assertGreater(control["revision"], before["revision"])
        set_ticket_conversation_state(self.tid, "assistant_active", self.wid)
        control = db.get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491701234567")
        self.assertEqual(control["mode"], "assistant")
        self.assertTrue(self.ticket()["customer_question_open"])

    def test_unassigned_conversation_retains_own_pending_question(self):
        control = db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491709876543",
            conversation_state="waiting_for_customer", pending_workshop_question_id="outbound-question")
        self.assertEqual(control["pending_workshop_question_id"], "outbound-question")
        self.assertEqual(control["mode"], "manual")
        control = db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491709876543", mode="assistant")
        self.assertIsNone(control["pending_workshop_question_id"])

    def test_explicit_resume_retires_workshop_question_but_keeps_customer_question_open(self):
        self.note("Preis?", "customer_question", message_id="cq")
        self.note("Filter wechseln?", "workshop_question", message_id="wq")
        ticket = set_ticket_conversation_state(self.tid, "assistant_active", self.wid)
        self.assertIsNone(pending_workshop_question(ticket))
        self.assertTrue(ticket["notes"][1]["response_cancelled_at"])
        self.assertTrue(ticket["customer_question_open"])
        self.assertIsNone(ticket["notes"][0]["resolved_at"])
        ticket = self.note("Ihr Fahrzeug ist angekommen", "workshop_notification")
        self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")

    def test_resume_is_blocked_during_inflight_send_with_or_without_ticket(self):
        self.note("Filter wechseln?", "workshop_question", message_id="wq")
        with closing(db.get_conn()) as conn:
            conn.execute("""INSERT INTO whatsapp_messages
                (workshop_id, customer_phone, direction, ticket_id, dispatch_state)
                VALUES (?, '491701234567', 'outbound', ?, 'sending')""", (self.wid, self.tid))
            conn.execute("""INSERT INTO whatsapp_messages
                (workshop_id, customer_phone, direction, dispatch_state)
                VALUES (?, '491709876543', 'outbound', 'sending')""", (self.wid,))
            conn.commit()
        with self.assertRaises(ValueError):
            set_ticket_conversation_state(self.tid, "assistant_active", self.wid)
        with self.assertRaises(ValueError):
            db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone="491709876543", mode="assistant")
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_customer")
        self.assertIsNotNone(pending_workshop_question(self.ticket()))

    def test_cross_tenant_note_and_control_updates_are_rejected(self):
        with self.assertRaises(KeyError):
            add_ticket_note(self.tid, "Fremd", workshop_id="other", purpose="customer_question")
        with self.assertRaises(ValueError):
            db.set_whatsapp_conversation_control(workshop_id="other", customer_phone="491701234567",
                                                   active_ticket_id=self.tid, mode="manual")
        self.assertEqual(self.ticket()["notes"], [])

    def test_legacy_closed_aggregate_is_preserved_without_invented_reply_link(self):
        old = [{"type": "customer_message", "text": "Dauer?", "created_at": "2026-01-01"},
               {"type": "customer_reply", "text": "Zwei Tage", "created_at": "2026-01-02"}]
        with closing(db.get_conn()) as conn:
            conn.execute("UPDATE tickets SET notes_json = ?, customer_question_open = 0 WHERE ticket_id = ?", (json.dumps(old), self.tid))
            conn.commit()
        db.init_db()
        ticket = self.ticket()
        self.assertFalse(ticket["customer_question_open"])
        self.assertTrue(ticket["notes"][0]["legacy_resolution_uncertain"])
        self.assertIsNone(ticket["notes"][0]["resolved_at"])
        self.assertIsNone(ticket["notes"][1]["reply_to_message_id"])
        first_migration = ticket["notes"]
        db.init_db()
        self.assertEqual(self.ticket()["notes"], first_migration)

    def test_ambiguous_legacy_questions_stay_open_and_ids_are_stable(self):
        old = [{"type": "customer_message", "text": "Preis?"}, {"type": "customer_reply", "text": "Hallo"}]
        notes = normalize_ticket_notes(old, workshop_id=self.wid, ticket_id=self.tid, legacy_question_open=True)
        self.assertEqual(len(open_customer_questions({"notes": notes})), 1)
        self.assertIsNone(notes[1]["reply_to_message_id"])
        self.assertEqual(notes, normalize_ticket_notes(notes, workshop_id=self.wid, ticket_id=self.tid, legacy_question_open=True))
        other = normalize_ticket_notes(old, workshop_id="other", ticket_id=self.tid)
        self.assertNotEqual(notes[0]["message_id"], other[0]["message_id"])

    def test_postgres_lock_and_placeholder_adapter_use_tenant_scoped_parameters(self):
        conn = Mock()
        with patch.object(db, "is_postgres", return_value=True):
            db.lock_communication_scope(conn, "tenant-a")
        conn.execute.assert_called_once_with("SELECT pg_advisory_xact_lock(hashtext(?))", ("communication:tenant-a",))
        self.assertEqual(db.PostgresConnection._convert_placeholders(conn.execute.call_args.args[0]),
                         "SELECT pg_advisory_xact_lock(hashtext(%s))")
        conn.reset_mock()
        with patch.object(db, "is_postgres", return_value=False):
            db.lock_communication_scope(conn, "tenant-a")
        conn.execute.assert_not_called()


class MigrationDialectTests(unittest.TestCase):
    def fixture(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE tickets (workshop_id TEXT, ticket_id TEXT, notes_json TEXT, customer_question_open INTEGER)")
        conn.execute("CREATE TABLE whatsapp_conversation_controls (workshop_id TEXT, customer_phone TEXT, mode TEXT, active_ticket_id TEXT)")
        conn.execute("CREATE TABLE whatsapp_messages (id INTEGER, workshop_id TEXT, direction TEXT)")
        conn.execute("INSERT INTO tickets VALUES ('tenant', 'ticket', ?, 1)",
                     (json.dumps([{"type": "customer_message", "text": "Preis?"}]),))
        conn.execute("INSERT INTO whatsapp_conversation_controls VALUES ('tenant', '49170', 'manual', 'ticket')")
        conn.execute("INSERT INTO whatsapp_messages VALUES (1, 'tenant', 'inbound')")
        return conn

    def test_sqlite_additive_migration_preserves_legacy_links_and_is_idempotent(self):
        with closing(self.fixture()) as conn, patch.object(db, "is_postgres", return_value=False):
            db._migrate_customer_communication(conn)
            ticket = dict(conn.execute("SELECT * FROM tickets").fetchone())
            message = dict(conn.execute("SELECT * FROM whatsapp_messages").fetchone())
            self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")
            self.assertTrue(json.loads(ticket["notes_json"])[0]["message_id"])
            self.assertTrue(message["message_id"].startswith("legacy-wa-"))
            db._migrate_customer_communication(conn)
            self.assertEqual(ticket, dict(conn.execute("SELECT * FROM tickets").fetchone()))
            self.assertEqual(message, dict(conn.execute("SELECT * FROM whatsapp_messages").fetchone()))
            self.assertEqual(conn.execute("SELECT active_ticket_id FROM whatsapp_conversation_controls").fetchone()[0], "ticket")

    def test_postgres_introspection_path_and_portable_migration_statements(self):
        with closing(self.fixture()) as conn:
            calls = []

            class PostgresIntrospectionAdapter:
                def execute(self, sql, params=()):
                    calls.append((sql, params))
                    if "information_schema.columns" in sql:
                        columns = conn.execute("PRAGMA table_info(" + params[0] + ")").fetchall()
                        exists = any(row["name"] == params[1] for row in columns)
                        return conn.execute("SELECT 1 WHERE ?", (int(exists),))
                    return conn.execute(sql, params)

            with patch.object(db, "is_postgres", return_value=True):
                db._migrate_customer_communication(PostgresIntrospectionAdapter())
            self.assertTrue(any("information_schema.columns" in sql for sql, _ in calls))
            self.assertFalse(any("PRAGMA" in sql or "AUTOINCREMENT" in sql for sql, _ in calls))
            self.assertEqual(conn.execute("SELECT conversation_state FROM tickets").fetchone()[0], "waiting_for_workshop")

    def test_migration_preserves_opaque_historical_note_entries(self):
        with closing(self.fixture()) as conn, patch.object(db, "is_postgres", return_value=False):
            original = json.dumps([{"type": "customer_message", "text": "Preis?"}, "opaque historical item"])
            conn.execute("UPDATE tickets SET notes_json = ?", (original,))
            db._migrate_customer_communication(conn)
            self.assertEqual(conn.execute("SELECT notes_json FROM tickets").fetchone()[0], original)


if __name__ == "__main__":
    unittest.main()
