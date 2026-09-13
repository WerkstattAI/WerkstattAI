from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.admin import (
    create_workshop_account,
    get_workshop_account,
    list_workshop_accounts,
    reset_workshop_owner_password,
    update_workshop_account,
)
from app.auth import authenticate_user, clear_session_cookie, get_current_user, set_session_cookie
from app.config import settings
from app.db import (
    default_workshop_id,
    get_whatsapp_conversation_control,
    set_whatsapp_conversation_control,
)
from app.models import IntakeState
from app.subscriptions import get_subscription
from app.tickets import (
    add_ticket_note,
    archive_ticket,
    find_ticket_by_id,
    list_latest_tickets,
    save_ticket,
    update_ticket_status,
)
from app.whatsapp import (
    list_whatsapp_conversations,
    list_whatsapp_messages,
    save_whatsapp_message,
    send_whatsapp_template_message,
    send_whatsapp_text_message,
    whatsapp_customer_service_window_for_phone,
)
from app.workshops import get_workshop, get_workshop_identity, update_workshop

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)


def _normalize_workshop_id(value: str | None = None) -> str:
    return (value or default_workshop_id()).strip() or default_workshop_id()


def _workshop_id_for_request(request: Request, value: str | None = None) -> str:
    user = get_current_user(request)
    if user:
        if str(user.get("role") or "").strip().lower() == "admin" and value:
            return _normalize_workshop_id(value)
        return _normalize_workshop_id(str(user.get("workshop_id") or ""))
    return _normalize_workshop_id(value)


def _template_context(request: Request, **extra: Any) -> dict[str, Any]:
    user = get_current_user(request)
    subscription = None
    if user:
        subscription = get_subscription(str(user.get("workshop_id") or ""))

    return {
        "request": request,
        "current_user": user,
        "subscription": subscription,
        **extra,
    }


def _is_admin_user(request: Request) -> bool:
    user = get_current_user(request)
    return str((user or {}).get("role") or "").strip().lower() == "admin"


# -------------------------
# Helpers
# -------------------------
def _as_dict(x: Any) -> dict:
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if hasattr(x, "dict"):
        return x.dict()
    return x if isinstance(x, dict) else {}


def _parse_iso(dt: str | None) -> datetime:
    if not dt:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _format_datetime_for_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return text

    return parsed.strftime("%d.%m.%Y · %H:%M")


def _ticket_id(t: dict) -> str:
    return str(
        t.get("_id")
        or t.get("id")
        or t.get("ticket_id")
        or ""
    )


def _normalize_status(value: str | None) -> str:
    status = (value or "").strip().lower()

    if status == "geschlossen":
        return "erledigt"

    if status in {"offen", "in_bearbeitung", "erledigt", "archiviert"}:
        return status

    return "offen"


def _normalize_priority(value: str | None) -> str:
    """
    Neue Prioritäten:
    - niedrig
    - normal
    - hoch

    Alte Fallbacks:
    - dringend -> hoch
    - notfall -> hoch
    """
    priority = (value or "").strip().lower()

    if priority in {"dringend", "notfall"}:
        return "hoch"

    if priority in {"niedrig", "normal", "hoch"}:
        return priority

    return "normal"


def _normalize_request_type(value: str | None) -> str:
    request_type = (value or "").strip().lower()

    if request_type in {"service", "diagnose", "notfall", "kostenvoranschlag"}:
        return request_type

    return "diagnose"


def _normalize_source(value: str | None) -> str:
    source = (value or "").strip().lower()
    if source in {"web_chat", "whatsapp", "direktannahme"}:
        return source
    return "web_chat"


def _normalize_filter_source(value: str | None) -> str:
    source = (value or "").strip().lower()
    if source in {"all", "web_chat", "whatsapp", "direktannahme"}:
        return source
    return "all"


def _normalize_filter_question_state(value: str | None) -> str:
    state = (value or "").strip().lower()
    if state in {"all", "open", "answered"}:
        return state
    return "all"


def _ui_status(backend_status: str | None) -> str:
    return _normalize_status(backend_status)


def _backend_status(ui_status: str) -> str:
    return _normalize_status(ui_status)


