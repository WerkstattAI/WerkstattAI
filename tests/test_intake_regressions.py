from __future__ import annotations

import gc
import os
import tempfile
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

import test_conversation_flows  # Isolated application configuration, never customer data.
import test_whatsapp_reliability as whatsapp_fixture
from fastapi.testclient import TestClient

from app.config import settings
from app.conversation.analysis import analyze_problem
from app.conversation.extractors import extract_km
from app.conversation.intent import detect_intent, INTENT_EXISTING_TICKET, INTENT_NEW_REQUEST, INTENT_UNCLEAR
from app.conversation.router import next_step
from app.conversation_sessions import load_session_state, save_session_state
from app.customer_access import CustomerAccess
from app.db import get_conn, init_db
from app.main import app, process_chat_message, whatsapp_session_id
from app.models import IntakeState
from app.tickets import find_ticket_by_id
from app.whatsapp import WhatsAppSendResult, list_whatsapp_messages


L01_CANCEL_COMMANDS = (
    "ich würde gerne abbrechen", "ich möchte die Anfrage jetzt abbrechen",
    "ich möchte bitte abbrechen", "ich würde gern abbrechen",
    "bitte die Anfrage jetzt abbrechen!",
)


class IntakeScenarios:
    def test_l01_polite_cancellation_preserves_previous_ticket_and_restarts(self):
        first = self.finish(("VW Golf 2016 120000 km", "Ölwechsel", "0000000000", "Erster Kunde"))
        for quote in (False, True):
            for name in (False, True):
                for command in L01_CANCEL_COMMANDS:
                    with self.subTest(quote=quote, name=name, command=command):
                        self.send("Problem melden")
                        if quote:
                            # A fresh quote, without an existing new-intake mode.
                            self.send("abbrechen")
                        self.start_contact(quote, name)
                        count = self.ticket_count()
                        with patch("app.main.save_ticket", side_effect=AssertionError("Unexpected completion")) as save:
                            result = self.send(command)
                            save.assert_not_called()
                        self.assert_open_without_completion(result, count)
                        self.assertEqual(result.data["mode"], "unknown")
                        self.assertIn("abgebrochen", result.reply)
                        for field in ("fahrzeug", "baujahr", "kilometerstand", "problem", "telefon", "name",
                                      "fahrbereit", "abschleppdienst", "pending_request_message"):
                            self.assertIsNone(result.data[field], field)
                        self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)
        ticket = self.finish(("Audi A4 2018 90000 km", "Reifenwechsel", "0000000001", "Neuer Kunde"))
        self.assert_saved_intake(ticket, vehicle="Audi A4", year="2018", km="90000",
                                 problem="Reifenwechsel", phone="0000000001")
        self.assertEqual(self.ticket_count(), self.count_before + 2)
        self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)

    def test_l02_compact_vehicle_facts_and_repeated_mileage_are_saved(self):
        for message in ("VW Golf 2016,120000 km", "VW Golf,2016,120000 km", "VW Golf 2016:120000 km"):
            for repeat in (False, True):
                with self.subTest(message=message, repeat=repeat):
                    self.sid = uuid.uuid4().hex
                    count = self.ticket_count()
                    result = self.send(message)
                    self.assertEqual(result.data["fahrzeug"], "VW Golf")
                    self.assertEqual(result.data["baujahr"], "2016")
                    self.assertEqual(result.data["kilometerstand"], "120000")
                    self.assertEqual(result.data["step"], "problem")
                    self.assertIn("Anliegen", result.reply)
                    if repeat:
                        result = self.send("120000 km")
                        self.assertEqual(result.data["step"], "problem")
                        self.assertIsNone(result.data["problem"])
                    self.assert_open_without_completion(result, count)
                    ticket = self.finish(("Ölwechsel", "0000000000", "Testkunde"))
                    self.assert_saved_intake(ticket)
                    self.assertEqual(self.ticket_count(), count + 1)

    def test_l02_compact_facts_preserve_numeric_and_unknown_models(self):
        for vehicle in ("BMW 320", "Mercedes E 220", "Peugeot 2008", "Fiat 500", "Tesla Model 3", "Testmarke Q 170"):
            self.sid = uuid.uuid4().hex
            result = self.send(vehicle + ",2020,8500 km")
            self.assertEqual(result.data["fahrzeug"], vehicle)
            self.assertEqual(result.data["step"], "problem")
            ticket = self.finish(("Ölwechsel", "0000000000", "Testkunde"))
            self.assert_saved_intake(ticket, vehicle=vehicle, year="2020", km="8500")

    def start_contact(self, quote=False, name=True):
        if quote:
            self.send("was kostet Ölwechsel")
        self.send("VW Golf 2016 120000 km")
        if not quote:
            self.send("Ölwechsel")
        if name:
            self.send("0000000000")

    def assert_open_without_completion(self, result, count):
        self.assertFalse(result.done)
        self.assertIsNone(result.data["ticket_id"])
        self.assertEqual(self.ticket_count(), count)
        self.assertEqual(result.data["workshop_messages"], [])
        self.assertNotIn("Ticket-Nr.", result.reply)

    def test_b01_natural_cancellation_and_fresh_restart(self):
        for quote in (False, True):
            for name in (False, True):
                for command in ("ich möchte abbrechen", "bitte die Anfrage abbrechen!", "doch abbrechen."):
                    with self.subTest(quote=quote, name=name, command=command):
                        self.sid = uuid.uuid4().hex
                        self.start_contact(quote, name)
                        count = self.ticket_count()
                        with patch("app.main.save_ticket", side_effect=AssertionError("Unexpected ticket completion")) as save:
                            result = self.send(command)
                            save.assert_not_called()
                        self.assert_open_without_completion(result, count)
                        self.assertEqual(result.data["mode"], "unknown")
                        self.assertIn("abgebrochen", result.reply)
                        for field in ("fahrzeug", "baujahr", "kilometerstand", "problem", "telefon", "name"):
                            self.assertIsNone(result.data[field], field)
                        ticket = self.finish(("Audi A4 2018 90000 km", "Reifenwechsel", "0000000001", "Jörg Müller"))
                        self.assert_saved_intake(ticket, vehicle="Audi A4", year="2018", km="90000",
                                                 problem="Reifenwechsel", phone="0000000001")

    def test_b01_negation_and_broken_key_do_not_cancel(self):
        for quote in (False, True):
            for message in ("ich möchte nicht abbrechen", "nicht abbrechen", "der Schlüssel ist abgebrochen"):
                with self.subTest(quote=quote, message=message):
                    self.sid = uuid.uuid4().hex
                    self.start_contact(quote, name=False)
                    result = self.send(message)
                    self.assertEqual(result.data["mode"], "quote" if quote else "new")
                    self.assertEqual(result.data["fahrzeug"], "VW Golf")
                    self.assertNotIn("Aufnahme ist abgebrochen", result.reply)
                    ticket = self.finish(("0000000000", "Jörg Müller"))
                    self.assertEqual(ticket["name"], "Jörg Müller")

    def test_b02_contact_corrections_in_both_flows(self):
        for quote in (False, True):
            for correction in ("nein! meine nummer ist 0000000001", "nein, meine nummer: 0000000001",
                               "meine neue nummer ist 0000000001", "nein meine Handynummer ist 0000000001",
                               "Nein, meine Telefonnummer lautet 0000000001", "nein meine rufnummer ist 0000000001",
                               "sorry, ich meinte 0000000001"):
                with self.subTest(quote=quote, correction=correction):
                    self.sid = uuid.uuid4().hex
                    self.start_contact(quote)
                    count = self.ticket_count()
                    result = self.send(correction)
                    self.assert_open_without_completion(result, count)
                    self.assertEqual(result.data["telefon"], "0000000001")
                    self.assertIsNone(result.data["name"])
                    self.assertEqual(result.data["step"], "quote_name" if quote else "name")
                    self.assertIn("ansprechen", result.reply)
                    ticket = self.finish(("Testkunde",))
                    self.assert_saved_intake(ticket, phone="0000000001",
                        problem="was kostet Ölwechsel" if quote else "Ölwechsel",
                        request_type="kostenvoranschlag" if quote else "service")
                    self.assertEqual(self.ticket_count(), count + 1)

    def test_b02_invalid_contact_corrections_preserve_phone(self):
        for message in ("nein", "meine neue Handynummer ist 123", "nein meine nummer: ungültig",
                        "meine neue Handynummer ist ungültig",
                        "Baujahr 2016", "120000 km", "BMW 320"):
            self.sid = uuid.uuid4().hex
            self.start_contact()
            count = self.ticket_count()
            result = self.send(message)
            self.assertEqual(result.data["telefon"], "0000000000", message)
            if message != "nein":  # Existing optional-name opt-out.
                self.assert_open_without_completion(result, count)

    def test_b02_contact_correction_before_vehicle_in_both_flows(self):
        for quote in (False, True):
            self.sid = uuid.uuid4().hex
            request = "was kostet Ölwechsel" if quote else "Ölwechsel"
            self.send(request + " Telefonnummer 0000000000")
            result = self.send("meine neue Handynummer ist 0000000001")
            self.assertEqual(result.data["telefon"], "0000000001")
            self.assertEqual(result.data["step"], "quote_fahrzeug" if quote else "fahrzeug")
            ticket = self.finish(("VW Golf 2016 120000 km", "Testkunde"))
            self.assert_saved_intake(ticket, phone="0000000001", problem=request,
                                     request_type="kostenvoranschlag" if quote else "service")

    def test_b03_known_vehicle_at_name_step(self):
        for quote in (False, True):
            for repeated in ("VW Golf", "vw golf!", " VW   GOLF. "):
                with self.subTest(quote=quote, repeated=repeated):
                    self.sid = uuid.uuid4().hex
                    self.start_contact(quote)
                    count = self.ticket_count()
                    result = self.send(repeated)
                    self.assert_open_without_completion(result, count)
                    self.assertIsNone(result.data["name"])
                    self.assertEqual(result.data["step"], "quote_name" if quote else "name")
                    self.assertIn("ansprechen", result.reply)
                    ticket = self.finish(("Jörg Müller",))
                    self.assertEqual(ticket["name"], "Jörg Müller")
                    self.assertEqual(ticket["fahrzeug"], "VW Golf")
                    self.assertEqual(self.ticket_count(), count + 1)

    def test_b03_explicit_introduction_is_not_a_vehicle_repeat(self):
        for introduction, name in (("mein Name ist Golf", "Golf"), ("Anna Handy", "Anna Handy"),
                                   ("Service Tester", "Service Tester")):
            self.sid = uuid.uuid4().hex
            self.start_contact()
            ticket = self.finish((introduction,))
            self.assertEqual(ticket["name"], name)

    def test_b04_invalid_whole_mileage_requires_clarification(self):
        for value in ("-8500 km", "-120000", "120,000 km", "120.000,5 km"):
            for message in (value, "Kilometerstand " + value):
                with self.subTest(message=message):
                    self.sid = uuid.uuid4().hex
                    self.send("VW Golf 2016")
                    count = self.ticket_count()
                    result = self.send(message)
                    self.assert_open_without_completion(result, count)
                    self.assertEqual(result.data["step"], "kilometerstand")
                    self.assertIsNone(result.data["kilometerstand"])
                    self.assertIn("Kilometerstand", result.reply)
                    ticket = self.finish(("8500 km", "Ölwechsel", "0000000000", "Testkunde"))
                    self.assert_saved_intake(ticket, km="8500")

    def test_b04_invalid_mileage_correction_keeps_valid_value(self):
        for value in ("-8500 km", "-120000", "120,000 km", "120.000,5 km"):
            self.sid = uuid.uuid4().hex
            self.start_contact()
            result = self.send("Korrektur: Kilometerstand " + value)
            self.assertEqual(result.data["kilometerstand"], "120000", value)
            self.assertFalse(result.done)
            ticket = self.finish(("Testkunde",))
            self.assert_saved_intake(ticket)

    def test_b05_confirmed_new_request_retains_intent(self):
        for first_quote, second_quote in ((False, True), (True, False), (False, False)):
            with self.subTest(first_quote=first_quote, second_quote=second_quote):
                self.sid = uuid.uuid4().hex
                self.start_contact(first_quote)
                first = self.finish(("Testkunde Eins",))
                count = self.ticket_count()
                request = "was kostet Reifenwechsel" if second_quote else "Reifenwechsel"
                result = self.send(request)
                self.assertIn("Ergänzung", result.reply)
                result = self.send("neu")
                self.assertFalse(result.done)
                self.assertIsNone(result.data["fahrzeug"])
                self.assertIsNone(result.data["telefon"])
                self.assertEqual(result.data["mode"], "quote" if second_quote else "new")
                second = self.finish(("Audi A4 2018 90000 km", "0000000001", "Testkunde Zwei"))
                self.assert_saved_intake(second, vehicle="Audi A4", year="2018", km="90000", phone="0000000001",
                    problem=request, request_type="kostenvoranschlag" if second_quote else "service")
                self.assertEqual(second["name"], "Testkunde Zwei")
                self.assertNotEqual(first["ticket_id"], second["ticket_id"])
                self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)
                self.assertEqual(self.ticket_count(), count + 1)

    def test_b05_price_supplement_stays_with_existing_ticket(self):
        self.start_contact()
        first = self.finish(("Testkunde",))
        result = self.send("was kostet Reifenwechsel")
        self.assertIn("Ergänzung", result.reply)
        self.send("Ergänzung")
        ticket = find_ticket_by_id(first["ticket_id"], self.wid)
        self.assertEqual(self.ticket_count(), self.count_before + 1)
        self.assertTrue(any("was kostet Reifenwechsel" in note.get("text", "") for note in ticket["notes"]))
        for field in ("fahrzeug", "problem", "telefon", "name", "request_type"):
            self.assertEqual(ticket[field], first[field])

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="werkstattai-intake-regressions-")
        cls.environment = patch.dict(os.environ, {
            "DATABASE_URL": "",
            "WERKSTATTAI_SQLITE_PATH": os.path.join(cls.directory.name, "isolated.db"),
        })
        cls.environment.start()
        init_db()
        cls.wid = settings.default_workshop_id

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        cls.environment.stop()
        cls.directory.cleanup()

    def setUp(self):
        self.sid = "regression-" + uuid.uuid4().hex
        self.phone = "4917010000001"  # Fictional verified transport identity.
        sender_patch = patch("app.main.send_whatsapp_text_message")
        self.sender = sender_patch.start()
        self.addCleanup(sender_patch.stop)
        self.count_before = self.ticket_count()

    def tearDown(self):
        self.sender.assert_not_called()

    def ticket_count(self):
        with closing(get_conn()) as conn:
            return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    def send(self, message):
        return process_chat_message(workshop_id=self.wid, session_id=self.sid,
            message=message, channel=self.channel,
            phone=self.phone if self.channel == "whatsapp" else None)

    def seed_state(self, **kwargs):
        state = IntakeState(workshop_id=self.wid, **kwargs)
        save_session_state(self.sid, state, workshop_id=self.wid, channel=self.channel)
        return state

    def finish(self, messages):
        for message in messages:
            result = self.send(message)
        self.assertTrue(result.done, result)
        return find_ticket_by_id(result.data["ticket_id"], self.wid)

    def assert_saved_intake(self, ticket, *, vehicle="VW Golf", year="2016", km="120000",
                            problem="Ölwechsel", phone="0000000000", request_type="service"):
        expected = dict(fahrzeug=vehicle, baujahr=year, kilometerstand=km,
                        problem=problem, telefon=phone, request_type=request_type)
        self.assertIsNotNone(ticket)
        self.assertEqual({key: ticket[key] for key in expected}, expected)

    def test_repeated_corrected_odometer_does_not_become_problem(self):
        for repeated in ("90000 km", "90.000 km", "90000"):
            with self.subTest(repeated=repeated):
                self.sid = uuid.uuid4().hex
                self.send("Problem melden")
                self.send("VW Golf")
                self.send("sorry meinte VW Passat bj 2017 90000 km")
                result = self.send(repeated)
                self.assertEqual(result.data["step"], "problem")
                self.assertIsNone(result.data["problem"])
                ticket = self.finish(("Ölwechsel", "0000000000", "Testkunde"))
                self.assert_saved_intake(ticket, vehicle="VW Passat", year="2017", km="90000")

    def test_repeated_vehicle_remains_data_and_service_is_saved(self):
        for repeated in ("VW Golf", "vw golf!", "VW GOLF."):
            with self.subTest(repeated=repeated):
                self.sid = uuid.uuid4().hex
                initial = self.send("VW Golf 2016 120000 km")
                self.assertEqual(initial.data["step"], "problem")
                result = self.send(repeated)
                self.assertEqual(result.data["step"], "problem")
                self.assertIsNone(result.data["problem"])
                self.assertIn("Anliegen", result.reply)
                self.assertFalse(result.done)
                for field in ("fahrzeug", "baujahr", "kilometerstand"):
                    self.assertEqual(result.data[field], initial.data[field])
                result = self.send("Ölwechsel")
                self.assertEqual(result.data["step"], "telefon")
                self.assertIn("Telefonnummer", result.reply)
                ticket = self.finish(("0000000000", "Testkunde"))
                self.assert_saved_intake(ticket)
                self.assertEqual(ticket["priority"], "niedrig")
                self.assertEqual(ticket["source"], self.channel)

    def test_explicit_phone_correction_at_name_step_is_saved(self):
        for correction in ("nein meine nummer ist 0000000001",
                           "Nein, meine Telefonnummer ist 0000000001"):
            with self.subTest(correction=correction):
                self.sid = uuid.uuid4().hex
                self.send("VW Golf 2016 120000 km")
                self.send("Ölwechsel")
                before = self.send("0000000000")
                count = self.ticket_count()
                result = self.send(correction)
                self.assertEqual(result.data["telefon"], "0000000001")
                self.assertEqual(result.data["step"], "name")
                self.assertIsNone(result.data["name"])
                self.assertFalse(result.done)
                self.assertIn("korrigiert", result.reply)
                self.assertIn("ansprechen", result.reply)
                for field in ("fahrzeug", "baujahr", "kilometerstand", "problem"):
                    self.assertEqual(result.data[field], before.data[field])
                self.assertEqual(self.ticket_count(), count)
                ticket = self.finish(("Testkunde",))
                self.assert_saved_intake(ticket, phone="0000000001")
                self.assertEqual(ticket["name"], "Testkunde")
                self.assertEqual(ticket["source"], self.channel)

    def test_symptom_with_known_vehicle_is_saved_as_problem(self):
        self.send("VW Golf 2016 120000 km")
        result = self.send("Mein VW Golf springt nicht an")
        self.assertEqual(result.data["problem"], "Mein VW Golf springt nicht an")
        self.assertEqual(result.data["step"], "abschleppdienst")
        self.assertIn("Abschleppdienst", result.reply)
        result = self.send("nein")
        for _ in range(5):
            if result.data["step"] != "followup":
                break
            result = self.send("seit gestern")
        self.assertEqual(result.data["step"], "telefon")
        ticket = self.finish(("0000000000", "Testkunde"))
        self.assert_saved_intake(ticket, problem="Mein VW Golf springt nicht an", request_type="notfall")

    def test_repeated_low_odometer_year_and_contact_remain_data(self):
        self.send("VW Golf")
        self.send("2016")
        self.send("8500")
        for repeated in ("8.500", "8500", "2016", "Baujahr 2016", "Telefonnummer 0000000000",
                         "Telefonnummer 0000000000", "0000000000"):
            result = self.send(repeated)
            self.assertEqual(result.data["step"], "problem", repeated)
            self.assertIsNone(result.data["problem"], repeated)
        ticket = self.finish(("Ölwechsel", "Testkunde"))
        self.assert_saved_intake(ticket, km="8500")

    def test_numeric_vehicle_models_are_preserved_in_saved_tickets(self):
        cases = (
            ("BMW 320 2016 120000 km", "BMW 320", "2016", "120000"),
            ("Mercedes E 220 2018 8500 km", "Mercedes E 220", "2018", "8500"),
            ("Peugeot 2008 2020 8500 km", "Peugeot 2008", "2020", "8500"),
            ("Peugeot 2008, Baujahr 2020, 8500 km", "Peugeot 2008", "2020", "8500"),
            ("Baujahr 2020, Peugeot 2008, 8500 km", "Peugeot 2008", "2020", "8500"),
            ("BMW 320, Bj. 2016, 120.000 km", "BMW 320", "2016", "120000"),
            ("BMW 320, Baujahr 2016, Kilometerstand 900 km", "BMW 320", "2016", "900"),
            ("Volvo 240 1992 180 tkm", "Volvo 240", "1992", "180000"),
            ("Testmarke 2005 2021 8500 km", "Testmarke 2005", "2021", "8500"),
            ("Testmarke Q 170 2019 8.500 km", "Testmarke Q 170", "2019", "8500"),
            ("Testmarke 12345 2021 8500 km", "Testmarke 12345", "2021", "8500"),
        )
        for message, vehicle, year, km in cases:
            with self.subTest(message=message):
                self.sid = uuid.uuid4().hex
                ticket = self.finish((message, "Ölwechsel", "0000000000", "Testkunde"))
                self.assert_saved_intake(ticket, vehicle=vehicle, year=year, km=km)

    def test_numeric_models_with_separate_year_are_preserved(self):
        for vehicle, year in (("BMW 320", "2016"), ("Mercedes E 220", "2018"), ("Peugeot 2008", "2020")):
            with self.subTest(vehicle=vehicle):
                self.sid = uuid.uuid4().hex
                result = self.send(vehicle)
                self.assertEqual(result.data["fahrzeug"], vehicle)
                self.assertEqual(result.data["step"], "baujahr")
                self.assertIsNone(result.data["baujahr"])
                ticket = self.finish((year, "120000 km", "Ölwechsel", "0000000000", "Testkunde"))
                self.assert_saved_intake(ticket, vehicle=vehicle, year=year)

    def test_model_year_ambiguity_keeps_vehicle_and_asks_for_year(self):
        for message in ("Peugeot 2008 8500 km", "Peugeot 2008"):
            with self.subTest(message=message):
                self.sid = uuid.uuid4().hex
                result = self.send(message)
                self.assertEqual(result.data["fahrzeug"], "Peugeot 2008")
                self.assertIsNone(result.data["baujahr"])
                self.assertEqual(result.data["step"], "baujahr")
                self.assertIn("Baujahr", result.reply)
                messages = ["Baujahr 2020"]
                if result.data["kilometerstand"] is None:
                    messages.append("8500")
                ticket = self.finish((*messages, "Ölwechsel", "0000000000", "Testkunde"))
                self.assert_saved_intake(ticket, vehicle="Peugeot 2008", year="2020", km="8500")

    def test_natural_vehicle_corrections_preserve_other_saved_fields(self):
        for correction in ("nein es ist ein VW Passat", "nein, das ist ein VW Passat",
                           "nein ich fahre einen VW Passat", "nein mein Fahrzeug ist VW Passat"):
            with self.subTest(correction=correction):
                self.sid = uuid.uuid4().hex
                self.send("VW Golf 2016 120000 km")
                self.send("Ölwechsel")
                result = self.send(correction)
                self.assertIn("korrigiert", result.reply)
                self.assertEqual(result.data["step"], "telefon")
                ticket = self.finish(("0000000000", "Testkunde"))
                self.assert_saved_intake(ticket, vehicle="VW Passat")

    def test_ambiguous_natural_correction_asks_for_vehicle_without_overwrite(self):
        self.send("VW Golf 2016 120000 km")
        self.send("Ölwechsel")
        result = self.send("nein es ist ein anderes")
        self.assertIn("Welches Fahrzeug", result.reply)
        self.assertEqual(result.data["fahrzeug"], "VW Golf")
        self.assertFalse(result.done)
        self.assertNotIn("Telefonnummer", result.reply)
        self.send("Testmarke X 170")
        ticket = self.finish(("0000000000", "Testkunde"))
        self.assert_saved_intake(ticket, vehicle="Testmarke X 170")

    def test_apology_and_short_phone_preambles_do_not_block_completion(self):
        for phone_answer in ("sorry 0000000000", "sorry, 0000000000", "entschuldigung 0000000000",
                             "hier meine Nummer 0000000000", "sorry hier meine Nummer 0000000000",
                             "sorry hier 0000000000",
                             "sorry 0000000"):
            with self.subTest(phone_answer=phone_answer):
                self.sid = uuid.uuid4().hex
                self.send("VW Golf 2016 120000 km")
                self.send("Ölwechsel")
                result = self.send(phone_answer)
                self.assertEqual(result.data["step"], "name")
                self.assertNotIn("Welche Angabe", result.reply)
                ticket = self.finish(("Testkunde",))
                expected = "0000000" if phone_answer == "sorry 0000000" else "0000000000"
                self.assert_saved_intake(ticket, phone=expected)

    def test_ambiguous_vehicle_correction_at_name_step_is_not_saved_as_name(self):
        self.send("VW Golf 2016 120000 km")
        self.send("Ölwechsel")
        self.send("0000000000")
        result = self.send("nein es ist ein anderes")
        self.assertIn("Welches Fahrzeug", result.reply)
        self.assertFalse(result.done)
        self.assertIsNone(result.data["name"])
        result = self.send("VW Passat")
        self.assertEqual(result.data["step"], "name")
        ticket = self.finish(("Testkunde",))
        self.assert_saved_intake(ticket, vehicle="VW Passat")

    def test_ambiguous_quote_vehicle_correction_can_be_answered_or_cancelled(self):
        self.send("Was kostet ein Ölwechsel?")
        self.send("BMW 320 2016 120000 km")
        result = self.send("nein es ist ein anderes")
        self.assertIn("Welches Fahrzeug", result.reply)
        self.send("Testmarke X 170")
        ticket = self.finish(("sorry 0000000000", "Testkunde"))
        self.assert_saved_intake(ticket, vehicle="Testmarke X 170", problem="Was kostet ein Ölwechsel?",
                                 request_type="kostenvoranschlag")
        self.sid = uuid.uuid4().hex
        self.send("Was kostet ein Ölwechsel?")
        self.send("VW Golf")
        self.send("nein es ist ein anderes")
        result = self.send("abbrechen")
        self.assertFalse(result.data["pending_vehicle_correction"])
        self.assertIsNone(result.data["ticket_id"])
        self.assertEqual(self.ticket_count(), self.count_before + 1)

    def test_phone_answer_does_not_join_vehicle_numbers(self):
        for phone_answer in ("BMW 320 2016 120000 km, Telefonnummer 0000000000",
                             "BMW 320 2016 120000 km 0000000000"):
            with self.subTest(phone_answer=phone_answer):
                self.sid = uuid.uuid4().hex
                self.send("BMW 320 2016 120000 km")
                self.send("Ölwechsel")
                ticket = self.finish((phone_answer, "Testkunde"))
                self.assert_saved_intake(ticket, vehicle="BMW 320")

    def test_natural_correction_and_apology_phone_work_in_quotes(self):
        self.send("Was kostet ein Ölwechsel?")
        self.send("BMW 320 2016 120000 km")
        result = self.send("nein es ist ein VW Passat")
        self.assertEqual(result.data["step"], "quote_telefon")
        result = self.send("sorry 0000000000")
        self.assertEqual(result.data["step"], "quote_name")
        ticket = self.finish(("Testkunde",))
        self.assert_saved_intake(ticket, vehicle="VW Passat", problem="Was kostet ein Ölwechsel?",
                                 request_type="kostenvoranschlag")

    def test_bare_no_remains_drivability_and_towing_answer(self):
        self.send("VW Golf 2016 120000 km")
        self.send("Warnlampe leuchtet")
        result = self.send("nein")
        self.assertEqual(result.data["fahrbereit"], "nein")
        self.assertEqual(result.data["step"], "abschleppdienst")
        result = self.send("nein")
        self.assertEqual(result.data["abschleppdienst"], "nein")
        for _ in range(5):
            if result.data["step"] != "followup":
                break
            result = self.send("seit gestern")
        self.assertEqual(result.data["step"], "telefon")
        ticket = self.finish(("0000000000", "Testkunde"))
        self.assert_saved_intake(ticket, problem="Warnlampe leuchtet", request_type="diagnose")
        self.assertFalse(ticket["fahrbereit"])

    def test_announcements_do_not_become_vehicle_or_problem(self):
        for message in ("ich wollte ein Problem melden", "ich wollte ein problenm melden",
                        "moin ich will ein problme melden", "Problem melden!",
                        "ich würde gerne ein Problem melden", "ich habe ein Problem"):
            with self.subTest(message=message):
                self.sid = uuid.uuid4().hex
                result = self.send(message)
                self.assertEqual(result.data["mode"], "new")
                self.assertIsNone(result.data["fahrzeug"])
                self.assertIsNone(result.data["problem"])
                self.assertIn("Worum geht", result.reply)
                self.assertFalse(result.done)
        self.assertEqual(self.ticket_count(), self.count_before)

    def test_announcement_with_symptom_retains_concrete_problem(self):
        result = self.send("ich wollte ein Problem melden, mein Auto springt nicht an")
        self.assertEqual(result.data["problem"], "mein Auto springt nicht an")
        self.assertIsNone(result.data["fahrzeug"])
        self.assertIn("Marke und Modell", result.reply)

    def test_two_complete_reports_in_same_session_are_separate(self):
        first = self.finish(("VW Golf 2016 120000 km", "Inspektion und Ölwechsel", "0000000000", "Testperson Eins"))
        result = self.send("Problem melden")
        for field in ("ticket_id", "fahrzeug", "baujahr", "kilometerstand", "problem", "telefon", "name", "fahrbereit"):
            self.assertIsNone(result.data[field], field)
        second = self.finish(("Toyota Yaris 2020 8500 km", "Reifenwechsel", "0000000001", "Testperson Zwei"))
        self.assertNotEqual(first["ticket_id"], second["ticket_id"])
        self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)
        self.assertEqual(second["fahrzeug"], "Toyota Yaris")
        self.assertEqual(second["telefon"], "0000000001")
        self.assertEqual(second["problem"], "Reifenwechsel")
        self.assertEqual(second["source"], self.channel)
        self.assertEqual(self.ticket_count(), self.count_before + 2)

    def test_vehicle_and_phone_corrections_are_actually_saved(self):
        self.send("VW Golf")
        result = self.send("sorry meinte VW Passat bj 2017 90000 km")
        self.assertEqual(result.data["fahrzeug"], "VW Passat")
        self.assertEqual(result.data["step"], "problem")
        self.assertIn("korrigiert", result.reply)
        self.send("Ölwechsel")
        self.send("0000000000")
        result = self.send("nein falsche nummer 0000000001")
        self.assertFalse(result.done)
        self.assertEqual(result.data["step"], "name")
        self.assertIsNone(result.data["name"])
        self.assertEqual(self.ticket_count(), self.count_before)
        ticket = self.finish(("Testperson",))
        for field, expected in {"fahrzeug": "VW Passat", "baujahr": "2017",
                                "kilometerstand": "90000", "telefon": "0000000001",
                                "name": "Testperson", "problem": "Ölwechsel"}.items():
            self.assertEqual(ticket[field], expected, field)

    def test_corrections_outside_vehicle_step_preserve_other_valid_fields(self):
        self.send("VW Golf 2016 120000 km")
        self.send("Ölwechsel")
        result = self.send("Korrektur: mein Fahrzeug ist Skoda Octavia bj 2019 8500 km")
        self.assertEqual(result.data["step"], "telefon")
        ticket = self.finish(("0000000001", "Testperson"))
        self.assertEqual(ticket["fahrzeug"], "Skoda Octavia")
        self.assertEqual(ticket["baujahr"], "2019")
        self.assertEqual(ticket["kilometerstand"], "8500")
        self.assertEqual(ticket["problem"], "Ölwechsel")

    def test_quote_vehicle_and_phone_corrections(self):
        self.send("Was kostet ein Ölwechsel?")
        self.send("VW Golf 2016")
        result = self.send("sorry meinte VW Passat bj 2017 90000 km")
        self.assertEqual(result.data["step"], "quote_telefon")
        self.send("0000000000")
        result = self.send("nein falsche nummer 0000000001")
        self.assertFalse(result.done)
        self.assertEqual(result.data["step"], "quote_name")
        ticket = self.finish(("Testperson",))
        self.assertEqual(ticket["fahrzeug"], "VW Passat")
        self.assertEqual(ticket["baujahr"], "2017")
        self.assertEqual(ticket["kilometerstand"], "90000")
        self.assertEqual(ticket["telefon"], "0000000001")
        self.assertEqual(ticket["request_type"], "kostenvoranschlag")

    def test_year_and_odometer_corrections_do_not_overwrite_vehicle(self):
        self.send("VW Golf 2016 8500 km")
        self.send("Ölwechsel")
        self.send("sorry Baujahr ist 2018")
        result = self.send("Korrektur: Kilometerstand 9000 km")
        self.assertEqual(result.data["fahrzeug"], "VW Golf")
        self.assertEqual(result.data["step"], "telefon")
        ticket = self.finish(("0000000001", "Testperson"))
        self.assertEqual(ticket["baujahr"], "2018")
        self.assertEqual(ticket["kilometerstand"], "9000")
        self.assertEqual(ticket["problem"], "Ölwechsel")

    def test_name_correction_does_not_replace_the_vehicle(self):
        self.send("VW Golf 2016 8500 km")
        self.send("Ölwechsel")
        self.send("0000000001")
        ticket = self.finish(("sorry meinte Max Mustermann",))
        self.assertEqual(ticket["name"], "Max Mustermann")
        self.assertEqual(ticket["fahrzeug"], "VW Golf")

    def test_high_odometer_is_not_also_a_contact_number(self):
        self.send("VW Golf")
        self.send("2016")
        result = self.send("1000000")
        self.assertEqual(result.data["kilometerstand"], "1000000")
        self.assertIsNone(result.data["telefon"])
        ticket = self.finish(("Ölwechsel", "0000000001", "Testperson"))
        self.assertEqual(ticket["kilometerstand"], "1000000")

    def test_contact_in_problem_step_is_not_saved_as_problem(self):
        self.send("VW Golf 2016 8500 km")
        result = self.send("Telefonnummer 0000000001")
        self.assertFalse(result.done)
        self.assertIsNone(result.data["problem"])
        self.assertEqual(result.data["step"], "problem")
        self.assertEqual(result.data["telefon"], "0000000001")
        ticket = self.finish(("Ölwechsel", "Testperson"))
        self.assertEqual(ticket["problem"], "Ölwechsel")

    def test_status_and_supplement_still_work_for_the_owned_ticket(self):
        ticket = self.finish(("VW Golf 2016 8500 km", "Ölwechsel", "0000000001", "Testperson"))
        result = self.send("Wie ist der Status?")
        self.assertIn("offen", result.reply)
        self.assertEqual(result.data["ticket_id"], ticket["ticket_id"])
        result = self.send("Ergänzung: Das Fahrzeug steht vor der Werkstatt.")
        self.assertEqual(result.data["ticket_id"], ticket["ticket_id"])
        updated = find_ticket_by_id(ticket["ticket_id"], self.wid)
        self.assertTrue(any("Das Fahrzeug steht vor der Werkstatt" in note["text"] for note in updated["notes"]))
        self.assertEqual(updated["problem"], ticket["problem"])
        self.assertEqual(self.ticket_count(), self.count_before + 1)

    def test_cancel_precedes_data_processing_in_every_intake_step(self):
        for mode, steps in (("new", ("fahrzeug", "baujahr", "kilometerstand", "problem", "fahrbereit",
                                   "abschleppdienst", "followup", "telefon", "name")),
                            ("quote", ("quote_anliegen", "quote_fahrzeug", "quote_telefon", "quote_name"))):
            for step in steps:
                for command in ("abbrechen", "stop", "Stopp!", "bitte abbrechen!", "abbrechen bitte", "stop bitte",
                                "ich möchte abbrechen", "bitte die Anfrage abbrechen", "doch abbrechen",
                                "ich will die Anfrage abbrechen", *L01_CANCEL_COMMANDS):
                    with self.subTest(mode=mode, step=step, command=command):
                        self.seed_state(mode=mode, step=step, fahrzeug="VW Golf", baujahr="2016",
                                        kilometerstand="8500", problem="Ölwechsel", telefon="0000000000")
                        result = self.send(command)
                        self.assertFalse(result.done)
                        self.assertIn("abgebrochen", result.reply)
                        self.assertEqual(result.data["workshop_id"], self.wid)
                        self.assertIsNone(result.data["ticket_id"])
                        self.assertIsNone(result.data["name"])
                        self.assertIsNone(result.data["fahrzeug"])
        self.assertEqual(self.ticket_count(), self.count_before)
        ticket = self.finish(("VW Golf 2016 8500 km", "Ölwechsel", "0000000001", "Testperson"))
        self.assertEqual(ticket["kilometerstand"], "8500")

    def test_cancelled_second_intake_does_not_delete_first_ticket(self):
        first = self.finish(("VW Golf 2016 8500 km", "Ölwechsel", "0000000000", "Testperson"))
        self.send("Problem melden")
        self.send("VW Passat")
        self.send("ich möchte abbrechen")
        self.assertEqual(self.ticket_count(), self.count_before + 1)
        self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)

    def test_stop_inside_a_symptom_is_not_a_command(self):
        result = self.send("Motor stoppt beim Fahren")
        self.assertEqual(result.data["problem"], "Motor stoppt beim Fahren")
        self.assertIsNone(result.data["fahrzeug"])
        self.assertNotIn("abgebrochen", result.reply)

    def test_symptom_subjects_and_adjectives_are_not_vehicle_models(self):
        for message in ("starker Qualm", "komische Geräusche", "Auto macht Geräusche",
                        "aus dem Motor kommt Rauch"):
            self.sid = uuid.uuid4().hex
            result = self.send(message)
            self.assertIsNone(result.data["fahrzeug"], message)
            self.assertEqual(result.data["problem"], message)
            self.assertFalse(result.done)

    def test_oil_change_word_boundaries_and_negation_are_saved_as_service(self):
        for problem in ("moin brauche ölwechsel", "ich gebrauche das Auto und brauche einen Ölwechsel",
                        "kein Rauch, nur Ölwechsel", "keine Warnlampe, nur Inspektion"):
            with self.subTest(problem=problem):
                self.sid = uuid.uuid4().hex
                self.send(problem)
                ticket = self.finish(("VW Golf 2016 8500 km", "0000000001", "Testperson"))
                self.assertEqual(ticket["request_type"], "service")
                self.assertEqual(ticket["priority"], "niedrig")

    def test_symptoms_and_nonknowledge_are_never_vehicle_names(self):
        for mode, step in (("new", "fahrzeug"), ("quote", "quote_fahrzeug")):
            for invalid in ("auto springt nich an", "keine ahnung", "weiß ich nicht", "überspringen"):
                with self.subTest(mode=mode, invalid=invalid):
                    self.seed_state(mode=mode, step=step, problem="Ölwechsel" if mode == "quote" else None)
                    result = self.send(invalid)
                    self.assertIsNone(result.data["fahrzeug"])
                    self.assertFalse(result.done)
                    self.assertEqual(result.data["step"], step)
                    if invalid.startswith("auto") and mode == "new":
                        self.assertEqual(result.data["problem"], invalid)

    def test_service_with_phone_in_first_message_uses_each_field_once(self):
        result = self.send("vw golf bj 2016 120000 km braucht ölwechsel meine telefonnummer 0000000000")
        self.assertEqual(result.data["step"], "name")
        self.assertEqual(result.data["telefon"], "0000000000")
        ticket = self.finish(("Testperson",))
        self.assertEqual(ticket["fahrzeug"], "vw golf")
        self.assertEqual(ticket["baujahr"], "2016")
        self.assertEqual(ticket["kilometerstand"], "120000")
        self.assertEqual(ticket["request_type"], "service")
        if self.channel == "whatsapp":
            self.assertEqual(ticket["verified_customer_phone"], self.phone)
        else:
            self.assertIsNone(ticket["verified_customer_phone"])

    def test_negated_old_ticket_returns_to_new_service(self):
        self.send("Status von einem bestehenden Ticket")
        result = self.send("ich will nur ölwechsel anmelden kein altes ticket")
        self.assertEqual(result.data["mode"], "new")
        self.assertIn("ölwechsel", result.data["problem"])
        ticket = self.finish(("VW Golf 2016 8500 km", "0000000001", "Testperson"))
        self.assertEqual(ticket["request_type"], "service")

    def test_all_low_odometer_formats_have_same_stored_value(self):
        for odometer in ("8500", "8.500", "8500 km", "8.500 km", "800 km", "0 km"):
            with self.subTest(odometer=odometer):
                self.sid = uuid.uuid4().hex
                self.send("VW Golf")
                self.send("2016")
                self.send(odometer)
                ticket = self.finish(("Ölwechsel", "0000000001", "Testperson"))
                expected = "800" if odometer == "800 km" else "0" if odometer == "0 km" else "8500"
                self.assertEqual(ticket["kilometerstand"], expected)
                self.assertEqual(ticket["baujahr"], "2016")

    def test_colloquial_drivability_is_saved(self):
        self.send("VW Golf 2016 8500 km")
        self.send("Warnlampe leuchtet")
        result = self.send("jo fährt noch")
        self.assertEqual(result.data["fahrbereit"], "ja")
        self.assertEqual(result.data["step"], "followup")
        self.send("seit gestern")
        self.send("gelbe Motorlampe")
        self.send("beim Beschleunigen")
        ticket = self.finish(("0000000001", "Testperson"))
        self.assertTrue(ticket["fahrbereit"])

    def test_inline_data_in_year_step_does_not_repeat_questions(self):
        self.send("VW Golf")
        result = self.send("2016 120000 km Ölwechsel, Telefonnummer 0000000001, mein Name ist Testperson")
        self.assertTrue(result.done, result)
        ticket = find_ticket_by_id(result.data["ticket_id"], self.wid)
        self.assertEqual(ticket["name"], "Testperson")
        self.assertEqual(ticket["kilometerstand"], "120000")

    def test_model_only_inline_message_does_not_invent_make(self):
        self.send("golf 2016 120000 km ölwechsel bitte")
        ticket = self.finish(("0000000001", "Testperson"))
        self.assertEqual(ticket["fahrzeug"], "golf")
        self.assertEqual(ticket["baujahr"], "2016")
        self.assertEqual(ticket["kilometerstand"], "120000")

    def test_workshop_side_questions_preserve_the_open_question_and_data(self):
        for mode, step in (("new", "baujahr"), ("quote", "quote_telefon")):
            self.seed_state(mode=mode, step=step, fahrzeug="VW Golf", problem="Ölwechsel")
            for hours, expected in (("Samstag 09:00-12:00", "Samstag 09:00-12:00"), ("", "noch nicht hinterlegt")):
                with patch("app.conversation.router.get_workshop", return_value={"name": "Testwerkstatt", "opening_hours": hours}):
                    result = self.send("habt ihr samstags offen?")
                self.assertIn(expected, result.reply)
                self.assertEqual(result.data["step"], step)
                self.assertEqual(result.data["mode"], mode)
                self.assertEqual(result.data["fahrzeug"], "VW Golf")
                self.assertIn("Baujahr" if mode == "new" else "Telefonnummer", result.reply)

    def test_unknown_required_year_remains_required_with_alternatives(self):
        self.send("VW Golf")
        replies = []
        for message in ("weiß ich nicht", "kann gerade nicht nachschauen", "überspringen"):
            result = self.send(message)
            replies.append(result.reply)
            self.assertEqual(result.data["step"], "baujahr")
            self.assertIsNone(result.data["baujahr"])
            self.assertFalse(result.done)
        self.assertNotEqual(replies[0], replies[1])
        self.assertNotEqual(replies[1], replies[2])
        self.assertIn("Erstzulassung", replies[0])
        self.send("Erstzulassung 2016")
        self.send("8500")
        ticket = self.finish(("Ölwechsel", "0000000001", "Testperson"))
        self.assertEqual(ticket["baujahr"], "2016")

    def test_unknown_and_command_messages_are_not_saved_as_names(self):
        for mode, step in (("new", "name"), ("quote", "quote_name")):
            self.sid = uuid.uuid4().hex
            self.seed_state(mode=mode, step=step, fahrzeug="VW Golf", baujahr="2016",
                            kilometerstand="8500", problem="Ölwechsel", telefon="0000000001")
            result = self.send("nein falsche nummer")
            self.assertFalse(result.done)
            self.assertIsNone(result.data["name"])
            ticket = self.finish(("keine ahnung",))
            self.assertIsNone(ticket["name"])


