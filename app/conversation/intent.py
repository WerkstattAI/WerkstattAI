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
    STEP_QUOTE_ANLIEGEN,
    STEP_QUOTE_FAHRZEUG,
    STEP_QUOTE_NAME,
    STEP_QUOTE_TELEFON,
    STEP_TELEFON,
)
from app.conversation.extractors import can_extract_vehicle, extract_km, extract_year, lower, normalize
from app.models import IntakeState


INTENT_NEW_REQUEST = "new_request"
INTENT_EXISTING_TICKET = "existing_ticket"
INTENT_GENERAL_QUESTION = "general_question"
INTENT_QUOTE_REQUEST = "quote_request"
INTENT_UNCLEAR = "unclear"


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

ACTIVE_QUOTE_STEPS = {
    STEP_QUOTE_ANLIEGEN,
    STEP_QUOTE_FAHRZEUG,
    STEP_QUOTE_TELEFON,
    STEP_QUOTE_NAME,
}


EXISTING_TICKET_KEYWORDS = [
    "bestehendes ticket",
    "bestehenden ticket",
    "anfrage zu einem bestehenden ticket",
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
    "allgemeine frage",
    "eine allgemeine frage",
    "oeffnungszeiten",
    "öffnungszeiten",
    "wann offen",
    "wann habt ihr offen",
    "offen",
    "samstag",
    "samstags",
    "adresse",
    "wo seid ihr",
    "wo genau",
    "wo ist eure werkstatt",
    "wo ist die werkstatt",
    "wo finde ich euch",
    "wo findet man euch",
    "standort",
    "kontakt",
    "telefon",
    "telefonnummer",
    "nummer",
    "email",
    "preise",
    "preis",
    "kosten",
    "leistungen",
    "was macht eure werkstatt",
    "werkstatt alles",
    "repariert ihr",
    "abschleppdienst",
    "abschleppen",
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

QUOTE_REQUEST_KEYWORDS = [
    "kostenvoranschlag",
    "kosten voranschlag",
    "kostenschätzung",
    "kostenschaetzung",
    "preisanfrage",
    "preis anfrage",
    "angebot",
    "was kostet",
    "kostet",
    "wieviel kostet",
    "wieviel",
    "wie viel kostet",
    "wie teuer",
    "preis",
    "preise",
    "kosten",
    "preis für",
    "preis fuer",
    "kosten für",
    "kosten fuer",
]

NEW_REQUEST_HINTS = [
    "problem melden",
    "ich möchte ein problem melden",
    "springt nicht an",
    "startet nicht",
    "geht nicht an",
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
    "wagen",
    "karre",
    "fahrzeug",
    "motor",
    "geräusch",
    "geraeusch",
    "stinkt",
    "ruckelt",
    "problem",
    "defekt",
    "funktioniert nicht",
]

AI_FREEFORM_HINTS = [
    "chatgpt",
    "ki",
    "künstliche intelligenz",
    "kuenstliche intelligenz",
    "schreib mir",
    "schreibe mir",
    "formuliere",
    "formuliere mir",
    "kannst du helfen",
    "kannst du mir helfen",
    "hilf mir",
    "was soll ich machen",
    "antworte als",
    "mach mir einen text",
    "erstelle mir",
]

EXPLICIT_NEW_REQUEST_CHOICES = [
    "problem melden",
    "neues problem",
    "neue meldung",
    "ich möchte ein problem melden",
    "ich moechte ein problem melden",
]

EXPLICIT_GENERAL_CHOICES = [
    "allgemeine frage",
    "eine allgemeine frage",
    "ich habe eine allgemeine frage",
]

EXPLICIT_EXISTING_CHOICES = [
    "bestehendes ticket",
    "bestehenden ticket",
    "anfrage zu einem bestehenden ticket",
    "ich habe eine anfrage zu einem bestehenden ticket",
]


def is_active_intake_step(step: str | None) -> bool:
    return (step or "").strip().lower() in ACTIVE_INTAKE_STEPS


def is_active_quote_step(step: str | None) -> bool:
    return (step or "").strip().lower() in ACTIVE_QUOTE_STEPS


def extract_ticket_reference(text: str) -> str | None:
    """
    Erkennt grob Ticket-Referenzen wie:
    - WAI-123
    - Ticket 123
    - Ticketnummer 123
    """
    t = normalize(text)

    m = re.search(
        r"\b([A-Z]{2,10}-\d{4,8}(?:-\d{1,10})?)\b",
        t,
        flags=re.IGNORECASE,
    )
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
    tl = lower(t)

    has_phone_context = any(
        keyword in tl
        for keyword in [
            "telefon",
            "telefonnummer",
            "nummer",
            "handy",
            "mobil",
            "rufnummer",
        ]
    )

    if not has_phone_context and (extract_year(t) or extract_km(t)):
        return None

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

    if (extract_year(text) or extract_km(text)) and "ticket" not in t:
        return False

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


def looks_like_quote_request(text: str) -> bool:
    t = lower(text)
    return any(keyword in t for keyword in QUOTE_REQUEST_KEYWORDS)


def looks_like_ai_freeform_request(text: str) -> bool:
    t = lower(text)
    return any(keyword in t for keyword in AI_FREEFORM_HINTS)


def looks_like_vehicle_intake_start(text: str) -> bool:
    return can_extract_vehicle(text) and bool(extract_year(text) or extract_km(text))


def has_explicit_new_request_choice(text: str) -> bool:
    t = lower(text).rstrip(".")
    return any(keyword in t for keyword in EXPLICIT_NEW_REQUEST_CHOICES)


def has_explicit_general_choice(text: str) -> bool:
    t = lower(text).rstrip(".")
    return any(keyword in t for keyword in EXPLICIT_GENERAL_CHOICES)


def has_explicit_existing_choice(text: str) -> bool:
    t = lower(text).rstrip(".")
    return any(keyword in t for keyword in EXPLICIT_EXISTING_CHOICES)


def has_direct_ticket_reference(text: str) -> bool:
    return bool(extract_ticket_reference(text) or extract_phone_reference(text))


def has_explicit_ticket_context(text: str) -> bool:
    t = lower(text)
    if has_direct_ticket_reference(text):
        return True

    explicit_keywords = [
        "bestehendes ticket",
        "bestehenden ticket",
        "ticket",
        "ticketnr",
        "ticket-nr",
        "ticketnummer",
        "auftrag",
        "fall",
    ]
    return any(keyword in t for keyword in explicit_keywords)


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
        return INTENT_UNCLEAR

    msg = normalize(user_message)

    mode = (getattr(state, "mode", None) or "unknown").strip().lower()

    if has_explicit_new_request_choice(msg):
        return INTENT_NEW_REQUEST

    if has_explicit_existing_choice(msg):
        return INTENT_EXISTING_TICKET

    if looks_like_quote_request(msg):
        return INTENT_QUOTE_REQUEST

    if looks_like_ai_freeform_request(msg):
        return INTENT_UNCLEAR

    if has_explicit_general_choice(msg):
        return INTENT_GENERAL_QUESTION

    if mode == "new" and is_active_intake_step(getattr(state, "step", None)):
        return INTENT_NEW_REQUEST

    if mode == "quote" and is_active_quote_step(getattr(state, "step", None)):
        return INTENT_QUOTE_REQUEST

    if mode == "existing" and getattr(state, "ticket_id", None):
        return INTENT_EXISTING_TICKET

    if has_direct_ticket_reference(msg):
        return INTENT_EXISTING_TICKET

    if looks_like_general_question(msg) and not has_explicit_ticket_context(msg):
        return INTENT_GENERAL_QUESTION

    if looks_like_existing_ticket_question(msg):
        return INTENT_EXISTING_TICKET

    if looks_like_new_request(msg) or looks_like_vehicle_intake_start(msg):
        return INTENT_NEW_REQUEST

    return INTENT_UNCLEAR