def _parse_ja_nein(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    if v == "ja":
        return "ja"
    if v == "nein":
        return "nein"
    return None


def _status_label(value: str | None) -> str:
    labels = {
        "offen": "Offen",
        "in_bearbeitung": "In Bearbeitung",
        "erledigt": "Erledigt",
        "archiviert": "Archiviert",
    }
    return labels.get(_normalize_status(value), "-")


def _priority_label(value: str | None) -> str:
    labels = {
        "niedrig": "Niedrig",
        "normal": "Normal",
        "hoch": "Hoch",
    }
    return labels.get(_normalize_priority(value), "Normal")


def _request_type_label(value: str | None) -> str:
    labels = {
        "service": "Service",
        "diagnose": "Diagnose",
        "notfall": "Notfall",
        "kostenvoranschlag": "Kostenvoranschlag",
    }
    return labels.get(_normalize_request_type(value), "Diagnose")


def _source_label(value: str | None) -> str:
    labels = {
        "web_chat": "Web-Chat",
        "whatsapp": "WhatsApp",
        "direktannahme": "Direktannahme",
    }
    return labels.get(_normalize_source(value), "Web-Chat")


def _message_status_label(value: str | None) -> str:
    labels = {
        "received": "Empfangen",
        "sent_local": "Lokal gespeichert",
        "sent": "An Meta übergeben",
        "delivered": "Zugestellt",
        "read": "Gelesen",
        "failed": "Fehler",
        "unknown": "Versandstatus unklar",
    }
    return labels.get(str(value or "").strip().lower(), str(value or "-"))


def _message_status_class(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in {"delivered", "read", "received"}:
        return "status-ok"
    if status == "failed":
        return "status-failed"
    return "status-local"


def _message_error(payload_json: str | None) -> str:
    if not payload_json:
        return ""

    try:
        payload = json.loads(payload_json)
    except Exception:
        return ""

    if not isinstance(payload, dict):
        return ""

    delivery_error = payload.get("delivery_error")
    if isinstance(delivery_error, dict):
        message = str(delivery_error.get("message") or "").strip()
        code = str(delivery_error.get("code") or "").strip()
        if message and code:
            return f"{message} (Meta-Code {code})"
        if message:
            return message
    elif isinstance(delivery_error, str) and delivery_error.strip():
        return delivery_error.strip()

    response = payload.get("meta_response")
    if isinstance(response, dict):
        meta_error = response.get("error")
        if isinstance(meta_error, dict):
            message = str(meta_error.get("message") or "").strip()
            code = str(meta_error.get("code") or "").strip()
            if message and code:
                return f"{message} ({code})"
            return message

    error = payload.get("meta_error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    status_events = payload.get("status_events")
    if isinstance(status_events, list):
        for status_event in reversed(status_events):
            if not isinstance(status_event, dict):
                continue
            errors = status_event.get("errors")
            if not isinstance(errors, list):
                continue
            for status_error in errors:
                if not isinstance(status_error, dict):
                    continue
                error_data = status_error.get("error_data")
                details = (
                    str(error_data.get("details") or "").strip()
                    if isinstance(error_data, dict)
                    else ""
                )
                message = str(status_error.get("message") or "").strip()
                title = str(status_error.get("title") or "").strip()
                code = str(status_error.get("code") or "").strip()
                detail = details or message or title
                if detail and code:
                    return f"{detail} (Meta-Code {code})"
                if detail:
                    return detail

    return ""


def _decorate_whatsapp_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = []
    for message in messages:
        item = dict(message)
        item["status_label"] = _message_status_label(item.get("status"))
        item["status_class"] = _message_status_class(item.get("status"))
        item["message_error"] = (
            _message_error(item.get("payload_json"))
            if str(item.get("status") or "").strip().lower() in {"failed", "unknown"}
            else ""
        )
        item["created_at_display"] = _format_datetime_for_display(item.get("created_at"))
        item["sender_label"] = "Kunde"
        if str(item.get("direction") or "").strip().lower() == "outbound":
            source = ""
            try:
                payload = json.loads(item.get("payload_json") or "{}")
                if isinstance(payload, dict):
                    source = str(payload.get("source") or "").strip().lower()
            except Exception:
                source = ""
            item["sender_label"] = "Assistent" if source == "webhook" else "Werkstatt"
        decorated.append(item)
    return decorated


def _whatsapp_readiness(request: Request, workshop: dict[str, Any]) -> dict[str, Any]:
    access_token_ready = bool(str(settings.whatsapp_access_token or "").strip())
    verify_token_ready = bool(str(settings.whatsapp_verify_token or "").strip())
    app_secret_ready = bool(str(settings.whatsapp_app_secret or "").strip())
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    display_phone_number = str(workshop.get("whatsapp_display_phone_number") or "").strip()
    configured_webhook_url = str(settings.whatsapp_webhook_public_url or "").strip()
    start_template_name = str(settings.whatsapp_start_template_name or "").strip()
    start_template_language = str(settings.whatsapp_start_template_language or "").strip()
    webhook_url = configured_webhook_url or f"{str(request.base_url).rstrip('/')}/webhooks/whatsapp"

    checks = [
        {
            "label": "Access Token",
            "configured": access_token_ready,
            "detail": "WHATSAPP_ACCESS_TOKEN",
        },
        {
            "label": "Verify Token",
            "configured": verify_token_ready,
            "detail": "WHATSAPP_VERIFY_TOKEN",
        },
        {
            "label": "App Secret",
            "configured": app_secret_ready,
            "detail": "WHATSAPP_APP_SECRET",
        },
        {
            "label": "Phone Number ID",
            "configured": bool(phone_number_id),
            "detail": phone_number_id or "In Einstellungen eintragen",
        },
        {
            "label": "Startvorlage",
            "configured": bool(start_template_name and start_template_language),
            "detail": (
                f"{start_template_name} · {start_template_language}"
                if start_template_name and start_template_language
                else "WHATSAPP_START_TEMPLATE_NAME / _LANGUAGE"
            ),
        },
    ]

    return {
        "is_ready": all(check["configured"] for check in checks),
        "can_send": access_token_ready and bool(phone_number_id),
        "reply_mode": "meta" if access_token_ready and phone_number_id else "unavailable",
        "webhook_url": webhook_url,
        "webhook_url_source": "configured" if configured_webhook_url else "request",
        "phone_number_id": phone_number_id,
        "display_phone_number": display_phone_number,
        "start_template_name": start_template_name,
        "start_template_language": start_template_language,
        "start_template_configured": bool(start_template_name and start_template_language),
        "can_start_template": bool(
            access_token_ready
            and phone_number_id
            and start_template_name
            and start_template_language
        ),
        "checks": checks,
    }


def _normalize_whatsapp_recipient(value: str | None) -> str:
    """Return a WhatsApp/E.164-style recipient without formatting characters."""
    raw = str(value or "").strip()
    digits = "".join(character for character in raw if character.isdigit())

    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        # Ticket intake currently targets German workshops. Meta expects the
        # international number without a leading plus sign.
        digits = f"49{digits[1:]}"

    return digits


def _meta_send_error(send_result: Any) -> str:
    if getattr(send_result, "status_code", None) is None:
        technical_detail = str(getattr(send_result, "error", "") or "Netzwerkfehler").strip()
        return (
            "Der Versandstatus ist unklar: Meta konnte die Nachricht bereits angenommen haben, "
            "bevor die Verbindung abbrach. Bitte nicht erneut senden, bis der Verlauf oder der "
            f"Meta-Status geprüft wurde. Technischer Hinweis: {technical_detail}"
        )

    payload = send_result.payload if isinstance(getattr(send_result, "payload", None), dict) else {}
    meta_error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(meta_error, dict):
        message = str(meta_error.get("message") or "").strip()
        code = str(meta_error.get("code") or "").strip()
        if message and code:
            return f"{message} (Meta-Code {code})"
        if message:
            return message

    return str(getattr(send_result, "error", "") or "Meta hat die WhatsApp-Nachricht abgelehnt.").strip()


def _meta_outbound_status(send_result: Any) -> str:
    if bool(getattr(send_result, "ok", False)):
        return "sent"
    return "failed" if getattr(send_result, "status_code", None) is not None else "unknown"


def _human_send_redirect_status(sent: bool, detail: str) -> str:
    if sent:
        return "sent"
    if str(detail or "").startswith("Der Versandstatus ist unklar"):
        return "unknown"
    return "failed"


def _free_text_window_error(*, workshop_id: str, customer_phone: str) -> str | None:
    service_window = whatsapp_customer_service_window_for_phone(
        workshop_id=workshop_id,
        customer_phone=customer_phone,
    )
    if service_window.get("service_window_open"):
        return None
    return (
        "Das 24-Stunden-Kundenfenster ist geschlossen. Der eingegebene Freitext wurde "
        "nicht an Meta gesendet. Senden Sie zuerst die freigegebene Startvorlage; sobald "
        "der Kunde darauf antwortet, sind wieder freie Antworten möglich."
    )


def _take_over_conversation_before_send(
    *,
    workshop_id: str,
    customer_phone: str,
    ticket_id: str | None = None,
) -> dict[str, Any] | None:
    """Pause the assistant before an external send so it cannot race the employee."""
    try:
        previous_control = get_whatsapp_conversation_control(
            workshop_id=workshop_id,
            customer_phone=customer_phone,
        )
        if ticket_id:
            set_whatsapp_conversation_control(
                workshop_id=workshop_id,
                customer_phone=customer_phone,
                mode="manual",
                active_ticket_id=ticket_id,
            )
        else:
            set_whatsapp_conversation_control(
                workshop_id=workshop_id,
                customer_phone=customer_phone,
                mode="manual",
            )
        return previous_control
    except Exception:
        logger.exception(
            "Could not switch WhatsApp conversation to manual for workshop=%s phone=%s",
            workshop_id,
            customer_phone,
        )
        return None


def _restore_whatsapp_conversation_control(
    *,
    previous_control: dict[str, Any],
) -> None:
    """Best-effort rollback when Meta rejects a send after the pre-send takeover."""
    try:
        set_whatsapp_conversation_control(
            workshop_id=str(previous_control.get("workshop_id") or ""),
            customer_phone=str(previous_control.get("customer_phone") or ""),
            mode=str(previous_control.get("mode") or "assistant"),
            active_ticket_id=previous_control.get("active_ticket_id"),
        )
    except Exception:
        logger.exception(
            "Could not restore WhatsApp conversation control after failed send for workshop=%s phone=%s",
            previous_control.get("workshop_id"),
            previous_control.get("customer_phone"),
        )


def _linked_ticket_whatsapp_phone(
    *,
    workshop_id: str,
    ticket_id: str,
) -> str:
    linked_messages = list_whatsapp_messages(
        workshop_id=workshop_id,
        ticket_id=ticket_id,
        limit=250,
    )
    linked_phone = next(
        (
            str(message.get("customer_phone") or "").strip()
            for message in reversed(linked_messages)
            if str(message.get("customer_phone") or "").strip()
        ),
        "",
    )
    return _normalize_whatsapp_recipient(linked_phone)


def _ticket_whatsapp_phone(
    *,
    workshop_id: str,
    ticket_id: str,
    ticket: dict[str, Any],
) -> str:
    linked_phone = _linked_ticket_whatsapp_phone(
        workshop_id=workshop_id,
        ticket_id=ticket_id,
    )
    return linked_phone or _normalize_whatsapp_recipient(ticket.get("telefon"))


def _send_ticket_customer_whatsapp(
    *,
    request: Request,
    workshop_id: str,
    ticket_id: str,
    ticket: dict[str, Any],
    text: str,
    source: str = "dashboard_ticket",
) -> tuple[bool, str, str]:
    if not text:
        return False, "Die Nachricht darf nicht leer sein.", ""
    if len(text) > 4096:
        return False, "Die WhatsApp-Nachricht darf höchstens 4096 Zeichen lang sein.", ""

    recipient = _ticket_whatsapp_phone(
        workshop_id=workshop_id,
        ticket_id=ticket_id,
        ticket=ticket,
    )
    if not recipient:
        return False, "Für dieses Ticket ist keine Telefonnummer hinterlegt.", ""
    if len(recipient) < 8 or len(recipient) > 15:
        return False, "Die Telefonnummer ist für WhatsApp ungültig. Bitte im Ticket prüfen.", recipient

    workshop = get_workshop(workshop_id)
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    access_token = str(settings.whatsapp_access_token or "").strip()
    if not phone_number_id:
        return False, "Die WhatsApp Phone Number ID fehlt in den Einstellungen.", recipient
    if not access_token:
        return False, "Der WhatsApp Access Token fehlt auf dem Server.", recipient

    window_error = _free_text_window_error(
        workshop_id=workshop_id,
        customer_phone=recipient,
    )
    if window_error:
        return False, window_error, recipient

    previous_control = _take_over_conversation_before_send(
        workshop_id=workshop_id,
        customer_phone=recipient,
        ticket_id=ticket_id,
    )
    if previous_control is None:
        return (
            False,
            "Die Werkstatt konnte die Unterhaltung nicht sicher übernehmen. Es wurde nichts gesendet.",
            recipient,
        )

    send_result = send_whatsapp_text_message(
        phone_number_id=phone_number_id,
        customer_phone=recipient,
        text=text,
        access_token=access_token,
        graph_api_version=settings.whatsapp_graph_api_version,
    )
    manual_mode_set = True
    if not send_result.ok and send_result.status_code is not None:
        _restore_whatsapp_conversation_control(
            previous_control=previous_control,
        )
    message_payload = {
        "source": source,
        "local_only": False,
        "user": (get_current_user(request) or {}).get("email"),
        "meta_status_code": send_result.status_code,
        "meta_response": send_result.payload,
        "meta_error": send_result.error,
    }

    try:
        save_whatsapp_message(
            workshop_id=workshop_id,
            phone_number_id=phone_number_id,
            customer_phone=recipient,
            direction="outbound",
            message_type="text",
            text=text,
            wa_message_id=send_result.wa_message_id,
            ticket_id=ticket_id,
            status=_meta_outbound_status(send_result),
            payload=message_payload,
        )
    except Exception:
        logger.exception(
            "Could not persist WhatsApp send result for workshop=%s ticket=%s",
            workshop_id,
            ticket_id,
        )
        if not send_result.ok:
            return False, _meta_send_error(send_result), recipient
        detail = (
            "Die Nachricht wurde an Meta übergeben, konnte intern aber nicht protokolliert "
            "werden. Bitte nicht erneut senden."
        )
        if not manual_mode_set:
            detail += " Der Assistent konnte nicht automatisch pausiert werden."
        return (
            True,
            detail,
            recipient,
        )

    if not send_result.ok:
        return False, _meta_send_error(send_result), recipient

    try:
        add_ticket_note(ticket_id, text, note_type="customer_reply", workshop_id=workshop_id)
    except Exception:
        logger.exception(
            "Could not add customer reply note after WhatsApp send for workshop=%s ticket=%s",
            workshop_id,
            ticket_id,
        )
        detail = (
            "Die Nachricht wurde an Meta übergeben, die Ticketnotiz konnte aber nicht "
            "gespeichert werden. Bitte nicht erneut senden."
        )
        if not manual_mode_set:
            detail += " Der Assistent konnte nicht automatisch pausiert werden."
        return (
            True,
            detail,
            recipient,
        )

    detail = (
        f"WhatsApp-Nachricht wurde an Meta für {recipient} übergeben. "
        "Die Werkstatt hat die Unterhaltung übernommen; erst „Zugestellt“ bestätigt den Empfang."
    )
    if not manual_mode_set:
        detail += " Der Assistent konnte nicht automatisch pausiert werden."
    return True, detail, recipient


def _pick_first(d: dict, keys: list[str]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_name(t: dict) -> str:
    keys = [
        "kunde",
        "kundenname",
        "kunde_name",
        "client_name",
        "kontakt_name",
        "name",
        "vorname",
        "nachname",
        "fullname",
        "full_name",
    ]

    name = _pick_first(t, keys)
    if name:
        return name

    raw = t.get("raw")
    if isinstance(raw, dict):
        name2 = _pick_first(raw, keys)
        if name2:
            return name2

        kontakt = raw.get("kontakt") if isinstance(raw.get("kontakt"), dict) else None
        if kontakt:
            name3 = _pick_first(kontakt, keys)
            if name3:
                return name3

    return ""


def _matches_query(t: dict, q: str) -> bool:
    q = (q or "").strip().lower()
    if not q:
        return True

    if q in {"kundenfrage", "kundenfragen", "chatfrage", "chat-fragen"}:
        return bool(t.get("has_customer_question"))

    if q in {"kostenvoranschlag", "kostenvoranschlaege", "kostenvoranschläge", "preisanfrage", "angebot"}:
        return t.get("request_type") == "kostenvoranschlag"

    hay = " ".join(
        [
            str(t.get("_id", "")).lower(),
            str(t.get("id", "")).lower(),
            str(t.get("ticket_id", "")).lower(),
            str(t.get("ticket_view_id", "")).lower(),
            str(t.get("kunde_name", "")).lower(),
            str(t.get("fahrzeug", "")).lower(),
            str(t.get("problem", "")).lower(),
            str(t.get("telefon", "")).lower(),
            str(t.get("baujahr", "")).lower(),
            str(t.get("priority", "")).lower(),
            str(t.get("request_type", "")).lower(),
            str(t.get("status", "")).lower(),
            str(t.get("last_note_text", "")).lower(),
        ]
    )
    return q in hay


def _is_customer_question_note(note: dict) -> bool:
    text = str(note.get("text", "") if isinstance(note, dict) else "").strip()
    note_type = str(note.get("type", "") if isinstance(note, dict) else "").strip().lower()
    return note_type == "customer_message" or text.lower().startswith("kundenfrage über den chat:")


def _note_type(note: dict) -> str:
    if not isinstance(note, dict):
        return "internal_note"

    note_type = str(note.get("type", "")).strip().lower()
    if note_type in {"internal_note", "customer_message", "customer_reply"}:
        return note_type

    return "customer_message" if _is_customer_question_note(note) else "internal_note"


def _details_payload(t: dict) -> dict:
    safe = dict(t)
    safe.pop("created_dt", None)
    safe.pop("updated_dt", None)
    safe.pop("details_json", None)
    return safe


def _prepare_tickets(limit: int, workshop_id: str | None = None) -> list[dict]:
    wid = _normalize_workshop_id(workshop_id)
    raw = list_latest_tickets(limit=limit, workshop_id=wid)
    tickets = [_as_dict(t) for t in raw]
    whatsapp_phone_by_ticket: dict[str, str] = {}
    for message in list_whatsapp_messages(workshop_id=wid, limit=500):
        linked_ticket_id = str(message.get("ticket_id") or "").strip()
        linked_phone = _normalize_whatsapp_recipient(message.get("customer_phone"))
        if linked_ticket_id and linked_phone:
            whatsapp_phone_by_ticket[linked_ticket_id] = linked_phone

    for t in tickets:
        t["ticket_view_id"] = _ticket_id(t)
        t["status"] = _normalize_status(t.get("status"))
        t["status_ui"] = _ui_status(t.get("status"))
        t["priority"] = _normalize_priority(t.get("priority"))
        t["request_type"] = _normalize_request_type(t.get("request_type"))
        t["source"] = _normalize_source(t.get("source"))
        t["status_label"] = _status_label(t.get("status_ui"))
        t["priority_label"] = _priority_label(t.get("priority"))
        t["request_type_label"] = _request_type_label(t.get("request_type"))
        t["source_label"] = _source_label(t.get("source"))
        t["created_dt"] = _parse_iso(t.get("created_at"))
        t["updated_dt"] = _parse_iso(t.get("updated_at"))
        t["created_at_display"] = _format_datetime_for_display(t.get("created_at"))
        t["updated_at_display"] = _format_datetime_for_display(t.get("updated_at"))
        t["is_new"] = (t.get("created_at") == t.get("updated_at"))
        t["kunde_name"] = _extract_name(t)
        linked_whatsapp_phone = whatsapp_phone_by_ticket.get(t["ticket_view_id"], "")
        t["has_whatsapp_conversation"] = bool(linked_whatsapp_phone)
        t["whatsapp_phone"] = linked_whatsapp_phone or _normalize_whatsapp_recipient(
            t.get("telefon")
        )
        t["can_message_customer"] = bool(t["whatsapp_phone"])
        if t["whatsapp_phone"]:
            t.update(
                whatsapp_customer_service_window_for_phone(
                    workshop_id=wid,
                    customer_phone=t["whatsapp_phone"],
                )
            )
            conversation_control = get_whatsapp_conversation_control(
                workshop_id=wid,
                customer_phone=t["whatsapp_phone"],
            )
            t["whatsapp_mode"] = conversation_control.get("mode") or "assistant"
        else:
            t["service_window_open"] = False
            t["service_window_expires_at"] = None
            t["last_customer_message_at"] = None
            t["whatsapp_mode"] = "assistant"

        notes = t.get("notes") if isinstance(t.get("notes"), list) else []
        last_note = notes[-1] if notes else {}
        customer_question_notes = [
            note
            for note in notes
            if isinstance(note, dict) and _is_customer_question_note(note)
        ]
        latest_customer_question = (
            customer_question_notes[-1]
            if customer_question_notes
            else {}
        )

        t["has_customer_question"] = bool(customer_question_notes)
        t["customer_question_count"] = len(customer_question_notes)
        t["customer_question_open"] = bool(t.get("customer_question_open"))
        t["latest_customer_question_text"] = (
            str(latest_customer_question.get("text", "")).strip()
            if latest_customer_question
            else ""
        )
        t["latest_customer_question_created_at"] = (
            str(latest_customer_question.get("created_at", "")).strip()
            if latest_customer_question
            else ""
        )
        t["latest_customer_question_created_at_display"] = _format_datetime_for_display(
            t["latest_customer_question_created_at"]
        )

        t["last_note_text"] = (
            str(last_note.get("text", "")).strip()
            if isinstance(last_note, dict)
            else ""
        )
        t["last_note_created_at"] = (
            str(last_note.get("created_at", "")).strip()
            if isinstance(last_note, dict)
            else ""
        )
        t["last_note_created_at_display"] = _format_datetime_for_display(
            t["last_note_created_at"]
        )

        if t["has_customer_question"] and not t["customer_question_open"]:
            latest_customer_question_at = _parse_iso(t.get("latest_customer_question_created_at"))
            customer_replies = [
                note for note in notes
                if isinstance(note, dict) and _note_type(note) == "customer_reply"
            ]
            latest_customer_reply_at = _parse_iso(
                customer_replies[-1].get("created_at")
                if customer_replies
                else None
            )
            if latest_customer_reply_at < latest_customer_question_at:
                t["customer_question_open"] = True

        t["details_payload"] = _details_payload(t)
        t["details_json"] = json.dumps(
            t["details_payload"],
            ensure_ascii=False,
            default=str,
        )

    return tickets


def _stats_for(tickets: list[dict]) -> dict:
    return {
        "offen": sum(1 for t in tickets if t.get("status_ui") == "offen"),
        "in_bearbeitung": sum(1 for t in tickets if t.get("status_ui") == "in_bearbeitung"),
        "erledigt": sum(1 for t in tickets if t.get("status_ui") == "erledigt"),
        "archiviert": sum(1 for t in tickets if t.get("status_ui") == "archiviert"),
        "hoch": sum(1 for t in tickets if t.get("priority") == "hoch"),
        "normal": sum(1 for t in tickets if t.get("priority") == "normal"),
        "niedrig": sum(1 for t in tickets if t.get("priority") == "niedrig"),
        "service": sum(1 for t in tickets if t.get("request_type") == "service"),
        "diagnose": sum(1 for t in tickets if t.get("request_type") == "diagnose"),
        "notfall": sum(1 for t in tickets if t.get("request_type") == "notfall"),
        "kostenvoranschlag": sum(1 for t in tickets if t.get("request_type") == "kostenvoranschlag"),
        "kundenfragen": sum(1 for t in tickets if t.get("has_customer_question")),
        "kundenfragen_offen": sum(1 for t in tickets if t.get("customer_question_open")),
        "all": len(tickets),
    }


def _priority_rank(priority: str) -> int:
    mapping = {
        "hoch": 0,
        "normal": 1,
        "niedrig": 2,
    }
    return mapping.get(priority, 9)


def _attention_reason(t: dict) -> str:
    if t.get("customer_question_open"):
        count = int(t.get("customer_question_count") or 0)
        if count > 1:
            return f"{count} offene Kundenfragen"
        return "Offene Kundenfrage"

    if t.get("has_customer_question"):
        count = int(t.get("customer_question_count") or 0)
        if count > 1:
            return f"{count} Kundenfragen"
        return "Kundenfrage"

    if t.get("request_type") == "notfall":
        return "Notfall"

    if t.get("priority") == "hoch":
        return "Hohe Prioritaet"

    if t.get("request_type") == "kostenvoranschlag":
        return "Kostenvoranschlag"

    return "Wichtig"


def _attention_rank(t: dict) -> tuple[int, float]:
    if t.get("customer_question_open"):
        rank = 0
    elif t.get("has_customer_question"):
        rank = 1
    elif t.get("request_type") == "notfall":
        rank = 2
    elif t.get("priority") == "hoch":
        rank = 3
    elif t.get("request_type") == "kostenvoranschlag":
        rank = 4
    else:
        rank = 9

    updated = t.get("updated_dt")
    timestamp = (
        updated.timestamp()
        if isinstance(updated, datetime) and updated != datetime.min.replace(tzinfo=timezone.utc)
        else 0
    )
    return rank, -timestamp


def _attention_tickets(tickets: list[dict], limit: int = 5) -> list[dict]:
    important = [
        t
        for t in tickets
        if t.get("status_ui") not in {"erledigt", "archiviert"}
        and (
            t.get("has_customer_question")
            or t.get("priority") == "hoch"
            or t.get("request_type") in {"notfall", "kostenvoranschlag"}
        )
    ]

    important.sort(key=_attention_rank)

    result = []
    for ticket in important[:limit]:
        item = dict(ticket)
        item["attention_reason"] = _attention_reason(ticket)
        result.append(item)

    return result


def _render_dashboard(
    request: Request,
    *,
    archive_mode: bool,
    status: str | None,
    source: str | None,
    question_state: str | None,
    q: str | None,
    sort: str | None,
    limit: int,
    workshop_id: str | None = None,
    message_status: str | None = None,
    message_detail: str | None = None,
    message_ticket: str | None = None,
):
    wid = _normalize_workshop_id(workshop_id)
    workshop = get_workshop(wid)
    tickets = _prepare_tickets(limit=limit, workshop_id=wid)

    if archive_mode:
        tickets = [t for t in tickets if t.get("status_ui") == "archiviert"]
    else:
        tickets = [t for t in tickets if t.get("status_ui") != "archiviert"]

    stats = _stats_for(tickets)
    attention_tickets = _attention_tickets(tickets)

    normalized_filter_status = _normalize_status(status) if status and status != "all" else "all"
    normalized_filter_source = _normalize_filter_source(source)
    normalized_filter_question_state = _normalize_filter_question_state(question_state)

    if normalized_filter_status != "all":
        tickets = [t for t in tickets if t.get("status_ui") == normalized_filter_status]

    if normalized_filter_source != "all":
        tickets = [t for t in tickets if t.get("source") == normalized_filter_source]

    if normalized_filter_question_state == "open":
        tickets = [t for t in tickets if t.get("customer_question_open")]
    elif normalized_filter_question_state == "answered":
        tickets = [
            t for t in tickets
            if t.get("has_customer_question") and not t.get("customer_question_open")
        ]

    if q and q.strip():
        tickets = [t for t in tickets if _matches_query(t, q)]

    if sort == "oldest":
        tickets.sort(key=lambda t: t["created_dt"])
    elif sort == "updated":
        tickets.sort(key=lambda t: t["updated_dt"], reverse=True)
    elif sort == "priority":
        tickets.sort(
            key=lambda t: (
                _priority_rank(t.get("priority", "")),
                -t["created_dt"].timestamp()
                if t["created_dt"] != datetime.min.replace(tzinfo=timezone.utc)
                else 0,
            )
        )
    else:
        tickets.sort(key=lambda t: t["created_dt"], reverse=True)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _template_context(
            request,
            workshop=workshop,
            whatsapp_readiness=_whatsapp_readiness(request, workshop),
            tickets=tickets,
            attention_tickets=attention_tickets,
            stats=stats,
            filters={
                "status": normalized_filter_status,
                "source": normalized_filter_source,
                "question_state": normalized_filter_question_state,
                "q": q or "",
                "sort": sort or "newest",
                "limit": limit,
                "workshop_id": wid,
            },
            archive_mode=archive_mode,
            workshop_id=wid,
            message_status=(message_status or "").strip(),
            message_detail=(message_detail or "").strip(),
            message_ticket=(message_ticket or "").strip(),
        ),
    )


# -------------------------
# Routes
# -------------------------
@router.get("/", response_class=HTMLResponse)
def home_page(request: Request):
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
        },
    )


@router.get("/datenschutz", response_class=HTMLResponse)
def datenschutz_page(request: Request):
    return templates.TemplateResponse(
        request,
        "datenschutz.html",
        {
            "request": request,
        },
    )


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, workshop_id: str | None = None):
    # An explicit invalid ID must never send a customer to the default workshop.
    wid = _normalize_workshop_id() if workshop_id is None else workshop_id.strip()
    workshop = get_workshop_identity(wid)
    if not workshop:
        return HTMLResponse("Werkstatt wurde nicht gefunden.", status_code=404)
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "workshop": workshop,
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
):
    return templates.TemplateResponse(
        request,
        "login.html",
        _template_context(
            request,
            next=next or "/dashboard",
            error=error,
        ),
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
):
    user = authenticate_user(email, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            _template_context(
                request,
                next=next or "/dashboard",
                error="E-Mail oder Passwort ist falsch.",
            ),
            status_code=401,
        )

    target = next if next.startswith("/") and not next.startswith("//") else "/dashboard"
    response = RedirectResponse(url=target, status_code=303)
    set_session_cookie(response, user, request=request)
    return response


