from __future__ import annotations

import re
from dataclasses import dataclass

from app.conversation.extractors import (
    can_extract_vehicle, extract_km, extract_name_candidate, extract_phone,
    extract_km_fact, find_year, has_problem_content, is_correction, is_vehicle_correction, normalize,
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
    content = re.sub(r"^(?:(?:sorry|entschuldigung)[,:]?\s*)+", "", content, flags=re.I)
    content = re.sub(
        r"^(?:(?:sorry|entschuldigung|nein|korrektur)[,:]?\s*)*"
        r"(?:(?:ich )?(?:meinte|mein fahrzeug ist|mein auto ist)|es ist|das ist|ich fahre|"
        r"(?:das )?(?:richtige|neue) fahrzeug(?: ist)?|fahrzeug\s*:)\s*",
        "", content, flags=re.I,
    )
    content = re.sub(r"^(?:ein|eine|einen)\s+", "", content, flags=re.I)
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

    km_fact = extract_km_fact(vehicle_part)
    year_match = find_year(vehicle_part)
    # One year-shaped number directly after a make could be the model. Keep
    # that vehicle text and ask for the missing year instead of guessing.
    if year_match and year_match.start() == year_match.start(1):
        prefix = normalize(vehicle_part[:year_match.start()]).strip(" ,.;")
        if len(prefix.split()) == 1 and not re.search(r"\d", prefix):
            from app.conversation.intent import looks_like_vehicle_intake_start
            if looks_like_vehicle_intake_start(prefix):
                year_match = None
    spans = []
    if year_match:
        fields["baujahr"] = year_match[1]
        spans.append(year_match.span())
    if km_fact:
        fields["kilometerstand"] = km_fact[0]
        spans.append(km_fact[1])
    for start, end in sorted(spans, reverse=True):
        vehicle_part = vehicle_part[:start] + " " + vehicle_part[end:]

    # Remove data labels and conversational padding, not a fixed make list.
    vehicle_part = re.sub(r"\b(?:bj|baujahr|erstzulassung|ez|kilometerstand|km)\b\s*[:=]?", "", vehicle_part, flags=re.I)
    vehicle_part = re.sub(r"^(?:hallo|moin|guten tag|ich fahre|mein auto ist|mein fahrzeug ist|fahrzeug)\s*[:,]?\s*(?:(?:ein|eine|einen)\s+)?", "", vehicle_part, flags=re.I)
    vehicle_part = re.sub(r"\b(?:braucht|brauche|benötigt|benoetigt|bitte|und|hat|mit)\s*$", "", vehicle_part.strip(" ,.;"), flags=re.I)
    vehicle_part = normalize(vehicle_part).strip(" ,.;")
    if (vehicle_answer or year_match or km_fact) and can_extract_vehicle(vehicle_part):
        fields["fahrzeug"] = vehicle_part
    elif problem_match and "problem" in fields:
        fields["problem"] = facts.strip(" ,.;")
    return fields


@dataclass
class IntakeFieldUpdate:
    recognized: set[str]
    changed: set[str]
    correction: bool


def consume_intake_fields(state: IntakeState, text: str, *, vehicle_answer: bool = False) -> IntakeFieldUpdate:
    fields = extract_intake_fields(text, vehicle_answer=vehicle_answer or state.pending_vehicle_correction)
    if state.step in {"telefon", "quote_telefon"} and "telefon" not in fields:
        # At the contact step a valid phone is the expected answer, including
        # a short apology/preamble that is not itself a correction target.
        phone = extract_phone(text)
        if phone:
            fields["telefon"] = phone
    correction = is_correction(text) or state.pending_vehicle_correction
    if correction and "fahrzeug" in fields and state.step not in {
        "fahrzeug", "quote_fahrzeug", "baujahr", "kilometerstand",
    } and not ("baujahr" in fields or "kilometerstand" in fields):
        # 'Sorry, meinte Max' at the name step must not replace the vehicle.
        # Vehicle hints resolve explicit cross-field corrections; this is a hint
        # for ambiguous corrections, never a make/model validation allowlist.
        from app.conversation.intent import looks_like_vehicle_intake_start
        candidate = fields["fahrzeug"]
        explicit_vehicle = re.search(r"\b(?:fahrzeug|auto)\s*(?:ist|:)", text, re.I)
        if not (explicit_vehicle or state.pending_vehicle_correction) and not looks_like_vehicle_intake_start(candidate):
            fields.pop("fahrzeug")
            if state.step in {"name", "quote_name"} and not is_vehicle_correction(text):
                name = extract_name_candidate(candidate)
                if name:
                    fields["name"] = name
    if "fahrzeug" in fields:
        state.pending_vehicle_correction = False
    elif is_vehicle_correction(text) and not ({"problem", "telefon", "name"} & fields.keys()):
        state.pending_vehicle_correction = True
    if state.step == "kilometerstand" and not re.search(PHONE_LABEL, text, re.I):
        fields.pop("telefon", None)
    if state.kilometerstand and re.fullmatch(r"\d{1,7}|\d{1,3}(?:[.\s]\d{3})+", normalize(text)):
        # Repeating a low unlabelled odometer after advancing to the problem
        # step is still a data answer, including alternate separator formats.
        if state.kilometerstand == extract_km(text, expected=True):
            fields["kilometerstand"] = state.kilometerstand
    changed = set()
    for field, value in fields.items():
        if correction or not getattr(state, field):
            if getattr(state, field) != value:
                setattr(state, field, value)
                changed.add(field)
    return IntakeFieldUpdate(set(fields), changed, correction)
