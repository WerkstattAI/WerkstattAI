"""Anschluss, Rollen, Fehler und Automatik mit isoliertem SQLite und simuliertem HTTP."""
import io
import json
import threading
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import test_whatsapp_verbindungen as verbindungspruefung
import app.db as db
import app.main as main
import app.whatsapp_anschluss as anschluss
import app.whatsapp_verbindungen as verbindungen
from app.auth import SESSION_COOKIE, create_session_token
from app.whatsapp_verbindungen import VerbindungsFehler, verbindungsstatus, widerrufe_verbindung, zugang_fuer_werkstatt
from app.whatsapp import (WhatsAppInboundMessage, prepare_whatsapp_inbound, deliver_prepared_whatsapp_reply,
    save_whatsapp_message, whatsapp_customer_service_window_for_phone, build_signature)
from anschlussdaten import MetaSimulation


class AnschlussTests(unittest.TestCase):
    def setUp(self):
        verbindungspruefung.VerbindungsTests.setUp(self)
        self.config = replace(self.konfiguration, whatsapp_app_id="111", whatsapp_signup_config_id="222",
            whatsapp_signup_origin="https://testserver", whatsapp_app_secret="synthetisches-app-geheimnis",
            whatsapp_signup_graph_version="v26.0")
        self.stack.enter_context(patch.object(anschluss, "settings", self.config))
        self.user = {"email": "anschluss@example.invalid", "role": "owner", "workshop_id": self.wid}
        with db.get_conn() as conn:
            conn.execute("INSERT INTO users (email, role, workshop_id, password_hash) VALUES (?, ?, ?, ?)",
                         (self.user["email"], "owner", self.wid, "synthetischer-passworthash"))
            conn.commit()
        self.cookie = create_session_token(self.user)
        self.client = self.stack.enter_context(TestClient(main.app, base_url="https://testserver"))
        self.client.cookies.set(SESSION_COOKIE, self.cookie)
        self.client.headers["origin"] = self.config.whatsapp_signup_origin
        self.meta = MetaSimulation()
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open", side_effect=self.meta.open))

    def post(self, aktion, **daten):
        return self.client.post("/dashboard/whatsapp/verbinden/" + aktion,
                                json={"workshop_id": self.wid, **daten}, follow_redirects=False)

    def start(self):
        antwort = self.post("start")
        self.assertEqual(antwort.status_code, 200, antwort.text)
        return antwort.json()["kennung"]

    def pruefe_zustand(self, antwort, erwartet):
        # Nur synthetische Testantworten; auch bei Regressionen Zugangswerte entfernen.
        inhalt = antwort.text
        anfrage = json.loads(antwort.request.content or "{}")
        for geheimnis in (self.cookie, self.meta.token, self.config.whatsapp_app_secret,
                          anfrage.get("code"), anfrage.get("kennung")):
            if geheimnis:
                inhalt = inhalt.replace(geheimnis, "[ENTFERNT]")
        diagnose = f"HTTP {antwort.status_code}; Antwort: {inhalt[:1500]}"
        self.assertEqual(antwort.status_code, 200, diagnose)
        try:
            daten = antwort.json()
        except ValueError:
            self.fail(diagnose)
        self.assertIsInstance(daten, dict, diagnose)
        self.assertEqual(daten.get("zustand"), erwartet, diagnose)

    def abschluss(self, kennung, **aenderungen):
        daten = dict(kennung=kennung, code="synthetischer-einmalcode-" + kennung, waba_id="333", phone_number_id="444",
            meta_ursprung="https://www.facebook.com", ereignis="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING")
        daten.update(aenderungen)
        return self.post("abschluss", **daten)

    def dienst(self, kennung):
        return anschluss.abschliessen(self.cookie, self.wid, self.config.whatsapp_signup_origin, kennung,
            code="synthetischer-einmalcode-" + kennung, waba_id="333", phone_number_id="444",
            meta_ursprung="https://www.facebook.com", ereignis="FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING")

    def test_erfolg_kette_chiffrat_version_und_gesperrte_betriebsbereitschaft(self):
        kennung = self.start()
        antwort = self.abschluss(kennung)
        self.assertEqual(antwort.status_code, 200, antwort.text)
        self.assertEqual(antwort.json()["zustand"], "abgeschlossen")
        status = verbindungsstatus(self.wid)
        self.assertEqual((status["version"], status["autorisierung"], status["coexistence_bereit"]), (2, "bestaetigt", 0))
        self.assertEqual(zugang_fuer_werkstatt(self.wid).token, self.meta.token)
        self.assertTrue(anschluss.automatik_gesperrt(self.wid))
        self.assertEqual(self.meta.aufrufe.count(("GET", "oauth/access_token")), 1)
        self.assertEqual(self.meta.aufrufe.count(("POST", "333/subscribed_apps")), 1)
        self.assertFalse(any("register" in pfad for _, pfad in self.meta.aufrufe))
        with db.get_conn() as conn:
            gespeichert = repr([dict(z) for z in conn.execute("SELECT * FROM whatsapp_anschlussversuche").fetchall()])
        for geheimnis in (kennung, self.cookie, self.meta.token, "synthetischer-einmalcode"):
            self.assertNotIn(geheimnis, gespeichert + antwort.text)

    def test_v4_coexistence_ohne_browser_nummer_wird_serverseitig_eindeutig_aufgeloest(self):
        antwort = self.abschluss(self.start(), phone_number_id=None)
        self.assertEqual(antwort.json()["zustand"], "abgeschlossen")
        self.meta.nummern = [{"id": "444"}, {"id": "555"}]
        antwort = self.abschluss(self.start(), phone_number_id=None)
        self.assertEqual(antwort.json()["zustand"], "fehlgeschlagen")

    def test_abbruch_ablauf_gefaelschte_und_wiederverwendete_kennung(self):
        kennung = self.start()
        self.pruefe_zustand(self.post("abbruch", kennung=kennung), "abgebrochen")
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        self.assertEqual(self.abschluss("x" * 43).status_code, 409)
        kennung = self.start()
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_anschlussversuche SET ablauf = 0")
            conn.commit()
        self.pruefe_zustand(self.post("status", kennung=kennung), "abgelaufen")
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        self.assertEqual(self.meta.aufrufe, [])
        kennung = self.start()
        self.pruefe_zustand(self.abschluss(kennung), "abgeschlossen")
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        self.assertEqual(self.meta.aufrufe.count(("GET", "oauth/access_token")), 1)

    def test_beide_granularen_rechte_verlangen_passende_oder_ausdruecklich_alle_ziele(self):
        for recht in self.meta.debug["scopes"]:
            for ziele in (["333"], [333], ["999", "333"], "uneingeschraenkt"):
                with self.subTest(recht=recht, ziele=ziele):
                    self.meta.debug["granular_scopes"] = [
                        {"scope": r, "target_ids": ["333"]} for r in self.meta.debug["scopes"]]
                    eintrag = next(r for r in self.meta.debug["granular_scopes"] if r["scope"] == recht)
                    if ziele == "uneingeschraenkt":
                        del eintrag["target_ids"]
                    else:
                        eintrag["target_ids"] = ziele
                    self.pruefe_zustand(self.abschluss(self.start()), "abgeschlossen")
                    self.assertEqual(verbindungsstatus(self.wid)["coexistence_bereit"], 0)

    def test_fremde_leere_fehlende_und_fehlerhafte_granulare_rechte_stoppen_vor_abonnement(self):
        for recht in self.meta.debug["scopes"]:
            for ziele in (["999"], [], None, "333", {"333": True}, [True], [False], [0], [-333],
                          [333.0], ["333", None], ["333", {}], "fehlend", "widerspruechlich"):
                with self.subTest(recht=recht, ziele=ziele):
                    self.meta.aufrufe.clear()
                    self.meta.debug["granular_scopes"] = [
                        {"scope": r, "target_ids": ["333"]} for r in self.meta.debug["scopes"]]
                    eintrag = next(r for r in self.meta.debug["granular_scopes"] if r["scope"] == recht)
                    if ziele == "fehlend":
                        self.meta.debug["granular_scopes"].remove(eintrag)
                    elif ziele == "widerspruechlich":
                        self.meta.debug["granular_scopes"].append({"scope": recht, "target_ids": []})
                    else:
                        eintrag["target_ids"] = ziele
                    self.pruefe_zustand(self.abschluss(self.start()), "fehlgeschlagen")
                    self.assertEqual(self.meta.aufrufe, [("GET", "oauth/access_token"), ("GET", "debug_token")])
                    self.assertFalse(verbindungsstatus(self.wid)["zugang_gespeichert"])

    def test_falsche_urspruenge_und_nicht_coexistence_ereignis(self):
        kennung = self.start()
        for ursprung in ("https://facebook.com.evil.invalid", "https://evilfacebook.com", "null", "https://www.facebook.com:444"):
            with self.subTest(ursprung=ursprung):
                self.assertEqual(self.abschluss(kennung, meta_ursprung=ursprung).status_code, 409)
        self.assertEqual(self.abschluss(kennung, ereignis="FINISH").status_code, 409)
        self.client.headers.pop("origin")
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        self.client.headers["origin"] = "https://evil.invalid"
        self.assertEqual(self.post("start").status_code, 403)
        self.assertEqual(self.meta.aufrufe, [])

    def test_fremde_waba_nummer_und_gefaelschte_coexistence_werden_abgelehnt(self):
        for daten in ({"waba_id": "999"}, {"phone_number_id": "999"}, {"waba_id": "333/../../me"}):
            with self.subTest(daten=daten):
                antwort = self.abschluss(self.start(), **daten)
                self.assertTrue(antwort.status_code == 409 or antwort.json()["zustand"] == "fehlgeschlagen")
                self.assertFalse(verbindungsstatus(self.wid)["versand_bereit"])
        self.meta.nummer["is_on_biz_app"] = False
        self.assertEqual(self.abschluss(self.start()).json()["zustand"], "fehlgeschlagen")
        self.assertNotIn(("POST", "333/subscribed_apps"), self.meta.aufrufe)

    def test_ungueltiger_token_falsche_app_und_rechte(self):
        original = self.meta.debug.copy()
        for aenderung in ({"is_valid": False}, {"app_id": "999"}, {"scopes": []}, {"granular_scopes": []}, {"expires_at": 1}):
            with self.subTest(aenderung=aenderung):
                self.meta.debug = {**original, **aenderung}
                self.assertEqual(self.abschluss(self.start()).json()["zustand"], "fehlgeschlagen")
        self.assertNotIn(("POST", "333/subscribed_apps"), self.meta.aufrufe)

    def test_zweiter_nutzer_und_fremde_werkstatt(self):
        kennung = self.start()
        andere = {"email": "anderer@example.invalid", "role": "owner", "workshop_id": self.wid}
        with db.get_conn() as conn:
            conn.execute("INSERT INTO users (email, password_hash, workshop_id, role) VALUES (?, 'synthetisch', ?, 'owner')",
                         (andere["email"], self.wid))
            conn.commit()
        self.client.cookies.set(SESSION_COOKIE, create_session_token(andere))
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        self.assertEqual(self.post("start", workshop_id="kunde-b").status_code, 409)
        self.assertEqual(self.meta.aufrufe, [])

    def test_logout_rollenverlust_und_passwortwechsel(self):
        kennung = self.start()
        self.assertEqual(self.client.post("/logout", follow_redirects=False).status_code, 303)
        self.client.cookies.set(SESSION_COOKIE, self.cookie)
        self.assertEqual(self.abschluss(kennung).status_code, 409)
        for spalte, wert in (("password_hash", "geaendert"), ("role", "staff")):
            kennung = self.start()
            with db.get_conn() as conn:
                conn.execute(f"UPDATE users SET {spalte} = ? WHERE email = ?", (wert, self.user["email"]))
                conn.commit()
            self.assertEqual(self.abschluss(kennung).status_code, 303)
            with db.get_conn() as conn:
                conn.execute("UPDATE users SET role = 'owner', password_hash = 'synthetischer-passworthash' WHERE email = ?", (self.user["email"],))
                conn.commit()
        self.assertEqual(self.meta.aufrufe, [])

    def test_code_timeout_und_bereits_verbrauchter_code_werden_nicht_wiederholt(self):
        for fehler in (TimeoutError(self.meta.token), urllib.error.HTTPError("https://example.invalid", 400, self.meta.token, {},
                io.BytesIO(json.dumps({"error": {"code": 100, "message": self.meta.token}}).encode()))):
            with self.subTest(fehler=type(fehler).__name__):
                self.meta.antworten[("GET", "oauth/access_token")] = fehler
                kennung = self.start()
                antwort = self.abschluss(kennung)
                self.assertIn(antwort.json()["zustand"], {"unklar", "fehlgeschlagen"})
                self.assertNotIn(self.meta.token, antwort.text)
                vorher = len(self.meta.aufrufe)
                self.assertEqual(self.abschluss(kennung).status_code, 409)
                self.assertEqual(self.post("fortsetzen", kennung=kennung).status_code, 409)
                self.assertEqual(len(self.meta.aufrufe), vorher)

    def test_timeout_nach_codeaustausch_aktiviert_nichts(self):
        self.meta.antworten[("GET", "debug_token")] = TimeoutError(self.meta.token)
        kennung = self.start()
        self.assertEqual(self.abschluss(kennung).json()["zustand"], "unklar")
        self.assertFalse(verbindungsstatus(self.wid)["zugang_gespeichert"])
        self.assertEqual(self.abschluss(kennung).status_code, 409)

    def test_abonnement_timeout_wird_ohne_neuen_code_abgeglichen(self):
        def unklar(methode, pfad):
            if methode == "POST" and pfad.endswith("subscribed_apps"):
                self.meta.abonniert = True
                raise TimeoutError(self.meta.token)
        self.meta.vor_aufruf = unklar
        kennung = self.start()
        antwort = self.abschluss(kennung)
        self.assertEqual(antwort.json()["zustand"], "teilfehler")
        self.assertTrue(antwort.json()["fortsetzbar"])
        self.assertFalse(verbindungsstatus(self.wid)["versand_bereit"])
        self.meta.vor_aufruf = None
        self.assertEqual(self.post("fortsetzen", kennung=kennung).json()["zustand"], "abgeschlossen")
        self.assertEqual(self.meta.aufrufe.count(("GET", "oauth/access_token")), 1)
        self.assertEqual(self.meta.aufrufe.count(("POST", "333/subscribed_apps")), 1)

    def test_abonnement_fehler_bleibt_unbestaetigt_und_geheimnisse_bleiben_serverseitig(self):
        self.meta.antworten[("POST", "333/subscribed_apps")] = urllib.error.HTTPError("https://example.invalid/" + self.meta.token,
            400, self.meta.token, {}, io.BytesIO(json.dumps({"error": {"code": 133010, "error_subcode": 7,
                                                                         "message": self.meta.token}}).encode()))
        with self.assertNoLogs("app", level="DEBUG"):
            antwort = self.abschluss(self.start())
        self.assertEqual(antwort.json()["zustand"], "teilfehler")
        self.assertIn("133010", antwort.text)
        self.assertNotIn(self.meta.token, antwort.text)
        with db.get_conn() as conn:
            for tabelle in ("whatsapp_anschlussversuche", "whatsapp_verbindungen"):
                self.assertNotIn(self.meta.token, repr([dict(z) for z in conn.execute(f"SELECT * FROM {tabelle}").fetchall()]))

    def test_nummernkonflikt_rollt_lokale_reservierung_zurueck(self):
        verbindungspruefung.VerbindungsTests.entwurf(self, "kunde-b", "444")
        antwort = self.abschluss(self.start())
        self.assertEqual(antwort.status_code, 409)
        self.assertFalse(verbindungsstatus(self.wid)["zugang_gespeichert"])
        self.assertNotIn(("POST", "333/subscribed_apps"), self.meta.aufrufe)

    def test_widerruf_waehrend_abonnement_verhindert_verspaeteten_abschluss(self):
        def widerruf(methode, pfad):
            if methode == "POST":
                widerrufe_verbindung(self.wid, erwartete_version=1)
        self.meta.vor_aufruf = widerruf
        self.assertEqual(self.abschluss(self.start()).status_code, 409)
        status = verbindungsstatus(self.wid)
        self.assertEqual((status["version"], status["autorisierung"], status["zugang_gespeichert"]), (2, "widerrufen", 0))

    def test_rollenverlust_waehrend_http_verhindert_bestaetigung(self):
        def rollenverlust(methode, pfad):
            if methode == "POST":
                with db.get_conn() as conn:
                    conn.execute("UPDATE users SET role = 'staff' WHERE email = ?", (self.user["email"],))
                    conn.commit()
        self.meta.vor_aufruf = rollenverlust
        self.assertEqual(self.abschluss(self.start()).status_code, 409)
        self.assertFalse(verbindungsstatus(self.wid)["versand_bereit"])

    def test_zwei_abschluesse_verbrauchen_code_nur_einmal(self):
        kennung = self.start()
        erreicht, weiter = threading.Event(), threading.Event()
        def pause(methode, pfad):
            if pfad == "oauth/access_token":
                erreicht.set()
                self.assertTrue(weiter.wait(10))
        self.meta.vor_aufruf = pause
        with ThreadPoolExecutor(max_workers=2) as pool:
            erster = pool.submit(self.dienst, kennung)
            try:
                self.assertTrue(erreicht.wait(10))
                with self.assertRaises(VerbindungsFehler):
                    self.dienst(kennung)
            finally:
                weiter.set()
            self.assertEqual(erster.result(timeout=15)["zustand"], "abgeschlossen")
        self.assertEqual(self.meta.aufrufe.count(("GET", "oauth/access_token")), 1)

    def test_neuer_versuch_ersetzt_laufenden_und_abbruch_waehrend_http(self):
        for aktion in ("start", "abbruch"):
            kennung = self.start()
            def unterbrechen(methode, pfad):
                if pfad == "debug_token":
                    self.post(aktion, kennung=kennung)
            self.meta.vor_aufruf = unterbrechen
            self.assertEqual(self.abschluss(kennung).status_code, 409)
            self.assertFalse(verbindungsstatus(self.wid)["zugang_gespeichert"])

    def test_dashboard_konfiguration_csp_und_geheimnisse(self):
        antwort = self.client.get("/dashboard/whatsapp/verbinden")
        self.assertEqual(antwort.status_code, 200)
        csp = antwort.headers["content-security-policy"]
        regeln = {teile[0]: teile[1:] for regel in csp.split(";") if (teile := regel.strip().split())}
        self.assertIn("https://connect.facebook.net", regeln["connect-src"])
        self.assertIn("https://connect.facebook.net", regeln["script-src"])
        self.assertTrue(any(wert.startswith("'nonce-") for wert in regeln["script-src"]))
        self.assertEqual(regeln["object-src"], ["'none'"])
        self.assertEqual(regeln["frame-ancestors"], ["'none'"])
        self.assertNotIn("*", csp)
        self.assertNotIn(self.config.whatsapp_app_secret, antwort.text)
        self.assertNotIn("https://connect.facebook.net", self.client.get("/dashboard/settings").headers["content-security-policy"])
        with patch.object(anschluss, "settings", replace(self.config, whatsapp_signup_config_id=None)):
            antwort = self.client.get("/dashboard/whatsapp/verbinden")
            self.assertIn("noch nicht eingerichtet", antwort.text)
            self.assertNotIn("sdk.js", antwort.text)
            self.assertEqual(self.post("start").status_code, 409)
        with patch.object(verbindungen, "settings", replace(self.config, whatsapp_zugangsschluessel="ungueltig")):
            self.assertEqual(self.post("start").status_code, 409)
            self.assertEqual(self.meta.aufrufe, [])

    def test_automatik_eingang_fenster_intake_und_vorbereitete_antwort_gesperrt(self):
        self.assertEqual(self.abschluss(self.start()).json()["zustand"], "abgeschlossen")
        telefon = "4915700012345"
        nachricht = WhatsAppInboundMessage("444", "+49 000", telefon, "wamid.gehalten", str(int(time.time())), "text", "Inspektion", {})
        verarbeiten = Mock(side_effect=AssertionError("Keine automatische Bearbeitung"))
        for _ in range(2):
            self.assertEqual(prepare_whatsapp_inbound(workshop_id=self.wid, message=nachricht, process_message=verarbeiten)["reason"],
                             "coexistence_nicht_freigegeben")
        verarbeiten.assert_not_called()
        self.assertFalse(whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=telefon)["service_window_open"])
        result = main.process_chat_message(workshop_id=self.wid, session_id="synthetisch", message="Inspektion", channel="whatsapp", phone=telefon)
        self.assertEqual(result.data["gesperrt"], "coexistence_nicht_freigegeben")
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_zurueckgehalten").fetchone()["n"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_messages").fetchone()["n"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"], 0)
        save_whatsapp_message(workshop_id=self.wid, customer_phone=telefon, direction="outbound", phone_number_id="444",
            text="Bereits vorbereitet", reply_to_wa_message_id=nachricht.message_id, status="pending", dispatch_state="pending")
        save_whatsapp_message(workshop_id=self.wid, customer_phone=telefon, direction="outbound", phone_number_id="444",
            text="Alter ungeklärter Versand", status="unknown", dispatch_state="sending")
        senden = Mock(side_effect=AssertionError("Kein automatischer Versand"))
        for _ in range(2):
            result = deliver_prepared_whatsapp_reply(workshop_id=self.wid, customer_phone=telefon,
                reply_to_wa_message_id=nachricht.message_id, send_message=senden)
            self.assertFalse(result["retry"])
        senden.assert_not_called()
        self.assertFalse(anschluss.automatik_gesperrt("eigener-betrieb"))

    def test_veralteter_erfolgsstatus_nach_widerruf_ist_nicht_mehr_aktuell(self):
        kennung = self.start()
        self.abschluss(kennung)
        widerrufe_verbindung(self.wid, erwartete_version=2)
        self.assertEqual(self.post("status", kennung=kennung).json()["zustand"], "ueberholt")

    def test_autorisierter_zugang_macht_gesperrte_coexistence_nicht_gruen(self):
        from app.web import _whatsapp_readiness
        from app.workshops import get_workshop
        self.abschluss(self.start())
        with patch("app.web.settings", replace(self.config, whatsapp_verify_token="synthetisch",
                   whatsapp_start_template_name="synthetisch", whatsapp_start_template_language="de")):
            status = _whatsapp_readiness(Mock(base_url="https://testserver/"), get_workshop(self.wid))
        self.assertFalse(status["is_ready"])
        self.assertIn("gesperrt", verbindungsstatus(self.wid)["meldung"])
        self.assertTrue(status["can_start_template"])

    def test_code_darf_auch_in_neuem_versuch_nicht_erneut_verwendet_werden(self):
        kennung = self.start()
        self.abschluss(kennung)
        anzahl = len(self.meta.aufrufe)
        antwort = self.abschluss(self.start(), code="synthetischer-einmalcode-" + kennung)
        self.assertEqual(antwort.status_code, 409)
        self.assertEqual(len(self.meta.aufrufe), anzahl)

    def test_logout_waehrend_http_und_mitarbeiterrolle_sperren_abschluss(self):
        def logout(methode, pfad):
            if methode == "POST":
                anschluss.sitzung_beenden(self.cookie)
        self.meta.vor_aufruf = logout
        self.assertEqual(self.abschluss(self.start()).status_code, 409)
        self.assertFalse(verbindungsstatus(self.wid)["versand_bereit"])
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET role = 'staff' WHERE email = ?", (self.user["email"],))
            conn.commit()
        self.client.cookies.set(SESSION_COOKIE, create_session_token({**self.user, "role": "staff"}))
        self.assertEqual(self.post("start").status_code, 409)
        self.assertEqual(self.client.get("/dashboard/whatsapp/verbinden").status_code, 403)

    def test_signierter_webhook_wird_dauerhaft_quittiert_ohne_historien_bild_oder_textbearbeitung(self):
        self.abschluss(self.start())
        for feld, art in (("messages", "text"), ("history", "text"), ("messages", "image")):
            message = {"id": f"wamid.{feld}.{art}", "from": "4915700012345", "timestamp": str(int(time.time())),
                       "type": art, "text": {"body": "Inspektion"}, "image": {"id": "555"}}
            payload = {"entry": [{"changes": [{"field": feld, "value": {"metadata": {"phone_number_id": "444"},
                                                                                  "messages": [message]}}]}]}
            body = json.dumps(payload).encode()
            with patch.object(main, "settings", self.config), patch.object(main, "process_chat_message") as verarbeiten:
                for _ in range(2):
                    antwort = self.client.post("/webhooks/whatsapp", content=body,
                        headers={"content-type": "application/json", "x-hub-signature-256": build_signature(body, self.config.whatsapp_app_secret)})
                    self.assertEqual(antwort.status_code, 200, antwort.text)
                verarbeiten.assert_not_called()
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_zurueckgehalten").fetchone()["n"], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_messages").fetchone()["n"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"], 0)

    def test_unerwartete_provider_typen_und_pagination_werden_sicher_behandelt(self):
        self.meta.debug["scopes"] = [{}]
        self.assertEqual(self.abschluss(self.start()).json()["zustand"], "fehlgeschlagen")
        self.meta.debug["scopes"] = ["whatsapp_business_management", "whatsapp_business_messaging"]
        self.meta.antworten[("GET", "333/phone_numbers")] = {"data": [{"id": "444"}],
            "paging": {"next": "https://evil.invalid/" + self.meta.token, "cursors": "falsch"}}
        antwort = self.abschluss(self.start())
        self.assertEqual(antwort.json()["zustand"], "fehlgeschlagen")
        self.assertNotIn(self.meta.token, antwort.text)
        self.assertFalse(verbindungsstatus(self.wid)["zugang_gespeichert"])
