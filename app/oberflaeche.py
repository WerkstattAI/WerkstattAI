"""Reine Anzeigehilfen für den Werkstattbereich."""

import re


def fahrzeugsymbol(wert):
    """Grobe Modellfamilie, niemals eine behauptete exakte Modellabbildung."""
    text = re.sub(r"[^a-z0-9äöüß]+", " ", str(wert or '').lower()).strip()
    if not text:
        return 'neutral'
    # Explizite Karosserieangaben haben Vorrang vor der Modellfamilie.
    for muster, symbol in [
        (r'\b(kombi|variant|touring|avant|sports tourer|t modell|estate)\b', 'kombi'),
        (r'\b(coupe|coupé|cabrio|cabriolet|roadster)\b', 'coupe'),
        (r'\b(transporter|sprinter|crafter|transit|vito|multivan|v klasse)\b', 'transporter'),
        (r'\b(suv|tiguan|touareg|kodiaq|karoq|q[3-8]|x[1-7]|gl[abcse])\b', 'suv'),
        (r'\b(golf|polo|up|fabia|clio|corsa|fiesta|yaris|aygo|mini)\b', 'kompakt'),
        (r'\b(limousine|sedan|c\s?(180|200|220|250|300)|[35][12][0689][di]?)\b', 'limousine'),
    ]:
        if re.search(muster, text):
            return symbol
    return 'neutral'


def kilometeranzeige(wert):
    if wert is None or str(wert).strip() == "":
        return "Nicht angegeben"
    text = str(wert).strip()
    if re.fullmatch(r"[0-9]+|[0-9]{1,3}(?:[. ][0-9]{3})+", text):
        zahl = text.replace('.', '').replace(' ', '').lstrip('0') or '0'
        return re.sub(r"(?<=[0-9])(?=(?:[0-9]{3})+$)", '.', zahl) + ' km'
    return text
