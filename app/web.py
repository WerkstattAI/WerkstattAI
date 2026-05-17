from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import default_workshop_id
from app.models import IntakeState
from app.tickets import (
    add_ticket_note,
    archive_ticket,
    find_ticket_by_id,
    list_latest_tickets,
    save_ticket,
    update_ticket_status,
)
from app.workshops import get_workshop, update_workshop

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _normalize_workshop_id(value: str | None = None) -> str:
    return (value or default_workshop_id()).strip() or default_workshop_id()


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
        {
            "request": request,
            "tickets": tickets,
            "attention_tickets": attention_tickets,
            "stats": stats,
            "filters": {
                "status": normalized_filter_status,
                "source": normalized_filter_source,
                "question_state": normalized_filter_question_state,
                "q": q or "",
                "sort": sort or "newest",
                "limit": limit,
                "workshop_id": wid,
            },
            "archive_mode": archive_mode,
            "workshop_id": wid,
        },
    )


# -------------------------
# Routes
# -------------------------
@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request):
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
        },
    )


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
    return _render_dashboard(
        request,
        archive_mode=False,
        status=status,
        source=source,
        question_state=question_state,
        q=q,
        sort=sort,
        limit=limit,
        workshop_id=workshop_id,
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
    return _render_dashboard(
        request,
        archive_mode=True,
        status=status,
        source=source,
        question_state=question_state,
        q=q,
        sort=sort,
        limit=limit,
        workshop_id=workshop_id,
    )


@router.get("/dashboard/settings", response_class=HTMLResponse)
def dashboard_settings(
    request: Request,
    workshop_id: str | None = None,
    saved: str | None = None,
):
    wid = _normalize_workshop_id(workshop_id)
    workshop = get_workshop(wid)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "workshop": workshop,
            "workshop_id": wid,
            "saved": saved == "1",
        },
    )


@router.post("/dashboard/settings")
def dashboard_settings_save(
    workshop_id: str | None = Form(None),
    name: str = Form(...),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    opening_hours: str = Form(""),
    services: str = Form(""),
    pricing_info: str = Form(""),
    towing_info: str = Form(""),
):
    wid = _normalize_workshop_id(workshop_id)
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
    wid = _normalize_workshop_id(workshop_id)
    return templates.TemplateResponse(
        "intake.html",
        {
            "request": request,
            "workshop_id": wid,
        },
    )


@router.post("/dashboard/intake")
def dashboard_intake_save(
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
    wid = _normalize_workshop_id(workshop_id)
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
    wid = _normalize_workshop_id(workshop_id)
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
        {
            "request": request,
            "ticket": t,
            "workshop_id": wid,
        },
    )


@router.post("/dashboard/ticket/{ticket_id}/status")
def ticket_set_status(
    ticket_id: str,
    status: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _normalize_workshop_id(workshop_id)
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status, workshop_id=wid)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard/ticket/{ticket_id}?workshop_id={wid}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/status_quick")
def ticket_set_status_quick(
    ticket_id: str,
    status: str = Form(...),
    workshop_id: str | None = Form(None),
):
    wid = _normalize_workshop_id(workshop_id)
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status, workshop_id=wid)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/notes")
def ticket_add_note(
    ticket_id: str,
    note_text: str = Form(...),
    note_type: str = Form("internal_note"),
    workshop_id: str | None = Form(None),
):
    wid = _normalize_workshop_id(workshop_id)
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
def ticket_archive(ticket_id: str, workshop_id: str | None = Form(None)):
    wid = _normalize_workshop_id(workshop_id)
    try:
        archive_ticket(ticket_id, workshop_id=wid)
    except ValueError:
        return HTMLResponse("Nur erledigte Tickets können archiviert werden", status_code=400)
    except KeyError:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)
    except Exception:
        return HTMLResponse("Archivierung fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard?workshop_id={wid}", status_code=303)
