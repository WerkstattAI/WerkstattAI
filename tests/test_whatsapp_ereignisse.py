"""Signierte Ereignisse und deterministische Konkurrenz ohne echten Meta-Transport."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from starlette.requests import Request
import app.db as db
import app.main as main
import app.whatsapp as wa
import app.whatsapp_anschluss as anschluss
import app.whatsapp_ereignisse as ereignisse
import app.whatsapp_verbindungen as verbindungen
from app.auth import SESSION_COOKIE, create_session_token
from app.models import IntakeState
from app.tickets import save_ticket, add_ticket_note, find_ticket_by_id
import test_whatsapp_verbindungen as verbindungspruefung


class EreignisFaelle:
    postgres = False

    def setUp(self):
        verbindungspruefung.VerbindungsTests.setUp(self)
        self.config = replace(self.konfiguration, whatsapp_app_id="111", whatsapp_app_secret="synthetische-signatur")
        for modul in (main, anschluss, verbindungen):
            self.stack.enter_context(patch.object(modul, "settings", self.config))
        if self.postgres:
            self.stack.enter_context(patch.object(db, "settings", replace(self.config,
                database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"])))
            db.init_db()
            self.wid = "ereignis-" + uuid.uuid4().hex
            with db.get_conn() as conn:
                conn.execute("INSERT INTO workshops (id, name) VALUES (?, 'Ereignisprüfung')", (self.wid,))
                conn.commit()
        self.kunde = "4915700012345"
        self.nummer = "444" if not self.postgres else str(uuid.uuid4().int)[:16]
        self.betrieb = "4915700099999"
        self.konto = "333" if not self.postgres else str(uuid.uuid4().int)[:16]
        self.anschliessen()
        self.client = self.stack.enter_context(TestClient(main.app, base_url="https://testserver"))
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Kein echter Meta-Transport")))

    def anschliessen(self, wid=None, phone=None, konto=None, anzeige=None):
        wid, phone = wid or self.wid, phone or self.nummer
        with db.get_conn() as conn:
            alt = conn.execute("SELECT version FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone()
        version = verbindungen.speichere_verbindungsentwurf(workshop_id=wid, phone_number_id=phone,
            waba_id=konto or self.konto, anzeigenummer=anzeige or self.betrieb, token="synthetischer-zugang",
            erwartete_version=alt["version"] if alt else 0)
        with db.get_conn() as conn:
            conn.execute("""UPDATE whatsapp_verbindungen SET herkunft = 'embedded_signup_coexistence', autorisierung = 'bestaetigt',
                zustand = 'verbunden', verbunden_seit = ? WHERE workshop_id = ?""", (time.time() - 60, wid))
            conn.commit()
        return version

    def paket(self, feld="smb_message_echoes", wert=None):
        echo = {"id": "wamid.telefon", "from": self.betrieb, "to": self.kunde,
                "timestamp": str(int(time.time())), "type": "text", "text": {"body": "Wir kümmern uns darum."}}
        return {"object": "whatsapp_business_account", "entry": [{"id": self.konto, "time": int(time.time()),
            "changes": [{"field": feld, "value": wert if wert is not None else {"messaging_product": "whatsapp",
                "metadata": {"phone_number_id": self.nummer}, "message_echoes": [echo]}}]}]}

    def webhook(self, payload, erwartet=200, signatur=None):
        body = json.dumps(payload).encode()
        if getattr(self, "direkt", False):
            async def empfangen():
                return {"type": "http.request", "body": body, "more_body": False}
            anfrage = Request({"type": "http", "method": "POST", "path": "/webhooks/whatsapp",
                "headers": [(b"x-hub-signature-256", wa.build_signature(body, self.config.whatsapp_app_secret).encode())]}, empfangen)
            return asyncio.run(main.whatsapp_webhook(anfrage))
        antwort = TestClient(main.app, base_url="https://testserver").post("/webhooks/whatsapp", content=body, headers={"content-type": "application/json",
            "x-hub-signature-256": signatur or wa.build_signature(body, self.config.whatsapp_app_secret)})
        self.assertEqual(antwort.status_code, erwartet, antwort.text)
        return antwort

    def nachrichten(self):
        return wa.list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.kunde)

    def kontrolle(self):
        return db.get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde)

    def fortsetzen(self):
        return db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde,
                                                    conversation_state="assistant_active")

    def vorbereiten(self):
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))
            conn.commit()
        nachricht = wa.WhatsAppInboundMessage(self.nummer, self.betrieb, self.kunde, "wamid.eingang",
            str(int(time.time())), "text", "Hallo", {}, self.konto)
        return wa.prepare_whatsapp_inbound(workshop_id=self.wid, message=nachricht,
            process_message=lambda: SimpleNamespace(reply="Automatische Antwort", data={}, done=False))

    def liefern(self, senden):
        return wa.deliver_prepared_whatsapp_reply(workshop_id=self.wid, customer_phone=self.kunde,
            reply_to_wa_message_id="wamid.eingang", send_message=senden)

    def test_echo_ohne_freigabe_einmalig_ohne_fenster_ticket_oder_http(self):
        with patch.object(main, "process_chat_message") as eingang, patch.object(main, "send_whatsapp_text_message") as senden:
            self.webhook(self.paket())
            self.webhook(self.paket())
            db.init_db()  # Persistente Entscheidung, keine Prozess- oder Cache-Deduplizierung.
            revision = self.fortsetzen()["revision"]
            self.webhook(self.paket())
            eingang.assert_not_called()
            senden.assert_not_called()
        self.assertEqual(self.kontrolle()["revision"], revision)
        self.assertEqual(self.kontrolle()["mode"], "assistant")
        self.assertEqual(len(self.nachrichten()), 1)
        nachricht = self.nachrichten()[0]
        self.assertEqual((nachricht["direction"], nachricht["sender_role"], nachricht["purpose"]),
                         ("outbound", "workshop", "workshop_notification"))
        self.assertIsNone(nachricht["ticket_id"])
        self.assertFalse(wa.whatsapp_customer_service_window_for_phone(workshop_id=self.wid, customer_phone=self.kunde)["service_window_open"])
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["coexistence_bereit"], 0)

    def test_ticket_fragen_und_reparaturstatus_bleiben_erhalten(self):
        tid = save_ticket(IntakeState(telefon=self.kunde, name="Prüfkunde"), workshop_id=self.wid, verified_customer_phone=self.kunde)
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde, mode="assistant", active_ticket_id=tid)
        add_ticket_note(tid, "Wie teuer?", workshop_id=self.wid, purpose="customer_question", message_id="frage-offen")
        vorher = find_ticket_by_id(tid, self.wid)
        self.webhook(self.paket())
        nachher = find_ticket_by_id(tid, self.wid)
        self.assertEqual(nachher["status"], vorher["status"])
        self.assertIsNone(next(n for n in nachher["notes"] if n["message_id"] == "frage-offen")["resolved_at"])
        self.assertEqual(nachher["notes"][-1]["purpose"], "workshop_notification")
        self.assertEqual(self.kontrolle()["mode"], "manual")

    def test_fremde_zuordnungen_signatur_und_fehlerhafte_felder(self):
        for art in ("konto", "nummer", "absender", "empfaenger", "feld", "fehlend", "typ", "historie", "kontakte"):
            payload = self.paket()
            eintrag = payload["entry"][0]
            change = eintrag["changes"][0]
            if art == "konto": eintrag["id"] = "999"
            if art == "nummer": change["value"]["metadata"]["phone_number_id"] = "999"
            if art == "absender": change["value"]["message_echoes"][0]["from"] = "49999"
            if art == "empfaenger": change["value"]["message_echoes"][0]["to"] = {"workshop_id": self.wid}
            if art == "feld": change["field"] = "unbekannt"
            if art == "fehlend": del change["field"]
            if art == "typ": change["field"] = ["messages"]
            if art == "historie": change["field"] = "history"
            if art == "kontakte": change["field"] = "smb_app_state_sync"
            change["value"]["messages"] = [{"from": self.kunde, "id": "wamid.falsch", "type": "text", "text": {"body": "Hallo"}}]
            self.webhook(payload)
        self.webhook(self.paket(), 403, "sha256=falsch")
        self.assertEqual(self.nachrichten(), [])

    def test_gemischtes_paket_und_dauerhaft_gesperrte_eingaenge(self):
        payload = self.paket()
        wert = {"metadata": {"phone_number_id": self.nummer}, "messages": [{"id": "wamid.gesperrt", "from": self.kunde,
            "timestamp": str(int(time.time())), "type": "text", "text": {"body": "Inspektion"}}]}
        payload["entry"][0]["changes"] += [{"field": feld, "value": wert} for feld in ("messages", "history", "smb_app_state_sync")]
        with patch.object(main, "process_chat_message") as verarbeiten:
            self.webhook(payload)
            self.fortsetzen()
            with db.get_conn() as conn:
                conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))
                conn.commit()
            self.webhook(self.paket("messages", wert))
            verarbeiten.assert_not_called()
        self.assertEqual(len(self.nachrichten()), 1)

    def test_typ_und_batchgrenzen_vor_seiteneffekten(self):
        payload = self.paket()
        payload["entry"][0]["changes"] *= 101
        self.webhook(payload, 413)
        payload = self.paket()
        payload["entry"][0]["changes"][0]["value"]["message_echoes"] = {}
        self.webhook(payload, 422)
        payload = self.paket()
        payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]["text"]["body"] = "x" * 4097
        self.webhook(payload, 413)
        self.assertEqual(self.nachrichten(), [])

    def test_echo_wiederholung_in_neuem_python_prozess(self):
        self.webhook(self.paket())
        revision = self.fortsetzen()["revision"]
        code = """
