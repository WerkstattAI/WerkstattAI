"""Synthetische Synchronisierung über signierte Routen, Transaktionen und simuliertes HTTP."""
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import app.db as db
import app.main as main
import app.whatsapp as wa
import app.whatsapp_anschluss as anschluss
import app.whatsapp_synchronisierung as sync
import app.whatsapp_verbindungen as verbindungen
from app.auth import SESSION_COOKIE, create_session_token
from app.whatsapp_medien import medienangaben
import test_whatsapp_ereignisse as grundlage
import test_whatsapp_anschluss as anschlussgrundlage


class SynchronisierungsFaelle:
    postgres = False
    anschliessen = grundlage.EreignisFaelle.anschliessen
    paket = grundlage.EreignisFaelle.paket
    webhook = grundlage.EreignisFaelle.webhook
    nachrichten = grundlage.EreignisFaelle.nachrichten
    kontrolle = grundlage.EreignisFaelle.kontrolle

    def setUp(self):
        grundlage.EreignisFaelle.setUp(self)
        self.config = replace(self.config, whatsapp_signup_config_id="222", whatsapp_signup_origin="https://testserver")
        self.stack.enter_context(patch.object(anschluss, "settings", self.config))
        self.user = {"email": uuid.uuid4().hex + "@example.invalid", "role": "owner", "workshop_id": self.wid}
        with db.atomic_database() as conn:
            conn.execute("INSERT INTO users (email, role, workshop_id, password_hash) VALUES (?, 'owner', ?, 'synthetisch')",
                         (self.user["email"], self.wid))
            self.v = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,)).fetchone())
            # Die Basisklasse simuliert einen Altanschluss vor dem App-Start. Hier gilt ein frischer geprüfter Signup.
            conn.execute("DELETE FROM whatsapp_sync WHERE workshop_id = ?", (self.wid,))
            sync.anlegen(conn, self.v, time.time() - 60)
        self.cookie = create_session_token(self.user)
        self.client.cookies.set(SESSION_COOKIE, self.cookie)
        self.client.headers["origin"] = "https://testserver"
        self.aufrufe = []
        self.vor_http = None
        self.http_fehler = None
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open", side_effect=self.http))

    def http(self, anfrage, *args, **kwargs):
        self.assertIsNone(db._TRANSACTION_CONNECTION.get(), "Netzaufruf ohne Datenbanksperre")
        self.assertEqual(anfrage.full_url, f"https://graph.facebook.com/v26.0/{self.nummer}/smb_app_data")
        self.assertEqual(anfrage.get_method(), "POST")
        d = json.loads(anfrage.data)
        self.assertEqual(d["messaging_product"], "whatsapp")
        self.aufrufe.append(d["sync_type"])
        if self.vor_http:
            self.vor_http(d["sync_type"])
        if self.http_fehler:
            raise self.http_fehler
        return io.BytesIO(json.dumps({"messaging_product": "whatsapp", "request_id": "synthetisch-" + d["sync_type"]}).encode())

    def route(self, aktion="fortsetzen", erwartet=200):
        a = self.client.post("/dashboard/whatsapp/synchronisierung/" + aktion, json={"workshop_id": self.wid})
        self.assertEqual(a.status_code, erwartet, a.text)
        return a.json()

    def zustand(self, art="history"):
        with db.get_conn() as conn:
            return dict(conn.execute("SELECT * FROM whatsapp_sync WHERE workshop_id = ? AND version = ? AND art = ?",
                                    (self.wid, self.v["version"], art)).fetchone())

    def nachricht(self, mid="wamid.historie", typ="text", ausgehend=False):
        n = {"id": mid, "from": self.betrieb if ausgehend else self.kunde, "timestamp": str(int(time.time()) - 120), "type": typ}
        if typ == "text":
            n[typ] = {"body": "Synthetischer Verlauf"}
        elif typ != "media_placeholder":
            n[typ] = {"id": "99999", "mime_type": "image/jpeg", "caption": "Prüfbild", "url": "https://fremd.invalid/geheim"}
        return n

    def historie(self, *, teil=1, phase=0, fortschritt=100, nachrichten=None):
        return self.paket("history", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer},
            "history": [{"metadata": {"phase": phase, "chunk_order": teil, "progress": fortschritt},
                         "threads": [{"id": self.kunde, "messages": [self.nachricht()] if nachrichten is None else nachrichten}]}]})

    def ablehnung(self):
        return self.paket("history", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer},
            "history": [{"errors": [{"code": 2593109, "message": "nicht speichern"}]}]})

    def kontakt(self, aktion="add", zeit=None, name="Prüfkontakt"):
        return self.paket("smb_app_state_sync", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer},
            "state_sync": [{"type": "contact", "action": aktion, "contact": {"phone_number": self.kunde, **({"full_name": name} if aktion == "add" else {})},
                "metadata": {"timestamp": int(time.time()) - 10 if zeit is None else zeit}}]})

    def medium(self):
        return self.paket("history", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer},
            "messages": [self.nachricht(typ="image")]})

    def test_annahme_ist_weder_zustimmung_noch_leere_historie(self):
        a = self.route()
        self.assertFalse(a["technisch_bereit"])
        self.assertEqual(self.aufrufe, ["smb_app_state_sync", "history"])
        self.assertEqual(self.zustand()["zustand"], "angenommen")
        self.assertEqual(self.nachrichten(), [])
        self.route()
        self.assertEqual(len(self.aufrufe), 2)
        self.assertFalse(self.route("status")["technisch_bereit"])

    def test_widerspruechliche_http_annahme_ist_kein_nachweis(self):
        with patch("urllib.request.OpenerDirector.open", return_value=io.BytesIO(
                b'{"messaging_product":"whatsapp","request_id":"synthetisch","error":{"code":1}}')):
            sync.schritt(self.cookie, self.wid, "https://testserver", "history")
        self.assertEqual(self.zustand()["zustand"], "unklar")
        self.assertIsNone(self.zustand()["request_id"])

    def test_historie_ohne_heutige_wirkungen_auch_junge_zeit(self):
        self.route()
        vorher = self.kontrolle()
        lieferung = self.historie()
        with patch.object(main, "process_chat_message") as chat, patch.object(main, "send_whatsapp_text_message") as senden:
            self.webhook(lieferung)
            self.webhook(lieferung)
            chat.assert_not_called()
            senden.assert_not_called()
        db.init_db()
        self.assertEqual(self.kontrolle(), vorher)
        n = self.nachrichten()[0]
        self.assertTrue(n["historisch"])
        self.assertIsNone(n["ticket_id"])
        self.assertFalse(wa.whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=self.kunde)["service_window_open"])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM tickets WHERE workshop_id = ?", (self.wid,)).fetchone()["n"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM conversation_sessions WHERE workshop_id = ?", (self.wid,)).fetchone()["n"], 0)
        pruefstatus = sync.status(self.wid)
        self.assertTrue(pruefstatus["technisch_bereit"], pruefstatus)
        self.assertTrue(anschluss.automatik_gesperrt(self.wid))
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["coexistence_bereit"], 0)

    def test_leere_lieferung_mit_abschluss_belegt_keine_fehlenden_phasen(self):
        self.route()
        self.webhook(self.historie(phase=2, nachrichten=[]))
        self.assertEqual(self.nachrichten(), [])
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        self.assertFalse(sync.status(self.wid)["kontakte_vollstaendig"])

    def test_historische_zeit_und_status_ohne_erfundenen_versanderfolg(self):
        self.route()
        neu = self.nachricht(mid="wamid.neuer", ausgehend=True)
        alt = self.nachricht(mid="wamid.aelter", ausgehend=True)
        alt["timestamp"] = str(int(neu["timestamp"]) - 3600)
        alt["history_context"] = {"status": "ERROR"}
        self.webhook(self.historie(nachrichten=[neu, alt]))
        n = self.nachrichten()
        self.assertEqual([m["wa_message_id"] for m in n], ["wamid.aelter", "wamid.neuer"])
        self.assertEqual([m["status"] for m in n], ["failed", "unknown"])
        self.assertLess(n[0]["created_at"], n[1]["created_at"])
        self.assertEqual(self.kontrolle()["revision"], 0)

    def test_phase_zwei_allein_kein_abschluss(self):
        self.route()
        self.webhook(self.historie(phase=2, fortschritt=90))
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_verzicht_meta_und_lokal_ohne_zugangswiderruf(self):
        self.route()
        self.webhook(self.ablehnung())
        self.assertEqual(self.zustand()["zustand"], "nicht_geteilt")
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["autorisierung"], "bestaetigt")

    def test_lokaler_verzicht_verhindert_initialisierung_und_import(self):
        self.route("verzicht")
        self.route()
        self.webhook(self.historie())
        self.assertEqual(self.aufrufe, ["smb_app_state_sync"])
        self.assertEqual(self.nachrichten(), [])
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_vertauschte_teile_luecken_monotonie_und_widerspruch(self):
        self.route()
        self.webhook(self.historie(teil=3, nachrichten=[]))
        self.webhook(self.historie(teil=1, fortschritt=10))
        self.assertEqual(self.zustand()["fortschritt"], 100)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        self.webhook(self.historie(teil=2, fortschritt=50, nachrichten=[]))
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        self.webhook(self.historie(teil=1, fortschritt=10, nachrichten=[]))
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_medien_beide_reihenfolgen_ohne_payload_url(self):
        self.route()
        self.webhook(self.medium())
        self.assertEqual(self.nachrichten(), [])
        self.webhook(self.historie(nachrichten=[self.nachricht(typ="media_placeholder")]))
        self.webhook(self.medium())
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertEqual(medienangaben(self.nachrichten()[0])["id"], "99999")
        self.assertNotIn("fremd.invalid", self.nachrichten()[0]["payload_json"])
        self.assertEqual(sync.status(self.wid)["medien_offen"], 0)
        self.webhook(self.historie(teil=2, nachrichten=[self.nachricht(mid="wamid.spaeter", typ="media_placeholder", ausgehend=True)]))
        self.assertEqual(sync.status(self.wid)["medien_offen"], 1)
        p = self.medium()
        p["entry"][0]["changes"][0]["value"]["messages"][0]["id"] = "wamid.spaeter"
        self.webhook(p)
        self.assertEqual(sync.status(self.wid)["medien_offen"], 0)
        self.assertIsNotNone(medienangaben(self.nachrichten()[1]))

    def test_bekanntes_echo_nach_freigabe_und_live_werden_nur_ergaenzt(self):
        self.route()
        self.webhook(self.paket())
        vorher = db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde, mode="assistant")
        self.webhook(self.historie(nachrichten=[self.nachricht(mid="wamid.telefon", ausgehend=True)]))
        self.webhook(self.paket())
        self.assertEqual(self.kontrolle(), vorher)
        self.assertEqual(len(self.nachrichten()), 1)
        wa.save_whatsapp_message(workshop_id=self.wid, customer_phone=self.kunde, phone_number_id=self.nummer,
            wa_message_id="wamid.live", direction="inbound", payload={"source": "webhook"})
        self.webhook(self.historie(teil=2, nachrichten=[self.nachricht(mid="wamid.live")]))
        self.assertEqual(len(self.nachrichten()), 2)
        self.assertFalse(self.nachrichten()[-1]["historisch"])

    def test_import_vor_live_oeffnet_auch_bei_wiederzustellung_keine_automation(self):
        self.route()
        self.webhook(self.historie())
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))
        wert = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer}, "messages": [self.nachricht()]}
        with patch.object(main, "process_chat_message") as chat:
            self.webhook(self.paket("messages", wert))
            chat.assert_not_called()
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertFalse(wa.whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=self.kunde)["service_window_open"])

    def test_kontakte_aendern_entfernen_verspaetet_und_gleichstand(self):
        self.route()
        zeit = int(time.time()) - 30
        self.webhook(self.kontakt(zeit=zeit))
        self.webhook(self.kontakt(zeit=zeit + 1, name="Neuer Name"))
        self.webhook(self.kontakt("remove", zeit + 2))
        self.webhook(self.kontakt(zeit=zeit + 1))
        self.webhook(self.kontakt(zeit=zeit + 2))
        with db.get_conn() as conn:
            k = conn.execute("SELECT * FROM whatsapp_kontakte WHERE workshop_id = ?", (self.wid,)).fetchone()
            self.assertEqual((k["entfernt"], k["name"], k["unklar"]), (1, None, 1))
        self.assertEqual(self.zustand("smb_app_state_sync")["zustand"], "pruefung")
        self.assertEqual(self.nachrichten(), [])

    def test_kontakt_sonderzeit_ist_keine_neueste_aenderung(self):
        self.route()
        self.webhook(self.kontakt("remove"))
        self.webhook(self.kontakt(zeit=-1))
        with db.get_conn() as conn:
            k = conn.execute("SELECT * FROM whatsapp_kontakte WHERE workshop_id = ?", (self.wid,)).fetchone()
            self.assertEqual((k["entfernt"], k["unklar"]), (1, 1))

    def test_timeout_reservierung_kein_blinder_retry_und_keine_fristverlaengerung(self):
        self.http_fehler = TimeoutError()
        vorher = self.zustand()["frist"]
        self.route()
        self.route()
        db.init_db()
        self.route()
        self.assertEqual(len(self.aufrufe), 2)
        self.assertEqual(self.zustand()["zustand"], "unklar")
        self.assertEqual(self.zustand()["frist"], vorher)
        self.webhook(self.historie())
        self.assertEqual(self.zustand()["zustand"], "abgeschlossen")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_crash_nach_reservierung_bleibt_dauerhaft_unklar(self):
        def absturz(art):
            raise RuntimeError("Synthetischer Prozessabbruch")
        self.vor_http = absturz
        self.route(erwartet=400)
        self.assertEqual(self.zustand("smb_app_state_sync")["zustand"], "reserviert")
        self.vor_http = None
        db.init_db()
        self.route()
        self.assertEqual(self.aufrufe.count("smb_app_state_sync"), 1)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_frist_und_quote_saubere_fehler(self):
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_sync SET frist = 1 WHERE workshop_id = ? AND art = 'history'", (self.wid,))
        self.http_fehler = urllib.error.HTTPError("https://graph.facebook.com", 400, "nicht speichern", {},
            io.BytesIO(b'{"error":{"code":2593107,"message":"nicht speichern"}}'))
        self.route()
        self.assertEqual(self.zustand()["zustand"], "frist")
        self.assertEqual(self.zustand("smb_app_state_sync")["zustand"], "quote")
        self.assertNotIn("nicht speichern", json.dumps(self.route("status")))

    def test_callback_vor_http_antwort_und_spaeter_fehler_nicht_rueckwaerts(self):
        self.direkt = True
        def callback(art):
            if art == "history":
                self.webhook(self.historie())
                raise TimeoutError()
        self.vor_http = callback
        self.route()
        self.assertEqual(self.zustand()["zustand"], "abgeschlossen")
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_callback_ablehnung_vor_erfolgreicher_http_antwort(self):
        self.direkt = True
        self.vor_http = lambda art: self.webhook(self.ablehnung()) if art == "history" else None
        self.route()
        self.assertEqual(self.zustand()["zustand"], "nicht_geteilt")

    def test_parallele_initialisierung_genau_eine_reservierung(self):
        gestartet, weiter = threading.Event(), threading.Event()
        def halten(art):
            gestartet.set()
            self.assertTrue(weiter.wait(20))
        self.vor_http = halten
        args = (self.cookie, self.wid, "https://testserver", "history")
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(sync.schritt, *args)
            self.assertTrue(gestartet.wait(20))
            try:
                b = pool.submit(sync.schritt, *args)
                self.assertFalse(b.result(20)["technisch_bereit"])
            finally:
                weiter.set()
            a.result(20)
        self.assertEqual(self.aufrufe, ["history"])

    def test_parallele_doppelte_chunks_und_neustart(self):
        self.route()
        self.direkt = True
        p = self.historie()
        barriere = threading.Barrier(2)
        def liefern():
            barriere.wait(20)
            self.webhook(p)
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(liefern), pool.submit(liefern)
            a.result(30)
            b.result(30)
        self.assertEqual(len(self.nachrichten()), 1)
        # Offenes Journal in einem frischen Prozess fortsetzen, ohne neue Meta-Anforderung.
        p = self.historie(teil=2, nachrichten=[self.nachricht(mid="wamid.neustart")])
        eintrag = p["entry"][0]
        daten, _ = sync.validiere("history", eintrag, eintrag["changes"][0]["value"])
        sync.erfasse(daten)
        umgebung = os.environ.copy()
        umgebung.update(DATABASE_URL=db.settings.database_url or "", APP_ENV="test")
        skript = "import sys; from app.whatsapp_synchronisierung import verarbeite_offene; verarbeite_offene(sys.argv[1])"
        lauf = subprocess.run([sys.executable, "-c", skript, self.wid], env=umgebung, capture_output=True, text=True, timeout=40)
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertEqual(len(self.nachrichten()), 2)

    def test_widerruf_waehrend_http_und_neuanschluss_keine_alte_freigabe(self):
        def widerrufen(art):
            verbindungen.widerrufe_verbindung(self.wid, erwartete_version=self.v["version"])
        self.vor_http = widerrufen
        sync.schritt(self.cookie, self.wid, "https://testserver", "history")
        self.assertFalse(sync.status(self.wid)["autorisiert"])
        self.anschliessen()
        with db.atomic_database() as conn:
            v = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,)).fetchone())
            sync.anlegen(conn, v, time.time())
        self.webhook(self.historie())
        self.webhook(self.kontakt())
        self.assertEqual(self.nachrichten(), [])
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        self.assertTrue(all(s["zustand"] == "pruefung" for s in sync.status(self.wid)["schritte"]))

    def test_widerruf_vor_lokaler_importfortsetzung(self):
        self.route()
        p = self.historie()["entry"][0]
        d, _ = sync.validiere("history", p, p["changes"][0]["value"])
        sync.erfasse(d)
        verbindungen.widerrufe_verbindung(self.wid, erwartete_version=self.v["version"])
        sync.verarbeite_offene(self.wid)
        self.assertEqual(self.nachrichten(), [])

    def test_fremde_zuordnung_und_gemischter_widerruf_vor_import(self):
        self.route()
        p = self.historie()
        p["entry"][0]["id"] = "998877"
        self.webhook(p)
        self.assertEqual(self.nachrichten(), [])
        p = self.historie()
        p["entry"][0]["changes"].append({"field": "account_update", "value": {"event": "ACCOUNT_OFFBOARDED"}})
        self.webhook(p)
        self.assertEqual(self.nachrichten(), [])
        self.assertFalse(sync.status(self.wid)["autorisiert"])

    def test_payload_typen_und_importgrenzen(self):
        self.route()
        for code in (True, -1, 2 ** 63):
            p = self.ablehnung()
            p["entry"][0]["changes"][0]["value"]["history"][0]["errors"][0]["code"] = code
            self.webhook(p, erwartet=422)
        for wert in (None, "falsch", [1]):
            p = self.historie()
            p["entry"][0]["changes"][0]["value"]["history"][0]["threads"] = wert
            self.webhook(p, erwartet=422)
        p = self.historie(nachrichten=[self.nachricht(mid=f"wamid.{i}") for i in range(110)])
        self.webhook(p)
        self.assertEqual(len(wa.list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.kunde, limit=200)), 110)
        p = self.historie(nachrichten=[self.nachricht()] * 5001)
        self.webhook(p, erwartet=413)

    def test_sync_routen_aktuelle_rechte_origin_sitzung(self):
        self.client.headers["origin"] = "https://fremd.invalid"
        self.route(erwartet=403)
        self.client.headers["origin"] = "https://testserver"
        with db.atomic_database() as conn:
            conn.execute("UPDATE users SET role = 'staff' WHERE email = ?", (self.user["email"],))
        a = self.client.post("/dashboard/whatsapp/synchronisierung/status", json={"workshop_id": self.wid}, follow_redirects=False)
        self.assertIn(a.status_code, (303, 403, 409))
        self.assertEqual(self.aufrufe, [])

    def test_isolierte_flagge_und_zurueckgehaltene_eingaenge(self):
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))
        self.assertTrue(anschluss.automatik_gesperrt(self.wid))
        n = wa.WhatsAppInboundMessage(self.nummer, self.betrieb, self.kunde, "wamid.zurueck", str(int(time.time())), "text", "Hallo", {}, self.konto)
        with db.atomic_database() as conn:
            self.assertTrue(anschluss.eingang_zurueckhalten(conn, self.wid, n))
        self.route()
        self.webhook(self.historie())
        self.assertFalse(anschluss.automatik_gesperrt(self.wid))
        with db.atomic_database() as conn:
            self.assertTrue(anschluss.eingang_zurueckhalten(conn, self.wid, n))

    def test_migration_erfindet_keinen_zeitnachweis(self):
        with db.atomic_database() as conn:
            conn.execute("DELETE FROM whatsapp_sync WHERE workshop_id = ?", (self.wid,))
        db.init_db()
        self.assertIsNone(self.zustand()["frist"])
        self.assertEqual(self.zustand()["zustand"], "nachweis_fehlt")
        self.route(erwartet=409)
        self.assertEqual(self.aufrufe, [])

    def test_zwei_werkstaetten_gleicher_kunde_und_fremder_medienzugriff(self):
        self.route()
        self.webhook(self.historie(nachrichten=[self.nachricht(typ="media_placeholder")]))
        self.webhook(self.medium())
        wid = "sync-zweit-" + uuid.uuid4().hex
        phone = str(uuid.uuid4().int)[:16]
        with db.atomic_database() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, 'Zweite Prüfwerkstatt')", (wid,))
        self.anschliessen(wid, phone)
        with db.atomic_database() as conn:
            v = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone())
            sync.anlegen(conn, v, time.time() - 30)
            conn.execute("UPDATE whatsapp_sync SET zustand = 'angenommen', request_id = 'synthetisch-zweit' WHERE workshop_id = ?", (wid,))
        p = self.historie()
        p["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = phone
        self.webhook(p)
        p = self.kontakt(name="Zweite Werkstatt")
        p["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = phone
        self.webhook(p)
        self.webhook(self.kontakt(name="Erste Werkstatt"))
        with db.get_conn() as conn:
            namen = {z["workshop_id"]: z["name"] for z in conn.execute("SELECT * FROM whatsapp_kontakte WHERE kundenrufnummer = ?", (self.kunde,)).fetchall()}
            fremd = conn.execute("SELECT id FROM whatsapp_messages WHERE workshop_id = ?", (wid,)).fetchone()["id"]
        self.assertEqual((namen[self.wid], namen[wid]), ("Erste Werkstatt", "Zweite Werkstatt"))
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertEqual(len(wa.list_whatsapp_messages(workshop_id=wid, customer_phone=self.kunde)), 1)
        a = self.client.post("/dashboard/whatsapp/synchronisierung/status", json={"workshop_id": wid})
        self.assertEqual(a.status_code, 409)
        a = self.client.get(f"/dashboard/whatsapp/medien/{fremd}")
        self.assertEqual(a.status_code, 404)

    def test_importierter_versand_mit_spaeterer_provider_id_keine_zweite_aktion(self):
        self.route()
        # Eine echte Versandreservierung besitzt bereits eine Gesprächskontrolle.
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde,
            mode="assistant", ausdrueckliche_freigabe=False)
        wa.save_whatsapp_message(workshop_id=self.wid, phone_number_id=self.nummer, customer_phone=self.kunde,
            direction="outbound", status="unknown", dispatch_state="sending", message_id="synthetischer-versuch", payload={})
        with db.get_conn() as conn:
            original = dict(conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND message_id = 'synthetischer-versuch'", (self.wid,)).fetchone())
        self.webhook(self.historie(nachrichten=[self.nachricht(ausgehend=True)]))
        self.assertEqual(len(self.nachrichten()), 2)
        vorher = self.kontrolle()
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=original["message_id"], status="sent",
            wa_message_id="wamid.historie", expected_dispatch_started_at=original["dispatch_started_at"])
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertEqual(self.kontrolle(), vorher)
        daten = json.loads(self.nachrichten()[0]["payload_json"])
        self.assertIn("historie", daten)
        self.assertNotIn("echo_bestaetigt", daten)

    def test_import_gegen_widerruf_unter_gemeinsamer_sperre(self):
        self.route()
        self.direkt = True
        drin, weiter = threading.Event(), threading.Event()
        original = sync._nachricht_importieren
        def halten(*args):
            drin.set()
            self.assertTrue(weiter.wait(20))
            return original(*args)
        with patch.object(sync, "_nachricht_importieren", side_effect=halten), ThreadPoolExecutor(2) as pool:
            a = pool.submit(self.webhook, self.historie())
            self.assertTrue(drin.wait(20))
            b = pool.submit(verbindungen.widerrufe_verbindung, self.wid, erwartete_version=self.v["version"])
            weiter.set()
            a.result(30)
            b.result(30)
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertFalse(sync.status(self.wid)["autorisiert"])
        self.webhook(self.historie(teil=2, nachrichten=[self.nachricht(mid="wamid.zu-spaet")]))
        self.assertEqual(len(self.nachrichten()), 1)

    def test_migration_wiederholt_bewahrt_luecken_und_frist(self):
        self.route()
        self.webhook(self.historie(teil=2))
        vorher = self.zustand()
        db.init_db()
        db.init_db()
        self.assertEqual(self.zustand(), vorher)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_unbekannte_richtung_und_uebergrosse_lieferung_ohne_wirkung(self):
        self.route()
        n = self.nachricht()
        n["from"] = "499999999"
        self.webhook(self.historie(nachrichten=[n]))
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertEqual(self.nachrichten(), [])
        self.webhook({"object": "whatsapp_business_account", "entry": [], "fuellung": "x" * (4 * 1024 * 1024)}, erwartet=413)

    def test_importierte_kontakte_im_werkstattgebundenen_export(self):
        from app.privacy_data import read_records, select_records
        self.route()
        self.webhook(self.kontakt())
        with db.get_conn() as conn:
            daten = select_records(read_records(conn, self.wid), {"kind": "phone", "value": self.kunde})
        self.assertEqual(len(daten["whatsapp_kontakte"]), 1)
        self.assertEqual(daten["whatsapp_kontakte"][0]["name"], "Prüfkontakt")


class SQLiteSynchronisierung(SynchronisierungsFaelle, unittest.TestCase):
    pass


@unittest.skipUnless(os.environ.get("WERKSTATTAI_TEST_POSTGRES_URL"), "Eigene PostgreSQL-Prüfdatenbank erforderlich")
class PostgreSQLSynchronisierung(SynchronisierungsFaelle, unittest.TestCase):
    postgres = True


class AnschlussZurSynchronisierung(unittest.TestCase):
    setUp = anschlussgrundlage.AnschlussTests.setUp
    post = anschlussgrundlage.AnschlussTests.post
    start = anschlussgrundlage.AnschlussTests.start
    abschluss = anschlussgrundlage.AnschlussTests.abschluss

    def test_verifizierter_anschluss_dauerhafter_auftrag_ohne_alte_signup_sitzung(self):
        beginn = time.time()
        self.assertEqual(self.abschluss(self.start()).json()["zustand"], "abgeschlossen")
        with db.atomic_database() as conn:
            zeilen = conn.execute("SELECT * FROM whatsapp_sync WHERE workshop_id = ?", (self.wid,)).fetchall()
            self.assertEqual(len(zeilen), 2)
            for z in zeilen:
                self.assertEqual((z["version"], z["waba_id"], z["phone_number_id"], z["zustand"]), (2, "333", "444", "offen"))
                self.assertLessEqual(abs(z["beginn"] - beginn), 2)
                self.assertEqual(z["frist"], z["beginn"] + 86400)
            conn.execute("UPDATE whatsapp_anschlussversuche SET sitzung_hash = 'alte-sitzung', ablauf = 0 WHERE workshop_id = ?", (self.wid,))
        self.meta.antworten[("POST", "444/smb_app_data")] = {"messaging_product": "whatsapp", "request_id": "synthetischer-sync-auftrag"}
        a = self.client.post("/dashboard/whatsapp/synchronisierung/fortsetzen", json={"workshop_id": self.wid})
        self.assertEqual(a.status_code, 200, a.text)
        self.assertEqual(self.meta.aufrufe.count(("POST", "444/smb_app_data")), 2)
        self.assertFalse(a.json()["technisch_bereit"])
        self.assertFalse(a.json()["betrieb_bereit"])
