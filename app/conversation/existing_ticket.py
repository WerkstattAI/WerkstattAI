from __future__ import annotations

import re
import uuid
from typing import Any, Tuple

from app.conversation.extractors import lower, normalize
from app.conversation.intent import extract_phone_reference, extract_ticket_reference
from app.conversation.general_question import stored_workshop_answer
from app.customer_access import CustomerAccess
from app.models import IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, find_tickets_by_phone
from app.workshops import get_workshop


ACCESS_DENIED_REPLY = (
    "Ich kann dieses Ticket hier nicht zuordnen. "
    "Bitte nutzen Sie den ursprünglichen Kundenchat oder wenden Sie sich direkt an die Werkstatt."
)


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


def _note_type(note: dict[str, Any]) -> str:
    note_type = str(note.get("type", "") if isinstance(note, dict) else "").strip().lower()
    if note_type in {"internal_note", "customer_message", "customer_reply"}:
        return note_type

    text = str(note.get("text", "") if isinstance(note, dict) else "").strip().lower()
    if text.startswith("kundenfrage über den chat:"):
        return "customer_message"

    return "internal_note"


def _get_latest_customer_reply(ticket: dict[str, Any]) -> dict[str, Any] | None:
    notes = ticket.get("notes") or []
    if not isinstance(notes, list):
        return None

    for note in reversed(notes):
        if not isinstance(note, dict):
            continue
        if note.get("delivery_status") not in {None, "sent"}:
            continue
        if note.get("sender_role") == "workshop" and note.get("purpose") in {
            "workshop_answer", "workshop_question", "workshop_notification",
        }:
            return note
        if not note.get("purpose") and _note_type(note) == "customer_reply":
            return note

    return None


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

    latest_note = _get_latest_customer_reply(ticket)
    if latest_note:
        note_text = latest_note.get("text") or "-"
        note_created_at = latest_note.get("created_at") or "-"
        lines.append("")
        lines.append(f"Letzte Antwort der Werkstatt: {note_text}")
        lines.append(f"Antwort-Zeit: {note_created_at}")

    return "\n".join(lines)


def _requires_workshop_decision(text: str) -> bool:
    """Decision words take precedence over all stored-fact shortcuts."""
    return bool(re.search(
        r"\b(?:preis\w*|kosten\w*|kostet|teuer|diagnos\w*|ursache\w*|defekt\w*|"
        r"fertig\w*|abhol\w*|reparaturdauer|dauer\w*|dauert|termin\w*|"
        r"ersatzteil\w*|teile|teil|reparier\w*|reparatur\w*|"
        r"bestätig\w*|bestaetig\w*|freigabe\w*|garantie\w*|kulanz\w*|"
        r"sicher|weiterfahren|fahrbereit|kaputt|bezahlen|zahlung\w*)\b|"
        r"\bwie (?:lange|teuer)\b|\bwann (?:ist|wird|kann|könn|koenn)\w*\b",
        lower(text),
    ))


def _question_text(text: str) -> str:
    """Strip an explicit reference, retaining the actual question for matching."""
    value = lower(text)
    value = re.sub(r"\b[a-z]{2,10}-\d{4,8}(?:-\d{1,10})?\b", "", value)
    value = re.sub(r"\b(?:ticket|ticketnr|ticket-nr|ticketnummer|auftrag|fall)\s*[:#-]?\s*\d{1,10}\b", "", value)
    value = re.sub(r"(?:\s+(?:zu|zum|von|für|fuer|wegen))?\s+(?:ticket|auftrag)\s*$", "", value.strip(" .?!:;"))
    if extract_ticket_reference(text):
        value = re.sub(r"\s+(?:zu|zum|von|für|fuer|wegen)$", "", value.strip(" .?!:;"))
    value = re.sub(r"^(?:hallo[,!]?|guten tag[,!]?|bitte)\s+", "", value)
    value = re.sub(r"\s+bitte$", "", value.strip(" .?!:;"))
    return normalize(value).strip(" .?!:;")


def _is_acknowledgement(text: str) -> bool:
    return lower(text).strip(" .?!") in {
        "danke", "vielen dank", "danke schön", "danke schoen", "dankeschön",
        "ok", "okay", "alles klar", "verstanden", "super danke", "danke für die info",
    }


def _is_customer_question(text: str) -> bool:
    return "?" in text or _requires_workshop_decision(text) or bool(re.search(
        r"^(?:wie|was|wer|wo|wann|warum|weshalb|wieso|welch\w*|kann|könn\w*|koenn\w*|"
        r"ist|sind|habt|haben|gibt|darf|dürf\w*|duerf\w*|soll|muss)\b", lower(text)
    ))