import json, sys
from dataclasses import replace
import app.db as db
db.settings = replace(db.settings, database_url=None)
from app.whatsapp_ereignisse import verarbeite_echo
eintrag = json.loads(sys.argv[1])['entry'][0]
assert verarbeite_echo(eintrag, eintrag['changes'][0]['value']) == 0
"""
        lauf = subprocess.run([sys.executable, "-c", code, json.dumps(self.paket())], capture_output=True, text=True, timeout=30)
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertEqual(self.kontrolle()["revision"], revision)
        self.assertEqual(len(self.nachrichten()), 1)

    def test_gleiche_anschlusssekunde_sperrt_zugang_ohne_neue_version_zu_widerrufen(self):
        zeit = int(time.time())
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET verbunden_seit = ? WHERE workshop_id = ?", (zeit + 0.2, self.wid))
            conn.commit()
        version = verbindungen.verbindungsstatus(self.wid)["version"]
        payload = self.paket("account_update", {"event": "PARTNER_REMOVED"})
        payload["entry"][0]["time"] = zeit
        self.webhook(payload)
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["version"], version)
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.assertTrue(anschluss.automatik_gesperrt(self.wid))
        self.anschliessen()
        self.webhook(payload)
        self.assertTrue(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_zeitlich_unklares_echo_wird_bewusst_ohne_erneute_uebernahme_quittiert(self):
        payload = self.paket()
        zeit = int(payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]["timestamp"])
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET verbunden_seit = ? WHERE workshop_id = ?", (zeit + 0.2, self.wid))
            conn.commit()
        self.webhook(payload)
        self.assertTrue(self.nachrichten()[0]["echo_zuordnung_offen"])
        revision = self.fortsetzen()["revision"]
        self.webhook(payload)
        self.assertFalse(self.nachrichten()[0]["echo_zuordnung_offen"])
        self.assertEqual(self.kontrolle()["revision"], revision)

    def test_eigene_api_id_ist_einziger_abgleich_nicht_text_oder_uhrzeit(self):
        wa.save_whatsapp_message(workshop_id=self.wid, phone_number_id=self.nummer, customer_phone=self.kunde,
            direction="outbound", text="Wir kümmern uns darum.", wa_message_id="wamid.eigene-sendung", status="sent",
            payload={"source": "webhook", "sender_role": "assistant"})
        self.webhook(self.paket())
        self.assertEqual(len(self.nachrichten()), 2)
        self.assertEqual(self.kontrolle()["mode"], "manual")

    def test_kontofelder_und_zeit_muessen_belegbar_sein(self):
        for wert in ({"event": "GERATENER_WIDERRUF"}, {"event": "PARTNER_REMOVED", "phone_number": "49999"},
                     {"event": "PARTNER_REMOVED", "waba_info": {"waba_id": "999"}},
                     {"event": "PARTNER_REMOVED", "phone_number": []}, {"event": "PARTNER_REMOVED", "waba_info": []}):
            self.webhook(self.paket("account_update", wert))
        for zeit in (None, True, {}, int(time.time()) + 3600):
            payload = self.paket("account_update", {"event": "PARTNER_REMOVED"})
            payload["entry"][0]["time"] = zeit
            self.webhook(payload)
        self.assertTrue(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_partnerentzug_und_kontoloeschung_sind_keine_loeschung_der_geschichte(self):
        self.webhook(self.paket())
        payload = self.paket("account_update", {"event": "PARTNER_REMOVED", "waba_info": {"waba_id": self.konto}})
        payload["entry"][0]["id"] = "777"
        self.webhook(payload)
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.anschliessen()
        self.webhook(self.paket("account_update", {"event": "ACCOUNT_DELETED"}))
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.assertEqual(len(self.nachrichten()), 1)

    def test_paralleles_echo_und_wiederholung_nach_fortsetzen(self):
        self.direkt = True
        barriere = threading.Barrier(2)
        original = ereignisse._verbindung
        def lesen(*args):
            ergebnis = original(*args)
            barriere.wait(timeout=15)
            return ergebnis
        with patch.object(ereignisse, "_verbindung", lesen), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.webhook, [self.paket(), self.paket()]))
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertEqual(self.kontrolle()["mode"], "manual")
        revision = self.fortsetzen()["revision"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.webhook, [self.paket(), self.paket()]))
        self.assertEqual(self.kontrolle()["revision"], revision)

    def test_uebernahme_gegen_vorbereitung(self):
        self.direkt = True
        begonnen, weiter = threading.Event(), threading.Event()
        original = wa.save_whatsapp_message
        def speichern(**kwargs):
            ergebnis = original(**kwargs)
            if kwargs.get("dispatch_state") == "pending":
                begonnen.set()
                self.assertTrue(weiter.wait(15))
            return ergebnis
        echo_gelesen = threading.Event()
        lesen = ereignisse._verbindung
        def zuordnung(*args):
            ergebnis = lesen(*args)
            echo_gelesen.set()
            return ergebnis
        with patch.object(wa, "save_whatsapp_message", speichern), patch.object(ereignisse, "_verbindung", zuordnung), ThreadPoolExecutor(max_workers=2) as pool:
            vorbereitet = pool.submit(self.vorbereiten)
            self.assertTrue(begonnen.wait(15))
            echo = pool.submit(self.webhook, self.paket())
            self.assertTrue(echo_gelesen.wait(15))
            weiter.set()
            vorbereitet.result(15)
            echo.result(15)
        senden = Mock()
        self.assertIn("suppressed_reason", self.liefern(senden))
        senden.assert_not_called()

    def test_echo_waehrend_reservierung_stoppt_transport_und_uebernimmt(self):
        self.vorbereiten()
        reserviert, weiter = threading.Event(), threading.Event()
        original = wa.beginne_automatischen_transport
        def beginn(*args):
            reserviert.set()
            self.assertTrue(weiter.wait(15))
            return original(*args)
        senden = Mock()
        with patch.object(wa, "beginne_automatischen_transport", beginn), ThreadPoolExecutor(max_workers=1) as pool:
            versand = pool.submit(self.liefern, senden)
            self.assertTrue(reserviert.wait(15))
            self.webhook(self.paket())
            self.assertTrue(self.nachrichten()[-1]["echo_zuordnung_offen"])
            weiter.set()
            self.assertEqual(versand.result(15)["status"], "failed")
        senden.assert_not_called()
        self.assertEqual(self.kontrolle()["mode"], "manual")

    def test_eigene_api_sendung_mit_fruehem_echo_und_status(self):
        self.vorbereiten()
        revision = self.kontrolle()["revision"]
        def senden(reply):
            self.webhook(self.paket())
            wert = {"metadata": {"phone_number_id": self.nummer}, "statuses": [{"id": "wamid.telefon",
                "recipient_id": self.kunde, "status": "read", "errors": [{"code": 123, "message": "GEHEIMER-PROVIDERTEXT"}]}]}
            self.webhook(self.paket("messages", wert))
            return wa.WhatsAppSendResult(True, 200, "wamid.telefon", {})
        self.assertEqual(self.liefern(senden)["status"], "read")
        self.assertEqual(self.kontrolle()["revision"], revision)
        ausgang = [m for m in self.nachrichten() if m["direction"] == "outbound"]
        self.assertEqual(len(ausgang), 1)
        self.assertEqual(ausgang[0]["sender_role"], "assistant")
        self.assertNotIn("GEHEIMER-PROVIDERTEXT", repr(ausgang))
        self.webhook(self.paket())
        self.assertEqual(self.kontrolle()["revision"], revision)

    def test_frueher_status_ohne_echo_ueberlebt_neue_db_verbindung(self):
        self.vorbereiten()
        def senden(reply):
            self.webhook(self.paket("messages", {"metadata": {"phone_number_id": self.nummer}, "statuses": [
                {"id": "wamid.eigen", "recipient_id": self.kunde, "status": "delivered"}]}))
            return wa.WhatsAppSendResult(True, 200, "wamid.eigen", {})
        self.assertEqual(self.liefern(senden)["status"], "delivered")

    def test_ungeklaerter_versand_bleibt_reserviert_kein_falsches_fortsetzen(self):
        self.vorbereiten()
        def senden(reply):
            self.webhook(self.paket())
            return wa.WhatsAppSendResult(False, None, None, {})
        self.assertEqual(self.liefern(senden)["status"], "unknown")
        with self.assertRaises(ValueError): self.fortsetzen()
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        with db.get_conn() as conn:
            versand = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND dispatch_state = 'sending'", (self.wid,)).fetchone()
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=versand["message_id"], status="sent", wa_message_id="wamid.anderer")
        self.assertEqual(self.kontrolle()["mode"], "manual")

    def test_kontowiderruf_mehrere_nummern_und_fremdes_konto(self):
        with db.get_conn() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES ('kunde-c', 'Drittes Konto')")
            conn.commit()
        self.anschliessen("kunde-b", "555", self.konto, "4915700088888")
        self.anschliessen("kunde-c", "666", "999", "4915700077777")
        self.webhook(self.paket("account_update", {"event": "PARTNER_REMOVED", "phone_number": self.betrieb}))
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.assertTrue(verbindungen.verbindungsstatus("kunde-b")["versand_bereit"])
        self.anschliessen()
        self.webhook(self.paket("account_update", {"event": "ACCOUNT_OFFBOARDED"}))
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.assertFalse(verbindungen.verbindungsstatus("kunde-b")["versand_bereit"])
        self.assertTrue(verbindungen.verbindungsstatus("kunde-c")["versand_bereit"])

    def test_partnerreferenz_appbezug_und_keine_automatische_wiederverbindung(self):
        wert = {"event": "PARTNER_APP_UNINSTALLED", "waba_info": {"waba_id": self.konto, "partner_app_id": "999"}}
        payload = self.paket("account_update", wert)
        payload["entry"][0]["id"] = "777"
        self.webhook(payload)
        self.assertTrue(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        wert["waba_info"]["partner_app_id"] = "111"
        self.webhook(payload)
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        self.webhook(self.paket("account_update", {"event": "ACCOUNT_RECONNECTED"}))
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_spaeter_widerruf_und_wiederholung_treffen_keine_neue_version(self):
        payload = self.paket("account_update", {"event": "PARTNER_REMOVED"})
        self.webhook(payload)
        version = self.anschliessen()
        self.webhook(payload)
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["version"], version)
        payload["entry"][0]["time"] -= 300
        self.webhook(payload)
        self.assertTrue(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_widerruf_gegen_neue_verbindungsversion(self):
        gelesen, weiter = threading.Event(), threading.Event()
        original = ereignisse._kontoverbindungen
        def lesen(*args):
            ergebnis = original(*args)
            gelesen.set()
            self.assertTrue(weiter.wait(15))
            return ergebnis
        with patch.object(ereignisse, "_kontoverbindungen", lesen), ThreadPoolExecutor(max_workers=1) as pool:
            widerruf = pool.submit(self.webhook, self.paket("account_update", {"event": "PARTNER_REMOVED"}))
            self.assertTrue(gelesen.wait(15))
            version = self.anschliessen()
            weiter.set()
            widerruf.result(15)
        self.assertEqual(verbindungen.verbindungsstatus(self.wid)["version"], version)
        self.assertTrue(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_bildecho_dashboard_mandantenschutz_und_widerruf(self):
        payload = self.paket()
        echo = payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]
        echo.update(type="image", image={"id": "123456", "caption": "Foto", "url": "https://falsch.invalid/geheim"})
        self.webhook(payload)
        m = self.nachrichten()[0]
        self.assertNotIn("falsch.invalid", m["payload_json"])
        with db.get_conn() as conn:
            conn.execute("INSERT INTO users (email, role, workshop_id, password_hash) VALUES ('echo@example.invalid', 'owner', ?, 'synthetisch')", (self.wid,))
            conn.commit()
        self.client.cookies.set(SESSION_COOKIE, create_session_token({"email": "echo@example.invalid", "role": "owner", "workshop_id": self.wid}))
        seite = self.client.get("/dashboard/whatsapp", params={"phone": self.kunde, "workshop_id": self.wid})
        self.assertEqual(seite.status_code, 200)
        self.assertIn("Foto", seite.text)
        url = f"/dashboard/whatsapp/medien/{m['id']}"
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_messages SET workshop_id = 'kunde-b' WHERE id = ?", (m["id"],))
            conn.commit()
        with patch("app.web.lade_bild") as laden:
            self.assertEqual(self.client.get(url, params={"workshop_id": "kunde-b"}).status_code, 404)
            laden.assert_not_called()
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_messages SET workshop_id = ? WHERE id = ?", (self.wid, m["id"]))
            conn.commit()
        self.webhook(self.paket("account_update", {"event": "PARTNER_REMOVED"}))
        with patch("app.web.lade_bild") as laden, patch.object(wa, "_post_graph_api_json") as transport:
            self.assertEqual(self.client.get(url, params={"workshop_id": self.wid}).status_code, 409)
            result = wa.send_whatsapp_text_message(workshop_id=self.wid, phone_number_id=self.nummer, customer_phone=self.kunde, text="Prüfung")
            self.assertFalse(result.ok)
            laden.assert_not_called()
            transport.assert_not_called()


class SQLiteEreignisTests(EreignisFaelle, unittest.TestCase):
    pass


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank eingerichtet")
class PostgreSQLEreignisTests(unittest.TestCase):
    postgres = True
    setUp = EreignisFaelle.setUp
    anschliessen = EreignisFaelle.anschliessen
    paket = EreignisFaelle.paket
    webhook = EreignisFaelle.webhook
    nachrichten = EreignisFaelle.nachrichten
    kontrolle = EreignisFaelle.kontrolle
    fortsetzen = EreignisFaelle.fortsetzen
    vorbereiten = EreignisFaelle.vorbereiten
    liefern = EreignisFaelle.liefern
    test_paralleles_echo_und_wiederholung_nach_fortsetzen = EreignisFaelle.test_paralleles_echo_und_wiederholung_nach_fortsetzen
    test_uebernahme_gegen_vorbereitung = EreignisFaelle.test_uebernahme_gegen_vorbereitung
    test_echo_waehrend_reservierung_stoppt_transport_und_uebernimmt = EreignisFaelle.test_echo_waehrend_reservierung_stoppt_transport_und_uebernimmt
    test_widerruf_gegen_neue_verbindungsversion = EreignisFaelle.test_widerruf_gegen_neue_verbindungsversion
    test_eigene_api_sendung_mit_fruehem_echo_und_status = EreignisFaelle.test_eigene_api_sendung_mit_fruehem_echo_und_status
