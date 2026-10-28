"""Unveränderte fachliche Gegenproben und ergänzende regressionsfeste Klärungsfälle."""
import json
import os
import time
import unittest
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import app.db as db
import app.whatsapp as wa
import app.whatsapp_ereignisse as ereignisse
from app.models import IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket, set_ticket_conversation_state
from app.dispatch_recovery import resolve_stale_dispatch
import test_whatsapp_ereignisse as grundlage


class GegenprobenFaelle:
    def test_unbekanntes_altes_echo_darf_bewusstes_fortsetzen_nicht_aufheben(self):
        paket = self.paket()
        echo = paket["entry"][0]["changes"][0]["value"]["message_echoes"][0]
        echo.update(id="wamid.bereits-bekannt", timestamp=str(int(time.time()) - 5))
        self.webhook(paket)
        self.assertEqual(self.kontrolle()["mode"], "manual")
        vorher = self.fortsetzen()
        # Andere, bisher ungesehene Nachricht: tatsächlich vor der bereits
        # bekannten Telefonantwort und vor dem bewussten Fortsetzen gesendet.
        echo.update(id="wamid.verspaetet-alt", timestamp=str(int(time.time()) - 30))
        self.webhook(paket)
        nachher = self.kontrolle()
        self.assertEqual(nachher["revision"], vorher["revision"],
                         "Ältere Telefonaktion hat die spätere bewusste Freigabe überschrieben")
        self.assertEqual(nachher["mode"], "assistant")

    def test_recovery_sent_ohne_provider_id_macht_echo_nicht_eindeutig_extern(self):
        self.vorbereiten()
        def senden(reply):
            # Die API hat angenommen und ein Echo ausgelöst; die HTTP-Antwort
            # geht verloren. Lokal bleibt die Provider-ID unbekannt.
            self.webhook(self.paket())
            return wa.WhatsAppSendResult(False, None, None, {})
        self.assertEqual(self.liefern(senden)["status"], "unknown")
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        with db.get_conn() as conn:
            original = dict(conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND dispatch_state = 'sending'",
                                         (self.wid,)).fetchone())
            conn.execute("UPDATE whatsapp_messages SET dispatch_started_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(), original["id"]))
            conn.commit()
        ergebnis = resolve_stale_dispatch(workshop_id=self.wid, message_id=original["message_id"],
                                         resolution="sent", actor_email="pruefung@example.invalid", confirmed=True)
        self.assertEqual(ergebnis["status"], "sent")
        self.assertIsNone(ergebnis["wa_message_id"])
        echo = next(m for m in self.nachrichten() if json.loads(m["payload_json"]).get("source") == "whatsapp_business_app")
        self.assertTrue(echo["echo_zuordnung_offen"],
                        "Erfolgsbestätigung ohne Provider-ID beweist nicht, dass dieses Echo eine fremde Telefonaktion war")


class WeitereKorrekturFaelle:
    def echo(self, kennung, zeit):
        paket = self.paket()
        paket["entry"][0]["changes"][0]["value"]["message_echoes"][0].update(id=kennung, timestamp=str(zeit))
        return paket

    def freigabe(self, zeit):
        with patch.object(db, "datetime", wraps=datetime) as uhr:
            uhr.now.return_value = datetime.fromtimestamp(zeit, timezone.utc)
            return self.fortsetzen()

    def unklarer_versand(self):
        self.vorbereiten()
        def senden(reply):
            self.webhook(self.paket())
            return wa.WhatsAppSendResult(False, None, None, {})
        self.assertEqual(self.liefern(senden)["status"], "unknown")
        with db.get_conn() as conn:
            zeile = dict(conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND dispatch_state = 'sending'",
                                     (self.wid,)).fetchone())
            zeit = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
            conn.execute("UPDATE whatsapp_messages SET dispatch_started_at = ? WHERE id = ?", (zeit, zeile["id"]))
            conn.commit()
        zeile["dispatch_started_at"] = zeit
        return zeile

    def bestaetigen(self, zeile, status="sent"):
        return resolve_stale_dispatch(workshop_id=self.wid, message_id=zeile["message_id"], resolution=status,
                                      actor_email="pruefung@example.invalid", confirmed=True)

    def test_neue_telefonantwort_nach_freigabe_uebernimmt_alte_nicht(self):
        zeit = int(time.time())
        vorher = self.freigabe(zeit - 10)
        self.webhook(self.echo("wamid.alt", zeit - 30))
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertFalse(self.nachrichten()[0]["echo_zuordnung_offen"])
        self.webhook(self.echo("wamid.neu", zeit - 5))
        self.assertEqual(self.kontrolle()["mode"], "manual")
        self.assertGreater(self.kontrolle()["revision"], vorher["revision"])

    def test_gleiche_sekunde_bleibt_offen_ohne_fachliche_uebernahme(self):
        zeit = int(time.time()) - 10
        vorher = self.freigabe(zeit + 0.4)
        paket = self.echo("wamid.gleiche-sekunde", zeit)
        self.webhook(paket)
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertEqual(self.kontrolle()["mode"], "assistant")
        self.assertTrue(self.nachrichten()[0]["echo_zuordnung_offen"])
        quittiert = self.fortsetzen()
        self.webhook(paket)
        self.assertFalse(self.nachrichten()[0]["echo_zuordnung_offen"])
        self.assertEqual(self.kontrolle()["revision"], quittiert["revision"])

    def test_alte_erste_zustellung_parallel_und_in_neuem_prozess(self):
        self.direkt = True
        zeit = int(time.time())
        vorher = self.freigabe(zeit - 10)
        paket = self.echo("wamid.parallel-alt", zeit - 30)
        barriere = threading.Barrier(2)
        original = ereignisse._verbindung
        def lesen(*args):
            ergebnis = original(*args)
            barriere.wait(15)
            return ergebnis
        with patch.object(ereignisse, "_verbindung", lesen), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.webhook, [paket, paket]))
        self.assertEqual(len(self.nachrichten()), 1)
        # Neue Provider-ID im neuen Prozess: auch die Freigabegrenze muss persistent sein.
        paket = self.echo("wamid.neuer-prozess-alt", zeit - 25)
        code = """
import json, os, sys
from dataclasses import replace
import app.db as db
db.settings = replace(db.settings, database_url=os.environ.get('WERKSTATTAI_TEST_POSTGRES_URL') if sys.argv[2] == 'pg' else None)
from app.whatsapp_ereignisse import verarbeite_echo
eintrag = json.loads(sys.argv[1])['entry'][0]
verarbeite_echo(eintrag, eintrag['changes'][0]['value'])
"""
        lauf = subprocess.run([sys.executable, "-c", code, json.dumps(paket), "pg" if self.postgres else "sqlite"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(lauf.returncode, 0, "Unterprozess der isolierten Echo-Prüfung fehlgeschlagen")
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertEqual(self.kontrolle()["mode"], "assistant")
        self.assertEqual(len(self.nachrichten()), 2)
        self.assertFalse(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))

    def test_erste_zustellung_wartet_auf_transaktionale_freigabe(self):
        self.direkt = True
        gehalten, weiter, echo_gelesen = threading.Event(), threading.Event(), threading.Event()
        merken = db.merke_assistentenfreigabe
        lesen = ereignisse._verbindung
        def freigeben(*args):
            merken(*args)
            gehalten.set()
            self.assertTrue(weiter.wait(15))
        def zuordnung(*args):
            wert = lesen(*args)
            echo_gelesen.set()
            return wert
        with patch.object(db, "merke_assistentenfreigabe", freigeben), patch.object(ereignisse, "_verbindung", zuordnung), ThreadPoolExecutor(max_workers=2) as pool:
            freigabe = pool.submit(self.fortsetzen)
            self.assertTrue(gehalten.wait(15))
            echo = pool.submit(self.webhook, self.echo("wamid.wartend-alt", int(time.time()) - 20))
            self.assertTrue(echo_gelesen.wait(15))
            weiter.set()
            vorher = freigabe.result(15)
            echo.result(15)
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertEqual(self.kontrolle()["mode"], "assistant")

    def test_ticket_freigabe_merkt_nur_ausdrueckliche_entscheidung(self):
        tid = save_ticket(IntakeState(telefon=self.kunde, name="Prüfkunde"), workshop_id=self.wid, verified_customer_phone=self.kunde)
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde, mode="manual", active_ticket_id=tid)
        set_ticket_conversation_state(tid, "assistant_active", self.wid)
        vorher = self.kontrolle()
        self.assertIsNotNone(vorher["assistent_freigegeben_am"])
        add_ticket_note(tid, "Interne Prüfung", workshop_id=self.wid, purpose="internal_note")
        self.assertEqual(self.kontrolle()["assistent_freigegeben_am"], vorher["assistent_freigegeben_am"])
        self.webhook(self.echo("wamid.ticket-alt", int(time.time()) - 20))
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertEqual(len(find_ticket_by_id(tid, self.wid)["notes"]), 1)
        self.assertEqual(find_ticket_by_id(tid, self.wid)["status"], "offen")

    def test_automatische_wiederherstellung_ist_keine_freigabe(self):
        from app.manual_dispatch import send_workshop_message
        result = send_workshop_message(workshop_id=self.wid, phone_number_id=self.nummer, customer_phone=self.kunde,
            text="Prüfung", purpose="workshop_notification", reply_to_message_id=None, message_id="fehlversand-0001",
            ticket_id=None, source="test", message_type="template", send=lambda: wa.WhatsAppSendResult(False, 400, None, {}))
        self.assertFalse(result.ok)
        self.assertEqual(self.kontrolle()["mode"], "assistant")
        self.assertIsNone(self.kontrolle()["assistent_freigegeben_am"])
        self.webhook(self.echo("wamid.vor-fehlversand", int(time.time()) - 10))
        self.assertEqual(self.kontrolle()["mode"], "manual")

    def test_recovery_sent_quittierung_und_wiederholte_zustellung(self):
        original = self.unklarer_versand()
        vorher = self.kontrolle()
        self.bestaetigen(original)
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        quittiert = self.fortsetzen()
        self.webhook(self.paket())
        self.assertEqual(self.kontrolle()["revision"], quittiert["revision"])
        self.assertFalse(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        senden = Mock()
        self.liefern(senden)
        senden.assert_not_called()

    def test_recovery_sent_spaetere_passende_provider_id_verknuepft_nur(self):
        original = self.unklarer_versand()
        self.bestaetigen(original)
        vorher = self.kontrolle()
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=original["message_id"], status="sent",
            wa_message_id="wamid.telefon", expected_dispatch_started_at=original["dispatch_started_at"])
        ausgang = [m for m in self.nachrichten() if m["direction"] == "outbound"]
        self.assertEqual(len(ausgang), 1)
        self.assertEqual(ausgang[0]["message_id"], original["message_id"])
        self.assertEqual(ausgang[0]["sender_role"], "assistant")
        self.assertEqual(json.loads(ausgang[0]["payload_json"])["manual_resolution"]["resolution"], "sent")
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])

    def test_spaete_provider_id_nach_quittierung_aendert_keine_freigabe(self):
        original = self.unklarer_versand()
        self.bestaetigen(original)
        vorher = self.fortsetzen()
        # Ein fremder/veralteter Transportlauf darf auch keine Identität nachtragen.
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=original["message_id"], status="sent",
            wa_message_id="wamid.telefon", expected_dispatch_started_at="anderer-transport")
        self.assertEqual(len([m for m in self.nachrichten() if m["direction"] == "outbound"]), 2)
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=original["message_id"], status="sent",
            wa_message_id="wamid.telefon", expected_dispatch_started_at=original["dispatch_started_at"])
        self.webhook(self.paket())
        self.assertEqual(len([m for m in self.nachrichten() if m["direction"] == "outbound"]), 1)
        self.assertEqual(self.kontrolle()["revision"], vorher["revision"])

    def test_recovery_sent_ohne_id_erzeugt_keine_ticketnotiz(self):
        tid = save_ticket(IntakeState(telefon=self.kunde, name="Prüfkunde"), workshop_id=self.wid, verified_customer_phone=self.kunde)
        db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.kunde, mode="assistant",
                                            active_ticket_id=tid, ausdrueckliche_freigabe=False)
        original = self.unklarer_versand()
        vorher = find_ticket_by_id(tid, self.wid)
        self.bestaetigen(original)
        self.assertEqual(find_ticket_by_id(tid, self.wid)["notes"], vorher["notes"])
        self.assertEqual(find_ticket_by_id(tid, self.wid)["conversation_state"], vorher["conversation_state"])
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))

    def test_erstes_echo_nach_recovery_erfolg_ohne_id_bleibt_offen(self):
        self.vorbereiten()
        self.liefern(lambda reply: wa.WhatsAppSendResult(False, None, None, {}))
        with db.get_conn() as conn:
            original = dict(conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND dispatch_state = 'sending'", (self.wid,)).fetchone())
            conn.execute("UPDATE whatsapp_messages SET dispatch_started_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(), original["id"]))
            conn.commit()
        self.bestaetigen(original)
        self.webhook(self.paket())
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        self.assertEqual(self.kontrolle()["mode"], "assistant")

    def test_recovery_sent_andere_provider_id_belegt_externes_echo(self):
        original = self.unklarer_versand()
        self.bestaetigen(original)
        wa.finalize_whatsapp_dispatch(workshop_id=self.wid, message_id=original["message_id"], status="sent",
            wa_message_id="wamid.tatsaechlicher-api-versand", expected_dispatch_started_at=original["dispatch_started_at"])
        self.assertEqual(self.kontrolle()["mode"], "manual")
        self.assertFalse(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))

    def test_recovery_sent_und_echo_parallel_bleiben_ungeklaert(self):
        self.direkt = True
        original = self.unklarer_versand()
        barriere = threading.Barrier(2)
        def bestaetigen():
            barriere.wait(15)
            return self.bestaetigen(original)
        def echo():
            barriere.wait(15)
            return self.webhook(self.paket())
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(bestaetigen), pool.submit(echo)
            a.result(15)
            b.result(15)
        self.assertTrue(any(m["echo_zuordnung_offen"] for m in self.nachrichten()))
        self.assertEqual(len([m for m in self.nachrichten() if m["direction"] == "outbound"]), 2)

    def test_zwei_werkstaetten_haben_getrennte_freigaben(self):
        self.freigabe(int(time.time()) - 10)
        wid = self.wid + "-zweite"
        phone = self.nummer + "1"
        with db.get_conn() as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, 'Zweite Prüfung')", (wid,))
            conn.commit()
        self.anschliessen(wid, phone)
        paket = self.echo("wamid.gleicher-kunde-zweite-werkstatt", int(time.time()) - 30)
        paket["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = phone
        self.webhook(paket)
        self.assertEqual(self.kontrolle()["mode"], "assistant")
        self.assertEqual(db.get_whatsapp_conversation_control(workshop_id=wid, customer_phone=self.kunde)["mode"], "manual")


class SQLiteGegenproben(GegenprobenFaelle, WeitereKorrekturFaelle, unittest.TestCase):
    postgres = False
    setUp = grundlage.EreignisFaelle.setUp
    anschliessen = grundlage.EreignisFaelle.anschliessen
    paket = grundlage.EreignisFaelle.paket
    webhook = grundlage.EreignisFaelle.webhook
    nachrichten = grundlage.EreignisFaelle.nachrichten
    kontrolle = grundlage.EreignisFaelle.kontrolle
    fortsetzen = grundlage.EreignisFaelle.fortsetzen
    vorbereiten = grundlage.EreignisFaelle.vorbereiten
    liefern = grundlage.EreignisFaelle.liefern


@unittest.skipUnless(os.getenv("WERKSTATTAI_TEST_POSTGRES_URL"), "Keine isolierte PostgreSQL-Prüfdatenbank eingerichtet")
class PostgreSQLGegenproben(SQLiteGegenproben):
    postgres = True
