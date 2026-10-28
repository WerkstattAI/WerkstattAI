"""Getrennte Meta-Ereignispfade auf vorhandenen Verbindungen und Nachrichten."""
from __future__ import annotations

import hashlib
import json
import re
import time

from app.db import atomic_database, get_conn, is_postgres, lock_communication_scope


def textwert(wert, grenze=256):
    return wert.strip() if isinstance(wert, str) and 0 < len(wert.strip()) <= grenze else None


def nummer(wert):
    wert = textwert(wert, 64)
    return re.sub(r"[+ ()-]", "", wert) if wert and re.fullmatch(r"[+ ()0-9-]+", wert) else None


def zeitwert(wert):
    if isinstance(wert, bool) or not isinstance(wert, (str, int)):
        return None
    try:
        zeit = int(wert)
        return zeit if 0 < zeit <= time.time() + 300 else None
    except ValueError:
        return None


def aenderungen(payload):
    """Gesamte Lieferung vor Seiteneffekten prüfen; unbekannte Felder bleiben getrennt."""
    if payload.get("object") != "whatsapp_business_account" or not isinstance(payload.get("entry"), list):
        raise ValueError("Ungültige Meta-Lieferung")
    ergebnis, anzahl = [], 0
    for eintrag in payload["entry"]:
        if not isinstance(eintrag, dict) or not isinstance(eintrag.get("changes"), list):
            raise ValueError("Ungültiger Meta-Eintrag")
        for aenderung in eintrag["changes"]:
            if not isinstance(aenderung, dict):
                raise ValueError("Ungültige Meta-Änderung")
            feld, wert = aenderung.get("field"), aenderung.get("value")
            anzahl += 1
            if not isinstance(feld, str) or not isinstance(wert, dict):
                continue
            for name in ("messages", "statuses", "message_echoes"):
                if name in wert:
                    if not isinstance(wert[name], list) or any(not isinstance(x, dict) for x in wert[name]):
                        raise ValueError("Ungültige Meta-Nachrichtenliste")
                    anzahl += max(0, len(wert[name]) - 1)
                    for nachricht in wert[name]:
                        for teil in ("text", "image", "video", "document", "audio"):
                            daten = nachricht.get(teil, {})
                            if not isinstance(daten, dict):
                                raise ValueError("Ungültiger Nachrichteninhalt")
                            for schluessel in ("body", "caption"):
                                if schluessel in daten:
                                    if not isinstance(daten[schluessel], str):
                                        raise ValueError("Ungültiger Nachrichteninhalt")
                                    if len(daten[schluessel]) > 4096:
                                        raise OverflowError("Nachricht überschreitet die Eingabegrenze")
            ergebnis.append((feld, eintrag, wert))
    if anzahl > 100:
        raise OverflowError("Zu viele Meta-Ereignisse")
    return ergebnis


def nachrichten_zuordnung(waba, phone_number_id):
    """M1 bleibt nummerngebunden; autorisierte M2-Nachrichten verlangen auch die WABA."""
    from app.workshops import find_workshop_id_by_whatsapp_phone_number_id
    wid = find_workshop_id_by_whatsapp_phone_number_id(phone_number_id)
    if not wid:
        return None
    with get_conn() as conn:
        zeile = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone()
    if zeile and zeile["herkunft"] != "m1_legacy" and zeile["waba_id"] != waba:
        return None
    return wid


def _verbindung(conn, waba, phone):
    zeilen = conn.execute("""SELECT v.* FROM whatsapp_verbindungen v JOIN workshops w ON w.id = v.workshop_id
        WHERE v.waba_id = ? AND v.phone_number_id = ? AND w.whatsapp_phone_number_id = v.phone_number_id
          AND w.is_demo = 0 AND v.autorisierung = 'bestaetigt' AND v.zustand = 'verbunden'""",
        (waba, phone)).fetchall()
    return dict(zeilen[0]) if len(zeilen) == 1 else None


def echo_offen(conn, wid, kunde):
    return bool(conn.execute("""SELECT 1 FROM whatsapp_messages WHERE workshop_id = ? AND customer_phone = ?
        AND processing_state = 'echo_pruefung' LIMIT 1""", (wid, kunde)).fetchone())


