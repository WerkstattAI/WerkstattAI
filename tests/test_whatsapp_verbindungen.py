"""Isolierte Nachweise für Nummernbindung, Zugang und gesperrte Schreibwege."""
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import test_conversation_flows as fixture
import app.db as db
import app.whatsapp_verbindungen as verbindungen
from app.admin import create_workshop_account, update_workshop_account
from app.privacy_data import export_data
from app.whatsapp import send_whatsapp_template_message, send_whatsapp_text_message, save_whatsapp_message
from app.workshops import get_workshop, update_workshop
from verbindungsdaten import TESTSCHLUESSEL, synthetische_verbindung


class VerbindungsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="werkstattai-verbindung-"))
        self.stack.enter_context(patch.dict(os.environ, {"WERKSTATTAI_SQLITE_PATH": os.path.join(temp, "test.sqlite")}))
        self.konfiguration = replace(db.settings, database_url=None, default_workshop_id="eigener-betrieb",
            demo_workshop_id="oeffentliche-demo", whatsapp_default_phone_number_id="m1-nummer",
            whatsapp_access_token="synthetischer-m1-zugang", whatsapp_zugangsschluessel=TESTSCHLUESSEL)
        self.stack.enter_context(patch.object(db, "settings", self.konfiguration))
        self.stack.enter_context(patch.object(verbindungen, "settings", self.konfiguration))
        db.init_db()
        self.wid = "kunde-a"
        with db.get_conn() as conn:
            for wid in (self.wid, "kunde-b"):
                conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (wid, wid))
            conn.commit()

    def entwurf(self, wid="kunde-a", nummer="nummer-a", version=0):
        return verbindungen.speichere_verbindungsentwurf(workshop_id=wid, waba_id="gemeinsame-waba",
            phone_number_id=nummer, anzeigenummer="+49 000", token="synthetischer-kundenzugang", erwartete_version=version)

    def test_zwei_werkstaetten_ein_konto_getrennte_nummern_und_zugaenge(self):
        for wid, nummer, token in ((self.wid, "nummer-a", "kuenstlicher-zugang-a"), ("kunde-b", "nummer-b", "kuenstlicher-zugang-b")):
            synthetische_verbindung(wid, nummer, token)
        for wid, nummer, token in ((self.wid, "nummer-a", "kuenstlicher-zugang-a"), ("kunde-b", "nummer-b", "kuenstlicher-zugang-b")):
            zugang = verbindungen.zugang_fuer_werkstatt(wid, phone_number_id=nummer)
            self.assertEqual(zugang.token, token)
            self.assertNotIn(token, repr(zugang))
        with self.assertRaises(verbindungen.VerbindungsFehler):
            verbindungen.zugang_fuer_werkstatt(self.wid, phone_number_id="nummer-b")

    def test_entwurf_speichert_verschluesselt_aber_autorisiert_nicht(self):
        self.entwurf()
        status = verbindungen.verbindungsstatus(self.wid)
        self.assertTrue(status["zugang_gespeichert"])
        self.assertFalse(status["versand_bereit"])
        self.assertEqual(status["autorisierung"], "unbestaetigt")
        self.assertFalse(status["coexistence_bereit"])
        with db.get_conn() as conn:
            zeile = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,)).fetchone())
        self.assertNotIn("synthetischer-kundenzugang", json.dumps(zeile))
        self.assertNotIn("zugang_verschluesselt", status)

    def test_doppelte_bindung_parallel_auf_datenbankebene(self):
        barriere = threading.Barrier(2)
        def speichern(wid):
            barriere.wait(timeout=10)
            try:
                self.entwurf(wid, "gleiche-nummer")
                return True
            except verbindungen.VerbindungsFehler:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            ergebnisse = list(pool.map(speichern, [self.wid, "kunde-b"]))
        self.assertEqual(sorted(ergebnisse), [False, True])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_verbindungen WHERE phone_number_id = 'gleiche-nummer'").fetchone()["n"], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ? WHERE whatsapp_phone_number_id IS NULL AND is_demo = 0", ("\tgleiche-nummer\n",))

    def test_leerwerte_normalisierung_und_idempotente_migration(self):
        with db.get_conn() as conn:
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ?, whatsapp_display_phone_number = ? WHERE id = ?", (" \t\n", "\t ", self.wid))
            conn.commit()
        db.init_db()
        db.init_db()
        self.assertIsNone(get_workshop(self.wid)["whatsapp_phone_number_id"])
        self.assertIsNone(get_workshop(self.wid)["whatsapp_display_phone_number"])
        self.assertTrue(verbindungen.verbindungsstatus("eigener-betrieb")["versand_bereit"])

    def test_altduplikate_bleiben_unveraendert_und_sperren_migration(self):
        with db.get_conn() as conn:
            conn.execute("DROP INDEX idx_workshops_whatsapp_nummer_eindeutig")
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = CASE WHEN id = 'kunde-a' THEN ' doppelt ' ELSE 'doppelt' END WHERE id IN ('kunde-a', 'kunde-b')")
            conn.commit()
        with self.assertRaisesRegex(verbindungen.VerbindungsFehler, "1 Nummerngruppen"):
            db.init_db()
        self.assertEqual(get_workshop(self.wid)["whatsapp_phone_number_id"], " doppelt ")
        self.assertEqual(get_workshop("kunde-b")["whatsapp_phone_number_id"], "doppelt")
        with self.assertRaises(verbindungen.VerbindungsFehler):
            verbindungen.zugang_fuer_werkstatt(self.wid)

    def test_legacy_nur_einmalige_passende_eigene_m1_zuordnung(self):
        with db.get_conn() as conn:
            conn.execute("DROP TABLE whatsapp_verbindungen")
            conn.execute("DROP TABLE verbindungs_migrationen")
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = 'manuelle-altnummer' WHERE id = ?", (self.wid,))
            conn.commit()
        db.init_db()
        self.assertTrue(verbindungen.verbindungsstatus("eigener-betrieb")["versand_bereit"])
        altstatus = verbindungen.verbindungsstatus(self.wid)
        self.assertEqual(altstatus["herkunft"], "manuell_altbestand")
        self.assertEqual(altstatus["autorisierung"], "unbestaetigt")
        self.assertFalse(altstatus["versand_bereit"])
        status = verbindungen.verbindungsstatus("eigener-betrieb")
        self.assertEqual(status["autorisierung"], "altbestand")
        self.assertFalse(status["coexistence_bereit"])
        with db.get_conn() as conn:
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = 'neue-altangabe' WHERE id = ?", (self.wid,))
            conn.commit()
        db.init_db()
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        with patch.object(verbindungen, "settings", replace(self.konfiguration, whatsapp_default_phone_number_id="andere-nummer")):
            self.assertFalse(verbindungen.verbindungsstatus("eigener-betrieb")["versand_bereit"])
        verbindungen.widerrufe_verbindung("eigener-betrieb", erwartete_version=1)
        db.init_db()
        self.assertFalse(verbindungen.verbindungsstatus("eigener-betrieb")["versand_bereit"])

    def test_demo_und_unverbundene_werkstatt_erben_keinen_globalen_token(self):
        for wid in ("oeffentliche-demo", self.wid, "unbekannt"):
            with self.subTest(wid=wid), self.assertRaises(verbindungen.VerbindungsFehler):
                verbindungen.zugang_fuer_werkstatt(wid)
        with self.assertRaises(verbindungen.VerbindungsFehler):
            self.entwurf("oeffentliche-demo")

    def test_widerruf_und_veraltete_aenderungen(self):
        version = synthetische_verbindung(self.wid, "nummer-a")
        verbindungen.widerrufe_verbindung(self.wid, erwartete_version=version)
        with self.assertRaisesRegex(verbindungen.VerbindungsFehler, "widerrufen"):
            verbindungen.zugang_fuer_werkstatt(self.wid)
        with self.assertRaises(verbindungen.VerbindungsFehler):
            self.entwurf(version=version)
        with self.assertRaises(verbindungen.VerbindungsFehler):
            verbindungen.widerrufe_verbindung(self.wid, erwartete_version=version)
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["zugang_gespeichert"])

    def test_bestaetigung_ohne_zugang_und_geaenderte_version_sperren_versand(self):
        synthetische_verbindung(self.wid, "nummer-a")
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET version = version + 1 WHERE workshop_id = ?", (self.wid,))
            conn.commit()
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET zugang_verschluesselt = NULL WHERE workshop_id = ?", (self.wid,))
            conn.commit()
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_historischer_produktivname_ist_keine_oeffentliche_demo(self):
        with db.get_conn() as conn:
            conn.execute("UPDATE workshops SET id = 'demo-werkstatt' WHERE id = ?", (self.wid,))
            conn.commit()
        synthetische_verbindung("demo-werkstatt", "historische-nummer")
        self.assertTrue(verbindungen.verbindungsstatus("demo-werkstatt")["versand_bereit"])

    def test_falscher_fehlender_ungueltiger_und_zweckentfremdeter_schluessel(self):
        synthetische_verbindung(self.wid, "nummer-a")
        for schluessel in (None, "ungueltig", Fernet.generate_key().decode(), self.konfiguration.auth_secret):
            with self.subTest(schluessel=bool(schluessel)), patch.object(verbindungen, "settings", replace(
                    self.konfiguration, whatsapp_zugangsschluessel=schluessel)):
                status = verbindungen.verbindungsstatus(self.wid)
                self.assertFalse(status["versand_bereit"])
                self.assertNotIn("synthetischer-kundenzugang", json.dumps(status))
                if schluessel in (None, "ungueltig", self.konfiguration.auth_secret):
                    with self.assertRaises(verbindungen.VerbindungsFehler):
                        self.entwurf("kunde-b", "nummer-b")

    def test_manipuliertes_oder_fremdes_chiffrat_und_abweichende_nummer(self):
        synthetische_verbindung(self.wid, "nummer-a")
        synthetische_verbindung("kunde-b", "nummer-b")
        with db.get_conn() as conn:
            conn.execute("""UPDATE whatsapp_verbindungen SET zugang_verschluesselt =
                (SELECT zugang_verschluesselt FROM whatsapp_verbindungen WHERE workshop_id = 'kunde-a') WHERE workshop_id = 'kunde-b'""")
            conn.commit()
        self.assertFalse(verbindungen.verbindungsstatus("kunde-b")["versand_bereit"])
        with db.get_conn() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET zugang_verschluesselt = 'manipuliert' WHERE workshop_id = ?", (self.wid,))
            conn.commit()
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])
        with db.get_conn() as conn:
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = 'abweichend' WHERE id = ?", (self.wid,))
            conn.commit()
        self.assertFalse(verbindungen.verbindungsstatus(self.wid)["versand_bereit"])

    def test_versand_reserviert_keinen_zugang_aus_parametern_oder_globaler_konfiguration(self):
        with patch("app.whatsapp._post_graph_api_json") as http:
            for senden, daten in ((send_whatsapp_text_message, {"text": "Test"}),
                                  (send_whatsapp_template_message, {"template_name": "test", "template_language": "de"})):
                ergebnis = senden(workshop_id=self.wid, phone_number_id="m1-nummer", customer_phone="4915700012345",
                                  access_token="eingeschleuster-zugang", **daten)
                self.assertFalse(ergebnis.ok)
            http.assert_not_called()

    def test_transport_ausserhalb_transaktion_und_geheimnisse_nicht_in_fehlern_oder_export(self):
        synthetische_verbindung(self.wid, "nummer-a")
        token = "synthetischer-kundenzugang"
        def http(**daten):
            self.assertIsNone(db._TRANSACTION_CONNECTION.get())
            self.assertEqual(daten["access_token"], token)
            raise OSError(token)
        with patch("app.whatsapp._post_graph_api_json", side_effect=http):
            ergebnis = send_whatsapp_template_message(workshop_id=self.wid, phone_number_id="nummer-a",
                customer_phone="4915700012345", template_name="test", template_language="de")
        self.assertNotIn(token, repr(ergebnis))
        fehler = urllib.error.HTTPError("https://example.invalid", 400, token, {}, io.BytesIO(token.encode()))
        with patch("app.whatsapp._post_graph_api_json", side_effect=fehler):
            ergebnis = send_whatsapp_template_message(workshop_id=self.wid, phone_number_id="nummer-a",
                customer_phone="4915700012345", template_name="test", template_language="de")
        self.assertNotIn(token, repr(ergebnis))
        with patch("app.whatsapp._post_graph_api_json", return_value=(200, {"debug": token, "messages": [{"id": token}]})):
            ergebnis = send_whatsapp_template_message(workshop_id=self.wid, phone_number_id="nummer-a",
                customer_phone="4915700012345", template_name="test", template_language="de")
        self.assertNotIn(token, repr(ergebnis))
        self.assertNotIn(token.encode(), export_data(workshop_id=self.wid, email="synthetisch@example.invalid"))

    def test_saemtliche_profilschreibwege_sperren_fremde_nummern(self):
        with self.assertRaises(verbindungen.VerbindungsFehler):
            update_workshop(self.wid, name="Test", address="", phone="", email="", opening_hours="", services="",
                            pricing_info="", towing_info="", whatsapp_phone_number_id="m1-nummer")
        with self.assertRaises(verbindungen.VerbindungsFehler):
            create_workshop_account(workshop_id="neuer-kunde", workshop_name="Test", admin_email="neu@example.invalid",
                admin_password="Synthetisch123!", whatsapp_phone_number_id="fremde-nummer")
        with self.assertRaises(verbindungen.VerbindungsFehler):
            update_workshop_account(workshop_id=self.wid, workshop_name="Test", whatsapp_phone_number_id="fremde-nummer")
        self.assertIsNone(get_workshop(self.wid)["whatsapp_phone_number_id"])

    def test_berechtigung_formular_medien_und_status_enthalten_keine_zugaenge(self):
        from app.main import app
        synthetische_verbindung(self.wid, "nummer-a")
        synthetische_verbindung("kunde-b", "nummer-b")
        with TestClient(app) as client:
            client.headers["cookie"] = fixture._dashboard_request(self.wid).headers["cookie"]
            seite = client.get("/dashboard/settings?workshop_id=kunde-b")
            self.assertEqual(seite.status_code, 200)
            self.assertNotIn("nummer-b", seite.text)
            self.assertNotIn("synthetischer-kundenzugang", seite.text)
            self.assertNotIn('name="whatsapp_phone_number_id"', seite.text)
            antwort = client.post("/dashboard/settings", data={"name": "Angriff", "whatsapp_phone_number_id": "nummer-b"})
            self.assertEqual(antwort.status_code, 400)
            self.assertEqual(get_workshop(self.wid)["whatsapp_phone_number_id"], "nummer-a")
            save_whatsapp_message(workshop_id=self.wid, phone_number_id="nummer-b", customer_phone="4915700012345",
                direction="inbound", message_type="image", payload={"image": {"id": "123"}})
            with db.get_conn() as conn:
                mid = conn.execute("SELECT MAX(id) AS mid FROM whatsapp_messages").fetchone()["mid"]
            with patch("app.web.lade_bild") as laden:
                self.assertEqual(client.get(f"/dashboard/whatsapp/medien/{mid}").status_code, 409)
                laden.assert_not_called()

    def test_admin_formulare_duerfen_auch_keine_nummern_provisionieren(self):
        from app.main import app
        with TestClient(app) as client:
            client.headers["cookie"] = fixture._dashboard_request("eigener-betrieb", role="admin").headers["cookie"]
            antwort = client.post("/dashboard/admin/workshops", data={"workshop_id": "neuer-kunde",
                "workshop_name": "Synthetisch", "admin_email": "synthetisch@example.invalid",
                "admin_password": "Synthetisch123!", "whatsapp_phone_number_id": "fremde-nummer"}, follow_redirects=False)
            self.assertEqual(antwort.status_code, 303)
            self.assertIn("error=", antwort.headers["location"])
            with db.get_conn() as conn:
                self.assertIsNone(conn.execute("SELECT 1 FROM workshops WHERE id = 'neuer-kunde'").fetchone())
            antwort = client.post("/dashboard/admin/workshops/kunde-a", data={"workshop_name": "Angriff",
                "whatsapp_phone_number_id": "fremde-nummer"}, follow_redirects=False)
            self.assertEqual(antwort.status_code, 303)
            self.assertIn("error=", antwort.headers["location"])
            self.assertEqual(get_workshop(self.wid)["name"], self.wid)
