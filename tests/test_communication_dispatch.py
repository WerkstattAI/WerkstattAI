from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import test_conversation_flows  # establish the isolated configuration before fixtures
import test_whatsapp_reliability as fixtures
from app.communication import open_customer_questions
from app.db import get_whatsapp_conversation_control, set_whatsapp_conversation_control
from app.manual_dispatch import send_workshop_message
from app.models import IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket, set_ticket_conversation_state
from app.whatsapp import WhatsAppSendResult, list_whatsapp_messages, save_whatsapp_message


class CommunicationDispatchTests(unittest.TestCase):
    setUp = fixtures.WhatsAppReliabilityTests.setUp
    tearDown = fixtures.WhatsAppReliabilityTests.tearDown
    payload = fixtures.WhatsAppReliabilityTests.payload
    request = fixtures.WhatsAppReliabilityTests.request
    webhook = fixtures.WhatsAppReliabilityTests.webhook

    def ticket(self):
        tid = save_ticket(IntakeState(telefon=self.phone, name="Testkunde"), workshop_id=self.wid,
                          verified_customer_phone=self.phone)
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound")
        set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone,
                                          mode="assistant", active_ticket_id=tid)
        return tid

    def question(self, tid, mid="customer-question-one"):
        add_ticket_note(tid, "Wie lange dauert die Reparatur?", workshop_id=self.wid,
                        sender_role="customer", purpose="customer_question", message_id=mid)

    def send(self, tid, *, purpose="workshop_notification", target=None, mid="manual-message-001", sender=None):
        return send_workshop_message(workshop_id=self.wid, customer_phone=self.phone,
            phone_number_id="reliability-sender", ticket_id=tid, text="Nachricht der Werkstatt", purpose=purpose,
            reply_to_message_id=target, message_id=mid, source="test",
            send=sender or (lambda: WhatsAppSendResult(True, 200, "wamid.manual." + mid, {})))

    def test_answer_resolves_only_selected_question_and_keeps_ticket_status(self):
        tid = self.ticket()
        self.question(tid, "customer-question-one")
        self.question(tid, "customer-question-two")
        self.assertTrue(self.send(tid, purpose="workshop_answer", target="customer-question-one").ok)
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(ticket["status"], "offen")
        self.assertEqual([n["message_id"] for n in open_customer_questions(ticket)], ["customer-question-two"])
        self.assertIsNotNone(next(n for n in ticket["notes"] if n["message_id"] == "customer-question-one")["resolved_at"])

    def test_reply_during_send_is_linked_and_finalization_does_not_reopen_wait(self):
        tid = self.ticket()

        def sender():
            control = get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)
            self.assertEqual(control["conversation_state"], "waiting_for_customer")
            self.assertEqual(control["mode"], "manual")
            with patch("app.main.process_chat_message") as intake, patch("app.main.send_whatsapp_text_message") as bot:
                self.webhook(self.payload("wamid.customer-reply-during-send"))
            intake.assert_not_called()
            bot.assert_not_called()
            return WhatsAppSendResult(True, 200, "wamid.manual.question", {})

        self.send(tid, purpose="workshop_question", sender=sender)
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(ticket["conversation_state"], "workshop_active")
        reply = next(n for n in ticket["notes"] if n["sender_role"] == "customer")
        self.assertEqual(reply["purpose"], "customer_information")
        self.assertEqual(reply["reply_to_message_id"], "manual-message-001")

    def test_notification_preserves_open_question_and_status(self):
        tid = self.ticket()
        self.question(tid)
        self.send(tid)
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(ticket["status"], "offen")
        self.assertEqual(len(open_customer_questions(ticket)), 1)
        self.assertTrue(ticket["customer_question_open"])

    def test_definitive_rejection_restores_previous_state_and_does_not_resolve_question(self):
        tid = self.ticket()
        self.question(tid)
        set_ticket_conversation_state(tid, "assistant_active", self.wid)
        self.send(tid, purpose="workshop_answer", target="customer-question-one",
                  sender=lambda: WhatsAppSendResult(False, 400, None, {}, "rejected"))
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(ticket["conversation_state"], "assistant_active")
        self.assertEqual(len(open_customer_questions(ticket)), 1)
        self.assertEqual(ticket["notes"][-1]["delivery_status"], "failed")

    def test_failure_does_not_undo_newer_employee_action(self):
        tid = self.ticket()

        def sender():
            set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="manual")
            return WhatsAppSendResult(False, 400, None, {}, "rejected")

        self.send(tid, sender=sender)
        self.assertEqual(find_ticket_by_id(tid, self.wid)["conversation_state"], "workshop_active")

    def test_unknown_result_reuses_message_id_without_duplicate_send_or_resolution(self):
        tid = self.ticket()
        self.question(tid)
        sender = Mock(return_value=WhatsAppSendResult(False, None, None, {}, "timeout"))
        for _ in range(2):
            self.send(tid, purpose="workshop_answer", target="customer-question-one", sender=sender)
        sender.assert_called_once()
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(len(open_customer_questions(ticket)), 1)
        self.assertEqual(len([n for n in ticket["notes"] if n["sender_role"] == "workshop"]), 1)
        self.assertEqual(len([m for m in list_whatsapp_messages(workshop_id=self.wid) if m["direction"] == "outbound"]), 1)

    def test_answer_target_from_other_ticket_is_rejected_before_send(self):
        tid = self.ticket()
        other = save_ticket(IntakeState(telefon=self.phone), workshop_id=self.wid)
        self.question(other)
        sender = Mock()
        with self.assertRaises(ValueError):
            self.send(tid, purpose="workshop_answer", target="customer-question-one", sender=sender)
        sender.assert_not_called()

    def test_whatsapp_conversation_without_ticket_can_receive_reply_to_workshop_question(self):
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound")
        self.send(None, purpose="workshop_question")
        with patch("app.main.process_chat_message") as intake:
            self.webhook(self.payload("wamid.reply-before-ticket"))
        intake.assert_not_called()
        control = get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)
        self.assertEqual(control["conversation_state"], "workshop_active")
        reply = list_whatsapp_messages(workshop_id=self.wid)[-1]
        self.assertEqual(reply["reply_to_message_id"], "manual-message-001")

    def test_followup_question_without_question_mark_is_still_an_open_question(self):
        from app.customer_handoff import receive_customer_message
        tid = self.ticket()
        self.question(tid)
        ticket = receive_customer_message(find_ticket_by_id(tid, self.wid), "Was kostet das", workshop_id=self.wid)
        self.assertEqual(len(open_customer_questions(ticket)), 2)

    def test_late_delivery_confirmation_resolves_an_uncertain_answer(self):
        from app.whatsapp import update_whatsapp_message_status
        tid = self.ticket()
        self.question(tid)
        self.send(tid, purpose="workshop_answer", target="customer-question-one",
                  sender=lambda: WhatsAppSendResult(False, None, "wamid.uncertain", {}, "uncertain"))
        self.assertEqual(len(open_customer_questions(find_ticket_by_id(tid, self.wid))), 1)
        update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.uncertain", status="delivered")
        self.assertFalse(open_customer_questions(find_ticket_by_id(tid, self.wid)))

    def test_ticket_form_persists_selected_purpose_and_explicit_resume(self):
        from fastapi.testclient import TestClient
        from test_conversation_flows import _dashboard_request
        from app.main import app
        from app.communication import pending_workshop_question
        tid = self.ticket()
        with TestClient(app) as client:
            client.headers["cookie"] = _dashboard_request(self.wid).headers["cookie"]
            response = client.post(f"/dashboard/ticket/{tid}/notes", data={"note_text": "Welcher Termin passt?",
                "note_type": "customer_reply", "purpose": "workshop_question", "message_id": "http-question-001"},
                follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            self.assertEqual(find_ticket_by_id(tid, self.wid)["conversation_state"], "waiting_for_customer")
            response = client.post(f"/dashboard/ticket/{tid}/conversation-control", data={"state": "assistant_active"},
                                   follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
        ticket = find_ticket_by_id(tid, self.wid)
        self.assertEqual(ticket["conversation_state"], "assistant_active")
        self.assertIsNone(pending_workshop_question(ticket))

    def test_unconfirmed_workshop_send_is_not_shown_to_customer_as_a_message(self):
        from app.conversation_sessions import save_session_state
        from app.main import process_chat_message
        tid = self.ticket()
        state = IntakeState(ticket_id=tid, workshop_id=self.wid, step="fertig")
        save_session_state("web-manual", state, workshop_id=self.wid, channel="web_chat")
        self.send(tid, sender=lambda: WhatsAppSendResult(False, None, None, {}, "timeout"))
        response = process_chat_message(workshop_id=self.wid, session_id="web-manual", message=None, channel="web_chat")
        self.assertEqual(response.data["workshop_messages"], [])
        self.assertEqual(response.reply, "")


if __name__ == "__main__":
    unittest.main()
