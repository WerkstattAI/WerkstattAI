from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.db import get_conn
from app.security import hash_password


_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_workshop_slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", str(value or "").strip().lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def _trial_ends_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=settings.trial_days)).isoformat()


def list_workshop_accounts() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                w.id,
                w.name,
                w.email,
                w.phone,
                w.subscription_plan,
                w.subscription_status,
                w.trial_ends_at,
                w.whatsapp_phone_number_id,
                w.created_at,
                COUNT(u.email) AS user_count,
                MIN(u.email) AS first_user_email
            FROM workshops w
            LEFT JOIN users u ON u.workshop_id = w.id
            GROUP BY
                w.id,
                w.name,
                w.email,
                w.phone,
                w.subscription_plan,
                w.subscription_status,
                w.trial_ends_at,
                w.whatsapp_phone_number_id,
                w.created_at
            ORDER BY w.created_at DESC, w.name ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_workshop_account(workshop_id: str) -> dict[str, Any] | None:
    wid = normalize_workshop_slug(workshop_id)
    if not wid:
        return None

    with get_conn() as conn:
        workshop = conn.execute(
            """
            SELECT
                id,
                name,
                address,
                phone,
                email,
                opening_hours,
                services,
                pricing_info,
                towing_info,
                subscription_plan,
                subscription_status,
                trial_ends_at,
                subscription_ends_at,
                whatsapp_phone_number_id,
                whatsapp_display_phone_number,
                created_at,
                updated_at
            FROM workshops
            WHERE id = ?
            LIMIT 1
            """,
            (wid,),
        ).fetchone()
        if not workshop:
            return None

        users = conn.execute(
            """
            SELECT email, role, created_at, updated_at
            FROM users
            WHERE workshop_id = ?
            ORDER BY role DESC, email ASC
            """,
            (wid,),
        ).fetchall()

    result = dict(workshop)
    result["users"] = [dict(row) for row in users]
    result["owner_email"] = next(
        (str(user["email"]) for user in result["users"] if user.get("role") == "owner"),
        str(result["users"][0]["email"]) if result["users"] else "",
    )
    return result


def _validate_plan_status(plan: str, status: str) -> tuple[str, str]:
    normalized_plan = str(plan or "starter").strip().lower() or "starter"
    normalized_status = str(status or "trialing").strip().lower() or "trialing"

    if normalized_plan not in {"starter", "pro", "pilot"}:
        raise ValueError("Ungueltiger Plan.")
    if normalized_status not in {"trialing", "active", "inactive", "past_due"}:
        raise ValueError("Ungueltiger Abo-Status.")

    return normalized_plan, normalized_status


