from __future__ import annotations

import unittest
from unittest.mock import patch

from app.auth import authenticate_user, create_session_token, decode_session_token
from app.db import get_conn, init_db
from app.config import settings
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
from app.main import process_chat_message, whatsapp_session_id
from app.tickets import (
    add_ticket_note,
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


class MessyCustomerIntentTests(unittest.TestCase):
    CASES = [
        # Potoczne lub niedokladne problemy
        ("auto kaputt", INTENT_NEW_REQUEST),
        ("karre geht nicht an", INTENT_NEW_REQUEST),
        ("mein wagen macht komische geräusche", INTENT_NEW_REQUEST),
        ("irgendwas stinkt beim fahren", INTENT_NEW_REQUEST),
        ("motor leuchtet gelb und ruckelt", INTENT_NEW_REQUEST),
        ("bremsen machen komische geraeusche", INTENT_NEW_REQUEST),
        ("hilfe mein auto startet nicht", INTENT_NEW_REQUEST),
        # Koszty pisane po ludzku, bez idealnej skladni
        ("wieviel kostet ölwechsel", INTENT_QUOTE_REQUEST),
        ("was kostet kupplung wechseln ungefähr", INTENT_QUOTE_REQUEST),
        ("preis bremsen wechseln?", INTENT_QUOTE_REQUEST),
        ("ungefähr kosten für reifenwechsel", INTENT_QUOTE_REQUEST),
        ("angebot fuer service bitte", INTENT_QUOTE_REQUEST),
        # Istniejacy ticket bez perfekcyjnej formy
        ("ticket ws-20260505-0005 status?", INTENT_EXISTING_TICKET),
        ("hab ticket WS-20260505-0005, auto fertig?", INTENT_EXISTING_TICKET),
        ("auftrag 123 was ist los", INTENT_EXISTING_TICKET),
        ("meine nummer wegen ticket ist 0176 1234567", INTENT_EXISTING_TICKET),
        # Ogolne pytania klienta
        ("wann habt ihr offen", INTENT_GENERAL_QUESTION),
        ("wo genau seid ihr", INTENT_GENERAL_QUESTION),
        ("habt ihr samstags offen?", INTENT_GENERAL_QUESTION),
        ("macht ihr auch abschleppen?", INTENT_GENERAL_QUESTION),
        ("was macht eure werkstatt alles?", INTENT_GENERAL_QUESTION),
        # Ludzie pisza jak do ChatGPT lub bardzo niejasno
        ("schreib mal bitte eine nachricht", INTENT_UNCLEAR),
        ("antwort mir wie eine ki", INTENT_UNCLEAR),
        ("ich weiss nicht was ich schreiben soll", INTENT_UNCLEAR),
        ("hallo guten tag", INTENT_UNCLEAR),
        ("???", INTENT_UNCLEAR),
    ]

    def test_messy_customer_messages_route_safely(self) -> None:
        for message, expected in self.CASES:
            with self.subTest(message=message):
                self.assertEqual(detect_intent(IntakeState(), message), expected)


class WhatsAppWebhookTests(unittest.TestCase):
    def test_whatsapp_session_id_uses_normalized_phone(self) -> None:
        self.assertEqual(
            whatsapp_session_id("+49 176 123 456 78"),
            "whatsapp:4917612345678",
        )


class AuthTests(unittest.TestCase):
    def test_default_dashboard_admin_can_authenticate(self) -> None:
        init_db()

        user = authenticate_user(
            settings.dashboard_admin_email,
            settings.dashboard_admin_password,
        )

        self.assertIsNotNone(user)
        self.assertEqual(user["workshop_id"], "demo-werkstatt")

    def test_session_token_roundtrip(self) -> None:
        user = {
            "email": "admin@werkstatt.local",
            "workshop_id": "demo-werkstatt",
            "role": "owner",
        }

        token = create_session_token(user)
        decoded = decode_session_token(token)

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["email"], user["email"])
        self.assertEqual(decoded["workshop_id"], user["workshop_id"])
        self.assertEqual(decoded["role"], user["role"])

    def test_tampered_session_token_is_rejected(self) -> None:
        user = {
            "email": "admin@werkstatt.local",
            "workshop_id": "demo-werkstatt",
            "role": "owner",
        }

        token = create_session_token(user)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        self.assertIsNone(decode_session_token(tampered))


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

    def test_informal_saturday_opening_hours_question_uses_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "habt ihr samstags offen?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("Samstag", reply)


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

    def test_problem_first_message_is_not_used_as_vehicle_name(self) -> None:
        state, reply, done = handle_new_request(IntakeState(), "karre geht nicht an")

        self.assertFalse(done)
        self.assertIsNone(state.fahrzeug)
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertIn("Verstanden", reply)
        self.assertIn("Marke und Modell", reply)

    def test_problem_first_flow_reuses_problem_after_vehicle_details(self) -> None:
        state, _, done = handle_new_request(IntakeState(), "karre geht nicht an")
        self.assertFalse(done)

        state, reply, done = handle_new_request(state, "BMW 320d")
        self.assertFalse(done)
        self.assertEqual(state.fahrzeug, "BMW 320d")
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertIn("Baujahr", reply)

        state, reply, done = handle_new_request(state, "2018")
        self.assertFalse(done)
        self.assertEqual(state.baujahr, "2018")
        self.assertIn("Kilometerstand", reply)

        state, reply, done = handle_new_request(state, "120000")
        self.assertFalse(done)
        self.assertEqual(state.kilometerstand, "120000")
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertEqual(state.request_type, "notfall")
        self.assertEqual(state.priority, "hoch")
        self.assertEqual(state.fahrbereit, "nein")
        self.assertIn("Abschleppdienst", reply)

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


