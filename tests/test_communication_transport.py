from __future__ import annotations

import unittest
from unittest.mock import patch

import test_whatsapp_reliability as reliability
from app.communication import open_customer_questions, pending_workshop_question
from app.conversation_sessions import load_session_state, save_session_state
from app.manual_dispatch import send_workshop_message
from app.models import IntakeState, WhatsAppWebhookRequest
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket
from app.whatsapp import WhatsAppSendResult, save_whatsapp_message


class CommunicationTransportTests(unittest.TestCase):
    # Reuse the isolated SQLite and signed Meta request fixture, without
    # inheriting (and re-running) its independent reliability test cases.
    setUp = reliability.WhatsAppReliabilityTests.setUp
    tearDown = reliability.WhatsAppReliabilityTests.tearDown
    payload = reliability.WhatsAppReliabilityTests.payload
    request = reliability.WhatsAppReliabilityTests.request
    webhook = reliability.WhatsAppReliabilityTests.webhook

    def seed_ticket(self, channel="whatsapp", *, stale_intake=False):
        self.session_id = reliability.main.whatsapp_session_id(self.phone) if channel == "whatsapp" else "browser-fixture"
        state = IntakeState(workshop_id=self.wid, fahrzeug="VW Golf", problem="Inspektion",
                            telefon=self.phone, mode="new", step="telefon" if stale_intake else "fertig")
        self.ticket_id = save_ticket(state, workshop_id=self.wid, verified_customer_phone=self.phone)
        state.ticket_id = self.ticket_id
        save_session_state(self.session_id, state, workshop_id=self.wid, channel=channel, phone=self.phone)
        if channel == "whatsapp":
            reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone,
                                                            mode="assistant", active_ticket_id=self.ticket_id)

    def inbound(self, text, message_id="wamid.communication.1"):
        payload = self.payload(message_id)
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = text
        return self.webhook(payload)

    def ticket(self):
        return find_ticket_by_id(self.ticket_id, self.wid)

    def test_whatsapp_status_answers_without_opening_a_workshop_task(self):
        self.seed_ticket()
        with patch.object(reliability.main, "send_whatsapp_text_message",
                          return_value=WhatsAppSendResult(True, 200, "wamid.status.reply", {})) as send:
            result = self.inbound("Wie ist der Status?")
        self.assertEqual(result["processed"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertIn("offen", send.call_args.kwargs["text"])
        ticket = self.ticket()
        self.assertFalse(ticket["customer_question_open"])
        self.assertEqual(open_customer_questions(ticket), [])
        self.assertEqual(ticket["conversation_state"], "assistant_active")
        self.assertEqual([n["purpose"] for n in ticket["notes"]], ["customer_information", "automatic_answer"])
        self.assertEqual(ticket["notes"][1]["reply_to_message_id"], ticket["notes"][0]["message_id"])

    def test_whatsapp_duration_gets_one_handoff_ack_then_remains_with_workshop(self):
        self.seed_ticket()
        with patch.object(reliability.main, "send_whatsapp_text_message",
                          return_value=WhatsAppSendResult(True, 200, "wamid.handoff.reply", {})) as send:
            first = self.inbound("Wie lange dauert die Reparatur?")
            second = self.inbound("Wie ist der Status?", "wamid.communication.2")
        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["manual_pending"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertIn("weitergegeben", send.call_args.kwargs["text"])
        ticket = self.ticket()
        self.assertTrue(ticket["customer_question_open"])
        self.assertEqual(ticket["conversation_state"], "waiting_for_workshop")
        self.assertEqual(len([n for n in ticket["notes"] if n["sender_role"] == "assistant"]), 1)

    def test_whatsapp_customer_answer_to_workshop_question_never_reaches_intake(self):
        self.seed_ticket(stale_intake=True)
        add_ticket_note(self.ticket_id, "Haben Sie den Fahrzeugschein?", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_question", message_id="workshop-question")
        with patch.object(reliability.main, "send_whatsapp_text_message") as send:
            result = self.inbound("Ja, bringe ich mit.")
        send.assert_not_called()
        self.assertEqual(result["manual_pending"], 1)
        ticket = self.ticket()
        customer_note = ticket["notes"][-1]
        self.assertEqual(customer_note["sender_role"], "customer")
        self.assertEqual(customer_note["purpose"], "customer_information")
        self.assertEqual(customer_note["reply_to_message_id"], "workshop-question")
        self.assertEqual(ticket["conversation_state"], "workshop_active")
        state = load_session_state(self.session_id, self.wid, channel="whatsapp")
        self.assertEqual(state.step, "telefon")
        self.assertEqual(state.telefon, self.phone)

    def test_web_customer_answer_does_not_advance_stale_intake_or_release_workshop(self):
        self.seed_ticket(channel="web_chat", stale_intake=True)
        add_ticket_note(self.ticket_id, "Welche Angaben sollen ergänzt werden?", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_question", message_id="web-workshop-question")
        response = reliability.main.process_chat_message(workshop_id=self.wid, session_id=self.session_id,
                                                        message="Neues Problem", channel="web_chat")
        self.assertEqual(response.reply, "")
        self.assertEqual(response.data["step"], "telefon")
        self.assertEqual(response.data["ticket_id"], self.ticket_id)
        self.assertEqual(self.ticket()["notes"][-1]["reply_to_message_id"], "web-workshop-question")
        self.assertEqual(self.ticket()["conversation_state"], "workshop_active")

    def test_only_explicit_assistant_action_resumes_a_whatsapp_conversation(self):
        self.seed_ticket()
        reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="manual")
        with patch.object(reliability.main, "send_whatsapp_text_message",
                          return_value=WhatsAppSendResult(True, 200, "wamid.resumed.reply", {})) as send:
            self.inbound("Status")
            send.assert_not_called()
            reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")
            self.inbound("Wie ist der Status?", "wamid.communication.resumed")
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.ticket()["conversation_state"], "assistant_active")

    def test_local_webhook_format_uses_the_same_pending_question_handoff(self):
        self.seed_ticket(stale_intake=True)
        add_ticket_note(self.ticket_id, "Bringen Sie den Fahrzeugschein mit?", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_question", message_id="local-workshop-question")
        with patch.object(reliability.main, "send_whatsapp_text_message") as send:
            response = reliability.main._process_test_whatsapp_webhook(WhatsAppWebhookRequest.model_validate({
                "workshop_id": self.wid, "from": self.phone, "text": "Ja, bringe ich mit.",
            }))
        send.assert_not_called()
        self.assertEqual(response.reply, "")
        self.assertEqual(response.data["conversation_state"], "workshop_active")
        self.assertEqual(self.ticket()["notes"][-1]["reply_to_message_id"], "local-workshop-question")
        self.assertEqual(load_session_state(self.session_id, self.wid, channel="whatsapp").step, "telefon")

    def test_local_webhook_format_records_handoff_confirmation_once(self):
        self.seed_ticket()
        with patch.object(reliability.main, "send_whatsapp_text_message") as send:
            response = reliability.main._process_test_whatsapp_webhook(WhatsAppWebhookRequest.model_validate({
                "workshop_id": self.wid, "from": self.phone, "text": "Wie lange dauert es?",
            }))
        send.assert_not_called()
        self.assertIn("weitergegeben", response.reply)
        self.assertEqual(response.data["conversation_state"], "waiting_for_workshop")
        self.assertTrue(self.ticket()["customer_question_open"])
        self.assertEqual(len(self.ticket()["notes"]), 2)

    def test_manual_send_is_blocked_while_assistant_http_is_in_flight(self):
        self.seed_ticket()
        manual_http_calls = []

        def manual_http():
            manual_http_calls.append("manual started")
            return WhatsAppSendResult(True, 200, "wamid.manual.overlap", {})

        def assistant_http(**kwargs):
            with self.assertRaises(ValueError):
                send_workshop_message(
                    workshop_id=self.wid, customer_phone=self.phone, phone_number_id="reliability-sender",
                    text="Die Werkstatt meldet sich.", purpose="workshop_notification", reply_to_message_id=None,
                    message_id="manual-during-assistant", ticket_id=self.ticket_id,
                    send=manual_http, source="test",
                )
            return WhatsAppSendResult(True, 200, "wamid.assistant.overlap", {})

        with patch.object(reliability.main, "send_whatsapp_text_message", side_effect=assistant_http):
            result = self.inbound("Wie ist der Status?")
        self.assertEqual(result["processed"], 1)
        self.assertEqual(manual_http_calls, [])
        self.assertFalse(any(n["sender_role"] == "workshop" for n in self.ticket()["notes"]))

    def test_explicit_resume_is_blocked_while_manual_http_is_in_flight(self):
        self.seed_ticket()
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound", text="Hallo")
        attempted_resume = []

        def manual_http():
            attempted_resume.append(True)
            with self.assertRaises(ValueError):
                reliability.db.set_whatsapp_conversation_control(
                    workshop_id=self.wid, customer_phone=self.phone, mode="assistant",
                )
            return WhatsAppSendResult(True, 200, "wamid.manual.blockresume", {})

        result = send_workshop_message(
            workshop_id=self.wid, customer_phone=self.phone, phone_number_id="reliability-sender",
            text="Die Werkstatt meldet sich.", purpose="workshop_notification", reply_to_message_id=None,
            message_id="manual-block-resume", ticket_id=self.ticket_id, send=manual_http, source="test",
        )
        self.assertTrue(result.ok)
        self.assertEqual(attempted_resume, [True])
        self.assertEqual(self.ticket()["conversation_state"], "workshop_active")

    def test_explicit_resume_cancels_old_question_so_new_customer_questions_keep_their_meaning(self):
        self.seed_ticket()
        add_ticket_note(self.ticket_id, "Haben Sie den Fahrzeugschein?", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_question", message_id="old-unanswered-question")
        reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")
        self.assertIsNone(pending_workshop_question(self.ticket()))
        with patch.object(reliability.main, "send_whatsapp_text_message",
                          return_value=WhatsAppSendResult(True, 200, "wamid.new-question-ack", {})):
            self.inbound("Wie lange dauert es?")
            self.inbound("Was kostet das?", "wamid.new-second-question")
        questions = open_customer_questions(self.ticket())
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[-1]["text"], "Was kostet das?")
        self.assertIsNone(questions[-1]["reply_to_message_id"])
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_workshop")

    def test_later_notification_does_not_reactivate_question_cancelled_by_resume(self):
        self.seed_ticket()
        add_ticket_note(self.ticket_id, "Haben Sie den Fahrzeugschein?", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_question", message_id="cancel-before-info")
        reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")
        add_ticket_note(self.ticket_id, "Die Werkstatt meldet sich am Nachmittag.", workshop_id=self.wid,
                        sender_role="workshop", purpose="workshop_notification", message_id="info-after-resume")
        self.assertIsNone(pending_workshop_question(self.ticket()))
        self.assertEqual(self.ticket()["conversation_state"], "workshop_active")

    def test_new_human_question_without_question_mark_remains_answerable(self):
        self.seed_ticket()
        add_ticket_note(self.ticket_id, "Wie lange dauert es?", workshop_id=self.wid,
                        sender_role="customer", purpose="customer_question", message_id="first-open-question")
        with patch.object(reliability.main, "send_whatsapp_text_message") as send:
            self.inbound("Was kostet das", "wamid.no-question-mark")
        send.assert_not_called()
        questions = open_customer_questions(self.ticket())
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[-1]["text"], "Was kostet das")
        self.assertIsNone(questions[-1]["reply_to_message_id"])


if __name__ == "__main__":
    unittest.main()