def _uebernehmen(conn, zeile):
    from app.db import get_whatsapp_conversation_control, set_whatsapp_conversation_control
    from app.tickets import add_ticket_note
    wid, kunde = zeile["workshop_id"], zeile["customer_phone"]
    verbindung = conn.execute("SELECT version FROM whatsapp_verbindungen WHERE workshop_id = ?" +
                             (" FOR UPDATE" if is_postgres() else ""), (wid,)).fetchone()
    if not verbindung or verbindung["version"] != json.loads(zeile["payload_json"]).get("verbindung_version"):
        conn.execute("UPDATE whatsapp_messages SET processing_state = 'echo_veraltet' WHERE id = ?", (zeile["id"],))
        return
    kontrolle = get_whatsapp_conversation_control(workshop_id=wid, customer_phone=kunde)
    ticket = kontrolle.get("active_ticket_id")
    if ticket:
        add_ticket_note(ticket, zeile["text"] or "Nachricht aus der WhatsApp Business-App.", workshop_id=wid,
                        sender_role="workshop", purpose="workshop_notification", message_id=zeile["message_id"],
                        delivery_status="sent")
    # Auch bei offenen Fragen bleiben deren Einträge unverändert; nur die Zuständigkeit wechselt.
    set_whatsapp_conversation_control(workshop_id=wid, customer_phone=kunde,
                                     conversation_state="workshop_active", active_ticket_id=ticket)
    conn.execute("UPDATE whatsapp_messages SET processing_state = 'complete', ticket_id = ? WHERE id = ?",
                 (ticket, zeile["id"]))


def verarbeite_echo(eintrag, wert):
    from app.whatsapp import _lock_conversation, save_whatsapp_message
    waba = textwert(eintrag.get("id"))
    meta = wert.get("metadata")
    phone = textwert(meta.get("phone_number_id")) if isinstance(meta, dict) else None
    if not waba or not phone or wert.get("messaging_product") != "whatsapp":
        return 0
    with get_conn() as conn:
        verbindung = _verbindung(conn, waba, phone)
    if not verbindung:
        return 0
    wid, anzahl = verbindung["workshop_id"], 0
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        aktuell = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?" +
                               (" FOR UPDATE" if is_postgres() else ""), (wid,)).fetchone()
        if not aktuell or aktuell["version"] != verbindung["version"] or aktuell["autorisierung"] != "bestaetigt":
            return 0
        for echo in wert.get("message_echoes", []):
            kunde, provider = nummer(echo.get("to")), textwert(echo.get("id"))
            zeit = zeitwert(echo.get("timestamp"))
            if not kunde or not provider or zeit is None:
                continue
            if nummer(echo.get("from")) != nummer(verbindung["anzeigenummer"]) or not nummer(echo.get("from")):
                continue
            _lock_conversation(conn, wid, kunde)
            alt = conn.execute("""SELECT * FROM whatsapp_messages WHERE workshop_id = ?
                AND direction = 'outbound' AND wa_message_id = ?""", (wid, provider)).fetchone()
            if alt:
                if alt["phone_number_id"] == phone and alt["customer_phone"] == kunde:
                    daten = json.loads(alt["payload_json"])
                    daten["echo_bestaetigt"] = True
                    conn.execute("UPDATE whatsapp_messages SET payload_json = ? WHERE id = ?", (json.dumps(daten), alt["id"]))
                continue
            if zeit < int(verbindung["verbunden_seit"]):
                continue
            typ = textwert(echo.get("type"), 32) or "unknown"
            inhalt = echo.get(typ) if isinstance(echo.get(typ), dict) else {}
            text = textwert(inhalt.get("body" if typ == "text" else "caption"), 4096)
            kandidaten = [z["message_id"] for z in conn.execute("""SELECT message_id FROM whatsapp_messages
                WHERE workshop_id = ? AND phone_number_id = ? AND customer_phone = ?
                  AND direction = 'outbound' AND dispatch_state = 'sending' AND wa_message_id IS NULL""",
                (wid, phone, kunde)).fetchall()]
            daten = {"source": "whatsapp_business_app", "sender_role": "workshop", "purpose": "workshop_notification",
                     "verbindung_version": verbindung["version"], "echo_kandidaten": kandidaten, "echo_bestaetigt": True}
            if typ in {"image", "audio", "video", "document", "sticker"}:
                daten[typ] = {k: v for k, v in inhalt.items() if k in {"id", "mime_type", "sha256", "caption", "filename"}
                              and isinstance(v, str) and len(v) <= 4096}
            save_whatsapp_message(workshop_id=wid, phone_number_id=phone, customer_phone=kunde,
                direction="outbound", message_type=typ, text=text or {"image": "Foto aus der Business-App.",
                "audio": "Sprachnachricht aus der Business-App.", "video": "Video aus der Business-App."}.get(typ, "Nachricht aus der Business-App."),
                wa_message_id=provider, status="sent", payload=daten, processing_state="echo_pruefung",
                message_id="echo:" + hashlib.sha256((phone + ":" + provider).encode()).hexdigest())
            zeile = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND wa_message_id = ? AND direction = 'outbound'",
                                 (wid, provider)).fetchone()
            if not kandidaten and zeit > int(verbindung["verbunden_seit"]):
                _uebernehmen(conn, zeile)
            elif not kandidaten:
                # Sekundengenaue Providerzeit kann den Neuanschluss nicht sicher ordnen.
                # Sichtbar halten und Automatik sperren, aber keine Werkstattaktion erfinden.
                daten["echo_zeit_ungeklaert"] = True
                conn.execute("UPDATE whatsapp_messages SET payload_json = ? WHERE id = ?", (json.dumps(daten), zeile["id"]))
            anzahl += 1
    return anzahl


