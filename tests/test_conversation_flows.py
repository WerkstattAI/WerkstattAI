from __future__ import annotations

import unittest
from unittest.mock import patch

from app.db import get_conn, init_db
from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.general_question import handle_general_question
from app.conversation.new_request import handle_new_request
from app.conversation.quote_request import handle_quote_request
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    INTENT_QUOTE_REQUEST,
    INTENT_UNCLEAR,
    detect_intent,
)
from app.conversation.router import next_step
from app.models import IntakeState
from app.main import whatsapp_session_id
from app.tickets import (
    find_ticket_by_id,
    find_tickets_by_phone,
    list_latest_tickets,
    save_ticket,
)


class IntentTests(unittest.TestCase):
    def test_short_contact_question_is_general(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kontakt"),
            INTENT_GENERAL_QUESTION,
        )

    def test_phone_number_is_existing_ticket_reference(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Meine Nummer ist 0176 1234567"),
            INTENT_EXISTING_TICKET,
        )

    def test_inline_vehicle_data_starts_new_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "VW Golf 2018 95000 km"),
            INTENT_NEW_REQUEST,
        )

    def test_quote_question_is_quote_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Was kostet ein Zahnriemenwechsel?"),
            INTENT_QUOTE_REQUEST,
        )

    def test_location_question_is_general(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Wo ist eure Werkstatt?"),
            INTENT_GENERAL_QUESTION,
        )

    def test_unclear_ai_style_request_is_not_new_ticket(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kannst du mir einen Text schreiben?"),
            INTENT_UNCLEAR,
        )

    def test_generic_help_request_is_unclear(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kannst du helfen?"),
            INTENT_UNCLEAR,
        )

    def test_unclear_message_does_not_start_new_request(self) -> None:
        state, reply, done = next_step(IntakeState(), "Kannst du mir helfen?")

        self.assertFalse(done)
        self.assertEqual(state.mode, "unknown")
        self.assertIn("kein freier KI-Chat", reply)
        self.assertIn("Problem melden", reply)

    def test_existing_ticket_mode_can_switch_to_new_request(self) -> None:
        state = IntakeState(mode="existing", ticket_id="WS-20260505-0005")

        self.assertEqual(
            detect_intent(state, "Ich möchte ein Problem melden."),
            INTENT_NEW_REQUEST,
        )


class IntentMatrixTests(unittest.TestCase):
    CASES = [
        # Problem melden
        ("Mein Auto springt nicht an", INTENT_NEW_REQUEST),
        ("Die Motorkontrollleuchte leuchtet", INTENT_NEW_REQUEST),
        ("VW Golf 2018 95000 km", INTENT_NEW_REQUEST),
        ("Ich habe ein Problem mit der Bremse", INTENT_NEW_REQUEST),
        ("Problem melden", INTENT_NEW_REQUEST),
        # Kostenvoranschlag anfragen
        ("Was kostet ein Ölwechsel?", INTENT_QUOTE_REQUEST),
        ("Ich brauche ein Angebot für Kupplung wechseln", INTENT_QUOTE_REQUEST),
        ("Wie teuer ist ein Reifenwechsel?", INTENT_QUOTE_REQUEST),
        ("Kostenvoranschlag anfragen", INTENT_QUOTE_REQUEST),
        ("Preis für Bremsen wechseln bitte", INTENT_QUOTE_REQUEST),
        # Anfrage zu einem bestehenden Ticket
        ("Wie ist der Status von Ticket WS-20260505-0005?", INTENT_EXISTING_TICKET),
        ("Ist mein Auto schon fertig? Ticket WS-20260505-0005", INTENT_EXISTING_TICKET),
        ("Meine Telefonnummer ist 0176 1234567", INTENT_EXISTING_TICKET),
        ("Anfrage zu einem bestehenden Ticket", INTENT_EXISTING_TICKET),
        ("Kann ich mein Fahrzeug zu Auftrag 123 abholen?", INTENT_EXISTING_TICKET),
        # Allgemeine Frage
        ("Wie sind eure Öffnungszeiten?", INTENT_GENERAL_QUESTION),
        ("Wo ist eure Werkstatt?", INTENT_GENERAL_QUESTION),
        ("Welche Telefonnummer habt ihr?", INTENT_GENERAL_QUESTION),
        ("Welche Leistungen bietet ihr an?", INTENT_GENERAL_QUESTION),
        ("Habt ihr einen Abschleppdienst?", INTENT_GENERAL_QUESTION),
        # Unclear / kontrollierter Fallback
        ("Kannst du mir helfen?", INTENT_UNCLEAR),
        ("Schreib mir eine Antwort", INTENT_UNCLEAR),
        ("Formuliere mir bitte eine Nachricht", INTENT_UNCLEAR),
        ("Hallo", INTENT_UNCLEAR),
        ("Was soll ich machen?", INTENT_UNCLEAR),
    ]

    def test_common_customer_messages_route_to_expected_intent(self) -> None:
        for message, expected in self.CASES:
            with self.subTest(message=message):
                self.assertEqual(detect_intent(IntakeState(), message), expected)


