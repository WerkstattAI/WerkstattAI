from __future__ import annotations

import re

from app.conversation.extractors import (
    can_extract_vehicle, extract_km, extract_name_candidate, extract_phone,
    extract_year, has_problem_content, is_correction, normalize,
    strip_request_announcement, infer_fahrbereit_from_text,
)
from app.models import IntakeState


PHONE_LABEL = r"\b(?:meine?\s+)?(?:telefonnummer|telefon|tel|handy|mobil|rufnummer|nummer)\b"
PROBLEM_START = (
    r"\b(?:inspektion|service|wartung|kundendienst|[oö]lwechsel|oelwechsel|"
    r"reifenwechsel|räderwechsel|raederwechsel|tüv|tuev|hu|au|"
    r"springt|startet|stinkt|ruckel\w*|warnlampe|motorkontrollleuchte|"
    r"geräusch\w*|geraeusch\w*|rauch\w*|qualm\w*|kaputt|"
    r"verliert|stoppt|macht komische|geht nicht|motor geht aus)\b"
)


def extract_intake_fields(text: str, *, vehicle_answer: bool = False) -> dict[str, str]:
    """Separate unambiguous inline facts; keep unknown make/model spellings.

    Unlabelled names are accepted only by the name step. A free vehicle answer
    is accepted only when asked for one, or when accompanied by vehicle facts.
    """
    content, _ = strip_request_announcement(text)
    content = re.sub(
        r"^(?:(?:sorry|entschuldigung|nein|korrektur)[,:]?\s*)*"
        r"(?:(?:ich )?(?:meinte|mein fahrzeug ist|mein auto ist)|"
        r"(?:das )?(?:richtige|neue) fahrzeug(?: ist)?|fahrzeug\s*:)\s*",
        "", content, flags=re.I,
    )
    fields: dict[str, str] = {}
    fahrbereit = infer_fahrbereit_from_text(content)
    if fahrbereit:
        fields["fahrbereit"] = fahrbereit
    phone = extract_phone(content)
    phone_label = re.search(PHONE_LABEL, content, re.I)
    if phone and (phone_label or re.fullmatch(r"\+?[\d ()/.-]+", content)):
        fields["telefon"] = phone
    # Exclude phone and name spans from all vehicle-number extraction.
    facts = content[:phone_label.start()] if phone_label else content
    name_label = re.search(r"\b(?:mein name ist|ich heiße|ich heisse|name\s*:)\s*(.+?)(?=\s+" + PHONE_LABEL + r"|$)", content, re.I)
    if name_label:
        name = extract_name_candidate(name_label[1].strip(" ,.;"))
        if name:
            fields["name"] = name
        facts = facts[:name_label.start()]
    if re.fullmatch(r"\+?[\d ()/.-]+", facts) and phone:
        return fields
    year = extract_year(facts)
    km = extract_km(facts)
    if year:
        fields["baujahr"] = year
    if km:
        fields["kilometerstand"] = km

    problem_match = re.search(PROBLEM_START, facts, re.I)
    if problem_match and has_problem_content(facts):
        # Pure symptoms should retain their subject and context.
        prefix = facts[:problem_match.start()]
        if re.search(r"\b(?:auto|wagen|karre|motor|aus dem|mein|meine|beim|die|der|kein\w*|ohne|nicht)\b", prefix, re.I):
            problem = facts
        else:
            problem = facts[problem_match.start():]
        fields["problem"] = problem.strip(" ,.;")
        vehicle_part = prefix
    else:
        vehicle_part = facts
        if has_problem_content(facts):
            fields["problem"] = facts.strip(" ,.;")
            vehicle_part = ""

    # Remove data labels and conversational padding, not a fixed make list.
    vehicle_part = re.sub(r"\b(?:19|20)\d{2}\b", "", vehicle_part)
    vehicle_part = re.sub(r"\b\d[\d. ]*\s*(?:km|tkm|k)\b|\b\d{5,7}\b", "", vehicle_part, flags=re.I)
    vehicle_part = re.sub(r"\b(?:bj|baujahr|erstzulassung|ez|kilometerstand|km)\b\s*[:=]?", "", vehicle_part, flags=re.I)
    vehicle_part = re.sub(r"^(?:hallo|moin|guten tag|ich fahre|mein auto ist|mein fahrzeug ist|fahrzeug)\s*[:,]?\s*", "", vehicle_part, flags=re.I)
    vehicle_part = re.sub(r"\b(?:braucht|brauche|benötigt|benoetigt|bitte|und|hat|mit)\s*$", "", vehicle_part.strip(" ,.;"), flags=re.I)
    vehicle_part = normalize(vehicle_part).strip(" ,.;")
    if (vehicle_answer or year or km) and can_extract_vehicle(vehicle_part):
        fields["fahrzeug"] = vehicle_part
    elif problem_match and "problem" in fields:
        fields["problem"] = facts.strip(" ,.;")
    return fields


def consume_intake_fields(state: IntakeState, text: str, *, vehicle_answer: bool = False) -> tuple[set[str], bool]:
    fields = extract_intake_fields(text, vehicle_answer=vehicle_answer)
    correction = is_correction(text)
    if correction and "fahrzeug" in fields and state.step not in {
        "fahrzeug", "quote_fahrzeug", "baujahr", "kilometerstand",
    } and not ("baujahr" in fields or "kilometerstand" in fields):
        # 'Sorry, meinte Max' at the name step must not replace the vehicle.
        # Vehicle hints resolve explicit cross-field corrections; this is a hint
        # for ambiguous corrections, never a make/model validation allowlist.
        from app.conversation.intent import looks_like_vehicle_intake_start
        candidate = fields["fahrzeug"]
        if not looks_like_vehicle_intake_start(candidate):
            fields.pop("fahrzeug")
            if state.step in {"name", "quote_name"}:
                name = extract_name_candidate(candidate)
                if name:
                    fields["name"] = name
    if state.step == "kilometerstand" and not re.search(PHONE_LABEL, text, re.I):
        fields.pop("telefon", None)
    changed = set()
    for field, value in fields.items():
        if correction or not getattr(state, field):
            if getattr(state, field) != value:
                setattr(state, field, value)
                changed.add(field)
    return changed, correction