def ordne_fruehe_rueckmeldung(conn, zeile, provider, daten):
    """Vor dem Provider-ID-CAS ein vorläufiges Echo in die ursprüngliche Sendung falten."""
    if not provider:
        return
    echo = conn.execute("""SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND direction = 'outbound'
        AND wa_message_id = ? AND processing_state = 'echo_pruefung'""", (zeile["workshop_id"], provider)).fetchone()
    if echo and echo["phone_number_id"] == zeile["phone_number_id"] and echo["customer_phone"] == zeile["customer_phone"]:
        kandidaten = json.loads(echo["payload_json"]).get("echo_kandidaten", [])
        if zeile["message_id"] in kandidaten:
            daten["echo_bestaetigt"] = True
            conn.execute("DELETE FROM whatsapp_messages WHERE id = ?", (echo["id"],))


def schliesse_rueckmeldungen(conn, wid, kunde, provider):
    from app.whatsapp import update_whatsapp_message_status
    if provider:
        versand = conn.execute("SELECT phone_number_id FROM whatsapp_messages WHERE workshop_id = ? AND wa_message_id = ? AND direction = 'outbound'",
                               (wid, provider)).fetchone()
        for ereignis in conn.execute("""SELECT * FROM whatsapp_events WHERE workshop_id = ? AND wa_message_id = ?
            AND from_phone = ? AND phone_number_id = ? AND event_type = 'status_frueh' ORDER BY id""",
            (wid, provider, kunde, versand["phone_number_id"] if versand else None)).fetchall():
            update_whatsapp_message_status(workshop_id=wid, wa_message_id=provider,
                status=ereignis["message_type"], payload=json.loads(ereignis["payload_json"]))
    for echo in conn.execute("""SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND customer_phone = ?
        AND processing_state = 'echo_pruefung' ORDER BY id""", (wid, kunde)).fetchall():
        daten = json.loads(echo["payload_json"])
        if daten.get("echo_zeit_ungeklaert"):
            continue
        kandidaten = daten.get("echo_kandidaten", [])
        offen = any(conn.execute("SELECT 1 FROM whatsapp_messages WHERE workshop_id = ? AND message_id = ? AND dispatch_state = 'sending'",
                                 (wid, mid)).fetchone() for mid in kandidaten)
        if not offen:
            _uebernehmen(conn, echo)


