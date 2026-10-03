from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.conversation.constants import CANCEL_VALUES, SKIP_VALUES
from app.models import IntakeState


def normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def lower(text: str) -> str:
    return re.sub(r"\bnich\b", "nicht", normalize(text).lower())


def is_cancel_command(text: str) -> bool:
    t = lower(text).strip(" .!?")
    return t in CANCEL_VALUES or bool(re.fullmatch(r"(?:bitte )?(?:abbrechen|stop|stopp|stoppen)(?: bitte)?", t))


def is_unavailable_answer(text: str) -> bool:
    t = lower(text).strip(" .!?")
    return t in SKIP_VALUES - {"nein", "egal"} or bool(re.fullmatch(
        r"(?:ich )?(?:weiß|weiss) (?:ich )?(?:es |das )?nicht|keine ahnung|"
        r"(?:ich )?kann (?:gerade |jetzt |aktuell )?nicht (?:nachschauen|nachsehen)|"
        r"(?:habe|hab) ich (?:gerade )?nicht (?:da|zur hand)", t
    ))


def strip_request_announcement(text: str) -> tuple[str, bool]:
    """Allow small typos in a reporting preamble; keep any concrete remainder."""
    t = normalize(text)
    match = re.match(
        r"^(?:(?:hallo|moin|guten tag)[,!]?\s+)?"
        r"(?:(?:ich\s+)?(?:wollte|will|möchte|moechte|würde gerne?|wuerde gerne?)\s+)?"
        r"(?:ein(?:e[nms]?)?\s+(?:neue[nms]?\s+)?)?(\w+)\s+melden\b[\s,.:;!-]*", t, re.I
    )
    if match and SequenceMatcher(None, match[1].lower(), "problem").ratio() >= 0.8:
        return t[match.end():].strip(), True
    match = re.match(r"^(?:neues (?:problem|anliegen)|neue (?:meldung|anfrage))\b[\s,.:;!-]*", t, re.I)
    if match:
        return t[match.end():].strip(), True
    match = re.fullmatch(r"(?:ich )?(?:habe|hab) (?:ein |ein kleines )?(\w+)[.!?]*", t, re.I)
    if match and SequenceMatcher(None, match[1].lower(), "problem").ratio() >= 0.8:
        return "", True
    return t, False


def is_correction(text: str) -> bool:
    return bool(re.search(
        r"\b(?:sorry|entschuldigung|meinte|korrektur|korrigier\w*|falsch\w*|statt|richtigstellung)\b",
        lower(text),
    ))


def extract_year(text: str) -> str | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def extract_km(text: str, *, expected: bool = False) -> str | None:
    """
    Sehr tolerante Kilometerstand-Erkennung:
    - 180000
    - 180.000
    - 180 000
    - 180k
    - 180 tkm
    - 180.000 km

    WICHTIG:
    - Reine 4-stellige Zahlen wie 2014 sollen NICHT als Kilometerstand gelten,
      weil das meistens ein Baujahr ist.
    """
    t = lower(text)

    if expected and re.fullmatch(r"\d{1,7}|\d{1,3}(?:[.\s]\d{3})+", t):
        return str(int(re.sub(r"\D", "", t)))

    m = re.search(r"\b(\d{2,3})\s*(k|tkm)\b", t)
    if m:
        return str(int(m.group(1)) * 1000)

    m = re.search(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{1,7})\s*km\b", t)
    if m:
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if 1 <= len(digits) <= 7:
            return str(int(digits))

    m = re.search(r"\b\d{1,3}(?:\.\d{3})+\b", t)
    if m:
        return str(int(m[0].replace(".", "")))

    m = re.search(r"\b\d{5,7}\b", t)
    if m:
        return m.group(0)

    return None


def extract_phone(text: str) -> str | None:
    """Extract one phone span, without joining vehicle numbers to it."""
    raw = normalize(text)
    label = re.search(r"\b(?:telefonnummer|telefon|tel|handy|mobil|rufnummer|nummer)\b\s*(?:ist|lautet)?\s*[:=.]?\s*", raw, re.I)
    if label:
        raw = raw[label.end():]
    elif not re.fullmatch(r"\+?[\d ()/.-]+", raw):
        raw = re.sub(r"\b(?:19|20)\d{2}\b", " ", raw)
        raw = re.sub(r"\b\d[\d. ]*\s*(?:km|tkm|k)\b", " ", raw, flags=re.I)
    for match in re.finditer(r"(?<!\w)\+?\d[\d ()/.-]*\d(?!\w)", raw):
        candidate = re.sub(r"[^\d+]", "", match[0])
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            return candidate
    return None


def cleanup_vehicle_text(text: str) -> str:
    t = normalize(text)

    year = extract_year(t)
    if year:
        t = re.sub(rf"\b{re.escape(year)}\b", "", t)

    t = re.sub(r"\b\d{2,3}\s*(k|tkm)\b", "", t, flags=re.I)
    t = re.sub(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{5,7})\s*km\b", "", t, flags=re.I)
    t = re.sub(r"\b\d{5,7}\b", "", t)

    t = re.sub(r"[,\-_/]+", " ", t)
    t = normalize(t)
    return t


