from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import test_conversation_flows as fixture  # Isolated application configuration.
import test_communication_transport as transport
from test_communication_ui import FormFields

from app.communication import open_customer_questions, pending_workshop_question
from app.manual_dispatch import send_workshop_message
from app.tickets import add_ticket_note, set_ticket_conversation_state
from app.web import dashboard_whatsapp, ticket_detail
from app.whatsapp import WhatsAppSendResult


class CustomerHandoffScenarios:
    seed_ticket = transport.CommunicationTransportTests.seed_ticket
    ticket = transport.CommunicationTransportTests.ticket
    payload = transport.CommunicationTransportTests.payload
    request = transport.CommunicationTransportTests.request
    webhook = transport.CommunicationTransportTests.webhook
    inbound = transport.CommunicationTransportTests.inbound
    tearDown = transport.CommunicationTransportTests.tearDown

    def setUp(self):
        transport.CommunicationTransportTests.setUp(self)
        self.seed_ticket(channel=self.channel, stale_intake=True)

    def note(self, text, purpose, message_id, **kwargs):
        return add_ticket_note(self.ticket_id, text, workshop_id=self.wid,
                               purpose=purpose, message_id=message_id, **kwargs)

    def receive(self, text, message_id="mixed-customer-message"):
        before = len(self.ticket()["notes"])
        with patch.object(transport.reliability.main, "send_whatsapp_text_message") as send:
            if self.channel == "whatsapp":
                result = self.inbound(text, message_id)
                self.assertEqual(result["manual_pending"], 1)
            else:
                result = transport.reliability.main.process_chat_message(
                    workshop_id=self.wid, session_id=self.session_id,
                    message=text, channel=self.channel, message_id=message_id,
                )
                self.assertEqual(result.reply, "")
                self.assertEqual(result.data["step"], "telefon")
            send.assert_not_called()
        ticket = self.ticket()
        self.assertEqual(len(ticket["notes"]), before + 1)
        self.assertEqual(ticket["status"], "offen")
        self.assertNotEqual(ticket["conversation_state"], "assistant_active")
        note = ticket["notes"][-1]
        self.assertEqual(note["text"], text)
        self.assertEqual(note["sender_role"], "customer")
        return note

    def assert_panel_target(self, message_id, *, present=True):
        request = fixture._dashboard_request(self.wid)
        request.state.csp_nonce = "handoff-test"
        responses = [ticket_detail(request, self.ticket_id, workshop_id=self.wid)]
        if self.channel == "whatsapp":
            responses.append(dashboard_whatsapp(request, phone=self.phone, workshop_id=self.wid))
        for response in responses:
            self.assertEqual(response.status_code, 200)
            target = FormFields(response.body.decode()).selects["reply_to_message_id"]
            values = [option["value"] for option in target["options"]]
            self.assertEqual(values.count(message_id), 1 if present else 0)
            if present:
                # JavaScript enables the picker only after choosing "Antwort".
                self.assertNotIn("disabled", next(option for option in target["options"] if option["value"] == message_id))

    def test_pure_answer_keeps_reference_without_opening_question(self):
        self.note("Sollen wir die Bremsen wechseln?", "workshop_question", "workshop-question")
        note = self.receive("Ja, bitte.")
        self.assertEqual(note["reply_to_message_id"], "workshop-question")
        self.assertEqual(note["purpose"], "customer_information")
        self.assertEqual(open_customer_questions(self.ticket()), [])
        self.assertIsNone(pending_workshop_question(self.ticket()))
        self.assertEqual(self.ticket()["conversation_state"], "workshop_active")

    def test_answer_classification_with_pending_workshop_question(self):
        examples = [
            ("Sollen wir die Bremsen wechseln?", "Ja, bitte.", False),
            ("Sollen wir die Reparatur durchführen?", "Ja, bitte die Reparatur durchführen.", False),
            ("Bestätigen Sie den Termin?", "Den Termin bestätige ich.", False),
            ("Sind Sie mit 400 Euro einverstanden?", "Mit den Kosten von 400 Euro bin ich einverstanden.", False),
            ("Sollen wir die Bremsen wechseln?", "Ja, bitte. Was kostet das insgesamt?", True),
            ("Sollen wir die Reparatur durchführen?", "Ja, bitte die Reparatur durchführen. Wann ist das Auto fertig?", True),
            ("Bestätigen Sie den Termin?", "Den Termin bestätige ich. Welche Unterlagen soll ich mitbringen?", True),
            ("Sollen wir die Bremsen wechseln?", "Ja, bitte. Was kostet das insgesamt", True),
            ("Bestätigen Sie den Termin?", "Ja, bitte. Welche Unterlagen soll ich mitbringen", True),
            ("Bringen Sie den Fahrzeugschein mit?", "Ja! Wo soll ich ihn abgeben", True),
            ("Bringen Sie den Fahrzeugschein mit?", "Ja; kann ich ihn vorher vorbeibringen", True),
        ]
        for index, (question, text, expected_question) in enumerate(examples):
            with self.subTest(text=text):
                self.seed_ticket(channel=self.channel, stale_intake=True)
                target = f"workshop-question-{index}"
                self.note(question, "workshop_question", target)
                note = self.receive(text, f"customer-answer-{index}")
                self.assertEqual(note["reply_to_message_id"], target)
                self.assertEqual(note["purpose"], "customer_question" if expected_question else "customer_information")
                self.assertEqual(open_customer_questions(self.ticket()), [note] if expected_question else [])
                self.assertIsNone(pending_workshop_question(self.ticket()))
                self.assert_panel_target(note["message_id"], present=expected_question)

    def test_decision_terms_without_pending_question_keep_existing_handoff(self):
        for index, text in enumerate(("Reparatur", "Termin", "Kosten", "Welche Unterlagen soll ich mitbringen")):
            with self.subTest(text=text):
                self.seed_ticket(channel=self.channel, stale_intake=True)
                set_ticket_conversation_state(self.ticket_id, "workshop_active", self.wid)
                note = self.receive(text, f"standalone-question-{index}")
                self.assertEqual(note["purpose"], "customer_question")
                self.assertIsNone(note["reply_to_message_id"])
                self.assertEqual(open_customer_questions(self.ticket()), [note])

    def test_mixed_answer_is_one_linked_open_question_and_panel_target(self):
        self.note("Sollen wir die Bremsen wechseln?", "workshop_question", "workshop-question")
        text = "Ja, bitte. Was kostet das insgesamt?"
        note = self.receive(text)
        self.assertEqual(note["reply_to_message_id"], "workshop-question")
        self.assertEqual(note["purpose"], "customer_question")
        self.assertTrue(note["requires_human_action"])
        self.assertIsNone(note["resolved_at"])
        self.assertEqual(open_customer_questions(self.ticket()), [note])
        self.assertIsNone(pending_workshop_question(self.ticket()))
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_workshop")
        self.assert_panel_target(note["message_id"])
        if self.channel == "whatsapp":
            before = self.ticket()["notes"]
            with patch.object(transport.reliability.main, "send_whatsapp_text_message") as send:
                self.assertEqual(self.inbound(text, "mixed-customer-message")["ignored"], 1)
                send.assert_not_called()
            self.assertEqual(self.ticket()["notes"], before)

    def test_question_without_pending_workshop_question_keeps_existing_behavior(self):
        set_ticket_conversation_state(self.ticket_id, "workshop_active", self.wid)
        note = self.receive("Was kostet das insgesamt?")
        self.assertEqual(note["purpose"], "customer_question")
        self.assertIsNone(note["reply_to_message_id"])
        self.assertEqual(open_customer_questions(self.ticket()), [note])

    def test_two_pending_workshop_questions_still_select_the_latest(self):
        self.note("Bringen Sie den Fahrzeugschein mit?", "workshop_question", "older-question")
        self.note("Sollen wir die Bremsen wechseln?", "workshop_question", "newer-question")
        note = self.receive("Ja, bitte. Was kostet das insgesamt?")
        self.assertEqual(note["reply_to_message_id"], "newer-question")
        self.assertEqual(open_customer_questions(self.ticket()), [note])
        self.assertEqual(pending_workshop_question(self.ticket())["message_id"], "older-question")

    def test_targeted_answer_closes_only_extra_question_and_preserves_original_reference(self):
        self.note("Wann ist das Auto fertig?", "customer_question", "other-customer-question")
        self.note("Sollen wir die Bremsen wechseln?", "workshop_question", "workshop-question")
        note = self.receive("Ja, bitte. Was kostet das insgesamt?")
        self.note("Wir haben Ihre Nachricht erhalten.", "workshop_notification", "notification")
        self.assertEqual(len(open_customer_questions(self.ticket())), 2)

        if self.channel == "whatsapp":
            def accepted_send():
                self.assertEqual(len(open_customer_questions(self.ticket())), 2)
                return WhatsAppSendResult(True, 200, "wamid.synthetic-answer", {})

            send = Mock(side_effect=accepted_send)
            result = send_workshop_message(
                workshop_id=self.wid, customer_phone=self.phone, phone_number_id="reliability-sender",
                ticket_id=self.ticket_id, text="Insgesamt 400 Euro.", purpose="workshop_answer",
                reply_to_message_id=note["message_id"], message_id="targeted-workshop-answer",
                send=send, source="test",
            )
            self.assertTrue(result.ok)
            send.assert_called_once()
        else:
            self.note("Insgesamt 400 Euro.", "workshop_answer", "targeted-workshop-answer",
                      reply_to_message_id=note["message_id"])

        ticket = self.ticket()
        self.assertEqual([q["message_id"] for q in open_customer_questions(ticket)], ["other-customer-question"])
        updated = next(n for n in ticket["notes"] if n["message_id"] == note["message_id"])
        self.assertTrue(updated["resolved_at"])
        self.assertEqual({**updated, "resolved_at": None}, note)
        self.assertEqual(ticket["notes"][-1]["reply_to_message_id"], note["message_id"])
        self.assertEqual(sum(n["message_id"] == note["message_id"] for n in ticket["notes"]), 1)
        self.assertEqual(ticket["status"], "offen")
        self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")
        self.assertIsNone(pending_workshop_question(ticket))
        self.assert_panel_target(note["message_id"], present=False)
        self.assert_panel_target("other-customer-question")


class WhatsAppCustomerHandoffTests(CustomerHandoffScenarios, unittest.TestCase):
    channel = "whatsapp"


class WebChatCustomerHandoffTests(CustomerHandoffScenarios, unittest.TestCase):
    channel = "web_chat"
