"""Begrenzte Business-App-Synchronisierung auf dem vorhandenen Ereignisjournal."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone

from app.db import atomic_database, get_conn, is_postgres, lock_communication_scope
from app.whatsapp_ereignisse import nummer, textwert, zeitwert, kontopruefung_offen
from app.whatsapp_verbindungen import VerbindungsFehler, zugang_fuer_werkstatt

ARTEN = ("smb_app_state_sync", "history")
MEDIEN = {"image", "audio", "video", "document", "sticker"}
MELDUNGEN = {
    "offen": "Synchronisierung noch nicht angefordert.",
    "reserviert": "Anforderung reserviert. Bei Unterbrechung ist der Ausgang unklar; kein erneuter Start.",
    "angenommen": "Anforderung angenommen; Liefernachweis steht noch aus.",
    "laufend": "Daten werden übernommen; Abschluss noch offen.",
    "abgeschlossen": "Meta meldet den Nachrichtenimport als abgeschlossen; bekannte Teile sind vorhanden.",
    "nicht_geteilt": "Der Verlauf wurde in der Business-App nicht geteilt.",
    "verzicht": "Auf den lokalen Verlaufsimport wurde ausdrücklich verzichtet.",
    "unklar": "Ergebnis der einmaligen Anforderung unklar. Kein erneuter Start; Klärung erforderlich.",
    "frist": "Die Frist für die einmalige Anforderung ist abgelaufen.",
    "quote": "Die einmalige Anforderung wurde bereits verbraucht. Klärung erforderlich.",
    "fehler": "Meta hat die Anforderung abgewiesen. Klärung erforderlich.",
    "pruefung": "Zuordnung oder Daten widersprüchlich. Synchronisierung muss geprüft werden.",
    "nachweis_fehlt": "Für diesen bestehenden Anschluss fehlt ein sicherer Initialisierungsnachweis.",
}


def _json(daten):
    return json.dumps(daten, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(daten):
    return hashlib.sha256(_json(daten).encode()).hexdigest()


def migriere_synchronisierung(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_sync (
        workshop_id TEXT NOT NULL REFERENCES workshops(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, waba_id TEXT NOT NULL, phone_number_id TEXT NOT NULL,
        art TEXT NOT NULL, beginn DOUBLE PRECISION, frist DOUBLE PRECISION,
        generation_offen INTEGER NOT NULL DEFAULT 0, zustand TEXT NOT NULL,
        reserviert_am DOUBLE PRECISION, request_id TEXT, fehlercode INTEGER,
        fortschritt INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(workshop_id, version, art))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_sync_teile (
        workshop_id TEXT NOT NULL REFERENCES workshops(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, phase INTEGER NOT NULL, teil INTEGER NOT NULL,
        pruefsumme TEXT NOT NULL, PRIMARY KEY(workshop_id, version, phase, teil))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS whatsapp_kontakte (
        workshop_id TEXT NOT NULL REFERENCES workshops(id) ON DELETE CASCADE,
        phone_number_id TEXT NOT NULL, version INTEGER NOT NULL, kundenrufnummer TEXT NOT NULL,
        name TEXT, vorname TEXT, entfernt INTEGER NOT NULL, zeit BIGINT,
        unklar INTEGER NOT NULL DEFAULT 0, pruefsumme TEXT NOT NULL,
        PRIMARY KEY(workshop_id, phone_number_id, kundenrufnummer))""")
    # Altanschlüsse erhalten weder eine neue 24-Stunden-Frist noch erfundene Herkunft.
    for v in conn.execute("SELECT * FROM whatsapp_verbindungen WHERE herkunft = 'embedded_signup_coexistence' AND autorisierung = 'bestaetigt'").fetchall():
        anlegen(conn, dict(v), None)


