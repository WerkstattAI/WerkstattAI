"""Bilder, Werkstattgrenzen und der begrenzte, authentifizierte Meta-Abruf."""
import io
import json
import unittest
from email.message import Message
from unittest.mock import Mock, patch

import test_manual_communication_forms as formulare
from app.db import get_conn, get_whatsapp_conversation_control, set_whatsapp_conversation_control
from app.tickets import add_ticket_note, find_ticket_by_id
from app.whatsapp import WhatsAppInboundMessage, list_whatsapp_messages, prepare_whatsapp_inbound, parse_meta_messages, save_whatsapp_message
from app.whatsapp_medien import MAX_BILD_BYTES, MedienFehler, _KeineWeiterleitung, lade_bild

PNG = b'\x89PNG\r\n\x1a\n' + b'Pruefbild'


class MedienNachrichtenTests(unittest.TestCase):
    setUp = formulare.ManualCommunicationFormTests.setUp
    tearDown = formulare.ManualCommunicationFormTests.tearDown

    def bild_speichern(self, kennung='wamid.pruefbild', beschriftung='Fahrzeugschein'):
        roh = {'type': 'image', 'image': {'id': '123456789', 'mime_type': 'image/png', 'caption': beschriftung}}
        nachricht = WhatsAppInboundMessage('reliability-sender', None, self.phone, kennung,
                                           '1792400000', 'image', beschriftung, roh)
        verarbeitung = Mock(side_effect=AssertionError('Bilder dürfen keine Textannahme auslösen'))
        ergebnis = prepare_whatsapp_inbound(workshop_id=self.wid, message=nachricht, process_message=verarbeitung)
        verarbeitung.assert_not_called()
        return nachricht, ergebnis

    def test_bild_als_einzelne_offene_aufgabe_mit_vorschau(self):
        nachricht, ergebnis = self.bild_speichern()
        self.assertEqual(ergebnis['reason'], 'image_requires_workshop_review')
        erneut = prepare_whatsapp_inbound(workshop_id=self.wid, message=nachricht, process_message=Mock())
        self.assertEqual(erneut['action'], 'duplicate')
        ticket = find_ticket_by_id(self.wa_ticket, self.wid)
        notizen = [n for n in ticket['notes'] if n['message_id'] == 'wa:wamid.pruefbild']
        self.assertEqual(len(notizen), 1)
        self.assertTrue(notizen[0]['requires_human_action'])
        for adresse in ('/dashboard/whatsapp?phone=' + self.phone, '/dashboard/ticket/' + self.wa_ticket):
            seite = self.client.get(adresse)
            self.assertEqual(seite.status_code, 200)
            self.assertIn('alt="Vom Kunden gesendetes Foto"', seite.text)
            self.assertNotIn('graph.facebook.com', seite.text)
            self.assertNotIn('mock-token', seite.text)

    def test_beschriftung_ist_keine_zustimmung_auf_eine_werkstattfrage(self):
        add_ticket_note(self.wa_ticket, 'Dürfen wir den Filter wechseln?', workshop_id=self.wid,
                        purpose='workshop_question', message_id='frage-zum-filter')
        self.bild_speichern(beschriftung='Ja')
        ticket = find_ticket_by_id(self.wa_ticket, self.wid)
        frage = next(n for n in ticket['notes'] if n['message_id'] == 'frage-zum-filter')
        self.assertFalse(frage.get('resolved_at'))
        self.assertIsNone(ticket['notes'][-1]['reply_to_message_id'])

    def test_bild_ohne_ticket_bleibt_im_posteingang_zur_pruefung(self):
        set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone,
                                         mode='assistant', active_ticket_id=None)
        self.bild_speichern()
        steuerung = get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)
        self.assertEqual(steuerung['conversation_state'], 'waiting_for_workshop')
        self.assertIsNone(steuerung['active_ticket_id'])
        self.assertIn('alt="Vom Kunden gesendetes Foto"', self.client.get('/dashboard/whatsapp?phone=' + self.phone).text)

    def test_bildabruf_ist_geschuetzt_und_mandantengebunden(self):
        self.bild_speichern()
        nachricht = next(n for n in list_whatsapp_messages(workshop_id=self.wid) if n['wa_message_id'] == 'wamid.pruefbild')
        adresse = '/dashboard/whatsapp/medien/' + str(nachricht['id'])
        with patch('app.web.lade_bild', return_value=(PNG, 'image/png')) as abruf:
            antwort = self.client.get(adresse)
            self.assertEqual(antwort.content, PNG)
            self.assertIn('no-store', antwort.headers['cache-control'])
            self.assertEqual(antwort.headers['content-type'], 'image/png')
            self.assertEqual(abruf.call_args.kwargs['nummer_id'], 'reliability-sender')
        with get_conn() as verbindung:
            verbindung.execute('UPDATE whatsapp_messages SET workshop_id = ? WHERE id = ?', ('fremde-werkstatt', nachricht['id']))
            verbindung.commit()
        with patch('app.web.lade_bild') as abruf:
            self.assertEqual(self.client.get(adresse).status_code, 404)
            self.assertEqual(self.client.get(adresse + '?workshop_id=fremde-werkstatt').status_code, 404)
            abruf.assert_not_called()
        self.client.cookies.clear()
        self.client.headers.pop('cookie', None)
        self.assertEqual(self.client.get(adresse, follow_redirects=False).status_code, 303)

    def test_nicht_verfuegbares_bild_zeigt_verstaendliche_meldung(self):
        self.bild_speichern()
        nachricht = next(n for n in list_whatsapp_messages(workshop_id=self.wid) if n['wa_message_id'] == 'wamid.pruefbild')
        with patch('app.web.lade_bild', side_effect=MedienFehler('Bitte erneut senden.', 404)):
            antwort = self.client.get('/dashboard/whatsapp/medien/' + str(nachricht['id']))
        self.assertEqual(antwort.status_code, 404)
        self.assertIn('Bitte erneut senden.', antwort.text)
        self.assertIn('no-store', antwort.headers['cache-control'])

    def test_parser_erhaelt_die_bildbeschriftung(self):
        daten = {"object": "whatsapp_business_account", 'entry': [{"id": "synthetische-waba", 'changes': [{"field": "messages", 'value': {'metadata': {'phone_number_id': '123'}, 'messages': [
            {'from': '49123456789', 'id': 'wamid.bild', 'type': 'image', 'image': {'id': '789', 'caption': 'Mein Fahrzeugschein'}}
        ]}}]}]}
        self.assertEqual(parse_meta_messages(daten)[0].text, 'Mein Fahrzeugschein')

    def test_begrenzter_verlauf_zeigt_die_neuesten_nachrichten(self):
        for nummer in range(5):
            save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction='inbound',
                                  text=f'Neue Nachricht {nummer}', wa_message_id=f'wamid.verlauf{nummer}')
        nachrichten = list_whatsapp_messages(workshop_id=self.wid, customer_phone=self.phone, limit=2)
        self.assertEqual([n['text'] for n in nachrichten], ['Neue Nachricht 3', 'Neue Nachricht 4'])


