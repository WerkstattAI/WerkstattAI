from __future__ import annotations

import gc
import json
import os
import re
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

# Initialize the existing suite's isolated configuration before importing the app.
import test_conversation_flows  # noqa: F401
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session_token
from app.db import get_conn, init_db
from app.main import app
from app.privacy_data import delete_data, fingerprint, make_token, preview, selection_for
from app.security import hash_password


class PrivacyTests(unittest.TestCase):
    password = "Test-only-owner-password!"
    phone = "491701234567"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="werkstattai-privacy-")
        self.environment = patch.dict(os.environ, {
            "WERKSTATTAI_SQLITE_PATH": os.path.join(self.directory.name, "privacy.db"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        init_db()
        self.owner = {"email": "owner-a@example.invalid", "workshop_id": "a", "role": "owner"}
        with closing(get_conn()) as conn:
            for wid in ("a", "b"):
                conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (wid, f"Werkstatt {wid}"))
                conn.execute("INSERT INTO users (email, password_hash, workshop_id, role) VALUES (?, ?, ?, 'owner')",
                             (f"owner-{wid}@example.invalid", hash_password(self.password), wid))
                self.seed_customer(conn, wid, self.phone, f"T-{wid}")
            self.seed_customer(conn, "a", "491709999999", "T-other")
            conn.commit()
        self.client = TestClient(app)
        self.login(self.owner)

    def tearDown(self):
        self.client.close()
        gc.collect()
        self.directory.cleanup()

    def seed_customer(self, conn, wid, phone, ticket):
        conn.execute("INSERT INTO tickets (workshop_id, ticket_id, created_at, updated_at, status, priority, telefon, name, notes_json) "
                     "VALUES (?, ?, '2026-09-15', '2026-09-15', 'neu', 'normal', ?, 'Testperson', ?)",
                     (wid, ticket, phone, json.dumps([{"text": f"internal-{ticket}"}])))
        conn.execute("INSERT INTO conversation_sessions (session_id, workshop_id, phone, state_json, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, '2026-09-15', '2026-09-15')",
                     (f"session-{ticket}", wid, phone, json.dumps({"ticket_id": ticket, "telefon": phone})))
        conn.execute("INSERT INTO whatsapp_messages (workshop_id, customer_phone, direction, wa_message_id, ticket_id, text) "
                     "VALUES (?, ?, 'inbound', ?, ?, ?)", (wid, phone, f"wa-{ticket}", ticket, f"message-{ticket}"))
        conn.execute("INSERT INTO whatsapp_events (workshop_id, wa_message_id, event_type, payload_json) "
                     "VALUES (?, ?, 'status', '{}')", (wid, f"wa-{ticket}"))
        conn.execute("INSERT INTO whatsapp_conversation_controls (workshop_id, customer_phone, active_ticket_id) VALUES (?, ?, ?)",
                     (wid, phone, ticket))

    def login(self, user):
        self.client.cookies.clear()
        self.client.cookies.set(SESSION_COOKIE, create_session_token(user))

    def form_token(self):
        response = self.client.get("/dashboard/privacy")
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="token" value="([^"]+)"', response.text).group(1)

    def preview_token(self, kind="phone", value="+49 (170) 1234567"):
        response = self.client.post("/dashboard/privacy/preview", data={
            "workshop_id": "a", "token": self.form_token(), "kind": kind, "value": value,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("5 Datensätze", re.sub(r"<[^>]*>", "", response.text))
        return re.findall(r'name="token" value="([^"]+)"', response.text)[-1]

    def delete_request(self, token, **changes):
        data = {"workshop_id": "a", "token": token, "password": self.password,
                "confirmation": "LÖSCHEN", "authorized": "true"}
        data.update(changes)
        return self.client.post("/dashboard/privacy/delete", data=data)

    def records(self, wid="a", phone=None):
        return preview(wid, selection_for("phone", phone or self.phone))

    def test_verified_sender_is_included_even_when_callback_number_differs(self):
        with closing(get_conn()) as conn:
            conn.execute("INSERT INTO tickets (workshop_id, ticket_id, telefon, verified_customer_phone, created_at, updated_at, status, priority) "
                         "VALUES (?, ?, ?, ?, '2026-09-26', '2026-09-26', 'offen', 'normal')",
                         ("a", "T-verified-owner", "491708888888", self.phone))
            conn.commit()
        selected = self.records()
        self.assertIn("T-verified-owner", {ticket["ticket_id"] for ticket in selected["tickets"]})
        self.assertNotIn("T-b", {ticket["ticket_id"] for ticket in selected["tickets"]})

    def test_public_legal_routes_and_provider_fields(self):
        self.client.cookies.clear()
        with patch.dict(os.environ, {"LEGAL_BUSINESS_ID": "DE-test-only", "LEGAL_PROVIDER_NAME": "<Testanbieter>"}):
            for path, title in (("/impressum", "Impressum"), ("/datenschutz", "Datenschutzinformation"),
                                ("/datenschutz/rechte", "Auskunft, Export und Löschung")):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(title, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
            response = self.client.get("/impressum")
            self.assertIn("DE-test-only", response.text)
            self.assertIn("&lt;Testanbieter&gt;", response.text)

    def test_anonymous_cannot_access_exports_deletion_or_avv(self):
        self.client.cookies.clear()
        for method, path in (("get", ""), ("get", "/avv"), ("post", "/export"), ("post", "/delete")):
            response = getattr(self.client, method)("/dashboard/privacy" + path, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers["location"].startswith("/login"))

    def test_owner_cannot_select_another_workshop(self):
        token = self.form_token()
        self.assertEqual(self.client.get("/dashboard/privacy?workshop_id=b").status_code, 403)
        for route in ("export", "preview", "delete"):
            data = {"workshop_id": "b", "token": token, "kind": "phone", "value": self.phone,
                    "password": self.password, "confirmation": "LÖSCHEN", "authorized": "true"}
            self.assertEqual(self.client.post("/dashboard/privacy/" + route, data=data).status_code, 403)
        self.assertEqual(sum(map(len, self.records("b").values())), 5)

    def test_revoked_or_changed_roles_are_rechecked(self):
        with closing(get_conn()) as conn:
            conn.execute("UPDATE users SET role = 'employee' WHERE email = ?", (self.owner["email"],))
            conn.commit()
        self.assertEqual(self.client.get("/dashboard/privacy", follow_redirects=False).status_code, 303)
        self.login({**self.owner, "role": "employee"})
        self.assertEqual(self.client.get("/dashboard/privacy").status_code, 403)
        with closing(get_conn()) as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (self.owner["email"],))
            conn.commit()
        self.assertEqual(self.client.get("/dashboard/privacy", follow_redirects=False).status_code, 303)

    def test_full_export_omits_passwords_and_other_tenants(self):
        response = self.client.post("/dashboard/privacy/export", data={"workshop_id": "a", "token": self.form_token()})
        self.assertEqual(response.status_code, 200)
        document = response.json()
        self.assertEqual(document["scope"], "workshop")
        self.assertEqual(document["workshop"]["id"], "a")
        self.assertEqual(sum(map(len, document["records"].values())), 10)
        self.assertEqual([u["email"] for u in document["users"]], [self.owner["email"]])
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn(self.password, response.text)
        self.assertNotIn("T-b", response.text)
        self.assertIn("attachment;", response.headers["content-disposition"])

    def test_customer_export_includes_linked_events_and_internal_notes(self):
        for kind, value in (("phone", "0170 1234567"), ("ticket", "T-a")):
            response = self.client.post("/dashboard/privacy/export", data={"workshop_id": "a", "scope": "customer",
                                        "token": self.preview_token(kind, value)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(sum(map(len, response.json()["records"].values())), 5)
            self.assertIn("internal-T-a", response.text)
            self.assertNotIn("T-other", response.text)
            self.assertNotIn("T-b", response.text)
            self.assertNotIn("users", response.json())

    def test_confirmed_delete_is_scoped_and_keeps_only_minimal_audit(self):
        token = self.preview_token()
        response = self.delete_request(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Löschung durchgeführt", response.text)
        self.assertFalse(any(self.records().values()))
        self.assertEqual(sum(map(len, self.records("b").values())), 5)
        self.assertEqual(sum(map(len, self.records(phone="491709999999").values())), 5)
        with closing(get_conn()) as conn:
            audit = dict(conn.execute("SELECT * FROM privacy_operations WHERE action = 'delete'").fetchone())
            self.assertEqual(sum(json.loads(audit["counts_json"]).values()), 5)
            self.assertNotIn(self.phone, json.dumps(audit))
            self.assertNotIn(self.owner["email"], json.dumps(audit))
            self.assertEqual(conn.execute("SELECT count(*) FROM users WHERE workshop_id = 'a'").fetchone()[0], 1)
        self.assertEqual(self.delete_request(token).status_code, 409)

    def test_changed_data_invalidates_export_and_delete(self):
        token = self.preview_token()
        with closing(get_conn()) as conn:
            conn.execute("UPDATE tickets SET notes_json = ? WHERE ticket_id = 'T-a'", (json.dumps(["changed"]),))
            conn.commit()
        response = self.client.post("/dashboard/privacy/export", data={"workshop_id": "a", "scope": "customer", "token": token})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.delete_request(token).status_code, 409)
        self.assertEqual(sum(map(len, self.records().values())), 5)

    def test_password_and_both_confirmations_are_required(self):
        token = self.preview_token()
        for changes, status in (({"password": "wrong"}, 403), ({"confirmation": "delete"}, 409), ({"authorized": "false"}, 409)):
            self.assertEqual(self.delete_request(token, **changes).status_code, status)
            self.assertEqual(sum(map(len, self.records().values())), 5)

    def test_tampered_expired_and_wrong_action_tokens_do_not_delete(self):
        token = self.preview_token()
        self.assertEqual(self.delete_request(token + "x").status_code, 409)
        self.assertEqual(self.delete_request(self.form_token()).status_code, 409)
        with patch("app.privacy_data.time.time", return_value=1):
            expired = make_token(email=self.owner["email"], workshop_id="a", action="preview")
        self.assertEqual(self.delete_request(expired).status_code, 409)
        self.assertEqual(sum(map(len, self.records().values())), 5)

    def test_password_guesses_are_rate_limited(self):
        token = self.preview_token()
        for _ in range(5):
            self.assertEqual(self.delete_request(token, password="wrong").status_code, 403)
        response = self.delete_request(token)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["retry-after"]), 0)
        self.assertEqual(sum(map(len, self.records().values())), 5)

    def test_export_limits_fail_without_partial_download_or_audit(self):
        token = self.form_token()
        for setting, value in (("MAX_EXPORT_ROWS", 1), ("MAX_EXPORT_BYTES", 1)):
            with patch("app.privacy_data." + setting, value):
                response = self.client.post("/dashboard/privacy/export", data={"workshop_id": "a", "token": token})
                self.assertEqual(response.status_code, 409)
                self.assertNotIn("content-disposition", response.headers)
        with closing(get_conn()) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM privacy_operations").fetchone()[0], 0)

    def test_audit_failure_rolls_back_all_deletions(self):
        before = self.records()
        with patch("app.privacy_data._audit", side_effect=RuntimeError("test storage failure")):
            with self.assertRaises(RuntimeError):
                delete_data(workshop_id="a", email=self.owner["email"], selection=selection_for("phone", self.phone),
                            expected_digest=fingerprint(before))
        self.assertEqual(self.records(), before)

    def test_damaged_session_json_does_not_break_phone_or_ticket_search(self):
        for state in ("{broken", "null", "[]", '{"ticket_id": [], "telefon": {}}'):
            with closing(get_conn()) as conn:
                conn.execute("UPDATE conversation_sessions SET state_json = ? WHERE session_id = 'session-T-a'", (state,))
                conn.commit()
            self.assertEqual(len(self.records()["conversation_sessions"]), 1)
            self.assertEqual(len(preview("a", selection_for("ticket", "T-a"))["tickets"]), 1)

    def test_avv_download_is_marked_as_a_draft(self):
        response = self.client.get("/dashboard/privacy/avv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("nicht unterschriftsreif", response.text)
        self.assertIn("Anlage 2", response.text)
        self.assertIn("attachment;", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
