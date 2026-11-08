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

    def test_kartenvorschau_verknuepft_nachrichten_nur_mit_ihrem_ticket(self):
        from app.nachrichtenvorschau import letzte_whatsapp_nachrichten
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction='inbound',
                              ticket_id=self.wa_ticket, text='Letzter Kartentext', message_id='karten-neu')
        bilder = letzte_whatsapp_nachrichten(self.wid, [self.wa_ticket, self.web_ticket])
        self.assertEqual(bilder[self.wa_ticket]['text'],'Letzter Kartentext')
        self.assertNotIn(self.web_ticket, bilder)
        self.assertEqual(letzte_whatsapp_nachrichten('fremde-werkstatt', [self.wa_ticket]), {})
        add_ticket_note(self.web_ticket, '<b>Kundenantwort</b>', workshop_id=self.wid,
                        purpose='workshop_notification', message_id='karten-web')
        add_ticket_note(self.web_ticket, 'Interne Geheimnotiz', workshop_id=self.wid, message_id='karten-intern')
        page = self.client.get('/dashboard',params={'workshop_id':self.wid})
        self.assertEqual(page.status_code,200)
        self.assertIn('Letzter Kartentext',page.text)
        self.assertIn('&lt;b&gt;Kundenantwort&lt;/b&gt;',page.text)
        import re
        vorschauen = re.findall(r'<div class="karten-nachricht-text">(.*?)</div>',page.text)
        self.assertNotIn('Interne Geheimnotiz', ''.join(vorschauen))

    def test_neue_skripte_behalten_csp_nonce_und_nachrichtenstandard(self):
        for path in ['/dashboard', '/dashboard/whatsapp', f'/dashboard/ticket/{self.web_ticket}']:
            page = self.client.get(path,params={'workshop_id':self.wid,'phone':self.phone})
            elements = Elemente(page.text).elemente
            scripts = [a for tag,a in elements if tag == 'script' and a.get('src','').startswith('/static/arbeitsplatz/')]
            self.assertEqual(len(scripts),2)
            for script in scripts:
                self.assertTrue(script.get('nonce'))
                self.assertIn("'nonce-"+script['nonce']+"'",page.headers['content-security-policy'])
            purpose = next(a for tag,a in elements if a.get('data-standard'))
            self.assertEqual(purpose['data-standard'],'workshop_notification')

    def test_verwaltungsnavigation_und_bestehende_formulare(self):
        for route, action in [('/dashboard/intake','/dashboard/intake'),('/dashboard/settings','/dashboard/settings'),('/dashboard/billing',None),('/dashboard/whatsapp/verbinden',None)]:
            page = self.client.get(route,params={'workshop_id':self.wid})
            self.assertEqual(page.status_code,200)
            elements = Elemente(page.text).elemente
            self.assertNotIn('class="sidebar"',page.text)
            self.assertIn('verwaltung.css',page.text)
            if action:
                self.assertTrue(any(tag=='form' and a.get('action')==action and a.get('method')=='post' for tag,a in elements))
            self.assertNotIn('/dashboard/admin/workshops',page.text)

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
        for name in ['arbeitsplatz.css','grundlagen.css','anmeldung.css','kundenchat.css','whatsapp.css','InterVariable.woff2','fahrzeug-symbolbild.png','fahrzeuge/markenbilder-v1.png','whatsapp.svg','symbole/gauge.svg']:
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

    def test_whatsapp_navigation_formulare_und_fragebezug_bleiben_erreichbar(self):
        response = self.client.get('/dashboard/whatsapp',params={'workshop_id':self.wid,'phone':self.phone})
        self.assertEqual(response.status_code,200)
        self.assertIn('<span class="contact-name">WhatsApp Test</span>', response.text)
        elements = Elemente(response.text).elemente
        ids = [a['id'] for _,a in elements if 'id' in a]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue({'messageThread','replyText','inboxMessagePurpose','inboxMessageReplyTarget','testPhone','webhookUrl'} <= set(ids))
        navigation = [a['href'] for tag,a in elements if tag=='a' and a.get('aria-current')=='page']
        self.assertEqual(navigation,['/dashboard/whatsapp?workshop_id='+self.wid])
        actions = [a.get('action') for tag,a in elements if tag=='form']
        self.assertTrue({'/logout','/dashboard/whatsapp/control','/dashboard/whatsapp/reply','/dashboard/whatsapp/test'} <= set(actions))
        self.assertNotIn('/dashboard/admin/workshops',response.text)
        self.assertIn(self.questions[self.wa_ticket],response.text)
        self.assertIn('conversation-control-bar',response.text)
        self.assertIn('formaction="/dashboard/whatsapp/open-manual"',response.text)
        self.assertLess(response.text.index('id="messageThread"'),response.text.index('<details class="verbindungsdetails"'))
        # Die gemeinsame Navigation darf ihre bisherigen Seiten nicht verlieren.
        for path in ['/dashboard','/dashboard/archive']:
            page = self.client.get(path,params={'workshop_id':self.wid})
            current = [a['href'] for tag,a in Elemente(page.text).elemente if tag=='a' and a.get('aria-current')=='page']
            self.assertEqual(current,[path+'?workshop_id='+self.wid])

    def test_kundenchat_bleibt_oeffentlich_mit_sitzung_und_aufnahmefunktionen(self):
        self.client.headers.pop('cookie',None)
        response = self.client.get('/assistant',params={'workshop_id':self.wid})
        self.assertEqual(response.status_code,200)
        elements = Elemente(response.text).elemente
        ids = [a['id'] for _,a in elements if 'id' in a]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue({'chatForm','messageInput','messages','sendBtn','resetBtn','typing','doneBox','charCount','sessionIdBox','conversationStatus'} <= set(ids))
        field = next(a for tag,a in elements if a.get('id')=='messageInput')
        self.assertEqual(field['maxlength'],'4096')
        self.assertIn('required',field)
        self.assertIn('werkstattai_session_id:',response.text)
        self.assertIn('/chat/messages',response.text)
        self.assertIn('Kostenvoranschlag anfragen',response.text)
        self.assertIn('/datenschutz?workshop_id='+self.wid,response.text)
        self.assertLess(response.text.index('id="chatForm"'),response.text.index('<aside'))

    def test_anmeldung_behaelt_rueckkehrziel_und_barrierefreie_felder(self):
        self.client.headers.pop('cookie',None)
        target = '/dashboard/whatsapp?workshop_id='+self.wid
        response = self.client.get('/login',params={'next':target})
        self.assertEqual(response.status_code,200)
        elements = Elemente(response.text).elemente
        fields = {a['name']:a for tag,a in elements if tag=='input' and 'name' in a}
        self.assertEqual(fields['next']['value'],target)
        self.assertEqual(fields['email']['autocomplete'],'username')
        self.assertEqual(fields['password']['autocomplete'],'current-password')
        self.assertEqual(fields['password']['type'],'password')
        self.assertIn('required',fields['email'])
        self.assertIn('required',fields['password'])
        self.assertIn(('form',{'method':'post','action':'/login'}),elements)
        self.assertIn('/datenschutz/rechte',response.text)


class KilometeranzeigeTests(unittest.TestCase):
    def test_zahlen_und_bereits_beschriebene_angaben(self):
        for value, expected in [(None,'Nicht angegeben'),('','Nicht angegeben'),(0,'0 km'),('128400','128.400 km'),('128.400','128.400 km'),('128 400','128.400 km'),('128.400 km','128.400 km'),('ca. 90000 km','ca. 90000 km'),('unbekannt','unbekannt')]:
            with self.subTest(value=value): self.assertEqual(kilometeranzeige(value),expected)
