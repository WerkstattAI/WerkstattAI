"""Geschützter Bildabruf über Meta; keine öffentlichen Medienlinks oder Dateikopien."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

MAX_BILD_BYTES = 5 * 1024 * 1024
BILD_TYPEN = {"image/jpeg": "jpg", "image/png": "png"}


class MedienFehler(ValueError):
    def __init__(self, meldung: str, status: int = 502):
        super().__init__(meldung)
        self.status = status


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def medienangaben(nachricht: dict) -> dict | None:
    if nachricht.get("message_type") != "image":
        return None
    try:
        daten = json.loads(nachricht.get("payload_json") or "{}")
        if nachricht.get("direction") != "inbound" and daten.get("source") != "whatsapp_business_app":
            return None
        bild = daten.get("image") if isinstance(daten, dict) else None
        kennung = str(bild.get("id") or "") if isinstance(bild, dict) else ""
        if not re.fullmatch(r"[0-9]{1,128}", kennung):
            return None
        return {"id": kennung, "beschriftung": str(bild.get("caption") or "")[:4096]}
    except (ValueError, TypeError):
        return None


def _lies_begrenzt(antwort, grenze: int) -> bytes:
    laenge = antwort.headers.get("Content-Length", "")
    if laenge and (not laenge.isdigit() or int(laenge) > grenze):
        raise MedienFehler("Das Bild überschreitet die zulässige Dateigröße.", 413)
    inhalt = antwort.read(grenze + 1)
    if len(inhalt) > grenze:
        raise MedienFehler("Das Bild überschreitet die zulässige Dateigröße.", 413)
    return inhalt


def lade_bild(*, medien_id: str, nummer_id: str, zugang: str, version: str) -> tuple[bytes, str]:
    if not zugang:
        raise MedienFehler("Der Bildabruf ist noch nicht eingerichtet.", 503)
    if not nummer_id or not re.fullmatch(r"[0-9]{1,128}", medien_id) or not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise MedienFehler("Der Bildverweis ist ungültig.", 404)
    abruf = urllib.request.build_opener(_KeineWeiterleitung())
    kopf = {"Authorization": "Bearer " + zugang, "User-Agent": "WerkstattAI/1.0"}
    adresse = f"https://graph.facebook.com/{version}/{medien_id}?" + urlencode({"phone_number_id": nummer_id})
    try:
        with abruf.open(urllib.request.Request(adresse, headers=kopf), timeout=15) as antwort:
            daten = json.loads(_lies_begrenzt(antwort, 64 * 1024))
        if not isinstance(daten, dict):
            raise MedienFehler("Meta hat keinen gültigen Bildverweis geliefert.")
        typ = str(daten.get("mime_type") or "").lower()
        if typ not in BILD_TYPEN:
            raise MedienFehler("Dieses Bildformat wird nicht unterstützt.", 415)
        groesse = daten.get("file_size")
        if groesse is not None and (not isinstance(groesse, int) or groesse < 1 or groesse > MAX_BILD_BYTES):
            raise MedienFehler("Das Bild überschreitet die zulässige Dateigröße.", 413)
        ziel = str(daten.get("url") or "")
        teile = urlsplit(ziel)
        if (teile.scheme != "https" or teile.username or teile.password or teile.port not in (None, 443)
                or teile.hostname not in {"lookaside.fbsbx.com", "lookaside.facebook.com", "mmg.whatsapp.net"}):
            raise MedienFehler("Meta hat eine unerwartete Medienadresse geliefert.")
        with abruf.open(urllib.request.Request(ziel, headers=kopf), timeout=15) as antwort:
            if antwort.headers.get_content_type() != typ:
                raise MedienFehler("Das gelieferte Dateiformat stimmt nicht mit dem Bild überein.", 415)
            inhalt = _lies_begrenzt(antwort, MAX_BILD_BYTES)
        if not ((typ == "image/jpeg" and inhalt.startswith(b"\xff\xd8\xff"))
                or (typ == "image/png" and inhalt.startswith(b"\x89PNG\r\n\x1a\n"))):
            raise MedienFehler("Die gelieferte Datei ist kein unterstütztes Bild.", 415)
        return inhalt, typ
    except MedienFehler:
        raise
    except urllib.error.HTTPError as fehler:
        status = 404 if fehler.code in (400, 404, 410) else 502
        raise MedienFehler("Das Bild ist bei Meta nicht verfügbar. Bitte den Kunden bei Bedarf um erneutes Senden bitten.", status) from None
    except (OSError, ValueError, TypeError):
        raise MedienFehler("Das Bild konnte gerade nicht geladen werden. Bitte später erneut versuchen.") from None
