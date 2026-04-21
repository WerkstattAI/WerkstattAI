from __future__ import annotations

from typing import List, TypedDict

from app.conversation.constants import (
    PRIORITY_HOCH,
    PRIORITY_NIEDRIG,
    PRIORITY_NORMAL,
    REQUEST_TYPE_DIAGNOSE,
    REQUEST_TYPE_NOTFALL,
    REQUEST_TYPE_SERVICE,
)
from app.conversation.extractors import lower


# =========================================================
# Typing
# =========================================================

class ProblemFlags(TypedDict):
    service_request: bool
    start_problem: bool
    not_drivable_hint: bool
    critical_brake_or_steering: bool
    overheat: bool
    smoke_or_steam: bool
    red_warning: bool
    warning_light: bool
    noise: bool
    performance_issue: bool
    fluid_leak: bool
    generic_problem: bool


class AnalysisResult(TypedDict):
    request_type: str
    priority: str
    score: int
    flags: ProblemFlags


# =========================================================
# Keyword-Listen
# =========================================================

SERVICE_KEYWORDS = [
    "service",
    "inspektion",
    "wartung",
    "kundendienst",
    "ölwechsel",
    "oelwechsel",
    "klimaservice",
    "reifenwechsel",
    "räderwechsel",
    "raederwechsel",
    "sommerreifen",
    "winterreifen",
    "reifen montieren",
    "reifen umziehen",
    "bremsenservice",
    "hu",
    "au",
    "tüv",
    "tuev",
]

DIAGNOSE_HINTS = [
    "geräusch",
    "geraeusch",
    "klopf",
    "quiets",
    "schleif",
    "pfeif",
    "brumm",
    "ruckel",
    "leistung",
    "warnlampe",
    "fehlermeldung",
    "leuchtet",
    "verliert öl",
    "verliert oel",
    "ölverlust",
    "oelverlust",
    "problem",
    "defekt",
    "funktioniert nicht",
    "motorlampe",
    "check engine",
]

START_HINTS = [
    "springt nicht an",
    "springt nicht mehr an",
    "startet nicht",
    "startet nicht mehr",
    "anlasser",
    "batterie leer",
    "klickt nur",
    "kein strom",
]

BRAKE_HINTS = [
    "bremse ohne wirkung",
    "bremsen funktionieren nicht",
    "bremsen greifen nicht",
    "bremsproblem",
    "bremsenproblem",
]

STEERING_HINTS = [
    "lenkung schwer",
    "lenkrad schwer",
    "lenkung blockiert",
    "lenkproblem",
]

OVERHEAT_HINTS = [
    "überhitz",
    "ueberhitz",
    "temperatur zu hoch",
    "motor wird heiß",
    "motor wird heiss",
    "kühlmittelverlust",
    "kuehlmittelverlust",
    "dampf",
]

SMOKE_HINTS = [
    "rauch",
    "qualm",
]

RED_WARNING_HINTS = [
    "rote warnlampe",
    "warnlampe rot",
    "rote lampe",
    "öldruck",
    "oeldruck",
    "batterielampe rot",
    "temperaturwarnung",
]

WARNING_HINTS = [
    "warnlampe",
    "fehlermeldung",
    "check engine",
    "motorkontrollleuchte",
    "motorlampe",
    "abs",
    "esp",
    "airbag",
]

DRIVEABILITY_HINTS = [
    "nicht fahrbereit",
    "nicht mehr fahrbar",
    "bleibt liegen",
    "liegen geblieben",
    "motor geht aus",
    "auto steht",
]

NOISE_HINTS = [
    "geräusch",
    "geraeusch",
    "klopf",
    "quiets",
    "schleif",
    "pfeif",
    "brumm",
]

PERFORMANCE_HINTS = [
    "ruckel",
    "keine leistung",
    "leistungsverlust",
    "zieht nicht",
    "nimmt kein gas an",
]

LEAK_HINTS = [
    "ölverlust",
    "oelverlust",
    "verliert öl",
    "verliert oel",
    "leck",
]


# =========================================================
# Kleine Helpers
# =========================================================

def contains_any(text: str, keywords: List[str]) -> bool:
    t = lower(text)
    return any(k in t for k in keywords)


def contains_all(text: str, keywords: List[str]) -> bool:
    t = lower(text)
    return all(k in t for k in keywords)


# =========================================================
# Analyse-Helfer
# =========================================================

def is_service_request(text: str) -> bool:
    t = lower(text)

    if contains_any(t, SERVICE_KEYWORDS):
        return True

    if contains_all(t, ["reifen", "wechsel"]):
        return True

    if contains_all(t, ["öl", "wechsel"]) or contains_all(t, ["oel", "wechsel"]):
        return True

    if contains_all(t, ["bremsen", "wechsel"]) or contains_all(t, ["bremsbeläge", "wechsel"]):
        return True

    return False