class WebIntakeRegressions(IntakeScenarios, unittest.TestCase):
    channel = "web_chat"


class WhatsAppIntakeRegressions(IntakeScenarios, unittest.TestCase):
    channel = "whatsapp"


class ExtractionAndRoutingRegressions(unittest.TestCase):
    def test_smoke_and_inflected_symptoms_still_match(self):
        for message in ("aus dem Motor kommt Rauch", "der Motor raucht", "starker Qualm", "es quietscht"):
            with self.subTest(message=message):
                self.assertNotEqual(analyze_problem(message)["request_type"], "service")
                self.assertTrue(any(analyze_problem(message)["flags"].values()))

    def test_year_in_freetext_is_not_an_odometer(self):
        for text in ("Baujahr 2016", "2016", "Seit 2017 fahre ich den Wagen"):
            self.assertIsNone(extract_km(text))
        self.assertEqual(extract_km("2016", expected=True), "2016")

    def test_phone_alone_does_not_start_lookup_but_explicit_status_does(self):
        self.assertEqual(detect_intent(IntakeState(), "Telefonnummer 0000000000"), INTENT_UNCLEAR)
        self.assertEqual(detect_intent(IntakeState(), "Status zu Telefonnummer 0000000000"), INTENT_EXISTING_TICKET)
        self.assertEqual(detect_intent(IntakeState(mode="existing"), "0000000000"), INTENT_EXISTING_TICKET)
        self.assertEqual(detect_intent(IntakeState(), "kein altes Ticket, Ölwechsel anmelden"), INTENT_NEW_REQUEST)

    def test_ambiguous_second_problem_is_clarified_before_ticket_changes(self):
        state = IntakeState(mode="new", step="fertig", ticket_id="WS-20410101-0001", problem="Ölwechsel")
        with patch("app.conversation.router.handle_existing_ticket") as existing:
            state, reply, done = next_step(state, "Motor springt nicht an")
            existing.assert_not_called()
        self.assertIn("neues Anliegen", reply)
        self.assertFalse(done)
        state, _, done = next_step(state, "neues Anliegen")
        self.assertIsNone(state.ticket_id)
        self.assertEqual(state.problem, "Motor springt nicht an")
        self.assertIsNone(state.fahrzeug)

    def test_supplement_is_delivered_to_the_authorized_existing_handler(self):
        state = IntakeState(mode="new", step="fertig", ticket_id="WS-20410101-0001")
        access = CustomerAccess("test", frozenset({state.ticket_id}))
        state, _, _ = next_step(state, "Motor springt nicht an", customer_access=access)
        with patch("app.conversation.router.handle_existing_ticket", return_value=(state, "Aufgenommen", False)) as existing:
            next_step(state, "Ergänzung", customer_access=access)
            self.assertEqual(existing.call_args.args[1], "Motor springt nicht an")
            self.assertIs(existing.call_args.kwargs["customer_access"], access)


