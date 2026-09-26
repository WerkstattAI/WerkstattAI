from __future__ import annotations

import asyncio
import gc
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

import app.db as db
import app.main as main
from app.conversation_sessions import load_session_state, save_session_state
from app.models import ChatResponse, IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket
from app.whatsapp import (
    WhatsAppSendResult, build_signature, parse_meta_messages, prepare_whatsapp_inbound,
    save_whatsapp_message, send_whatsapp_text_message, whatsapp_customer_service_window_for_phone,
)


class WhatsAppReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="werkstattai-wa-reliability-", ignore_cleanup_errors=True)
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {"WERKSTATTAI_SQLITE_PATH": os.path.join(self.temp.name, "db.sqlite")}))
        self.stack.enter_context(patch.object(db, "settings", replace(db.settings, database_url=None, app_env="development")))
        self.stack.enter_context(patch.object(main, "settings", replace(main.settings, database_url=None, app_env="development",
                                                                      whatsapp_access_token="mock-token", whatsapp_app_secret="mock-secret")))
        db.init_db()
        self.wid = db.default_workshop_id()
        self.phone = "4915700012345"
        with closing(db.get_conn()) as conn:
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ?, subscription_status = 'active' WHERE id = ?",
                         ("reliability-sender", self.wid))
            conn.commit()

    def tearDown(self):
        self.stack.close()
        gc.collect()
        self.temp.cleanup()

    def payload(self, message_id="wamid.reliable", timestamp="now"):
        timestamp = str(int(datetime.now(timezone.utc).timestamp())) if timestamp == "now" else timestamp
        message = {"from": self.phone, "id": message_id, "type": "text", "text": {"body": "Hallo"}}
        if timestamp is not None:
            message["timestamp"] = timestamp
        return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "reliability-sender"}, "messages": [message]}}]}]}

    def request(self, payload):
        body = json.dumps(payload).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return Request({"type": "http", "method": "POST", "path": "/webhooks/whatsapp", "query_string": b"",
                        "headers": [(b"x-hub-signature-256", build_signature(body, "mock-secret").encode())]}, receive)

    def webhook(self, payload):
        return asyncio.run(main.whatsapp_webhook(self.request(payload)))

    def count(self, table):
        with closing(db.get_conn()) as conn:
            return conn.execute(f"SELECT COUNT(*) AS amount FROM {table}").fetchone()["amount"]

    def test_delayed_missing_invalid_and_future_meta_timestamps_do_not_open_window(self):
        old = str(int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()))
        future = str(int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()))
        for index, timestamp in enumerate((old, None, "invalid", future)):
            with self.subTest(timestamp=timestamp), patch.object(main, "process_chat_message") as process, patch.object(main, "send_whatsapp_text_message") as send:
                response = self.webhook(self.payload(f"wamid.old.{index}", timestamp))
                self.assertEqual(response["manual_pending"], 1)
                process.assert_not_called()
                send.assert_not_called()
        self.assertFalse(whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=self.phone)["service_window_open"])

    def test_central_sender_blocks_closed_window_and_allows_current_inbound(self):
        kwargs = dict(phone_number_id="reliability-sender", customer_phone=self.phone, text="Antwort", access_token="mock")
        with patch("app.whatsapp._post_graph_api_json", return_value=(200, {"messages": [{"id": "wamid.sent"}]})) as send:
            self.assertFalse(send_whatsapp_text_message(**kwargs).ok)
            send.assert_not_called()
            save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound")
            self.assertTrue(send_whatsapp_text_message(**kwargs).ok)
            self.assertEqual(send.call_count, 1)

    def test_ticket_access_uses_verified_sender_not_entered_callback_number(self):
        callback = "01709998888"
        for message in ("Audi A4 2019 120000 km", "Inspektion und Ölwechsel", callback, "Private Kundin"):
            response = main.process_chat_message(workshop_id=self.wid, session_id=main.whatsapp_session_id(self.phone),
                                                message=message, channel="whatsapp", phone=self.phone)
        self.assertTrue(response.done)
        ticket_id = response.data["ticket_id"]
        ticket = find_ticket_by_id(ticket_id, self.wid)
        self.assertEqual(ticket["verified_customer_phone"], self.phone)
        self.assertNotEqual(ticket["telefon"], self.phone)
        owner = main.process_chat_message(workshop_id=self.wid, session_id=main.whatsapp_session_id(self.phone),
                                          message=f"Zusammenfassung {ticket_id}", channel="whatsapp", phone=self.phone)
        self.assertIn("Private Kundin", owner.reply)
        other = main.process_chat_message(workshop_id=self.wid, session_id="whatsapp:491709998888",
                                          message=f"Zusammenfassung {ticket_id}", channel="whatsapp", phone="491709998888")
        self.assertNotIn("Private Kundin", other.reply)
        self.assertNotIn("Audi A4", other.reply)

    def test_unverified_legacy_ticket_contact_number_does_not_grant_access(self):
        ticket_id = save_ticket(IntakeState(name="Legacy secret", telefon=self.phone), workshop_id=self.wid)
        response = main.process_chat_message(workshop_id=self.wid, session_id=main.whatsapp_session_id(self.phone),
                                              message=f"Zusammenfassung {ticket_id}", channel="whatsapp", phone=self.phone)
        self.assertNotIn("Legacy secret", response.reply)

    def test_missing_verified_whatsapp_sender_cannot_process_intake(self):
        with self.assertRaises(HTTPException):
            main.process_chat_message(workshop_id=self.wid, session_id="whatsapp:unknown", message="Hallo",
                                      channel="whatsapp", phone=None)
        self.assertEqual(self.count("conversation_sessions"), 0)

    def test_reprocessing_rolls_back_ticket_note_session_and_inbound_together(self):
        attempts = 0

        def process(**kwargs):
            nonlocal attempts
            attempts += 1
            state = IntakeState(ticket_id="WS-RELIABILITY-ROLLBACK", fahrzeug="Test", telefon=self.phone)
            tid = save_ticket(state, workshop_id=self.wid)
            add_ticket_note(tid, "Exactly one note", workshop_id=self.wid)
            save_session_state("reliability-session", state, workshop_id=self.wid, channel="whatsapp")
            if attempts == 1:
                raise RuntimeError("temporary database/business error")
            return ChatResponse(reply="Saved", done=True, data={"ticket_id": tid})

        with patch.object(main, "process_chat_message", side_effect=process), patch.object(main, "send_whatsapp_text_message", return_value=WhatsAppSendResult(True, 200, "wamid.reply", {})) as send:
            with self.assertRaises(HTTPException) as error:
                self.webhook(self.payload())
            self.assertEqual(error.exception.status_code, 503)
            for table in ("tickets", "conversation_sessions", "whatsapp_messages", "whatsapp_events"):
                self.assertEqual(self.count(table), 0, table)
            self.assertEqual(self.webhook(self.payload())["processed"], 1)
            self.assertEqual(self.webhook(self.payload())["ignored"], 1)
            self.assertEqual(attempts, 2)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(len(find_ticket_by_id("WS-RELIABILITY-ROLLBACK", self.wid)["notes"]), 1)
        self.assertEqual(load_session_state("reliability-session", self.wid, channel="whatsapp").ticket_id, "WS-RELIABILITY-ROLLBACK")

    def test_retryable_send_resumes_durable_reply_without_repeating_business_processing(self):
        with patch.object(main, "process_chat_message", return_value=ChatResponse(reply="Saved reply", done=False)) as process, patch.object(main, "send_whatsapp_text_message", side_effect=[WhatsAppSendResult(False, 503, None, {}, "busy"), WhatsAppSendResult(True, 200, "wamid.sent", {})]) as send:
            with self.assertRaises(HTTPException) as error:
                self.webhook(self.payload())
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(self.webhook(self.payload())["processed"], 1)
            self.assertEqual(self.webhook(self.payload())["ignored"], 1)
            self.assertEqual(process.call_count, 1)
            self.assertEqual(send.call_count, 2)
        self.assertEqual(self.count("whatsapp_messages"), 2)

    def test_timeout_or_crash_after_send_claim_is_never_blindly_resent(self):
        with patch.object(main, "process_chat_message", return_value=ChatResponse(reply="Saved", done=False)) as process, patch.object(main, "send_whatsapp_text_message", return_value=WhatsAppSendResult(False, None, None, {}, "timeout")) as send:
            self.assertEqual(self.webhook(self.payload())["replies"][0]["send_status"], "unknown")
            self.assertEqual(self.webhook(self.payload())["ignored"], 1)
            self.assertEqual(process.call_count, 1)
            self.assertEqual(send.call_count, 1)
        with patch.object(main, "process_chat_message", return_value=ChatResponse(reply="Another", done=False)), patch.object(main, "send_whatsapp_text_message", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.webhook(self.payload("wamid.crash"))
        with patch.object(main, "send_whatsapp_text_message") as send:
            self.assertEqual(self.webhook(self.payload("wamid.crash"))["ignored"], 1)
            send.assert_not_called()

    def test_employee_takeover_during_send_is_not_reversed(self):
        tid = save_ticket(IntakeState(ticket_id="WS-RELIABILITY-CONTROL", telefon=self.phone), workshop_id=self.wid)

        def send(**kwargs):
            db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="manual", active_ticket_id=tid)
            return WhatsAppSendResult(True, 200, "wamid.reply", {})

        with patch.object(main, "process_chat_message", return_value=ChatResponse(reply="Reply", done=True, data={"ticket_id": tid})), patch.object(main, "send_whatsapp_text_message", side_effect=send):
            self.webhook(self.payload())
        control = db.get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)
        self.assertEqual(control["mode"], "manual")
        self.assertEqual(control["active_ticket_id"], tid)

    def test_takeover_then_release_invalidates_previously_prepared_reply(self):
        inbound = parse_meta_messages(self.payload())[0]
        prepare_whatsapp_inbound(workshop_id=self.wid, message=inbound, process_message=lambda: ChatResponse(reply="Old reply", done=False))
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="manual")
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")
        with patch.object(main, "send_whatsapp_text_message") as send:
            response = self.webhook(self.payload())
            self.assertEqual(response["manual_pending"], 1)
            send.assert_not_called()

    def test_duplicate_concurrent_webhooks_only_process_and_send_once(self):
        payload = self.payload()
        with patch.object(main, "process_chat_message", return_value=ChatResponse(reply="Once", done=False)) as process, patch.object(main, "send_whatsapp_text_message", return_value=WhatsAppSendResult(True, 200, "wamid.once", {})) as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.webhook(payload), range(2)))
            self.assertEqual(process.call_count, 1)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(sum(result["processed"] for result in results), 1)
        self.assertEqual(self.count("whatsapp_messages"), 2)

    def test_parallel_ticket_notes_are_all_preserved(self):
        ticket_id = save_ticket(IntakeState(telefon=self.phone), workshop_id=self.wid)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda index: add_ticket_note(ticket_id, f"Note {index}", workshop_id=self.wid), range(12)))
        notes = find_ticket_by_id(ticket_id, self.wid)["notes"]
        self.assertEqual({note["text"] for note in notes}, {f"Note {index}" for index in range(12)})
        self.assertEqual(len(notes), 12)

    def test_migration_recovers_original_meta_timestamp_without_replaying_old_rows(self):
        old = str(int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()))
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound",
                              wa_message_id="wamid.legacy", payload={"timestamp": old})
        with closing(db.get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET customer_message_at = NULL")
            conn.commit()
        db.init_db()
        self.assertFalse(whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=self.phone)["service_window_open"])
        with closing(db.get_conn()) as conn:
            row = conn.execute("SELECT customer_message_at, processing_state FROM whatsapp_messages").fetchone()
        self.assertIsNotNone(row["customer_message_at"])
        self.assertEqual(row["processing_state"], "complete")


if __name__ == "__main__":
    unittest.main()
