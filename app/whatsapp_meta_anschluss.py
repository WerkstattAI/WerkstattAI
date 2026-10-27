"""Serverseitiger Meta-Adapter; keine Registrierung und keine rohe Fehlerausgabe."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from app.whatsapp import bereinigte_meta_fehlercodes


class MetaAnschlussFehler(ValueError):
    def __init__(self, meldung="Meta konnte den Anschluss nicht bestätigen.", *, unklar=False):
        super().__init__(meldung)
        self.unklar = unklar


def meta_id(wert):
    return isinstance(wert, str) and re.fullmatch(r"[0-9]{1,32}", wert) is not None


@dataclass(frozen=True)
class GepruefterAnschluss:
    waba_id: str
    phone_number_id: str
    anzeigenummer: str
    token: str = field(repr=False)


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MetaAnschluss:
    def __init__(self, konfiguration):
        self.konfiguration = konfiguration

    def _http(self, methode, pfad, *, token=None, parameter=None):
        adresse = f"https://graph.facebook.com/{self.konfiguration.whatsapp_signup_graph_version}/{pfad}"
        if parameter:
            adresse += "?" + urllib.parse.urlencode(parameter)
        kopf = {"Accept": "application/json"}
        if token:
            kopf["Authorization"] = "Bearer " + token
        anfrage = urllib.request.Request(adresse, headers=kopf, method=methode,
                                         data=b"" if methode == "POST" else None)
        try:
            with urllib.request.build_opener(_KeineWeiterleitung()).open(anfrage, timeout=15) as antwort:
                inhalt = antwort.read(1048577)
            if len(inhalt) > 1048576:
                raise ValueError()
            daten = json.loads(inhalt)
            if not isinstance(daten, dict) or "error" in daten:
                raise ValueError()
            return daten
        except urllib.error.HTTPError as fehler:
            codes = {}
            try:
                with fehler:
                    inhalt = fehler.read(65537)
                if len(inhalt) <= 65536:
                    codes = bereinigte_meta_fehlercodes(json.loads(inhalt))
            except Exception:
                pass
            diagnose = ", ".join(f"{feld} {wert}" for feld, wert in codes.items())
            raise MetaAnschlussFehler(f"Meta HTTP {fehler.code}" + (f" ({diagnose})" if diagnose else ""),
                                      unklar=fehler.code >= 500) from None
        except Exception:
            raise MetaAnschlussFehler("Das Ergebnis des Meta-Schritts ist unklar.", unklar=True) from None

    def tausche_code(self, code):
        daten = self._http("GET", "oauth/access_token", parameter={
            "client_id": self.konfiguration.whatsapp_app_id,
            "client_secret": self.konfiguration.whatsapp_app_secret, "code": code})
        token = daten.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise MetaAnschlussFehler("Kein gültiger Kundenzugang zurückgegeben.", unklar=True)
        return token

    def _liste(self, pfad, token, felder=None):
        parameter = {"limit": 100}
        if felder:
            parameter["fields"] = felder
        ergebnis = []
        for _ in range(10):
            daten = self._http("GET", pfad, token=token, parameter=parameter)
            if not isinstance(daten.get("data"), list) or any(not isinstance(e, dict) for e in daten["data"]):
                raise MetaAnschlussFehler("Unvollständige Asset-Antwort von Meta.")
            ergebnis.extend(daten["data"])
            paging = daten.get("paging") or {}
            if not isinstance(paging, dict):
                raise MetaAnschlussFehler()
            if not paging.get("next"):
                return ergebnis
            # Niemals eine fremde Paging-URL mit dem Zugang aufrufen.
            cursors = paging.get("cursors")
            cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
                raise MetaAnschlussFehler("Die Asset-Liste konnte nicht vollständig geprüft werden.")
            parameter["after"] = cursor
        raise MetaAnschlussFehler("Die Asset-Liste überschreitet die unterstützte Größe.")

    def pruefe(self, token, waba_id, phone_number_id=None):
        if not meta_id(waba_id) or (phone_number_id is not None and not meta_id(phone_number_id)):
            raise MetaAnschlussFehler("Ungültige Asset-Auswahl.")
        app_token = f"{self.konfiguration.whatsapp_app_id}|{self.konfiguration.whatsapp_app_secret}"
        daten = self._http("GET", "debug_token", token=app_token, parameter={"input_token": token}).get("data")
        rechte = {"whatsapp_business_management", "whatsapp_business_messaging"}
        if (not isinstance(daten, dict) or daten.get("is_valid") is not True
                or daten.get("app_id") != self.konfiguration.whatsapp_app_id
                or not isinstance(daten.get("scopes"), list) or any(not isinstance(r, str) for r in daten["scopes"])
                or not rechte.issubset(daten["scopes"])):
            raise MetaAnschlussFehler("Kundenzugang oder App-Berechtigungen sind nicht gültig.")
        for feld in ("expires_at", "data_access_expires_at"):
            wert = daten.get(feld)
            if type(wert) is not int or (wert != 0 and wert <= int(time.time())):
                raise MetaAnschlussFehler("Der Kundenzugang ist abgelaufen oder nicht prüfbar.")
        granular = daten.get("granular_scopes")
        if not isinstance(granular, list):
            raise MetaAnschlussFehler("Das ausgewählte Messaging-Konto wurde nicht autorisiert.")
        for recht in rechte:
            eintraege = [r for r in granular if isinstance(r, dict) and r.get("scope") == recht]
            if not eintraege:
                raise MetaAnschlussFehler("Eine erforderliche Kontoberechtigung wurde nicht nachgewiesen.")
            for eintrag in eintraege:
                # Nur ein vorhandener Scope ohne Ziele gilt laut Meta für alle Assets.
                if "target_ids" not in eintrag:
                    continue
                ziele = eintrag["target_ids"]
                # Meta dokumentiert auch ganzzahlige IDs; Bool und andere Typen gelten nicht als IDs.
                if (not isinstance(ziele, list) or not ziele
                        or any(not (meta_id(z) or (type(z) is int and z > 0 and len(str(z)) <= 32)) for z in ziele)
                        or waba_id not in [str(z) for z in ziele]):
                    raise MetaAnschlussFehler("Das ausgewählte Messaging-Konto wurde nicht autorisiert.")
        nummern = self._liste(f"{waba_id}/phone_numbers", token, "id")
        ids = {n.get("id") for n in nummern if meta_id(n.get("id"))}
        if phone_number_id is None:
            if len(ids) != 1:
                raise MetaAnschlussFehler("Meta hat keine eindeutige Telefonnummer ausgewählt. Anschluss erneut starten.")
            phone_number_id = next(iter(ids))
        if phone_number_id not in ids:
            raise MetaAnschlussFehler("Die Telefonnummer gehört nicht zum autorisierten Messaging-Konto.")
        nummer = self._http("GET", phone_number_id, token=token,
            parameter={"fields": "id,display_phone_number,is_on_biz_app,platform_type"})
        anzeige = nummer.get("display_phone_number")
        if (nummer.get("id") != phone_number_id or nummer.get("is_on_biz_app") is not True
                or nummer.get("platform_type") != "CLOUD_API" or not isinstance(anzeige, str)
                or re.fullmatch(r"[+0-9 ()-]{3,64}", anzeige) is None):
            raise MetaAnschlussFehler("Meta bestätigt keine bestehende Business-App-Nummer mit Cloud-API-Zugang.")
        return GepruefterAnschluss(waba_id, phone_number_id, anzeige, token)

    def ist_abonniert(self, anschluss):
        apps = self._liste(f"{anschluss.waba_id}/subscribed_apps", anschluss.token)
        return any(isinstance(e.get("whatsapp_business_api_data"), dict)
                   and e["whatsapp_business_api_data"].get("id") == self.konfiguration.whatsapp_app_id for e in apps)

    def abonnieren(self, anschluss):
        daten = self._http("POST", f"{anschluss.waba_id}/subscribed_apps", token=anschluss.token)
        if daten.get("success") is not True:
            raise MetaAnschlussFehler("Das Kontoabonnement ist nicht bestätigt.", unklar=True)
