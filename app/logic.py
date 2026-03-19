from __future__ import annotations

import re
from typing import List, Tuple

from app.models import IntakeState


# =========================================================
# Helpers
# =========================================================

def _normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def _lower(text: str) -> str:
    return _normalize(text).lower()


def _extract_year(text: str) -> str | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def _extract_km(text: str) -> str | None:
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
    t = _lower(text)

    # 180k / 180 tkm
    m = re.search(r"\b(\d{2,3})\s*(k|tkm)\b", t)
    if m:
        return str(int(m.group(1)) * 1000)

    # 180000 km / 180.000 km / 180 000 km
    m = re.search(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{5,7})\s*km\b", t)
    if m:
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if 4 <= len(digits) <= 7:
            return digits

    # Reine große Zahlen OHNE "km"
    m = re.search(r"\b\d{5,7}\b", t)
    if m:
        return m.group(0)

    return None


def _extract_phone(text: str) -> str | None:
    raw = _normalize(text)
    digits = re.findall(r"\d", raw)
    if len(digits) < 7:
        return None

    cleaned = re.sub(r"[^\d+]", "", raw)
    cleaned = re.sub(r"(?!^)\+", "", cleaned)

    only_digits = re.sub(r"\D", "", cleaned)
    if len(only_digits) < 7:
        return None

    return cleaned


def _is_cancel(text: str) -> bool:
    t = _lower(text)
    return t in {
        "abbrechen",
        "stopp",
        "stop",
        "cancel",
        "ende",
        "zurücksetzen",
        "zuruecksetzen",
        "reset",
        "neu",
        "neu starten",
    }


def _reset_state() -> IntakeState:
    return IntakeState(step="fahrzeug")


def _is_yes(text: str) -> bool:
    t = _lower(text)
    return t in {
        "ja",
        "j",
        "yes",
        "y",
        "klar",
        "ok",
        "okay",
        "natürlich",
        "natuerlich",
        "sicher",
        "genau",
        "passt",
    }


def _is_no(text: str) -> bool:
    t = _lower(text)
    return t in {
        "nein",
        "n",
        "no",
        "nicht",
        "leider nein",
        "eher nicht",
    }


def _contains_any(text: str, keywords: list[str]) -> bool:
    t = _lower(text)
    return any(k in t for k in keywords)


def _contains_all(text: str, keywords: list[str]) -> bool:
    t = _lower(text)
    return all(k in t for k in keywords)


def _cleanup_vehicle_text(text: str) -> str:
    t = _normalize(text)

    year = _extract_year(t)
    if year:
        t = re.sub(rf"\b{re.escape(year)}\b", "", t)

    t = re.sub(r"\b\d{2,3}\s*(k|tkm)\b", "", t, flags=re.I)
    t = re.sub(r"\b(\d{1,3}(?:[.\s]\d{3})+|\d{5,7})\s*km\b", "", t, flags=re.I)
    t = re.sub(r"\b\d{5,7}\b", "", t)

    t = re.sub(r"[,\-_/]+", " ", t)
    t = _normalize(t)
    return t


def _extract_name_candidate(text: str) -> str | None:
    t = _normalize(text)
    tl = t.lower()

    if tl in {"überspringen", "ueberspringen", "skip", "egal", "nein"}:
        return None

    if len(t) < 2:
        return None

    if _extract_phone(t):
        return None

    if _extract_year(t):
        return None

    km = _extract_km(t)
    if km and re.sub(r"\D", "", t) == km:
        return None

    return t[:60]


def _infer_fahrbereit_from_text(text: str) -> str | None:
    t = _lower(text)

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


def _has_start_problem(text: str) -> bool:
    t = _lower(text)
    return (
        "springt nicht an" in t
        or "springt nicht mehr an" in t
        or "startet nicht" in t
        or "startet nicht mehr" in t
        or ("springt" in t and "nicht" in t and "an" in t)
        or ("startet" in t and "nicht" in t)
    )


def _has_critical_brake_or_steering(text: str) -> bool:
    t = _lower(text)

    steering_critical = (
        ("lenk" in t or "lenkrad" in t)
        and any(k in t for k in ["seite", "zieht", "schief", "block", "schwer", "problem"])
    )

    brake_critical = (
        "bremse ohne wirkung" in t
        or "bremsen funktionieren nicht" in t
        or ("brems" in t and any(k in t for k in ["zieht", "seite", "stark", "problem", "schief"]))
    )

    return steering_critical or brake_critical


