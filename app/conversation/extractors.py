from __future__ import annotations

import re

from app.models import IntakeState


def normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def lower(text: str) -> str:
    return normalize(text).lower()


def extract_year(text: str) -> str | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def extract_km(text: str) -> str | None:
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

    m = re.search(r"\b(\d{2,3})\s*(k|tkm)\b", t)
    if m:
        return str(int(m.group(1)) * 1000)

    m = re.search(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{5,7})\s*km\b", t)
    if m:
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if 4 <= len(digits) <= 7:
            return digits

    m = re.search(r"\b\d{5,7}\b", t)
    if m:
        return m.group(0)

    return None


def extract_phone(text: str) -> str | None:
    raw = normalize(text)
    digits = re.findall(r"\d", raw)
    if len(digits) < 7:
        return None

    cleaned = re.sub(r"[^\d+]", "", raw)
    cleaned = re.sub(r"(?!^)\+", "", cleaned)

    only_digits = re.sub(r"\D", "", cleaned)
    if len(only_digits) < 7:
        return None

    return cleaned


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

    if extract_phone(t):
        return None

    if extract_year(t):
        return None

    km = extract_km(t)
    if km and re.sub(r"\D", "", t) == km:
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
        "noch fahrbar",
        "weiterfahren möglich",
        "weiterfahren moeglich",
        "ich fahre noch damit",
    ]
    if any(p in t for p in positive_patterns):
        return "ja"

    return None


def can_extract_vehicle(text: str) -> bool:
    t = normalize(text)
    if len(t) < 3:
        return False

    if extract_phone(t):
        return False

    pure_digits = re.sub(r"\D", "", t)
    if pure_digits and len(pure_digits) == len(t.replace(" ", "")):
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