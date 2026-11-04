"""Reine Anzeigehilfen für den Werkstattbereich."""

import re


def kilometeranzeige(wert):
    if wert is None or str(wert).strip() == "":
        return "Nicht angegeben"
    text = str(wert).strip()
    if re.fullmatch(r"[0-9]+|[0-9]{1,3}(?:[. ][0-9]{3})+", text):
        zahl = text.replace('.', '').replace(' ', '').lstrip('0') or '0'
        return re.sub(r"(?<=[0-9])(?=(?:[0-9]{3})+$)", '.', zahl) + ' km'
    return text
