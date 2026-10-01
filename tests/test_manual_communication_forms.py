from __future__ import annotations

import unittest
import uuid
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

import test_conversation_flows as fixture
import test_whatsapp_reliability as reliability
import app.web as web
from app.communication import open_customer_questions, validate_workshop_message
from app.models import IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket
from app.whatsapp import WhatsAppSendResult, list_whatsapp_messages, save_whatsapp_message


class ManualCommunicationFormTests(unittest.TestCase):
    def setUp(self):
        reliability.WhatsAppReliabilityTests.setUp(self)
        self.stack.enter_context(patch.object(web, "settings", replace(web.settings, whatsapp_access_token="mock-token")))
        self.web_ticket = save_ticket(IntakeState(name="Web Test", source="web_chat"), self.wid)
        self.wa_ticket = save_ticket(IntakeState(name="WhatsApp Test", source="whatsapp", telefon=self.phone),
                                     self.wid, verified_customer_phone=self.phone)
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound",
                              ticket_id=self.wa_ticket, text="Synthetischer Eingang")
        reliability.db.set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone,
                                                          active_ticket_id=self.wa_ticket, mode="manual")
        self.questions = {}
        for tid in (self.web_ticket, self.wa_ticket):
            self.questions[tid] = "price-" + tid
            add_ticket_note(tid, "Was kostet die Reparatur?", workshop_id=self.wid,
                            purpose="customer_question", message_id=self.questions[tid])
            add_ticket_note(tid, "Alte Frage?", workshop_id=self.wid,
                            purpose="customer_question", message_id="closed-" + tid)
            add_ticket_note(tid, "Alte Antwort", workshop_id=self.wid,
                            purpose="workshop_answer", reply_to_message_id="closed-" + tid)
        self.client = TestClient(reliability.main.app)
        self.client.headers["cookie"] = fixture._dashboard_request(self.wid).headers["cookie"]

    def tearDown(self):
        self.client.close()
        reliability.WhatsAppReliabilityTests.tearDown(self)

    def forms(self):
        return [
            (self.web_ticket, f"/dashboard/ticket/{self.web_ticket}/notes",
             {"note_type": "customer_reply", "note_text": "Ihr Fahrzeug ist angekommen."}),
            (self.wa_ticket, f"/dashboard/ticket/{self.wa_ticket}/notes",
             {"note_type": "customer_reply", "note_text": "Ihr Fahrzeug ist angekommen."}),
            (self.wa_ticket, "/dashboard/whatsapp/reply",
             {"customer_phone": self.phone, "ticket_id": self.wa_ticket, "reply_text": "Ihr Fahrzeug ist angekommen."}),
            (self.wa_ticket, f"/dashboard/ticket/{self.wa_ticket}/customer-message",
             {"message_text": "Ihr Fahrzeug ist angekommen."}),
        ]

    def test_invalid_posts_do_not_store_or_send_messages(self):
        for tid, path, data in self.forms():
            other = self.wa_ticket if tid == self.web_ticket else self.web_ticket
            cases = [
                {}, {"purpose": ""}, {"purpose": "invalid"}, {"purpose": "workshop_answer"},
                {"purpose": "workshop_answer", "reply_to_message_id": "missing"},
                {"purpose": "workshop_answer", "reply_to_message_id": self.questions[other]},
                {"purpose": "workshop_answer", "reply_to_message_id": "closed-" + tid},
                {"purpose": "workshop_notification", "reply_to_message_id": self.questions[tid]},
                {"purpose": "workshop_question", "reply_to_message_id": self.questions[tid]},
            ]
            for selection in cases:
                with self.subTest(path=path, selection=selection):
                    before = find_ticket_by_id(tid, self.wid)
                    messages = list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone)
                    with patch.object(web, "send_whatsapp_text_message") as send:
                        response = self.client.post(path, data={**data, **selection}, follow_redirects=False)
                        send.assert_not_called()
                    if response.status_code == 303:
                        self.assertIn("status=failed", response.headers["location"])
                    else:
                        self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(find_ticket_by_id(tid, self.wid), before)
                    self.assertEqual(list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone), messages)

    def test_explicit_information_question_and_answer_keep_targeted_semantics(self):
        for index, (tid, path, data) in enumerate(self.forms()):
            with self.subTest(path=path):
                target = f"target-{index}"
                add_ticket_note(tid, "Weitere Frage?", workshop_id=self.wid,
                                purpose="customer_question", message_id=target)
                before = [q["message_id"] for q in open_customer_questions(find_ticket_by_id(tid, self.wid))]
                with patch.object(web, "send_whatsapp_text_message", side_effect=lambda **kwargs:
                                  WhatsAppSendResult(True, 200, "wamid." + uuid.uuid4().hex, {})) as send:
                    for purpose in ("workshop_notification", "workshop_question"):
                        response = self.client.post(path, data={**data, "purpose": purpose}, follow_redirects=False)
                        self.assertEqual(response.status_code, 303)
                        self.assertNotIn("failed", response.headers["location"])
                        self.assertEqual([q["message_id"] for q in open_customer_questions(find_ticket_by_id(tid, self.wid))], before)
                    response = self.client.post(path, data={**data, "purpose": "workshop_answer",
                                                            "reply_to_message_id": target}, follow_redirects=False)
                    self.assertEqual(response.status_code, 303)
                    self.assertNotIn("failed", response.headers["location"])
                    self.assertEqual(send.call_count, 0 if tid == self.web_ticket else 3)
                ticket = find_ticket_by_id(tid, self.wid)
                self.assertEqual([q["message_id"] for q in open_customer_questions(ticket)], [q for q in before if q != target])
                self.assertEqual(ticket["status"], "offen")

    def test_internal_single_target_inference_remains_available(self):
        ticket = find_ticket_by_id(self.web_ticket, self.wid)
        self.assertEqual(validate_workshop_message(ticket, "workshop_answer"), self.questions[self.web_ticket])
        with self.assertRaises(ValueError):
            validate_workshop_message(ticket, "workshop_answer", require_explicit_target=True)

    def test_unassigned_inbox_also_requires_valid_explicit_purpose(self):
        phone = "4915700099999"
        save_whatsapp_message(workshop_id=self.wid, customer_phone=phone, direction="inbound", text="Test")
        before = list_whatsapp_messages(workshop_id=self.wid, customer_phone=phone)
        for selection in ({}, {"purpose": "invalid"}, {"purpose": "workshop_answer"},
                          {"purpose": "workshop_notification", "reply_to_message_id": self.questions[self.wa_ticket]}):
            with self.subTest(selection=selection), patch.object(web, "send_whatsapp_text_message") as send:
                response = self.client.post("/dashboard/whatsapp/reply", data={
                    "customer_phone": phone, "reply_text": "Information", **selection,
                }, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertIn("reply_status=failed", response.headers["location"])
                send.assert_not_called()
                self.assertEqual(list_whatsapp_messages(workshop_id=self.wid, customer_phone=phone), before)