def anlegen(conn, verbindung, beginn):
    """Einmal je verifiziertem Anschluss; Beginn ist die konservative Signup-Startzeit."""
    v = verbindung
    alt = conn.execute("SELECT 1 FROM whatsapp_sync WHERE waba_id = ? AND phone_number_id = ? AND NOT (workshop_id = ? AND version = ?) LIMIT 1",
                       (v["waba_id"], v["phone_number_id"], v["workshop_id"], v["version"])).fetchone()
    for art in ARTEN:
        conn.execute("""INSERT INTO whatsapp_sync
            (workshop_id, version, waba_id, phone_number_id, art, beginn, frist, generation_offen, zustand)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(workshop_id, version, art) DO NOTHING""",
            (v["workshop_id"], v["version"], v["waba_id"], v["phone_number_id"], art, beginn,
             beginn + 86400 if beginn is not None else None, int(bool(alt) or beginn is None),
             "pruefung" if alt else "offen" if beginn is not None else "nachweis_fehlt"))


def _aktuell(conn, wid):
    v = conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?" +
                     (" FOR UPDATE" if is_postgres() else ""), (wid,)).fetchone()
    if (not v or v["herkunft"] != "embedded_signup_coexistence" or v["autorisierung"] != "bestaetigt"
            or v["zustand"] != "verbunden" or kontopruefung_offen(conn, wid, v["version"])):
        return None
    return dict(v)


def _auftraege(conn, v):
    return {z["art"]: dict(z) for z in conn.execute("SELECT * FROM whatsapp_sync WHERE workshop_id = ? AND version = ? AND waba_id = ? AND phone_number_id = ?",
        (v["workshop_id"], v["version"], v["waba_id"], v["phone_number_id"])).fetchall()}


def technisch_bereit(conn, v):
    a = _auftraege(conn, v)
    return (len(a) == 2 and not any(z["generation_offen"] for z in a.values())
            and a["history"]["zustand"] in {"abgeschlossen", "nicht_geteilt", "verzicht"}
            and bool(a["smb_app_state_sync"]["request_id"])
            and a["smb_app_state_sync"]["zustand"] in {"angenommen", "laufend"})


def status(wid):
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        v = _aktuell(conn, wid)
        if not v:
            return {"autorisiert": False, "technisch_bereit": False, "betrieb_bereit": False, "schritte": []}
        a = _auftraege(conn, v)
        schritte = []
        for art in ARTEN:
            z = a.get(art)
            if not z:
                continue
            if z["zustand"] == "offen" and z["frist"] <= time.time():
                _zustand(conn, z, "frist")
                z["zustand"] = "frist"
            schritte.append({"art": art, "zustand": z["zustand"], "meldung": MELDUNGEN[z["zustand"]],
                            "fortschritt": z["fortschritt"], "startbar": z["zustand"] == "offen"})
        medien = conn.execute("SELECT COUNT(*) AS n FROM whatsapp_messages WHERE workshop_id = ? AND message_type = 'media_placeholder'", (wid,)).fetchone()["n"]
        return {"autorisiert": True, "technisch_bereit": technisch_bereit(conn, v),
                "betrieb_bereit": bool(v["coexistence_bereit"]), "schritte": schritte, "medien_offen": medien,
                "kontakte_vollstaendig": False}


def _zustand(conn, z, zustand, code=None):
    conn.execute("UPDATE whatsapp_sync SET zustand = ?, fehlercode = ? WHERE workshop_id = ? AND version = ? AND art = ?",
                 (zustand, code, z["workshop_id"], z["version"], z["art"]))


