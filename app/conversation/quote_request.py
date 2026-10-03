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
    is_cancel_command,
    is_correction,
    is_unavailable_answer,
    extract_name_candidate,
    extract_phone,
    lower,
    normalize,
)
from app.conversation.intake_fields import consume_intake_fields
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
        "kostenvoranschlag",
        "angebot anfragen",
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


def pending_quote_question(state: IntakeState) -> str:
    return {
        STEP_QUOTE_ANLIEGEN: _quote_welcome_reply,
        STEP_QUOTE_FAHRZEUG: _ask_vehicle_reply,
        STEP_QUOTE_TELEFON: _ask_phone_reply,
        STEP_QUOTE_NAME: _ask_name_reply,
    }.get(state.step, _quote_welcome_reply)()


def _advance_quote(state: IntakeState) -> Tuple[IntakeState, str, bool]:
    for field, step in (
        ("problem", STEP_QUOTE_ANLIEGEN), ("fahrzeug", STEP_QUOTE_FAHRZEUG),
        ("telefon", STEP_QUOTE_TELEFON), ("name", STEP_QUOTE_NAME),
    ):
        if not getattr(state, field):
            state.step = step
            return state, pending_quote_question(state), False
    state.step = STEP_FERTIG
    return state, _completion_reply(state), True


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
    if is_cancel_command(msg):
        return fresh_intake_state_from(state, mode="unknown"), "Die Aufnahme ist abgebrochen. Sie können jederzeit ein neues Anliegen melden.", False
    if state.ticket_id or state.step == STEP_FERTIG or (getattr(state, "mode", None) or "unknown").strip().lower() != "quote":
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

    changed, correction = consume_intake_fields(
        new_state, msg, vehicle_answer=new_state.step == STEP_QUOTE_FAHRZEUG or is_correction(msg),
    )
    if correction:
        result_state, reply, done = _advance_quote(new_state)
        prefix = "Danke, die Angaben sind korrigiert." if changed else "Welche Angabe soll ich korrigieren?"
        return result_state, prefix + "\n" + reply, done
    if is_unavailable_answer(msg) and new_state.step != STEP_QUOTE_NAME:
        attempts = new_state.unavailable_attempts.get(new_state.step, 0) + 1
        new_state.unavailable_attempts[new_state.step] = attempts
        hint = "Diese Angabe wird noch benötigt."
        if new_state.step == STEP_QUOTE_FAHRZEUG:
            hint += " Marke und Modell stehen in den Fahrzeugunterlagen; das Baujahr ist hier optional."
        if attempts == 2:
            hint = "Sie können später weitermachen oder mit „abbrechen“ beenden. " + hint
        elif attempts > 2:
            return new_state, "Ich warte auf die fehlende Angabe. Schreiben Sie sie hier, sobald sie vorliegt, oder beenden Sie mit „abbrechen“.", False
        return new_state, hint + "\n" + pending_quote_question(new_state), False

    if new_state.step == STEP_QUOTE_ANLIEGEN:
        if _is_quote_button(msg):
            return new_state, _quote_welcome_reply(), False

        if len(msg) < 3 or (changed and not new_state.problem):
            return new_state, "Bitte beschreiben Sie kurz, wofür Sie einen Kostenvoranschlag möchten.", False

        new_state.problem = new_state.problem or msg
        return _advance_quote(new_state)

    if new_state.step == STEP_QUOTE_FAHRZEUG:
        if not new_state.fahrzeug:
            return new_state, "Bitte nennen Sie kurz Marke und Modell des Fahrzeugs.", False
        return _advance_quote(new_state)

    if new_state.step == STEP_QUOTE_TELEFON:
        phone = extract_phone(msg)
        if not phone:
            return new_state, _ask_phone_invalid_reply(), False

        new_state.telefon = phone
        return _advance_quote(new_state)

    if new_state.step == STEP_QUOTE_NAME:
        if lower(msg) in SKIP_VALUES or is_unavailable_answer(msg):
            new_state.name = None
        else:
            new_state.name = extract_name_candidate(msg)
            if not new_state.name:
                return new_state, _ask_name_reply(), False

        new_state.step = STEP_FERTIG
        return new_state, _completion_reply(new_state), True

    new_state.step = STEP_QUOTE_ANLIEGEN
    return new_state, _quote_welcome_reply(), False