def merke_fruehen_status(conn, wid, phone, kunde, provider, status, daten):
    if not phone or not kunde or status not in {"sent", "delivered", "read", "failed"}:
        return
    if not conn.execute("""SELECT 1 FROM whatsapp_messages WHERE workshop_id = ? AND phone_number_id = ?
        AND customer_phone = ? AND direction = 'outbound' AND dispatch_state = 'sending'""", (wid, phone, kunde)).fetchone():
        return
    schluessel = "status:" + hashlib.sha256((phone + ":" + provider + ":" + status).encode()).hexdigest()
    conn.execute("""INSERT INTO whatsapp_events (workshop_id, phone_number_id, from_phone, wa_message_id,
        event_type, message_type, payload_json, ereignis_schluessel) VALUES (?, ?, ?, ?, 'status_frueh', ?, ?, ?)
        ON CONFLICT(workshop_id, ereignis_schluessel) DO NOTHING""", (wid, phone, kunde, provider, status, json.dumps(daten), schluessel))


def _kontoverbindungen(konto):
    with get_conn() as conn:
        return [dict(z) for z in conn.execute("SELECT * FROM whatsapp_verbindungen WHERE waba_id = ? ORDER BY workshop_id", (konto,)).fetchall()]


def verarbeite_konto(eintrag, wert):
    from app.whatsapp_verbindungen import settings, widerrufe_verbindung
    ereignis = wert.get("event")
    if ereignis not in {"PARTNER_REMOVED", "PARTNER_APP_UNINSTALLED", "ACCOUNT_OFFBOARDED", "ACCOUNT_DELETED"}:
        return 0
    info = wert.get("waba_info")
    if info is not None and not isinstance(info, dict):
        return 0
    if info is not None and ereignis not in {"PARTNER_REMOVED", "PARTNER_APP_UNINSTALLED"}:
        return 0
    if ereignis == "PARTNER_APP_UNINSTALLED" and (not info or textwert(info.get("partner_app_id")) != settings.whatsapp_app_id):
        return 0
    # Bei Partner-Ereignissen ist entry.id der Partner; waba_info bezeichnet das Kundenkonto.
    konto = textwert(info.get("waba_id")) if info is not None else textwert(eintrag.get("id"))
    zeit = zeitwert(eintrag.get("time"))
    telefon = nummer(wert.get("phone_number")) if "phone_number" in wert else None
    if not konto or zeit is None or ("phone_number" in wert and not telefon):
        return 0
    kandidaten = _kontoverbindungen(konto)
    kandidaten = [z for z in kandidaten if (not telefon or nummer(z["anzeigenummer"]) == telefon)]
    if telefon and len(kandidaten) != 1:
        return 0
    schluessel = "konto:" + hashlib.sha256(json.dumps([konto, telefon, ereignis, zeit], separators=(",", ":")).encode()).hexdigest()
    anzahl = 0
    for verbindung in kandidaten:
        wid = verbindung["workshop_id"]
        with atomic_database() as conn:
            lock_communication_scope(conn, wid)
            aktuell = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?" +
                                  (" FOR UPDATE" if is_postgres() else ""), (wid,)).fetchone()
            if (aktuell["version"] != verbindung["version"] or aktuell["autorisierung"] != "bestaetigt"
                    or zeit < int(aktuell["verbunden_seit"])):
                continue
            unklar = zeit == int(aktuell["verbunden_seit"])
            neu = conn.execute("""INSERT INTO whatsapp_events (workshop_id, phone_number_id, event_type, payload_json,
                ereignis_schluessel) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workshop_id, ereignis_schluessel) DO NOTHING""", (wid, aktuell["phone_number_id"],
                "account_update_pruefung" if unklar else "account_update",
                json.dumps({"event": ereignis, "version": aktuell["version"], "zeit": zeit}), schluessel))
            if neu.rowcount:
                if not unklar:
                    widerrufe_verbindung(wid, erwartete_version=aktuell["version"])
                anzahl += 1
    return anzahl


def kontopruefung_offen(conn, wid, version):
    return any(json.loads(z["payload_json"]).get("version") == version for z in conn.execute(
        "SELECT payload_json FROM whatsapp_events WHERE workshop_id = ? AND event_type = 'account_update_pruefung'", (wid,)).fetchall())
