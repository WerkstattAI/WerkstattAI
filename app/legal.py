from __future__ import annotations

import os


def provider_details() -> dict:
    """Only explicit provider data; never infer legal identity from a demo workshop."""
    return {
        "name": os.getenv("LEGAL_PROVIDER_NAME") or "Mikolaj Olszewski",
        "business_name": os.getenv("LEGAL_BUSINESS_NAME") or "WerkstattAI",
        "legal_form": os.getenv("LEGAL_LEGAL_FORM") or "[Rechtsform / Einzelunternehmen bestätigen]",
        "address": os.getenv("LEGAL_ADDRESS") or "[Straße und Hausnummer]\n[Postleitzahl und Ort]\n[Land]",
        "email": os.getenv("LEGAL_EMAIL") or "kontakt.werkstattai.de@outlook.com",
        "phone": os.getenv("LEGAL_PHONE") or "[Telefonnummer ergänzen]",
        "representative": os.getenv("LEGAL_REPRESENTATIVE") or "",
        "register": os.getenv("LEGAL_REGISTER") or "",
        "vat_id": os.getenv("LEGAL_VAT_ID") or "",
        "business_id": os.getenv("LEGAL_BUSINESS_ID") or "",
    }
