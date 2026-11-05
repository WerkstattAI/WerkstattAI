"""Gesprächsvorschau zeigt keine internen Notizen und keine falschen Absender."""
import unittest
from app.nachrichtenvorschau import letzte_nachricht


class NachrichtenvorschauTests(unittest.TestCase):
    def test_interne_notiz_und_unbekannte_zwecke_bleiben_ausgeschlossen(self):
        self.assertIsNone(letzte_nachricht([{'purpose':'internal_note','text':'Intern'}, {'text':'Alt'}]))
        notes = [{'purpose':'customer_information','text':'Hallo','created_at':'2026-11-05T10:00:00Z'},
                 {'purpose':'internal_note','text':'Geheim','created_at':'2026-11-05T12:00:00Z'}]
        self.assertEqual(letzte_nachricht(notes)['text'], 'Hallo')

    def test_zeitvergleich_beruecksichtigt_zeitzonen(self):
        notes = [{'purpose':'customer_information','text':'Neu','created_at':'2026-11-05T10:30:00Z'},
                 {'purpose':'workshop_answer','text':'Alt','created_at':'2026-11-05T11:00:00+01:00'}]
        self.assertEqual(letzte_nachricht(notes)['text'], 'Neu')

    def test_whatsapp_foto_und_automatischer_absender(self):
        bild = letzte_nachricht([], {'direction':'inbound','message_type':'image'})
        self.assertEqual((bild['text'],bild['sender']), ('Foto','Kunde'))
        antwort = letzte_nachricht([], {'direction':'outbound','payload_json':'{"source":"webhook"}',
                                       'text':'Antwort','status':'failed'})
        self.assertEqual((antwort['sender'],antwort['versandhinweis']), ('Assistent','Nicht gesendet'))

    def test_kanonische_absender_und_fehlerhafte_metadaten(self):
        note = {'message_id':'m1','purpose':'workshop_notification','sender_role':'workshop','text':'Antwort'}
        wa = {'message_id':'m1','direction':'outbound','text':'Antwort','payload_json':'{"source":"webhook"}'}
        self.assertEqual(letzte_nachricht([note],wa)['sender'],'Werkstatt')
        for payload in ['[]','kaputt','null']:
            self.assertEqual(letzte_nachricht([],dict(wa,payload_json=payload))['sender'],'Werkstatt')
