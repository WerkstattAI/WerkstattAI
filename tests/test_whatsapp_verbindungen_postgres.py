"""Transaktions- und Eindeutigkeitsprüfung nur auf einer wegwerfbaren PostgreSQL-Datenbank."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import app.db as db
import app.whatsapp_verbindungen as verbindungen
from verbindungsdaten import TESTSCHLUESSEL


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
