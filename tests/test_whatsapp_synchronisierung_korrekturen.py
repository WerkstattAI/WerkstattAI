"""Originale Gegenproben und ergänzende Regressionen der beiden Sync-Korrekturen."""
import os
import subprocess
import sys
import threading
import time
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app.db as db
import app.main as main
import app.whatsapp as wa
import app.whatsapp_anschluss as anschluss
import app.whatsapp_synchronisierung as sync
import test_whatsapp_synchronisierung as grundlage
import test_whatsapp_ereignisse as ereignisgrundlage


class KorrekturFaelle:
    # Nur Hilfsmethoden übernehmen, keine geerbten Bestandsfälle erneut zählen.
    setUp = grundlage.SynchronisierungsFaelle.setUp
    anschliessen = grundlage.SynchronisierungsFaelle.anschliessen
    paket = grundlage.SynchronisierungsFaelle.paket
    webhook = grundlage.SynchronisierungsFaelle.webhook
    nachrichten = grundlage.SynchronisierungsFaelle.nachrichten
    kontrolle = grundlage.SynchronisierungsFaelle.kontrolle
    http = grundlage.SynchronisierungsFaelle.http
    route = grundlage.SynchronisierungsFaelle.route
    zustand = grundlage.SynchronisierungsFaelle.zustand
    nachricht = grundlage.SynchronisierungsFaelle.nachricht
    historie = grundlage.SynchronisierungsFaelle.historie
    ablehnung = grundlage.SynchronisierungsFaelle.ablehnung
    kontakt = grundlage.SynchronisierungsFaelle.kontakt
    medium = grundlage.SynchronisierungsFaelle.medium

    def fertig(self):
        self.route()
        self.webhook(self.historie())
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_ablehnung_nach_import_mit_null_prozent_ist_widerspruch(self):
        self.route()
        self.webhook(self.historie(fortschritt=0))
        self.assertEqual(len(self.nachrichten()), 1)
        self.webhook(self.ablehnung())
        self.assertEqual(self.zustand()["zustand"], "pruefung",
                         "Bereits importierte Daten widersprechen der späteren Nichtteilen-Entscheidung, auch bei Fortschritt 0")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_gesicherte_luecke_sperrt_bereitschaft_vor_hintergrundlauf(self):
        self.fertig()
        # Der dauerhafte Eingang ist bereits bestätigt; der Hintergrundlauf
        # bleibt wie nach einem Prozessabbruch zunächst unausgeführt.
        with patch.object(sync, "verarbeite_offene"):
            self.webhook(self.historie(teil=3, nachrichten=[]))
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_events WHERE workshop_id = ? AND event_type = 'sync_offen'",
                                          (self.wid,)).fetchone()["n"], 1)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"],
                         "Bereits quittierte neue Importarbeit darf vor ihrer Prüfung nicht als technisch bereit gelten")

    def test_gesicherte_historie_darf_vor_import_keinen_chat_starten(self):
        self.fertig()
        # Betriebsfreigabe ausschließlich in dieser künstlichen Testdatenbank.
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))
        self.assertFalse(anschluss.automatik_gesperrt(self.wid))
        n = self.nachricht(mid="wamid.verspaeteter-import")
        with patch.object(sync, "verarbeite_offene"):
            self.webhook(self.historie(teil=2, nachrichten=[n]))
        wert = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer}, "messages": [n]}
        with patch.object(main, "process_chat_message", return_value=SimpleNamespace(reply="", data={}, done=False)) as chat:
            self.webhook(self.paket("messages", wert))
        chat.assert_not_called()

    def erfassen(self, paket):
        e = paket["entry"][0]
        c = e["changes"][0]
        daten, _ = sync.validiere(c["field"], e, c["value"])
        return sync.erfasse(daten)

    def freigeben(self):
        # Nur dieses isolierte Fixture simuliert eine spätere Betriebsfreigabe.
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (self.wid,))

    def test_duplikate_abschluss_und_luecke_loesen_nur_passende_sperre(self):
        self.route()
        fertig = self.historie()
        self.webhook(fertig)
        self.erfassen(fertig)
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        luecke = self.historie(teil=3, nachrichten=[])
        self.erfassen(luecke)
        self.erfassen(luecke)
        self.erfassen(fertig)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_events WHERE workshop_id = ? AND event_type = 'sync_offen'",
                                          (self.wid,)).fetchone()["n"], 1)
        sync.verarbeite_offene(self.wid)
        self.assertEqual(self.zustand()["zustand"], "laufend")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        self.erfassen(self.historie(teil=2, nachrichten=[]))
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        sync.verarbeite_offene(self.wid)
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        self.erfassen(luecke)
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_offene_kontakte_sperren_bis_zur_verarbeitung(self):
        self.fertig()
        self.erfassen(self.kontakt())
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        sync.verarbeite_offene(self.wid)
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_capture_rollback_hinterlaesst_weder_arbeit_noch_sperre(self):
        self.fertig()
        with self.assertRaisesRegex(RuntimeError, "Prüfabbruch"):
            with db.atomic_database():
                self.erfassen(self.historie(teil=2, nachrichten=[]))
                self.assertFalse(sync.status(self.wid)["technisch_bereit"])
                raise RuntimeError("Prüfabbruch")
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_neustart_sperrt_vor_recovery_und_wiederholt_keinen_eingang(self):
        self.fertig()
        self.freigeben()
        n = self.nachricht(mid="wamid.neustart-offen")
        self.erfassen(self.historie(teil=2, nachrichten=[n]))
        normal = self.paket("messages", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer}, "messages": [n]})
        with patch.object(main, "process_chat_message") as chat:
            self.webhook(normal)
            umgebung = os.environ.copy()
            umgebung.update(DATABASE_URL=db.settings.database_url or "", APP_ENV="test")
            skript = """import sys
from unittest.mock import patch
from app import whatsapp_synchronisierung as s, whatsapp_anschluss as a
with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Echter HTTP-Transport gesperrt')):
    assert not s.status(sys.argv[1])['technisch_bereit']
    assert a.automatik_gesperrt(sys.argv[1])
    s.verarbeite_offene(sys.argv[1])
    assert s.status(sys.argv[1])['technisch_bereit']
"""
            lauf = subprocess.run([sys.executable, "-c", skript, self.wid], env=umgebung, capture_output=True, text=True, timeout=40)
            self.assertEqual(lauf.returncode, 0, lauf.stderr)
            self.assertFalse(anschluss.automatik_gesperrt(self.wid))
            self.webhook(normal)
            chat.assert_not_called()
        self.assertEqual(len(self.nachrichten()), 2)
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_zurueckgehalten WHERE workshop_id = ? AND wa_message_id = ?",
                                          (self.wid, n["id"])).fetchone()["n"], 1)

    def test_capture_transaktion_ordnet_parallelen_normalen_eingang(self):
        self.fertig()
        self.freigeben()
        self.direkt = True
        drin, weiter, eingang = threading.Event(), threading.Event(), threading.Event()
        aktuell, atomar = sync._aktuell, wa.atomic_database
        n = self.nachricht(mid="wamid.parallel-offen")
        def halten(*args):
            v = aktuell(*args)
            drin.set()
            self.assertTrue(weiter.wait(20))
            return v
        @contextmanager
        def eingang_starten():
            eingang.set()
            with atomar() as conn:
                yield conn
        normal = self.paket("messages", {"messaging_product": "whatsapp", "metadata": {"phone_number_id": self.nummer}, "messages": [n]})
        with patch.object(sync, "_aktuell", halten), patch.object(wa, "atomic_database", eingang_starten), patch.object(main, "process_chat_message") as chat, ThreadPoolExecutor(2) as pool:
            capture = pool.submit(self.erfassen, self.historie(teil=2, nachrichten=[n]))
            try:
                self.assertTrue(drin.wait(20))
                empfang = pool.submit(self.webhook, normal)
                self.assertTrue(eingang.wait(20))
            finally:
                weiter.set()
            capture.result(30)
            empfang.result(30)
            chat.assert_not_called()
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_capture_nach_dispatch_reservierung_stoppt_letzte_versandpruefung(self):
        self.fertig()
        ereignisgrundlage.EreignisFaelle.vorbereiten(self)
        reserviert, weiter = threading.Event(), threading.Event()
        original = wa.beginne_automatischen_transport
        def halten(*args):
            reserviert.set()
            self.assertTrue(weiter.wait(20))
            return original(*args)
        senden = Mock()
        with patch.object(wa, "beginne_automatischen_transport", halten), ThreadPoolExecutor(1) as pool:
            versand = pool.submit(ereignisgrundlage.EreignisFaelle.liefern, self, senden)
            try:
                self.assertTrue(reserviert.wait(20))
                self.erfassen(self.historie(teil=2, nachrichten=[]))
            finally:
                weiter.set()
            self.assertEqual(versand.result(30)["status"], "failed")
        senden.assert_not_called()
        sync.verarbeite_offene(self.wid)
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        erneut = ereignisgrundlage.EreignisFaelle.liefern(self, senden)
        self.assertTrue(erneut["already_dispatched"])
        senden.assert_not_called()

    def test_offene_arbeit_bleibt_auf_werkstatt_beschraenkt(self):
        self.fertig()
        wid, phone = "korrektur-" + uuid.uuid4().hex, str(uuid.uuid4().int)[:16]
        with db.atomic_database() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, 'Zweite Prüfwerkstatt')", (wid,))
        self.anschliessen(wid, phone)
        with db.atomic_database() as conn:
            v = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (wid,)).fetchone())
            sync.anlegen(conn, v, time.time())
            conn.execute("UPDATE whatsapp_sync SET zustand = 'angenommen', request_id = 'synthetisch-zweit' WHERE workshop_id = ?", (wid,))
        p = self.historie()
        p["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = phone
        self.webhook(p)
        self.assertTrue(sync.status(wid)["technisch_bereit"])
        self.erfassen(self.historie(teil=3, nachrichten=[]))
        self.assertTrue(sync.status(wid)["technisch_bereit"])
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        sync.verarbeite_offene(wid)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_alte_version_gibt_neue_weder_frei_noch_dauerhaft_gesperrt(self):
        self.fertig()
        self.erfassen(self.historie(teil=3, nachrichten=[]))
        # Neues verifiziertes Nummern-/Kontopaar; gleiche Paare bleiben nach
        # bestehendem Generationsschutz prüfpflichtig (Bestandsregression).
        self.nummer, self.konto = str(uuid.uuid4().int)[:16], str(uuid.uuid4().int)[:16]
        self.anschliessen()
        with db.atomic_database() as conn:
            self.v = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,)).fetchone())
            sync.anlegen(conn, self.v, time.time())
        for art in sync.ARTEN:
            sync.schritt(self.cookie, self.wid, "https://testserver", art)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        self.assertEqual(self.zustand()["zustand"], "angenommen")
        # Ausschließlich synthetischer Abschluss, während die alte Arbeit noch
        # im Journal steht: die alte Version darf diese Freigabe nicht sperren.
        with db.atomic_database() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_events WHERE workshop_id = ? AND event_type = 'sync_offen'",
                                          (self.wid,)).fetchone()["n"], 1)
            conn.execute("UPDATE whatsapp_sync SET zustand = 'abgeschlossen' WHERE workshop_id = ? AND version = ? AND art = 'history'",
                         (self.wid, self.v["version"]))
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        # Alte Teile mit 100 Prozent sind kein Liefernachweis der neuen Version.
        with db.atomic_database() as conn:
            conn.execute("UPDATE whatsapp_sync SET zustand = 'angenommen' WHERE workshop_id = ? AND version = ? AND art = 'history'",
                         (self.wid, self.v["version"]))
        self.erfassen(self.ablehnung())
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])
        sync.verarbeite_offene(self.wid)
        self.assertEqual(self.zustand()["zustand"], "nicht_geteilt")
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])

    def test_erstmalige_ablehnung_ohne_daten_und_duplikat_bleiben_bereit(self):
        self.route()
        p = self.ablehnung()
        self.webhook(p)
        self.erfassen(p)
        self.assertEqual(self.zustand()["zustand"], "nicht_geteilt")
        self.assertTrue(sync.status(self.wid)["technisch_bereit"])
        self.assertEqual(self.nachrichten(), [])

    def test_leerer_teil_bei_null_prozent_ist_liefernachweis(self):
        self.route()
        p = self.historie(fortschritt=0, nachrichten=[])
        self.webhook(p)
        self.webhook(p)
        self.webhook(self.ablehnung())
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_medien_vor_thread_bei_null_prozent_widersprechen_ablehnung(self):
        self.route()
        self.webhook(self.medium())
        self.assertEqual(self.zustand()["fortschritt"], 0)
        self.assertEqual(self.nachrichten(), [])
        self.webhook(self.ablehnung())
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_medien_zu_bekannter_nachricht_ohne_thread_bleiben_nachweis(self):
        self.route()
        wa.save_whatsapp_message(workshop_id=self.wid, customer_phone=self.kunde,
            phone_number_id=self.nummer, direction="inbound", message_type="media_placeholder",
            wa_message_id="wamid.historie", payload={}, status="received", processing_state="complete")
        self.webhook(self.medium())
        self.assertEqual(self.nachrichten()[0]["message_type"], "image")
        db.init_db()
        self.webhook(self.ablehnung())
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_gemischte_daten_und_ablehnung_im_wert_werden_vorab_abgewiesen(self):
        self.route()
        ablehnung = self.ablehnung()["entry"][0]["changes"][0]["value"]["history"][0]
        for zuerst in (True, False):
            p = self.historie(fortschritt=0)
            h = p["entry"][0]["changes"][0]["value"]["history"]
            h.insert(0 if zuerst else len(h), ablehnung)
            self.webhook(p, erwartet=422)
        p = self.medium()
        p["entry"][0]["changes"][0]["value"]["history"] = [ablehnung]
        self.webhook(p, erwartet=422)
        self.assertEqual(self.nachrichten(), [])
        self.assertEqual(self.zustand()["zustand"], "angenommen")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_daten_und_ablehnung_in_getrennten_changes_bleiben_widerspruch(self):
        self.route()
        p = self.historie(fortschritt=0)
        p["entry"][0]["changes"] += self.ablehnung()["entry"][0]["changes"]
        self.webhook(p)
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertEqual(len(self.nachrichten()), 1)
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])

    def test_ablehnung_vor_daten_im_selben_paket_gibt_nicht_frei(self):
        self.route()
        p = self.ablehnung()
        p["entry"][0]["changes"] += self.historie(fortschritt=0)["entry"][0]["changes"]
        with patch.object(main, "process_chat_message") as chat:
            self.webhook(p)
            chat.assert_not_called()
        self.assertEqual(self.zustand()["zustand"], "pruefung")
        self.assertFalse(sync.status(self.wid)["technisch_bereit"])


class SQLiteKorrekturen(KorrekturFaelle, unittest.TestCase):
    postgres = False


@unittest.skipUnless(os.environ.get("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank angegeben")
class PostgreSQLKorrekturen(KorrekturFaelle, unittest.TestCase):
    postgres = True
