from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.tickets import (
    add_ticket_note,
    archive_ticket,
    find_ticket_by_id,
    list_latest_tickets,
    update_ticket_status,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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

    if request_type in {"service", "diagnose", "notfall"}:
        return request_type

    return "diagnose"


def _ui_status(backend_status: str | None) -> str:
    return _normalize_status(backend_status)


def _backend_status(ui_status: str) -> str:
    return _normalize_status(ui_status)


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
        ]
    )
    return q in hay


def _details_payload(t: dict) -> dict:
    safe = dict(t)
    safe.pop("created_dt", None)
    safe.pop("updated_dt", None)
    safe.pop("details_json", None)
    return safe


def _prepare_tickets(limit: int) -> list[dict]:
    raw = list_latest_tickets(limit=limit)
    tickets = [_as_dict(t) for t in raw]

    for t in tickets:
        t["ticket_view_id"] = _ticket_id(t)
        t["status"] = _normalize_status(t.get("status"))
        t["status_ui"] = _ui_status(t.get("status"))
        t["priority"] = _normalize_priority(t.get("priority"))
        t["request_type"] = _normalize_request_type(t.get("request_type"))
        t["created_dt"] = _parse_iso(t.get("created_at"))
        t["updated_dt"] = _parse_iso(t.get("updated_at"))
        t["is_new"] = (t.get("created_at") == t.get("updated_at"))
        t["kunde_name"] = _extract_name(t)

        notes = t.get("notes") if isinstance(t.get("notes"), list) else []
        last_note = notes[-1] if notes else {}

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
        "all": len(tickets),
    }


def _priority_rank(priority: str) -> int:
    mapping = {
        "hoch": 0,
        "normal": 1,
        "niedrig": 2,
    }
    return mapping.get(priority, 9)


def _render_dashboard(
    request: Request,
    *,
    archive_mode: bool,
    status: str | None,
    q: str | None,
    sort: str | None,
    limit: int,
):
    tickets = _prepare_tickets(limit=limit)

    if archive_mode:
        tickets = [t for t in tickets if t.get("status_ui") == "archiviert"]
    else:
        tickets = [t for t in tickets if t.get("status_ui") != "archiviert"]

    stats = _stats_for(tickets)

    normalized_filter_status = _normalize_status(status) if status and status != "all" else "all"

    if normalized_filter_status != "all":
        tickets = [t for t in tickets if t.get("status_ui") == normalized_filter_status]

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
            "stats": stats,
            "filters": {
                "status": normalized_filter_status,
                "q": q or "",
                "sort": sort or "newest",
                "limit": limit,
            },
            "archive_mode": archive_mode,
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
    q: str | None = None,
    sort: str | None = None,
    limit: int = 250,
):
    return _render_dashboard(
        request,
        archive_mode=False,
        status=status,
        q=q,
        sort=sort,
        limit=limit,
    )


@router.get("/dashboard/archive", response_class=HTMLResponse)
def dashboard_archive(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: int = 250,
):
    return _render_dashboard(
        request,
        archive_mode=True,
        status=status,
        q=q,
        sort=sort,
        limit=limit,
    )


@router.get("/dashboard/ticket/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(request: Request, ticket_id: str):
    ticket = find_ticket_by_id(ticket_id)
    if not ticket:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)

    t = _as_dict(ticket)
    t["ticket_view_id"] = _ticket_id(t) or ticket_id
    t["status"] = _normalize_status(t.get("status"))
    t["status_ui"] = _ui_status(t.get("status"))
    t["priority"] = _normalize_priority(t.get("priority"))
    t["request_type"] = _normalize_request_type(t.get("request_type"))
    t["kunde_name"] = _extract_name(t)
    t["raw_json"] = json.dumps(t, ensure_ascii=False, default=str, indent=2)

    return templates.TemplateResponse(
        "ticket.html",
        {
            "request": request,
            "ticket": t,
        },
    )


@router.post("/dashboard/ticket/{ticket_id}/status")
def ticket_set_status(ticket_id: str, status: str = Form(...)):
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url=f"/dashboard/ticket/{ticket_id}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/status_quick")
def ticket_set_status_quick(ticket_id: str, status: str = Form(...)):
    try:
        normalized_status = _backend_status(status)
        update_ticket_status(ticket_id, normalized_status)
    except Exception:
        return HTMLResponse("Status-Update fehlgeschlagen", status_code=400)

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/notes")
def ticket_add_note(ticket_id: str, note_text: str = Form(...)):
    try:
        text = (note_text or "").strip()
        if not text:
            return HTMLResponse("Notiz darf nicht leer sein", status_code=400)

        add_ticket_note(ticket_id, text)
    except KeyError:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)
    except Exception:
        return HTMLResponse("Notiz konnte nicht gespeichert werden", status_code=400)

    return RedirectResponse(url=f"/dashboard/ticket/{ticket_id}", status_code=303)


@router.post("/dashboard/ticket/{ticket_id}/archive")
def ticket_archive(ticket_id: str):
    try:
        archive_ticket(ticket_id)
    except ValueError:
        return HTMLResponse("Nur erledigte Tickets können archiviert werden", status_code=400)
    except KeyError:
        return HTMLResponse("Ticket nicht gefunden", status_code=404)
    except Exception:
        return HTMLResponse("Archivierung fehlgeschlagen", status_code=400)

    return RedirectResponse(url="/dashboard", status_code=303)