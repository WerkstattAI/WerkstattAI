from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import closing
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app.config import settings
from app.db import get_conn
from app.security import verify_password
from app.security_config import is_production


SESSION_COOKIE = "werkstattai_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 10


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(payload: str) -> str:
    digest = hmac.new(
        settings.auth_secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest)


def _user_record(email: str) -> dict[str, Any] | None:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT email, password_hash, workshop_id, role FROM users WHERE email = ? LIMIT 1",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def _identity(user: dict[str, Any]) -> dict[str, Any]:
    return {key: user[key] for key in ("email", "workshop_id", "role")}


def _session_version(user: dict[str, Any]) -> str:
    # A password reset changes the salted hash, invalidating every old cookie.
    # The keyed digest never exposes the stored password hash to the browser.
    state = json.dumps(
        [user["email"], user["workshop_id"], user["role"], user["password_hash"]],
        separators=(",", ":"), ensure_ascii=True,
    )
    return _sign("session-version-v1:" + state)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None

    user = _user_record(normalized_email)
    if not user:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return {**_identity(user), "session_version": _session_version(user)}


def create_session_token(user: dict[str, Any]) -> str:
    current = _user_record(str(user.get("email") or "").strip().lower())
    if not current or any(user.get(key) != current[key] for key in ("email", "workshop_id", "role")):
        raise ValueError("Dieser Zugang ist nicht mehr gültig. Bitte neu anmelden.")
    version = _session_version(current)
    # Preserve the version verified during password authentication if a reset
    # happens between password verification and cookie creation.
    if "session_version" in user and not hmac.compare_digest(str(user["session_version"]), version):
        raise ValueError("Dieser Zugang hat sich geändert. Bitte neu anmelden.")
    payload = {
        **_identity(current),
        "session_version": version,
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def decode_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or len(token) > 4096 or "." not in token:
        return None

    try:
        encoded_payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(encoded_payload), signature):
            return None
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
        if not isinstance(payload, dict) or type(payload.get("exp")) is not int or payload["exp"] <= int(time.time()):
            return None
        if any(not isinstance(payload.get(key), str) or not payload[key]
               for key in ("email", "workshop_id", "role", "session_version")):
            return None
        if not payload["session_version"].isascii():
            return None
    except Exception:
        return None

    current = _user_record(payload["email"])
    if not current or any(payload[key] != current[key] for key in ("email", "workshop_id", "role")):
        return None
    if not hmac.compare_digest(payload["session_version"], _session_version(current)):
        return None
    return _identity(current)


def get_current_user(request: Request) -> dict[str, Any] | None:
    # request.state.user may be stale or supplied by an internal caller. The
    # signed cookie and current database record are the source of authority.
    return decode_session_token(request.cookies.get(SESSION_COOKIE))


def _request_uses_https(request: Request | None) -> bool:
    if request is None:
        return False

    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"

    return request.url.scheme == "https"


def should_secure_session_cookie(request: Request | None = None) -> bool:
    if is_production(settings):
        return True
    mode = str(settings.session_cookie_secure or "auto").strip().lower()

    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False

    return _request_uses_https(request)


def set_session_cookie(response: Response, user: dict[str, Any], request: Request | None = None) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=should_secure_session_cookie(request),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def login_redirect_url(request: Request) -> str:
    path = request.url.path
    query = request.url.query
    target = path + (f"?{query}" if query else "")
    return f"/login?next={quote(target)}"


def is_dashboard_path(path: str) -> bool:
    return path == "/dashboard" or path.startswith("/dashboard/")


def require_dashboard_login(request: Request) -> RedirectResponse | None:
    user = get_current_user(request)
    if user:
        request.state.user = user
        return None
    return RedirectResponse(url=login_redirect_url(request), status_code=303)
