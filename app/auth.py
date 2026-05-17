from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app.config import settings
from app.db import get_conn
from app.security import verify_password


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


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT email, password_hash, workshop_id, role
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (normalized_email,),
        ).fetchone()

    if not row:
        return None

    if not verify_password(password, row["password_hash"]):
        return None

    return {
        "email": row["email"],
        "workshop_id": row["workshop_id"],
        "role": row["role"],
    }


def create_session_token(user: dict[str, Any]) -> str:
    payload = {
        "email": user["email"],
        "workshop_id": user["workshop_id"],
        "role": user["role"],
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def decode_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None

    encoded_payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(encoded_payload), signature):
        return None

    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except Exception:
        return None

    if int(payload.get("exp") or 0) < int(time.time()):
        return None

    email = str(payload.get("email") or "").strip().lower()
    workshop_id = str(payload.get("workshop_id") or "").strip()
    role = str(payload.get("role") or "").strip() or "owner"
    if not email or not workshop_id:
        return None

    return {
        "email": email,
        "workshop_id": workshop_id,
        "role": role,
    }


def get_current_user(request: Request) -> dict[str, Any] | None:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return user
    return decode_session_token(request.cookies.get(SESSION_COOKIE))


def set_session_cookie(response: Response, user: dict[str, Any]) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
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