class Antwort(io.BytesIO):
    def __init__(self, inhalt, typ, groesse=None):
        super().__init__(inhalt)
        self.headers = Message()
        self.headers['Content-Type'] = typ
        if groesse is not None:
            self.headers['Content-Length'] = str(groesse)


class MedienAbrufTests(unittest.TestCase):
    def abruf(self, **aenderungen):
        daten = {'url': 'https://lookaside.fbsbx.com/whatsapp_business/attachments/test',
                 'mime_type': 'image/png', 'file_size': len(PNG), **aenderungen}
        oeffner = Mock()
        oeffner.open.side_effect = [Antwort(json.dumps(daten).encode(), 'application/json'), Antwort(PNG, 'image/png')]
        return oeffner

    def laden(self):
        return lade_bild(medien_id='123456789', nummer_id='987654321', zugang='geheimer-testzugang', version='v23.0')

    def test_abruf_prueft_nummer_und_authentifiziert_beide_schritte(self):
        oeffner = self.abruf()
        with patch('app.whatsapp_medien.urllib.request.build_opener', return_value=oeffner):
            self.assertEqual(self.laden(), (PNG, 'image/png'))
        anfragen = [a.args[0] for a in oeffner.open.call_args_list]
        self.assertIn('phone_number_id=987654321', anfragen[0].full_url)
        for anfrage in anfragen:
            self.assertEqual(anfrage.get_header('Authorization'), 'Bearer geheimer-testzugang')
            self.assertNotIn('geheimer-testzugang', anfrage.full_url)

    def test_fremde_adressen_bekommen_keinen_zugang(self):
        for ziel in ('http://lookaside.fbsbx.com/bild', 'https://fremd.invalid/bild',
                     'https://lookaside.fbsbx.com.fremd.invalid/bild', 'https://user@lookaside.fbsbx.com/bild',
                     'https://lookaside.fbsbx.com:444/bild'):
            with self.subTest(ziel=ziel):
                oeffner = self.abruf(url=ziel)
                with patch('app.whatsapp_medien.urllib.request.build_opener', return_value=oeffner):
                    with self.assertRaises(MedienFehler):
                        self.laden()
                self.assertEqual(oeffner.open.call_count, 1)
        self.assertIsNone(_KeineWeiterleitung().redirect_request(None, None, 302, '', {}, 'https://fremd.invalid'))

    def test_dateigrenze_und_aktive_formate_werden_abgewiesen(self):
        for aenderungen in ({'file_size': MAX_BILD_BYTES + 1}, {'mime_type': 'image/svg+xml'}, {'mime_type': 'text/html'}):
            oeffner = self.abruf(**aenderungen)
            with patch('app.whatsapp_medien.urllib.request.build_opener', return_value=oeffner):
                with self.assertRaises(MedienFehler):
                    self.laden()
            self.assertEqual(oeffner.open.call_count, 1)

    def test_gelieferte_datei_muss_ein_bild_innerhalb_der_grenze_sein(self):
        for inhalt, typ, groesse in ((b'<html>kein Bild</html>', 'image/png', None),
                                    (PNG, 'text/html', None), (PNG, 'image/png', MAX_BILD_BYTES + 1),
                                    (b'x' * (MAX_BILD_BYTES + 1), 'image/png', None)):
            oeffner = self.abruf()
            # Beide Antworten werden je Prüffall frisch erzeugt.
            oeffner.open.side_effect = [Antwort(json.dumps({'url':'https://lookaside.fbsbx.com/bild','mime_type':'image/png'}).encode(), 'application/json'),
                                       Antwort(inhalt, typ, groesse)]
            with patch('app.whatsapp_medien.urllib.request.build_opener', return_value=oeffner):
                with self.assertRaises(MedienFehler):
                    self.laden()


if __name__ == '__main__':
    unittest.main()
