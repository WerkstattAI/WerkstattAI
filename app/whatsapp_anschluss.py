"""Einmaliger, sitzungsgebundener Anschluss mit dauerhaften Prüfschritten."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from app.auth import decode_session_token
from app.config import settings
from app.db import atomic_database, get_conn, is_postgres, lock_communication_scope
from app.whatsapp_meta_anschluss import MetaAnschluss, MetaAnschlussFehler, meta_id
from app.whatsapp_verbindungen import VerbindungsFehler, _chiffre, speichere_verbindungsentwurf


HERKUNFT = "embedded_signup_coexistence"
META_URSPRUENGE = {"https://www.facebook.com", "https://web.facebook.com"}
MELDUNGEN = {
    "offen": "Bereit für die Verbindung in der WhatsApp Business-App.",
    "austausch": "Code wird einmalig geprüft. Bei Unterbrechung ist ein neuer Anschlussversuch erforderlich.",
    "abonnement": "Kundenzugang geprüft; Kontoabonnement wird bestätigt.",
    "teilfehler": "Kontoabonnement noch nicht bestätigt. Prüfung ohne erneuten Codeaustausch fortsetzen.",
    "abgeschlossen": "Zugang autorisiert. Bitte Kontakte und Verlauf synchronisieren; die betriebliche Automatik bleibt gesperrt.",
    "abgebrochen": "Anschluss abgebrochen. Ein externer Meta-Schritt kann bereits erfolgt sein.",
    "abgelaufen": "Anschlussversuch abgelaufen. Bitte neu starten.",
    "fehlgeschlagen": "Anschluss nicht bestätigt. Bitte neu starten.",
    "unklar": "Codeaustausch oder Prüfung unklar. Code nicht wiederverwenden; Anschluss neu starten.",
    "ueberholt": "Die Verbindung wurde nach diesem Versuch geändert oder widerrufen. Der frühere Abschluss ist nicht mehr aktuell.",
}


def migriere_anschluss(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_anschlussversuche (
        kennung_hash TEXT PRIMARY KEY, workshop_id TEXT NOT NULL REFERENCES workshops(id) ON DELETE CASCADE,
        nutzer TEXT NOT NULL, sitzung_hash TEXT NOT NULL, ursprung TEXT NOT NULL,
        ablauf INTEGER NOT NULL, version INTEGER NOT NULL, zustand TEXT NOT NULL,
        diagnose TEXT, code_hash TEXT UNIQUE, erstellt_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        aktualisiert_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_zurueckgehalten (
        workshop_id TEXT NOT NULL REFERENCES workshops(id) ON DELETE CASCADE,
        wa_message_id TEXT NOT NULL, phone_number_id TEXT NOT NULL, grund TEXT NOT NULL,
        erstellt_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(workshop_id, wa_message_id))""")


def eingerichtet():
    ursprung = settings.whatsapp_signup_origin or ""
    try:
        url = urlsplit(ursprung)
        _chiffre()
    except (ValueError, VerbindungsFehler):
        return False
    return bool(meta_id(settings.whatsapp_app_id) and meta_id(settings.whatsapp_signup_config_id)
        and settings.whatsapp_app_secret and settings.whatsapp_zugangsschluessel
        and re.fullmatch(r"v[0-9]{1,2}\.0", settings.whatsapp_signup_graph_version)
        and url.scheme == "https" and url.hostname and not url.username and not url.password
        and not url.path and not url.query and not url.fragment and "*" not in ursprung)


def _hash(wert):
    return hashlib.sha256(wert.encode()).hexdigest()


def _berechtigt(conn, cookie, wid, ursprung):
    if not eingerichtet() or ursprung != settings.whatsapp_signup_origin:
        raise VerbindungsFehler("Der WhatsApp-Anschluss ist für diesen Ursprung nicht eingerichtet.")
    nutzer = decode_session_token(cookie)
    if not nutzer:
        raise VerbindungsFehler("Bitte erneut anmelden.")
    # Rollen-/Passwortänderungen müssen vor oder nach dem lokalen Abschluss liegen.
    conn.execute("SELECT email FROM users WHERE email = ?" + (" FOR UPDATE" if is_postgres() else ""), (nutzer["email"],)).fetchone()
    nutzer = decode_session_token(cookie)
    if not nutzer or nutzer["role"] not in {"owner", "admin"} or (nutzer["role"] != "admin" and nutzer["workshop_id"] != wid):
        raise VerbindungsFehler("Nur die berechtigte Werkstattverwaltung darf WhatsApp verbinden.")
    lock_communication_scope(conn, wid)
    werkstatt = conn.execute("SELECT is_demo FROM workshops WHERE id = ?" + (" FOR UPDATE" if is_postgres() else ""), (wid,)).fetchone()
    if not werkstatt or werkstatt["is_demo"]:
        raise VerbindungsFehler("Für diese Werkstatt ist kein WhatsApp-Anschluss zulässig.")
    return nutzer


