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
from app.conversation_sessions import save_session_state
from app.customer_access import CustomerAccess
from app.db import get_conn, init_db
from app.main import app, process_chat_message
from app.models import IntakeState
from app.tickets import find_ticket_by_id
from app.whatsapp import WhatsAppSendResult, list_whatsapp_messages


class IntakeScenarios:
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
                for command in ("abbrechen", "stop", "Stopp!"):
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
        self.send("abbrechen")
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


class BrowserEndpointIntakeRegressions(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