class WhatsAppWebhookTests(unittest.TestCase):
    def test_whatsapp_session_id_uses_normalized_phone(self) -> None:
        self.assertEqual(
            whatsapp_session_id("+49 176 123 456 78"),
            "whatsapp:4917612345678",
        )


class ExistingTicketTests(unittest.TestCase):
    def test_internal_note_is_not_shown_to_customer(self) -> None:
        ticket = {
            "ticket_id": "WS-20260505-0005",
            "status": "offen",
            "priority": "normal",
            "request_type": "diagnose",
            "fahrzeug": "VW Golf",
            "baujahr": "2018",
            "kilometerstand": "95000",
            "problem": "Motorlampe leuchtet",
            "name": "Lukas Weber",
            "telefon": "+4915112340000",
            "notes": [
                {
                    "type": "internal_note",
                    "text": "Nur fuer die Werkstatt sichtbar",
                    "created_at": "2026-05-05T20:00:00",
                }
            ],
        }

        with patch("app.conversation.existing_ticket.find_ticket_by_id", return_value=ticket), patch(
            "app.conversation.existing_ticket.add_ticket_note"
        ):
            _, reply, done = handle_existing_ticket(
                IntakeState(),
                "Gibt es eine Notiz? Ticket WS-20260505-0005",
            )

        self.assertFalse(done)
        self.assertNotIn("Nur fuer die Werkstatt sichtbar", reply)
        self.assertIn("noch keine Antwort der Werkstatt", reply)

    def test_existing_ticket_message_is_recorded_as_customer_message(self) -> None:
        ticket = {
            "ticket_id": "WS-20260505-0005",
            "status": "offen",
            "priority": "normal",
            "request_type": "diagnose",
            "fahrzeug": "VW Golf",
            "baujahr": "2018",
            "kilometerstand": "95000",
            "problem": "Motorlampe leuchtet",
            "name": "Lukas Weber",
            "telefon": "+4915112340000",
            "notes": [],
        }

        with patch("app.conversation.existing_ticket.find_ticket_by_id", return_value=ticket), patch(
            "app.conversation.existing_ticket.add_ticket_note"
        ) as add_note:
            state, reply, done = handle_existing_ticket(
                IntakeState(),
                "Ist mein Auto fertig? Ticket WS-20260505-0005",
            )

        self.assertFalse(done)
        self.assertEqual(state.ticket_id, "WS-20260505-0005")
        self.assertIn("Status", reply)
        add_note.assert_called_once()
        self.assertEqual(add_note.call_args.kwargs["note_type"], "customer_message")


class GeneralQuestionTests(unittest.TestCase):
    def test_opening_hours_use_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "Welche Öffnungszeiten habt ihr?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("09:00-17:00", reply)


