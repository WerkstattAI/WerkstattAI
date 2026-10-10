import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

import test_communication_routing as routing
import test_manual_communication_forms as forms
import test_web_session_security as sessions
import test_customer_handoff as handoff
from app.communication import open_customer_questions, pending_workshop_question
from app.tickets import add_ticket_note, find_ticket_by_id, set_ticket_conversation_state
from app.tickets import save_ticket
from app.models import IntakeState
from app.whatsapp import WhatsAppSendResult, list_whatsapp_messages


class NaturalStatusTests(unittest.TestCase):
    setUp = routing.CommunicationRoutingTests.setUp
    handle = routing.CommunicationRoutingTests.handle

    def test_natural_status_references_are_saved_facts(self):
        for text in ('Wie ist der Status meines Tickets?', 'Wie ist der aktuelle Status meines Auftrags?',
                     'Was ist der Status des Tickets?', 'Status meines Tickets',
                     'Hallo, wie lautet der Status meines Tickets bitte?'):
            with self.subTest(text=text):
                self.add.reset_mock()
                _, reply, done = self.handle(text)
                self.assertIn('offen', reply)
                self.assertFalse(done)
                self.assertFalse(self.add.call_args_list[0].kwargs['requires_human_action'])

    def test_status_plus_decision_still_needs_workshop(self):
        for text in ('Wie ist der Status meines Tickets und wann kann ich es abholen?',
                     'Wie ist der Status der Reparatur?', 'Status meines Tickets und was kostet es?'):
            with self.subTest(text=text):
                self.add.reset_mock()
                _, reply, _ = self.handle(text)
                self.assertIn('weitergegeben', reply)
                self.assertTrue(self.add.call_args_list[0].kwargs['requires_human_action'])


class SuccessfulFormReplayTests(unittest.TestCase):
    setUp = forms.ManualCommunicationFormTests.setUp
    tearDown = forms.ManualCommunicationFormTests.tearDown
    forms = forms.ManualCommunicationFormTests.forms

    def test_staff_can_mark_only_customer_information_reviewed(self):
        tid = self.web_ticket
        add_ticket_note(tid, 'Ich bringe den Fahrzeugschein mit.', workshop_id=self.wid,
                        purpose='customer_information', requires_human_action=True, message_id='information-to-review')
        add_ticket_note(tid, 'Dürfen wir reparieren?', workshop_id=self.wid,
                        purpose='workshop_question', message_id='still-awaiting-answer')
        before = find_ticket_by_id(tid, self.wid)
        route = f'/dashboard/ticket/{tid}/information-resolve'
        with TestClient(forms.reliability.main.app) as anonymous:
            response = anonymous.post(route, data={'message_id': 'information-to-review'}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.headers['location'].startswith('/login'))
        self.assertEqual(find_ticket_by_id(tid, self.wid), before)
        foreign = save_ticket(IntakeState(source='web_chat'), workshop_id='foreign-information-workshop')
        add_ticket_note(foreign, 'Private Information', workshop_id='foreign-information-workshop',
                        purpose='customer_information', requires_human_action=True, message_id='foreign-information')
        response = self.client.post(f'/dashboard/ticket/{foreign}/information-resolve', data={
            'message_id': 'foreign-information', 'workshop_id': 'foreign-information-workshop'}, follow_redirects=False)
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(find_ticket_by_id(foreign, 'foreign-information-workshop')['notes'][-1]['resolved_at'])
        for mid in ('missing-information', self.questions[tid], 'still-awaiting-answer'):
            response = self.client.post(route, data={'message_id': mid}, follow_redirects=False)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(find_ticket_by_id(tid, self.wid), before)
        page = self.client.get(f'/dashboard/ticket/{tid}')
        self.assertTrue('Als bearbeitet markieren' in page.text)
        for _ in range(2):
            self.assertEqual(self.client.post(route, data={'message_id': 'information-to-review'},
                                             follow_redirects=False).status_code, 303)
        ticket = find_ticket_by_id(tid, self.wid)
        note = next(n for n in ticket['notes'] if n['message_id'] == 'information-to-review')
        self.assertTrue(note['resolved_at'])
        self.assertTrue(note['resolved_by'])
        self.assertEqual(ticket['status'], before['status'])
        self.assertEqual(ticket['conversation_state'], before['conversation_state'])
        self.assertEqual(open_customer_questions(ticket), open_customer_questions(before))
        self.assertEqual(pending_workshop_question(ticket), pending_workshop_question(before))
        self.assertTrue('Bearbeitet' in self.client.get(f'/dashboard/ticket/{tid}').text)
        self.assertFalse('Als bearbeitet markieren' in self.client.get(f'/dashboard/ticket/{tid}').text)

    def test_same_successful_whatsapp_form_replays_success_without_sending(self):
        for index, (tid, path, data) in enumerate(self.forms()[1:]):
            with self.subTest(path=path):
                target = f'replay-question-{index}'
                add_ticket_note(tid, 'Was kostet es?', workshop_id=self.wid,
                                purpose='customer_question', message_id=target)
                payload = {**data, 'purpose': 'workshop_answer', 'reply_to_message_id': target,
                           'message_id': f'replay-attempt-{index}'}
                with patch.object(forms.web, 'send_whatsapp_text_message',
                                  return_value=WhatsAppSendResult(True, 200, f'wamid.replay{index}', {})) as send:
                    first = self.client.post(path, data=payload, follow_redirects=False)
                    self.assertEqual(first.status_code, 303)
                    self.assertNotIn('status=failed', first.headers['location'])
                    before = find_ticket_by_id(tid, self.wid)
                    outbound = list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone)
                    with patch.object(forms.web, '_free_text_window_error', return_value='Fenster geschlossen'), \
                         patch('app.manual_dispatch.whatsapp_customer_service_window_for_phone',
                               return_value={'service_window_open': False}):
                        again = self.client.post(path, data=payload, follow_redirects=False)
                    self.assertNotIn('status=failed', again.headers['location'])
                    self.assertEqual(send.call_count, 1)
                    self.assertEqual(find_ticket_by_id(tid, self.wid), before)
                    self.assertEqual(list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone), outbound)
                    for change in ({'purpose': 'workshop_notification', 'reply_to_message_id': ''},
                                   {next(key for key in data if key.endswith('text')): 'Andere Nachricht'},
                                   {'reply_to_message_id': ''}, {'reply_to_message_id': 'different-target'}):
                        changed = self.client.post(path, data={**payload, **change}, follow_redirects=False)
                        self.assertIn('status=failed', changed.headers['location'])
                        self.assertEqual(send.call_count, 1)
                        self.assertEqual(find_ticket_by_id(tid, self.wid), before)


