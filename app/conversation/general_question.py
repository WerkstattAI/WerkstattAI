from __future__ import annotations

from typing import Tuple

from app.conversation.extractors import lower, normalize
from app.models import IntakeState


# =========================================================
# INTENT HELPERS
# =========================================================

def _is_opening_hours_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "öffnungszeiten",
        "wann offen",
        "wann habt ihr offen",
        "wann geöffnet",
        "opening hours",
    ])


def _is_location_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "adresse",
        "wo seid ihr",
        "wo ist die werkstatt",
        "standort",
        "location",
    ])


def _is_contact_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "kontakt",
        "telefon",
        "nummer",
        "email",
        "wie erreichen",
    ])


def _is_service_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "was macht ihr",
        "leistungen",
        "service",
        "repariert ihr",
        "was könnt ihr",
    ])


def _is_price_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "preis",
        "kosten",
        "wie teuer",
        "wie viel kostet",
    ])


def _is_towing_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "abschleppen",
        "abschleppdienst",
        "panne",
        "liegen geblieben",
    ])


# =========================================================
# REPLIES
# =========================================================

def _reply_opening_hours() -> str:
    return (
        "Unsere Öffnungszeiten sind aktuell:\n"
        "- Montag bis Freitag: 08:00 – 17:00\n"
        "- Samstag: nach Vereinbarung\n\n"
        "Für Notfälle können Sie uns auch außerhalb der Zeiten kontaktieren."
    )


def _reply_location() -> str:
    return (
        "Unsere Werkstatt befindet sich in Ihrer Region.\n"
        "Die genaue Adresse erhalten Sie bei Terminvereinbarung oder auf Anfrage."
    )


def _reply_contact() -> str:
    return (
        "Sie können uns telefonisch oder direkt über diesen Chat erreichen.\n"
        "Wenn Sie möchten, kann ich auch direkt ein Ticket für Sie anlegen."
    )


def _reply_service() -> str:
    return (
        "Wir bieten unter anderem:\n"
        "- Diagnose von Fahrzeugproblemen\n"
        "- Reparaturen\n"
        "- Wartung und Service\n"
        "- Unterstützung bei Notfällen\n\n"
        "Beschreiben Sie einfach Ihr Problem, ich helfe Ihnen direkt weiter."
    )


def _reply_price() -> str:
    return (
        "Die Kosten hängen stark vom Problem und Fahrzeug ab.\n"
        "Am besten beschreiben Sie kurz Ihr Anliegen – dann kann ich eine Einschätzung geben."
    )


def _reply_towing() -> str:
    return (
        "Wenn Ihr Fahrzeug nicht fahrbereit ist, können wir auch einen Abschleppdienst organisieren.\n"
        "Erstellen Sie einfach ein Ticket, dann kümmern wir uns darum."
    )


def _reply_fallback() -> str:
    return (
        "Ich helfe Ihnen gerne weiter.\n\n"
        "Sie können:\n"
        "- ein neues Problem melden\n"
        "- nach einem bestehenden Ticket fragen\n"
        "- oder eine allgemeine Frage stellen\n\n"
        "Wie kann ich Ihnen helfen?"
    )


# =========================================================
# MAIN HANDLER
# =========================================================

def handle_general_question(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:

    if user_message is None or normalize(user_message) == "":
        return state, _reply_fallback(), False

    msg = normalize(user_message)

    if _is_opening_hours_question(msg):
        return state, _reply_opening_hours(), False

    if _is_location_question(msg):
        return state, _reply_location(), False

    if _is_contact_question(msg):
        return state, _reply_contact(), False

    if _is_service_question(msg):
        return state, _reply_service(), False

    if _is_price_question(msg):
        return state, _reply_price(), False

    if _is_towing_question(msg):
        return state, _reply_towing(), False

    return state, _reply_fallback(), False