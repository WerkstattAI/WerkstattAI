"""Künstliche bestätigte Verbindungen ausschließlich in isolierten Testdatenbanken."""
from dataclasses import replace
from unittest.mock import patch

from cryptography.fernet import Fernet

import app.whatsapp_verbindungen as verbindungen
from app.db import get_conn

TESTSCHLUESSEL = Fernet.generate_key().decode("ascii")


def synthetische_verbindung(workshop_id, nummer, token="synthetischer-kundenzugang"):
    with get_conn() as conn:
        alt = conn.execute("SELECT version FROM whatsapp_verbindungen WHERE workshop_id = ?", (workshop_id,)).fetchone()
    with patch.object(verbindungen, "settings", replace(verbindungen.settings, whatsapp_zugangsschluessel=TESTSCHLUESSEL)):
        version = verbindungen.speichere_verbindungsentwurf(workshop_id=workshop_id, waba_id="synthetische-waba",
            phone_number_id=nummer, anzeigenummer="", token=token, erwartete_version=alt["version"] if alt else 0)
    # Nur Tests simulieren das später erforderliche, verifizierte Meta-Ergebnis.
    with get_conn() as conn:
        conn.execute("""UPDATE whatsapp_verbindungen SET autorisierung = 'bestaetigt', zustand = 'verbunden',
            herkunft = 'synthetischer_test' WHERE workshop_id = ?""", (workshop_id,))
        conn.commit()
    return version