class WorkshopMessagePollingTests(unittest.TestCase):
    setUp = sessions.WebSessionSecurityTests.setUp
    tearDown = sessions.WebSessionSecurityTests.tearDown
    send = sessions.WebSessionSecurityTests.send
    make_ticket = sessions.WebSessionSecurityTests.make_ticket

    def poll(self, client, **changes):
        return client.get('/chat/messages', params={'workshop_id': self.workshop,
                                                   'session_id': 'shared-public-id', **changes})

    def test_idle_chat_receives_only_its_visible_messages_without_writes(self):
        tid = self.make_ticket(self.first)
        for purpose, mid, delivery in [('internal_note', 'private', None),
                                       ('workshop_notification', 'failed-message', 'failed'),
                                       ('workshop_notification', 'pending-message', 'pending'),
                                       ('workshop_question', 'visible-question', None)]:
            add_ticket_note(tid, mid, workshop_id=self.workshop, purpose=purpose,
                            message_id=mid, delivery_status=delivery)
        before = find_ticket_by_id(tid, self.workshop)
        for _ in range(3):
            response = self.poll(self.first)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()['data']
            self.assertEqual(data['ticket_id'], tid)
            self.assertEqual(data['conversation_state'], 'waiting_for_customer')
            self.assertEqual([m['message_id'] for m in data['workshop_messages']], ['visible-question'])
            self.assertEqual(set(data), {'ticket_id', 'conversation_state', 'workshop_messages'})
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(find_ticket_by_id(tid, self.workshop), before)
        for client, changes in [(self.second, {}), (self.first, {'session_id': 'other-session'}),
                                (self.first, {'workshop_id': 'different-workshop'})]:
            response = self.poll(client, **changes)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()['data']['ticket_id'])
            self.assertEqual(response.json()['data']['workshop_messages'], [])

    def test_poll_rejects_invalid_session_and_ticket_lookup_parameters(self):
        self.assertEqual(self.poll(self.first, session_id='').status_code, 422)
        self.assertEqual(self.poll(self.first, session_id='   ').status_code, 422)
        self.assertEqual(self.poll(self.first, session_id='x' * 129).status_code, 422)
        response = self.poll(self.first, ticket_id='foreign-ticket')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['data']['ticket_id'])


class CustomerReceiptScenarios:
    seed_ticket = handoff.CustomerHandoffScenarios.seed_ticket
    ticket = handoff.CustomerHandoffScenarios.ticket
    payload = handoff.CustomerHandoffScenarios.payload
    request = handoff.CustomerHandoffScenarios.request
    webhook = handoff.CustomerHandoffScenarios.webhook
    inbound = handoff.CustomerHandoffScenarios.inbound
    setUp = handoff.CustomerHandoffScenarios.setUp
    tearDown = handoff.CustomerHandoffScenarios.tearDown
    note = handoff.CustomerHandoffScenarios.note
    receive = handoff.CustomerHandoffScenarios.receive

    def test_thanks_does_not_answer_question_or_create_human_task(self):
        self.note('Dürfen wir die Reifen wechseln?', 'workshop_question', 'permission-question')
        for index, text in enumerate(('Danke', 'Vielen Dank!', 'Danke für die Info')):
            note = self.receive(text, f'receipt-{index}')
            self.assertFalse(note['requires_human_action'])
            self.assertIsNone(note['reply_to_message_id'])
            self.assertEqual(pending_workshop_question(self.ticket())['message_id'], 'permission-question')
            self.assertEqual(self.ticket()['conversation_state'], 'waiting_for_customer')
            self.assertEqual(open_customer_questions(self.ticket()), [])
        answer = self.receive('Ja, bitte wechseln.', 'actual-answer')
        self.assertEqual(answer['reply_to_message_id'], 'permission-question')
        self.assertTrue(answer['requires_human_action'])
        self.assertIsNone(pending_workshop_question(self.ticket()))


class WebCustomerReceiptTests(CustomerReceiptScenarios, unittest.TestCase):
    channel = 'web_chat'


class WhatsAppCustomerReceiptTests(CustomerReceiptScenarios, unittest.TestCase):
    channel = 'whatsapp'
