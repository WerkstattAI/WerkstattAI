from __future__ import annotations

from typing import Any, Tuple

from app.conversation.extractors import lower, normalize
from app.conversation.intent import extract_phone_reference, extract_ticket_reference
from app.models import IntakeState
from app.tickets import find_ticket_by_id, find_tickets_by_phone


def _format_ticket_short(ticket: dict[str, Any]) -> str:
    ticket_id = ticket.get("ticket_id") or "-"
    fahrzeug = ticket.get("fahrzeug") or "-"
    status = ticket.get("status") or "-"
    priority = ticket.get("priority") or "-"
    created_at = ticket.get("created_at") or "-"

    return (
        f"- {ticket_id} | {fahrzeug} | Status: {status} | "
        f"Priorität: {priority} | Erstellt: {created_at}"
    )


def _get_latest_note(ticket: dict[str, Any]) -> dict[str, Any] | None:
    notes = ticket.get("notes") or []
    if not isinstance(notes, list) or not notes:
        return None
    return notes[-1]


def _build_ticket_summary(ticket: dict[str, Any]) -> str:
    ticket_id = ticket.get("ticket_id") or "-"
    fahrzeug = ticket.get("fahrzeug") or "-"
    baujahr = ticket.get("baujahr") or "-"
    kilometerstand = ticket.get("kilometerstand") or "-"
    problem = ticket.get("problem") or "-"
    status = ticket.get("status") or "-"
    priority = ticket.get("priority") or "-"
    request_type = ticket.get("request_type") or "-"
    telefon = ticket.get("telefon") or "-"
    name = ticket.get("name") or ticket.get("kunde_name") or "-"
    fahrbereit = ticket.get("fahrbereit")
    abschleppdienst = ticket.get("abschleppdienst")
    created_at = ticket.get("created_at") or "-"
    updated_at = ticket.get("updated_at") or "-"

    fahrbereit_text = "-"
    if fahrbereit is True:
        fahrbereit_text = "ja"
    elif fahrbereit is False:
        fahrbereit_text = "nein"

    abschleppdienst_text = "-"
    if abschleppdienst is True:
        abschleppdienst_text = "ja"
    elif abschleppdienst is False:
        abschleppdienst_text = "nein"

    lines = [
        f"Ticket **{ticket_id}**",
        "",
        f"- Fahrzeug: {fahrzeug}",
        f"- Baujahr: {baujahr}",
        f"- Kilometerstand: {kilometerstand}",
        f"- Anliegen: {problem}",
        f"- Status: {status}",
        f"- Priorität: {priority}",
        f"- Typ: {request_type}",
        f"- Fahrbereit: {fahrbereit_text}",
        f"- Abschleppdienst: {abschleppdienst_text}",
        f"- Kunde: {name}",
        f"- Telefon: {telefon}",
        f"- Erstellt: {created_at}",
        f"- Zuletzt aktualisiert: {updated_at}",
    ]

    latest_note = _get_latest_note(ticket)
    if latest_note:
        note_text = latest_note.get("text") or "-"
        note_created_at = latest_note.get("created_at") or "-"
        lines.append("")
        lines.append(f"Letzte Notiz: {note_text}")
        lines.append(f"Notiz-Zeit: {note_created_at}")

    return "\n".join(lines)


def _looks_like_status_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "status",
            "wie ist der status",
            "stand",
            "aktueller stand",
            "bearbeitung",
        ]
    )


def _looks_like_priority_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "priorität",
            "prioritaet",
            "wie dringend",
            "dringlichkeit",
            "priority",
        ]
    )


def _looks_like_problem_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "problem",
            "anliegen",
            "worum geht",
            "was war",
            "defekt",
            "fehler",
        ]
    )


def _looks_like_vehicle_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "fahrzeug",
            "auto",
            "wagen",
            "modell",
            "marke",
            "baujahr",
            "kilometerstand",
            "km-stand",
        ]
    )


def _looks_like_contact_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "telefon",
            "telefonnummer",
            "nummer",
            "kontakt",
            "name",
            "kunde",
            "kundenname",
        ]
    )


def _looks_like_note_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "notiz",
            "notizen",
            "letzte notiz",
            "interne notiz",
        ]
    )


def _looks_like_summary_question(text: str) -> bool:
    t = lower(text)
    return any(
        key in t
        for key in [
            "zusammenfassung",
            "zusammenfassen",
            "zusammengefasst",
            "komplett",
            "alles zu dem ticket",
            "ticket anzeigen",
            "zeige ticket",
            "zeig ticket",
        ]
    )