@router.post("/logout")
def logout_submit():
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status: str | None = None,
    source: str | None = None,
    question_state: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int = 250,
    workshop_id: str | None = None,
    message_status: str | None = None,
    message_detail: str | None = None,
    message_ticket: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    return _render_dashboard(
        request,
        archive_mode=False,
        status=status,
        source=source,
        question_state=question_state,
        q=q,
        sort=sort,
        limit=limit,
        workshop_id=wid,
        message_status=message_status,
        message_detail=message_detail,
        message_ticket=message_ticket,
    )


@router.get("/dashboard/archive", response_class=HTMLResponse)
def dashboard_archive(
    request: Request,
    status: str | None = None,
    source: str | None = None,
    question_state: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int = 250,
    workshop_id: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    return _render_dashboard(
        request,
        archive_mode=True,
        status=status,
        source=source,
        question_state=question_state,
        q=q,
        sort=sort,
        limit=limit,
        workshop_id=wid,
        message_status=None,
        message_detail=None,
        message_ticket=None,
    )


@router.get("/dashboard/settings", response_class=HTMLResponse)
def dashboard_settings(
    request: Request,
    workshop_id: str | None = None,
    saved: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)

    return templates.TemplateResponse(
        request,
        "settings.html",
        _template_context(
            request,
            workshop=workshop,
            workshop_id=wid,
            saved=saved == "1",
        ),
    )


@router.get("/dashboard/billing", response_class=HTMLResponse)
def dashboard_billing(
    request: Request,
    workshop_id: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)

    return templates.TemplateResponse(
        request,
        "billing.html",
        _template_context(
            request,
            workshop_id=wid,
            workshop=workshop,
            subscription=get_subscription(wid),
        ),
    )


@router.get("/dashboard/admin/workshops", response_class=HTMLResponse)
def dashboard_admin_workshops(
    request: Request,
    created: str | None = None,
    updated: str | None = None,
    reset: str | None = None,
    error: str | None = None,
):
    if not _is_admin_user(request):
        return HTMLResponse("Nur Admins duerfen Werkstattkonten verwalten.", status_code=403)

    return templates.TemplateResponse(
        request,
        "admin_workshops.html",
        _template_context(
            request,
            workshop_id=str((get_current_user(request) or {}).get("workshop_id") or ""),
            workshops=list_workshop_accounts(),
            created=(created or "").strip(),
            updated=(updated or "").strip(),
            reset=(reset or "").strip(),
            error=(error or "").strip(),
        ),
    )


@router.post("/dashboard/admin/workshops")
def dashboard_admin_workshops_create(
    request: Request,
    workshop_id: str = Form(""),
    workshop_name: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    opening_hours: str = Form(""),
    services: str = Form(""),
    pricing_info: str = Form(""),
    towing_info: str = Form(""),
    subscription_plan: str = Form("starter"),
    subscription_status: str = Form("trialing"),
    whatsapp_phone_number_id: str = Form(""),
    whatsapp_display_phone_number: str = Form(""),
):
    if not _is_admin_user(request):
        return HTMLResponse("Nur Admins duerfen Werkstattkonten verwalten.", status_code=403)

    try:
        account = create_workshop_account(
            workshop_id=workshop_id,
            workshop_name=workshop_name,
            admin_email=admin_email,
            admin_password=admin_password,
            address=address,
            phone=phone,
            email=email,
            opening_hours=opening_hours,
            services=services,
            pricing_info=pricing_info,
            towing_info=towing_info,
            subscription_plan=subscription_plan,
            subscription_status=subscription_status,
            whatsapp_phone_number_id=whatsapp_phone_number_id,
            whatsapp_display_phone_number=whatsapp_display_phone_number,
        )
    except ValueError as exc:
        return RedirectResponse(
            url="/dashboard/admin/workshops?" + urlencode({"error": str(exc)}),
            status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url="/dashboard/admin/workshops?" + urlencode({"error": "Werkstattkonto konnte nicht erstellt werden."}),
            status_code=303,
        )

    return RedirectResponse(
        url="/dashboard/admin/workshops?" + urlencode({"created": account["id"]}),
        status_code=303,
    )


@router.get("/dashboard/admin/workshops/{admin_workshop_id}", response_class=HTMLResponse)
def dashboard_admin_workshop_edit(
    request: Request,
    admin_workshop_id: str,
    saved: str | None = None,
    reset: str | None = None,
    error: str | None = None,
):
    if not _is_admin_user(request):
        return HTMLResponse("Nur Admins duerfen Werkstattkonten verwalten.", status_code=403)

    account = get_workshop_account(admin_workshop_id)
    if not account:
        return HTMLResponse("Werkstattkonto wurde nicht gefunden.", status_code=404)

    return templates.TemplateResponse(
        request,
        "admin_workshop_edit.html",
        _template_context(
            request,
            workshop_id=str((get_current_user(request) or {}).get("workshop_id") or ""),
            account=account,
            saved=(saved or "").strip(),
            reset=(reset or "").strip(),
            error=(error or "").strip(),
        ),
    )


@router.post("/dashboard/admin/workshops/{admin_workshop_id}")
def dashboard_admin_workshop_update(
    request: Request,
    admin_workshop_id: str,
    workshop_name: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    opening_hours: str = Form(""),
    services: str = Form(""),
    pricing_info: str = Form(""),
    towing_info: str = Form(""),
    subscription_plan: str = Form("starter"),
    subscription_status: str = Form("trialing"),
    trial_ends_at: str = Form(""),
    subscription_ends_at: str = Form(""),
    whatsapp_phone_number_id: str = Form(""),
    whatsapp_display_phone_number: str = Form(""),
):
    if not _is_admin_user(request):
        return HTMLResponse("Nur Admins duerfen Werkstattkonten verwalten.", status_code=403)

    try:
        update_workshop_account(
            workshop_id=admin_workshop_id,
            workshop_name=workshop_name,
            address=address,
            phone=phone,
            email=email,
            opening_hours=opening_hours,
            services=services,
            pricing_info=pricing_info,
            towing_info=towing_info,
            subscription_plan=subscription_plan,
            subscription_status=subscription_status,
            trial_ends_at=trial_ends_at,
            subscription_ends_at=subscription_ends_at,
            whatsapp_phone_number_id=whatsapp_phone_number_id,
            whatsapp_display_phone_number=whatsapp_display_phone_number,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/dashboard/admin/workshops/{admin_workshop_id}?" + urlencode({"error": str(exc)}),
            status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url=f"/dashboard/admin/workshops/{admin_workshop_id}?"
            + urlencode({"error": "Werkstattkonto konnte nicht gespeichert werden."}),
            status_code=303,
        )

    return RedirectResponse(
        url=f"/dashboard/admin/workshops/{admin_workshop_id}?" + urlencode({"saved": "1"}),
        status_code=303,
    )


@router.post("/dashboard/admin/workshops/{admin_workshop_id}/reset-password")
def dashboard_admin_workshop_reset_password(
    request: Request,
    admin_workshop_id: str,
    owner_email: str = Form(...),
    new_password: str = Form(...),
):
    if not _is_admin_user(request):
        return HTMLResponse("Nur Admins duerfen Werkstattkonten verwalten.", status_code=403)

    try:
        reset_workshop_owner_password(
            workshop_id=admin_workshop_id,
            owner_email=owner_email,
            new_password=new_password,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/dashboard/admin/workshops/{admin_workshop_id}?" + urlencode({"error": str(exc)}),
            status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url=f"/dashboard/admin/workshops/{admin_workshop_id}?"
            + urlencode({"error": "Passwort konnte nicht aktualisiert werden."}),
            status_code=303,
        )

    return RedirectResponse(
        url=f"/dashboard/admin/workshops/{admin_workshop_id}?" + urlencode({"reset": owner_email}),
        status_code=303,
    )


@router.get("/dashboard/whatsapp", response_class=HTMLResponse)
def dashboard_whatsapp(
    request: Request,
    phone: str | None = None,
    workshop_id: str | None = None,
    test_status: str | None = None,
    test_detail: str | None = None,
    reply_status: str | None = None,
    reply_detail: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)
    readiness = _whatsapp_readiness(request, workshop)
    conversations = []
    for conversation in list_whatsapp_conversations(workshop_id=wid):
        item = dict(conversation)
        control = get_whatsapp_conversation_control(
            workshop_id=wid,
            customer_phone=str(item.get("customer_phone") or ""),
        )
        item["mode"] = control.get("mode") or "assistant"
        item["active_ticket_id"] = control.get("active_ticket_id")
        item["mode_label"] = (
            "Werkstatt antwortet"
            if item["mode"] == "manual"
            else "Assistent antwortet"
        )
        item["last_created_at_display"] = _format_datetime_for_display(
            item.get("last_created_at")
        )
        item["last_customer_message_at_display"] = _format_datetime_for_display(
            item.get("last_customer_message_at")
        )
        item["service_window_expires_at_display"] = _format_datetime_for_display(
            item.get("service_window_expires_at")
        )
        conversations.append(item)
    selected_phone = _normalize_whatsapp_recipient(phone)

    if not selected_phone and conversations:
        selected_phone = str(conversations[0].get("customer_phone") or "")

    messages = []
    selected_conversation = None
    if selected_phone:
        messages = _decorate_whatsapp_messages(
            list_whatsapp_messages(
                workshop_id=wid,
                customer_phone=selected_phone,
                limit=250,
            )
        )
        selected_conversation = next(
            (
                conversation
                for conversation in conversations
                if conversation.get("customer_phone") == selected_phone
            ),
            None,
        )

    return templates.TemplateResponse(
        request,
        "whatsapp.html",
        _template_context(
            request,
            workshop_id=wid,
            workshop=workshop,
            readiness=readiness,
            conversations=conversations,
            selected_phone=selected_phone,
            selected_conversation=selected_conversation,
            messages=messages,
            test_status=(test_status or "").strip(),
            test_detail=(test_detail or "").strip(),
            reply_status=(reply_status or "").strip(),
            reply_detail=(reply_detail or "").strip(),
        ),
    )


@router.post("/dashboard/whatsapp/test")
def dashboard_whatsapp_test(
    request: Request,
    test_phone: str | None = Form(None),
    customer_phone: str | None = Form(None),
    test_text: str = Form("WerkstattAI Testnachricht. WhatsApp Verbindung funktioniert."),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    submitted_customer_phone = customer_phone if isinstance(customer_phone, str) else ""
    submitted_test_phone = test_phone if isinstance(test_phone, str) else ""
    phone = _normalize_whatsapp_recipient(submitted_customer_phone or submitted_test_phone)
    text = (test_text or "").strip() or "WerkstattAI Testnachricht. WhatsApp Verbindung funktioniert."

    def redirect(status: str, detail: str) -> RedirectResponse:
        query = urlencode(
            {
                "workshop_id": wid,
                "phone": phone,
                "test_status": status,
                "test_detail": detail,
            }
        )
        return RedirectResponse(url=f"/dashboard/whatsapp?{query}", status_code=303)

    if not phone:
        return redirect("failed", "Testnummer fehlt.")
    if len(phone) < 8 or len(phone) > 15:
        return redirect("failed", "Die Testnummer ist für WhatsApp ungültig.")

    workshop = get_workshop(wid)
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    access_token = str(settings.whatsapp_access_token or "").strip()
    if not access_token:
        return redirect("failed", "WHATSAPP_ACCESS_TOKEN fehlt.")
    if not phone_number_id:
        return redirect("failed", "Phone Number ID fehlt in den Werkstatt-Einstellungen.")

    window_error = _free_text_window_error(
        workshop_id=wid,
        customer_phone=phone,
    )
    if window_error:
        return redirect(
            "failed",
            window_error + " Nutzen Sie für den Ersttest die konfigurierte Startvorlage.",
        )

    previous_control = _take_over_conversation_before_send(
        workshop_id=wid,
        customer_phone=phone,
    )
    if previous_control is None:
        return redirect(
            "failed",
            "Die Werkstatt konnte den Testkontakt nicht sicher übernehmen. Es wurde nichts gesendet.",
        )

    send_result = send_whatsapp_text_message(
        phone_number_id=phone_number_id,
        customer_phone=phone,
        text=text,
        access_token=access_token,
        graph_api_version=settings.whatsapp_graph_api_version,
    )
    if not send_result.ok and send_result.status_code is not None:
        _restore_whatsapp_conversation_control(previous_control=previous_control)

    status = _meta_outbound_status(send_result)
    save_whatsapp_message(
        workshop_id=wid,
        phone_number_id=phone_number_id,
        customer_phone=phone,
        direction="outbound",
        message_type="text",
        text=text,
        wa_message_id=send_result.wa_message_id,
        status=status,
        payload={
            "source": "dashboard_test",
            "local_only": False,
            "user": (get_current_user(request) or {}).get("email"),
            "meta_status_code": send_result.status_code,
            "meta_response": send_result.payload,
            "meta_error": send_result.error,
        },
    )

    if send_result.ok:
        return redirect("sent", "Testnachricht wurde an die Meta API übergeben. Die Zustellung wird separat bestätigt.")

    detail = _meta_send_error(send_result)
    return redirect(
        "unknown" if send_result.status_code is None else "failed",
        detail,
    )


@router.post("/dashboard/whatsapp/reply")
def dashboard_whatsapp_reply(
    request: Request,
    customer_phone: str = Form(...),
    reply_text: str = Form(...),
    ticket_id: str | None = Form(None),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    phone = _normalize_whatsapp_recipient(customer_phone)
    text = (reply_text or "").strip()

    def redirect(status: str, detail: str) -> RedirectResponse:
        query = urlencode(
            {
                "workshop_id": wid,
                "phone": phone,
                "reply_status": status,
                "reply_detail": detail,
            }
        )
        return RedirectResponse(url=f"/dashboard/whatsapp?{query}", status_code=303)

    if not phone:
        return redirect("failed", "WhatsApp-Kontakt fehlt.")
    if len(phone) < 8 or len(phone) > 15:
        return redirect("failed", "Die Telefonnummer ist für WhatsApp ungültig.")
    if not text:
        return redirect("failed", "Antwort darf nicht leer sein.")
    if len(text) > 4096:
        return redirect("failed", "Die WhatsApp-Nachricht darf höchstens 4096 Zeichen lang sein.")

    try:
        normalized_ticket_id = ticket_id.strip() if isinstance(ticket_id, str) else ""
        if normalized_ticket_id:
            ticket = find_ticket_by_id(normalized_ticket_id, workshop_id=wid)
            if not ticket:
                return redirect("failed", "Ticket wurde nicht gefunden. Es wurde nichts gesendet.")
            if _ticket_whatsapp_phone(
                workshop_id=wid,
                ticket_id=normalized_ticket_id,
                ticket=ticket,
            ) != phone:
                return redirect(
                    "failed",
                    "Die WhatsApp-Nummer passt nicht zu diesem Ticket. Es wurde nichts gesendet.",
                )
            sent, detail, _ = _send_ticket_customer_whatsapp(
                request=request,
                workshop_id=wid,
                ticket_id=normalized_ticket_id,
                ticket=ticket,
                text=text,
                source="dashboard_whatsapp_inbox",
            )
            return redirect(_human_send_redirect_status(sent, detail), detail)
        if not list_whatsapp_messages(
            workshop_id=wid,
            customer_phone=phone,
            limit=1,
        ):
            return redirect(
                "failed",
                "Diese Unterhaltung gehört nicht zum WhatsApp-Posteingang Ihrer Werkstatt.",
            )

        workshop = get_workshop(wid)
        phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
        access_token = str(settings.whatsapp_access_token or "").strip()
        if not phone_number_id:
            return redirect("failed", "Die WhatsApp Phone Number ID fehlt in den Einstellungen.")
        if not access_token:
            return redirect("failed", "Der WhatsApp Access Token fehlt auf dem Server.")

        window_error = _free_text_window_error(
            workshop_id=wid,
            customer_phone=phone,
        )
        if window_error:
            return redirect("failed", window_error)

        previous_control = _take_over_conversation_before_send(
            workshop_id=wid,
            customer_phone=phone,
        )
        if previous_control is None:
            return redirect(
                "failed",
                "Die Werkstatt konnte die Unterhaltung nicht sicher übernehmen. Es wurde nichts gesendet.",
            )

        send_result = send_whatsapp_text_message(
            phone_number_id=phone_number_id,
            customer_phone=phone,
            text=text,
            access_token=access_token,
            graph_api_version=settings.whatsapp_graph_api_version,
        )
        manual_mode_set = True
        if not send_result.ok and send_result.status_code is not None:
            _restore_whatsapp_conversation_control(
                previous_control=previous_control,
            )
        status = _meta_outbound_status(send_result)

        try:
            save_whatsapp_message(
                workshop_id=wid,
                phone_number_id=phone_number_id,
                customer_phone=phone,
                direction="outbound",
                message_type="text",
                text=text,
                wa_message_id=send_result.wa_message_id,
                status=status,
                payload={
                    "source": "dashboard",
                    "local_only": False,
                    "user": (get_current_user(request) or {}).get("email"),
                    "meta_status_code": send_result.status_code,
                    "meta_response": send_result.payload,
                    "meta_error": send_result.error,
                },
            )
        except Exception:
            logger.exception(
                "Could not persist inbox WhatsApp send result for workshop=%s",
                wid,
            )
            if send_result.ok:
                return redirect(
                    "sent",
                    "Die Nachricht wurde an Meta übergeben, konnte intern aber nicht protokolliert werden. Bitte nicht erneut senden.",
                )
            detail = _meta_send_error(send_result)
            return redirect(
                "unknown" if send_result.status_code is None else "failed",
                detail,
            )

        if not send_result.ok:
            detail = _meta_send_error(send_result)
            return redirect(
                "unknown" if send_result.status_code is None else "failed",
                detail,
            )
    except Exception:
        return redirect("failed", "Die Antwort konnte technisch nicht gesendet werden.")

    detail = (
        "WhatsApp-Nachricht wurde an Meta übergeben. Die Werkstatt hat die Unterhaltung "
        "übernommen. Erst der Status „Zugestellt“ bestätigt den Empfang am Kundenhandy."
    )
    if not manual_mode_set:
        detail += " Der Assistent konnte nicht automatisch pausiert werden."
    return redirect(
        "sent",
        detail,
    )


def _whatsapp_action_redirect(
    *,
    workshop_id: str,
    customer_phone: str,
    context: str,
    status: str,
    detail: str,
    ticket_id: str | None = None,
) -> RedirectResponse:
    normalized_context = str(context or "").strip().lower()
    if normalized_context == "dashboard" and ticket_id:
        query = urlencode(
            {
                "workshop_id": workshop_id,
                "message_status": status,
                "message_detail": detail,
                "message_ticket": ticket_id,
            }
        )
        return RedirectResponse(url=f"/dashboard?{query}", status_code=303)

    if normalized_context == "ticket" and ticket_id:
        query = urlencode(
            {
                "workshop_id": workshop_id,
                "reply_status": status,
                "reply_detail": detail,
            }
        )
        return RedirectResponse(
            url=f"/dashboard/ticket/{ticket_id}?{query}",
            status_code=303,
        )

    status_key = "test_status" if normalized_context == "test" else "reply_status"
    detail_key = "test_detail" if normalized_context == "test" else "reply_detail"
    query = urlencode(
        {
            "workshop_id": workshop_id,
            "phone": customer_phone,
            status_key: status,
            detail_key: detail,
        }
    )
    return RedirectResponse(url=f"/dashboard/whatsapp?{query}", status_code=303)


@router.post("/dashboard/whatsapp/start-template")
def dashboard_whatsapp_start_template(
    request: Request,
    customer_phone: str = Form(...),
    workshop_id: str | None = Form(None),
    ticket_id: str | None = Form(None),
    context: str = Form("inbox"),
):
    """Start a customer conversation with the server-configured approved template."""
    wid = _workshop_id_for_request(request, workshop_id)
    phone = _normalize_whatsapp_recipient(customer_phone)
    normalized_ticket_id = ticket_id.strip() if isinstance(ticket_id, str) else ""
    normalized_context = context.strip().lower() if isinstance(context, str) else "inbox"
    if normalized_context not in {"inbox", "dashboard", "ticket", "test"}:
        normalized_context = "inbox"

    def redirect(status: str, detail: str) -> RedirectResponse:
        return _whatsapp_action_redirect(
            workshop_id=wid,
            customer_phone=phone,
            context=normalized_context,
            status=status,
            detail=detail,
            ticket_id=normalized_ticket_id or None,
        )

    if not phone or len(phone) < 8 or len(phone) > 15:
        return redirect("failed", "Die Telefonnummer ist für WhatsApp ungültig.")

    ticket = None
    if normalized_ticket_id:
        ticket = find_ticket_by_id(normalized_ticket_id, workshop_id=wid)
        if not ticket:
            return redirect("failed", "Ticket wurde nicht gefunden.")
        ticket_phone = _ticket_whatsapp_phone(
            workshop_id=wid,
            ticket_id=normalized_ticket_id,
            ticket=ticket,
        )
        if not ticket_phone or ticket_phone != phone:
            return redirect(
                "failed",
                "Die WhatsApp-Nummer passt nicht zu diesem Ticket. Es wurde nichts gesendet.",
            )
    elif normalized_context in {"dashboard", "ticket"}:
        return redirect("failed", "Für diesen Vorgang fehlt ein gültiges Ticket.")
    elif normalized_context == "inbox" and not list_whatsapp_messages(
        workshop_id=wid,
        customer_phone=phone,
        limit=1,
    ):
        return redirect("failed", "Diese Unterhaltung gehört nicht zum WhatsApp-Posteingang.")

    workshop = get_workshop(wid)
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    access_token = str(settings.whatsapp_access_token or "").strip()
    template_name = str(settings.whatsapp_start_template_name or "").strip()
    template_language = str(settings.whatsapp_start_template_language or "").strip()
    missing = []
    if not access_token:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not phone_number_id:
        missing.append("Phone Number ID")
    if not template_name:
        missing.append("WHATSAPP_START_TEMPLATE_NAME")
    if not template_language:
        missing.append("WHATSAPP_START_TEMPLATE_LANGUAGE")
    if missing:
        return redirect(
            "failed",
            "Startvorlage nicht verfügbar. Es fehlt: " + ", ".join(missing) + ".",
        )

    previous_control = _take_over_conversation_before_send(
        workshop_id=wid,
        customer_phone=phone,
        ticket_id=normalized_ticket_id or None,
    )
    if previous_control is None:
        return redirect(
            "failed",
            "Die Werkstatt konnte die Unterhaltung nicht sicher übernehmen. Die Vorlage wurde nicht gesendet.",
        )

    send_result = send_whatsapp_template_message(
        phone_number_id=phone_number_id,
        customer_phone=phone,
        template_name=template_name,
        template_language=template_language,
        access_token=access_token,
        graph_api_version=settings.whatsapp_graph_api_version,
    )
    manual_mode_set = True
    if not send_result.ok and send_result.status_code is not None:
        _restore_whatsapp_conversation_control(previous_control=previous_control)

    audit_text = f"Startvorlage „{template_name}“"
    try:
        save_whatsapp_message(
            workshop_id=wid,
            phone_number_id=phone_number_id,
            customer_phone=phone,
            direction="outbound",
            message_type="template",
            text=audit_text,
            wa_message_id=send_result.wa_message_id,
            ticket_id=normalized_ticket_id or None,
            status=_meta_outbound_status(send_result),
            payload={
                "source": f"dashboard_start_template_{normalized_context}",
                "local_only": False,
                "user": (get_current_user(request) or {}).get("email"),
                "template_name": template_name,
                "template_language": template_language,
                "meta_status_code": send_result.status_code,
                "meta_response": send_result.payload,
                "meta_error": send_result.error,
            },
        )
    except Exception:
        logger.exception(
            "Could not persist WhatsApp template send for workshop=%s phone=%s",
            wid,
            phone,
        )
        if send_result.ok:
            detail = (
                "Die Startvorlage wurde an Meta übergeben, konnte intern aber nicht "
                "protokolliert werden. Bitte nicht erneut senden."
            )
            if not manual_mode_set:
                detail += " Der Assistent konnte nicht automatisch pausiert werden."
            return redirect("template_sent", detail)
        detail = _meta_send_error(send_result)
        return redirect(
            "unknown" if send_result.status_code is None else "failed",
            detail,
        )

    if not send_result.ok:
        detail = _meta_send_error(send_result)
        return redirect(
            "unknown" if send_result.status_code is None else "failed",
            detail,
        )

    detail = (
        f"Startvorlage „{template_name}“ wurde an Meta übergeben, aber noch nicht als "
        "zugestellt bestätigt. Bitte warten Sie auf die Antwort des Kunden; erst sie öffnet "
        "das 24-Stunden-Fenster für Ihren freien Text."
    )
    if not manual_mode_set:
        detail += " Der Assistent konnte nicht automatisch pausiert werden."
    return redirect("template_sent", detail)


@router.post("/dashboard/whatsapp/control")
def dashboard_whatsapp_control(
    request: Request,
    customer_phone: str = Form(...),
    mode: str = Form(...),
    workshop_id: str | None = Form(None),
    ticket_id: str | None = Form(None),
    context: str = Form("inbox"),
):
    """Switch one tenant-scoped conversation between assistant and workshop control."""
    wid = _workshop_id_for_request(request, workshop_id)
    phone = _normalize_whatsapp_recipient(customer_phone)
    normalized_mode = mode.strip().lower() if isinstance(mode, str) else ""
    normalized_ticket_id = ticket_id.strip() if isinstance(ticket_id, str) else ""
    normalized_context = context.strip().lower() if isinstance(context, str) else "inbox"

    def redirect(status: str, detail: str) -> RedirectResponse:
        return _whatsapp_action_redirect(
            workshop_id=wid,
            customer_phone=phone,
            context=normalized_context,
            status=status,
            detail=detail,
            ticket_id=normalized_ticket_id or None,
        )

    if not phone or len(phone) < 8 or len(phone) > 15:
        return redirect("failed", "Die Telefonnummer ist für WhatsApp ungültig.")
    if normalized_mode not in {"assistant", "manual"}:
        return redirect("failed", "Ungültiger Gesprächsmodus.")

    if normalized_ticket_id:
        ticket = find_ticket_by_id(normalized_ticket_id, workshop_id=wid)
        if not ticket:
            return redirect("failed", "Ticket wurde nicht gefunden.")
        ticket_phone = _ticket_whatsapp_phone(
            workshop_id=wid,
            ticket_id=normalized_ticket_id,
            ticket=ticket,
        )
        if ticket_phone != phone:
            return redirect("failed", "Die WhatsApp-Nummer passt nicht zu diesem Ticket.")
    elif not list_whatsapp_messages(
        workshop_id=wid,
        customer_phone=phone,
        limit=1,
    ):
        return redirect("failed", "Diese Unterhaltung gehört nicht zu Ihrer Werkstatt.")

    try:
        if normalized_mode == "assistant":
            set_whatsapp_conversation_control(
                workshop_id=wid,
                customer_phone=phone,
                mode="assistant",
            )
            detail = "Der Assistent übernimmt ab der nächsten Kundennachricht."
        elif normalized_ticket_id:
            set_whatsapp_conversation_control(
                workshop_id=wid,
                customer_phone=phone,
                mode="manual",
                active_ticket_id=normalized_ticket_id,
            )
            detail = "Die Werkstatt hat die Unterhaltung übernommen; der Assistent bleibt pausiert."
        else:
            set_whatsapp_conversation_control(
                workshop_id=wid,
                customer_phone=phone,
                mode="manual",
            )
            detail = "Die Werkstatt hat die Unterhaltung übernommen; der Assistent bleibt pausiert."
    except ValueError as exc:
        return redirect("failed", str(exc))
    except Exception:
        logger.exception(
            "Could not change WhatsApp control for workshop=%s phone=%s",
            wid,
            phone,
        )
        return redirect("failed", "Der Gesprächsmodus konnte nicht geändert werden.")

    return redirect("saved", detail)


@router.post("/dashboard/whatsapp/open-manual")
def dashboard_whatsapp_open_manual(
    request: Request,
    customer_phone: str = Form(...),
    workshop_id: str | None = Form(None),
    ticket_id: str | None = Form(None),
    context: str = Form("inbox"),
    reply_text: str | None = Form(None),
    message_text: str | None = Form(None),
):
    """Pause the assistant before opening the employee's WhatsApp client."""
    wid = _workshop_id_for_request(request, workshop_id)
    phone = _normalize_whatsapp_recipient(customer_phone)
    normalized_ticket_id = ticket_id.strip() if isinstance(ticket_id, str) else ""
    normalized_context = context.strip().lower() if isinstance(context, str) else "inbox"
    draft = reply_text if isinstance(reply_text, str) else message_text
    draft = str(draft or "").strip()

    def redirect(status: str, detail: str) -> RedirectResponse:
        return _whatsapp_action_redirect(
            workshop_id=wid,
            customer_phone=phone,
            context=normalized_context,
            status=status,
            detail=detail,
            ticket_id=normalized_ticket_id or None,
        )

    if not phone or len(phone) < 8 or len(phone) > 15:
        return redirect("failed", "Die Telefonnummer ist für WhatsApp ungültig.")
    if len(draft) > 4096:
        return redirect("failed", "Die WhatsApp-Nachricht darf höchstens 4096 Zeichen lang sein.")

    if normalized_ticket_id:
        ticket = find_ticket_by_id(normalized_ticket_id, workshop_id=wid)
        if not ticket:
            return redirect("failed", "Ticket wurde nicht gefunden.")
        if _ticket_whatsapp_phone(
            workshop_id=wid,
            ticket_id=normalized_ticket_id,
            ticket=ticket,
        ) != phone:
            return redirect("failed", "Die WhatsApp-Nummer passt nicht zu diesem Ticket.")
    elif not list_whatsapp_messages(
        workshop_id=wid,
        customer_phone=phone,
        limit=1,
    ):
        return redirect("failed", "Diese Unterhaltung gehört nicht zu Ihrer Werkstatt.")

    previous_control = _take_over_conversation_before_send(
        workshop_id=wid,
        customer_phone=phone,
        ticket_id=normalized_ticket_id or None,
    )
    if previous_control is None:
        return redirect(
            "failed",
            "Der Assistent konnte nicht sicher pausiert werden. WhatsApp wurde nicht geöffnet.",
        )

    query = f"?{urlencode({'text': draft})}" if draft else ""
    return RedirectResponse(url=f"https://wa.me/{phone}{query}", status_code=303)


@router.post("/dashboard/settings")
def dashboard_settings_save(
    request: Request,
    workshop_id: str | None = Form(None),
    name: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    opening_hours: str = Form(""),
    services: str = Form(""),
    pricing_info: str = Form(""),
    towing_info: str = Form(""),
    whatsapp_phone_number_id: str = Form(""),
    whatsapp_display_phone_number: str = Form(""),
):
    wid = _workshop_id_for_request(request, workshop_id)
    try:
        update_workshop(
            wid,
            name=name,
            address=address,
            phone=phone,
            email=email,
            opening_hours=opening_hours,
            services=services,
            pricing_info=pricing_info,
            towing_info=towing_info,
            whatsapp_phone_number_id=whatsapp_phone_number_id,
            whatsapp_display_phone_number=whatsapp_display_phone_number,
        )
    except ValueError as e:
        return HTMLResponse(str(e), status_code=400)
    except Exception:
        return HTMLResponse("Einstellungen konnten nicht gespeichert werden", status_code=400)

    return RedirectResponse(
        url=f"/dashboard/settings?workshop_id={wid}&saved=1",
        status_code=303,
    )


@router.get("/dashboard/intake", response_class=HTMLResponse)
def dashboard_intake(
    request: Request,
    workshop_id: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)
    return templates.TemplateResponse(
        request,
        "intake.html",
        _template_context(
            request,
            workshop_id=wid,
            workshop=workshop,
        ),
    )


@router.post("/dashboard/intake")
def dashboard_intake_save(
    request: Request,
    workshop_id: str | None = Form(None),
    fahrzeug: str = Form(...),
    baujahr: str = Form(""),
    kilometerstand: str = Form(""),
    problem: str = Form(...),
    telefon: str = Form(""),
    name: str = Form(""),
    request_type: str = Form("diagnose"),
    priority: str = Form("normal"),
    fahrbereit: str = Form(""),
    abschleppdienst: str = Form(""),
):
    wid = _workshop_id_for_request(request, workshop_id)
    fahrzeug_text = (fahrzeug or "").strip()
    problem_text = (problem or "").strip()

    if len(fahrzeug_text) < 2:
        return HTMLResponse("Fahrzeug darf nicht leer sein", status_code=400)
    if len(problem_text) < 3:
        return HTMLResponse("Anliegen darf nicht leer sein", status_code=400)

    state = IntakeState(
        mode="new",
        step="fertig",
        workshop_id=wid,
        fahrzeug=fahrzeug_text,
        baujahr=(baujahr or "").strip() or None,
        kilometerstand=(kilometerstand or "").strip() or None,
        problem=problem_text,
        telefon=(telefon or "").strip() or None,
        name=(name or "").strip() or None,
        request_type=_normalize_request_type(request_type),
        priority=_normalize_priority(priority),
        fahrbereit=_parse_ja_nein(fahrbereit),
        abschleppdienst=_parse_ja_nein(abschleppdienst),
        followup_questions=[],
        followup_answers=[],
        followup_index=0,
        source="direktannahme",
    )

    try:
        ticket_id = save_ticket(state, workshop_id=wid)
        add_ticket_note(
            ticket_id,
            "Direktannahme in der Werkstatt erfasst.",
            note_type="internal_note",
            workshop_id=wid,
        )
    except Exception:
        return HTMLResponse("Direktannahme konnte nicht gespeichert werden", status_code=400)

    return RedirectResponse(
        url=f"/dashboard/ticket/{ticket_id}?workshop_id={wid}",
        status_code=303,
    )


@router.get("/dashboard/ticket/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(
    request: Request,
    ticket_id: str,
    workshop_id: str | None = None,
    reply_status: str | None = None,
    reply_detail: str | None = None,
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)
    ticket = find_ticket_by_id(ticket_id, workshop_id=wid)
    if not ticket:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)

    t = _as_dict(ticket)
    t["ticket_view_id"] = _ticket_id(t) or ticket_id
    t["status"] = _normalize_status(t.get("status"))
    t["status_ui"] = _ui_status(t.get("status"))
    t["priority"] = _normalize_priority(t.get("priority"))
    t["request_type"] = _normalize_request_type(t.get("request_type"))
    t["source"] = _normalize_source(t.get("source"))
    t["status_label"] = _status_label(t.get("status_ui"))
    t["priority_label"] = _priority_label(t.get("priority"))
    t["request_type_label"] = _request_type_label(t.get("request_type"))
    t["source_label"] = _source_label(t.get("source"))
    t["kunde_name"] = _extract_name(t)
    t["created_at_display"] = _format_datetime_for_display(t.get("created_at"))
    t["updated_at_display"] = _format_datetime_for_display(t.get("updated_at"))
    linked_whatsapp_phone = _linked_ticket_whatsapp_phone(
        workshop_id=wid,
        ticket_id=ticket_id,
    )
    t["has_whatsapp_conversation"] = bool(linked_whatsapp_phone)
    t["whatsapp_phone"] = linked_whatsapp_phone or _normalize_whatsapp_recipient(
        t.get("telefon")
    )
    if t["whatsapp_phone"]:
        t.update(
            whatsapp_customer_service_window_for_phone(
                workshop_id=wid,
                customer_phone=t["whatsapp_phone"],
            )
        )
        conversation_control = get_whatsapp_conversation_control(
            workshop_id=wid,
            customer_phone=t["whatsapp_phone"],
        )
        t["whatsapp_mode"] = conversation_control.get("mode") or "assistant"
    else:
        t["service_window_open"] = False
        t["service_window_expires_at"] = None
        t["last_customer_message_at"] = None
        t["whatsapp_mode"] = "assistant"

    raw_notes = t.get("notes") if isinstance(t.get("notes"), list) else []
    notes = []
    for note in raw_notes:
        if not isinstance(note, dict):
            continue
        item = dict(note)
        item["created_at_display"] = _format_datetime_for_display(item.get("created_at"))
        notes.append(item)
    t["notes"] = notes
    t["internal_notes"] = [note for note in notes if _note_type(note) == "internal_note"]
    t["customer_messages"] = [note for note in notes if _note_type(note) == "customer_message"]
    t["customer_replies"] = [note for note in notes if _note_type(note) == "customer_reply"]
    t["customer_question_open"] = bool(t.get("customer_question_open"))
    t["has_customer_question"] = bool(t["customer_messages"])

    if t["has_customer_question"] and not t["customer_question_open"]:
        latest_customer_question_at = _parse_iso(
            t["customer_messages"][-1].get("created_at")
            if t["customer_messages"]
            else None
        )
        latest_customer_reply_at = _parse_iso(
            t["customer_replies"][-1].get("created_at")
            if t["customer_replies"]
            else None
        )
        if latest_customer_reply_at < latest_customer_question_at:
            t["customer_question_open"] = True

    t["raw_json"] = json.dumps(t, ensure_ascii=False, default=str, indent=2)

    return templates.TemplateResponse(
        request,
        "ticket.html",
        _template_context(
            request,
            ticket=t,
            workshop_id=wid,
            workshop=workshop,
            whatsapp_readiness=_whatsapp_readiness(request, workshop),
            reply_status=(reply_status or "").strip(),
            reply_detail=(reply_detail or "").strip(),
        ),
    )


@router.post("/dashboard/ticket/{ticket_id}/status")
def ticket_set_status(
    request: Request,
    ticket_id: str,
    status: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status, workshop_id=wid)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard/ticket/{ticket_id}?workshop_id={wid}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/status_quick")
def ticket_set_status_quick(
    request: Request,
    ticket_id: str,
    status: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status, workshop_id=wid)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard?workshop_id={wid}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/customer-message")
def ticket_send_customer_message(
    request: Request,
    ticket_id: str,
    message_text: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    text = (message_text or "").strip()

    def redirect(status: str, detail: str) -> RedirectResponse:
        query = urlencode(
            {
                "workshop_id": wid,
                "message_status": status,
                "message_detail": detail,
                "message_ticket": ticket_id,
            }
        )
        return RedirectResponse(
            url=f"/dashboard?{query}",
            status_code=303,
        )

    if not text:
        return redirect("failed", "Die Nachricht darf nicht leer sein.")
    if len(text) > 4096:
        return redirect("failed", "Die WhatsApp-Nachricht darf höchstens 4096 Zeichen lang sein.")

    ticket = find_ticket_by_id(ticket_id, workshop_id=wid)
    if not ticket:
        return redirect("failed", "Ticket wurde nicht gefunden.")

    try:
        sent, detail, _ = _send_ticket_customer_whatsapp(
            request=request,
            workshop_id=wid,
            ticket_id=ticket_id,
            ticket=ticket,
            text=text,
            source="dashboard_active_tickets",
        )
    except Exception:
        return redirect("failed", "Die Nachricht konnte technisch nicht gesendet werden.")

    return redirect(_human_send_redirect_status(sent, detail), detail)


@router.post("/dashboard/ticket/{ticket_id}/notes")
def ticket_add_note(
    request: Request,
    ticket_id: str,
    note_text: str = Form(...),
    note_type: str = Form("internal_note"),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)

    def redirect_reply(status: str = "", detail: str = "") -> RedirectResponse:
        query = urlencode(
            {
                "workshop_id": wid,
                "reply_status": status,
                "reply_detail": detail,
            }
        )
        return RedirectResponse(
            url=f"/dashboard/ticket/{ticket_id}?{query}",
            status_code=303,
        )

    try:
        text = (note_text or "").strip()
        if not text:
            return HTMLResponse("Notiz darf nicht leer sein", status_code=400)

        if note_type not in {"internal_note", "customer_reply"}:
            return HTMLResponse("Ungültiger Notiztyp", status_code=400)

        if note_type == "customer_reply":
            ticket = find_ticket_by_id(ticket_id, workshop_id=wid)
            if not ticket:
                return HTMLResponse("Ticket nicht gefunden", status_code=404)
            has_linked_whatsapp = bool(
                _linked_ticket_whatsapp_phone(workshop_id=wid, ticket_id=ticket_id)
            )
            is_whatsapp_ticket = (
                str(ticket.get("source") or "").strip().lower() == "whatsapp"
            )
            if has_linked_whatsapp or is_whatsapp_ticket:
                sent, detail, _ = _send_ticket_customer_whatsapp(
                    request=request,
                    workshop_id=wid,
                    ticket_id=ticket_id,
                    ticket=ticket,
                    text=text,
                )
                return redirect_reply(_human_send_redirect_status(sent, detail), detail)

            add_ticket_note(
                ticket_id,
                text,
                note_type="customer_reply",
                workshop_id=wid,
            )
            detail = (
                "Antwort wurde für den Web-Chat gespeichert."
                if str(ticket.get("source") or "").strip().lower() == "web_chat"
                else "Antwort wurde im Ticket gespeichert."
            )
            return redirect_reply("saved", detail)

        add_ticket_note(ticket_id, text, note_type="internal_note", workshop_id=wid)
    except KeyError:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)
    except Exception:
        return HTMLResponse("Notiz konnte nicht gespeichert werden", status_code=400)

    return RedirectResponse(url=f"/dashboard/ticket/{ticket_id}?workshop_id={wid}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/archive")
def ticket_archive(request: Request, ticket_id: str, workshop_id: str | None = Form(None)):
    wid = _workshop_id_for_request(request, workshop_id)
    try:
        archive_ticket(ticket_id, workshop_id=wid)
    except ValueError:
        return HTMLResponse("Nur erledigte Tickets können archiviert werden", status_code=400)
    except KeyError:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)
    except Exception:
        return HTMLResponse("Archivierung fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard?workshop_id={wid}", status_code=303)