def schritt(cookie, wid, ursprung, art, *, verzichten=False):
    """Aktuelle Berechtigung, dauerhafte Reservierung, danach HTTP ohne DB-Sperren."""
    from app import whatsapp_anschluss as anschluss
    from app.whatsapp_meta_sync import initialisieren
    if art not in ARTEN or (verzichten and art != "history"):
        raise VerbindungsFehler("Ungültiger Synchronisierungsschritt.")
    with atomic_database() as conn:
        anschluss._berechtigt(conn, cookie, wid, ursprung)
        v = _aktuell(conn, wid)
        z = _auftraege(conn, v).get(art) if v else None
        if not z or z["generation_offen"]:
            raise VerbindungsFehler("Der Anschluss kann keiner sicheren Synchronisierung zugeordnet werden.")
        if z["zustand"] != "offen":
            return status(wid)
        if verzichten:
            _zustand(conn, z, "verzicht")
            return status(wid)
        if z["frist"] <= time.time():
            _zustand(conn, z, "frist")
            return status(wid)
        zugang = zugang_fuer_werkstatt(wid, phone_number_id=v["phone_number_id"])
        conn.execute("UPDATE whatsapp_sync SET zustand = 'reserviert', reserviert_am = ? WHERE workshop_id = ? AND version = ? AND art = ? AND zustand = 'offen'",
                     (time.time(), wid, v["version"], art))
    # Kein Retry: auch ein Absturz direkt vor dem Transport lässt die Reservierung stehen.
    ergebnis = initialisieren(anschluss.settings, zugang, art)
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        aktuell = _aktuell(conn, wid)
        if aktuell and aktuell["version"] == v["version"]:
            z = _auftraege(conn, aktuell)[art]
            if ergebnis.get("request_id"):
                conn.execute("UPDATE whatsapp_sync SET request_id = ? WHERE workshop_id = ? AND version = ? AND art = ?",
                             (ergebnis["request_id"], wid, v["version"], art))
            if z["zustand"] == "reserviert":
                _zustand(conn, z, ergebnis["zustand"], ergebnis.get("code"))
            elif ergebnis.get("code") == 2593109 and z["zustand"] not in {"nicht_geteilt", "verzicht"}:
                _zustand(conn, z, "pruefung", 2593109)
    return status(wid)


def _liste(wert, grenze=5000):
    if not isinstance(wert, list) or any(not isinstance(x, dict) for x in wert):
        raise ValueError("Ungültige Synchronisierungsliste")
    if len(wert) > grenze:
        raise OverflowError("Synchronisierungsliste zu groß")
    return wert


def _text(wert, grenze=256):
    t = textwert(wert, grenze)
    if t is None:
        raise ValueError("Ungültiger Synchronisierungswert")
    return t


def _nummer(wert):
    n = nummer(wert)
    if not n or not re.fullmatch(r"[0-9]{3,32}", n):
        raise ValueError("Ungültige Kontaktnummer")
    return n


def _nachricht(n, *, medium=False):
    typ = _text(n.get("type"), 32)
    zeit = zeitwert(n.get("timestamp"))
    if zeit is None:
        raise ValueError("Ungültige Nachrichtenzeit")
    r = {"id": _text(n.get("id")), "from": _nummer(n.get("from")), "zeit": zeit, "type": typ}
    if "to" in n:
        r["to"] = _nummer(n["to"])
    if medium and typ not in MEDIEN:
        raise ValueError("Ungültige Mediennachlieferung")
    if typ in MEDIEN | {"text"}:
        inhalt = n.get(typ)
        if not isinstance(inhalt, dict):
            raise ValueError("Ungültiger Nachrichteninhalt")
        r[typ] = {}
        for k in ("body", "caption", "id", "mime_type", "sha256", "filename"):
            if k in inhalt:
                if not isinstance(inhalt[k], str) or len(inhalt[k]) > (4096 if k in {"body", "caption"} else 256):
                    raise ValueError("Ungültiger Medieninhalt")
                r[typ][k] = inhalt[k]
        if medium and not re.fullmatch(r"[0-9]{1,128}", r[typ].get("id", "")):
            raise ValueError("Ungültige Medienkennung")
    if "history_context" in n:
        h = n["history_context"]
        if not isinstance(h, dict) or h.get("status") not in {"DELIVERED", "ERROR", "PENDING", "PLAYED", "READ", "SENT"}:
            raise ValueError("Ungültiger Verlaufsstatus")
        r["verlauf_status"] = h["status"]
    return r