def update_workshop_account(
    *,
    workshop_id: str,
    workshop_name: str,
    address: str = "",
    phone: str = "",
    email: str = "",
    opening_hours: str = "",
    services: str = "",
    pricing_info: str = "",
    towing_info: str = "",
    subscription_plan: str = "starter",
    subscription_status: str = "trialing",
    trial_ends_at: str = "",
    subscription_ends_at: str = "",
    whatsapp_phone_number_id: str = "",
    whatsapp_display_phone_number: str = "",
) -> dict[str, Any]:
    wid = normalize_workshop_slug(workshop_id)
    name = str(workshop_name or "").strip()
    plan, status = _validate_plan_status(subscription_plan, subscription_status)

    if not wid:
        raise ValueError("Workshop-ID fehlt.")
    if not name:
        raise ValueError("Werkstattname fehlt.")

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM workshops WHERE id = ? LIMIT 1",
            (wid,),
        ).fetchone()
        if not existing:
            raise ValueError("Werkstattkonto wurde nicht gefunden.")

        conn.execute(
            """
            UPDATE workshops
            SET
                name = ?,
                address = ?,
                phone = ?,
                email = ?,
                opening_hours = ?,
                services = ?,
                pricing_info = ?,
                towing_info = ?,
                subscription_plan = ?,
                subscription_status = ?,
                trial_ends_at = ?,
                subscription_ends_at = ?,
                whatsapp_phone_number_id = ?,
                whatsapp_display_phone_number = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                name,
                str(address or "").strip(),
                str(phone or "").strip(),
                str(email or "").strip(),
                str(opening_hours or "").strip(),
                str(services or "").strip(),
                str(pricing_info or "").strip(),
                str(towing_info or "").strip(),
                plan,
                status,
                str(trial_ends_at or "").strip() or None,
                str(subscription_ends_at or "").strip() or None,
                str(whatsapp_phone_number_id or "").strip(),
                str(whatsapp_display_phone_number or "").strip(),
                wid,
            ),
        )
        conn.commit()

    account = get_workshop_account(wid)
    if not account:
        raise ValueError("Werkstattkonto wurde nicht gefunden.")
    return account


def reset_workshop_owner_password(
    *,
    workshop_id: str,
    owner_email: str,
    new_password: str,
) -> None:
    wid = normalize_workshop_slug(workshop_id)
    email = str(owner_email or "").strip().lower()
    password = str(new_password or "")

    if not wid:
        raise ValueError("Workshop-ID fehlt.")
    if not email or "@" not in email:
        raise ValueError("Owner-E-Mail ist ungueltig.")
    if len(password) < 8:
        raise ValueError("Neues Passwort muss mindestens 8 Zeichen haben.")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT email
            FROM users
            WHERE workshop_id = ? AND email = ?
            LIMIT 1
            """,
            (wid, email),
        ).fetchone()
        if not row:
            raise ValueError("Owner-Login wurde nicht gefunden.")

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE workshop_id = ? AND email = ?
            """,
            (hash_password(password), wid, email),
        )
        conn.commit()


def create_workshop_account(
    *,
    workshop_id: str,
    workshop_name: str,
    admin_email: str,
    admin_password: str,
    address: str = "",
    phone: str = "",
    email: str = "",
    opening_hours: str = "",
    services: str = "",
    pricing_info: str = "",
    towing_info: str = "",
    subscription_plan: str = "starter",
    subscription_status: str = "trialing",
    whatsapp_phone_number_id: str = "",
    whatsapp_display_phone_number: str = "",
) -> dict[str, Any]:
    wid = normalize_workshop_slug(workshop_id or workshop_name)
    name = str(workshop_name or "").strip()
    user_email = str(admin_email or "").strip().lower()
    password = str(admin_password or "")
    plan = str(subscription_plan or "starter").strip().lower() or "starter"
    status = str(subscription_status or "trialing").strip().lower() or "trialing"

    if not wid:
        raise ValueError("Workshop-ID fehlt.")
    if not name:
        raise ValueError("Werkstattname fehlt.")
    if not user_email or "@" not in user_email:
        raise ValueError("Admin-E-Mail ist ungueltig.")
    if len(password) < 8:
        raise ValueError("Admin-Passwort muss mindestens 8 Zeichen haben.")
    plan, status = _validate_plan_status(plan, status)

    with get_conn() as conn:
        existing_workshop = conn.execute(
            "SELECT id FROM workshops WHERE id = ? LIMIT 1",
            (wid,),
        ).fetchone()
        if existing_workshop:
            raise ValueError("Diese Workshop-ID existiert bereits.")

        existing_user = conn.execute(
            "SELECT email FROM users WHERE email = ? LIMIT 1",
            (user_email,),
        ).fetchone()
        if existing_user:
            raise ValueError("Diese Admin-E-Mail existiert bereits.")

        conn.execute(
            """
            INSERT INTO workshops (
                id,
                name,
                address,
                phone,
                email,
                opening_hours,
                services,
                pricing_info,
                towing_info,
                subscription_plan,
                subscription_status,
                trial_ends_at,
                whatsapp_phone_number_id,
                whatsapp_display_phone_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wid,
                name,
                str(address or "").strip(),
                str(phone or "").strip(),
                str(email or "").strip(),
                str(opening_hours or "").strip(),
                str(services or "").strip(),
                str(pricing_info or "").strip(),
                str(towing_info or "").strip(),
                plan,
                status,
                _trial_ends_at(),
                str(whatsapp_phone_number_id or "").strip(),
                str(whatsapp_display_phone_number or "").strip(),
            ),
        )
        conn.execute(
            """
            INSERT INTO users (
                email,
                password_hash,
                workshop_id,
                role
            )
            VALUES (?, ?, ?, 'owner')
            """,
            (
                user_email,
                hash_password(password),
                wid,
            ),
        )
        conn.commit()

    return {
        "id": wid,
        "name": name,
        "admin_email": user_email,
        "subscription_plan": plan,
        "subscription_status": status,
    }
