from __future__ import annotations

from typing import Tuple

from app.conversation.extractors import lower, normalize
from app.models import IntakeState
from app.workshops import get_workshop


# =========================================================
# INTENT HELPERS
# =========================================================

def _is_opening_hours_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "oeffnungszeiten",
        "offnungszeiten",
        "öffnungszeiten",
        "wann offen",
        "wann habt ihr offen",
        "habt ihr offen",
        "offen",
        "samstag",
        "samstags",
        "wann geöffnet",
        "wann geoeffnet",
        "opening hours",
    ])


def _is_location_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "adresse",
        "wo seid ihr",
        "wo ist eure werkstatt",
        "wo ist die werkstatt",
        "wo finde ich euch",
        "wo findet man euch",
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
        "e-mail",
        "wie erreichen",
    ])


def _is_service_question(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in [
        "was macht ihr",
        "leistungen",
        "service",
        "repariert ihr",
        "reparaturen",
        "was könnt ihr",
        "was koennt ihr",
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

def _split_semicolon_list(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def _split_comma_list(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _reply_opening_hours(workshop: dict) -> str:
    opening_hours = _split_semicolon_list(workshop.get("opening_hours"))
    if not opening_hours:
        return "Die Öffnungszeiten sind aktuell noch nicht hinterlegt."

    lines = [f"Die Öffnungszeiten von {workshop.get('name') or 'der Werkstatt'} sind:"]
    lines.extend(f"- {item}" for item in opening_hours)
    return "\n".join(lines)


def _reply_location(workshop: dict) -> str:
    return (
        f"{workshop.get('name') or 'Unsere Werkstatt'} befindet sich hier:\n"
        f"{workshop.get('address') or 'Adresse noch nicht hinterlegt'}"
    )


def _reply_contact(workshop: dict) -> str:
    return (
        f"Sie erreichen {workshop.get('name') or 'unsere Werkstatt'} so:\n"
        f"- Telefon: {workshop.get('phone') or '-'}\n"
        f"- E-Mail: {workshop.get('email') or '-'}\n"
        "Sie können Ihr Anliegen auch direkt hier im Chat beschreiben."
    )


def _reply_service(workshop: dict) -> str:
    services = _split_comma_list(workshop.get("services"))
    if not services:
        return "Die Leistungen der Werkstatt sind aktuell noch nicht hinterlegt."

    lines = [f"{workshop.get('name') or 'Unsere Werkstatt'} bietet unter anderem:"]
    lines.extend(f"- {service}" for service in services)
    lines.append("")
    lines.append("Beschreiben Sie einfach Ihr Anliegen, dann helfen wir Ihnen weiter.")
    return "\n".join(lines)


def _reply_price(workshop: dict) -> str:
    return (
        workshop.get("pricing_info")
        or "Die Kosten hängen stark vom Fahrzeug und vom konkreten Anliegen ab."
    )


def _reply_towing(workshop: dict) -> str:
    return (
        workshop.get("towing_info")
        or "Informationen zum Abschleppdienst sind aktuell noch nicht hinterlegt."
    )


def _reply_fallback() -> str:
    return (
        "Ich helfe Ihnen gerne weiter.\n\n"
        "Sie können:\n"
        "- ein Problem melden\n"
        "- eine Anfrage zu einem bestehenden Ticket stellen\n"
        "- einen Kostenvoranschlag anfragen\n"
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
    state.mode = "general"
    workshop = get_workshop(getattr(state, "workshop_id", None))

    if _is_opening_hours_question(msg):
        return state, _reply_opening_hours(workshop), False

    if _is_location_question(msg):
        return state, _reply_location(workshop), False

    if _is_contact_question(msg):
        return state, _reply_contact(workshop), False

    if _is_service_question(msg):
        return state, _reply_service(workshop), False

    if _is_price_question(msg):
        return state, _reply_price(workshop), False

    if _is_towing_question(msg):
        return state, _reply_towing(workshop), False

    return state, _reply_fallback(), False
