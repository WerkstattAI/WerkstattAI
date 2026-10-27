"""Sichere Meta-Diagnose für Text und Vorlagen mit ausschließlich simuliertem HTTP."""
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import app.db as db
import test_whatsapp_verbindungen as verbindungspruefung
from app.manual_dispatch import send_workshop_message
from app.web import _meta_outbound_status, _meta_send_error
from app.whatsapp import WhatsAppSendResult, save_whatsapp_message, send_whatsapp_template_message, send_whatsapp_text_message
from verbindungsdaten import synthetische_verbindung


class MetaFehlerdiagnoseTests(unittest.TestCase):
    def setUp(self):
        verbindungspruefung.VerbindungsTests.setUp(self)
        self.token = "synthetischer-geheimer-zugang"
        self.fremdtext = "UNGEPRUEFTER-PROVIDERTEXT"
        self.telefon = "4915700012345"
        synthetische_verbindung(self.wid, "nummer-a", self.token)
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.telefon, direction="inbound", text="Test")
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open",
                                      side_effect=AssertionError("Echter HTTP-Transport ist gesperrt.")))

    def senden(self, art):
        daten = dict(workshop_id=self.wid, phone_number_id="nummer-a", customer_phone=self.telefon)
        if art == "text":
            return send_whatsapp_text_message(**daten, text="Synthetische Nachricht")
        return send_whatsapp_template_message(**daten, template_name="synthetische_vorlage", template_language="de")

    def http_fehler(self, inhalt, status=400):
        def antwort(*args, **kwargs):
            self.assertIsNone(db._TRANSACTION_CONNECTION.get(), "Keine Sperre über HTTP halten")
            raise urllib.error.HTTPError(f"https://example.invalid/{self.token}", status,
                self.fremdtext + self.token, {"X-Diagnose": self.token}, io.BytesIO(inhalt))
        return patch("urllib.request.urlopen", side_effect=antwort)

    def test_code_und_subcode_ohne_fremdtext_in_ergebnis_datenbank_oberflaeche_und_logs(self):
        inhalt = json.dumps({"error": {"code": 133010, "error_subcode": 2494010,
            "message": self.fremdtext + self.token, "error_data": {"details": self.token},
            "fbtrace_id": self.token}, "debug": self.token}).encode()
        for art in ("text", "template"):
            with self.subTest(art=art):
                ausgabe = io.StringIO()
                with self.http_fehler(inhalt) as http, self.assertNoLogs("app", level="DEBUG"), \
                        redirect_stdout(ausgabe), redirect_stderr(ausgabe):
                    ergebnis = send_workshop_message(workshop_id=self.wid, customer_phone=self.telefon,
                        phone_number_id="nummer-a", text="Synthetische Nachricht", purpose="workshop_notification",
                        reply_to_message_id=None, message_id=f"fehlerdiagnose-{art}", ticket_id=None,
                        send=lambda: self.senden(art), source="synthetischer_test", message_type=art)
                http.assert_called_once()
                self.assertFalse(ergebnis.ok)
                self.assertEqual(ergebnis.status_code, 400)
                self.assertEqual(ergebnis.payload, {"error": {"code": 133010, "error_subcode": 2494010}})
                meldung = _meta_send_error(ergebnis)
                self.assertIn("Meta-Code 133010", meldung)
                self.assertIn("Meta-Subcode 2494010", meldung)
                with db.get_conn() as conn:
                    zeile = dict(conn.execute("SELECT * FROM whatsapp_messages WHERE message_id = ?",
                                              (f"fehlerdiagnose-{art}",)).fetchone())
                self.assertEqual((zeile["status"], zeile["dispatch_state"]), ("failed", "complete"))
                gespeichert = json.loads(zeile["payload_json"])
                self.assertEqual(gespeichert["meta_response"], ergebnis.payload)
                for sichtbarer_inhalt in (repr(ergebnis), meldung, json.dumps(zeile), ausgabe.getvalue()):
                    self.assertNotIn(self.token, sichtbarer_inhalt)
                    self.assertNotIn(self.fremdtext, sichtbarer_inhalt)
                    self.assertNotIn("example.invalid", sichtbarer_inhalt)

    def test_ungueltige_antworten_und_typen_fallen_auf_http_status_zurueck(self):
        inhalte = [b"kein JSON", b"\xff", b"[]", b"null", b'"Text"', b'{"error": []}',
                   b'{"error": "Text"}', b'{"unbekannt": 133010}', b"x" * 65537]
        for wert in (True, False, None, "133010", 133010.0, [], {}, -1):
            inhalte.append(json.dumps({"error": {"code": wert, "error_subcode": wert,
                                                 "message": self.fremdtext + self.token}}).encode())
        for art in ("text", "template"):
            for index, inhalt in enumerate(inhalte):
                with self.subTest(art=art, fall=index), self.http_fehler(inhalt) as http:
                    ergebnis = self.senden(art)
                    http.assert_called_once()
                    self.assertEqual(ergebnis, WhatsAppSendResult(False, 400, None, {}, "Meta API HTTP 400"))
                    self.assertEqual(_meta_send_error(ergebnis), "Meta API HTTP 400")

    def test_diagnosefelder_werden_einzeln_typgeprueft_und_ohne_fremde_meldung_formatiert(self):
        faelle = [({"code": 133010}, {"code": 133010}, "Meta-Code 133010"),
                  ({"code": 133010, "error_subcode": "falsch"}, {"code": 133010}, "Meta-Code 133010"),
                  ({"code": True, "error_subcode": 7}, {"error_subcode": 7}, "Meta-Subcode 7"),
                  ({"code": 0}, {"code": 0}, "Meta-Code 0")]
        for art in ("text", "template"):
            for fehler, erwartet, text in faelle:
                with self.subTest(art=art, fehler=fehler), self.http_fehler(json.dumps({"error": fehler}).encode()):
                    ergebnis = self.senden(art)
                    self.assertEqual(ergebnis.payload, {"error": erwartet})
                    self.assertIn(text, _meta_send_error(ergebnis))
        # Auch ein alter, unbereinigter Ergebnisdatensatz darf keinen Providertext anzeigen.
        ergebnis = WhatsAppSendResult(False, 400, None,
            {"error": {"code": 133010, "message": self.token}}, "Meta API HTTP 400")
        self.assertIn("Meta-Code 133010", _meta_send_error(ergebnis))
        self.assertNotIn(self.token, _meta_send_error(ergebnis))

    def test_http_status_und_unbekannter_transportstatus_bleiben_erhalten(self):
        for art in ("text", "template"):
            for status in (400, 429, 503):
                with self.subTest(art=art, status=status), self.http_fehler(b"ungueltig", status):
                    ergebnis = self.senden(art)
                    self.assertEqual(ergebnis.status_code, status)
                    self.assertEqual(_meta_outbound_status(ergebnis), "failed")
            with self.subTest(art=art), patch("urllib.request.urlopen", side_effect=OSError(self.token)):
                ergebnis = self.senden(art)
                self.assertIsNone(ergebnis.status_code)
                self.assertEqual(_meta_outbound_status(ergebnis), "unknown")
                self.assertIn("Versandstatus ist unklar", _meta_send_error(ergebnis))
                self.assertNotIn(self.token, repr(ergebnis) + _meta_send_error(ergebnis))

    def test_unlesbarer_http_fehler_bleibt_bestaetigte_ablehnung(self):
        for art in ("text", "template"):
            with self.subTest(art=art):
                fehler = urllib.error.HTTPError("https://example.invalid", 400, "Fehler", {}, io.BytesIO())
                with patch.object(fehler, "read", side_effect=OSError(self.token)), \
                        patch("urllib.request.urlopen", side_effect=fehler):
                    ergebnis = self.senden(art)
                self.assertEqual(ergebnis, WhatsAppSendResult(False, 400, None, {}, "Meta API HTTP 400"))