def validiere(feld, eintrag, wert):
    """Nur benötigte Providerfelder übernehmen; keine URLs oder rohen Fehlermeldungen."""
    meta = wert.get("metadata")
    if not isinstance(meta, dict) or wert.get("messaging_product") != "whatsapp":
        raise ValueError("Ungültige Synchronisierungszuordnung")
    r = {"waba": _text(eintrag.get("id"), 32), "phone": _text(meta.get("phone_number_id"), 32), "feld": feld}
    if not r["waba"].isdigit() or not r["phone"].isdigit():
        raise ValueError("Ungültige Synchronisierungskennung")
    anzahl = 0
    if feld == "smb_app_state_sync":
        r["kontakte"] = []
        for k in _liste(wert.get("state_sync")):
            c, m = k.get("contact"), k.get("metadata")
            if k.get("type") != "contact" or k.get("action") not in {"add", "remove"} or not isinstance(c, dict) or not isinstance(m, dict):
                raise ValueError("Ungültige Kontaktänderung")
            zeit = zeitwert(m.get("timestamp"))
            # Ein Sonderwert ohne belegbare Änderungszeit wird nicht als neueste Änderung ausgegeben.
            if zeit is None and m.get("timestamp") not in (-1, "-1", 0, "0"):
                raise ValueError("Ungültige Kontaktzeit")
            kontakt = {"nummer": _nummer(c.get("phone_number")), "aktion": k["action"], "zeit": zeit,
                       "name": None, "vorname": None}
            if k["action"] == "add":
                for quell, ziel in (("full_name", "name"), ("first_name", "vorname")):
                    if quell in c:
                        kontakt[ziel] = _text(c[quell], 256)
            r["kontakte"].append(kontakt)
        anzahl = len(r["kontakte"])
    else:
        r.update(teile=[], medien=[])
        for h in _liste(wert.get("history", []), 100):
            if "errors" in h:
                codes = [e.get("code") for e in _liste(h["errors"], 20)]
                if not codes or any(type(c) is not int or not 0 <= c <= 2147483647 for c in codes) or "threads" in h:
                    raise ValueError("Ungültiger Verlaufsfehler")
                r["teile"].append({"fehler": codes})
                continue
            m = h.get("metadata")
            if (not isinstance(m, dict) or type(m.get("phase")) is not int or m["phase"] not in (0, 1, 2)
                    or type(m.get("chunk_order")) is not int or not 0 <= m["chunk_order"] <= 100000
                    or type(m.get("progress")) is not int or not 0 <= m["progress"] <= 100):
                raise ValueError("Ungültiger Verlaufsfortschritt")
            teil = {"phase": m["phase"], "teil": m["chunk_order"], "fortschritt": m["progress"], "nachrichten": []}
            for thread in _liste(h.get("threads")):
                kunde = _nummer(thread.get("id"))
                for n in _liste(thread.get("messages")):
                    teil["nachrichten"].append({**_nachricht(n), "kunde": kunde})
            anzahl += len(teil["nachrichten"])
            r["teile"].append(teil)
        for n in _liste(wert.get("messages", [])):
            r["medien"].append(_nachricht(n, medium=True))
        anzahl += len(r["medien"])
        if any("fehler" in t for t in r["teile"]) and (r["medien"] or any("fehler" not in t for t in r["teile"])):
            raise ValueError("Widersprüchliche Verlaufsentscheidung")
    if anzahl > 5000:
        raise OverflowError("Zu viele Importdatensätze")
    return r, anzahl


