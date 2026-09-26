from __future__ import annotations

import gc
import json
import os
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

import test_conversation_flows  # noqa: F401 - isolated app configuration
from fastapi.testclient import TestClient

from app.config import settings
from app.conversation_sessions import load_session_state, save_session_state
from app.customer_sessions import BROWSER_COOKIE
from app.db import get_conn, init_db
from app.main import app
from app.models import IntakeState
from app.tickets import find_ticket_by_id, save_ticket


class WebSessionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="werkstattai-web-sessions-")
        self.environment = patch.dict(os.environ, {
            "WERKSTATTAI_SQLITE_PATH": os.path.join(self.directory.name, "sessions.db"),
        })
        self.environment.start()
        init_db()
        self.workshop = settings.default_workshop_id
        self.first = TestClient(app)
        self.second = TestClient(app)

    def tearDown(self):
        self.first.close()
        self.second.close()
        gc.collect()
        self.environment.stop()
        self.directory.cleanup()

    def send(self, client, message, *, sid="shared-public-id", phone=None):
        response = client.post("/chat", json={"workshop_id": self.workshop,
            "session_id": sid, "message": message, "phone": phone})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def make_ticket(self, client):
        for message in ("Audi A4 2019 120000 km", "Inspektion und Ölwechsel", "0170 1234567", "Private Testperson"):
            result = self.send(client, message)
        self.assertTrue(result["done"], result)
        return result["data"]["ticket_id"]

    def test_browser_cookie_is_httponly_and_reused_on_page_reload(self):
        response = self.first.get("/assistant", params={"workshop_id": self.workshop})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        cookie = self.first.cookies.get(BROWSER_COOKIE)
        self.assertTrue(cookie)
        self.first.get("/assistant", params={"workshop_id": self.workshop})
        self.assertEqual(self.first.cookies.get(BROWSER_COOKIE), cookie)

    def test_same_client_session_id_in_another_browser_cannot_open_ticket(self):
        ticket = self.make_ticket(self.first)
        owner = self.send(self.first, f"Zusammenfassung {ticket}")
        self.assertIn("Private Testperson", owner["reply"])
        before_notes = find_ticket_by_id(ticket, self.workshop)["notes"]
        stranger = self.send(self.second, f"Zusammenfassung {ticket}", phone="01701234567")
        self.assertNotIn("Private Testperson", stranger["reply"])
        self.assertNotIn("Audi A4", stranger["reply"])
        self.assertIsNone(stranger["data"]["ticket_id"])
        self.assertEqual(find_ticket_by_id(ticket, self.workshop)["notes"], before_notes)
        self.assertNotEqual(self.first.cookies.get(BROWSER_COOKIE), self.second.cookies.get(BROWSER_COOKIE))

    def test_own_ticket_is_readable_after_reloading_same_browser(self):
        ticket = self.make_ticket(self.first)
        self.first.get("/assistant", params={"workshop_id": self.workshop})
        answer = self.send(self.first, f"Wie ist der Status von {ticket}?")
        self.assertIn(ticket, answer["reply"])
        self.assertIn("Status", answer["reply"])

    def test_phone_input_is_not_a_customer_identity_proof(self):
        ticket = save_ticket(IntakeState(name="Secret Customer", telefon="01709998888", problem="Private problem"), workshop_id=self.workshop)
        for message in ("Zusammenfassung " + ticket, "Meine Nummer ist 01709998888"):
            result = self.send(self.first, message, phone="01709998888")
            self.assertNotIn("Secret Customer", result["reply"])
            self.assertNotIn("Private problem", result["reply"])
        self.assertFalse(find_ticket_by_id(ticket, self.workshop)["notes"])

    def test_web_request_cannot_read_or_change_whatsapp_session(self):
        sid = "whatsapp:491701234567"
        state = IntakeState(name="WhatsApp Private", telefon="491701234567", problem="Private WhatsApp problem")
        save_session_state(sid, state, workshop_id=self.workshop, channel="whatsapp", phone=state.telefon)
        response = self.send(self.first, None, sid=sid)
        self.assertNotIn("WhatsApp Private", json.dumps(response))
        self.assertNotIn("Private WhatsApp problem", json.dumps(response))
        self.assertEqual(load_session_state(sid, self.workshop, channel="whatsapp").name, "WhatsApp Private")
        self.assertIsNone(load_session_state(sid, self.workshop, channel="web_chat").name)

    def test_legacy_whatsapp_session_is_only_resumed_by_whatsapp(self):
        sid = "whatsapp:491709876543"
        with closing(get_conn()) as conn:
            conn.execute("INSERT INTO conversation_sessions (session_id, workshop_id, channel, state_json, created_at, updated_at) "
                "VALUES (?, ?, 'whatsapp', ?, '2026-01-01', '2026-01-01')",
                (f"{self.workshop}:{sid}", self.workshop, json.dumps({"name": "Legacy Private"})))
            conn.commit()
        result = self.send(self.first, None, sid=sid)
        self.assertNotIn("Legacy Private", json.dumps(result))
        self.assertEqual(load_session_state(sid, self.workshop, channel="whatsapp").name, "Legacy Private")
        self.assertIsNone(load_session_state(sid, self.workshop, channel="web_chat").name)

    def test_tampered_browser_cookie_starts_separate_conversation(self):
        ticket = self.make_ticket(self.first)
        cookie = self.first.cookies.get(BROWSER_COOKIE)
        self.first.cookies.clear()
        self.first.cookies.set(BROWSER_COOKIE, cookie + "x")
        result = self.send(self.first, "Zusammenfassung " + ticket)
        self.assertNotIn("Private Testperson", result["reply"])
        self.assertIsNone(result["data"]["ticket_id"])

    def test_api_does_not_return_persisted_customer_state(self):
        ticket = self.make_ticket(self.first)
        result = self.send(self.first, "Wie ist der Status?")
        self.assertEqual(result["data"]["ticket_id"], ticket)
        self.assertTrue(set(result["data"]).issubset({"step", "mode", "workshop_id", "ticket_id", "request_type", "priority"}))
        self.assertNotIn("telefon", result["data"])
        self.assertNotIn("last_user_message", result["data"])


if __name__ == "__main__":
    unittest.main()
