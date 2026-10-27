"""Transaktions- und Eindeutigkeitsprüfung nur auf einer wegwerfbaren PostgreSQL-Datenbank."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

import app.db as db
import app.whatsapp_verbindungen as verbindungen
from verbindungsdaten import TESTSCHLUESSEL


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank eingerichtet")
class PostgreSQLVersionswechselTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        konfiguration = replace(db.settings, database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"],
            app_env="development", whatsapp_zugangsschluessel=TESTSCHLUESSEL)
        self.stack.enter_context(patch.object(db, "settings", konfiguration))
        self.stack.enter_context(patch.object(verbindungen, "settings", konfiguration))
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open",
                                      side_effect=AssertionError("Echter HTTP-Transport ist gesperrt.")))
        db.init_db()
        self.wid = "pg-versionswechsel-" + uuid.uuid4().hex
        with db.get_conn() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (self.wid, "Synthetische Werkstatt"))
            conn.commit()
        self.assertEqual(self.entwurf("alt", 0), 1)

    def entwurf(self, nummer, version=1):
        return verbindungen.speichere_verbindungsentwurf(workshop_id=self.wid, waba_id="synthetische-waba",
            phone_number_id=f"{self.wid}-{nummer}", anzeigenummer=nummer, token="synthetischer-zugang",
            erwartete_version=version)

    def widerruf(self, version=1):
        return verbindungen.widerrufe_verbindung(self.wid, erwartete_version=version)

    def bestand(self):
        with db.get_conn() as conn:
            verbindung = dict(conn.execute("SELECT * FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,)).fetchone())
            werkstatt = dict(conn.execute("SELECT whatsapp_phone_number_id, whatsapp_display_phone_number FROM workshops WHERE id = ?",
                                         (self.wid,)).fetchone())
        return verbindung, werkstatt

    def gesteuerte_konkurrenz(self, erster, zweiter, *, erster_schreibt, zweiter_wartet=False):
        """Am Schreibpunkt pausieren, echte Transaktionen und Datenbanksperren behalten.

        Der Entwurf hält vor seiner Nummernänderung an, also nach dem Versionslesen.
        Beim Widerruf liegt der Haltepunkt vor seinem bedingten UPDATE. Kein SQL-Ergebnis
        wird vorgetäuscht; Ereignisse bestimmen die Reihenfolge ohne zufällige Wartezeit.
        """
        angehalten, fortsetzen, zweiter_an_sperre = (threading.Event() for _ in range(3))
        nummer_geschrieben = threading.Event()
        lokal = threading.local()
        original = db.PostgresConnection.execute

        def execute(conn, sql, params=()):
            anweisung = " ".join(sql.upper().split())
            rolle = getattr(lokal, "rolle", None)
            if rolle == "erster" and anweisung.startswith(f"UPDATE {erster_schreibt.upper()} SET "):
                angehalten.set()
                if not fortsetzen.wait(15):
                    raise AssertionError("Freigabe des Schreibpunkts fehlt")
            if (rolle == "zweiter" and anweisung.startswith("SELECT ")
                    and " FROM WORKSHOPS " in anweisung and "FOR UPDATE" in anweisung):
                zweiter_an_sperre.set()
            cursor = original(conn, sql, params)
            if rolle == "erster" and anweisung.startswith("UPDATE WORKSHOPS SET "):
                nummer_geschrieben.set()
            return cursor

        def ausfuehren(rolle, aktion):
            lokal.rolle = rolle
            try:
                return aktion()
            except verbindungen.VerbindungsFehler as fehler:
                return fehler

        with patch.object(db.PostgresConnection, "execute", execute), ThreadPoolExecutor(max_workers=2) as pool:
            erster_lauf = pool.submit(ausfuehren, "erster", erster)
            try:
                self.assertTrue(angehalten.wait(15), "Erster Schreibpunkt nicht erreicht")
                zweiter_lauf = pool.submit(ausfuehren, "zweiter", zweiter)
                if zweiter_wartet:
                    # Der erste Entwurf besitzt bereits die Werkstattsperre.
                    self.assertTrue(zweiter_an_sperre.wait(15), "Zweiter Entwurf erreicht die Sperre nicht")
                else:
                    zweites_ergebnis = zweiter_lauf.result(timeout=15)
                    self.assertNotIsInstance(zweites_ergebnis, verbindungen.VerbindungsFehler)
                    zwischenstand = self.bestand()
            finally:
                fortsetzen.set()
            erstes_ergebnis = erster_lauf.result(timeout=15)
            zweites_ergebnis = zweiter_lauf.result(timeout=15)
        if zweiter_wartet:
            return erstes_ergebnis, zweites_ergebnis
        if erster_schreibt == "workshops":
            self.assertTrue(nummer_geschrieben.is_set(), "Rollback muss eine tatsächlich geschriebene Nummer zurücknehmen")
        self.assertEqual(self.bestand(), zwischenstand, "Abgelehnte Mutation verändert den bestätigten Bestand")
        return erstes_ergebnis, zweites_ergebnis

    def test_bestaetigter_widerruf_weist_bereits_gelesenen_entwurf_ab(self):
        _, vorherige_bindung = self.bestand()
        entwurf, widerruf = self.gesteuerte_konkurrenz(lambda: self.entwurf("veraltet"), self.widerruf,
                                                     erster_schreibt="workshops")
        self.assertIsInstance(entwurf, verbindungen.VerbindungsFehler)
        self.assertIsNone(widerruf)
        verbindung, bindung = self.bestand()
        self.assertEqual(bindung, vorherige_bindung)
        self.assertEqual((verbindung["version"], verbindung["autorisierung"], verbindung["zustand"]),
                         (2, "widerrufen", "widerrufen"))
        self.assertIsNone(verbindung["zugang_verschluesselt"])
        self.assertEqual(verbindung["coexistence_bereit"], 0)
        # Ein bewusster Neuanschluss mit aktueller Version bleibt möglich.
        self.assertEqual(self.entwurf("neu", 2), 3)
        self.widerruf(3)
        self.assertEqual(self.bestand()[0]["version"], 4)

    def test_bestaetigter_entwurf_weist_bereits_gestarteten_widerruf_ab(self):
        widerruf, entwurf = self.gesteuerte_konkurrenz(self.widerruf, lambda: self.entwurf("neu"),
                                                     erster_schreibt="whatsapp_verbindungen")
        self.assertIsInstance(widerruf, verbindungen.VerbindungsFehler)
        self.assertEqual(entwurf, 2)
        verbindung, bindung = self.bestand()
        self.assertEqual((verbindung["version"], verbindung["autorisierung"], verbindung["zustand"]),
                         (2, "unbestaetigt", "vorbereitet"))
        self.assertIsNotNone(verbindung["zugang_verschluesselt"])
        self.assertEqual(bindung["whatsapp_phone_number_id"], f"{self.wid}-neu")

    def test_zwei_entwuerfe_nur_ein_versionswechsel_und_eine_nummernbindung(self):
        erster, zweiter = self.gesteuerte_konkurrenz(lambda: self.entwurf("erster"), lambda: self.entwurf("zweiter"),
            erster_schreibt="workshops", zweiter_wartet=True)
        self.assertEqual(erster, 2)
        self.assertIsInstance(zweiter, verbindungen.VerbindungsFehler)
        verbindung, bindung = self.bestand()
        self.assertEqual(verbindung["version"], 2)
        self.assertEqual(verbindung["phone_number_id"], f"{self.wid}-erster")
        self.assertEqual(bindung["whatsapp_phone_number_id"], verbindung["phone_number_id"])
        self.assertEqual(bindung["whatsapp_display_phone_number"], "erster")
        self.assertEqual(self.entwurf("zweiter", 2), 3)


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank eingerichtet")
class PostgreSQLVerbindungsTests(unittest.TestCase):
    def test_migration_eindeutigkeit_konkurrenz_und_versionsschutz(self):
        import psycopg
        konfiguration = replace(db.settings, database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"],
            app_env="development", whatsapp_zugangsschluessel=TESTSCHLUESSEL)
        with patch.object(db, "settings", konfiguration), patch.object(verbindungen, "settings", konfiguration):
            db.init_db()
            db.init_db()
            with db.get_conn() as conn:
                for wid in ("pg-verbindung-a", "pg-verbindung-b"):
                    conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (wid, wid))
                conn.commit()
            def speichern(wid, nummer, version=0):
                return verbindungen.speichere_verbindungsentwurf(workshop_id=wid, waba_id="pg-gemeinsames-konto",
                    phone_number_id=nummer, anzeigenummer="", token="pg-synthetischer-zugang", erwartete_version=version)
            barriere = threading.Barrier(2)
            def gleichzeitig(wid):
                barriere.wait(timeout=10)
                try:
                    speichern(wid, "pg-gleiche-nummer")
                    return wid
                except verbindungen.VerbindungsFehler:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                ergebnisse = list(pool.map(gleichzeitig, ["pg-verbindung-a", "pg-verbindung-b"]))
            gewinner = next(wid for wid in ergebnisse if wid)
            self.assertEqual(sum(bool(wid) for wid in ergebnisse), 1)
            anderer = "pg-verbindung-b" if gewinner == "pg-verbindung-a" else "pg-verbindung-a"
            speichern(anderer, "pg-zweite-nummer")
            with self.assertRaises(psycopg.errors.UniqueViolation), db.get_conn() as conn:
                conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ? WHERE id = ?", ("\tpg-gleiche-nummer\n", anderer))
            with db.get_conn() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM whatsapp_verbindungen WHERE waba_id = 'pg-gemeinsames-konto'").fetchone()["n"], 2)
            # Ein Altduplikat wird ohne Auswahl eines Besitzers abgelehnt; DDL und Daten rollen zurück.
            with self.assertRaises(verbindungen.VerbindungsFehler), db.get_conn() as conn:
                conn.execute("DROP INDEX idx_workshops_whatsapp_nummer_eindeutig")
                conn.execute("UPDATE workshops SET whatsapp_phone_number_id = ' pg-gleiche-nummer ' WHERE id = ?", (anderer,))
                verbindungen.migriere_verbindungen(conn, konfiguration)
            db.init_db()
            barriere = threading.Barrier(2)
            def aendern(index):
                barriere.wait(timeout=10)
                try:
                    return speichern(gewinner, f"pg-neue-nummer-{index}", 1)
                except verbindungen.VerbindungsFehler:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                versionen = list(pool.map(aendern, [1, 2]))
            self.assertEqual(sum(v == 2 for v in versionen), 1)
            verbindungen.widerrufe_verbindung(gewinner, erwartete_version=2)
            with self.assertRaises(verbindungen.VerbindungsFehler):
                verbindungen.widerrufe_verbindung(gewinner, erwartete_version=2)
