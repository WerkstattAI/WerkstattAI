from __future__ import annotations

import unittest
from unittest.mock import patch

from app.conversation.existing_ticket import ACCESS_DENIED_REPLY, handle_existing_ticket
from app.conversation.intent import (
    INTENT_EXISTING_TICKET, INTENT_NEW_REQUEST, INTENT_QUOTE_REQUEST, detect_intent,
)
from app.conversation.router import next_step
from app.customer_access import CustomerAccess
from app.models import IntakeState


class CommunicationRoutingTests(unittest.TestCase):
    def setUp(self):
        self.ticket = {
            "ticket_id": "WS-20260926-0042", "workshop_id": "routing-workshop",
            "status": "offen", "fahrzeug": "VW Golf", "baujahr": "2018",
            "kilometerstand": "80000", "problem": "Motorlampe leuchtet",
            "telefon": "017012345678", "name": "Testkunde", "priority": "normal",
            "notes": [{"type": "internal_note", "text": "Private interne Kalkulation"}],
        }
        self.state = IntakeState(
            workshop_id="routing-workshop", ticket_id=self.ticket["ticket_id"],
            mode="new", step="fertig",
        )
        self.access = CustomerAccess("routing-workshop", frozenset({self.ticket["ticket_id"]}))
        self.find = patch("app.conversation.existing_ticket.find_ticket_by_id", return_value=self.ticket).start()
        self.add = patch("app.conversation.existing_ticket.add_ticket_note", return_value=self.ticket).start()
        patch("app.conversation.existing_ticket.get_workshop", return_value={
            "name": "Testwerkstatt", "address": "Werkstattstraße 7", "phone": "0123456",
            "email": "test@example.invalid", "opening_hours": "Montag: 08:00-17:00",
        }).start()
        self.addCleanup(patch.stopall)

    def handle(self, message):
        return next_step(self.state, message, customer_access=self.access, message_id="wa:test-question")

    def test_status_answer_is_information_and_automatic_answer_with_reply_reference(self):
        _, reply, done = self.handle("Wie ist der Status?")
        self.assertFalse(done)
        self.assertIn("offen", reply)
        self.assertEqual(self.add.call_count, 2)
        incoming, outgoing = self.add.call_args_list
        self.assertEqual(incoming.kwargs["purpose"], "customer_information")
        self.assertFalse(incoming.kwargs["requires_human_action"])
        self.assertEqual(incoming.kwargs["message_id"], "wa:test-question")
        self.assertEqual(outgoing.kwargs["sender_role"], "assistant")
        self.assertEqual(outgoing.kwargs["purpose"], "automatic_answer")
        self.assertEqual(outgoing.kwargs["reply_to_message_id"], "wa:test-question")

    def test_workshop_decisions_are_human_questions_even_with_status_keyword(self):
        for message in (
            "Wie lange dauert die Reparatur?", "Wann ist mein Auto fertig?", "Ist mein Auto schon fertig?",
            "Was kostet die Reparatur?", "Wie teuer wird es?", "Welche Diagnose habt ihr?",
            "Ist der Termin bestätigt?", "Sind die Ersatzteile da?", "Kann ich das Auto abholen?",
            "Wie ist der Status und wann ist es fertig?", "Ist mein Fahrzeug sicher?",
        ):
            with self.subTest(message=message):
                self.add.reset_mock()
                _, reply, _ = self.handle(message)
                self.assertEqual(self.state.ticket_id, self.ticket["ticket_id"])
                self.assertIn("weitergegeben", reply)
                self.assertEqual(self.add.call_count, 2)
                self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_question")
                self.assertTrue(self.add.call_args_list[0].kwargs["requires_human_action"])

    def test_status_of_explicit_owned_ticket_remains_a_stored_fact(self):
        _, reply, _ = self.handle(f"Wie ist der Status von {self.ticket['ticket_id']}?")
        self.assertIn("offen", reply)
        self.assertFalse(self.add.call_args_list[0].kwargs["requires_human_action"])
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_information")

    def test_unrecognised_question_is_never_answered_by_ticket_summary(self):
        _, reply, _ = self.handle("Warum bekomme ich keine Rückmeldung?")
        self.assertIn("weitergegeben", reply)
        self.assertNotIn("Motorlampe", reply)
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_question")

    def test_mixed_status_and_unrecognised_question_goes_to_workshop(self):
        _, reply, _ = self.handle("Wie ist der Status und kann ich bar bezahlen?")
        self.assertIn("weitergegeben", reply)
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_question")

    def test_vehicle_word_alone_does_not_make_an_unknown_question_safe(self):
        _, reply, _ = self.handle("Ist mein Auto blau?")
        self.assertIn("weitergegeben", reply)
        self.assertEqual(self.add.call_count, 2)

    def test_saved_vehicle_fields_can_be_automatically_reported(self):
        _, reply, _ = self.handle("Welches Fahrzeug ist gespeichert?")
        self.assertIn("VW Golf", reply)
        self.assertIn("80000", reply)
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_information")
        self.assertFalse(self.add.call_args_list[0].kwargs["requires_human_action"])

    def test_saved_workshop_profile_is_answered_inside_existing_ticket(self):
        for message, expected in (
            ("Welche Öffnungszeiten habt ihr?", "08:00-17:00"),
            ("Wo ist eure Werkstatt?", "Werkstattstraße 7"),
            ("Welche Telefonnummer habt ihr?", "0123456"),
        ):
            with self.subTest(message=message):
                self.add.reset_mock()
                _, reply, _ = self.handle(message)
                self.assertIn(expected, reply)
                self.assertEqual(self.add.call_count, 2)
                self.assertFalse(self.add.call_args_list[0].kwargs["requires_human_action"])

    def test_profile_keyword_does_not_override_schedule_request(self):
        _, reply, _ = self.handle("Habt ihr Samstag offen und Zeit für eine Reparatur?")
        self.assertIn("weitergegeben", reply)
        self.assertEqual(self.add.call_count, 2)

    def test_information_is_not_mislabelled_as_a_customer_question(self):
        _, reply, _ = self.handle("Ich bringe den Fahrzeugschein mit.")
        self.assertIn("Nachricht", reply)
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_information")
        self.assertTrue(self.add.call_args_list[0].kwargs["requires_human_action"])

    def test_acknowledgement_does_not_open_a_task_or_emit_another_answer(self):
        _, reply, _ = self.handle("Vielen Dank!")
        self.assertEqual(reply, "")
        self.assertEqual(self.add.call_args_list[0].kwargs["purpose"], "customer_information")
        self.assertFalse(self.add.call_args_list[0].kwargs["requires_human_action"])

    def test_internal_notes_are_never_customer_facts(self):
        _, reply, _ = self.handle("Gibt es eine Notiz?")
        self.assertIn("noch keine Antwort", reply)
        self.assertNotIn("Private interne", reply)

    def test_definitively_failed_workshop_messages_are_not_repeated_as_delivered_facts(self):
        self.ticket["notes"].append({
            "sender_role": "workshop", "purpose": "workshop_notification", "type": "customer_reply",
            "text": "Diese Nachricht konnte nicht zugestellt werden", "delivery_status": "failed",
        })
        _, reply, _ = self.handle("Gibt es eine Notiz?")
        self.assertIn("noch keine Antwort", reply)
        self.assertNotIn("nicht zugestellt", reply)

    def test_foreign_ticket_access_fails_before_any_message_is_saved(self):
        self.find.return_value = {**self.ticket, "workshop_id": "other-workshop"}
        _, reply, _ = self.handle("Wie ist der Status?")
        self.assertEqual(reply, ACCESS_DENIED_REPLY)
        self.add.assert_not_called()

    def test_storage_failure_is_propagated_instead_of_false_forwarding_claim(self):
        self.add.side_effect = RuntimeError("database unavailable")
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            self.handle("Wie lange dauert es?")

    def test_ticket_price_stays_in_existing_context_and_new_intake_remains_explicit(self):
        for message in ("Was kostet es?", "Preisliste", "Öffnungszeiten", "Allgemeine Frage"):
            self.assertEqual(detect_intent(self.state, message), INTENT_EXISTING_TICKET)
        self.assertEqual(detect_intent(self.state, "Neues Problem"), INTENT_NEW_REQUEST)
        self.assertEqual(detect_intent(IntakeState(), "Was kostet Ölwechsel?"), INTENT_QUOTE_REQUEST)

    def test_direct_ticket_reference_takes_precedence_over_price_intent(self):
        self.assertEqual(
            detect_intent(IntakeState(), f"Was kostet es für Ticket {self.ticket['ticket_id']}?"),
            INTENT_EXISTING_TICKET,
        )

    def test_active_intake_keeps_phone_answer_in_intake(self):
        state = IntakeState(mode="new", step="telefon", workshop_id="routing-workshop")
        self.assertEqual(detect_intent(state, "017012345678"), INTENT_NEW_REQUEST)


if __name__ == "__main__":
    unittest.main()