def erfasse(daten):
    """Autorisiert und dauerhaft erfassen, erst danach lokal importieren."""
    with get_conn() as conn:
        v = conn.execute("SELECT workshop_id FROM whatsapp_verbindungen WHERE waba_id = ? AND phone_number_id = ?",
                         (daten["waba"], daten["phone"])).fetchone()
    if not v:
        return None
    wid = v["workshop_id"]
    with atomic_database() as conn:
        lock_communication_scope(conn, wid)
        v = _aktuell(conn, wid)
        if not v or (v["waba_id"], v["phone_number_id"]) != (daten["waba"], daten["phone"]):
            return None
        z = _auftraege(conn, v).get(daten["feld"])
        if not z or z["generation_offen"] or z["zustand"] in {"offen", "verzicht", "frist", "quote", "fehler", "nachweis_fehlt", "pruefung"}:
            return None
        key = f"sync:{v['version']}:" + _hash(daten)
        conn.execute("""INSERT INTO whatsapp_events (workshop_id, phone_number_id, event_type, payload_json, ereignis_schluessel)
            VALUES (?, ?, 'sync_offen', ?, ?) ON CONFLICT(workshop_id, ereignis_schluessel) DO NOTHING""",
            (wid, v["phone_number_id"], _json({"version": v["version"], "daten": daten}), key))
    return wid


def verarbeite_offene(wid):
    """Journal und Import pro Lieferung atomar; Dashboard setzt nach Neustart lokal fort."""
    for _ in range(100):
        with atomic_database() as conn:
            lock_communication_scope(conn, wid)
            e = conn.execute("SELECT * FROM whatsapp_events WHERE workshop_id = ? AND event_type = 'sync_offen' ORDER BY id LIMIT 1", (wid,)).fetchone()
            if not e:
                return
            inhalt = json.loads(e["payload_json"])
            v = _aktuell(conn, wid)
            d = inhalt["daten"]
            z = _auftraege(conn, v).get(d["feld"]) if v else None
            if (z and v["version"] == inhalt["version"] and not z["generation_offen"]
                    and z["zustand"] not in {"pruefung", "verzicht", "nachweis_fehlt"}
                    and (v["waba_id"], v["phone_number_id"]) == (d["waba"], d["phone"])):
                if d["feld"] == "history":
                    _historie(conn, v, z, d)
                else:
                    _kontakte(conn, v, z, d["kontakte"])
            # Keine zweite dauerhafte Nachrichtenablage: nach Commit bleiben nur Journalkennung und Version.
            conn.execute("UPDATE whatsapp_events SET event_type = 'sync_erledigt', payload_json = ? WHERE id = ?",
                         (_json({"version": inhalt["version"]}), e["id"]))


def _historie(conn, v, z, d):
    if z["zustand"] == "nicht_geteilt":
        if d["medien"] or any("fehler" not in t for t in d["teile"]):
            _zustand(conn, z, "pruefung")
        return
    for t in d["teile"]:
        if "fehler" in t:
            _zustand(conn, z, "nicht_geteilt" if t["fehler"] == [2593109] and not z["fortschritt"] else "pruefung", t["fehler"][0])
            return
        alt = conn.execute("SELECT pruefsumme FROM whatsapp_sync_teile WHERE workshop_id = ? AND version = ? AND phase = ? AND teil = ?",
                           (v["workshop_id"], v["version"], t["phase"], t["teil"])).fetchone()
        if alt:
            if alt["pruefsumme"] != _hash(t):
                _zustand(conn, z, "pruefung")
                return
            continue
        # Richtung und Teilnehmer der gesamten Lieferung vor dem ersten Eintrag prüfen.
        for n in t["nachrichten"]:
            kunde, betrieb = n["kunde"], nummer(v["anzeigenummer"])
            if kunde == betrieb or n["from"] not in {kunde, betrieb} or ("to" in n and n["to"] != (kunde if n["from"] == betrieb else betrieb)):
                _zustand(conn, z, "pruefung")
                return
        for n in t["nachrichten"]:
            if not _nachricht_importieren(conn, v, n):
                _zustand(conn, z, "pruefung")
                return
        conn.execute("INSERT INTO whatsapp_sync_teile (workshop_id, version, phase, teil, pruefsumme) VALUES (?, ?, ?, ?, ?)",
                     (v["workshop_id"], v["version"], t["phase"], t["teil"], _hash(t)))
        z["fortschritt"] = max(z["fortschritt"], t["fortschritt"])
        conn.execute("UPDATE whatsapp_sync SET fortschritt = ? WHERE workshop_id = ? AND version = ? AND art = 'history'",
                     (z["fortschritt"], v["workshop_id"], v["version"]))
    for n in d["medien"]:
        _medium(conn, v, n)
    if _auftraege(conn, v)["history"]["zustand"] == "pruefung":
        return
    teile = conn.execute("SELECT phase, MIN(teil) AS erster, MAX(teil) AS letzter, COUNT(*) AS anzahl FROM whatsapp_sync_teile WHERE workshop_id = ? AND version = ? GROUP BY phase",
                         (v["workshop_id"], v["version"])).fetchall()
    lueckenlos = bool(teile) and all(t["erster"] == 1 and t["letzter"] == t["anzahl"] for t in teile)
    _zustand(conn, z, "abgeschlossen" if z["fortschritt"] == 100 and lueckenlos else "laufend")


