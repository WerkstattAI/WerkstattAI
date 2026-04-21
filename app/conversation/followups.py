from __future__ import annotations

from typing import List

from app.conversation.analysis import analyze_problem
from app.conversation.constants import (
    REQUEST_TYPE_NOTFALL,
    REQUEST_TYPE_SERVICE,
)
from app.conversation.extractors import lower


# =========================================================
# Frage-Pools
# =========================================================

FOLLOWUP_POOL = {
    "since_when": "Seit wann besteht das Problem ungefähr?",
    "sporadic": "Tritt das Problem ständig auf oder nur sporadisch?",
    "warning_lamps": "Leuchtet eine Warnlampe oder gibt es eine Fehlermeldung im Display? Wenn ja, welche?",
    "noise_smell_smoke": "Gibt es ungewöhnliche Geräusche, Geruch, Rauch oder Dampf? Bitte kurz beschreiben.",
    "trigger": "In welcher Situation tritt es auf? (z.B. beim Starten, Bremsen, Beschleunigen oder bei bestimmter Geschwindigkeit)",
    "recent_work": "Wurde in letzter Zeit etwas am Fahrzeug repariert oder ist kurz davor etwas passiert?",
    "start_behavior": "Was passiert genau beim Startversuch? Dreht der Anlasser, klickt es nur oder bleibt alles still?",
    "drive_symptoms": "Wie verhält sich das Fahrzeug genau beim Fahren? Ruckeln, Leistungsverlust, Aussetzer oder Notlauf?",
}

NOTFALL_POOL = {
    "safety_drive": "Ist das Fahrzeug aktuell sicher fahrbar oder riskant weiterzufahren?",
    "overheat": "Steigt die Motortemperatur stark an oder haben Sie Kühlmittelverlust bemerkt?",
    "warning_lamps": "Leuchtet eine rote Warnlampe oder gibt es eine dringende Fehlermeldung?",
    "brake_steering": "Betrifft das Problem die Bremsen oder die Lenkung direkt und ist das Fahrzeug dadurch unsicher?",
}


# =========================================================
# Auswahl-Logik
# =========================================================

def select_diagnose_followups(problem_text: str, max_q: int = 3) -> List[str]:
    analysis = analyze_problem(problem_text)
    flags = analysis["flags"]
    selected: List[str] = []

    selected.append(FOLLOWUP_POOL["since_when"])

    if flags["start_problem"]:
        selected.append(FOLLOWUP_POOL["start_behavior"])
    elif flags["warning_light"]:
        selected.append(FOLLOWUP_POOL["warning_lamps"])
    else:
        selected.append(FOLLOWUP_POOL["sporadic"])

    if flags["noise"] or flags["smoke_or_steam"]:
        selected.append(FOLLOWUP_POOL["noise_smell_smoke"])
    elif flags["performance_issue"]:
        selected.append(FOLLOWUP_POOL["drive_symptoms"])
    else:
        selected.append(FOLLOWUP_POOL["trigger"])

    t = lower(problem_text)
    if any(k in t for k in ["repar", "werkstatt", "gewechselt", "service", "inspektion", "nach"]):
        selected.append(FOLLOWUP_POOL["recent_work"])

    deduped: List[str] = []
    for q in selected:
        if q not in deduped:
            deduped.append(q)

    result = deduped[:max_q]
    if len(result) < 2:
        result = deduped[:2]

    return result


def select_notfall_followups(problem_text: str, include_safety_drive: bool = True) -> List[str]:
    analysis = analyze_problem(problem_text)
    flags = analysis["flags"]
    selected: List[str] = []

    if include_safety_drive:
        selected.append(NOTFALL_POOL["safety_drive"])

    if flags["critical_brake_or_steering"]:
        selected.append(NOTFALL_POOL["brake_steering"])
    elif flags["overheat"] or flags["smoke_or_steam"]:
        selected.append(NOTFALL_POOL["overheat"])
    else:
        selected.append(NOTFALL_POOL["warning_lamps"])

    deduped: List[str] = []
    for q in selected:
        if q not in deduped:
            deduped.append(q)

    return deduped[:2]


def select_followups(problem_text: str, include_safety_drive: bool = True) -> List[str]:
    analysis = analyze_problem(problem_text)
    request_type = analysis["request_type"]

    if request_type == REQUEST_TYPE_SERVICE:
        return []

    if request_type == REQUEST_TYPE_NOTFALL:
        return select_notfall_followups(
            problem_text,
            include_safety_drive=include_safety_drive,
        )

    return select_diagnose_followups(problem_text, max_q=3)