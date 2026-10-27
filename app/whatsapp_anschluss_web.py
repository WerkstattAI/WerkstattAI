"""Geschützte Dashboard-Endpunkte ohne Test- oder Scheinbestätigungsroute."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.auth import SESSION_COOKIE, get_current_user
from app import whatsapp_anschluss as anschluss
from app.whatsapp_verbindungen import VerbindungsFehler
from app.db import get_conn
from app.workshops import get_workshop_identity

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _werkstatt(request, wid):
    nutzer = get_current_user(request)
    if not nutzer or nutzer["role"] not in {"owner", "admin"}:
        raise VerbindungsFehler("Nur die Werkstattverwaltung darf WhatsApp verbinden.")
    if not isinstance(wid, str) or not wid or len(wid) > 128:
        raise VerbindungsFehler("Ungültige Werkstatt.")
    if nutzer["role"] != "admin" and wid != nutzer["workshop_id"]:
        raise VerbindungsFehler("Kein Zugriff auf diese Werkstatt.")
    werkstatt = get_workshop_identity(wid)
    if not werkstatt or werkstatt["is_demo"]:
        raise VerbindungsFehler("Für diese Werkstatt ist kein WhatsApp-Anschluss zulässig.")
    return werkstatt


@router.get("/dashboard/whatsapp/verbinden")
def seite(request: Request, workshop_id: str | None = None):
    try:
        nutzer = get_current_user(request)
        wid = workshop_id or (nutzer or {}).get("workshop_id")
        werkstatt = _werkstatt(request, wid)
    except VerbindungsFehler as fehler:
        return JSONResponse({"detail": str(fehler)}, status_code=403)
    bereit = anschluss.eingerichtet()
    with get_conn() as conn:
        zurueckgehalten = dict(conn.execute("""SELECT COUNT(*) AS anzahl, MAX(erstellt_am) AS zuletzt
            FROM whatsapp_zurueckgehalten WHERE workshop_id = ?""", (wid,)).fetchone())
    return templates.TemplateResponse(request, "whatsapp_verbinden.html", {
        "workshop": werkstatt, "workshop_id": wid, "eingerichtet": bereit,
        "zurueckgehalten": zurueckgehalten,
        "konfiguration": {"appId": anschluss.settings.whatsapp_app_id,
            "configId": anschluss.settings.whatsapp_signup_config_id,
            "version": anschluss.settings.whatsapp_signup_graph_version,
            "origin": anschluss.settings.whatsapp_signup_origin, "workshopId": wid} if bereit else None})


@router.post("/dashboard/whatsapp/verbinden/{aktion}")
async def schritt(request: Request, aktion: str):
    try:
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise VerbindungsFehler("Ungültige Anschlussanfrage.")
        daten = await request.json()
        erlaubt = {"workshop_id", "kennung"}
        if aktion == "abschluss":
            erlaubt |= {"code", "meta_ursprung", "ereignis", "waba_id", "phone_number_id"}
        if not isinstance(daten, dict) or set(daten) - erlaubt:
            raise VerbindungsFehler("Ungültige Anschlussanfrage.")
        wid = daten.get("workshop_id")
        _werkstatt(request, wid)
        cookie = request.cookies.get(SESSION_COOKIE)
        ursprung = request.headers.get("origin")
        if ursprung != anschluss.settings.whatsapp_signup_origin or not ursprung:
            raise VerbindungsFehler("Die Herkunft der Anschlussanfrage ist nicht zugelassen.")
        args = (cookie, wid, ursprung)
        if aktion == "start":
            ergebnis = await run_in_threadpool(anschluss.starte, *args)
        else:
            args += (daten.get("kennung"),)
            if aktion == "abschluss":
                ergebnis = await run_in_threadpool(anschluss.abschliessen, *args,
                    **{k: daten.get(k) for k in ("code", "meta_ursprung", "ereignis", "waba_id", "phone_number_id")})
            elif aktion == "fortsetzen":
                ergebnis = await run_in_threadpool(anschluss.fortsetzen, *args)
            elif aktion == "abbruch":
                ergebnis = await run_in_threadpool(anschluss.abbrechen, *args)
            elif aktion == "status":
                ergebnis = await run_in_threadpool(anschluss.status, *args)
            else:
                raise VerbindungsFehler("Unbekannter Anschlussschritt.")
        return JSONResponse(ergebnis)
    except VerbindungsFehler as fehler:
        return JSONResponse({"detail": str(fehler)}, status_code=409)
    except Exception:
        # Keine Eingabe, Codes, Providerantworten oder Transportausnahmen zurückgeben.
        return JSONResponse({"detail": "Der Anschlussschritt konnte nicht bestätigt werden. Status prüfen."}, status_code=400)
