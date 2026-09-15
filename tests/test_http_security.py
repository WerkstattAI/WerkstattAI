from __future__ import annotations

import asyncio
import gc
import os
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

# Reuse the suite's isolated database setup before importing application settings.
import test_conversation_flows
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from app.config import settings
from app.db import get_conn, init_db
from app.http_security import client_ip, secure_application
from app.main import api
from app.rate_limits import DatabaseRateLimiter, Limit
from app.security_config import (
    MAX_BODY_BYTES, MAX_CHAT_BODY_BYTES, MAX_WEBHOOK_BODY_BYTES,
    validate_new_admin_password, validate_security_settings, trusted_proxies,
)


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="werkstattai-http-security-")
        self.environment = patch.dict(os.environ, {"WERKSTATTAI_SQLITE_PATH": os.path.join(self.directory.name, "security.db")})
        self.environment.start()
        self.config = replace(settings, app_env="test", railway_environment="", cors_allowed_origins="", trusted_proxy_cidrs="")
        init_db()

    def tearDown(self):
        gc.collect()
        self.environment.stop()
        self.directory.cleanup()

    def client(self, **changes):
        return TestClient(secure_application(api, replace(self.config, **changes)))

    def test_chat_limit_survives_new_middleware_instances_and_session_changes(self):
        for index in range(3):
            with self.client(rate_limit_chat_per_minute=2) as client:
                response = client.post("/chat", json={"session_id": f"session-{index}", "message": "Hallo"})
            self.assertEqual(response.status_code, 200 if index < 2 else 429)
        self.assertGreater(int(response.headers["retry-after"]), 0)
        self.assertIn("Content-Security-Policy", response.headers)

    def test_rate_limit_atomic_across_independent_instances(self):
        limit = Limit("parallel", 7)
        def consume(_):
            return DatabaseRateLimiter(self.config.auth_secret).consume([limit], now=1800000001)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(consume, range(24)))
        self.assertEqual(results.count(0), 7)
        self.assertEqual(sum(value > 0 for value in results), 17)

    def test_rate_limit_window_expires_and_raw_identifiers_are_not_stored(self):
        limiter = DatabaseRateLimiter(self.config.auth_secret)
        limit = Limit("login:private-person@example.invalid", 1)
        self.assertEqual(limiter.consume([limit], now=1800000000), 0)
        self.assertEqual(limiter.consume([limit], now=1800000001), 59)
        self.assertEqual(limiter.consume([limit], now=1800000060), 0)
        with get_conn() as conn:
            rows = conn.execute("SELECT bucket_key, expires_at FROM rate_limit_buckets").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertRegex(rows[0]["bucket_key"], r"^[a-f0-9]{64}$")

    def test_spoofed_headers_do_not_bypass_login_limits(self):
        with self.client(rate_limit_login_per_minute=2) as client:
            for index in range(3):
                response = client.post("/login", data={"email": "missing@example.invalid", "password": "wrong"},
                    headers={"X-Real-IP": f"192.0.2.{index + 1}", "X-Forwarded-For": f"198.51.100.{index + 1}",
                             "CF-Connecting-IP": f"203.0.113.{index + 1}"})
                self.assertEqual(response.status_code, 401 if index < 2 else 429)

    def test_only_trusted_proxy_can_supply_client_ip(self):
        networks = trusted_proxies(replace(self.config, trusted_proxy_cidrs="100.64.0.0/10"))
        headers = Headers({"X-Real-IP": "192.0.2.8", "X-Forwarded-For": "192.0.2.9"})
        self.assertEqual(client_ip({"client": ("100.64.0.3", 123)}, headers, networks), "192.0.2.8")
        self.assertEqual(client_ip({"client": ("198.51.100.1", 123)}, headers, networks), "198.51.100.1")
        bad = Headers({"X-Real-IP": "192.0.2.8, 192.0.2.9"})
        self.assertEqual(client_ip({"client": ("100.64.0.3", 123)}, bad, networks), "100.64.0.3")
        self.assertEqual(client_ip({"client": ("2001:db8::123", 123)}, Headers(), []), "2001:db8::/64")

    def test_login_account_limit_applies_across_ips_and_multipart_forms(self):
        configured = replace(self.config, trusted_proxy_cidrs="100.64.0.0/10")
        secured = secure_application(api, configured)
        async def proxy(scope, receive, send):
            if scope["type"] == "http":
                scope = dict(scope, client=("100.64.0.3", 123))
            await secured(scope, receive, send)
        with TestClient(proxy) as client:
            for index in range(21):
                response = client.post("/login", files={"email": (None, "account@example.invalid"), "password": (None, "wrong")},
                    headers={"X-Real-IP": f"192.0.2.{index + 1}"})
                self.assertEqual(response.status_code, 401 if index < 20 else 429)

    def test_cors_is_closed_by_default_and_disallows_cross_origin_writes(self):
        with self.client() as client:
            response = client.options("/chat", headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("access-control-allow-origin", response.headers)
            response = client.post("/chat", headers={"Origin": "https://attacker.example"}, json={"session_id": "forbidden"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(client.post("/chat", headers={"Origin": "http://testserver"}, json={"session_id": "same-origin"}).status_code, 200)

    def test_allowlisted_cors_origin_has_no_cross_origin_credentials(self):
        with self.client(cors_allowed_origins="https://customer.example") as client:
            response = client.options("/chat", headers={"Origin": "https://customer.example", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], "https://customer.example")
            self.assertNotIn("access-control-allow-credentials", response.headers)
            response = client.post("/chat", headers={"Origin": "https://customer.example"}, json={"session_id": "allowed"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], "https://customer.example")

    def test_field_limits_reject_input_without_echoing_it(self):
        with self.client() as client:
            for body in ({"session_id": "a" * 129}, {"session_id": "x", "message": "x" * 4097},
                         {"session_id": " "}, {"session_id": "x", "workshop_id": "w" * 129},
                         {"session_id": "x", "phone": "0" * 33}, {"session_id": "x", "channel": "whatsapp"}):
                self.assertEqual(client.post("/chat", json=body).status_code, 422)
            password = "SecretNeverEchoThis" * 20
            response = client.post("/login", data={"email": "test@example.invalid", "password": password})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(password, response.text)
            self.assertNotIn('"input"', response.text)
            response = client.post("/chat", json={"session_id": "boundary", "message": "x" * 4096})
            self.assertEqual(response.status_code, 200)

    def test_oversized_requests_rejected_before_chat_or_webhook_runs(self):
        with self.client() as client, patch("app.main.process_chat_message") as process:
            self.assertEqual(client.post("/chat", content=b"x" * (MAX_CHAT_BODY_BYTES + 1)).status_code, 413)
            for path in ("/webhooks/whatsapp", "/meta/whatsapp"):
                self.assertEqual(client.post(path, content=b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)).status_code, 413)
            process.assert_not_called()

    def test_chunked_and_understated_content_lengths_cannot_bypass_limit(self):
        async def exercise(declared):
            reached = []
            async def downstream(scope, receive, send):
                reached.append(True)
                await JSONResponse({"ok": True})(scope, receive, send)
            messages = [{"type": "http.request", "body": b"x" * 20000, "more_body": index < 3} for index in range(4)]
            async def receive():
                return messages.pop(0) if messages else {"type": "http.disconnect"}
            sent = []
            async def send(message):
                sent.append(message)
            headers = [(b"host", b"testserver")]
            if declared:
                headers.append((b"content-length", b"1"))
            scope = {"type": "http", "method": "POST", "path": "/probe", "headers": headers,
                     "query_string": b"", "scheme": "http", "client": ("127.0.0.1", 123)}
            await secure_application(downstream, self.config)(scope, receive, send)
            self.assertEqual(sent[0]["status"], 413)
            self.assertFalse(reached)
        for declared in (False, True):
            asyncio.run(exercise(declared))

    def test_headers_cover_success_errors_redirects_and_fresh_script_nonces(self):
        with self.client() as client:
            first = client.get("/assistant")
            second = client.get("/assistant")
            nonce = re.search(r'<script nonce="([^"]+)"', first.text).group(1)
            self.assertIn("'nonce-" + nonce + "'", first.headers["content-security-policy"])
            self.assertNotIn(nonce, second.text)
            for response in (first, client.get("/missing"), client.get("/dashboard", follow_redirects=False),
                             client.post("/chat", json={})):
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertEqual(response.headers["x-frame-options"], "DENY")
                self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        with TestClient(secure_application(api, self.config), raise_server_exceptions=False) as client:
            with patch("app.main.process_chat_message", side_effect=RuntimeError("private error detail")):
                response = client.post("/chat", json={"session_id": "error"})
            self.assertEqual(response.status_code, 500)
            self.assertIn("content-security-policy", response.headers)
            self.assertNotIn("private error detail", response.text)

    def test_storage_failure_fails_closed_but_health_remains_available(self):
        with self.client() as client, patch("app.http_security.DatabaseRateLimiter.consume", side_effect=RuntimeError("offline")):
            with self.assertLogs("app.http_security", level="ERROR"):
                response = client.post("/chat", json={"session_id": "offline"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(client.get("/health").status_code, 200)

    def test_production_secret_validation_rejects_defaults_and_insecure_configuration(self):
        valid = replace(self.config, app_env="production", auth_secret="3v-WBxoAZPwbjdVs4McD6nmjXEzVrWUJSChBJmiyMFc",
                        whatsapp_access_token=None, whatsapp_app_secret=None)
        validate_security_settings(valid)
        for secret in ("dev-change-me", "x" * 40, "change-this-to-a-long-random-secret", "short"):
            with self.assertRaises(ValueError):
                validate_security_settings(replace(valid, auth_secret=secret))
        for change in ({"cors_allowed_origins": "*"}, {"cors_allowed_origins": "https://example.com/path"},
                       {"cors_allowed_origins": "http://example.com"}, {"trusted_proxy_cidrs": "0.0.0.0/0"},
                       {"session_cookie_secure": "false"}, {"rate_limit_chat_per_minute": 0},
                       {"whatsapp_access_token": "token", "whatsapp_app_secret": None}):
            with self.assertRaises(ValueError):
                validate_security_settings(replace(valid, **change))
        with self.assertRaises(ValueError):
            validate_new_admin_password(replace(valid, dashboard_admin_password="werkstatt123"))
        with self.assertRaises(ValueError):
            validate_security_settings(replace(valid, app_env="development", railway_environment="production", auth_secret="dev-change-me"))
        with TestClient(secure_application(api, valid), base_url="https://testserver") as client:
            self.assertEqual(client.get("/health").headers["strict-transport-security"], "max-age=31536000")

    def test_malformed_session_cookie_does_not_cause_server_error(self):
        with self.client() as client:
            client.cookies.set("werkstattai_session", "invalid.cookie")
            self.assertEqual(client.get("/dashboard", follow_redirects=False).status_code, 303)
        self.assertIsNone(test_conversation_flows.decode_session_token("ü.invalid"))

    def test_production_startup_actually_rejects_weak_session_secret(self):
        weak = replace(self.config, app_env="production", auth_secret="dev-change-me")
        with patch("app.main.settings", weak), self.assertRaisesRegex(ValueError, "AUTH_SECRET"):
            with self.client():
                pass

    def test_production_cookies_stay_secure_even_without_proxy_headers(self):
        from app.auth import should_secure_session_cookie
        with patch("app.auth.settings", replace(self.config, app_env="production")):
            self.assertTrue(should_secure_session_cookie(test_conversation_flows._request_with_scheme("http")))


if __name__ == "__main__":
    unittest.main()