def _version(conn, wid):
    zeile = conn.execute("SELECT version FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone()
    return zeile["version"] if zeile else 0


def _versuch(conn, cookie, wid, ursprung, kennung):
    nutzer = _berechtigt(conn, cookie, wid, ursprung)
    if not isinstance(kennung, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", kennung):
        raise VerbindungsFehler("Ungültiger Anschlussversuch.")
    zeile = conn.execute("SELECT * FROM whatsapp_anschlussversuche WHERE kennung_hash = ?"
                         + (" FOR UPDATE" if is_postgres() else ""), (_hash(kennung),)).fetchone()
    if (not zeile or zeile["workshop_id"] != wid or zeile["nutzer"] != nutzer["email"]
            or zeile["sitzung_hash"] != _hash(cookie) or zeile["ursprung"] != ursprung):
        raise VerbindungsFehler("Dieser Anschlussversuch gehört nicht zur aktuellen Sitzung.")
    return dict(zeile)


def _aktiv(versuch, zustaende):
    if versuch["ablauf"] <= int(time.time()):
        raise VerbindungsFehler("Der Anschlussversuch ist abgelaufen. Bitte neu starten.")
    if versuch["zustand"] not in zustaende:
        raise VerbindungsFehler("Dieser Anschlussschritt läuft bereits oder wurde beendet. Status prüfen.")


def _zustand(conn, versuch, zustand, diagnose=None, version=None):
    conn.execute("""UPDATE whatsapp_anschlussversuche SET zustand = ?, diagnose = ?, version = ?,
        aktualisiert_am = CURRENT_TIMESTAMP WHERE kennung_hash = ?""",
        (zustand, diagnose, versuch["version"] if version is None else version, versuch["kennung_hash"]))


def starte(cookie, wid, ursprung):
    kennung = secrets.token_urlsafe(32)
    with atomic_database() as conn:
        nutzer = _berechtigt(conn, cookie, wid, ursprung)
        # Ein neuer Versuch ersetzt ältere Versuche, auch wenn deren HTTP noch läuft.
        conn.execute("""UPDATE whatsapp_anschlussversuche SET zustand = 'abgebrochen'
            WHERE workshop_id = ? AND zustand IN ('offen', 'austausch', 'abonnement', 'teilfehler')""", (wid,))
        conn.execute("""INSERT INTO whatsapp_anschlussversuche
            (kennung_hash, workshop_id, nutzer, sitzung_hash, ursprung, ablauf, version, zustand)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'offen')""",
            (_hash(kennung), wid, nutzer["email"], _hash(cookie), ursprung, int(time.time()) + 600, _version(conn, wid)))
    return {"kennung": kennung, "zustand": "offen", "meldung": MELDUNGEN["offen"]}


def _status_ergebnis(conn, wid, versuch):
    """Status innerhalb der bereits berechtigten und gesperrten Transaktion ermitteln."""
    zustand = versuch["zustand"]
    if versuch["ablauf"] <= int(time.time()) and zustand not in {"abgeschlossen", "abgebrochen", "fehlgeschlagen"}:
        zustand = "abgelaufen"
        _zustand(conn, versuch, zustand)
    aktuell = _version(conn, wid) == versuch["version"]
    if zustand == "abgeschlossen" and not aktuell:
        zustand = "ueberholt"
    return {"zustand": zustand, "meldung": MELDUNGEN[zustand], "diagnose": versuch["diagnose"],
            "fortsetzbar": zustand == "teilfehler" and aktuell, "coexistence_bereit": False}


def status(cookie, wid, ursprung, kennung):
    with atomic_database() as conn:
        return _status_ergebnis(conn, wid, _versuch(conn, cookie, wid, ursprung, kennung))


def abbrechen(cookie, wid, ursprung, kennung):
    with atomic_database() as conn:
        versuch = _versuch(conn, cookie, wid, ursprung, kennung)
        if versuch["zustand"] != "abgeschlossen":
            _zustand(conn, versuch, "abgebrochen")
            versuch.update(zustand="abgebrochen", diagnose=None)
        # Ein bereits bestätigter Zugang bleibt erhalten; auch dessen Version beachten.
        return _status_ergebnis(conn, wid, versuch)


def sitzung_beenden(cookie):
    if not cookie:
        return
    with atomic_database() as conn:
        conn.execute("""UPDATE whatsapp_anschlussversuche SET zustand = 'abgebrochen'
            WHERE sitzung_hash = ? AND zustand IN ('offen', 'austausch', 'abonnement', 'teilfehler')""", (_hash(cookie),))


def _fehler_merke(kennung, zustand, diagnose):
    # Kein zurückkommender HTTP-Fehler darf einen Abbruch oder neueren Erfolg überschreiben.
    with atomic_database() as conn:
        conn.execute("""UPDATE whatsapp_anschlussversuche SET zustand = ?, diagnose = ?, aktualisiert_am = CURRENT_TIMESTAMP
            WHERE kennung_hash = ? AND zustand IN ('austausch', 'abonnement')""", (zustand, diagnose, _hash(kennung)))


def _entwurf(conn, wid, version):
    zeile = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone()
    if not zeile or zeile["version"] != version or zeile["herkunft"] != HERKUNFT or zeile["autorisierung"] != "unbestaetigt":
        raise VerbindungsFehler("Die Verbindung wurde zwischenzeitlich geändert oder widerrufen.")
    try:
        daten = json.loads(_chiffre().decrypt(zeile["zugang_verschluesselt"].encode()))
        if daten[:4] != [wid, zeile["waba_id"], zeile["phone_number_id"], version] or len(daten) != 5 or not isinstance(daten[4], str):
            raise ValueError()
        return zeile["waba_id"], zeile["phone_number_id"], daten[4]
    except Exception:
        raise VerbindungsFehler("Der gespeicherte Kundenzugang ist nicht verfügbar.") from None


def abschliessen(cookie, wid, ursprung, kennung, *, code, meta_ursprung, ereignis, waba_id, phone_number_id=None):
    if (meta_ursprung not in META_URSPRUENGE or ereignis != "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
            or not meta_id(waba_id) or (phone_number_id is not None and not meta_id(phone_number_id))
            or not isinstance(code, str) or not 1 <= len(code) <= 4096):
        raise VerbindungsFehler("Kein gültiger Abschluss des Business-App-Anschlusses.")
    with atomic_database() as conn:
        versuch = _versuch(conn, cookie, wid, ursprung, kennung)
        _aktiv(versuch, {"offen"})
        if _version(conn, wid) != versuch["version"]:
            raise VerbindungsFehler("Die Verbindung wurde zwischenzeitlich geändert.")
        try:
            conn.execute("UPDATE whatsapp_anschlussversuche SET code_hash = ? WHERE kennung_hash = ?",
                         (_hash(code), versuch["kennung_hash"]))
        except Exception:
            raise VerbindungsFehler("Dieser Code wurde bereits verwendet. Bitte einen neuen Meta-Anschluss starten.") from None
        _zustand(conn, versuch, "austausch")
    adapter = MetaAnschluss(settings)
    try:
        token = adapter.tausche_code(code)
        geprueft = adapter.pruefe(token, waba_id, phone_number_id)
        with atomic_database() as conn:
            versuch = _versuch(conn, cookie, wid, ursprung, kennung)
            _aktiv(versuch, {"austausch"})
            version = speichere_verbindungsentwurf(workshop_id=wid, waba_id=geprueft.waba_id,
                phone_number_id=geprueft.phone_number_id, anzeigenummer=geprueft.anzeigenummer,
                token=geprueft.token, erwartete_version=versuch["version"])
            conn.execute("UPDATE whatsapp_verbindungen SET herkunft = ? WHERE workshop_id = ?", (HERKUNFT, wid))
            _zustand(conn, versuch, "abonnement", version=version)
        _abonnement(cookie, wid, ursprung, kennung, adapter, geprueft)
    except MetaAnschlussFehler as fehler:
        _fehler_merke(kennung, "unklar" if fehler.unklar else "fehlgeschlagen", str(fehler))
    except VerbindungsFehler:
        _fehler_merke(kennung, "fehlgeschlagen", "Sitzung oder Verbindung hat sich geändert. Anschluss nicht bestätigt.")
        raise
    return status(cookie, wid, ursprung, kennung)


def _abonnement(cookie, wid, ursprung, kennung, adapter, geprueft):
    try:
        if not adapter.ist_abonniert(geprueft):
            adapter.abonnieren(geprueft)
        if not adapter.ist_abonniert(geprueft):
            raise MetaAnschlussFehler("Das Kontoabonnement ist noch nicht nachweisbar.", unklar=True)
    except MetaAnschlussFehler as fehler:
        _fehler_merke(kennung, "teilfehler", str(fehler))
        return
    with atomic_database() as conn:
        versuch = _versuch(conn, cookie, wid, ursprung, kennung)
        _aktiv(versuch, {"abonnement"})
        waba, nummer, token = _entwurf(conn, wid, versuch["version"])
        if (waba, nummer, token) != (geprueft.waba_id, geprueft.phone_number_id, geprueft.token):
            raise VerbindungsFehler("Das geprüfte Ergebnis passt nicht zum gespeicherten Anschlussversuch.")
        # Neuer Versionswechsel erzeugt ein dazu passendes Chiffrat, niemals nur version++.
        version = speichere_verbindungsentwurf(workshop_id=wid, waba_id=geprueft.waba_id,
            phone_number_id=geprueft.phone_number_id, anzeigenummer=geprueft.anzeigenummer,
            token=geprueft.token, erwartete_version=versuch["version"])
        bestaetigung = conn.execute("""UPDATE whatsapp_verbindungen SET herkunft = ?, autorisierung = 'bestaetigt',
            zustand = 'verbunden', coexistence_bereit = 0 WHERE workshop_id = ? AND version = ?""", (HERKUNFT, wid, version))
        if bestaetigung.rowcount != 1:
            raise VerbindungsFehler("Die Verbindung wurde zwischenzeitlich geändert.")
        _zustand(conn, versuch, "abgeschlossen", version=version)
        from app.whatsapp_synchronisierung import anlegen
        verbindung = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone())
        anlegen(conn, verbindung, versuch["ablauf"] - 600)


def fortsetzen(cookie, wid, ursprung, kennung):
    with atomic_database() as conn:
        versuch = _versuch(conn, cookie, wid, ursprung, kennung)
        _aktiv(versuch, {"teilfehler"})
        waba, nummer, token = _entwurf(conn, wid, versuch["version"])
        _zustand(conn, versuch, "abonnement")
    adapter = MetaAnschluss(settings)
    try:
        geprueft = adapter.pruefe(token, waba, nummer)
        _abonnement(cookie, wid, ursprung, kennung, adapter, geprueft)
    except MetaAnschlussFehler as fehler:
        _fehler_merke(kennung, "teilfehler" if fehler.unklar else "fehlgeschlagen", str(fehler))
    except VerbindungsFehler:
        _fehler_merke(kennung, "fehlgeschlagen", "Sitzung oder Verbindung hat sich geändert. Anschluss nicht bestätigt.")
        raise
    return status(cookie, wid, ursprung, kennung)


def automatik_gesperrt(workshop_id):
    with get_conn() as conn:
        zeile = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?",
                             (workshop_id,)).fetchone()
        from app.whatsapp_ereignisse import kontopruefung_offen
        if zeile and kontopruefung_offen(conn, workshop_id, zeile["version"]):
            return True
        if zeile and zeile["herkunft"] == HERKUNFT:
            from app.whatsapp_synchronisierung import technisch_bereit
            if zeile["zustand"] != "verbunden" or not technisch_bereit(conn, zeile):
                return True
    return bool(zeile and zeile["herkunft"] == HERKUNFT
                and (not zeile["coexistence_bereit"] or zeile["autorisierung"] != "bestaetigt"))


def eingang_zurueckhalten(conn, workshop_id, message):
    vorhanden = conn.execute("SELECT 1 FROM whatsapp_zurueckgehalten WHERE workshop_id = ? AND wa_message_id = ?",
                             (workshop_id, message.message_id)).fetchone()
    if vorhanden:
        return True
    if not automatik_gesperrt(workshop_id):
        return False
    conn.execute("""INSERT INTO whatsapp_zurueckgehalten (workshop_id, wa_message_id, phone_number_id, grund)
        VALUES (?, ?, ?, 'coexistence_nicht_freigegeben') ON CONFLICT(workshop_id, wa_message_id) DO NOTHING""",
        (workshop_id, message.message_id, message.phone_number_id))
    return True