def _resolve_ticket_from_message(
    user_message: str,
    workshop_id: str | None = None,
    *,
    customer_access: CustomerAccess | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Versucht zuerst Ticket-ID, danach Telefonnummer.
    Gibt zurück:
    - genau 1 Ticket -> (ticket, None)
    - kein Ticket -> (None, Fehlermeldung)
    - mehrere Tickets -> (None, Rückfrage/Übersicht)
    """
    if customer_access is None or not workshop_id or customer_access.workshop_id != workshop_id:
        return None, ACCESS_DENIED_REPLY

    ticket_ref = extract_ticket_reference(user_message)
    if ticket_ref:
        ticket = find_ticket_by_id(ticket_ref, workshop_id=workshop_id)
        if customer_access.allows(ticket):
            return ticket, None
        return None, ACCESS_DENIED_REPLY

    phone_ref = extract_phone_reference(user_message)
    if phone_ref:
        matches = [
            ticket for ticket in find_tickets_by_phone(phone_ref, workshop_id=workshop_id)
            if customer_access.allows(ticket)
        ]

        if not matches:
            return None, ACCESS_DENIED_REPLY

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


def _resolve_ticket_for_state(
    state: IntakeState,
    user_message: str,
    *,
    customer_access: CustomerAccess | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    workshop_id = getattr(state, "workshop_id", None)
    if customer_access is None or not workshop_id or customer_access.workshop_id != workshop_id:
        return None, ACCESS_DENIED_REPLY
    ticket, error_reply = _resolve_ticket_from_message(
        user_message, workshop_id=workshop_id, customer_access=customer_access,
    )
    if ticket or extract_ticket_reference(user_message) or extract_phone_reference(user_message):
        return ticket, error_reply

    if getattr(state, "ticket_id", None):
        remembered = find_ticket_by_id(state.ticket_id or "", workshop_id=workshop_id)
        if customer_access.allows(remembered):
            return remembered, None
        return None, ACCESS_DENIED_REPLY

    return ticket, error_reply


def _stored_ticket_answer(ticket: dict[str, Any], user_message: str) -> str | None:
    """Return a stored fact only for a recognised, unambiguous request.

    Unknown text must reach the workshop; a broad word such as "Auto" or
    "Nummer" is not evidence that the saved vehicle/contact data answers it.
    """
    if _requires_workshop_decision(user_message):
        return None
    question = _question_text(user_message)
    ticket_id = ticket.get("ticket_id") or "-"
    if re.fullmatch(
        r"(?:(?:wie|was) (?:ist|lautet) (?:der |mein |aktuelle |aktueller )*status|"
        r"(?:aktueller? )?status|wie ist der (?:aktuelle )?stand(?: (?:meines|des) (?:tickets|auftrags))?)",
        question,
    ):
        return f"Der gespeicherte Status von Ticket **{ticket_id}** ist: **{ticket.get('status') or '-'}**."

    if re.fullmatch(r"(?:wie ist die |welche )?(?:priorität|prioritaet|dringlichkeit)(?: ist (?:gespeichert|hinterlegt))?", question):
        return f"Die gespeicherte Priorität von Ticket **{ticket_id}** ist: **{ticket.get('priority') or '-'}**."

    if re.fullmatch(
        r"(?:(?:welches?|was für ein) (?:fahrzeug|auto|modell|baujahr)|fahrzeug|auto|modell|baujahr|kilometerstand|km-stand|fahrzeugdaten)"
        r"(?: (?:ist|sind|habt ihr))?(?: (?:bei euch |im ticket )?(?:gespeichert|hinterlegt|erfasst))?",
        question,
    ):
        return (
            f"Gespeicherte Fahrzeugdaten zu Ticket **{ticket_id}**:\n"
            f"- Fahrzeug: {ticket.get('fahrzeug') or '-'}\n"
            f"- Baujahr: {ticket.get('baujahr') or '-'}\n"
            f"- Kilometerstand: {ticket.get('kilometerstand') or '-'}"
        )

    if re.fullmatch(
        r"(?:was (?:habe ich|wurde) (?:als (?:problem|anliegen) )?gemeldet|"
        r"welches (?:problem|anliegen) (?:ist|wurde) (?:gespeichert|hinterlegt|gemeldet)|"
        r"gespeichertes anliegen|gemeldetes problem)", question,
    ):
        return f"Das gemeldete Anliegen bei Ticket **{ticket_id}** lautet:\n**{ticket.get('problem') or '-'}**"

    if re.fullmatch(
        r"(?:(?:welche|welcher) (?:telefonnummer|nummer|name|kontaktdaten) "
        r"(?:ist|sind|habt ihr) (?:bei euch |von mir |im ticket )?(?:gespeichert|hinterlegt)|"
        r"(?:meine |gespeicherte )?(?:kontaktdaten|telefonnummer|kundenname))", question,
    ):
        return (
            f"Gespeicherte Kontaktdaten zu Ticket **{ticket_id}**:\n"
            f"- Kunde: {ticket.get('name') or ticket.get('kunde_name') or '-'}\n"
            f"- Telefon: {ticket.get('telefon') or '-'}"
        )

    if re.fullmatch(r"(?:wie (?:ist|lautet) (?:meine |die )?)?ticket(?:nummer|-nr\.?|nr)?", question):
        return f"Ihre Ticketnummer ist **{ticket_id}**."

    if re.fullmatch(
        r"(?:(?:gibt es|habt ihr) (?:eine |neue )?(?:notiz|antwort)|"
        r"(?:letzte |neueste )?(?:notiz|notizen|antwort)(?: der werkstatt)?)", question,
    ):
        latest_note = _get_latest_customer_reply(ticket)
        if latest_note:
            return (
                f"Letzte Nachricht der Werkstatt zu Ticket **{ticket_id}**:\n"
                f"{latest_note.get('text') or '-'}\n"
                f"Erstellt: {latest_note.get('created_at') or '-'}"
            )
        return f"Zu Ticket **{ticket_id}** liegt aktuell noch keine Antwort der Werkstatt an den Kunden vor."

    if re.fullmatch(r"(?:zusammenfassung|zusammenfassen|zusammengefasst|(?:zeige?|anzeigen)(?: (?:das|mein))?(?: ticket)?|ticket anzeigen|alles zu dem ticket)", question):
        return _build_ticket_summary(ticket)
    if not question and extract_ticket_reference(user_message):
        return _build_ticket_summary(ticket)
    # A verified phone lookup may show its matching ticket, but never creates
    # authority: _resolve_ticket_for_state already applied CustomerAccess.
    if extract_phone_reference(user_message) and re.fullmatch(
        r"(?:meine? (?:telefonnummer|nummer|telefon) (?:ist|lautet) )?[+\d ()/-]+", lower(user_message)
    ):
        return _build_ticket_summary(ticket)

    return stored_workshop_answer(user_message, get_workshop(ticket.get("workshop_id")))


def handle_existing_ticket(
    state: IntakeState,
    user_message: str | None,
    *,
    customer_access: CustomerAccess | None = None,
    message_id: str | None = None,
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
    state.mode = "existing"
    workshop_id = getattr(state, "workshop_id", None)

    ticket, error_reply = _resolve_ticket_for_state(state, msg, customer_access=customer_access)
    if error_reply:
        return state, error_reply, False

    if not ticket:
        return state, "Ich konnte kein passendes bestehendes Ticket ermitteln.", False

    state.ticket_id = str(ticket.get("ticket_id") or "")
    reply = _stored_ticket_answer(ticket, msg)
    message_id = message_id or uuid.uuid4().hex
    automatic = reply is not None
    acknowledgement = _is_acknowledgement(msg)
    question = not automatic and not acknowledgement and _is_customer_question(msg)
    add_ticket_note(
        state.ticket_id,
        msg,
        note_type="customer_message",
        workshop_id=workshop_id,
        sender_role="customer",
        purpose="customer_question" if question else "customer_information",
        requires_human_action=not automatic and not acknowledgement,
        message_id=message_id,
    )
    if automatic:
        add_ticket_note(
            state.ticket_id,
            reply,
            workshop_id=workshop_id,
            sender_role="assistant",
            purpose="automatic_answer",
            requires_human_action=False,
            reply_to_message_id=message_id,
        )
        return state, reply, False
    if acknowledgement:
        return state, "", False
    subject = "Frage" if question else "Nachricht"
    reply = (
        f"Ich habe Ihre {subject} zu Ticket **{state.ticket_id}** an die Werkstatt weitergegeben. "
        "Die Werkstatt kümmert sich darum."
    )
    add_ticket_note(
        state.ticket_id,
        reply,
        workshop_id=workshop_id,
        sender_role="assistant",
        purpose="automatic_answer",
        requires_human_action=False,
        reply_to_message_id=message_id,
    )
    return state, reply, False
