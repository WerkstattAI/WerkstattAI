from __future__ import annotations

import json
import unittest
from contextlib import closing
from datetime import datetime, timezone

import test_conversation_flows  # noqa: F401 - isolated application configuration
import test_whatsapp_reliability as fixtures
import app.db as db
from app.communication import open_customer_questions
from app.models import IntakeState
from app.tickets import add_ticket_note, finalize_ticket_message_delivery, save_ticket, find_ticket_by_id
from app.whatsapp import (finalize_whatsapp_dispatch,
                          save_whatsapp_message, update_whatsapp_message_status)


class DispatchFinalizationTests(unittest.TestCase):
    setUp = fixtures.WhatsAppReliabilityTests.setUp
    tearDown = fixtures.WhatsAppReliabilityTests.tearDown

    def row(self, mid="core-claim-001"):
        with closing(db.get_conn()) as conn:
            return dict(conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND message_id = ?",
                                     (self.wid, mid)).fetchone())

    def claim(self, *, mid="core-claim-001", status="unknown", dispatch_state="sending"):
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="outbound",
                              message_id=mid, status=status, dispatch_state=dispatch_state,
                              payload={"sender_role": "assistant", "purpose": "intake_question"})
        return self.row(mid)

    def test_upgrade_gives_old_sending_rows_fresh_grace_exactly_once(self):
        row = self.claim()
        with closing(db.get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET created_at = '2000-01-01' WHERE id = ?", (row["id"],))
            conn.execute("ALTER TABLE whatsapp_messages DROP COLUMN dispatch_started_at")
            conn.commit()
        before = datetime.now(timezone.utc)
        db.init_db()
        upgraded = self.row()
        self.assertGreaterEqual(datetime.fromisoformat(upgraded["dispatch_started_at"]), before)
        self.assertEqual(upgraded["dispatch_state"], "sending")
        self.assertEqual(upgraded["status"], "unknown")
        db.init_db()
        self.assertEqual(self.row()["dispatch_started_at"], upgraded["dispatch_started_at"])

    def test_stale_attempt_token_cannot_finalize_a_newer_claim(self):
        before = self.claim()
        result = finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=before["message_id"], status="sent",
                                             expected_dispatch_started_at="2000-01-01T00:00:00+00:00",
                                             metadata_updates={"wrong_attempt": True})
        self.assertFalse(result["finalized"])
        self.assertEqual(self.row(), before)

    def test_terminal_status_is_immutable_even_with_inconsistent_sending_marker(self):
        for index, status in enumerate(("sent", "sent_local", "delivered", "read", "failed")):
            with self.subTest(status=status):
                before = self.claim(mid=f"terminal-core-{index}", status=status)
                result = finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=before["message_id"],
                                                     status="sent", metadata_updates={"overwritten": True})
                self.assertFalse(result["finalized"])
                self.assertEqual(self.row(before["message_id"]), before)

    def test_unknown_keeps_original_claim_until_late_meta_resolves_it(self):
        before = self.claim()
        result = finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=before["message_id"], status="unknown",
                                             wa_message_id="wamid.core-unknown", metadata_updates={"meta_error": "timeout"})
        self.assertFalse(result["finalized"])
        self.assertEqual(result["dispatch_state"], "sending")
        self.assertEqual(result["dispatch_started_at"], before["dispatch_started_at"])
        self.assertTrue(update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.core-unknown", status="delivered"))
        self.assertEqual(self.row()["dispatch_state"], "complete")
        self.assertEqual(self.row()["status"], "delivered")

    def test_legacy_complete_unknown_keeps_its_state_and_records_late_event(self):
        self.claim(dispatch_state="complete")
        with closing(db.get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET wa_message_id = 'wamid.legacy-unknown' WHERE workshop_id = ?", (self.wid,))
            conn.commit()
        update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.legacy-unknown", status="delivered")
        row = self.row()
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["dispatch_state"], "complete")
        self.assertEqual(json.loads(row["payload_json"])["status_events"], [{"status": "delivered"}])

    def test_failed_ticket_delivery_cannot_be_relabelled_sent(self):
        tid = save_ticket(IntakeState(telefon=self.phone), self.wid)
        add_ticket_note(tid, "Preis?", workshop_id=self.wid, purpose="customer_question", message_id="question")
        add_ticket_note(tid, "Hundert Euro", workshop_id=self.wid, purpose="workshop_answer", message_id="answer",
                        reply_to_message_id="question", delivery_status="pending")
        finalize_ticket_message_delivery(tid, "answer", "failed", self.wid)
        before = find_ticket_by_id(tid, self.wid)
        with self.assertRaises(ValueError):
            finalize_ticket_message_delivery(tid, "answer", "sent", self.wid)
        self.assertEqual(find_ticket_by_id(tid, self.wid), before)
        self.assertEqual(len(open_customer_questions(before)), 1)



if __name__ == "__main__":
    unittest.main()
