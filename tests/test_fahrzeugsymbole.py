"""Markenzuordnung mit neutralem Rückfall statt geratener Fahrzeugmodelle."""
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from app.oberflaeche import fahrzeugsymbol, kilometeranzeige


class FahrzeugsymboleTests(unittest.TestCase):
    def test_alle_freigegebenen_marken(self):
        beispiele = {'VW Golf':'volkswagen', 'BMW 320d':'bmw', 'Mercedes-Benz C180':'mercedes',
                     'Audi A4':'audi', 'Škoda Octavia':'skoda', 'Opel Astra':'opel',
                     'Ford Focus':'ford', 'Toyota Corolla':'toyota', 'Renault Clio':'renault',
                     'Peugeot 308':'peugeot', 'Citroën C3':'citroen', 'SEAT Leon':'seat',
                     'Hyundai i30':'hyundai', 'Kia Ceed':'kia', 'Volvo V60':'volvo',
                     'Nissan Qashqai':'nissan', 'Mazda 3':'mazda', 'Dacia Sandero':'dacia'}
        for name, marke in beispiele.items():
            with self.subTest(name=name):
                self.assertEqual(fahrzeugsymbol(name), marke)

    def test_modell_und_karosserie_aendern_das_markenbild_nicht(self):
        for marke, namen in {
            'volkswagen':['VW Golf Variant', 'Volkswagen Touareg', 'vw up', 'V.W. Polo'],
            'bmw':['BMW X5', 'BMW320d Touring', 'b.m.w. 118i', 'ＢＭＷ 520d'],
            'mercedes':['Mercedes Sprinter', 'Mercedes-Benz C180 Coupe', 'MercedesBenz GLC', 'Benz Vito'],
            'skoda':['Skoda Fabia', 'ŠKODA Kodiaq', 'S\u030ckoda Superb'],
            'citroen':['CITROEN C4', 'Citroën Berlingo'],
        }.items():
            for name in namen:
                with self.subTest(name=name):
                    self.assertEqual(fahrzeugsymbol(name), marke)

    def test_unbekannt_mehrdeutig_und_modell_allein_bleiben_neutral(self):
        for name in [None, '', 'Unbekannt', 'Golf', '320d', 'C180', 'SUV', 'Tesla Model 3',
                     'Golfplatzmobil', 'Fordson', 'Auditor', 'Kian', 'Volvobus', 'Alfa Romeo',
                     'BMW / Audi', 'Volkswagen oder Mercedes', '<script>']:
            with self.subTest(name=name):
                self.assertEqual(fahrzeugsymbol(name), 'neutral')

    def test_wiederholte_identische_marke_bleibt_eindeutig(self):
        self.assertEqual(fahrzeugsymbol('VW / Volkswagen Golf'), 'volkswagen')

    def test_vorlage_verwendet_unterschiedliche_bildausschnitte_und_echte_daten(self):
        root = Path(__file__).resolve().parents[1]
        env = Environment(loader=FileSystemLoader(root / 'templates'), autoescape=True)
        env.filters.update(fahrzeugsymbol=fahrzeugsymbol, kilometeranzeige=kilometeranzeige)
        karte = env.get_template('_fahrzeugkarte.html').module.fahrzeugkarte
        from xml.etree import ElementTree
        positionen = set()
        for name in ['Volkswagen', 'BMW', 'Mercedes', 'Audi', 'Škoda', 'Opel', 'Ford', 'Toyota',
                     'Renault', 'Peugeot', 'Citroën', 'SEAT', 'Hyundai', 'Kia', 'Volvo',
                     'Nissan', 'Mazda', 'Dacia', 'unbekannt']:
            html = str(karte(dict(fahrzeug=name, baujahr=2020, kilometerstand=123456)))
            self.assertIn('123.456 km', html)
            self.assertIn('2020', html)
            self.assertIn('data-fahrzeugmarke="'+fahrzeugsymbol(name)+'"', html)
            svg = ElementTree.fromstring(html[html.index('<svg '):html.index('</svg>')+6])
            bild = svg.find('image')
            self.assertTrue((root / bild.attrib['href'].lstrip('/')).is_file())
            positionen.add((bild.attrib['x'], bild.attrib['y']))
        self.assertEqual(len(positionen), 19)
