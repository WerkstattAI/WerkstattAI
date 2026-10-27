"""Echte PostgreSQL-Abschlüsse mit simuliertem Meta-HTTP auf Wegwerfdatenbank."""
import os
import unittest
import uuid
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import app.db as db
import app.whatsapp_anschluss as anschluss
from app.auth import SESSION_COOKIE, create_session_token
import test_whatsapp_anschluss as pruefung


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank eingerichtet")
class PostgreSQLAnschlussTests(unittest.TestCase):
    # Nur die Datenbank-spezifischen Integrationsfälle zusätzlich unter PostgreSQL.
    def setUp(self):
        pruefung.AnschlussTests.setUp(self)
        konfiguration = replace(self.config, database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"], app_env="development")
        self.stack.enter_context(patch.object(db, "settings", konfiguration))
        db.init_db()
        self.wid = "pg-anschluss-" + uuid.uuid4().hex
        self.user = {"email": self.wid + "@example.invalid", "workshop_id": self.wid, "role": "owner"}
        with db.get_conn() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?)", (self.wid, "Synthetischer Anschluss"))
            conn.execute("INSERT INTO users (email, role, workshop_id, password_hash) VALUES (?, 'owner', ?, 'synthetischer-passworthash')",
                         (self.user["email"], self.wid))
            conn.commit()
        self.cookie = create_session_token(self.user)
        self.client.cookies.set(SESSION_COOKIE, self.cookie)

    def tearDown(self):
        # Synthetische Nummern können im nächsten Fall wieder verwendet werden.
        with db.get_conn() as conn:
            conn.execute("DELETE FROM whatsapp_verbindungen WHERE workshop_id = ?", (self.wid,))
            conn.execute("UPDATE workshops SET whatsapp_phone_number_id = NULL WHERE id = ?", (self.wid,))
            conn.commit()


    post = pruefung.AnschlussTests.post
    start = pruefung.AnschlussTests.start
    abschluss = pruefung.AnschlussTests.abschluss
    dienst = pruefung.AnschlussTests.dienst
    test_erfolg_kette_chiffrat_version_und_gesperrte_betriebsbereitschaft = pruefung.AnschlussTests.test_erfolg_kette_chiffrat_version_und_gesperrte_betriebsbereitschaft
    test_zwei_abschluesse_verbrauchen_code_nur_einmal = pruefung.AnschlussTests.test_zwei_abschluesse_verbrauchen_code_nur_einmal
    test_widerruf_waehrend_abonnement_verhindert_verspaeteten_abschluss = pruefung.AnschlussTests.test_widerruf_waehrend_abonnement_verhindert_verspaeteten_abschluss
    test_rollenverlust_waehrend_http_verhindert_bestaetigung = pruefung.AnschlussTests.test_rollenverlust_waehrend_http_verhindert_bestaetigung
    test_abonnement_timeout_wird_ohne_neuen_code_abgeglichen = pruefung.AnschlussTests.test_abonnement_timeout_wird_ohne_neuen_code_abgeglichen

    def test_logout_und_dauerhafter_abschluss_werden_atomisch_geordnet(self):
        kennung = self.start()
        gelesen, weiter, logout_gestartet = threading.Event(), threading.Event(), threading.Event()
        original = db.PostgresConnection.execute
        finale_phase = threading.Event()
        logout_pid = []

        def meta_schritt(methode, pfad):
            if methode == "GET" and pfad.endswith("subscribed_apps") and self.meta.abonniert:
                finale_phase.set()

        class Haltepunkt:
            def __init__(self, cursor):
                self.cursor = cursor
            def fetchone(self):
                zeile = self.cursor.fetchone()
                gelesen.set()
                if not weiter.wait(15):
                    raise AssertionError("Abschluss nicht freigegeben")
                return zeile

        def execute(conn, sql, params=()):
            anweisung = " ".join(sql.split())
            if anweisung.startswith("UPDATE whatsapp_anschlussversuche SET zustand = 'abgebrochen'") and "sitzung_hash" in anweisung:
                logout_pid.append(conn._conn.info.backend_pid)
                logout_gestartet.set()
            cursor = original(conn, sql, params)
            if finale_phase.is_set() and not gelesen.is_set() and anweisung.startswith("SELECT * FROM whatsapp_anschlussversuche"):
                return Haltepunkt(cursor)
            return cursor

        self.meta.vor_aufruf = meta_schritt
        with patch.object(db.PostgresConnection, "execute", execute), ThreadPoolExecutor(max_workers=2) as pool:
            abschluss = pool.submit(self.dienst, kennung)
            try:
                self.assertTrue(gelesen.wait(10))
                logout = pool.submit(anschluss.sitzung_beenden, self.cookie)
                self.assertTrue(logout_gestartet.wait(10))
                # Auf den beobachteten Datenbankzustand warten, keine zufällige Schlafpause.
                blockiert = False
                frist = time.monotonic() + 10
                with db.get_conn() as conn:
                    while time.monotonic() < frist and not logout.done():
                        if conn.execute("SELECT cardinality(pg_blocking_pids(?)) AS n", (logout_pid[0],)).fetchone()["n"]:
                            blockiert = True
                            break
                self.assertTrue(blockiert, "Logout darf den bereits gesperrten Abschlusszustand nicht überholen")
            finally:
                weiter.set()
            self.assertEqual(abschluss.result(timeout=15)["zustand"], "abgeschlossen")
            logout.result(timeout=15)
