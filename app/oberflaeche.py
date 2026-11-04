"""Reine Anzeigehilfen für den Werkstattbereich."""

import re
import unicodedata


# Nur ausdrücklich genannte Marken; Modellnamen allein werden nicht geraten.
_FAHRZEUGMARKEN = {
    'volkswagen': r'volkswagen|vw|v\W+w\.?',
    'bmw': r'bmw|b\W+m\W+w\.?',
    'mercedes': r'mercedes(?:\W*benz)?|benz',
    'audi': r'audi',
    'skoda': r'skoda',
    'opel': r'opel',
    'ford': r'ford',
    'toyota': r'toyota',
    'renault': r'renault',
    'peugeot': r'peugeot',
    'citroen': r'citroen',
    'seat': r'seat',
    'hyundai': r'hyundai',
    'kia': r'kia',
    'volvo': r'volvo',
    'nissan': r'nissan',
    'mazda': r'mazda',
    'dacia': r'dacia',
}


def fahrzeugsymbol(wert):
    """Ein Symbolbild pro Marke, unabhängig von Modell und Karosserie."""
    text = ''.join(zeichen for zeichen in unicodedata.normalize('NFKD', str(wert or '').casefold())
                   if not unicodedata.combining(zeichen))
    marken = {marke for marke, muster in _FAHRZEUGMARKEN.items()
              if re.search(r'(?<!\w)(?:' + muster + r')(?![^\W\d_])', text)}
    # Mehrere unterschiedliche Marken sind ohne weitere Daten nicht eindeutig.
    return next(iter(marken)) if len(marken) == 1 else 'neutral'


def kilometeranzeige(wert):
    if wert is None or str(wert).strip() == "":
        return "Nicht angegeben"
    text = str(wert).strip()
    if re.fullmatch(r"[0-9]+|[0-9]{1,3}(?:[. ][0-9]{3})+", text):
        zahl = text.replace('.', '').replace(' ', '').lstrip('0') or '0'
        return re.sub(r"(?<=[0-9])(?=(?:[0-9]{3})+$)", '.', zahl) + ' km'
    return text
