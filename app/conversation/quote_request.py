from __future__ import annotations

from typing import Tuple

from app.conversation.constants import (
    REQUEST_TYPE_KOSTENVORANSCHLAG,
    STEP_FERTIG,
    STEP_QUOTE_ANLIEGEN,
    STEP_QUOTE_FAHRZEUG,
    STEP_QUOTE_NAME,
    STEP_QUOTE_TELEFON,
    SKIP_VALUES,
)
from app.conversation.extractors import (
    cleanup_vehicle_text,
    extract_year,
    extract_name_candidate,
    extract_phone,
    lower,
    normalize,
)
from app.conversation.new_request import copy_state, fresh_intake_state_from, reset_state
from app.models import IntakeState


def is_quote_starter(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "kostenvoranschlag",
            "kosten voranschlag",
            "preisanfrage",
            "preis anfrage",
            "angebot",
            "was kostet",
            "wie viel kostet",
            "wie teuer",
            "kosten",
            "preis",
        ]
    )


def _is_quote_button(text: str) -> bool:
    t = lower(text).rstrip(".")
    return t in {
        "ich möchte einen kostenvoranschlag anfragen",
        "ich moechte einen kostenvoranschlag anfragen",
        "kostenvoranschlag anfragen",
    }


def _quote_welcome_reply() -> str:
    return (
        "Gerne. Für einen Kostenvoranschlag brauche ich kurz ein paar Angaben.\n"
        "Welche Leistung oder Reparatur soll ungefähr kalkuliert werden?"
    )


def _ask_vehicle_reply() -> str:
    return (
        "Danke. Zu welchem Fahrzeug gehört die Anfrage?\n"
        "Bitte nennen Sie Marke, Modell und wenn möglich Baujahr. "
        "Beispiel: VW Golf 2018."
    )


def _ask_phone_reply() -> str:
    return (
        "Alles klar. Unter welcher Telefonnummer kann die Werkstatt Sie "
        "für Rückfragen oder ein Angebot erreichen?"
    )


def _ask_phone_invalid_reply() -> str:
    return "Bitte geben Sie eine gültige Telefonnummer an (mindestens 7 Ziffern)."


def _ask_name_reply() -> str:
    return 'Wie dürfen wir Sie ansprechen? (optional, sonst „überspringen“ schreiben)'


def _completion_reply(state: IntakeState) -> str:
    return (
        "Perfekt – Ihre Anfrage für einen Kostenvoranschlag wurde aufgenommen.\n\n"
        "Zusammenfassung:\n"
        f"- Anfrage: {state.problem or '-'}\n"
        f"- Fahrzeug: {state.fahrzeug or '-'}\n"
        f"- Telefon: {state.telefon or '-'}\n"
        f"- Name: {state.name or '-'}\n\n"
        "Die Werkstatt prüft die Angaben und meldet sich mit einer Einschätzung."
    )


def handle_quote_request(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:
    if user_message is None or normalize(user_message) == "":
        new_state = reset_state()
        new_state.mode = "quote"
        new_state.step = STEP_QUOTE_ANLIEGEN
        return new_state, _quote_welcome_reply(), False

    msg = normalize(user_message)
    if (getattr(state, "mode", None) or "unknown").strip().lower() != "quote":
        new_state = fresh_intake_state_from(state, mode="quote")
    else:
        new_state = copy_state(state)

    new_state.mode = "quote"
    new_state.request_type = REQUEST_TYPE_KOSTENVORANSCHLAG
    new_state.priority = "normal"
    new_state.last_user_message = msg

    if new_state.step not in {
        STEP_QUOTE_ANLIEGEN,
        STEP_QUOTE_FAHRZEUG,
        STEP_QUOTE_TELEFON,
        STEP_QUOTE_NAME,
    }:
        new_state.step = STEP_QUOTE_ANLIEGEN

    if new_state.step == STEP_QUOTE_ANLIEGEN:
        if _is_quote_button(msg):
            return new_state, _quote_welcome_reply(), False

        if len(msg) < 3:
            return new_state, "Bitte beschreiben Sie kurz, wofür Sie einen Kostenvoranschlag möchten.", False

        new_state.problem = msg
        new_state.step = STEP_QUOTE_FAHRZEUG
        return new_state, _ask_vehicle_reply(), False

    if new_state.step == STEP_QUOTE_FAHRZEUG:
        fahrzeug = cleanup_vehicle_text(msg)
        if len(fahrzeug) < 3:
            return new_state, "Bitte nennen Sie kurz Marke und Modell des Fahrzeugs.", False

        new_state.fahrzeug = fahrzeug
        new_state.baujahr = extract_year(msg)
        new_state.step = STEP_QUOTE_TELEFON
        return new_state, _ask_phone_reply(), False

    if new_state.step == STEP_QUOTE_TELEFON:
        phone = extract_phone(msg)
        if not phone:
            return new_state, _ask_phone_invalid_reply(), False

        new_state.telefon = phone
        new_state.step = STEP_QUOTE_NAME
        return new_state, _ask_name_reply(), False

    if new_state.step == STEP_QUOTE_NAME:
        if lower(msg) in SKIP_VALUES:
            new_state.name = None
        else:
            new_state.name = extract_name_candidate(msg)

        new_state.step = STEP_FERTIG
        return new_state, _completion_reply(new_state), True

    new_state.step = STEP_QUOTE_ANLIEGEN
    return new_state, _quote_welcome_reply(), False
