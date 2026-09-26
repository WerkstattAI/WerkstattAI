"""Bind public web conversations to a signed, HttpOnly browser identity."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request, Response

from app.auth import should_secure_session_cookie
from app.config import settings

BROWSER_COOKIE = "werkstattai_browser"
BROWSER_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def _sign(value: str) -> str:
    return hmac.new(settings.auth_secret.encode(), ("public-browser-v1:" + value).encode(), hashlib.sha256).hexdigest()


def browser_identity(request: Request, response: Response) -> str:
    token = request.cookies.get(BROWSER_COOKIE, "")
    try:
        if len(token) > 256:
            raise ValueError
        identifier, expiry, signature = token.split(".")
        if (len(identifier) != 48 or any(c not in "0123456789abcdef" for c in identifier)
                or int(expiry) <= int(time.time())
                or not hmac.compare_digest(_sign(identifier + "." + expiry), signature)):
            raise ValueError
        return identifier
    except (ValueError, TypeError):
        identifier = secrets.token_hex(24)
        payload = identifier + "." + str(int(time.time()) + BROWSER_MAX_AGE_SECONDS)
        response.set_cookie(BROWSER_COOKIE, payload + "." + _sign(payload),
                            max_age=BROWSER_MAX_AGE_SECONDS, httponly=True,
                            secure=should_secure_session_cookie(request), samesite="lax")
        return identifier


def bound_web_session(request: Request, response: Response, workshop_id: str, client_session_id: str) -> str:
    identity = browser_identity(request, response)
    value = json.dumps([identity, workshop_id, client_session_id], ensure_ascii=True, separators=(",", ":"))
    return "bound-" + _sign("conversation:" + value)