def check_l01_l02_transport(test, send):
    """Exercise public transports; private fields are checked in saved records."""
    def count():
        with closing(get_conn()) as conn:
            return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    before = count()
    for quote in (False, True):
        if quote:
            send("was kostet Ölwechsel")
        send("VW Golf 2016 120000 km")
        if not quote:
            send("Ölwechsel")
        send("0000000000")
        with patch("app.main.save_ticket", side_effect=AssertionError("Unexpected completion")) as save:
            result = send("ich würde gerne abbrechen")
            save.assert_not_called()
        test.assertFalse(result["done"])
        test.assertEqual(result["data"]["mode"], "unknown")
        test.assertIsNone(result["data"]["ticket_id"])
        test.assertIn("abgebrochen", result["reply"])
        test.assertNotIn("Ticket-Nr.", result["reply"])
        test.assertEqual(count(), before)

    for message in ("VW Golf 2016,120000 km", "VW Golf,2016,120000 km", "VW Golf 2016:120000 km"):
        send("Problem melden")
        result = send(message)
        test.assertEqual(result["data"]["step"], "problem")
        result = send("120000 km")
        test.assertEqual(result["data"]["step"], "problem")
        test.assertFalse(result["done"])
        for text in ("Ölwechsel", "0000000000", "Testkunde"):
            result = send(text)
        test.assertTrue(result["done"])
        ticket = find_ticket_by_id(result["data"]["ticket_id"], test.wid)
        expected = dict(fahrzeug="VW Golf", baujahr="2016", kilometerstand="120000",
                        problem="Ölwechsel", telefon="0000000000", name="Testkunde", request_type="service")
        test.assertEqual({key: ticket[key] for key in expected}, expected)
    test.assertEqual(count(), before + 3)