def _nachricht_importieren(conn, v, n):
    from app.whatsapp import save_whatsapp_message
    wid, kunde = v["workshop_id"], n["kunde"]
    richtung = "outbound" if n["from"] == nummer(v["anzeigenummer"]) else "inbound"
    alt = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND wa_message_id = ?", (wid, n["id"])).fetchall()
    bezug = {"version": v["version"], "zeit": n["zeit"], "status": n.get("verlauf_status")}
    if alt:
        if len(alt) != 1 or (alt[0]["phone_number_id"], alt[0]["customer_phone"], alt[0]["direction"]) != (v["phone_number_id"], kunde, richtung):
            return False
        zeile = alt[0]
        p = json.loads(zeile["payload_json"])
        p.setdefault("historie", bezug)
        conn.execute("UPDATE whatsapp_messages SET payload_json = ? WHERE id = ?", (_json(p), zeile["id"]))
    else:
        p = {"source": "whatsapp_historie", "historie": bezug}
        kandidaten = [k["message_id"] for k in conn.execute("""SELECT message_id FROM whatsapp_messages
            WHERE workshop_id = ? AND phone_number_id = ? AND customer_phone = ? AND direction = 'outbound'
              AND wa_message_id IS NULL AND (dispatch_state = 'sending' OR status IN ('sent', 'delivered', 'read', 'unknown'))""",
            (wid, v["phone_number_id"], kunde)).fetchall()] if richtung == "outbound" else []
        if kandidaten:
            p["echo_kandidaten"] = kandidaten
        typ = n["type"]
        if typ in MEDIEN:
            p[typ] = n.get(typ, {})
        inhalt = n.get(typ, {})
        verlaufsstatus = {"SENT": "sent", "DELIVERED": "delivered", "READ": "read", "PLAYED": "read",
                          "ERROR": "failed", "PENDING": "unknown"}.get(n.get("verlauf_status"), "unknown")
        save_whatsapp_message(workshop_id=wid, customer_phone=kunde, phone_number_id=v["phone_number_id"],
            direction=richtung, message_type=typ, text=inhalt.get("body", inhalt.get("caption")), wa_message_id=n["id"],
            payload=p, status=verlaufsstatus if richtung == "outbound" else "received",
            message_timestamp=None, processing_state="historie_pruefung" if kandidaten else "complete")
        conn.execute("UPDATE whatsapp_messages SET created_at = ? WHERE workshop_id = ? AND wa_message_id = ? AND direction = ?",
                     (datetime.fromtimestamp(n["zeit"], timezone.utc).isoformat(), wid, n["id"], richtung))
    medium = conn.execute("SELECT * FROM whatsapp_events WHERE workshop_id = ? AND ereignis_schluessel = ?",
                          (wid, f"sync_medium:{v['version']}:{n['id']}")).fetchone()
    if medium:
        _medium(conn, v, json.loads(medium["payload_json"]))
    return True


