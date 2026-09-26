from __future__ import annotations

import unittest
from unittest.mock import patch

from app.conversation.existing_ticket import ACCESS_DENIED_REPLY, handle_existing_ticket
from app.conversation.router import next_step
from app.customer_access import CustomerAccess, normalize_customer_phone
from app.models import IntakeState


class CustomerAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.own_id = "WS-20260915-0001"
        self.other_id = "WS-20260915-0002"
        self.phone = "+49 170 12345678"
        self.own = self.ticket(self.own_id, self.phone)
        self.other = self.ticket(self.other_id, "+49 171 98765432")
        self.access = CustomerAccess("workshop-a", frozenset({self.own_id}))
        self.state = IntakeState(workshop_id="workshop-a", mode="existing")
        self.find = patch("app.conversation.existing_ticket.find_ticket_by_id").start()
        self.by_phone = patch("app.conversation.existing_ticket.find_tickets_by_phone").start()
        self.add_note = patch("app.conversation.existing_ticket.add_ticket_note").start()
        self.addCleanup(patch.stopall)

    @staticmethod
    def ticket(ticket_id, phone, workshop_id="workshop-a"):
        return {
            "ticket_id": ticket_id,
            "workshop_id": workshop_id,
            "telefon": phone,
            "verified_customer_phone": phone,
            "name": "Private customer name",
            "fahrzeug": "Private customer vehicle",
            "problem": "Private problem details",
            "status": "in Bearbeitung",
            "priority": "normal",
            "notes": [{"type": "internal_note", "text": "Private workshop note"}],
        }

    def handle(self, message, access=None):
        return handle_existing_ticket(self.state, message, customer_access=access)

    def assert_denied(self, reply):
        self.assertEqual(reply, ACCESS_DENIED_REPLY)
        for sensitive in (self.own_id, self.other_id, "Private", "Bearbeitung"):
            self.assertNotIn(sensitive, reply)
        self.add_note.assert_not_called()

    def test_ticket_reference_without_server_context_is_denied_before_lookup(self):
        self.find.return_value = self.other
        _, reply, done = self.handle(f"Zeige Ticket {self.other_id}")
        self.assert_denied(reply)
        self.assertFalse(done)
        self.find.assert_not_called()
        self.by_phone.assert_not_called()

    def test_customer_entered_phone_and_remembered_id_do_not_grant_access(self):
        self.state.telefon = self.other["telefon"]
        self.state.ticket_id = self.other_id
        self.find.return_value = self.other
        _, reply, _ = self.handle("Wie ist der Status?")
        self.assert_denied(reply)
        self.find.assert_not_called()

    def test_empty_browser_grants_cannot_be_replaced_by_intake_phone(self):
        self.state.telefon = self.other["telefon"]
        self.find.return_value = self.other
        _, reply, _ = self.handle(f"Ticket {self.other_id}", CustomerAccess("workshop-a"))
        self.assert_denied(reply)

    def test_foreign_and_missing_ticket_receive_identical_reply(self):
        replies = []
        for ticket in (self.other, None):
            self.find.return_value = ticket
            _, reply, _ = self.handle(f"Ticket {self.other_id}", self.access)
            replies.append(reply)
            self.assert_denied(reply)
        self.assertEqual(replies[0], replies[1])

    def test_browser_session_can_read_own_ticket_and_record_question(self):
        self.find.return_value = self.own
        state, reply, done = self.handle(f"Status Ticket {self.own_id}", self.access)
        self.assertFalse(done)
        self.assertIn(self.own_id, reply)
        self.assertIn("in Bearbeitung", reply)
        self.assertEqual(state.ticket_id, self.own_id)
        self.add_note.assert_called_once()
        self.assertEqual(self.add_note.call_args.args[0], self.own_id)
        self.assertEqual(self.add_note.call_args.kwargs["workshop_id"], "workshop-a")

    def test_denied_foreign_reference_keeps_current_owned_ticket(self):
        self.state.ticket_id = self.own_id
        self.find.return_value = self.other
        state, reply, _ = self.handle(f"Ticket {self.other_id}", self.access)
        self.assert_denied(reply)
        self.assertEqual(state.ticket_id, self.own_id)

    def test_remembered_ticket_requires_authorization_again(self):
        self.state.ticket_id = self.other_id
        self.find.return_value = self.other
        _, reply, _ = self.handle("Wie ist der Status?", self.access)
        self.assert_denied(reply)

    def test_owned_remembered_ticket_can_be_followed_up(self):
        self.state.ticket_id = self.own_id
        self.find.return_value = self.own
        _, reply, _ = self.handle("Wie lange dauert es noch?", self.access)
        self.assertIn(self.own_id, reply)
        self.add_note.assert_called_once()

    def test_context_for_another_workshop_cannot_lookup_state_workshop(self):
        _, reply, _ = self.handle(f"Ticket {self.own_id}", CustomerAccess("workshop-b", frozenset({self.own_id})))
        self.assert_denied(reply)
        self.find.assert_not_called()

    def test_ticket_from_another_workshop_is_denied_even_with_owned_id(self):
        self.find.return_value = {**self.own, "workshop_id": "workshop-b"}
        _, reply, _ = self.handle(f"Ticket {self.own_id}", self.access)
        self.assert_denied(reply)

    def test_ticket_without_workshop_is_denied(self):
        self.find.return_value = {key: value for key, value in self.own.items() if key != "workshop_id"}
        _, reply, _ = self.handle(f"Ticket {self.own_id}", self.access)
        self.assert_denied(reply)

    def test_phone_results_hide_every_foreign_ticket_before_counting(self):
        own_second = self.ticket("WS-20260915-0003", self.phone)
        access = CustomerAccess("workshop-a", frozenset({self.own_id, own_second["ticket_id"]}))
        self.by_phone.return_value = [self.other, self.own, own_second]
        _, reply, _ = self.handle("Meine Telefonnummer ist 0170 12345678", access)
        self.assertIn("**2** Tickets", reply)
        self.assertIn(self.own_id, reply)
        self.assertIn(own_second["ticket_id"], reply)
        self.assertNotIn(self.other_id, reply)
        self.add_note.assert_not_called()

    def test_phone_lookup_with_one_owned_result_does_not_offer_foreign_selection(self):
        self.by_phone.return_value = [self.other, self.own]
        _, reply, _ = self.handle("Meine Telefonnummer ist 0170 12345678", self.access)
        self.assertIn(self.own_id, reply)
        self.assertNotIn(self.other_id, reply)
        self.add_note.assert_called_once()

    def test_phone_lookup_without_owned_result_matches_unknown_number(self):
        for results in ([self.other], []):
            self.by_phone.return_value = results
            _, reply, _ = self.handle("Meine Telefonnummer ist 0171 98765432", self.access)
            self.assert_denied(reply)

    def test_verified_whatsapp_sender_can_access_exact_normalized_number(self):
        self.find.return_value = {**self.own, "telefon": "0170-12345678"}
        access = CustomerAccess("workshop-a", verified_phone="4917012345678")
        _, reply, _ = self.handle(f"Status Ticket {self.own_id}", access)
        self.assertIn(self.own_id, reply)
        self.add_note.assert_called_once()

    def test_whatsapp_sender_cannot_access_foreign_ticket_even_if_id_is_remembered(self):
        self.find.return_value = self.other
        self.state.ticket_id = self.other_id
        access = CustomerAccess("workshop-a", frozenset({self.other_id}), verified_phone="4917012345678")
        _, reply, _ = self.handle("Wie ist der Status?", access)
        self.assert_denied(reply)

    def test_whatsapp_phone_lookup_does_not_authorize_substring_matches(self):
        self.by_phone.return_value = [self.own, {**self.other, "telefon": "12345678"}]
        access = CustomerAccess("workshop-a", verified_phone="4917012345678")
        _, reply, _ = self.handle("Meine Telefonnummer ist 12345678", access)
        self.assertIn(self.own_id, reply)
        self.assertNotIn(self.other_id, reply)
        self.add_note.assert_called_once()

    def test_invalid_verified_phone_never_falls_back_to_browser_grant(self):
        self.find.return_value = self.own
        for invalid in ("", "123", "0", "+", "49ext17012345678"):
            access = CustomerAccess("workshop-a", frozenset({self.own_id}), verified_phone=invalid)
            _, reply, _ = self.handle(f"Ticket {self.own_id}", access)
            self.assert_denied(reply)

    def test_ticket_summary_never_exposes_internal_workshop_notes(self):
        self.find.return_value = self.own
        _, reply, _ = self.handle(f"Zeige Ticket {self.own_id}", self.access)
        self.assertIn("Private problem details", reply)
        self.assertNotIn("Private workshop note", reply)

    def test_router_passes_authorization_to_existing_ticket_handler(self):
        self.find.return_value = self.own
        _, reply, _ = next_step(self.state, f"Status Ticket {self.own_id}", customer_access=self.access)
        self.assertIn(self.own_id, reply)
        self.add_note.assert_called_once()

    def test_router_without_authorization_fails_closed(self):
        _, reply, _ = next_step(self.state, f"Status Ticket {self.own_id}")
        self.assert_denied(reply)
        self.find.assert_not_called()

    def test_rejected_lookup_does_not_prevent_a_new_request(self):
        self.find.return_value = self.other
        self.handle(f"Ticket {self.other_id}", self.access)
        with patch("app.conversation.router.handle_new_request", return_value=(self.state, "Neues Anliegen", False)) as new_request:
            _, reply, _ = next_step(self.state, "Neues Problem", customer_access=self.access)
        self.assertEqual(reply, "Neues Anliegen")
        new_request.assert_called_once()

    def test_full_phone_normalization(self):
        expected = "4917012345678"
        for value in ("+49 170 12345678", "0049-170-12345678", "0170 12345678", "4917012345678"):
            self.assertEqual(normalize_customer_phone(value), expected)
        self.assertNotEqual(normalize_customer_phone("12345678"), expected)
        self.assertNotEqual(normalize_customer_phone("+1 170 12345678"), expected)
        self.assertEqual(normalize_customer_phone("4917012345678 ext 123"), "")


if __name__ == "__main__":
    unittest.main()
