from __future__ import annotations

import json
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
from app.db import default_workshop_id
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
    send_whatsapp_text_message,
)
from app.workshops import get_workshop, update_workshop

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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
        "sent": "Gesendet",
        "delivered": "Zugestellt",
        "read": "Gelesen",
        "failed": "Fehler",
    }
    return labels.get(str(value or "").strip().lower(), str(value or "-"))


def _message_status_class(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in {"sent", "delivered", "read", "received"}:
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

    error = payload.get("meta_error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    response = payload.get("meta_response")
    if isinstance(response, dict):
        meta_error = response.get("error")
        if isinstance(meta_error, dict):
            message = str(meta_error.get("message") or "").strip()
            code = str(meta_error.get("code") or "").strip()
            if message and code:
                return f"{message} ({code})"
            return message

    return ""


def _decorate_whatsapp_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = []
    for message in messages:
        item = dict(message)
        item["status_label"] = _message_status_label(item.get("status"))
        item["status_class"] = _message_status_class(item.get("status"))
        item["message_error"] = _message_error(item.get("payload_json"))
        decorated.append(item)
    return decorated


def _whatsapp_readiness(request: Request, workshop: dict[str, Any]) -> dict[str, Any]:
    access_token_ready = bool(str(settings.whatsapp_access_token or "").strip())
    verify_token_ready = bool(str(settings.whatsapp_verify_token or "").strip())
    app_secret_ready = bool(str(settings.whatsapp_app_secret or "").strip())
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    display_phone_number = str(workshop.get("whatsapp_display_phone_number") or "").strip()
    configured_webhook_url = str(settings.whatsapp_webhook_public_url or "").strip()
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
    ]

    return {
        "is_ready": all(check["configured"] for check in checks),
        "can_send": access_token_ready and bool(phone_number_id),
        "reply_mode": "meta" if access_token_ready and phone_number_id else "local",
        "webhook_url": webhook_url,
        "webhook_url_source": "configured" if configured_webhook_url else "request",
        "phone_number_id": phone_number_id,
        "display_phone_number": display_phone_number,
        "checks": checks,
    }


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
    raw = list_latest_tickets(limit=limit, workshop_id=_normalize_workshop_id(workshop_id))
    tickets = [_as_dict(t) for t in raw]

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
        t["is_new"] = (t.get("created_at") == t.get("updated_at"))
        t["kunde_name"] = _extract_name(t)

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
):
    wid = _normalize_workshop_id(workshop_id)
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
        "dashboard.html",
        _template_context(
            request,
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
        ),
    )


# -------------------------
# Routes
# -------------------------
@router.get("/datenschutz", response_class=HTMLResponse)
def datenschutz_page(request: Request):
    return templates.TemplateResponse(
        "datenschutz.html",
        {
            "request": request,
        },
    )


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request):
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = None,
    error: str | None = None,
):
    return templates.TemplateResponse(
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
    set_session_cookie(response, user)
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

    return templates.TemplateResponse(
        "billing.html",
        _template_context(
            request,
            workshop_id=wid,
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
):
    wid = _workshop_id_for_request(request, workshop_id)
    workshop = get_workshop(wid)
    readiness = _whatsapp_readiness(request, workshop)
    conversations = list_whatsapp_conversations(workshop_id=wid)
    selected_phone = (phone or "").strip()

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
        ),
    )


@router.post("/dashboard/whatsapp/test")
def dashboard_whatsapp_test(
    request: Request,
    test_phone: str = Form(...),
    test_text: str = Form("WerkstattAI Testnachricht. WhatsApp Verbindung funktioniert."),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    phone = (test_phone or "").strip()
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

    workshop = get_workshop(wid)
    phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
    access_token = str(settings.whatsapp_access_token or "").strip()
    if not access_token:
        return redirect("failed", "WHATSAPP_ACCESS_TOKEN fehlt.")
    if not phone_number_id:
        return redirect("failed", "Phone Number ID fehlt in den Werkstatt-Einstellungen.")

    send_result = send_whatsapp_text_message(
        phone_number_id=phone_number_id,
        customer_phone=phone,
        text=text,
        access_token=access_token,
        graph_api_version=settings.whatsapp_graph_api_version,
    )

    status = "sent" if send_result.ok else "failed"
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
        return redirect("sent", "Testnachricht wurde ueber Meta API gesendet.")

    return redirect("failed", send_result.error or "Meta API hat die Testnachricht abgelehnt.")


@router.post("/dashboard/whatsapp/reply")
def dashboard_whatsapp_reply(
    request: Request,
    customer_phone: str = Form(...),
    reply_text: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    phone = (customer_phone or "").strip()
    text = (reply_text or "").strip()

    if not phone:
        return HTMLResponse("WhatsApp Kontakt fehlt", status_code=400)
    if not text:
        return HTMLResponse("Antwort darf nicht leer sein", status_code=400)

    try:
        workshop = get_workshop(wid)
        phone_number_id = str(workshop.get("whatsapp_phone_number_id") or "").strip()
        access_token = str(settings.whatsapp_access_token or "").strip()
        send_result = None
        status = "sent_local"
        wa_message_id = None
        payload: dict[str, Any] = {
            "source": "dashboard",
            "local_only": True,
            "user": (get_current_user(request) or {}).get("email"),
        }

        if access_token and phone_number_id:
            send_result = send_whatsapp_text_message(
                phone_number_id=phone_number_id,
                customer_phone=phone,
                text=text,
                access_token=access_token,
                graph_api_version=settings.whatsapp_graph_api_version,
            )
            status = "sent" if send_result.ok else "failed"
            wa_message_id = send_result.wa_message_id
            payload = {
                "source": "dashboard",
                "local_only": False,
                "user": (get_current_user(request) or {}).get("email"),
                "meta_status_code": send_result.status_code,
                "meta_response": send_result.payload,
                "meta_error": send_result.error,
            }

        save_whatsapp_message(
            workshop_id=wid,
            phone_number_id=phone_number_id or None,
            customer_phone=phone,
            direction="outbound",
            message_type="text",
            text=text,
            wa_message_id=wa_message_id,
            status=status,
            payload=payload,
        )
    except Exception:
        return HTMLResponse("Antwort konnte nicht gespeichert werden", status_code=400)

    return RedirectResponse(
        url=f"/dashboard/whatsapp?workshop_id={wid}&phone={phone}",
        status_code=303,
    )


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
    return templates.TemplateResponse(
        "intake.html",
        _template_context(
            request,
            workshop_id=wid,
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
def ticket_detail(request: Request, ticket_id: str, workshop_id: str | None = None):
    wid = _workshop_id_for_request(request, workshop_id)
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

    notes = t.get("notes") if isinstance(t.get("notes"), list) else []
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
        "ticket.html",
        _template_context(
            request,
            ticket=t,
            workshop_id=wid,
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


@router.post("/dashboard/ticket/{ticket_id}/notes")
def ticket_add_note(
    request: Request,
    ticket_id: str,
    note_text: str = Form(...),
    note_type: str = Form("internal_note"),
    workshop_id: str | None = Form(None),
):
    wid = _workshop_id_for_request(request, workshop_id)
    try:
        text = (note_text or "").strip()
        if not text:
            return HTMLResponse("Notiz darf nicht leer sein", status_code=400)

        if note_type not in {"internal_note", "customer_reply"}:
            return HTMLResponse("Ungültiger Notiztyp", status_code=400)

        add_ticket_note(ticket_id, text, note_type=note_type, workshop_id=wid)
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