class NewRequestTests(unittest.TestCase):
    def test_early_phone_during_followup_is_stored_not_used_as_answer(self) -> None:
        state = IntakeState(
            mode="new",
            step="followup",
            problem="Motorkontrollleuchte leuchtet und das Auto ruckelt",
            followup_questions=["Seit wann besteht das Problem ungefähr?"],
            followup_answers=[],
            followup_index=0,
        )

        new_state, reply, done = handle_new_request(state, "0176 11122233")

        self.assertFalse(done)
        self.assertEqual(new_state.telefon, "017611122233")
        self.assertEqual(new_state.followup_answers, [])
        self.assertIn("Telefonnummer ist gespeichert", reply)
        self.assertIn("Seit wann besteht", reply)

    def test_switching_from_existing_ticket_to_new_request_clears_ticket_context(self) -> None:
        state = IntakeState(
            mode="existing",
            ticket_id="WS-20260505-0005",
            workshop_id="demo-werkstatt",
        )

        new_state, reply, done = handle_new_request(state, "Ich möchte ein Problem melden.")

        self.assertFalse(done)
        self.assertEqual(new_state.mode, "new")
        self.assertIsNone(new_state.ticket_id)
        self.assertEqual(new_state.workshop_id, "demo-werkstatt")
        self.assertIn("Welche Marke", reply)


class QuoteRequestTests(unittest.TestCase):
    def test_switching_from_existing_ticket_to_quote_clears_ticket_context(self) -> None:
        state = IntakeState(
            mode="existing",
            ticket_id="WS-20260505-0005",
            workshop_id="demo-werkstatt",
        )

        new_state, reply, done = handle_quote_request(state, "Was kostet ein Ölwechsel?")

        self.assertFalse(done)
        self.assertEqual(new_state.mode, "quote")
        self.assertIsNone(new_state.ticket_id)
        self.assertEqual(new_state.workshop_id, "demo-werkstatt")
        self.assertIn("Zu welchem Fahrzeug", reply)


class TicketTenantTests(unittest.TestCase):
    def test_ticket_reads_are_scoped_by_workshop(self) -> None:
        init_db()

        state_a = IntakeState(
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem="Motorlampe leuchtet",
            telefon="+4915112345678",
            name="Lukas Weber",
        )
        state_b = IntakeState(
            fahrzeug="BMW 320d",
            baujahr="2019",
            kilometerstand="88000",
            request_type="service",
            priority="normal",
            problem="Service faellig",
            telefon="+4915112345678",
            name="Anna Klein",
        )

        ticket_a = save_ticket(state_a, workshop_id="tenant-a")
        ticket_b = save_ticket(state_b, workshop_id="tenant-b")

        try:
            self.assertIsNotNone(find_ticket_by_id(ticket_a, workshop_id="tenant-a"))
            self.assertIsNone(find_ticket_by_id(ticket_a, workshop_id="tenant-b"))

            tenant_a_phone_matches = find_tickets_by_phone("+49 151 12345678", workshop_id="tenant-a")
            tenant_b_phone_matches = find_tickets_by_phone("+49 151 12345678", workshop_id="tenant-b")

            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_phone_matches))
            self.assertFalse(any(t["ticket_id"] == ticket_b for t in tenant_a_phone_matches))
            self.assertTrue(any(t["ticket_id"] == ticket_b for t in tenant_b_phone_matches))
            self.assertFalse(any(t["ticket_id"] == ticket_a for t in tenant_b_phone_matches))

            tenant_a_latest = list_latest_tickets(workshop_id="tenant-a")
            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_latest))
            self.assertFalse(any(t["ticket_id"] == ticket_b for t in tenant_a_latest))
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM tickets WHERE ticket_id IN (?, ?)",
                    (ticket_a, ticket_b),
                )
                conn.commit()


if __name__ == "__main__":
    unittest.main()