def _has_notfall_hint(text: str) -> bool:
    t = _lower(text)

    return (
        _has_start_problem(t)
        or "nicht fahrbereit" in t
        or "liegen geblieben" in t
        or "bleibt liegen" in t
        or "motor geht aus" in t
        or "rote warnlampe" in t
        or "warnlampe rot" in t
        or "rauch" in t
        or "qualm" in t
        or "dampf" in t
        or "überhitz" in t
        or "ueberhitz" in t
        or "kühlmittel" in t
        or "kuehlmittel" in t
        or _has_critical_brake_or_steering(t)
    )


def _detect_priority(text: str, request_type: str | None = None) -> str:
    """
    Kompatibel mit deinem jetzigen Projekt:
    normal | dringend | notfall
    """
    t = _lower(text)
    rt = request_type or _detect_request_type(t)

    if _has_start_problem(t) or "nicht fahrbereit" in t or "liegen geblieben" in t:
        return "notfall"

    if rt == "notfall":
        return "dringend"

    if _has_critical_brake_or_steering(t):
        return "dringend"

    if any(k in t for k in [
        "warnlampe",
        "fehlermeldung",
        "ruckel",
        "leistung",
        "ölverlust",
        "oelverlust",
        "problem",
        "defekt",
    ]):
        return "dringend"

    return "normal"


# =========================================================
# Anfrage-Typ erkennen
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


def _is_service_request(text: str) -> bool:
    t = _lower(text)

    if _contains_any(t, SERVICE_KEYWORDS):
        return True

    if _contains_all(t, ["reifen", "wechsel"]):
        return True

    if _contains_all(t, ["öl", "wechsel"]) or _contains_all(t, ["oel", "wechsel"]):
        return True

    if _contains_all(t, ["bremsen", "wechsel"]) or _contains_all(t, ["bremsbeläge", "wechsel"]):
        return True

    return False


def _detect_request_type(text: str) -> str:
    """
    service | diagnose | notfall
    """
    t = _lower(text)

    if _has_notfall_hint(t):
        return "notfall"

    if _is_service_request(t):
        return "service"

    if _contains_any(t, DIAGNOSE_HINTS):
        return "diagnose"

    return "diagnose"


# =========================================================
# Follow-up-Auswahl
# =========================================================

FOLLOWUP_POOL = {
    "since_when": "Seit wann besteht das Problem ungefähr?",
    "sporadic": "Tritt das Problem ständig auf oder nur sporadisch?",
    "warning_lamps": "Leuchtet eine Warnlampe oder gibt es eine Fehlermeldung im Display? Wenn ja, welche?",
    "noise_smell_smoke": "Gibt es ungewöhnliche Geräusche, Geruch oder Rauch? Bitte kurz beschreiben.",
    "trigger": "In welcher Situation tritt es auf? (z.B. beim Starten, Bremsen, Beschleunigen oder bei bestimmter Geschwindigkeit)",
    "recent_work": "Wurde in letzter Zeit etwas am Fahrzeug repariert oder ist kurz davor etwas passiert?",
}

NOTFALL_POOL = {
    "safety_drive": "Ist das Fahrzeug aktuell sicher fahrbar oder riskant weiterzufahren?",
    "overheat": "Steigt die Motortemperatur stark an oder haben Sie Kühlmittelverlust bemerkt?",
    "warning_lamps": "Leuchtet eine rote Warnlampe oder gibt es eine dringende Fehlermeldung?",
}


def _select_diagnose_followups(problem_text: str, max_q: int = 3) -> List[str]:
    t = _lower(problem_text)
    selected: List[str] = []

    keywords_start = any(k in t for k in ["springt nicht an", "start", "anlasser", "batterie", "klick", "kein strom"])
    keywords_noise = any(k in t for k in ["geräusch", "geraeusch", "klopf", "quiets", "schleif", "pfeif", "brumm"])
    keywords_warning = any(k in t for k in ["warn", "lampe", "check engine", "motorkontroll", "fehlermeld", "abs", "esp", "airbag"])

    selected.append(FOLLOWUP_POOL["since_when"])

    if keywords_warning:
        selected.append(FOLLOWUP_POOL["warning_lamps"])
    else:
        selected.append(FOLLOWUP_POOL["sporadic"])

    if keywords_noise or keywords_start:
        selected.append(FOLLOWUP_POOL["noise_smell_smoke"])
    else:
        selected.append(FOLLOWUP_POOL["trigger"])

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


