"""Werkstattgebundene WhatsApp-Zugänge ohne öffentliches Provisionierungsrecht."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db import atomic_database, get_conn, is_postgres


class VerbindungsFehler(ValueError):
    """Bereinigter Fehler, der auch in der Oberfläche angezeigt werden darf."""


@dataclass(frozen=True)
class WhatsAppZugang:
    workshop_id: str
    phone_number_id: str
    version: int
    token: str = field(repr=False)


def normalisiere_nummernwert(wert: str | None) -> str | None:
    return str(wert or "").strip() or None


def migriere_verbindungen(conn, konfiguration) -> None:
    """Altzuordnungen erhalten; Mehrdeutigkeit sperrt die Migration atomar."""
    if is_postgres():
        conn.execute("LOCK TABLE workshops IN SHARE ROW EXCLUSIVE MODE")
    altzuordnungen = conn.execute("SELECT id, whatsapp_phone_number_id, whatsapp_display_phone_number FROM workshops").fetchall()
    nummern: dict[str, int] = {}
    for zeile in altzuordnungen:
        nummer = normalisiere_nummernwert(zeile["whatsapp_phone_number_id"])
        if nummer:
            nummern[nummer] = nummern.get(nummer, 0) + 1
    konflikte = sum(anzahl > 1 for anzahl in nummern.values())
    if konflikte:
        raise VerbindungsFehler(
            f"Mehrdeutige WhatsApp-Altzuordnung: {konflikte} Nummerngruppen. "
            "Bestehende Werkstattzuordnungen vor der Migration prüfen; keine Zuordnung wurde ausgewählt."
        )
    for zeile in altzuordnungen:
        nummer = normalisiere_nummernwert(zeile["whatsapp_phone_number_id"])
        anzeige = normalisiere_nummernwert(zeile["whatsapp_display_phone_number"])
        if nummer != zeile["whatsapp_phone_number_id"] or anzeige != zeile["whatsapp_display_phone_number"]:
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ?, whatsapp_display_phone_number = ? WHERE id = ?",
                         (nummer, anzeige, zeile["id"]))
    trim_funktion = "BTRIM" if is_postgres() else "TRIM"
    leerzeichen = " \t\n\r\v\f"
    conn.execute(f"""CREATE UNIQUE INDEX IF NOT EXISTS idx_workshops_whatsapp_nummer_eindeutig
        ON workshops(NULLIF({trim_funktion}(whatsapp_phone_number_id, '{leerzeichen}'), ''))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_verbindungen (
        workshop_id TEXT PRIMARY KEY REFERENCES workshops(id),
        waba_id TEXT,
        phone_number_id TEXT UNIQUE,
        anzeigenummer TEXT,
        herkunft TEXT NOT NULL DEFAULT 'manuell_altbestand',
        autorisierung TEXT NOT NULL DEFAULT 'unbestaetigt'
            CHECK(autorisierung IN ('unbestaetigt', 'bestaetigt', 'widerrufen', 'altbestand')),
        zustand TEXT NOT NULL DEFAULT 'nicht_verbunden'
            CHECK(zustand IN ('nicht_verbunden', 'vorbereitet', 'verbunden', 'widerrufen')),
        coexistence_bereit INTEGER NOT NULL DEFAULT 0 CHECK(coexistence_bereit IN (0, 1)),
        version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
        zugang_verschluesselt TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS verbindungs_migrationen (
        name TEXT PRIMARY KEY, erstellt_am TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    if conn.execute("SELECT 1 FROM verbindungs_migrationen WHERE name = 'm2_1'").fetchone():
        return
    for zeile in conn.execute("SELECT * FROM workshops WHERE whatsapp_phone_number_id IS NOT NULL").fetchall():
        # Nur die bereits konfigurierte eigene M1-Zuordnung wird einmalig festgehalten.
        legacy = (not zeile["is_demo"] and zeile["id"] == konfiguration.default_workshop_id
                  and zeile["whatsapp_phone_number_id"] == normalisiere_nummernwert(
                      konfiguration.whatsapp_default_phone_number_id))
        conn.execute("""INSERT INTO whatsapp_verbindungen
            (workshop_id, phone_number_id, anzeigenummer, herkunft, autorisierung)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(workshop_id) DO NOTHING""",
            (zeile["id"], zeile["whatsapp_phone_number_id"], zeile["whatsapp_display_phone_number"],
             "m1_legacy" if legacy else "manuell_altbestand", "altbestand" if legacy else "unbestaetigt"))
    conn.execute("INSERT INTO verbindungs_migrationen (name) VALUES ('m2_1')")


def pruefe_unveraenderte_nummer(conn, workshop_id: str, nummer: str | None, anzeige: str | None) -> None:
    """Profil- und Adminformulare dürfen keine Nummernbindung verändern."""
    zeile = conn.execute("SELECT whatsapp_phone_number_id, whatsapp_display_phone_number FROM workshops WHERE id = ?",
                         (workshop_id,)).fetchone()
    for wert, spalte in ((nummer, "whatsapp_phone_number_id"), (anzeige, "whatsapp_display_phone_number")):
        if wert is not None and normalisiere_nummernwert(wert) != normalisiere_nummernwert(zeile[spalte] if zeile else None):
            raise VerbindungsFehler("WhatsApp-Zuordnungen können hier nicht geändert werden. Ein verifizierter Anschluss ist erforderlich.")


def _chiffre() -> Fernet:
    try:
        schluessel = settings.whatsapp_zugangsschluessel
        if not schluessel or schluessel in {settings.auth_secret, settings.whatsapp_app_secret}:
            raise ValueError()
        return Fernet(schluessel.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        raise VerbindungsFehler("Der geschützte WhatsApp-Zugang ist nicht verfügbar. Schlüsselkonfiguration prüfen.") from None


def speichere_verbindungsentwurf(*, workshop_id: str, waba_id: str, phone_number_id: str,
                                 anzeigenummer: str, token: str, erwartete_version: int = 0) -> int:
    """Interner Entwurf ohne Autorisierung; kein Ersatz für verifizierte Meta-Ergebnisse.

    Es gibt bewusst keinen HTTP-Endpunkt und keine Funktion zur Bestätigung.
    Der spätere Provisionierungsdienst muss seine Meta-Prüfung selbst nachweisen.
    """
    nummer = normalisiere_nummernwert(phone_number_id)
    konto = normalisiere_nummernwert(waba_id)
    if not nummer or not konto or not token.strip():
        raise VerbindungsFehler("Die Verbindungsangaben sind unvollständig.")
    version = erwartete_version + 1
    inhalt = json.dumps([workshop_id, konto, nummer, version, token], ensure_ascii=True).encode()
    geheimnis = _chiffre().encrypt(inhalt).decode("ascii")
    try:
        with atomic_database() as conn:
            werkstatt = conn.execute("SELECT * FROM workshops WHERE id = ?" + (" FOR UPDATE" if is_postgres() else ""),
                                     (workshop_id,)).fetchone()
            if not werkstatt or werkstatt["is_demo"]:
                raise VerbindungsFehler("Für diese Werkstatt ist kein WhatsApp-Anschluss zulässig.")
            alt = conn.execute("SELECT version FROM whatsapp_verbindungen WHERE workshop_id = ?", (workshop_id,)).fetchone()
            if (alt["version"] if alt else 0) != erwartete_version:
                raise VerbindungsFehler("Die WhatsApp-Verbindung wurde zwischenzeitlich geändert.")
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ?, whatsapp_display_phone_number = ? WHERE id = ?",
                         (nummer, normalisiere_nummernwert(anzeigenummer), workshop_id))
            # Der Widerruf kann nach dem Lesen der Version bereits bestätigt sein.
            # Deshalb entscheidet erst der bedingte Schreibvorgang über den Erfolg.
            ergebnis = conn.execute("""INSERT INTO whatsapp_verbindungen
                (workshop_id, waba_id, phone_number_id, anzeigenummer, herkunft, autorisierung, zustand,
                 coexistence_bereit, version, zugang_verschluesselt)
                VALUES (?, ?, ?, ?, 'interner_entwurf', 'unbestaetigt', 'vorbereitet', 0, ?, ?)
                ON CONFLICT(workshop_id) DO UPDATE SET waba_id = excluded.waba_id,
                phone_number_id = excluded.phone_number_id, anzeigenummer = excluded.anzeigenummer,
                herkunft = excluded.herkunft, autorisierung = excluded.autorisierung, zustand = excluded.zustand,
                coexistence_bereit = 0, version = excluded.version,
                zugang_verschluesselt = excluded.zugang_verschluesselt, updated_at = CURRENT_TIMESTAMP
                WHERE whatsapp_verbindungen.version = ?""",
                (workshop_id, konto, nummer, normalisiere_nummernwert(anzeigenummer), version, geheimnis,
                 erwartete_version))
            if ergebnis.rowcount != 1:
                # Die gesamte Transaktion einschließlich Nummernreservierung rollt zurück.
                raise VerbindungsFehler("Die WhatsApp-Verbindung wurde zwischenzeitlich geändert.")
    except VerbindungsFehler:
        raise
    except Exception:
        raise VerbindungsFehler("Die WhatsApp-Zuordnung konnte nicht gespeichert werden. Eindeutigkeit und Datenbank prüfen.") from None
    return version


def widerrufe_verbindung(workshop_id: str, *, erwartete_version: int) -> None:
    with atomic_database() as conn:
        ergebnis = conn.execute("""UPDATE whatsapp_verbindungen SET autorisierung = 'widerrufen',
            zustand = 'widerrufen', coexistence_bereit = 0, zugang_verschluesselt = NULL,
            version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE workshop_id = ? AND version = ?""",
            (workshop_id, erwartete_version))
        if ergebnis.rowcount != 1:
            raise VerbindungsFehler("Die WhatsApp-Verbindung wurde zwischenzeitlich geändert oder fehlt.")


def zugang_fuer_werkstatt(workshop_id: str, *, phone_number_id: str | None = None) -> WhatsAppZugang:
    """Einzige Auflösung für Versand und Medien; keine Standardwerkstatt als Ersatz."""
    with get_conn() as conn:
        werkstatt = conn.execute("SELECT * FROM workshops WHERE id = ?", (workshop_id,)).fetchone()
        zeile = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (workshop_id,)).fetchone()
        nummer = normalisiere_nummernwert(werkstatt["whatsapp_phone_number_id"]) if werkstatt else None
        zuordnungen = conn.execute("SELECT id FROM workshops WHERE NULLIF(TRIM(whatsapp_phone_number_id), '') = ?",
                                  (nummer,)).fetchall() if nummer else []
    if not werkstatt or werkstatt["is_demo"]:
        raise VerbindungsFehler("Für diese Werkstatt ist kein WhatsApp-Anschluss zulässig.")
    if (not zeile or not nummer or len(zuordnungen) != 1 or zeile["phone_number_id"] != nummer
            or (phone_number_id is not None and normalisiere_nummernwert(phone_number_id) != nummer)):
        raise VerbindungsFehler("Keine eindeutige WhatsApp-Verbindung für diese Werkstatt vorhanden.")
    if zeile["autorisierung"] == "widerrufen" or zeile["zustand"] == "widerrufen":
        raise VerbindungsFehler("Die WhatsApp-Verbindung wurde widerrufen.")
    if (zeile["herkunft"] == "m1_legacy" and zeile["autorisierung"] == "altbestand"
            and workshop_id == settings.default_workshop_id
            and nummer == normalisiere_nummernwert(settings.whatsapp_default_phone_number_id)):
        token = str(settings.whatsapp_access_token or "").strip()
        if token:
            return WhatsAppZugang(workshop_id, nummer, zeile["version"], token)
    if (zeile["autorisierung"] != "bestaetigt" or zeile["zustand"] != "verbunden"
            or not zeile["waba_id"] or not zeile["zugang_verschluesselt"]):
        raise VerbindungsFehler("Der WhatsApp-Anschluss ist noch nicht autorisiert oder der Zugang fehlt.")
    try:
        inhalt = json.loads(_chiffre().decrypt(zeile["zugang_verschluesselt"].encode("ascii")))
        if (not isinstance(inhalt, list) or len(inhalt) != 5 or
                inhalt[:4] != [workshop_id, zeile["waba_id"], nummer, zeile["version"]]
                or not isinstance(inhalt[4], str) or not inhalt[4].strip()):
            raise ValueError()
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise VerbindungsFehler("Der geschützte WhatsApp-Zugang konnte nicht geöffnet werden. Schlüssel und Verbindung prüfen.") from None
    return WhatsAppZugang(workshop_id, nummer, zeile["version"], inhalt[4])


def verbindungsstatus(workshop_id: str) -> dict:
    """Nur ausdrücklich freigegebene Statusfelder; niemals Chiffrat oder Zugang."""
    with get_conn() as conn:
        zeile = conn.execute("""SELECT herkunft, autorisierung, zustand, coexistence_bereit, version,
            CASE WHEN zugang_verschluesselt IS NULL THEN 0 ELSE 1 END AS zugang_gespeichert
            FROM whatsapp_verbindungen WHERE workshop_id = ?""", (workshop_id,)).fetchone()
    status = dict(zeile) if zeile else {"herkunft": None, "autorisierung": "unbestaetigt", "zustand": "nicht_verbunden",
                                      "coexistence_bereit": 0, "version": 0, "zugang_gespeichert": 0}
    try:
        zugang_fuer_werkstatt(workshop_id)
        status.update(versand_bereit=True, meldung=("Eigene M1-Altverbindung; keine Coexistence-Freigabe."
                      if status["herkunft"] == "m1_legacy" else "Autorisierte WhatsApp-Verbindung."))
    except VerbindungsFehler as fehler:
        status.update(versand_bereit=False, meldung=str(fehler))
    return status