def has_start_problem(text: str) -> bool:
    t = lower(text)
    return any(k in t for k in START_HINTS) or (
        ("springt" in t and "nicht" in t and "an" in t)
        or ("startet" in t and "nicht" in t)
    )


def has_critical_brake_or_steering(text: str) -> bool:
    t = lower(text)

    brake_critical = any(k in t for k in BRAKE_HINTS) or (
        "brems" in t and any(k in t for k in ["zieht", "seite", "stark", "schief", "problem", "weich"])
    )

    steering_critical = any(k in t for k in STEERING_HINTS) or (
        ("lenk" in t or "lenkrad" in t)
        and any(k in t for k in ["zieht", "schief", "block", "schwer", "problem", "seite"])
    )

    return brake_critical or steering_critical


def build_problem_flags(text: str) -> ProblemFlags:
    t = lower(text)

    flags: ProblemFlags = {
        "service_request": is_service_request(t),
        "start_problem": has_start_problem(t),
        "not_drivable_hint": any(k in t for k in DRIVEABILITY_HINTS),
        "critical_brake_or_steering": has_critical_brake_or_steering(t),
        "overheat": any(k in t for k in OVERHEAT_HINTS),
        "smoke_or_steam": any(k in t for k in SMOKE_HINTS),
        "red_warning": any(k in t for k in RED_WARNING_HINTS),
        "warning_light": any(k in t for k in WARNING_HINTS),
        "noise": any(k in t for k in NOISE_HINTS),
        "performance_issue": any(k in t for k in PERFORMANCE_HINTS),
        "fluid_leak": any(k in t for k in LEAK_HINTS),
        "generic_problem": any(k in t for k in ["problem", "defekt", "funktioniert nicht"]),
    }

    return flags


# =========================================================
# Hauptanalyse
# =========================================================

def analyze_problem(
    problem_text: str,
    fahrbereit: str | None = None,
    abschleppdienst: str | None = None,
) -> AnalysisResult:
    """
    returns {
        "request_type": "service" | "diagnose" | "notfall",
        "priority": "niedrig" | "normal" | "hoch",
        "score": int,
        "flags": {...}
    }
    """
    flags = build_problem_flags(problem_text)
    score = 0

    if flags["start_problem"]:
        score += 5

    if flags["not_drivable_hint"]:
        score += 5

    if flags["critical_brake_or_steering"]:
        score += 5

    if flags["overheat"]:
        score += 5

    if flags["smoke_or_steam"]:
        score += 4

    if flags["red_warning"]:
        score += 4

    if flags["warning_light"]:
        score += 2

    if flags["performance_issue"]:
        score += 2

    if flags["noise"]:
        score += 2

    if flags["fluid_leak"]:
        score += 2

    if flags["generic_problem"]:
        score += 1

    if fahrbereit == "nein":
        score += 5

    if abschleppdienst == "ja":
        score += 2

    service_only = (
        flags["service_request"]
        and not flags["start_problem"]
        and not flags["not_drivable_hint"]
        and not flags["critical_brake_or_steering"]
        and not flags["overheat"]
        and not flags["smoke_or_steam"]
        and not flags["red_warning"]
        and not flags["warning_light"]
        and not flags["performance_issue"]
        and not flags["noise"]
        and not flags["fluid_leak"]
        and not flags["generic_problem"]
    )

    hard_notfall = any(
        [
            flags["start_problem"],
            flags["not_drivable_hint"],
            flags["critical_brake_or_steering"],
            flags["overheat"],
        ]
    )

    if service_only:
        request_type = REQUEST_TYPE_SERVICE
    elif hard_notfall:
        request_type = REQUEST_TYPE_NOTFALL
    else:
        request_type = REQUEST_TYPE_DIAGNOSE

    if service_only:
        priority = PRIORITY_NIEDRIG
    elif score >= 6:
        priority = PRIORITY_HOCH
    elif score >= 3:
        priority = PRIORITY_NORMAL
    else:
        priority = PRIORITY_NIEDRIG

    if request_type == REQUEST_TYPE_NOTFALL:
        priority = PRIORITY_HOCH

    result: AnalysisResult = {
        "request_type": request_type,
        "priority": priority,
        "score": score,
        "flags": flags,
    }
    return result


def detect_request_type(text: str) -> str:
    return analyze_problem(text)["request_type"]


def detect_priority(
    text: str,
    request_type: str | None = None,
    fahrbereit: str | None = None,
    abschleppdienst: str | None = None,
) -> str:
    return analyze_problem(
        text,
        fahrbereit=fahrbereit,
        abschleppdienst=abschleppdienst,
    )["priority"]