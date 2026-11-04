"""Verträge der neuen Oberfläche mit den vorhandenen Kommunikationsabläufen."""
import re
import unittest
from html.parser import HTMLParser

import test_manual_communication_forms as formularfixture
from app.models import IntakeState
from app.oberflaeche import kilometeranzeige
from app.tickets import save_ticket, add_ticket_note
from app.whatsapp import save_whatsapp_message


class Elemente(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elemente = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elemente.append((tag, dict(attrs)))


class ArbeitsplatzTests(unittest.TestCase):
    setUp = formularfixture.ManualCommunicationFormTests.setUp
    tearDown = formularfixture.ManualCommunicationFormTests.tearDown

    def test_vorschau_und_ticket_behalten_formularziele_und_listenkontext(self):
        context = '/dashboard?workshop_id=' + self.wid + '&q=Test&source=web_chat&sort=priority&page=2&limit=20'
        from urllib.parse import quote
        response = self.client.get(f'/dashboard/ticket/{self.web_ticket}?workshop_id={self.wid}&return_to={quote(context,safe="")}')
        self.assertEqual(response.status_code, 200)
        parsed = Elemente(response.text)
        ids = [attrs['id'] for _, attrs in parsed.elemente if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({'communication-history','communication-controls','internal-notes','ticketCustomerReplyText','ticketIdText','phoneText'} <= set(ids))
        returns = [attrs['value'] for tag, attrs in parsed.elemente if tag == 'input' and attrs.get('name') == 'return_to']
        self.assertGreaterEqual(len(returns), 3)
        from urllib.parse import parse_qs, urlsplit
        for value in returns:
            query = parse_qs(urlsplit(value).query)
            self.assertEqual(urlsplit(value).path, '/dashboard')
            for key, expected in [('workshop_id',self.wid),('q','Test'),('source','web_chat'),('sort','priority'),('page','2'),('limit','20')]:
                self.assertEqual(query.get(key),[expected],value)
        purposes = [attrs for tag, attrs in parsed.elemente if tag == 'select' and attrs.get('name') == 'purpose']
        self.assertEqual(len(purposes), 1)
        self.assertIn('required', purposes[0])
        self.assertIn(f'/dashboard/ticket/{self.web_ticket}/notes', response.text)
        self.assertNotIn('/dashboard/admin/workshops', response.text)
        self.assertIn('data-ticket-tab="notizen-panel"', response.text)

    def test_verlauf_ist_chronologisch_und_interne_notizen_bleiben_getrennt(self):
        add_ticket_note(self.web_ticket,'Nur intern sichtbar',workshop_id=self.wid,message_id='pruefung-intern')
        response = self.client.get(f'/dashboard/ticket/{self.web_ticket}?workshop_id={self.wid}')
        text = response.text
        history = text.split('id="communication-history"',1)[1].split('id="communication-controls"',1)[0]
        ids = re.findall(r'id="communication-([^"]+)"',history)
        self.assertEqual(ids, [self.questions[self.web_ticket], 'closed-'+self.web_ticket, ids[-1]])
        self.assertNotIn('Nur intern sichtbar', history)
        self.assertIn('Nur intern sichtbar', text.split('id="internal-notes"',1)[1])
        self.assertIn('data-frage-beantworten="'+self.questions[self.web_ticket]+'"', history)
        self.assertNotIn('data-frage-beantworten="closed-', history)

    def test_liste_zeigt_echte_fahrzeugdaten_null_und_escaped_inhalte(self):
        tid = save_ticket(IntakeState(name='Test',fahrzeug='<script>fahrzeug</script>',kilometerstand='0',source='web_chat'),self.wid)
        response = self.client.get(f'/dashboard?workshop_id={self.wid}')
        self.assertEqual(response.status_code,200)
        self.assertIn('data-ticket-auswahl="ticket-'+tid+'"',response.text)
        self.assertIn('&lt;script&gt;fahrzeug&lt;/script&gt;',response.text)
        self.assertNotIn('<script>fahrzeug</script>',response.text)
        self.assertIn('0 km',response.text)
        self.assertIn('Unbekannt',response.text)
        self.assertIn('Nicht angegeben',response.text)
        self.assertIn('Antwort erforderlich',response.text)
        self.assertIn('name="question_state"',response.text)
        self.assertIn('name="task_state"',response.text)
        self.assertIn('data-context-action',response.text)

    def test_statische_bilder_sind_verfuegbar_ohne_private_dateien_freizugeben(self):
        self.client.headers.pop('cookie',None)
        for name in ['arbeitsplatz.css','InterVariable.woff2','fahrzeug-symbolbild.png','whatsapp.svg','symbole/gauge.svg']:
            response = self.client.get('/static/arbeitsplatz/'+name)
            self.assertEqual(response.status_code,200,name)
            self.assertIn("default-src 'self'",response.headers['content-security-policy'])
        for path in ['/static/arbeitsplatz/../../app/config.py','/static/app/config.py','/dashboard']:
            self.assertIn(self.client.get(path,follow_redirects=False).status_code,[303,404])

    def test_versandanzeige_nutzt_metastatus_ohne_webspeicherung_als_zustellung_zu_zeigen(self):
        for status, label in [('sent','An Meta übergeben'),('delivered','Zugestellt'),('read','Gelesen')]:
            mid = 'anzeige-'+status
            add_ticket_note(self.wa_ticket,label,workshop_id=self.wid,purpose='workshop_notification',message_id=mid,delivery_status='sent')
            save_whatsapp_message(workshop_id=self.wid,customer_phone=self.phone,direction='outbound',ticket_id=self.wa_ticket,text=label,message_id=mid,status=status)
        text = self.client.get(f'/dashboard/ticket/{self.wa_ticket}?workshop_id={self.wid}').text
        for mid, label in [('anzeige-sent','An Meta übergeben'),('anzeige-delivered','Zugestellt'),('anzeige-read','Gelesen')]:
            message = text.split('id="communication-'+mid+'"',1)[1].split('class="note-date"',1)[1].split('</div>',1)[0]
            self.assertIn(label,message)
        add_ticket_note(self.web_ticket,'Webantwort',workshop_id=self.wid,purpose='workshop_notification',delivery_status='sent')
        text = self.client.get(f'/dashboard/ticket/{self.web_ticket}?workshop_id={self.wid}').text
        self.assertIn('Im Webchat gespeichert',text)
        self.assertNotIn(' · An Meta übergeben',text)


class KilometeranzeigeTests(unittest.TestCase):
    def test_zahlen_und_bereits_beschriebene_angaben(self):
        for value, expected in [(None,'Nicht angegeben'),('','Nicht angegeben'),(0,'0 km'),('128400','128.400 km'),('128.400','128.400 km'),('128 400','128.400 km'),('128.400 km','128.400 km'),('ca. 90000 km','ca. 90000 km'),('unbekannt','unbekannt')]:
            with self.subTest(value=value): self.assertEqual(kilometeranzeige(value),expected)