def _select_notfall_followups(problem_text: str, include_safety_drive: bool = True) -> List[str]:
    t = _lower(problem_text)
    selected: List[str] = []

    if include_safety_drive:
        selected.append(NOTFALL_POOL["safety_drive"])

    if any(k in t for k in ["überhitz", "ueberhitz", "temperatur", "kühlmittel", "kuehlmittel", "dampf"]):
        selected.append(NOTFALL_POOL["overheat"])
    else:
        selected.append(NOTFALL_POOL["warning_lamps"])

    deduped: List[str] = []
    for q in selected:
        if q not in deduped:
            deduped.append(q)

    return deduped[:2]


def _select_followups(problem_text: str, include_safety_drive: bool = True) -> List[str]:
    request_type = _detect_request_type(problem_text)

    if request_type == "service":
        return []

    if request_type == "notfall":
        return _select_notfall_followups(problem_text, include_safety_drive=include_safety_drive)

    return _select_diagnose_followups(problem_text, max_q=3)


# =========================================================
# Intelligente Feld-Erkennung
# =========================================================

def _can_extract_vehicle(text: str) -> bool:
    t = _normalize(text)
    if len(t) < 3:
        return False

    if _extract_phone(t):
        return False

    pure_digits = re.sub(r"\D", "", t)
    if pure_digits and len(pure_digits) == len(t.replace(" ", "")):
        return False

    return True


def _consume_inline_vehicle_year_km(state: IntakeState, text: str) -> None:
    """
    Beispiele:
    - BMW 320d 2014 210000 km
    - Audi A4 2011 180k
    """
    t = _normalize(text)

    if not getattr(state, "fahrzeug", None) and _can_extract_vehicle(t):
        fahrzeug = _cleanup_vehicle_text(t)
        if len(fahrzeug) >= 3:
            state.fahrzeug = fahrzeug

    if not getattr(state, "baujahr", None):
        year = _extract_year(t)
        if year:
            state.baujahr = year

    if not getattr(state, "kilometerstand", None):
        km = _extract_km(t)
        if km:
            state.kilometerstand = km


# =========================================================
# Zustandsmaschine
# =========================================================

