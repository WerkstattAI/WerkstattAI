from __future__ import annotations

from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import get_current_user
from app.db import get_conn
from app.privacy_data import PrivacyError, counts, delete_data, export_data, fingerprint, make_token, preview, read_token, selection_for
from app.rate_limits import DatabaseRateLimiter, Limit
from app.config import settings
from app.security import verify_password

router = APIRouter()
templates = Jinja2Templates(directory="templates")
LABELS = {"tickets": "Tickets einschließlich Notizen", "conversation_sessions": "Gesprächsstände",
          "whatsapp_messages": "WhatsApp-Nachrichten", "whatsapp_events": "WhatsApp-Ereignisse",
          "whatsapp_conversation_controls": "WhatsApp-Zuordnungen"}


def identity(request: Request, workshop_id: str | None):
    session = get_current_user(request)
    if not session:
        raise HTTPException(401, "Bitte anmelden.")
    with closing(get_conn()) as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (session["email"],)).fetchone()
        if not user or user["workshop_id"] != session["workshop_id"] or user["role"] != session["role"]:
            raise HTTPException(403, "Dieser Zugang ist nicht mehr gültig. Bitte neu anmelden.")
        if user["role"] not in {"owner", "admin"}:
            raise HTTPException(403, "Datenverwaltung ist nur für Werkstattinhaber und Administratoren verfügbar.")
        wid = workshop_id or user["workshop_id"]
        if wid != user["workshop_id"] and user["role"] != "admin":
            raise HTTPException(403, "Diese Werkstatt gehört nicht zu Ihrem Zugang.")
        workshop = conn.execute("SELECT id, name, is_demo FROM workshops WHERE id = ?", (wid,)).fetchone()
        if not workshop or workshop["is_demo"]:
            raise HTTPException(403, "Die Datenverwaltung ist für diese Werkstatt nicht verfügbar.")
    return dict(user), dict(workshop)


def render(request, user, workshop, *, status=200, **extra):
    return templates.TemplateResponse(request, "privacy_center.html", {
        "request": request, "workshop": workshop, "workshop_id": workshop["id"], "labels": LABELS,
        "form_token": make_token(email=user["email"], workshop_id=workshop["id"], action="form"), **extra,
    }, status_code=status)


@router.get("/dashboard/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, workshop_id: str | None = None):
    user, workshop = identity(request, workshop_id)
    return render(request, user, workshop)


@router.post("/dashboard/privacy/preview", response_class=HTMLResponse)
def privacy_preview(request: Request, workshop_id: str = Form(..., max_length=128),
                    token: str = Form(..., max_length=4096), kind: str = Form(..., max_length=16),
                    value: str = Form(..., max_length=128)):
    user, workshop = identity(request, workshop_id)
    try:
        read_token(token, email=user["email"], workshop_id=workshop_id, action="form")
        selection = selection_for(kind, value)
        records = preview(workshop_id, selection)
        return render(request, user, workshop, selection=selection, quantities=counts(records),
                      matching_tickets=[{"ticket_id": row["ticket_id"], "status": row["status"], "name": row["name"] or row["kunde_name"]} for row in records["tickets"]],
                      total=sum(counts(records).values()),
                      preview_token=make_token(email=user["email"], workshop_id=workshop_id, action="preview",
                                               selection=selection, digest=fingerprint(records)))
    except PrivacyError as error:
        return render(request, user, workshop, status=400, error=str(error))


@router.post("/dashboard/privacy/export")
def privacy_export(request: Request, workshop_id: str = Form(..., max_length=128),
                   token: str = Form(..., max_length=4096), scope: str = Form("workshop", max_length=16)):
    user, workshop = identity(request, workshop_id)
    try:
        if scope not in {"workshop", "customer"}:
            raise PrivacyError("Ungültiger Exportbereich.")
        checked = read_token(token, email=user["email"], workshop_id=workshop_id,
                             action="form" if scope == "workshop" else "preview")
        content = export_data(workshop_id=workshop_id, email=user["email"],
                              selection=checked.get("selection") if scope == "customer" else None,
                              expected_digest=checked.get("digest"))
        return Response(content, media_type="application/json", headers={
            "Content-Disposition": 'attachment; filename="werkstattai-datenexport.json"', "Cache-Control": "no-store"})
    except PrivacyError as error:
        return render(request, user, workshop, status=409, error=str(error))


@router.post("/dashboard/privacy/delete", response_class=HTMLResponse)
def privacy_delete(request: Request, workshop_id: str = Form(..., max_length=128),
                   token: str = Form(..., max_length=4096), password: str = Form(..., max_length=128),
                   confirmation: str = Form(..., max_length=32), authorized: bool = Form(False)):
    user, workshop = identity(request, workshop_id)
    try:
        checked = read_token(token, email=user["email"], workshop_id=workshop_id, action="preview")
        retry = DatabaseRateLimiter(settings.auth_secret).consume([Limit("privacy-password:" + user["email"], 5, 900)])
        if retry:
            raise HTTPException(429, "Zu viele Passwortprüfungen. Bitte später erneut versuchen.", headers={"Retry-After": str(retry)})
        if not verify_password(password, user["password_hash"]):
            return render(request, user, workshop, status=403, error="Das Passwort ist nicht korrekt. Es wurde nichts gelöscht.")
        if confirmation != "LÖSCHEN" or not authorized:
            raise PrivacyError("Bitte die Berechtigung bestätigen und LÖSCHEN eingeben. Es wurde nichts gelöscht.")
        quantities = delete_data(workshop_id=workshop_id, email=user["email"], selection=checked["selection"],
                                  expected_digest=checked["digest"])
        return render(request, user, workshop, deleted=quantities)
    except PrivacyError as error:
        return render(request, user, workshop, status=409, error=str(error))


@router.get("/dashboard/privacy/avv")
def privacy_avv(request: Request, workshop_id: str | None = None):
    identity(request, workshop_id)
    content = (Path(__file__).resolve().parents[1] / "docs/recht/avv-grundlage.md").read_bytes()
    return Response(content, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="WerkstattAI-AVV-Entwurf.md"'})
