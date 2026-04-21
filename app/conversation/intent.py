from __future__ import annotations

import re

from app.conversation.constants import (
    STEP_ABSCHLEPPDIENST,
    STEP_BAUJAHR,
    STEP_FAHRBEREIT,
    STEP_FAHRZEUG,
    STEP_FOLLOWUP,
    STEP_KILOMETERSTAND,
    STEP_NAME,
    STEP_PROBLEM,
    STEP_TELEFON,
)
from app.conversation.extractors import lower, normalize
from app.models import IntakeState


INTENT_NEW_REQUEST = "new_request"
INTENT_EXISTING_TICKET = "existing_ticket"
INTENT_GENERAL_QUESTION = "general_question"


ACTIVE_INTAKE_STEPS = {
    STEP_FAHRZEUG,
    STEP_BAUJAHR,
    STEP_KILOMETERSTAND,
    STEP_PROBLEM,
    STEP_FAHRBEREIT,
    STEP_ABSCHLEPPDIENST,
    STEP_FOLLOWUP,
    STEP_TELEFON,
    STEP_NAME,
}


EXISTING_TICKET_KEYWORDS = [
    "ticket",
    "ticketnr",
    "ticket-nr",
    "ticketnummer",
    "status",
    "auftrag",
    "fall",
    "notiz",
    "notizen",
    "zusammenfassung",
    "zusammenfassen",
    "zusammengefasst",
    "zeige",
    "zeig",
    "such",
    "suche",
    "finden",
    "finde",
    "kundenname",
    "telefonnummer",
    "telefon",
    "nummer",
    "kontakt",
    "priorität",
    "prioritaet",
    "fahrzeug",
    "was war",
    "was steht",
]

GENERAL_QUESTION_KEYWORDS = [
    "was bedeutet",
    "wie funktioniert",
    "wie geht",
    "kannst du helfen",
    "hilf mir",
    "erklär",
    "erklaer",
    "erkläre",
    "formuliere",
    "schreib mir",
    "antworte",
    "antworten",
    "was soll ich",
    "kannst du mir sagen",
]

NEW_REQUEST_HINTS = [
    "springt nicht an",
    "startet nicht",
    "inspektion",
    "service",
    "ölwechsel",
    "oelwechsel",
    "reifenwechsel",
    "warnlampe",
    "motorkontrollleuchte",
    "bremse",
    "lenkung",
    "auto",
    "fahrzeug",
    "motor",
    "problem",
    "defekt",
    "funktioniert nicht",
]


def is_active_intake_step(step: str | None) -> bool:
    return (step or "").strip().lower() in ACTIVE_INTAKE_STEPS


def extract_ticket_reference(text: str) -> str | None:
    """
    Erkennt grob Ticket-Referenzen wie:
    - WAI-123
    - Ticket 123
    - Ticketnummer 123
    """
    t = normalize(text)

    m = re.search(r"\b([A-Z]{2,10}-\d{1,10})\b", t, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    m = re.search(
        r"\b(?:ticket|ticketnr|ticket-nr|ticketnummer|auftrag|fall)\s*[:#-]?\s*(\d{1,10})\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1)

    return None


def extract_phone_reference(text: str) -> str | None:
    """
    Erkennt grob Telefonnummern im Text.
    Für die Intent-Erkennung reicht das:
    Wenn >= 7 Ziffern vorkommen, behandeln wir das als mögliche Telefonsuche.
    """
    t = normalize(text)
    digits = re.sub(r"\D", "", t)

    if len(digits) >= 7:
        return digits

    return None


def looks_like_existing_ticket_question(text: str) -> bool:
    t = lower(text)

    if extract_ticket_reference(text):
        return True

    if extract_phone_reference(text):
        return True

    return any(keyword in t for keyword in EXISTING_TICKET_KEYWORDS)


def looks_like_general_question(text: str) -> bool:
    t = lower(text)

    if "?" in text and any(keyword in t for keyword in GENERAL_QUESTION_KEYWORDS):
        return True

    if any(keyword in t for keyword in GENERAL_QUESTION_KEYWORDS):
        return True

    return False


def looks_like_new_request(text: str) -> bool:
    t = lower(text)
    return any(keyword in t for keyword in NEW_REQUEST_HINTS)


def detect_intent(state: IntakeState, user_message: str | None) -> str:
    """
    Erkennt grob die Absicht des Nutzers:
    - new_request
    - existing_ticket
    - general_question

    WICHTIG:
    Wenn ein Intake bereits läuft, bleibt der Intent auf new_request,
    damit der Flow nicht mitten drin kaputtgeht.
    """
    if user_message is None or normalize(user_message) == "":
        return INTENT_NEW_REQUEST

    msg = normalize(user_message)

    if is_active_intake_step(getattr(state, "step", None)):
        return INTENT_NEW_REQUEST

    if looks_like_existing_ticket_question(msg):
        return INTENT_EXISTING_TICKET

    if looks_like_general_question(msg):
        return INTENT_GENERAL_QUESTION

    if looks_like_new_request(msg):
        return INTENT_NEW_REQUEST

    return INTENT_NEW_REQUEST