def next_step(state: IntakeState, user_message: str | None) -> Tuple[IntakeState, str, bool]:
    """
    Flow v2:
      fahrzeug
      -> baujahr
      -> kilometerstand
      -> problem
          -> service: telefon -> name -> fertig
          -> diagnose/notfall: fahrbereit -> ggf. abschleppdienst -> followup -> telefon -> name -> fertig
    """

    if user_message is None or _normalize(user_message) == "":
        new_state = state
        reply = (
            "Willkommen bei der Werkstatt-Annahme. 😊\n"
            "Welche Marke und welches Modell hat Ihr Fahrzeug? (z.B. „Mercedes C180“)"
        )
        return new_state, reply, False

    msg = _normalize(user_message)

    if _is_cancel(msg):
        new_state = _reset_state()
        reply = (
            "Alles klar – ich habe die Eingaben zurückgesetzt.\n"
            "Welche Marke und welches Modell hat Ihr Fahrzeug?"
        )
        return new_state, reply, False

    new_state = state.model_copy(deep=True)
    new_state.last_user_message = msg

    if new_state.step == "fahrzeug":
        _consume_inline_vehicle_year_km(new_state, msg)

        if not getattr(new_state, "fahrzeug", None):
            return new_state, "Könnten Sie bitte Marke und Modell etwas genauer angeben?", False

        if not getattr(new_state, "baujahr", None):
            new_state.step = "baujahr"
            return (
                new_state,
                f"Verstanden: **{new_state.fahrzeug}**.\nWelches Baujahr hat das Fahrzeug? (z.B. 2008)",
                False,
            )

        if not getattr(new_state, "kilometerstand", None):
            new_state.step = "kilometerstand"
            return (
                new_state,
                f"Verstanden: **{new_state.fahrzeug}**.\nDanke. Wie hoch ist der Kilometerstand? (z.B. 180000 oder 180k)",
                False,
            )

        new_state.step = "problem"
        return (
            new_state,
            (
                f"Verstanden: **{new_state.fahrzeug}**.\n"
                "Worum geht es genau?\n"
                "Bitte beschreiben Sie kurz Ihr Anliegen oder das Problem.\n"
                "Beispiele: „Reifenwechsel“, „Inspektion“, „Auto springt nicht an“, „Warnlampe leuchtet“"
            ),
            False,
        )

    if new_state.step == "baujahr":
        year = _extract_year(msg)
        if not year:
            return new_state, "Bitte nennen Sie ein vierstelliges Baujahr (z.B. 2008).", False

        new_state.baujahr = year
        new_state.step = "kilometerstand"
        return new_state, "Danke. Wie hoch ist der Kilometerstand? (z.B. 180000 oder 180k)", False

    if new_state.step == "kilometerstand":
        km = _extract_km(msg)
        if not km:
            return new_state, "Bitte geben Sie den Kilometerstand als Zahl an (z.B. 180000 oder 180k).", False

        new_state.kilometerstand = km
        new_state.step = "problem"
        return (
            new_state,
            (
                "Worum geht es genau?\n"
                "Bitte beschreiben Sie kurz Ihr Anliegen oder das Problem.\n"
                "Beispiele: „Reifenwechsel“, „Inspektion“, „Auto springt nicht an“, „Warnlampe leuchtet“"
            ),
            False,
        )

    if new_state.step == "problem":
        if len(msg) < 3:
            return new_state, "Bitte beschreiben Sie Ihr Anliegen kurz etwas genauer.", False

        new_state.problem = msg
        request_type = _detect_request_type(new_state.problem)
        priority = _detect_priority(new_state.problem, request_type)

        if hasattr(new_state, "request_type"):
            new_state.request_type = request_type

        if hasattr(new_state, "priority"):
            new_state.priority = priority

        if request_type == "service":
            new_state.followup_questions = []
            new_state.followup_answers = []
            new_state.followup_index = 0
            new_state.step = "telefon"
            return (
                new_state,
                "Alles klar – das klingt nach einem Service-/Wartungsauftrag.\nWelche Telefonnummer können wir für Rückfragen oder einen Terminvorschlag nutzen?",
                False,
            )

        inferred = _infer_fahrbereit_from_text(new_state.problem)
        if inferred:
            new_state.fahrbereit = inferred

            if inferred == "nein":
                new_state.step = "abschleppdienst"
                return new_state, "Benötigen Sie einen Abschleppdienst? (Ja/Nein)", False

            followups = _select_followups(new_state.problem or "")
            new_state.followup_questions = followups
            new_state.followup_answers = []
            new_state.followup_index = 0

            if followups:
                new_state.step = "followup"
                return new_state, followups[0], False

            new_state.step = "telefon"
            return new_state, "Welche Telefonnummer können wir für Rückfragen nutzen?", False

        new_state.step = "fahrbereit"
        return new_state, "Ist das Fahrzeug aktuell fahrbereit? (Ja/Nein)", False

    if new_state.step == "fahrbereit":
        inferred = _infer_fahrbereit_from_text(msg)

        if inferred is None and not (_is_yes(msg) or _is_no(msg)):
            return new_state, "Kurz Ja oder Nein: Ist das Fahrzeug fahrbereit?", False

        new_state.fahrbereit = inferred or ("ja" if _is_yes(msg) else "nein")

        if new_state.fahrbereit == "nein":
            new_state.step = "abschleppdienst"
            return new_state, "Benötigen Sie einen Abschleppdienst? (Ja/Nein)", False

        followups = _select_followups(new_state.problem or "")
        new_state.followup_questions = followups
        new_state.followup_answers = []
        new_state.followup_index = 0

        if followups:
            new_state.step = "followup"
            return new_state, followups[0], False

        new_state.step = "telefon"
        return new_state, "Welche Telefonnummer können wir für Rückfragen nutzen?", False

    if new_state.step == "abschleppdienst":
        if not (_is_yes(msg) or _is_no(msg)):
            return new_state, "Kurz Ja oder Nein: Benötigen Sie einen Abschleppdienst?", False

        new_state.abschleppdienst = "ja" if _is_yes(msg) else "nein"

        followups = _select_followups(
            new_state.problem or "",
            include_safety_drive=False,
        )
        new_state.followup_questions = followups
        new_state.followup_answers = []
        new_state.followup_index = 0

        if followups:
            new_state.step = "followup"
            return new_state, followups[0], False

        new_state.step = "telefon"
        return new_state, "Vielen Dank. Welche Telefonnummer können wir für Rückfragen nutzen?", False

    if new_state.step == "followup":
        if not msg:
            return new_state, "Könnten Sie das bitte kurz beantworten?", False

        answers = list(getattr(new_state, "followup_answers", []) or [])
        answers.append(msg)
        new_state.followup_answers = answers

        idx = int(getattr(new_state, "followup_index", 0) or 0) + 1
        new_state.followup_index = idx

        questions = list(getattr(new_state, "followup_questions", []) or [])
        if idx < len(questions):
            return new_state, questions[idx], False

        new_state.step = "telefon"
        return new_state, "Vielen Dank. Welche Telefonnummer können wir für Rückfragen nutzen?", False

    if new_state.step == "telefon":
        phone = _extract_phone(msg)
        if not phone:
            return new_state, "Bitte geben Sie eine gültige Telefonnummer an (mindestens 7 Ziffern).", False

        new_state.telefon = phone
        new_state.step = "name"
        return new_state, "Wie dürfen wir Sie ansprechen? (Vorname reicht – optional, sonst „überspringen“ schreiben)", False

    if new_state.step == "name":
        t = _lower(msg)
        if t in {"überspringen", "ueberspringen", "skip", "egal", "nein"}:
            new_state.name = None
        else:
            new_state.name = _extract_name_candidate(msg)

        new_state.step = "fertig"

        request_type = _detect_request_type(new_state.problem or "")
        priority = _detect_priority(new_state.problem or "", request_type)

        if hasattr(new_state, "request_type"):
            new_state.request_type = request_type

        if hasattr(new_state, "priority"):
            new_state.priority = priority

        summary_lines = [
            "Perfekt – die Anfrage ist vollständig. ✅",
            "",
            "Zusammenfassung:",
            f"- Fahrzeug: {new_state.fahrzeug or '-'}",
            f"- Baujahr: {new_state.baujahr or '-'}",
            f"- Kilometerstand: {getattr(new_state, 'kilometerstand', None) or '-'}",
            f"- Anliegen: {new_state.problem or '-'}",
        ]

        if hasattr(new_state, "request_type"):
            summary_lines.append(f"- Typ: {getattr(new_state, 'request_type', None) or '-'}")

        if hasattr(new_state, "priority"):
            summary_lines.append(f"- Priorität: {getattr(new_state, 'priority', None) or '-'}")

        if request_type != "service":
            summary_lines.append(f"- Fahrbereit: {getattr(new_state, 'fahrbereit', None) or '-'}")

        if getattr(new_state, "abschleppdienst", None):
            summary_lines.append(f"- Abschleppdienst: {new_state.abschleppdienst}")

        q_list = list(getattr(new_state, "followup_questions", []) or [])
        a_list = list(getattr(new_state, "followup_answers", []) or [])
        if q_list and a_list:
            summary_lines.append("")
            summary_lines.append("Zusätzliche Angaben:")
            for i, (q, a) in enumerate(zip(q_list, a_list), start=1):
                summary_lines.append(f"- {i}) {q} — {a}")

        if getattr(new_state, "name", None):
            summary_lines.append(f"\nKontakt: {new_state.name}, Tel. {new_state.telefon}")
        else:
            summary_lines.append(f"\nKontakt: Tel. {new_state.telefon}")

        summary_lines.append("\nWir melden uns so schnell wie möglich.")
        reply = "\n".join(summary_lines)

        return new_state, reply, True

    new_state.step = "fahrzeug"
    return new_state, "Ich starte nochmal neu. Welche Marke und welches Modell hat Ihr Fahrzeug?", False