class BrowserEndpointIntakeRegressions(unittest.TestCase):
    def test_l01_l02_through_public_chat(self):
        with tempfile.TemporaryDirectory(prefix="werkstattai-l01-l02-http-") as directory:
            with patch.dict(os.environ, {"DATABASE_URL": "", "WERKSTATTAI_SQLITE_PATH": os.path.join(directory, "http.db")}):
                init_db()
                self.wid = settings.default_workshop_id
                with TestClient(app) as client, patch("app.main.send_whatsapp_text_message") as sender:
                    def send(message):
                        response = client.post("/chat", json={"session_id": "l01-l02-http", "message": message,
                                                              "workshop_id": self.wid})
                        self.assertEqual(response.status_code, 200, response.text)
                        return response.json()
                    check_l01_l02_transport(self, send)
                    sender.assert_not_called()
                gc.collect()

    def test_vehicle_repeat_and_phone_correction_through_public_chat(self):
        with tempfile.TemporaryDirectory(prefix="werkstattai-intake-http-") as directory:
            with patch.dict(os.environ, {"DATABASE_URL": "", "WERKSTATTAI_SQLITE_PATH": os.path.join(directory, "http.db")}):
                init_db()
                with TestClient(app) as client, patch("app.main.send_whatsapp_text_message") as sender:
                    for correction in (False, True):
                        with self.subTest(correction=correction):
                            sid = uuid.uuid4().hex

                            def send(message):
                                response = client.post("/chat", json={"session_id": sid, "message": message,
                                                                      "workshop_id": settings.default_workshop_id})
                                self.assertEqual(response.status_code, 200, response.text)
                                return response.json()

                            send("VW Golf 2016 120000 km")
                            if not correction:
                                result = send("vw golf!")
                                self.assertEqual(result["data"]["step"], "problem")
                                self.assertIn("Anliegen", result["reply"])
                                self.assertFalse(result["done"])
                            send("Ölwechsel")
                            send("0000000000")
                            if correction:
                                result = send("Nein, meine Telefonnummer ist 0000000001")
                                self.assertEqual(result["data"]["step"], "name")
                                self.assertIn("korrigiert", result["reply"])
                                self.assertIn("ansprechen", result["reply"])
                                self.assertFalse(result["done"])
                            result = send("Testkunde")
                            self.assertTrue(result["done"])
                            ticket = find_ticket_by_id(result["data"]["ticket_id"], settings.default_workshop_id)
                            expected = dict(fahrzeug="VW Golf", baujahr="2016", kilometerstand="120000",
                                            problem="Ölwechsel", request_type="service", priority="niedrig",
                                            telefon="0000000001" if correction else "0000000000", name="Testkunde")
                            self.assertEqual({key: ticket[key] for key in expected}, expected)
                    sender.assert_not_called()
                gc.collect()

    def test_two_reports_through_public_chat_have_distinct_saved_records(self):
        with tempfile.TemporaryDirectory(prefix="werkstattai-intake-http-") as directory:
            with patch.dict(os.environ, {"DATABASE_URL": "", "WERKSTATTAI_SQLITE_PATH": os.path.join(directory, "http.db")}):
                init_db()
                with TestClient(app) as client:
                    def send(message):
                        response = client.post("/chat", json={"session_id": "same-browser", "message": message,
                                                              "workshop_id": settings.default_workshop_id})
                        self.assertEqual(response.status_code, 200, response.text)
                        return response.json()
                    for message in ("VW Golf 2016 8500 km", "Ölwechsel", "0000000000", "Testperson Eins"):
                        result = send(message)
                    first = find_ticket_by_id(result["data"]["ticket_id"], settings.default_workshop_id)
                    send("Problem melden")
                    for message in ("Audi A4 2018 90000 km", "Reifenwechsel", "0000000001", "Testperson Zwei"):
                        result = send(message)
                    self.assertTrue(result["done"])
                    second = find_ticket_by_id(result["data"]["ticket_id"], settings.default_workshop_id)
                    self.assertNotEqual(first["ticket_id"], second["ticket_id"])
                    self.assertEqual(first, find_ticket_by_id(first["ticket_id"], settings.default_workshop_id))
                    self.assertEqual(second["fahrzeug"], "Audi A4")
                gc.collect()


