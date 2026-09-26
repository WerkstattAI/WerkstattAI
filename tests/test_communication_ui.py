from __future__ import annotations

import gc
import os
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, select_autoescape


class FormFields(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.selects = {}
        self.current = None
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "select":
            self.current = {"attributes": attributes, "options": []}
            self.selects[attributes["name"]] = self.current
        elif tag == "option" and self.current is not None:
            self.current["options"].append(attributes)

    def handle_endtag(self, tag):
        if tag == "select":
            self.current = None


class CommunicationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_path = Path(__file__).resolve().parents[1] / "templates"
        cls.environment = Environment(loader=FileSystemLoader(template_path), autoescape=select_autoescape())
        cls.macros = cls.environment.get_template("_communication.html").module

    def question(self, message_id):
        return {"message_id": message_id, "text": "Wie lange dauert die Reparatur?", "created_at": "2026-09-26"}

    def test_single_open_question_has_explicit_stable_answer_target(self):
        fields = FormFields(str(self.macros.purpose_controls("ticket", [self.question("question-1")]))).selects
        target = fields["reply_to_message_id"]
        selected = [item["value"] for item in target["options"] if "selected" in item]
        self.assertEqual(selected, ["question-1"])
        self.assertIn("required", target["attributes"])
        self.assertNotIn("disabled", target["attributes"])

    def test_multiple_questions_require_a_deliberate_target(self):
        fields = FormFields(str(self.macros.purpose_controls("inbox", [self.question("one"), self.question("two")]))).selects
        target = fields["reply_to_message_id"]
        self.assertEqual([item["value"] for item in target["options"]], ["", "one", "two"])
        self.assertFalse(any("selected" in item for item in target["options"]))
        self.assertIn("required", target["attributes"])

    def test_no_open_question_cannot_be_sent_as_an_answer(self):
        fields = FormFields(str(self.macros.purpose_controls("ticket", []))).selects
        purposes = {item["value"]: item for item in fields["purpose"]["options"]}
        self.assertIn("disabled", purposes["workshop_answer"])
        self.assertIn("selected", purposes["workshop_notification"])
        self.assertIn("disabled", fields["reply_to_message_id"]["attributes"])

    def test_customer_question_markup_is_escaped_in_answer_picker(self):
        question = self.question('target" onclick="alert(1)')
        question["text"] = "</option><script>alert('customer input')</script>"
        markup = str(self.macros.purpose_controls("ticket", [question]))
        self.assertNotIn("<script>", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("&#34;", markup)

    def test_legacy_closed_question_does_not_appear_open_or_definitively_answered(self):
        markup = str(self.macros.message_heading({
            "sender_role": "customer", "purpose": "customer_question",
            "requires_human_action": True, "resolved_at": None,
            "legacy_closed": True, "legacy_semantics_uncertain": True,
        }))
        self.assertIn("Früher als erledigt markiert", markup)
        self.assertIn("Zweck nicht sicher erfasst", markup)
        self.assertNotIn("Offene Kundenfrage", markup)

    def test_all_message_roles_and_purposes_have_distinct_customer_facing_labels(self):
        headings = [str(self.macros.message_heading({"sender_role": role, "purpose": purpose}))
                    for role, purpose in [("customer", "customer_information"),
                                          ("assistant", "automatic_answer"),
                                          ("workshop", "workshop_question")]]
        self.assertIn("Kundeninformation", headings[0])
        self.assertIn("Assistent", headings[1])
        self.assertIn("Automatische Antwort", headings[1])
        self.assertIn("Werkstatt-Team", headings[2])
        self.assertIn("Frage an Kunden", headings[2])

    def test_customer_information_needing_workshop_action_is_not_labeled_an_open_question(self):
        markup = str(self.macros.message_heading({
            "sender_role": "customer", "purpose": "customer_information",
            "requires_human_action": True, "resolved_at": None,
        }))
        self.assertIn("Zur Bearbeitung", markup)
        self.assertIn("Kundeninformation", markup)
        self.assertNotIn("Offene Kundenfrage", markup)


class CommunicationPageTests(unittest.TestCase):
    def setUp(self):
        import test_conversation_flows as fixture
        from app.db import init_db, set_whatsapp_conversation_control
        from app.models import IntakeState
        from app.tickets import add_ticket_note, save_ticket
        from app.whatsapp import save_whatsapp_message

        self.directory = tempfile.TemporaryDirectory(prefix="werkstattai-communication-ui-")
        self.environment = patch.dict(os.environ, {
            "WERKSTATTAI_SQLITE_PATH": str(Path(self.directory.name) / "ui.db"),
        })
        self.environment.start()
        init_db()
        self.workshop = "demo-werkstatt"
        self.phone = "491701234567"
        self.ticket = save_ticket(IntakeState(name="UI Beispielkunde", telefon=self.phone), workshop_id=self.workshop)
        for number, text in enumerate(["Wie lange dauert die Reparatur?", "Was kostet die Reparatur?"]):
            message_id = f"customer-{number}"
            add_ticket_note(self.ticket, text, "customer_message", self.workshop,
                            purpose="customer_question", message_id=message_id)
            save_whatsapp_message(workshop_id=self.workshop, customer_phone=self.phone,
                                  direction="inbound", text=text, ticket_id=self.ticket, message_id=message_id)
        add_ticket_note(self.ticket, "Ihre Ticketnummer ist " + self.ticket, "customer_reply", self.workshop,
                        sender_role="assistant", purpose="automatic_answer")
        set_whatsapp_conversation_control(workshop_id=self.workshop, customer_phone=self.phone,
                                          mode="manual", active_ticket_id=self.ticket)
        self.request = fixture._dashboard_request(self.workshop)
        self.request.state.csp_nonce = "ui-test"

    def tearDown(self):
        gc.collect()
        self.environment.stop()
        self.directory.cleanup()

    def test_ticket_history_shows_assistant_and_customer_roles_with_answer_targets(self):
        from app.web import ticket_detail
        response = ticket_detail(self.request, self.ticket, workshop_id=self.workshop)
        self.assertEqual(response.status_code, 200)
        markup = response.body.decode()
        self.assertIn("Automatische Antwort", markup)
        self.assertIn("<strong>Assistent</strong>", markup)
        targets = FormFields(markup).selects["reply_to_message_id"]["options"]
        self.assertEqual([option["value"] for option in targets], ["", "customer-0", "customer-1"])

    def test_inbox_uses_the_active_tickets_open_questions(self):
        from app.web import dashboard_whatsapp
        response = dashboard_whatsapp(self.request, phone=self.phone, workshop_id=self.workshop)
        self.assertEqual(response.status_code, 200)
        markup = response.body.decode()
        targets = FormFields(markup).selects["reply_to_message_id"]["options"]
        self.assertEqual([option["value"] for option in targets], ["", "customer-0", "customer-1"])
        self.assertIn("Werkstatt übernimmt", markup)

    def test_dashboard_delivers_question_targets_to_contact_modal(self):
        from app.web import dashboard
        response = dashboard(self.request, workshop_id=self.workshop)
        self.assertEqual(response.status_code, 200)
        markup = response.body.decode()
        self.assertIn("data-open-questions=", markup)
        self.assertIn('"message_id": "customer-0"', markup)
        self.assertIn('name="purpose"', markup)


if __name__ == "__main__":
    unittest.main()
