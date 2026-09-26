from __future__ import annotations

import base64
import gc
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from contextlib import closing
from unittest.mock import patch

# Reuse the suite's isolated configuration before importing the application.
import test_conversation_flows  # noqa: F401
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.admin import reset_workshop_owner_password
from app.auth import (
    SESSION_COOKIE, authenticate_user, create_session_token,
    decode_session_token, get_current_user,
)
from app.config import settings
from app.db import get_conn, init_db
from app.main import app
from app.security import hash_password


class AuthRevocationTests(unittest.TestCase):
    password = "Review-only-login-password!"
    changed_password = "Review-only-replacement-password!"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="werkstattai-auth-revocation-")
        self.environment = patch.dict(os.environ, {
            "WERKSTATTAI_SQLITE_PATH": os.path.join(self.directory.name, "auth.db"),
        })
        self.environment.start()
        init_db()
        self.user = {"email": "review-owner@example.invalid", "workshop_id": "auth-review", "role": "owner"}
        with closing(get_conn()) as conn:
            for workshop in ("auth-review", "auth-other"):
                conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (workshop, workshop))
            conn.execute("INSERT INTO users (email, password_hash, workshop_id, role) VALUES (?, ?, ?, ?)",
                         (self.user["email"], hash_password(self.password), self.user["workshop_id"], self.user["role"]))
            conn.commit()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()
        gc.collect()
        self.directory.cleanup()

    def login(self, password=None):
        self.client.cookies.clear()
        response = self.client.post("/login", data={
            "email": self.user["email"], "password": password or self.password,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        return self.client.cookies.get(SESSION_COOKIE)

    def reset_password(self):
        reset_workshop_owner_password(workshop_id=self.user["workshop_id"], owner_email=self.user["email"],
                                      new_password=self.changed_password)

    def request(self, token=None, state_user=None):
        headers = [(b"cookie", f"{SESSION_COOKIE}={token}".encode())] if token else []
        request = Request({"type": "http", "method": "GET", "path": "/dashboard",
                           "headers": headers, "query_string": b""})
        if state_user is not None:
            request.state.user = state_user
        return request

    def assert_revoked(self, token):
        self.assertIsNone(decode_session_token(token))
        self.client.cookies.clear()
        self.client.cookies.set(SESSION_COOKIE, token)
        self.assertEqual(self.client.get("/tickets").status_code, 401)
        for path in ("/dashboard", "/dashboard/admin/workshops", "/dashboard/privacy"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertTrue(response.headers["location"].startswith("/login"))
        self.assertEqual(self.client.post("/dashboard/privacy/export", follow_redirects=False).status_code, 303)

    def test_password_reset_revokes_cookie_and_new_login_works(self):
        token = self.login()
        self.assertEqual(self.client.get("/tickets").status_code, 200)
        self.assertEqual(self.client.get("/dashboard/privacy").status_code, 200)
        self.reset_password()
        self.assert_revoked(token)
        self.assertIsNone(authenticate_user(self.user["email"], self.password))
        replacement = self.login(self.changed_password)
        self.assertNotEqual(replacement, token)
        self.assertEqual(decode_session_token(replacement), self.user)
        self.assertEqual(self.client.get("/tickets").status_code, 200)

    def test_deleted_user_cannot_reuse_old_cookie(self):
        token = self.login()
        with closing(get_conn()) as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (self.user["email"],))
            conn.commit()
        self.assert_revoked(token)
        with self.assertRaises(ValueError):
            create_session_token(self.user)

    def test_admin_demotion_revokes_cookie_and_new_login_has_current_role(self):
        with closing(get_conn()) as conn:
            conn.execute("UPDATE users SET role = 'admin' WHERE email = ?", (self.user["email"],))
            conn.commit()
        token = self.login()
        self.assertEqual(self.client.get("/dashboard/admin/workshops").status_code, 200)
        with closing(get_conn()) as conn:
            conn.execute("UPDATE users SET role = 'owner' WHERE email = ?", (self.user["email"],))
            conn.commit()
        self.assert_revoked(token)
        replacement = self.login()
        self.assertEqual(decode_session_token(replacement), self.user)
        self.assertEqual(self.client.get("/dashboard/admin/workshops", follow_redirects=False).status_code, 403)

    def test_workshop_change_revokes_old_tenant_access(self):
        token = self.login()
        with closing(get_conn()) as conn:
            conn.execute("UPDATE users SET workshop_id = 'auth-other' WHERE email = ?", (self.user["email"],))
            conn.commit()
        self.assert_revoked(token)
        replacement = self.login()
        self.assertEqual(decode_session_token(replacement)["workshop_id"], "auth-other")
        self.assertEqual(self.client.get("/tickets?workshop_id=auth-review").json()["workshop_id"], "auth-other")

    def test_legacy_cookie_without_version_is_rejected(self):
        payload = {**self.user, "exp": int(time.time()) + 3600}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        signature = base64.urlsafe_b64encode(hmac.new(settings.auth_secret.encode(), encoded.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        self.assert_revoked(encoded + "." + signature)

    def test_request_state_is_not_authentication(self):
        self.assertIsNone(get_current_user(self.request(state_user={**self.user, "role": "admin"})))
        token = self.login()
        request = self.request(token, state_user={**self.user, "role": "admin", "workshop_id": "auth-other"})
        self.assertEqual(get_current_user(request), self.user)
        self.reset_password()
        self.assertIsNone(get_current_user(request))

    def test_signed_cookie_does_not_contain_password_hash(self):
        token = self.login()
        encoded = token.split(".")[0]
        payload_text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        with closing(get_conn()) as conn:
            password_hash = conn.execute("SELECT password_hash FROM users WHERE email = ?", (self.user["email"],)).fetchone()["password_hash"]
        self.assertNotIn(self.password, payload_text)
        self.assertNotIn(password_hash, payload_text)
        self.assertNotIn("password_hash", payload_text)
        self.assertEqual(decode_session_token(token), self.user)

    def test_reset_during_login_cannot_mint_cookie_for_old_password(self):
        authenticated = authenticate_user(self.user["email"], self.password)
        self.reset_password()
        with self.assertRaises(ValueError):
            create_session_token(authenticated)
        with patch("app.web.authenticate_user", return_value=authenticated):
            response = self.client.post("/login", data={"email": self.user["email"], "password": self.password})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(SESSION_COOKIE, response.headers.get("set-cookie", ""))

    def test_cannot_mint_cookie_for_changed_role(self):
        with self.assertRaises(ValueError):
            create_session_token({**self.user, "role": "admin"})


if __name__ == "__main__":
    unittest.main()