class SignedWhatsAppIntakeRegressions(unittest.TestCase):
    setUp = whatsapp_fixture.WhatsAppReliabilityTests.setUp
    tearDown = whatsapp_fixture.WhatsAppReliabilityTests.tearDown
    payload = whatsapp_fixture.WhatsAppReliabilityTests.payload
    request = whatsapp_fixture.WhatsAppReliabilityTests.request
    webhook = whatsapp_fixture.WhatsAppReliabilityTests.webhook

    def test_l01_l02_through_signed_webhook(self):
        def send(message):
            result = self.send(message)
            state = load_session_state(whatsapp_session_id(self.phone), self.wid, channel="whatsapp")
            return {**result, "data": state.model_dump()}
        check_l01_l02_transport(self, send)

    def send(self, message):
        message_id = "wamid.intake." + uuid.uuid4().hex
        payload = self.payload(message_id)
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = message
        with patch("app.main.send_whatsapp_text_message", return_value=WhatsAppSendResult(
                True, 200, "wamid.fake-reply." + uuid.uuid4().hex, {})) as sender:
            result = self.webhook(payload)
        self.assertEqual(result["processed"], 1, result)
        sender.assert_called_once()
        return result["replies"][0]

    def test_vehicle_repeat_and_phone_correction_through_signed_webhook(self):
        for correction in (False, True):
            with self.subTest(correction=correction):
                self.send("Problem melden")
                self.send("VW Golf 2016 120000 km")
                if not correction:
                    result = self.send("vw golf!")
                    state = load_session_state(whatsapp_session_id(self.phone), self.wid, channel="whatsapp")
                    self.assertEqual(state.step, "problem")
                    self.assertIsNone(state.problem)
                    self.assertIn("Anliegen", result["reply"])
                    self.assertFalse(result["done"])
                self.send("Ölwechsel")
                self.send("0000000000")
                if correction:
                    result = self.send("Nein, meine Telefonnummer ist 0000000001")
                    state = load_session_state(whatsapp_session_id(self.phone), self.wid, channel="whatsapp")
                    self.assertEqual(state.telefon, "0000000001")
                    self.assertEqual(state.step, "name")
                    self.assertIsNone(state.name)
                    self.assertIn("korrigiert", result["reply"])
                    self.assertIn("ansprechen", result["reply"])
                    self.assertFalse(result["done"])
                result = self.send("Testkunde")
                self.assertTrue(result["done"])
                ticket = find_ticket_by_id(result["active_ticket_id"], self.wid)
                expected = dict(fahrzeug="VW Golf", baujahr="2016", kilometerstand="120000",
                                problem="Ölwechsel", request_type="service", priority="niedrig",
                                telefon="0000000001" if correction else "0000000000", name="Testkunde",
                                verified_customer_phone=self.phone)
                self.assertEqual({key: ticket[key] for key in expected}, expected)

    def test_two_reports_through_signed_meta_webhook_are_separate(self):
        for message in ("VW Golf 2016 8500 km", "Ölwechsel", "0000000000", "Testperson Eins"):
            result = self.send(message)
        self.assertTrue(result["done"])
        first = find_ticket_by_id(result["active_ticket_id"], self.wid)
        result = self.send("ich wollte ein problenm melden")
        self.assertFalse(result["done"])
        self.assertIsNone(result["active_ticket_id"])
        messages = list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone)
        announcement = next(item for item in messages if item["text"] == "ich wollte ein problenm melden")
        self.assertIsNone(announcement["ticket_id"])
        for message in ("VW Passat 2017 90000 km", "Reifenwechsel", "0000000001", "Testperson Zwei"):
            result = self.send(message)
        self.assertTrue(result["done"])
        second = find_ticket_by_id(result["active_ticket_id"], self.wid)
        self.assertNotEqual(first["ticket_id"], second["ticket_id"])
        self.assertEqual(find_ticket_by_id(first["ticket_id"], self.wid), first)
        self.assertEqual(second["fahrzeug"], "VW Passat")
        self.assertEqual(second["kilometerstand"], "90000")
        self.assertEqual(second["telefon"], "0000000001")
        self.assertEqual(second["verified_customer_phone"], self.phone)

    def test_quote_abort_is_not_a_ticket_through_signed_meta_webhook(self):
        for message in ("Was kostet ein Ölwechsel?", "VW Golf", "0000000000"):
            self.send(message)
        result = self.send("abbrechen")
        self.assertFalse(result["done"])
        self.assertIn("abgebrochen", result["reply"])
        with closing(get_conn()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 0)

    def test_four_remaining_defects_through_signed_webhook_save_correct_fields(self):
        cases = (
            (("VW Golf", "sorry meinte VW Passat bj 2017 90000 km", "90000 km", "Ölwechsel",
              "0000000000", "Testkunde"), "VW Passat", "2017", "90000"),
            (("Peugeot 2008 2020 8500 km", "Ölwechsel", "0000000000", "Testkunde"),
             "Peugeot 2008", "2020", "8500"),
            (("VW Golf 2016 120000 km", "Ölwechsel", "nein es ist ein VW Passat", "0000000000", "Testkunde"),
             "VW Passat", "2016", "120000"),
            (("VW Golf 2016 120000 km", "Ölwechsel", "sorry 0000000000", "Testkunde"),
             "VW Golf", "2016", "120000"),
        )
        for messages, vehicle, year, km in cases:
            with self.subTest(messages=messages):
                self.send("Problem melden")
                for message in messages:
                    result = self.send(message)
                self.assertTrue(result["done"])
                ticket = find_ticket_by_id(result["active_ticket_id"], self.wid)
                expected = dict(fahrzeug=vehicle, baujahr=year, kilometerstand=km, problem="Ölwechsel",
                                telefon="0000000000", request_type="service")
                self.assertEqual({key: ticket[key] for key in expected}, expected)


if __name__ == "__main__":
    unittest.main()
