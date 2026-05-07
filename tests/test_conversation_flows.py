from __future__ import annotations

import unittest
from unittest.mock import patch

from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    INTENT_QUOTE_REQUEST,
    detect_intent,
)
from app.models import IntakeState


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


if __name__ == "__main__":
    unittest.main()
