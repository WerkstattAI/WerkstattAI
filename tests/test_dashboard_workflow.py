import unittest
from contextlib import closing
from unittest.mock import patch

import test_manual_communication_forms as forms
from app.db import get_conn
from app.models import IntakeState
from app.tickets import add_ticket_note, save_ticket, update_ticket_status, find_ticket_by_id
from app.customer_handoff import receive_customer_message
import app.web as web


class DashboardWorkflowTests(unittest.TestCase):
    setUp = forms.ManualCommunicationFormTests.setUp
    tearDown = forms.ManualCommunicationFormTests.tearDown

    def make(self, **values):
        return save_ticket(IntakeState(fahrzeug='Testfahrzeug', source='web_chat', **values), self.wid)

    def page(self, **params):
        response = self.client.get('/dashboard', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_pending_information_and_completed_ticket_remain_tasks(self):
        tid = self.make()
        add_ticket_note(tid, 'Filter wechseln?', workshop_id=self.wid, purpose='workshop_question', message_id='filter-question')
        receive_customer_message(find_ticket_by_id(tid, self.wid), 'Danke', workshop_id=self.wid)
        self.assertNotIn(tid, [t['ticket_view_id'] for t in self.page().context['attention_tickets']])
        receive_customer_message(find_ticket_by_id(tid, self.wid), 'Ja, bitte wechseln.', workshop_id=self.wid, message_id='filter-answer')
        update_ticket_status(tid, 'erledigt', self.wid)
        attention = self.page().context['attention_tickets']
        self.assertIn(tid, [t['ticket_view_id'] for t in attention])
        item = next(t for t in attention if t['ticket_view_id'] == tid)
        self.assertEqual(item['attention_reason'], 'Kundenantwort prüfen')

    def test_answered_history_does_not_displace_emergency_and_preview_is_open(self):
        for i in range(6):
            tid = self.make()
            add_ticket_note(tid, 'Erledigte Frage?', workshop_id=self.wid, purpose='customer_question', message_id=f'old-{i}')
            add_ticket_note(tid, 'Beantwortet', workshop_id=self.wid, purpose='workshop_answer', reply_to_message_id=f'old-{i}')
        emergency = self.make(priority='hoch', request_type='notfall')
        response = self.page()
        self.assertEqual(response.context['attention_tickets'][0]['ticket_view_id'], emergency)
        item = next(t for t in response.context['tickets'] if t['ticket_view_id'] == self.web_ticket)
        self.assertEqual(item['latest_customer_question_text'], 'Was kostet die Reparatur?')

    def test_complete_scope_before_pagination_and_global_kpi_links(self):
        old = self.make(priority='hoch', request_type='notfall')
        with closing(get_conn()) as conn:
            conn.execute("UPDATE tickets SET created_at = '2020-01-01T00:00:00+00:00' WHERE workshop_id = ? AND ticket_id = ?", (self.wid, old))
            # Bounded synthetic inserts in one transaction, no production database.
            for i in range(510):
                conn.execute("INSERT INTO tickets (workshop_id, ticket_id, created_at, updated_at, status, fahrzeug, priority, notes_json) VALUES (?, ?, ?, ?, ?, ?, 'normal', '[]')",
                             (self.wid, f'TEST-BULK-{i}', '2026-10-11', '2026-10-11', 'archiviert' if i < 10 else 'erledigt', 'Bulk'))
            conn.commit()
        response = self.page(q=old, limit=20)
        self.assertEqual([t['ticket_view_id'] for t in response.context['tickets']], [old])
        self.assertEqual(response.context['stats']['all'], 503)
        self.assertLessEqual(len(self.page(limit=500).context['tickets']), 100)
        response = self.page(status='in_bearbeitung', source='direktannahme', q='missing')
        target = response.context['kpi_links']['kundenfragen_offen']
        result = self.client.get(target)
        self.assertEqual(result.context['total'], response.context['stats']['kundenfragen_offen'])

    def test_quick_status_preserves_validated_context_and_handles_failure(self):
        path = f'/dashboard/ticket/{self.web_ticket}/status_quick'
        context = '/dashboard?status=offen&source=web_chat&q=Test&sort=oldest&page=3&limit=20'
        response = self.client.post(path, data={'status':'in_bearbeitung','return_to':context}, follow_redirects=False)
        self.assertIn('page=3', response.headers['location'])
        self.assertIn('q=Test', response.headers['location'])
        self.assertIn('#ticket-', response.headers['location'])
        response = self.client.post(path, data={'status':'offen','return_to':'//evil.test'}, follow_redirects=False)
        self.assertTrue(response.headers['location'].startswith('/dashboard?'))
        with patch.object(web, 'update_ticket_status', side_effect=RuntimeError('simulated storage failure')):
            response = self.client.post(path, data={'status':'erledigt'}, headers={'Accept':'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['ok'], False)
        self.assertEqual(find_ticket_by_id(self.web_ticket, self.wid)['status'], 'offen')

    def test_webchat_action_and_delivery_information_match_channel(self):
        row = next(t for t in self.page().context['tickets'] if t['ticket_view_id'] == self.web_ticket)
        self.assertIn('Im Webchat antworten', self.page().text)
        detail = self.client.get(f'/dashboard/ticket/{self.web_ticket}')
        self.assertIn('automatisch', detail.text)
        self.assertNotIn('Startvorlage senden', detail.text)

    def test_events_are_bounded_scoped_and_do_not_resolve_work(self):
        first = self.client.get('/dashboard/events')
        self.assertEqual(first.status_code, 200)
        cursor = first.json()['cursor']
        add_ticket_note(self.web_ticket, 'Neue Testfrage?', workshop_id=self.wid, purpose='customer_question', message_id='new-dashboard-event')
        before = find_ticket_by_id(self.web_ticket, self.wid)
        result = self.client.get('/dashboard/events', params={'after':cursor}).json()
        self.assertEqual(len(result['events']), 1)
        self.assertIn('#communication-new-dashboard-event', result['events'][0]['url'])
        again = self.client.get('/dashboard/events', params={'after':result['cursor']}).json()
        self.assertEqual(again['events'], [])
        self.assertEqual(find_ticket_by_id(self.web_ticket, self.wid), before)

    def test_whatsapp_control_keeps_validated_list_context(self):
        from urllib.parse import urlsplit, parse_qs
        from app.db import get_whatsapp_conversation_control
        response = self.client.post('/dashboard/whatsapp/control', data={
            'customer_phone':self.phone, 'ticket_id':self.wa_ticket, 'mode':'assistant',
            'context':'ticket', 'return_to':'/dashboard?source=whatsapp&page=2&q=Test'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        target = urlsplit(response.headers['location'])
        self.assertEqual(target.fragment, 'communication-controls')
        self.assertIn('page=2', parse_qs(target.query)['return_to'][0])
        self.assertEqual(get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)['mode'], 'assistant')

    def test_privacy_deletion_includes_only_selected_ticket_events(self):
        from app.privacy_data import preview, fingerprint, delete_data
        selection = {'kind':'ticket', 'value':self.web_ticket}
        records = preview(self.wid, selection)
        self.assertGreaterEqual(len(records['dashboard_events']), 2)
        result = delete_data(workshop_id=self.wid, email='local@example.invalid',
                             selection=selection, expected_digest=fingerprint(records))
        self.assertEqual(result['dashboard_events'], len(records['dashboard_events']))
        with closing(get_conn()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM dashboard_events WHERE workshop_id=? AND ticket_id=?',
                             (self.wid,self.web_ticket)).fetchone()['n'], 0)
            self.assertGreater(conn.execute('SELECT COUNT(*) AS n FROM dashboard_events WHERE workshop_id=? AND ticket_id=?',
                               (self.wid,self.wa_ticket)).fetchone()['n'], 0)

    def test_only_targeted_task_disappears_and_counts_name_tickets(self):
        add_ticket_note(self.web_ticket, 'Ich bringe den Schlüssel mit.', workshop_id=self.wid,
                        purpose='customer_information', requires_human_action=True, message_id='review-key')
        add_ticket_note(self.web_ticket, 'Zweite offene Frage?', workshop_id=self.wid,
                        purpose='customer_question', message_id='second-open')
        before = self.page().context
        self.assertEqual(before['stats']['kundenfragen_offen'], 2)
        self.client.post(f'/dashboard/ticket/{self.web_ticket}/notes', data={
            'note_type':'customer_reply','note_text':'Testantwort','purpose':'workshop_answer',
            'reply_to_message_id':self.questions[self.web_ticket],'message_id':'targeted-answer'})
        item = next(t for t in self.page().context['tickets'] if t['ticket_view_id'] == self.web_ticket)
        self.assertEqual({n['message_id'] for n in item['open_tasks']}, {'review-key','second-open'})
        self.client.post(f'/dashboard/ticket/{self.web_ticket}/information-resolve', data={'message_id':'review-key'})
        item = next(t for t in self.page().context['tickets'] if t['ticket_view_id'] == self.web_ticket)
        self.assertEqual([n['message_id'] for n in item['open_tasks']], ['second-open'])
        self.assertEqual(item['status'], 'offen')

    def test_event_pagination_replay_and_owner_scope(self):
        from app.auth import create_session_token, SESSION_COOKIE
        from app.security import hash_password
        with closing(get_conn()) as conn:
            conn.execute("INSERT INTO users(email,password_hash,workshop_id,role) VALUES(?,?,?,'owner')",
                         ('dashboard-owner@example.invalid',hash_password('OnlyLocalDashboard!'),self.wid))
            conn.commit()
        self.client.headers['cookie'] = SESSION_COOKIE + '=' + create_session_token({
            'email':'dashboard-owner@example.invalid','workshop_id':self.wid,'role':'owner'})
        foreign = save_ticket(IntakeState(fahrzeug='PRIVATE FOREIGN',source='web_chat'), 'foreign-dashboard')
        cursor = self.client.get('/dashboard/events').json()['cursor']
        for i in range(53):
            add_ticket_note(self.web_ticket, f'Neue Frage {i}?', workshop_id=self.wid,
                            purpose='customer_question',message_id=f'event-{i}')
        # Same message ID never creates another event.
        add_ticket_note(self.web_ticket, 'Neue Frage 0?', workshop_id=self.wid,
                        purpose='customer_question',message_id='event-0')
        result = self.client.get('/dashboard/events',params={'after':cursor,'workshop_id':'foreign-dashboard'}).json()
        self.assertEqual(len(result['events']),50)
        self.assertTrue(result['more'])
        remainder = self.client.get('/dashboard/events',params={'after':result['cursor']}).json()
        self.assertEqual(len(remainder['events']),3)
        self.assertFalse(remainder['more'])
        self.assertTrue(all(e['ticket_id']==self.web_ticket for e in result['events']+remainder['events']))
        page=self.page(workshop_id='foreign-dashboard')
        self.assertNotIn('PRIVATE FOREIGN',page.text)
        response=self.client.post(f'/dashboard/ticket/{foreign}/status_quick',data={'status':'erledigt','workshop_id':'foreign-dashboard'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(find_ticket_by_id(foreign,'foreign-dashboard')['status'],'offen')