def _medium(conn, v, n):
    key = f"sync_medium:{v['version']}:{n['id']}"
    zeilen = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND phone_number_id = ? AND wa_message_id = ?",
                         (v["workshop_id"], v["phone_number_id"], n["id"])).fetchall()
    if len(zeilen) == 1:
        z = zeilen[0]
        p = json.loads(z["payload_json"])
        if n["from"] not in {z["customer_phone"], nummer(v["anzeigenummer"])}:
            return
        typ = n["type"]
        if z["message_type"] not in {"media_placeholder", typ}:
            return
        if p.get(typ, {}).get("id") and p[typ]["id"] != n[typ]["id"]:
            _zustand(conn, _auftraege(conn, v)["history"], "pruefung")
            return
        p[typ] = n[typ]
        conn.execute("UPDATE whatsapp_messages SET message_type = ?, payload_json = ? WHERE id = ?", (typ, _json(p), z["id"]))
        conn.execute("DELETE FROM whatsapp_events WHERE workshop_id = ? AND ereignis_schluessel = ?", (v["workshop_id"], key))
    else:
        alt = conn.execute("SELECT payload_json FROM whatsapp_events WHERE workshop_id = ? AND ereignis_schluessel = ?", (v["workshop_id"], key)).fetchone()
        if alt and alt["payload_json"] != _json(n):
            _zustand(conn, _auftraege(conn, v)["history"], "pruefung")
        conn.execute("""INSERT INTO whatsapp_events (workshop_id, phone_number_id, wa_message_id, from_phone, event_type, payload_json, ereignis_schluessel)
            VALUES (?, ?, ?, ?, 'sync_medium', ?, ?) ON CONFLICT(workshop_id, ereignis_schluessel) DO NOTHING""",
            (v["workshop_id"], v["phone_number_id"], n["id"], n["from"], _json(n), key))


def _kontakte(conn, v, z, kontakte):
    konflikt = False
    for k in kontakte:
        alt = conn.execute("SELECT * FROM whatsapp_kontakte WHERE workshop_id = ? AND phone_number_id = ? AND kundenrufnummer = ?",
                           (v["workshop_id"], v["phone_number_id"], k["nummer"])).fetchone()
        if alt:
            if alt["pruefsumme"] == _hash(k):
                continue
            if alt["zeit"] is not None and k["zeit"] is not None and k["zeit"] < alt["zeit"]:
                continue
            if k["zeit"] is None or (alt["zeit"] is not None and k["zeit"] == alt["zeit"]):
                # Unentscheidbare Änderungen dürfen weder Namen noch einen Tombstone überschreiben.
                conn.execute("UPDATE whatsapp_kontakte SET unklar = 1 WHERE workshop_id = ? AND phone_number_id = ? AND kundenrufnummer = ?",
                             (v["workshop_id"], v["phone_number_id"], k["nummer"]))
                konflikt = True
                continue
        unklar = int(k["zeit"] is None)
        konflikt |= bool(unklar)
        conn.execute("""INSERT INTO whatsapp_kontakte
            (workshop_id, phone_number_id, version, kundenrufnummer, name, vorname, entfernt, zeit, unklar, pruefsumme)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(workshop_id, phone_number_id, kundenrufnummer)
            DO UPDATE SET version = excluded.version, name = excluded.name, vorname = excluded.vorname,
                entfernt = excluded.entfernt, zeit = excluded.zeit, unklar = excluded.unklar, pruefsumme = excluded.pruefsumme""",
            (v["workshop_id"], v["phone_number_id"], v["version"], k["nummer"], k["name"], k["vorname"],
             int(k["aktion"] == "remove"), k["zeit"], unklar, _hash(k)))
    _zustand(conn, z, "pruefung" if konflikt else "laufend")
