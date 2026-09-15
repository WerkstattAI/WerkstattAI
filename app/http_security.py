from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.rate_limits import DatabaseRateLimiter, Limit
from app.security_config import (
    MAX_BODY_BYTES, MAX_CHAT_BODY_BYTES, MAX_WEBHOOK_BODY_BYTES,
    allowed_origins, is_production, trusted_proxies,
)

logger = logging.getLogger(__name__)
WEBHOOK_PATHS = {"/webhooks/whatsapp", "/meta/whatsapp"}


def client_ip(scope: Scope, headers: Headers, networks: list) -> str:
    peer = str((scope.get("client") or ("unknown", 0))[0])
    try:
        address = ipaddress.ip_address(peer)
        if any(address in network for network in networks):
            # Railway overwrites X-Real-IP. Never accept client-supplied XFF/CF headers.
            try:
                address = ipaddress.ip_address(headers.get("x-real-ip", peer))
            except ValueError:
                pass
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.version == 6:
            return str(ipaddress.ip_network(f"{address}/64", strict=False))
        return str(address)
    except ValueError:
        return peer


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, config: Settings):
        self.app = app
        self.production = is_production(config)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        nonce = secrets.token_urlsafe(24)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        csp = (
            "default-src 'self'; "
            f"script-src 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; frame-src 'none'; form-action 'self' https://wa.me"
        )
        if self.production:
            csp += "; upgrade-insecure-requests"
        elif scope["path"] in {"/docs", "/redoc"}:
            # FastAPI's development-only API explorers use CDN scripts and inline setup.
            csp = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https: 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; font-src https:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"

        async def send_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = csp
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
                headers["Cache-Control"] = "no-store"
                if self.production:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        await self.app(scope, receive, send_headers)


class RequestProtectionMiddleware:
    def __init__(self, app: ASGIApp, config: Settings):
        self.app = app
        self.config = config
        self.networks = trusted_proxies(config)
        self.origins = allowed_origins(config)
        self.limiter = DatabaseRateLimiter(config.auth_secret)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        path = scope["path"].rstrip("/") or "/"

        async def reject(status: int, detail: str, retry_after: int | None = None):
            extra = {"Retry-After": str(retry_after)} if retry_after else None
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(scope, receive, send)

        if len(scope.get("query_string", b"")) > 2048 or len(scope["path"]) > 1024:
            await reject(414, "Die angeforderte URL ist zu lang.")
            return
        if sum(len(key) + len(value) for key, value in scope["headers"]) > 16384:
            await reject(431, "Die Anfrage enthält zu große HTTP-Header.")
            return
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"} and headers.get("origin"):
            scheme = "https" if is_production(self.config) else scope.get("scheme", "http")
            same_origin = f"{scheme}://{headers.get('host', '')}"
            if headers["origin"] != same_origin and headers["origin"] not in self.origins:
                await reject(403, "Diese Herkunft ist nicht zugelassen.")
                return

        maximum = MAX_WEBHOOK_BODY_BYTES if path in WEBHOOK_PATHS else MAX_CHAT_BODY_BYTES if path == "/chat" else MAX_BODY_BYTES
        lengths = headers.getlist("content-length")
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                await reject(400, "Ungültige Größenangabe für die Anfrage.")
                return
            if len(lengths[0]) > 10 or int(lengths[0]) > maximum:
                await reject(413, "Die Anfrage ist zu groß.")
                return

        identity = client_ip(scope, headers, self.networks)
        limits = []
        if path != "/health":
            if path in WEBHOOK_PATHS:
                limits.append(Limit(f"webhook:{identity}", self.config.rate_limit_webhook_per_minute))
            else:
                limits.append(Limit(f"request:{identity}", self.config.rate_limit_requests_per_minute))
            if path == "/chat" and scope["method"] == "POST":
                limits.append(Limit(f"chat:{identity}", self.config.rate_limit_chat_per_minute))
            if path == "/login" and scope["method"] == "POST":
                limits.append(Limit(f"login:{identity}", self.config.rate_limit_login_per_minute))

        async def consume(items: list[Limit]) -> bool:
            if not items:
                return True
            try:
                retry = await run_in_threadpool(self.limiter.consume, items)
            except Exception:
                logger.exception("Rate-limit storage unavailable")
                await reject(503, "Die Anfrage kann gerade nicht geprüft werden. Bitte erneut versuchen.", 5)
                return False
            if retry:
                await reject(429, "Zu viele Anfragen. Bitte kurz warten und erneut versuchen.", retry)
                return False
            return True

        if not await consume(limits):
            return

        async def read_body():
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return None
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > maximum:
                    raise OverflowError
                body.extend(chunk)
                if not message.get("more_body", False):
                    return bytes(body)

        try:
            body = await asyncio.wait_for(read_body(), timeout=15)
        except OverflowError:
            await reject(413, "Die Anfrage ist zu groß.")
            return
        except asyncio.TimeoutError:
            await reject(408, "Die Übertragung der Anfrage hat zu lange gedauert.")
            return
        if body is None:
            return

        if path == "/login" and scope["method"] == "POST":
            async def form_body():
                return {"type": "http.request", "body": body, "more_body": False}
            try:
                async with Request(scope, form_body).form(max_files=0, max_fields=20) as form:
                    email = str(form.get("email", "")).strip().lower()
            except Exception:
                await reject(400, "Ungültiges Anmeldeformular.")
                return
            if email and len(email) <= 254 and not await consume([Limit(f"login-account:{email}", 20, 900)]):
                return

        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def secure_application(app: ASGIApp, config: Settings) -> ASGIApp:
    protected = RequestProtectionMiddleware(app, config)
    cors = CORSMiddleware(protected, allow_origins=allowed_origins(config), allow_credentials=False,
                          allow_methods=["GET", "HEAD", "POST", "PATCH"], allow_headers=["Content-Type"],
                          expose_headers=["Retry-After"], max_age=600)
    return SecurityHeadersMiddleware(cors, config)
