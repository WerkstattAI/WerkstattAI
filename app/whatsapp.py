from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import get_conn


MESSAGE_DIRECTIONS = {"inbound", "outbound"}
MESSAGE_STATUSES = {
    "received",
    "sent_local",
    "sent",
    "delivered",
    "read",
    "failed",
    "unknown",
}
CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class WhatsAppInboundMessage:
    phone_number_id: str
    display_phone_number: str | None
    from_phone: str
    message_id: str
    timestamp: str | None
    message_type: str
    text: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class WhatsAppStatusEvent:
    phone_number_id: str
    display_phone_number: str | None
    wa_message_id: str
    recipient_phone: str | None
    status: str
    timestamp: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class WhatsAppSendResult:
    ok: bool
    status_code: int | None
    wa_message_id: str | None
    payload: dict[str, Any]
    error: str | None = None


def build_signature(body: bytes, app_secret: str) -> str:
    digest = hmac.new(
        str(app_secret or "").encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(body: bytes, signature_header: str | None, app_secret: str | None) -> bool:
    secret = str(app_secret or "").strip()
    if not secret:
        return False

    expected = build_signature(body, secret)
    provided = str(signature_header or "").strip()
    return hmac.compare_digest(expected, provided)


def parse_meta_messages(payload: dict[str, Any]) -> list[WhatsAppInboundMessage]:
    if not isinstance(payload, dict):
        return []

    messages: list[WhatsAppInboundMessage] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue

        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue

            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            display_phone_number = str(metadata.get("display_phone_number") or "").strip() or None

            if not phone_number_id:
                continue

            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue

                message_type = str(message.get("type") or "").strip().lower()
                text = None
                if message_type == "text":
                    text_payload = message.get("text") if isinstance(message.get("text"), dict) else {}
                    text = str(text_payload.get("body") or "").strip() or None

                from_phone = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not from_phone or not message_id:
                    continue

                messages.append(
                    WhatsAppInboundMessage(
                        phone_number_id=phone_number_id,
                        display_phone_number=display_phone_number,
                        from_phone=from_phone,
                        message_id=message_id,
                        timestamp=str(message.get("timestamp") or "").strip() or None,
                        message_type=message_type or "unknown",
                        text=text,
                        raw=message,
                    )
                )

    return messages


def parse_meta_statuses(payload: dict[str, Any]) -> list[WhatsAppStatusEvent]:
    if not isinstance(payload, dict):
        return []

    statuses: list[WhatsAppStatusEvent] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue

        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue

            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            display_phone_number = str(metadata.get("display_phone_number") or "").strip() or None
            if not phone_number_id:
                continue

            for status_payload in value.get("statuses") or []:
                if not isinstance(status_payload, dict):
                    continue

                message_id = str(status_payload.get("id") or "").strip()
                status = str(status_payload.get("status") or "").strip().lower()
                if not message_id or not status:
                    continue

                statuses.append(
                    WhatsAppStatusEvent(
                        phone_number_id=phone_number_id,
                        display_phone_number=display_phone_number,
                        wa_message_id=message_id,
                        recipient_phone=str(status_payload.get("recipient_id") or "").strip() or None,
                        status=status,
                        timestamp=str(status_payload.get("timestamp") or "").strip() or None,
                        raw=status_payload,
                    )
                )

    return statuses


def save_whatsapp_event(
    *,
    workshop_id: str,
    phone_number_id: str | None,
    display_phone_number: str | None,
    wa_message_id: str | None,
    from_phone: str | None,
    event_type: str,
    message_type: str | None,
    text: str | None,
    payload: dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO whatsapp_events (
                workshop_id,
                phone_number_id,
                display_phone_number,
                wa_message_id,
                from_phone,
                event_type,
                message_type,
                text,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workshop_id,
                phone_number_id,
                display_phone_number,
                wa_message_id,
                from_phone,
                event_type,
                message_type,
                text,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_message_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def whatsapp_customer_service_window(
    last_customer_message_at: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return Meta's rolling 24-hour free-form reply window for a conversation."""
    last_customer_message = _parse_message_datetime(last_customer_message_at)
    if last_customer_message is None:
        return {
            "service_window_open": False,
            "service_window_expires_at": None,
            "service_window_remaining_seconds": 0,
        }

    if now is None:
        current_time = (
            datetime.now(timezone.utc)
            if last_customer_message.tzinfo is not None
            else datetime.now()
        )
    else:
        current_time = now
        if last_customer_message.tzinfo is None and current_time.tzinfo is not None:
            current_time = current_time.replace(tzinfo=None)
        elif last_customer_message.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

    expires_at = last_customer_message + CUSTOMER_SERVICE_WINDOW
    remaining_seconds = max(0, int((expires_at - current_time).total_seconds()))
    return {
        "service_window_open": current_time < expires_at,
        "service_window_expires_at": expires_at.isoformat(timespec="seconds"),
        "service_window_remaining_seconds": remaining_seconds,
    }


def whatsapp_customer_service_window_for_phone(
    *,
    workshop_id: str,
    customer_phone: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the free-text window from the latest inbound message in this tenant."""
    wid = str(workshop_id or "").strip()
    phone = str(customer_phone or "").strip()
    if not wid or not phone:
        return whatsapp_customer_service_window(None, now=now)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT MAX(created_at) AS last_customer_message_at
            FROM whatsapp_messages
            WHERE workshop_id = ?
              AND customer_phone = ?
              AND direction = 'inbound'
            """,
            (wid, phone),
        ).fetchone()

    last_customer_message_at = row["last_customer_message_at"] if row else None
    result = whatsapp_customer_service_window(last_customer_message_at, now=now)
    result["last_customer_message_at"] = last_customer_message_at
    return result


def _meta_status_error(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    errors = payload.get("errors")
    if not isinstance(errors, list):
        return None

    for error in errors:
        if not isinstance(error, dict):
            continue

        error_data = error.get("error_data")
        details = (
            str(error_data.get("details") or "").strip()
            if isinstance(error_data, dict)
            else ""
        )
        message = str(error.get("message") or "").strip()
        title = str(error.get("title") or "").strip()
        code = str(error.get("code") or "").strip()
        detail = details or message or title
        if detail or code:
            return {
                "message": detail or "Meta hat die Nachricht nicht zugestellt.",
                "code": code or None,
            }

    return None


def _normalize_direction(direction: str) -> str:
    normalized = str(direction or "").strip().lower()
    if normalized not in MESSAGE_DIRECTIONS:
        raise ValueError("Invalid WhatsApp message direction")
    return normalized


def _normalize_status(status: str | None, direction: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in MESSAGE_STATUSES:
        return normalized
    return "received" if direction == "inbound" else "sent_local"


def save_whatsapp_message(
    *,
    workshop_id: str,
    customer_phone: str,
    direction: str,
    phone_number_id: str | None = None,
    message_type: str = "text",
    text: str | None = None,
    wa_message_id: str | None = None,
    ticket_id: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    normalized_direction = _normalize_direction(direction)
    normalized_status = _normalize_status(status, normalized_direction)
    wid = str(workshop_id or "").strip()
    phone = str(customer_phone or "").strip()
    message_id = str(wa_message_id or "").strip() or None

    if not wid:
        raise ValueError("workshop_id is required")
    if not phone:
        raise ValueError("customer_phone is required")

    with get_conn() as conn:
        if message_id:
            existing = conn.execute(
                """
                SELECT 1
                FROM whatsapp_messages
                WHERE workshop_id = ?
                  AND direction = ?
                  AND wa_message_id = ?
                LIMIT 1
                """,
                (wid, normalized_direction, message_id),
            ).fetchone()
            if existing:
                return False

        conn.execute(
            """
            INSERT INTO whatsapp_messages (
                workshop_id,
                phone_number_id,
                customer_phone,
                direction,
                message_type,
                text,
                wa_message_id,
                ticket_id,
                status,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wid,
                str(phone_number_id or "").strip() or None,
                phone,
                normalized_direction,
                str(message_type or "text").strip().lower() or "text",
                text,
                message_id,
                str(ticket_id or "").strip() or None,
                normalized_status,
                json.dumps(payload or {}, ensure_ascii=False),
                _now_iso(),
            ),
        )
        conn.commit()

    return True


def update_whatsapp_message_status(
    *,
    workshop_id: str,
    wa_message_id: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    wid = str(workshop_id or "").strip()
    message_id = str(wa_message_id or "").strip()
    normalized_status = str(status or "").strip().lower()

    if not wid or not message_id or normalized_status not in MESSAGE_STATUSES:
        return False

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM whatsapp_messages
            WHERE workshop_id = ?
              AND direction = 'outbound'
              AND wa_message_id = ?
            LIMIT 1
            """,
            (wid, message_id),
        ).fetchone()
        if not row:
            return False

        current_payload: dict[str, Any] = {}
        try:
            parsed = json.loads(row["payload_json"] or "{}")
            if isinstance(parsed, dict):
                current_payload = parsed
        except json.JSONDecodeError:
            current_payload = {}

        status_events = current_payload.get("status_events")
        if not isinstance(status_events, list):
            status_events = []
        status_events.append(payload or {})
        current_payload["status_events"] = status_events[-20:]
        if normalized_status == "failed":
            delivery_error = _meta_status_error(payload)
            if delivery_error:
                current_payload["delivery_error"] = delivery_error

        conn.execute(
            """
            UPDATE whatsapp_messages
            SET status = ?,
                payload_json = ?
            WHERE workshop_id = ?
              AND direction = 'outbound'
              AND wa_message_id = ?
            """,
            (
                normalized_status,
                json.dumps(current_payload, ensure_ascii=False),
                wid,
                message_id,
            ),
        )
        conn.commit()

    return True


def list_whatsapp_messages(
    *,
    workshop_id: str,
    customer_phone: str | None = None,
    ticket_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    wid = str(workshop_id or "").strip()
    safe_limit = max(1, min(int(limit), 500))

    if not wid:
        return []

    filters = ["workshop_id = ?"]
    params: list[Any] = [wid]

    if customer_phone:
        filters.append("customer_phone = ?")
        params.append(str(customer_phone).strip())

    if ticket_id:
        filters.append("ticket_id = ?")
        params.append(str(ticket_id).strip())

    params.append(safe_limit)
    sql = f"""
        SELECT
            workshop_id,
            phone_number_id,
            customer_phone,
            direction,
            message_type,
            text,
            wa_message_id,
            ticket_id,
            status,
            payload_json,
            created_at
        FROM whatsapp_messages
        WHERE {" AND ".join(filters)}
        ORDER BY created_at ASC, id ASC
        LIMIT ?
    """

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def _post_graph_api_json(
    *,
    url: str,
    access_token: str,
    payload: dict[str, Any],
    timeout_seconds: int = 15,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8")
        parsed = json.loads(response_body) if response_body else {}
        return response.status, parsed if isinstance(parsed, dict) else {}


def send_whatsapp_text_message(
    *,
    phone_number_id: str,
    customer_phone: str,
    text: str,
    access_token: str,
    graph_api_version: str = "v23.0",
) -> WhatsAppSendResult:
    normalized_phone_number_id = str(phone_number_id or "").strip()
    normalized_customer_phone = str(customer_phone or "").strip()
    normalized_text = str(text or "").strip()
    normalized_token = str(access_token or "").strip()
    version = str(graph_api_version or "v23.0").strip().lstrip("/") or "v23.0"

    if not normalized_phone_number_id:
        return WhatsAppSendResult(False, None, None, {}, "phone_number_id is missing")
    if not normalized_customer_phone:
        return WhatsAppSendResult(False, None, None, {}, "customer_phone is missing")
    if not normalized_text:
        return WhatsAppSendResult(False, None, None, {}, "message text is missing")
    if not normalized_token:
        return WhatsAppSendResult(False, None, None, {}, "access token is missing")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_customer_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": normalized_text,
        },
    }
    url = f"https://graph.facebook.com/{version}/{normalized_phone_number_id}/messages"

    try:
        status_code, response_payload = _post_graph_api_json(
            url=url,
            access_token=normalized_token,
            payload=payload,
        )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(error_body) if error_body else {}
        except json.JSONDecodeError:
            error_payload = {"raw": error_body}
        return WhatsAppSendResult(
            False,
            exc.code,
            None,
            error_payload if isinstance(error_payload, dict) else {},
            f"Meta API HTTP {exc.code}",
        )
    except Exception as exc:
        return WhatsAppSendResult(False, None, None, {}, str(exc))

    message_id = None
    messages = response_payload.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            message_id = str(first.get("id") or "").strip() or None

    return WhatsAppSendResult(
        ok=200 <= int(status_code or 0) < 300,
        status_code=status_code,
        wa_message_id=message_id,
        payload=response_payload,
        error=None,
    )


def send_whatsapp_template_message(
    *,
    phone_number_id: str,
    customer_phone: str,
    template_name: str,
    template_language: str,
    access_token: str,
    graph_api_version: str = "v23.0",
) -> WhatsAppSendResult:
    """Send a parameter-free, pre-approved WhatsApp template through Cloud API."""
    normalized_phone_number_id = str(phone_number_id or "").strip()
    normalized_customer_phone = str(customer_phone or "").strip()
    normalized_template_name = str(template_name or "").strip()
    normalized_template_language = str(template_language or "").strip()
    normalized_token = str(access_token or "").strip()
    version = str(graph_api_version or "v23.0").strip().lstrip("/") or "v23.0"

    if not normalized_phone_number_id:
        return WhatsAppSendResult(False, None, None, {}, "phone_number_id is missing")
    if not normalized_customer_phone:
        return WhatsAppSendResult(False, None, None, {}, "customer_phone is missing")
    if not normalized_template_name:
        return WhatsAppSendResult(False, None, None, {}, "template name is missing")
    if not normalized_template_language:
        return WhatsAppSendResult(False, None, None, {}, "template language is missing")
    if not normalized_token:
        return WhatsAppSendResult(False, None, None, {}, "access token is missing")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_customer_phone,
        "type": "template",
        "template": {
            "name": normalized_template_name,
            "language": {"code": normalized_template_language},
        },
    }
    url = f"https://graph.facebook.com/{version}/{normalized_phone_number_id}/messages"

    try:
        status_code, response_payload = _post_graph_api_json(
            url=url,
            access_token=normalized_token,
            payload=payload,
        )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(error_body) if error_body else {}
        except json.JSONDecodeError:
            error_payload = {"raw": error_body}
        return WhatsAppSendResult(
            False,
            exc.code,
            None,
            error_payload if isinstance(error_payload, dict) else {},
            f"Meta API HTTP {exc.code}",
        )
    except Exception as exc:
        return WhatsAppSendResult(False, None, None, {}, str(exc))

    message_id = None
    messages = response_payload.get("messages")
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            message_id = str(first.get("id") or "").strip() or None

    return WhatsAppSendResult(
        ok=200 <= int(status_code or 0) < 300,
        status_code=status_code,
        wa_message_id=message_id,
        payload=response_payload,
        error=None,
    )


def list_whatsapp_conversations(*, workshop_id: str, limit: int = 100) -> list[dict[str, Any]]:
    wid = str(workshop_id or "").strip()
    safe_limit = max(1, min(int(limit), 500))

    if not wid:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                customer_phone,
                phone_number_id,
                direction,
                message_type,
                text,
                wa_message_id,
                ticket_id,
                status,
                created_at
            FROM whatsapp_messages
            WHERE workshop_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (wid, safe_limit * 20),
        ).fetchall()

    conversations: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        phone = str(item.get("customer_phone") or "").strip()
        if not phone:
            continue

        if phone not in conversations:
            conversations[phone] = {
                "customer_phone": phone,
                "phone_number_id": item.get("phone_number_id"),
                "last_direction": item.get("direction"),
                "last_message_type": item.get("message_type"),
                "last_text": item.get("text"),
                "last_wa_message_id": item.get("wa_message_id"),
                "last_ticket_id": item.get("ticket_id"),
                "last_status": item.get("status"),
                "last_created_at": item.get("created_at"),
                "message_count": 0,
                "inbound_count": 0,
                "outbound_count": 0,
                "last_customer_message_at": None,
            }

        conversations[phone]["message_count"] += 1
        if item.get("direction") == "inbound":
            conversations[phone]["inbound_count"] += 1
            if not conversations[phone]["last_customer_message_at"]:
                conversations[phone]["last_customer_message_at"] = item.get("created_at")
        elif item.get("direction") == "outbound":
            conversations[phone]["outbound_count"] += 1

    result = list(conversations.values())[:safe_limit]
    for conversation in result:
        conversation.update(
            whatsapp_customer_service_window_for_phone(
                workshop_id=wid,
                customer_phone=str(conversation.get("customer_phone") or ""),
            )
        )
    return result
