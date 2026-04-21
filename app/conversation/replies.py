from __future__ import annotations

from typing import List, cast

from app.conversation.constants import REQUEST_TYPE_SERVICE
from app.models import IntakeState


def welcome_reply() -> str:
    return (
        "Willkommen bei der Werkstatt-Annahme. 😊\n"
        "Welche Marke und welches Modell hat Ihr Fahrzeug? (z.B. „Mercedes C180“)"
    )


def reset_reply() -> str:
    return (
        "Alles klar – ich habe die Eingaben zurückgesetzt.\n"
        "Welche Marke und welches Modell hat Ihr Fahrzeug?"
    )


def ask_vehicle_clarify_reply() -> str:
    return "Könnten Sie bitte Marke und Modell etwas genauer angeben?"


def ask_baujahr_reply(fahrzeug: str | None = None) -> str:
    if fahrzeug:
        return f"Verstanden: **{fahrzeug}**.\nWelches Baujahr hat das Fahrzeug? (z.B. 2008)"
    return "Welches Baujahr hat das Fahrzeug? (z.B. 2008)"


def ask_baujahr_invalid_reply() -> str:
    return "Bitte nennen Sie ein vierstelliges Baujahr (z.B. 2008)."


def ask_kilometerstand_reply(fahrzeug: str | None = None) -> str:
    if fahrzeug:
        return (
            f"Verstanden: **{fahrzeug}**.\n"
            "Danke. Wie hoch ist der Kilometerstand? (z.B. 180000 oder 180k)"
        )
    return "Danke. Wie hoch ist der Kilometerstand? (z.B. 180000 oder 180k)"


def ask_kilometerstand_invalid_reply() -> str:
    return "Bitte geben Sie den Kilometerstand als Zahl an (z.B. 180000 oder 180k)."


def ask_problem_reply(fahrzeug: str | None = None) -> str:
    prefix = f"Verstanden: **{fahrzeug}**.\n" if fahrzeug else ""
    return (
        f"{prefix}"
        "Worum geht es genau?\n"
        "Bitte beschreiben Sie kurz Ihr Anliegen oder das Problem.\n"
        "Beispiele: „Reifenwechsel“, „Inspektion“, „Auto springt nicht an“, „Warnlampe leuchtet“"
    )


def ask_problem_invalid_reply() -> str:
    return "Bitte beschreiben Sie Ihr Anliegen kurz etwas genauer."


def service_detected_reply() -> str:
    return (
        "Alles klar – das klingt nach einem Service-/Wartungsauftrag.\n"
        "Welche Telefonnummer können wir für Rückfragen oder einen Terminvorschlag nutzen?"
    )


def ask_fahrbereit_reply() -> str:
    return "Ist das Fahrzeug aktuell fahrbereit? (Ja/Nein)"


def ask_fahrbereit_invalid_reply() -> str:
    return "Kurz Ja oder Nein: Ist das Fahrzeug fahrbereit?"


def ask_abschleppdienst_reply() -> str:
    return "Benötigen Sie einen Abschleppdienst? (Ja/Nein)"


def ask_abschleppdienst_invalid_reply() -> str:
    return "Kurz Ja oder Nein: Benötigen Sie einen Abschleppdienst?"


def ask_phone_reply(prefix: str | None = None) -> str:
    if prefix:
        return f"{prefix}\nWelche Telefonnummer können wir für Rückfragen nutzen?"
    return "Welche Telefonnummer können wir für Rückfragen nutzen?"


def ask_phone_with_thanks_reply() -> str:
    return "Vielen Dank. Welche Telefonnummer können wir für Rückfragen nutzen?"


def ask_phone_invalid_reply() -> str:
    return "Bitte geben Sie eine gültige Telefonnummer an (mindestens 7 Ziffern)."


def ask_name_reply() -> str:
    return 'Wie dürfen wir Sie ansprechen? (Vorname reicht – optional, sonst „überspringen“ schreiben)'


def ask_followup_invalid_reply() -> str:
    return "Könnten Sie das bitte kurz beantworten?"


def restart_reply() -> str:
    return "Ich starte nochmal neu. Welche Marke und welches Modell hat Ihr Fahrzeug?"


def build_completion_summary(state: IntakeState, score: int) -> str:
    fahrzeug = getattr(state, "fahrzeug", None) or "-"
    baujahr = getattr(state, "baujahr", None) or "-"
    kilometerstand = getattr(state, "kilometerstand", None) or "-"
    problem = getattr(state, "problem", None) or "-"
    request_type = getattr(state, "request_type", None) or "-"
    priority = getattr(state, "priority", None) or "-"
    fahrbereit = getattr(state, "fahrbereit", None) or "-"
    abschleppdienst = getattr(state, "abschleppdienst", None)
    telefon = getattr(state, "telefon", None) or "-"
    name = getattr(state, "name", None)

    summary_lines = [
        "Perfekt – die Anfrage ist vollständig. ✅",
        "",
        "Zusammenfassung:",
        f"- Fahrzeug: {fahrzeug}",
        f"- Baujahr: {baujahr}",
        f"- Kilometerstand: {kilometerstand}",
        f"- Anliegen: {problem}",
        f"- Typ: {request_type}",
        f"- Priorität: {priority}",
        f"- Analyse-Score: {score}",
    ]

    if request_type != REQUEST_TYPE_SERVICE:
        summary_lines.append(f"- Fahrbereit: {fahrbereit}")

    if abschleppdienst:
        summary_lines.append(f"- Abschleppdienst: {abschleppdienst}")

    q_list = list(cast(List[str], getattr(state, "followup_questions", []) or []))
    a_list = list(cast(List[str], getattr(state, "followup_answers", []) or []))
    if q_list and a_list:
        summary_lines.append("")
        summary_lines.append("Zusätzliche Angaben:")
        for i, (q, a) in enumerate(zip(q_list, a_list), start=1):
            summary_lines.append(f"- {i}) {q} — {a}")

    summary_lines.append("")
    if name:
        summary_lines.append(f"Kontakt: {name}, Tel. {telefon}")
    else:
        summary_lines.append(f"Kontakt: Tel. {telefon}")

    summary_lines.append("")
    summary_lines.append("Wir melden uns so schnell wie möglich.")

    return "\n".join(summary_lines)