def extract_name_candidate(text: str) -> str | None:
    t = normalize(text)
    tl = t.lower()

    if tl in {"überspringen", "ueberspringen", "skip", "egal", "nein"}:
        return None

    if len(t) < 2:
        return None

    if is_cancel_command(t) or is_unavailable_answer(t) or is_correction(t):
        return None

    if extract_phone(t):
        return None

    if extract_year(t):
        return None

    km = extract_km(t)
    if km and re.sub(r"\D", "", t) == km:
        return None

    t = re.sub(r"^(?:mein name ist|ich heiße|ich heisse|ich bin|name\s*:?)\s*", "", t, flags=re.I)
    if not re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+){0,5}", t, re.UNICODE):
        return None
    title_name = len(t.split()) >= 2 and all(word[0].isupper() for word in t.split())
    from app.conversation.analysis import analyze_problem
    flags = analyze_problem(t)["flags"]
    service_name = title_name and flags["service_request"] and not any(
        value for key, value in flags.items() if key != "service_request"
    ) and any(not has_problem_content(word) for word in t.split())
    if (has_problem_content(t) and not service_name) or re.search(r"\b(?:nummer|telefon|nicht|kein|bitte)\b", lower(t)):
        return None
    return t[:60]


def infer_fahrbereit_from_text(text: str) -> str | None:
    t = lower(text)

    negative_patterns = [
        "nicht fahrbereit",
        "fährt nicht",
        "faehrt nicht",
        "springt nicht an",
        "springt nicht mehr an",
        "startet nicht",
        "startet nicht mehr",
        "geht nicht an",
        "liegen geblieben",
        "bleibt liegen",
        "motor geht aus",
        "auto steht",
        "kann nicht fahren",
        "nicht mehr fahrbar",
        "fahrzeug steht",
    ]
    if any(p in t for p in negative_patterns):
        return "nein"

    positive_patterns = [
        "fahrbereit",
        "ich kann noch fahren",
        "auto fährt noch",
        "auto faehrt noch",
        "fährt noch",
        "faehrt noch",
        "noch fahrbar",
        "weiterfahren möglich",
        "weiterfahren moeglich",
        "ich fahre noch damit",
    ]
    if any(p in t for p in positive_patterns):
        return "ja"

    return None


def has_problem_content(text: str) -> bool:
    # Delayed import avoids a dependency cycle with analysis.
    from app.conversation.analysis import analyze_problem
    if any(analyze_problem(text)["flags"].values()):
        return True
    return bool(re.search(r"\b(?:stinkt|leuchtet|stoppt|geht nicht|macht komische)\b", lower(text)))


def can_extract_vehicle(text: str) -> bool:
    t = normalize(text)
    tl = t.lower()

    if len(t) < 3:
        return False

    if is_cancel_command(t) or is_unavailable_answer(t) or strip_request_announcement(t)[1]:
        return False
    if has_problem_content(t):
        return False
    if is_correction(t) or re.search(r"\b(?:baujahr|kilometerstand|nummer|telefon|ist|falsch|richtig)\b", lower(t)):
        return False
    if re.search(r"\b(?:ich|mein|meine|brauch\w*|nur|nein|ja|jo|kein\w*|aus|dem|kommt|motor)\b", lower(t)):
        return False
    if re.search(
        r"\b(?:auto|wagen|karre|fahrzeug|macht|geht|springt|startet|stoppt|"
        r"komisch\w*|stark\w*|ungewöhnlich\w*|seltsam\w*|laut\w*|"
        r"blau\w*|weiß\w*|weiss\w*|schwarz\w*|viel|etwas|es|habe|hab)\b",
        lower(t),
    ):
        return False
    if lower(t) in {"auto", "wagen", "karre", "fahrzeug", "hallo", "moin", "danke"}:
        return False

    if "?" in t:
        return False

    pure_digits = re.sub(r"\D", "", t)
    if pure_digits and len(pure_digits) == len(t.replace(" ", "")):
        return False

    blocked_phrases = [
        "ich möchte",
        "ich moechte",
        "problem melden",
        "allgemeine frage",
        "anfrage zu einem bestehenden ticket",
        "bestehendes ticket",
        "öffnungszeiten",
        "oeffnungszeiten",
        "wann habt ihr offen",
        "wie sind eure",
        "status von ticket",
        "ticket",
        "hilfe",
        "kontakt",
        "adresse",
        "kosten",
        "preis",
        "springt nicht an",
        "startet nicht",
        "geht nicht an",
        "warnlampe",
        "motorkontrollleuchte",
        "geräusch",
        "geraeusch",
        "stinkt",
        "ruckelt",
        "reparatur",
        "inspektion",
        "oelwechsel",
        "ölwechsel",
        "reifenwechsel",
    ]
    if any(phrase in tl for phrase in blocked_phrases):
        return False

    has_vehicle_context = bool(extract_year(t) or extract_km(t))
    if extract_phone(t) and not has_vehicle_context:
        return False

    return True


def consume_inline_vehicle_year_km(state: IntakeState, text: str) -> None:
    t = normalize(text)

    if not getattr(state, "fahrzeug", None) and can_extract_vehicle(t):
        fahrzeug = cleanup_vehicle_text(t)
        if len(fahrzeug) >= 3:
            state.fahrzeug = fahrzeug

    if not getattr(state, "baujahr", None):
        year = extract_year(t)
        if year:
            state.baujahr = year

    if not getattr(state, "kilometerstand", None):
        km = extract_km(t)
        if km:
            state.kilometerstand = km