def _resolve_ticket_from_message(user_message: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Versucht zuerst Ticket-ID, danach Telefonnummer.
    Gibt zurück:
    - genau 1 Ticket -> (ticket, None)
    - kein Ticket -> (None, Fehlermeldung)
    - mehrere Tickets -> (None, Rückfrage/Übersicht)
    """
    ticket_ref = extract_ticket_reference(user_message)
    if ticket_ref:
        ticket = find_ticket_by_id(ticket_ref)
        if ticket:
            return ticket, None
        return None, f"Ich konnte kein Ticket mit der Nummer **{ticket_ref}** finden."

    phone_ref = extract_phone_reference(user_message)
    if phone_ref:
        matches = find_tickets_by_phone(phone_ref)

        if not matches:
            return None, "Ich konnte kein Ticket zu dieser Telefonnummer finden."

        if len(matches) == 1:
            return matches[0], None

        lines = [
            f"Ich habe **{len(matches)}** Tickets zu dieser Telefonnummer gefunden:",
            "",
        ]
        for ticket in matches[:10]:
            lines.append(_format_ticket_short(ticket))

        lines.append("")
        lines.append("Bitte nennen Sie die genaue Ticketnummer, damit ich das richtige Ticket öffnen kann.")
        return None, "\n".join(lines)

    return None, (
        "Bitte nennen Sie eine **Ticketnummer** oder **Telefonnummer**, "
        "damit ich das passende bestehende Ticket finden kann."
    )


def _answer_ticket_question(ticket: dict[str, Any], user_message: str) -> str:
    if _looks_like_status_question(user_message):
        return (
            f"Der Status von Ticket **{ticket.get('ticket_id') or '-'}** ist: "
            f"**{ticket.get('status') or '-'}**."
        )

    if _looks_like_priority_question(user_message):
        return (
            f"Die Priorität von Ticket **{ticket.get('ticket_id') or '-'}** ist: "
            f"**{ticket.get('priority') or '-'}**."
        )

    if _looks_like_problem_question(user_message):
        return (
            f"Das gemeldete Anliegen bei Ticket **{ticket.get('ticket_id') or '-'}** lautet:\n"
            f"**{ticket.get('problem') or '-'}**"
        )

    if _looks_like_vehicle_question(user_message):
        return (
            f"Zum Ticket **{ticket.get('ticket_id') or '-'}** gehört folgendes Fahrzeug:\n"
            f"- Fahrzeug: {ticket.get('fahrzeug') or '-'}\n"
            f"- Baujahr: {ticket.get('baujahr') or '-'}\n"
            f"- Kilometerstand: {ticket.get('kilometerstand') or '-'}"
        )

    if _looks_like_contact_question(user_message):
        return (
            f"Kontaktdaten zu Ticket **{ticket.get('ticket_id') or '-'}**:\n"
            f"- Kunde: {ticket.get('name') or ticket.get('kunde_name') or '-'}\n"
            f"- Telefon: {ticket.get('telefon') or '-'}"
        )

    if _looks_like_note_question(user_message):
        latest_note = _get_latest_note(ticket)
        if not latest_note:
            return f"Zu Ticket **{ticket.get('ticket_id') or '-'}** gibt es aktuell keine interne Notiz."

        return (
            f"Letzte Notiz zu Ticket **{ticket.get('ticket_id') or '-'}**:\n"
            f"- Text: {latest_note.get('text') or '-'}\n"
            f"- Erstellt: {latest_note.get('created_at') or '-'}"
        )

    if _looks_like_summary_question(user_message):
        return _build_ticket_summary(ticket)

    # Default: kurze Zusammenfassung
    return _build_ticket_summary(ticket)


def handle_existing_ticket(
    state: IntakeState,
    user_message: str | None,
) -> Tuple[IntakeState, str, bool]:
    """
    Beantwortet einfache Fragen zu bestehenden Tickets.
    Erkennt aktuell:
    - Ticket-ID
    - Telefonnummer

    und beantwortet u.a. Fragen zu:
    - Status
    - Priorität
    - Problem
    - Fahrzeug
    - Kontakt
    - letzte Notiz
    - Zusammenfassung
    """
    if user_message is None or normalize(user_message) == "":
        reply = (
            "Bitte nennen Sie eine **Ticketnummer** oder **Telefonnummer**, "
            "damit ich ein bestehendes Ticket suchen kann."
        )
        return state, reply, False

    msg = normalize(user_message)

    ticket, error_reply = _resolve_ticket_from_message(msg)
    if error_reply:
        return state, error_reply, False

    if not ticket:
        return state, "Ich konnte kein passendes bestehendes Ticket ermitteln.", False

    reply = _answer_ticket_question(ticket, msg)
    return state, reply, False