class EndToEndConversationTests(unittest.TestCase):
    WORKSHOP_ID = "demo-werkstatt"

    def _send(self, session_id: str, message: str):
        return process_chat_message(
            workshop_id=self.WORKSHOP_ID,
            session_id=session_id,
            message=message,
            channel="test",
        )

    def _cleanup(self, session_ids: list[str], ticket_ids: list[str]) -> None:
        with get_conn() as conn:
            for session_id in session_ids:
                conn.execute(
                    "DELETE FROM conversation_sessions WHERE session_id = ?",
                    (f"{self.WORKSHOP_ID}:{session_id}",),
                )
            for ticket_id in ticket_ids:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
            conn.commit()

    def test_service_flow_creates_service_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-service"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "Audi A4 2019 120000 km")
            self._send(session_id, "Inspektion und Ölwechsel")
            self._send(session_id, "0176 44411122")
            response = self._send(session_id, "Service Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "service")
            self.assertEqual(ticket["priority"], "niedrig")
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_notfall_flow_creates_high_priority_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-notfall"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "BMW 320d 2017 130000 km")
            self._send(session_id, "Auto springt nicht an und steht auf der Straße")
            self._send(session_id, "ja")
            self._send(session_id, "nein")
            self._send(session_id, "0176 44422233")
            response = self._send(session_id, "Notfall Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "notfall")
            self.assertEqual(ticket["priority"], "hoch")
            self.assertFalse(ticket["fahrbereit"])
            self.assertTrue(ticket["abschleppdienst"])
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_quote_flow_creates_quote_ticket_from_messy_price_question(self) -> None:
        init_db()
        session_id = "test-e2e-quote"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "wieviel kostet ölwechsel")
            self._send(session_id, "VW Polo 2015")
            self._send(session_id, "0176 44433344")
            response = self._send(session_id, "Quote Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "kostenvoranschlag")
            self.assertEqual(ticket["fahrzeug"], "VW Polo")
        finally:
            self._cleanup([session_id], ticket_ids)


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


class TicketMetadataTests(unittest.TestCase):
    def test_ticket_source_is_saved(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem="Motorlampe leuchtet",
            telefon="+4915112345678",
            name="Lukas Weber",
            source="whatsapp",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            ticket = find_ticket_by_id(ticket_id, workshop_id="demo-werkstatt")

            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["source"], "whatsapp")
            self.assertFalse(ticket["customer_question_open"])
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()

    def test_customer_question_open_toggles_with_customer_reply(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="BMW 320d",
            baujahr="2019",
            kilometerstand="88000",
            request_type="diagnose",
            priority="normal",
            problem="Klimaanlage kuehlt nicht",
            telefon="+4915112345678",
            name="Anna Klein",
            source="web_chat",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            ticket = add_ticket_note(
                ticket_id,
                "Kundenfrage über den Chat: Ist mein Auto morgen fertig?",
                note_type="customer_message",
                workshop_id="demo-werkstatt",
            )
            self.assertTrue(ticket["customer_question_open"])

            ticket = add_ticket_note(
                ticket_id,
                "Wir melden uns morgen Vormittag mit einer Einschätzung.",
                note_type="customer_reply",
                workshop_id="demo-werkstatt",
            )
            self.assertFalse(ticket["customer_question_open"])
            self.assertEqual(ticket["status"], "in_bearbeitung")
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()

    def test_customer_reply_does_not_reopen_done_ticket(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="Mercedes C-Klasse",
            baujahr="2020",
            kilometerstand="65000",
            request_type="diagnose",
            priority="normal",
            problem="Bremse quietscht",
            telefon="+4915112345678",
            name="Tom Becker",
            source="web_chat",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE tickets SET status = ? WHERE ticket_id = ?",
                    ("erledigt", ticket_id),
                )
                conn.commit()

            ticket = add_ticket_note(
                ticket_id,
                "Ihr Fahrzeug ist fertig.",
                note_type="customer_reply",
                workshop_id="demo-werkstatt",
            )

            self.assertEqual(ticket["status"], "erledigt")
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
