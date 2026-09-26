"""Opt-in integration test. The URL must name a disposable, empty database."""
from __future__ import annotations

import json
import os
import unittest
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

import app.db as db
from app.communication import open_customer_questions, pending_workshop_question
from app.models import IntakeState
from app.tickets import add_ticket_note, finalize_ticket_message_delivery, find_ticket_by_id, save_ticket, set_ticket_conversation_state


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "No disposable PostgreSQL test database configured")
class PostgreSQLCommunicationTests(unittest.TestCase):
    def test_fresh_schema_legacy_migration_and_targeted_delivery(self):
        settings = replace(db.settings, database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"],
                           app_env="development", dashboard_admin_password="Disposable-Migration-Test-2026!")
        with patch.object(db, "settings", settings):
            # This test deliberately drops only the new columns in a disposable
            # database to exercise the exact upgrade path from the prior schema.
            db.init_db()
            wid = db.default_workshop_id()
            tid = save_ticket(IntakeState(name="Postgres migration test", telefon="491701234567"), wid)
            db.set_whatsapp_conversation_control(workshop_id=wid, customer_phone="491701234567",
                                                   mode="manual", active_ticket_id=tid)
            old_notes = [{"type": "customer_message", "text": "Preis?", "created_at": "2026-01-01"},
                         {"type": "customer_reply", "text": "Wir melden uns", "created_at": "2026-01-02"}]
            with closing(db.get_conn()) as conn:
                conn.execute("UPDATE tickets SET notes_json = ?, customer_question_open = 1 WHERE workshop_id = ? AND ticket_id = ?",
                             (json.dumps(old_notes), wid, tid))
                conn.execute("""INSERT INTO whatsapp_messages (workshop_id, customer_phone, direction, text, ticket_id)
                                VALUES (?, '491701234567', 'inbound', ?, ?)""", (wid, "Preis?", tid))
                conn.execute("ALTER TABLE tickets DROP COLUMN conversation_state")
                conn.execute("ALTER TABLE whatsapp_conversation_controls DROP COLUMN conversation_state")
                conn.execute("ALTER TABLE whatsapp_conversation_controls DROP COLUMN pending_workshop_question_id")
                conn.execute("ALTER TABLE whatsapp_messages DROP COLUMN message_id")
                conn.commit()
            db.init_db()
            ticket = find_ticket_by_id(tid, wid)
            self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")
            self.assertEqual(len(open_customer_questions(ticket)), 1)
            self.assertIsNone(ticket["notes"][1]["reply_to_message_id"])
            before = ticket["notes"]
            db.init_db()
            self.assertEqual(before, find_ticket_by_id(tid, wid)["notes"])
            with closing(db.get_conn()) as conn:
                message = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ?", (wid,)).fetchone()
                self.assertEqual(message["ticket_id"], tid)
                self.assertTrue(message["message_id"].startswith("legacy-wa-"))
            target = before[0]["message_id"]
            add_ticket_note(tid, "Hundert Euro", workshop_id=wid, purpose="workshop_answer",
                            reply_to_message_id=target, message_id="pg-answer", delivery_status="pending")
            self.assertTrue(find_ticket_by_id(tid, wid)["customer_question_open"])
            ticket = finalize_ticket_message_delivery(tid, "pg-answer", "sent", wid)
            self.assertFalse(ticket["customer_question_open"])
            self.assertEqual(ticket["status"], "offen")
            control = db.get_whatsapp_conversation_control(workshop_id=wid, customer_phone="491701234567")
            self.assertEqual(control["conversation_state"], "workshop_active")
            self.assertEqual(control["mode"], "manual")
            add_ticket_note(tid, "Filter wechseln?", workshop_id=wid, purpose="workshop_question", message_id="pg-question")
            ticket = set_ticket_conversation_state(tid, "assistant_active", wid)
            self.assertIsNone(pending_workshop_question(ticket))
            self.assertTrue(ticket["notes"][-1]["response_cancelled_at"])
            with closing(db.get_conn()) as conn:
                conn.execute("""INSERT INTO whatsapp_messages
                                (workshop_id, customer_phone, direction, ticket_id, dispatch_state)
                                VALUES (?, '491701234567', 'outbound', ?, 'sending')""", (wid, tid))
                conn.commit()
            with self.assertRaises(ValueError):
                set_ticket_conversation_state(tid, "assistant_active", wid)


if __name__ == "__main__":
    unittest.main()
