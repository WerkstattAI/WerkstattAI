"""Konservative Symbolauswahl ohne erfundene exakte Fahrzeugbilder."""
import unittest
from app.oberflaeche import fahrzeugsymbol


class FahrzeugsymboleTests(unittest.TestCase):
    def test_karosserieangabe_hat_vorrang(self):
        for name, expected in [('VW Golf VII','kompakt'),('VW Golf Variant','kombi'),
                               ('Mercedes C180','limousine'),('Mercedes C180 Coupe','coupe'),
                               ('BMW 320d Touring','kombi'),('Audi Q5','suv'),
                               ('Mercedes Sprinter','transporter')]:
            with self.subTest(name=name):
                self.assertEqual(fahrzeugsymbol(name),expected)

    def test_unbekannte_modelle_und_leere_eingaben_bleiben_neutral(self):
        for name in [None,'','Unbekannt','Skoda Octavia','Golfplatzmobil','<script>']:
            self.assertEqual(fahrzeugsymbol(name),'neutral')
