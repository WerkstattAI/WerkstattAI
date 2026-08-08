from __future__ import annotations

import unittest
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import authenticate_user, create_session_token, decode_session_token
from app.admin import (
    create_workshop_account,
    get_workshop_account,
    list_workshop_accounts,
    reset_workshop_owner_password,
    update_workshop_account,
)
from app.db import get_conn, init_db
from app.config import settings
from app.conversation.analysis import analyze_problem
from app.conversation.existing_ticket import handle_existing_ticket
from app.conversation.fallback import handle_unclear_request
from app.conversation.general_question import handle_general_question
from app.conversation.new_request import handle_new_request
from app.conversation.quote_request import handle_quote_request
from app.conversation.intent import (
    INTENT_EXISTING_TICKET,
    INTENT_GENERAL_QUESTION,
    INTENT_NEW_REQUEST,
    INTENT_QUOTE_REQUEST,
    INTENT_UNCLEAR,
    detect_intent,
)
from app.conversation.router import next_step
from app.models import IntakeState
from app.main import (
    StatusUpdate,
    patch_ticket_status,
    ticket_by_id,
    tickets,
    process_chat_message,
    subscription,
    whatsapp_session_id,
    whatsapp_webhook,
    whatsapp_webhook_verify_alt,
    whatsapp_webhook_verify,
)
from app.subscriptions import get_subscription, is_subscription_active
from app.tickets import (
    add_ticket_note,
    find_ticket_by_id,
    find_tickets_by_phone,
    list_latest_tickets,
    save_ticket,
)
from app.whatsapp import (
    build_signature,
    list_whatsapp_conversations,
    list_whatsapp_messages,
    parse_meta_messages,
    parse_meta_statuses,
    save_whatsapp_message,
    WhatsAppSendResult,
)
from app.web import (
    datenschutz_page,
    dashboard_admin_workshops,
    dashboard_admin_workshops_create,
    dashboard_admin_workshop_reset_password,
    dashboard_admin_workshop_update,
    dashboard_settings_save,
    dashboard_whatsapp_reply,
    dashboard_whatsapp_test,
    _whatsapp_readiness,
    _workshop_id_for_request,
)
from app.workshops import get_workshop, update_workshop


def _asgi_request(body: bytes, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhooks/whatsapp",
        "headers": raw_headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _dashboard_request(workshop_id: str = "demo-werkstatt", role: str = "owner") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/dashboard/whatsapp/reply",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    request.state.user = {
        "email": "admin@werkstatt.local",
        "workshop_id": workshop_id,
        "role": role,
    }
    return request


def _get_request(path: str = "/webhooks/whatsapp") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _anonymous_dashboard_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/tickets",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("testclient", 50000),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


class IntentTests(unittest.TestCase):
    def test_short_contact_question_is_general(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kontakt"),
            INTENT_GENERAL_QUESTION,
        )

    def test_phone_number_is_existing_ticket_reference(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Meine Nummer ist 0176 1234567"),
            INTENT_EXISTING_TICKET,
        )

    def test_inline_vehicle_data_starts_new_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "VW Golf 2018 95000 km"),
            INTENT_NEW_REQUEST,
        )

    def test_known_vehicle_without_year_starts_new_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "VW Golf"),
            INTENT_NEW_REQUEST,
        )

    def test_plain_greeting_does_not_start_new_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Hallo"),
            INTENT_UNCLEAR,
        )

    def test_quote_question_is_quote_request(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Was kostet ein Zahnriemenwechsel?"),
            INTENT_QUOTE_REQUEST,
        )

    def test_location_question_is_general(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Wo ist eure Werkstatt?"),
            INTENT_GENERAL_QUESTION,
        )

    def test_unclear_ai_style_request_is_not_new_ticket(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kannst du mir einen Text schreiben?"),
            INTENT_UNCLEAR,
        )

    def test_generic_help_request_is_unclear(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Kannst du helfen?"),
            INTENT_UNCLEAR,
        )

    def test_unclear_message_does_not_start_new_request(self) -> None:
        state, reply, done = next_step(IntakeState(), "Kannst du mir helfen?")

        self.assertFalse(done)
        self.assertEqual(state.mode, "unknown")
        self.assertIn("kein freier KI-Chat", reply)

    def test_unclear_reply_does_not_reset_active_intake_context(self) -> None:
        state = IntakeState(
            mode="new",
            step="telefon",
            fahrzeug="VW Golf",
            baujahr="2017",
            kilometerstand="142000",
            problem="kontrollleuchte und ruckeln",
        )

        state, _, done = handle_unclear_request(state, "Am staerksten beim Beschleunigen")

        self.assertFalse(done)
        self.assertEqual(state.mode, "new")
        self.assertEqual(state.step, "telefon")

        state, reply, done = next_step(state, "0176 12345678")

        self.assertFalse(done)
        self.assertEqual(state.mode, "new")
        self.assertEqual(state.step, "name")
        self.assertEqual(state.telefon, "017612345678")
        self.assertIn("ansprechen", reply)

    def test_active_followup_keeps_new_request_intent(self) -> None:
        state = IntakeState(
            mode="new",
            step="followup",
            problem="Motorkontrollleuchte leuchtet und das Auto ruckelt beim Beschleunigen",
            followup_questions=[
                "Wie verhält sich das Fahrzeug genau beim Fahren? Ruckeln, Leistungsverlust, Aussetzer oder Notlauf?"
            ],
            followup_index=0,
        )

        self.assertEqual(
            detect_intent(state, "Am staerksten beim Beschleunigen bei niedriger Drehzahl"),
            INTENT_NEW_REQUEST,
        )

    def test_existing_ticket_mode_can_switch_to_new_request(self) -> None:
        state = IntakeState(mode="existing", ticket_id="WS-20260505-0005")

        self.assertEqual(
            detect_intent(state, "Ich möchte ein Problem melden."),
            INTENT_NEW_REQUEST,
        )


    def test_existing_ticket_mode_can_switch_to_general_question(self) -> None:
        state = IntakeState(mode="existing", ticket_id="WS-20260505-0005")

        self.assertEqual(
            detect_intent(state, "Welche Öffnungszeiten habt ihr?"),
            INTENT_GENERAL_QUESTION,
        )

    def test_general_price_overview_is_not_started_as_quote(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Habt ihr eine Preisliste?"),
            INTENT_GENERAL_QUESTION,
        )

    def test_specific_repair_price_still_starts_quote(self) -> None:
        self.assertEqual(
            detect_intent(IntakeState(), "Was kostet ein Ölwechsel?"),
            INTENT_QUOTE_REQUEST,
        )


class IntentMatrixTests(unittest.TestCase):
    CASES = [
        # Problem melden
        ("Mein Auto springt nicht an", INTENT_NEW_REQUEST),
        ("Die Motorkontrollleuchte leuchtet", INTENT_NEW_REQUEST),
        ("VW Golf 2018 95000 km", INTENT_NEW_REQUEST),
        ("Ich habe ein Problem mit der Bremse", INTENT_NEW_REQUEST),
        ("Problem melden", INTENT_NEW_REQUEST),
        # Kostenvoranschlag anfragen
        ("Was kostet ein Ölwechsel?", INTENT_QUOTE_REQUEST),
        ("Ich brauche ein Angebot für Kupplung wechseln", INTENT_QUOTE_REQUEST),
        ("Wie teuer ist ein Reifenwechsel?", INTENT_QUOTE_REQUEST),
        ("Kostenvoranschlag anfragen", INTENT_QUOTE_REQUEST),
        ("Preis für Bremsen wechseln bitte", INTENT_QUOTE_REQUEST),
        # Anfrage zu einem bestehenden Ticket
        ("Wie ist der Status von Ticket WS-20260505-0005?", INTENT_EXISTING_TICKET),
        ("Ist mein Auto schon fertig? Ticket WS-20260505-0005", INTENT_EXISTING_TICKET),
        ("Meine Telefonnummer ist 0176 1234567", INTENT_EXISTING_TICKET),
        ("Anfrage zu einem bestehenden Ticket", INTENT_EXISTING_TICKET),
        ("Kann ich mein Fahrzeug zu Auftrag 123 abholen?", INTENT_EXISTING_TICKET),
        # Allgemeine Frage
        ("Wie sind eure Öffnungszeiten?", INTENT_GENERAL_QUESTION),
        ("Wo ist eure Werkstatt?", INTENT_GENERAL_QUESTION),
        ("Welche Telefonnummer habt ihr?", INTENT_GENERAL_QUESTION),
        ("Welche Leistungen bietet ihr an?", INTENT_GENERAL_QUESTION),
        ("Habt ihr einen Abschleppdienst?", INTENT_GENERAL_QUESTION),
        # Unclear / kontrollierter Fallback
        ("Kannst du mir helfen?", INTENT_UNCLEAR),
        ("Schreib mir eine Antwort", INTENT_UNCLEAR),
        ("Formuliere mir bitte eine Nachricht", INTENT_UNCLEAR),
        ("Hallo", INTENT_UNCLEAR),
        ("Was soll ich machen?", INTENT_UNCLEAR),
    ]

    def test_common_customer_messages_route_to_expected_intent(self) -> None:
        for message, expected in self.CASES:
            with self.subTest(message=message):
                self.assertEqual(detect_intent(IntakeState(), message), expected)


class MessyCustomerIntentTests(unittest.TestCase):
    CASES = [
        # Umgangssprachliche oder ungenaue Problemtexte
        ("auto kaputt", INTENT_NEW_REQUEST),
        ("karre geht nicht an", INTENT_NEW_REQUEST),
        ("mein wagen macht komische geräusche", INTENT_NEW_REQUEST),
        ("irgendwas stinkt beim fahren", INTENT_NEW_REQUEST),
        ("motor leuchtet gelb und ruckelt", INTENT_NEW_REQUEST),
        ("bremsen machen komische geraeusche", INTENT_NEW_REQUEST),
        ("hilfe mein auto startet nicht", INTENT_NEW_REQUEST),
        # Kostenfragen ohne perfekte Formulierung
        ("wieviel kostet ölwechsel", INTENT_QUOTE_REQUEST),
        ("was kostet kupplung wechseln ungefähr", INTENT_QUOTE_REQUEST),
        ("preis bremsen wechseln?", INTENT_QUOTE_REQUEST),
        ("ungefähr kosten für reifenwechsel", INTENT_QUOTE_REQUEST),
        ("angebot fuer service bitte", INTENT_QUOTE_REQUEST),
        # Bestehendes Ticket ohne perfekte Formulierung
        ("ticket ws-20260505-0005 status?", INTENT_EXISTING_TICKET),
        ("hab ticket WS-20260505-0005, auto fertig?", INTENT_EXISTING_TICKET),
        ("auftrag 123 was ist los", INTENT_EXISTING_TICKET),
        ("meine nummer wegen ticket ist 0176 1234567", INTENT_EXISTING_TICKET),
        # Allgemeine Kundenfragen
        ("wann habt ihr offen", INTENT_GENERAL_QUESTION),
        ("wo genau seid ihr", INTENT_GENERAL_QUESTION),
        ("habt ihr samstags offen?", INTENT_GENERAL_QUESTION),
        ("macht ihr auch abschleppen?", INTENT_GENERAL_QUESTION),
        ("was macht eure werkstatt alles?", INTENT_GENERAL_QUESTION),
        # Freiform- oder sehr unklare Nachrichten
        ("schreib mal bitte eine nachricht", INTENT_UNCLEAR),
        ("antwort mir wie eine ki", INTENT_UNCLEAR),
        ("ich weiss nicht was ich schreiben soll", INTENT_UNCLEAR),
        ("hallo guten tag", INTENT_UNCLEAR),
        ("???", INTENT_UNCLEAR),
    ]

    def test_messy_customer_messages_route_safely(self) -> None:
        for message, expected in self.CASES:
            with self.subTest(message=message):
                self.assertEqual(detect_intent(IntakeState(), message), expected)


class WhatsAppWebhookTests(unittest.TestCase):
    def test_datenschutz_page_is_publicly_renderable(self) -> None:
        response = datenschutz_page(_get_request("/datenschutz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.template.name, "datenschutz.html")

    META_PAYLOAD = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "49123456789",
                                "phone_number_id": "wa-phone-123",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Max Kunde"},
                                    "wa_id": "4917612345678",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "4917612345678",
                                    "id": "wamid.test-message-1",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "Hallo"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    STATUS_PAYLOAD = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "49123456789",
                                "phone_number_id": "wa-phone-123",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.outbound-status-1",
                                    "status": "delivered",
                                    "timestamp": "1710000060",
                                    "recipient_id": "4917612345678",
                                    "conversation": {"id": "conversation-1"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    def test_whatsapp_session_id_uses_normalized_phone(self) -> None:
        self.assertEqual(
            whatsapp_session_id("+49 176 123 456 78"),
            "whatsapp:4917612345678",
        )

    def test_meta_webhook_verification_accepts_valid_token(self) -> None:
        old_token = settings.whatsapp_verify_token
        object.__setattr__(settings, "whatsapp_verify_token", "verify-test-token")
        try:
            response = whatsapp_webhook_verify(
                _get_request(),
                mode="subscribe",
                verify_token="verify-test-token",
                challenge="challenge-123",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.body.decode("utf-8"), "challenge-123")
        finally:
            object.__setattr__(settings, "whatsapp_verify_token", old_token)

    def test_alt_meta_webhook_verification_accepts_valid_token(self) -> None:
        old_token = settings.whatsapp_verify_token
        object.__setattr__(settings, "whatsapp_verify_token", "verify-test-token")
        try:
            response = whatsapp_webhook_verify_alt(
                _get_request("/meta/whatsapp"),
                mode="subscribe",
                verify_token="verify-test-token",
                challenge="challenge-123",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.body.decode("utf-8"), "challenge-123")
        finally:
            object.__setattr__(settings, "whatsapp_verify_token", old_token)

    def test_meta_webhook_verification_rejects_wrong_token(self) -> None:
        old_token = settings.whatsapp_verify_token
        object.__setattr__(settings, "whatsapp_verify_token", "verify-test-token")
        try:
            with self.assertRaises(HTTPException) as ctx:
                whatsapp_webhook_verify(
                    _get_request(),
                    mode="subscribe",
                    verify_token="wrong",
                    challenge="challenge-123",
                )

            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            object.__setattr__(settings, "whatsapp_verify_token", old_token)

    def test_meta_payload_parser_extracts_text_message(self) -> None:
        messages = parse_meta_messages(self.META_PAYLOAD)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].phone_number_id, "wa-phone-123")
        self.assertEqual(messages[0].display_phone_number, "49123456789")
        self.assertEqual(messages[0].from_phone, "4917612345678")
        self.assertEqual(messages[0].message_id, "wamid.test-message-1")
        self.assertEqual(messages[0].text, "Hallo")

    def test_meta_payload_parser_extracts_status_event(self) -> None:
        statuses = parse_meta_statuses(self.STATUS_PAYLOAD)

        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].phone_number_id, "wa-phone-123")
        self.assertEqual(statuses[0].wa_message_id, "wamid.outbound-status-1")
        self.assertEqual(statuses[0].recipient_phone, "4917612345678")
        self.assertEqual(statuses[0].status, "delivered")

    def test_meta_webhook_rejects_invalid_signature(self) -> None:
        old_secret = settings.whatsapp_app_secret
        object.__setattr__(settings, "whatsapp_app_secret", "secret-test")
        try:
            request = _asgi_request(
                json.dumps(self.META_PAYLOAD).encode("utf-8"),
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": "sha256=wrong",
                },
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(whatsapp_webhook(request))

            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            object.__setattr__(settings, "whatsapp_app_secret", old_secret)

    def test_meta_webhook_processes_text_message_for_mapped_workshop(self) -> None:
        init_db()
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET
                    whatsapp_phone_number_id = ?,
                    whatsapp_display_phone_number = ?,
                    subscription_status = 'trialing',
                    trial_ends_at = ?
                WHERE id = ?
                """,
                ("wa-phone-123", "49123456789", trial_ends_at, "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM conversation_sessions
                WHERE session_id = ?
                """,
                ("demo-werkstatt:whatsapp:4917612345678",),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917612345678"),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_events
                WHERE wa_message_id = ?
                """,
                ("wamid.test-message-1",),
            )
            conn.commit()

        old_secret = settings.whatsapp_app_secret
        old_token = settings.whatsapp_access_token
        object.__setattr__(settings, "whatsapp_app_secret", "secret-test")
        object.__setattr__(settings, "whatsapp_access_token", "")
        body = json.dumps(self.META_PAYLOAD, separators=(",", ":")).encode("utf-8")
        try:
            request = _asgi_request(
                body,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": build_signature(body, "secret-test"),
                },
            )
            payload = asyncio.run(whatsapp_webhook(request))

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["processed"], 1)
            self.assertEqual(payload["ignored"], 0)
            self.assertEqual(payload["replies"][0]["workshop_id"], "demo-werkstatt")

            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT wa_message_id, from_phone, text
                    FROM whatsapp_events
                    WHERE wa_message_id = ?
                    LIMIT 1
                    """,
                    ("wamid.test-message-1",),
                ).fetchone()

            self.assertIsNotNone(row)
            self.assertEqual(row["from_phone"], "4917612345678")
            self.assertEqual(row["text"], "Hallo")

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917612345678",
            )
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["direction"], "inbound")
            self.assertEqual(messages[0]["wa_message_id"], "wamid.test-message-1")
            self.assertEqual(messages[0]["text"], "Hallo")
            self.assertEqual(messages[1]["direction"], "outbound")
            self.assertEqual(messages[1]["status"], "sent_local")
            self.assertIn("kein freier KI-Chat", messages[1]["text"])
        finally:
            object.__setattr__(settings, "whatsapp_app_secret", old_secret)
            object.__setattr__(settings, "whatsapp_access_token", old_token)

    def test_meta_webhook_sends_auto_reply_when_access_token_is_configured(self) -> None:
        init_db()
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET
                    whatsapp_phone_number_id = ?,
                    whatsapp_display_phone_number = ?,
                    subscription_status = 'trialing',
                    trial_ends_at = ?
                WHERE id = ?
                """,
                ("wa-phone-123", "49123456789", trial_ends_at, "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM conversation_sessions
                WHERE session_id = ?
                """,
                ("demo-werkstatt:whatsapp:4917612345678",),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917612345678"),
            )
            conn.commit()

        old_secret = settings.whatsapp_app_secret
        old_token = settings.whatsapp_access_token
        object.__setattr__(settings, "whatsapp_app_secret", "secret-test")
        object.__setattr__(settings, "whatsapp_access_token", "test-access-token")
        body = json.dumps(self.META_PAYLOAD, separators=(",", ":")).encode("utf-8")
        try:
            with patch("app.main.send_whatsapp_text_message") as send_mock:
                send_mock.return_value = WhatsAppSendResult(
                    ok=True,
                    status_code=200,
                    wa_message_id="wamid.auto-reply-1",
                    payload={"messages": [{"id": "wamid.auto-reply-1"}]},
                )
                payload = asyncio.run(
                    whatsapp_webhook(
                        _asgi_request(
                            body,
                            headers={
                                "content-type": "application/json",
                                "x-hub-signature-256": build_signature(body, "secret-test"),
                            },
                        )
                    )
                )

            self.assertEqual(payload["processed"], 1)
            self.assertEqual(payload["replies"][0]["send_status"], "sent")
            self.assertEqual(payload["replies"][0]["outbound_wa_message_id"], "wamid.auto-reply-1")
            self.assertEqual(send_mock.call_args.kwargs["phone_number_id"], "wa-phone-123")
            self.assertEqual(send_mock.call_args.kwargs["customer_phone"], "4917612345678")
            self.assertEqual(send_mock.call_args.kwargs["access_token"], "test-access-token")

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917612345678",
            )
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[1]["direction"], "outbound")
            self.assertEqual(messages[1]["status"], "sent")
            self.assertEqual(messages[1]["wa_message_id"], "wamid.auto-reply-1")
            self.assertIn('"local_only": false', messages[1]["payload_json"])
        finally:
            object.__setattr__(settings, "whatsapp_app_secret", old_secret)
            object.__setattr__(settings, "whatsapp_access_token", old_token)

    def test_meta_webhook_duplicate_message_is_not_reprocessed(self) -> None:
        init_db()
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET
                    whatsapp_phone_number_id = ?,
                    subscription_status = 'trialing',
                    trial_ends_at = ?
                WHERE id = ?
                """,
                ("wa-phone-123", trial_ends_at, "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM conversation_sessions
                WHERE session_id = ?
                """,
                ("demo-werkstatt:whatsapp:4917612345678",),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917612345678"),
            )
            conn.commit()

        old_secret = settings.whatsapp_app_secret
        object.__setattr__(settings, "whatsapp_app_secret", "secret-test")
        body = json.dumps(self.META_PAYLOAD, separators=(",", ":")).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-hub-signature-256": build_signature(body, "secret-test"),
        }
        try:
            first = asyncio.run(whatsapp_webhook(_asgi_request(body, headers=headers)))
            second = asyncio.run(whatsapp_webhook(_asgi_request(body, headers=headers)))

            self.assertEqual(first["processed"], 1)
            self.assertEqual(second["processed"], 0)
            self.assertEqual(second["ignored"], 1)

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917612345678",
            )
            self.assertEqual(len(messages), 2)
        finally:
            object.__setattr__(settings, "whatsapp_app_secret", old_secret)

    def test_meta_webhook_updates_outbound_message_status(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET whatsapp_phone_number_id = ?
                WHERE id = ?
                """,
                ("wa-phone-123", "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND wa_message_id = ?
                """,
                ("demo-werkstatt", "wamid.outbound-status-1"),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_events
                WHERE wa_message_id = ?
                """,
                ("wamid.outbound-status-1",),
            )
            conn.commit()

        save_whatsapp_message(
            workshop_id="demo-werkstatt",
            phone_number_id="wa-phone-123",
            customer_phone="4917612345678",
            direction="outbound",
            message_type="text",
            text="Ihre Anfrage wurde aufgenommen.",
            wa_message_id="wamid.outbound-status-1",
            status="sent",
            payload={"meta_response": {"messages": [{"id": "wamid.outbound-status-1"}]}},
        )

        old_secret = settings.whatsapp_app_secret
        object.__setattr__(settings, "whatsapp_app_secret", "secret-test")
        body = json.dumps(self.STATUS_PAYLOAD, separators=(",", ":")).encode("utf-8")
        try:
            payload = asyncio.run(
                whatsapp_webhook(
                    _asgi_request(
                        body,
                        headers={
                            "content-type": "application/json",
                            "x-hub-signature-256": build_signature(body, "secret-test"),
                        },
                    )
                )
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["processed"], 0)
            self.assertEqual(payload["status_updates"], 1)
            self.assertEqual(payload["ignored"], 0)

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917612345678",
            )
            matching = [
                message for message in messages
                if message["wa_message_id"] == "wamid.outbound-status-1"
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["status"], "delivered")
            self.assertIn("status_events", matching[0]["payload_json"])
        finally:
            object.__setattr__(settings, "whatsapp_app_secret", old_secret)
            with get_conn() as conn:
                conn.execute(
                    """
                    DELETE FROM whatsapp_messages
                    WHERE workshop_id = ? AND wa_message_id = ?
                    """,
                    ("demo-werkstatt", "wamid.outbound-status-1"),
                )
                conn.execute(
                    """
                    DELETE FROM whatsapp_events
                    WHERE wa_message_id = ?
                    """,
                    ("wamid.outbound-status-1",),
                )
                conn.commit()

    def test_whatsapp_message_history_is_scoped_by_workshop(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id IN (?, ?) AND customer_phone = ?
                """,
                ("tenant-a", "tenant-b", "4917612345678"),
            )
            conn.commit()

        save_whatsapp_message(
            workshop_id="tenant-a",
            phone_number_id="phone-a",
            customer_phone="4917612345678",
            direction="inbound",
            text="Nachricht fuer A",
            wa_message_id="wamid.tenant-a",
        )
        save_whatsapp_message(
            workshop_id="tenant-b",
            phone_number_id="phone-b",
            customer_phone="4917612345678",
            direction="inbound",
            text="Nachricht fuer B",
            wa_message_id="wamid.tenant-b",
        )

        messages_a = list_whatsapp_messages(
            workshop_id="tenant-a",
            customer_phone="4917612345678",
        )
        messages_b = list_whatsapp_messages(
            workshop_id="tenant-b",
            customer_phone="4917612345678",
        )

        self.assertEqual([m["text"] for m in messages_a], ["Nachricht fuer A"])
        self.assertEqual([m["text"] for m in messages_b], ["Nachricht fuer B"])

    def test_whatsapp_conversation_list_groups_latest_message(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917611111111"),
            )
            conn.commit()

        save_whatsapp_message(
            workshop_id="demo-werkstatt",
            phone_number_id="wa-phone-123",
            customer_phone="4917611111111",
            direction="inbound",
            text="Erste Nachricht",
            wa_message_id="wamid.group-1",
        )
        save_whatsapp_message(
            workshop_id="demo-werkstatt",
            phone_number_id="wa-phone-123",
            customer_phone="4917611111111",
            direction="outbound",
            text="Antwort vom Bot",
            status="sent_local",
        )

        conversations = list_whatsapp_conversations(workshop_id="demo-werkstatt")
        selected = [
            conversation
            for conversation in conversations
            if conversation["customer_phone"] == "4917611111111"
        ]

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["message_count"], 2)
        self.assertEqual(selected[0]["last_direction"], "outbound")
        self.assertEqual(selected[0]["last_text"], "Antwort vom Bot")

    def test_whatsapp_readiness_uses_request_webhook_url_by_default(self) -> None:
        old_public_url = settings.whatsapp_webhook_public_url
        object.__setattr__(settings, "whatsapp_webhook_public_url", "")
        try:
            readiness = _whatsapp_readiness(_get_request(), {"whatsapp_phone_number_id": ""})

            self.assertEqual(readiness["webhook_url"], "http://testserver/webhooks/whatsapp")
            self.assertEqual(readiness["webhook_url_source"], "request")
        finally:
            object.__setattr__(settings, "whatsapp_webhook_public_url", old_public_url)

    def test_whatsapp_readiness_prefers_configured_public_webhook_url(self) -> None:
        old_public_url = settings.whatsapp_webhook_public_url
        object.__setattr__(
            settings,
            "whatsapp_webhook_public_url",
            "https://werkstattai-whatsapp.example.workers.dev",
        )
        try:
            readiness = _whatsapp_readiness(_get_request(), {"whatsapp_phone_number_id": ""})

            self.assertEqual(
                readiness["webhook_url"],
                "https://werkstattai-whatsapp.example.workers.dev",
            )
            self.assertEqual(readiness["webhook_url_source"], "configured")
        finally:
            object.__setattr__(settings, "whatsapp_webhook_public_url", old_public_url)

    def test_dashboard_whatsapp_reply_is_saved_as_local_outbound_message(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917622222222"),
            )
            conn.commit()

        response = dashboard_whatsapp_reply(
            _dashboard_request(),
            customer_phone="4917622222222",
            reply_text="Wir melden uns gleich mit einer Einschaetzung.",
            workshop_id="ignored-by-authenticated-user",
        )

        self.assertEqual(response.status_code, 303)
        messages = list_whatsapp_messages(
            workshop_id="demo-werkstatt",
            customer_phone="4917622222222",
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["direction"], "outbound")
        self.assertEqual(messages[0]["status"], "sent_local")
        self.assertEqual(messages[0]["text"], "Wir melden uns gleich mit einer Einschaetzung.")

    def test_dashboard_whatsapp_reply_sends_with_meta_when_configured(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET whatsapp_phone_number_id = ?
                WHERE id = ?
                """,
                ("wa-phone-123", "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917633333333"),
            )
            conn.commit()

        old_token = settings.whatsapp_access_token
        object.__setattr__(settings, "whatsapp_access_token", "test-access-token")
        try:
            with patch("app.web.send_whatsapp_text_message") as send_mock:
                send_mock.return_value = WhatsAppSendResult(
                    ok=True,
                    status_code=200,
                    wa_message_id="wamid.outbound-1",
                    payload={"messages": [{"id": "wamid.outbound-1"}]},
                )

                response = dashboard_whatsapp_reply(
                    _dashboard_request(),
                    customer_phone="4917633333333",
                    reply_text="Ihr Fahrzeug ist fertig.",
                    workshop_id="ignored-by-authenticated-user",
                )

            self.assertEqual(response.status_code, 303)
            send_mock.assert_called_once()
            self.assertEqual(send_mock.call_args.kwargs["phone_number_id"], "wa-phone-123")
            self.assertEqual(send_mock.call_args.kwargs["customer_phone"], "4917633333333")

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917633333333",
            )

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["direction"], "outbound")
            self.assertEqual(messages[0]["status"], "sent")
            self.assertEqual(messages[0]["wa_message_id"], "wamid.outbound-1")
        finally:
            object.__setattr__(settings, "whatsapp_access_token", old_token)

    def test_dashboard_whatsapp_test_requires_access_token(self) -> None:
        init_db()

        old_token = settings.whatsapp_access_token
        object.__setattr__(settings, "whatsapp_access_token", "")
        try:
            with patch("app.web.send_whatsapp_text_message") as send_mock:
                response = dashboard_whatsapp_test(
                    _dashboard_request(),
                    test_phone="4917644444444",
                    test_text="Test",
                    workshop_id="ignored-by-authenticated-user",
                )

            self.assertEqual(response.status_code, 303)
            self.assertIn("test_status=failed", response.headers["location"])
            self.assertIn("WHATSAPP_ACCESS_TOKEN", response.headers["location"])
            send_mock.assert_not_called()
        finally:
            object.__setattr__(settings, "whatsapp_access_token", old_token)

    def test_dashboard_whatsapp_test_sends_and_saves_success(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET whatsapp_phone_number_id = ?
                WHERE id = ?
                """,
                ("wa-phone-test", "demo-werkstatt"),
            )
            conn.execute(
                """
                DELETE FROM whatsapp_messages
                WHERE workshop_id = ? AND customer_phone = ?
                """,
                ("demo-werkstatt", "4917655555555"),
            )
            conn.commit()

        old_token = settings.whatsapp_access_token
        object.__setattr__(settings, "whatsapp_access_token", "test-access-token")
        try:
            with patch("app.web.send_whatsapp_text_message") as send_mock:
                send_mock.return_value = WhatsAppSendResult(
                    ok=True,
                    status_code=200,
                    wa_message_id="wamid.test-send-1",
                    payload={"messages": [{"id": "wamid.test-send-1"}]},
                )

                response = dashboard_whatsapp_test(
                    _dashboard_request(),
                    test_phone="4917655555555",
                    test_text="Testnachricht",
                    workshop_id="ignored-by-authenticated-user",
                )

            self.assertEqual(response.status_code, 303)
            self.assertIn("test_status=sent", response.headers["location"])
            send_mock.assert_called_once()
            self.assertEqual(send_mock.call_args.kwargs["phone_number_id"], "wa-phone-test")
            self.assertEqual(send_mock.call_args.kwargs["customer_phone"], "4917655555555")

            messages = list_whatsapp_messages(
                workshop_id="demo-werkstatt",
                customer_phone="4917655555555",
            )

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["direction"], "outbound")
            self.assertEqual(messages[0]["status"], "sent")
            self.assertEqual(messages[0]["wa_message_id"], "wamid.test-send-1")
        finally:
            object.__setattr__(settings, "whatsapp_access_token", old_token)

    def test_workshop_settings_store_whatsapp_number_config(self) -> None:
        init_db()

        update_workshop(
            "settings-whatsapp-test",
            name="WhatsApp Test Werkstatt",
            address="Teststrasse 1",
            phone="012345",
            email="test@example.com",
            opening_hours="Montag bis Freitag: 09:00-17:00",
            services="Reifenwechsel",
            pricing_info="Nach Absprache",
            towing_info="Partnerdienst",
            whatsapp_phone_number_id="wa-settings-123",
            whatsapp_display_phone_number="+49 176 55555555",
        )

        workshop = get_workshop("settings-whatsapp-test")

        self.assertEqual(workshop["whatsapp_phone_number_id"], "wa-settings-123")
        self.assertEqual(workshop["whatsapp_display_phone_number"], "+49 176 55555555")

    def test_dashboard_settings_save_uses_authenticated_workshop(self) -> None:
        init_db()

        response = dashboard_settings_save(
            _dashboard_request("demo-werkstatt"),
            workshop_id="other-workshop",
            name="Demo Settings Werkstatt",
            address="Demo Strasse 7",
            phone="0176000000",
            email="demo@example.com",
            opening_hours="Montag bis Freitag: 08:00-16:00",
            services="Service, Reifen",
            pricing_info="Individuell",
            towing_info="Abschlepppartner",
            whatsapp_phone_number_id="wa-demo-secure",
            whatsapp_display_phone_number="+49 176 000000",
        )

        self.assertEqual(response.status_code, 303)

        demo = get_workshop("demo-werkstatt")
        other = get_workshop("other-workshop")

        self.assertEqual(demo["whatsapp_phone_number_id"], "wa-demo-secure")
        self.assertEqual(demo["whatsapp_display_phone_number"], "+49 176 000000")
        self.assertNotEqual(other["whatsapp_phone_number_id"], "wa-demo-secure")


class AuthTests(unittest.TestCase):
    def test_default_dashboard_admin_can_authenticate(self) -> None:
        init_db()

        user = authenticate_user(
            settings.dashboard_admin_email,
            settings.dashboard_admin_password,
        )

        self.assertIsNotNone(user)
        self.assertEqual(user["workshop_id"], "demo-werkstatt")

    def test_session_token_roundtrip(self) -> None:
        user = {
            "email": "admin@werkstatt.local",
            "workshop_id": "demo-werkstatt",
            "role": "owner",
        }

        token = create_session_token(user)
        decoded = decode_session_token(token)

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["email"], user["email"])
        self.assertEqual(decoded["workshop_id"], user["workshop_id"])
        self.assertEqual(decoded["role"], user["role"])

    def test_tampered_session_token_is_rejected(self) -> None:
        user = {
            "email": "admin@werkstatt.local",
            "workshop_id": "demo-werkstatt",
            "role": "owner",
        }

        token = create_session_token(user)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        self.assertIsNone(decode_session_token(tampered))


class AdminWorkshopTests(unittest.TestCase):
    WORKSHOP_ID = "admin-panel-test"
    ADMIN_EMAIL = "owner.admin-panel-test@example.com"

    def setUp(self) -> None:
        init_db()
        with get_conn() as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (self.ADMIN_EMAIL,))
            conn.execute("DELETE FROM workshops WHERE id = ?", (self.WORKSHOP_ID,))
            conn.commit()

    def tearDown(self) -> None:
        with get_conn() as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (self.ADMIN_EMAIL,))
            conn.execute("DELETE FROM workshops WHERE id = ?", (self.WORKSHOP_ID,))
            conn.commit()

    def test_create_workshop_account_creates_owner_login(self) -> None:
        account = create_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
            address="Testweg 9",
            phone="0123",
            email="kontakt@example.com",
            services="Service",
            whatsapp_phone_number_id="wa-admin-panel-test",
        )

        self.assertEqual(account["id"], self.WORKSHOP_ID)

        user = authenticate_user(self.ADMIN_EMAIL, "startpass123")
        self.assertIsNotNone(user)
        self.assertEqual(user["workshop_id"], self.WORKSHOP_ID)
        self.assertEqual(user["role"], "owner")

        workshop = get_workshop(self.WORKSHOP_ID)
        self.assertEqual(workshop["name"], "Admin Panel Test Werkstatt")
        self.assertEqual(workshop["whatsapp_phone_number_id"], "wa-admin-panel-test")

        accounts = list_workshop_accounts()
        self.assertTrue(any(item["id"] == self.WORKSHOP_ID for item in accounts))

    def test_admin_workshop_panel_rejects_owner_role(self) -> None:
        response = dashboard_admin_workshops(_dashboard_request(role="owner"))

        self.assertEqual(response.status_code, 403)

    def test_admin_workshop_panel_creates_account(self) -> None:
        response = dashboard_admin_workshops_create(
            _dashboard_request(role="admin"),
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
            address="Testweg 9",
            phone="0123",
            email="kontakt@example.com",
            opening_hours="Montag bis Freitag",
            services="Service",
            pricing_info="Nach Absprache",
            towing_info="Partnerdienst",
            subscription_plan="pilot",
            subscription_status="trialing",
            whatsapp_phone_number_id="wa-admin-panel-test",
            whatsapp_display_phone_number="+49 176 999999",
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("created=admin-panel-test", response.headers["location"])

        user = authenticate_user(self.ADMIN_EMAIL, "startpass123")
        self.assertIsNotNone(user)
        self.assertEqual(user["workshop_id"], self.WORKSHOP_ID)

    def test_admin_can_switch_dashboard_context_to_customer_workshop(self) -> None:
        self.assertEqual(
            _workshop_id_for_request(
                _dashboard_request(workshop_id="demo-werkstatt", role="admin"),
                self.WORKSHOP_ID,
            ),
            self.WORKSHOP_ID,
        )
        self.assertEqual(
            _workshop_id_for_request(
                _dashboard_request(workshop_id="demo-werkstatt", role="owner"),
                self.WORKSHOP_ID,
            ),
            "demo-werkstatt",
        )

    def test_update_workshop_account_changes_subscription_and_whatsapp(self) -> None:
        create_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
        )

        account = update_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Updated Werkstatt",
            address="Neue Strasse 2",
            phone="0999",
            email="neu@example.com",
            opening_hours="Montag",
            services="Diagnose",
            pricing_info="Festpreis nach Freigabe",
            towing_info="Neuer Partner",
            subscription_plan="pro",
            subscription_status="active",
            trial_ends_at="2026-07-01T00:00:00+00:00",
            subscription_ends_at="2027-07-01T00:00:00+00:00",
            whatsapp_phone_number_id="wa-updated",
            whatsapp_display_phone_number="+49 176 111111",
        )

        self.assertEqual(account["name"], "Admin Panel Updated Werkstatt")
        self.assertEqual(account["subscription_plan"], "pro")
        self.assertEqual(account["subscription_status"], "active")
        self.assertEqual(account["whatsapp_phone_number_id"], "wa-updated")

    def test_admin_update_route_saves_workshop_account(self) -> None:
        create_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
        )

        response = dashboard_admin_workshop_update(
            _dashboard_request(role="admin"),
            admin_workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Route Updated Werkstatt",
            address="Route 1",
            phone="0444",
            email="route@example.com",
            opening_hours="Dienstag",
            services="Service",
            pricing_info="Route Preis",
            towing_info="Route Partner",
            subscription_plan="pilot",
            subscription_status="past_due",
            trial_ends_at="2026-07-02T00:00:00+00:00",
            subscription_ends_at="",
            whatsapp_phone_number_id="wa-route-updated",
            whatsapp_display_phone_number="+49 176 222222",
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("saved=1", response.headers["location"])

        account = get_workshop_account(self.WORKSHOP_ID)
        self.assertIsNotNone(account)
        self.assertEqual(account["name"], "Admin Route Updated Werkstatt")
        self.assertEqual(account["subscription_status"], "past_due")
        self.assertEqual(account["whatsapp_phone_number_id"], "wa-route-updated")

    def test_reset_workshop_owner_password_replaces_login_password(self) -> None:
        create_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
        )

        reset_workshop_owner_password(
            workshop_id=self.WORKSHOP_ID,
            owner_email=self.ADMIN_EMAIL,
            new_password="newpass123",
        )

        self.assertIsNone(authenticate_user(self.ADMIN_EMAIL, "startpass123"))
        user = authenticate_user(self.ADMIN_EMAIL, "newpass123")
        self.assertIsNotNone(user)
        self.assertEqual(user["workshop_id"], self.WORKSHOP_ID)

    def test_admin_reset_password_route_updates_owner_login(self) -> None:
        create_workshop_account(
            workshop_id=self.WORKSHOP_ID,
            workshop_name="Admin Panel Test Werkstatt",
            admin_email=self.ADMIN_EMAIL,
            admin_password="startpass123",
        )

        response = dashboard_admin_workshop_reset_password(
            _dashboard_request(role="admin"),
            admin_workshop_id=self.WORKSHOP_ID,
            owner_email=self.ADMIN_EMAIL,
            new_password="routepass123",
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("reset=owner.admin-panel-test%40example.com", response.headers["location"])
        self.assertIsNone(authenticate_user(self.ADMIN_EMAIL, "startpass123"))
        self.assertIsNotNone(authenticate_user(self.ADMIN_EMAIL, "routepass123"))


class SubscriptionTests(unittest.TestCase):
    def test_default_workshop_has_active_trial(self) -> None:
        init_db()
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET
                    subscription_plan = 'starter',
                    subscription_status = 'trialing',
                    trial_ends_at = ?
                WHERE id = ?
                """,
                (trial_ends_at, "demo-werkstatt"),
            )
            conn.commit()

        subscription = get_subscription("demo-werkstatt")

        self.assertEqual(subscription["plan"], "starter")
        self.assertEqual(subscription["status"], "trialing")
        self.assertTrue(subscription["is_active"])
        self.assertTrue(is_subscription_active("demo-werkstatt"))

    def test_inactive_subscription_blocks_chat(self) -> None:
        init_db()

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE workshops
                SET subscription_status = 'inactive'
                WHERE id = ?
                """,
                ("demo-werkstatt",),
            )
            conn.commit()

        try:
            with self.assertRaises(HTTPException) as ctx:
                process_chat_message(
                    workshop_id="demo-werkstatt",
                    session_id="test-inactive-subscription",
                    message="Hallo",
                    channel="test",
                )

            self.assertEqual(ctx.exception.status_code, 402)
        finally:
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE workshops
                    SET subscription_status = 'trialing'
                    WHERE id = ?
                    """,
                    ("demo-werkstatt",),
                )
                conn.execute(
                    """
                    DELETE FROM conversation_sessions
                    WHERE session_id = ?
                    """,
                    ("demo-werkstatt:test-inactive-subscription",),
                )
                conn.commit()


class ExistingTicketTests(unittest.TestCase):
    def test_internal_note_is_not_shown_to_customer(self) -> None:
        ticket = {
            "ticket_id": "WS-20260505-0005",
            "status": "offen",
            "priority": "normal",
            "request_type": "diagnose",
            "fahrzeug": "VW Golf",
            "baujahr": "2018",
            "kilometerstand": "95000",
            "problem": "Motorlampe leuchtet",
            "name": "Lukas Weber",
            "telefon": "+4915112340000",
            "notes": [
                {
                    "type": "internal_note",
                    "text": "Nur fuer die Werkstatt sichtbar",
                    "created_at": "2026-05-05T20:00:00",
                }
            ],
        }

        with patch("app.conversation.existing_ticket.find_ticket_by_id", return_value=ticket), patch(
            "app.conversation.existing_ticket.add_ticket_note"
        ):
            _, reply, done = handle_existing_ticket(
                IntakeState(),
                "Gibt es eine Notiz? Ticket WS-20260505-0005",
            )

        self.assertFalse(done)
        self.assertNotIn("Nur fuer die Werkstatt sichtbar", reply)
        self.assertIn("noch keine Antwort der Werkstatt", reply)

    def test_existing_ticket_message_is_recorded_as_customer_message(self) -> None:
        ticket = {
            "ticket_id": "WS-20260505-0005",
            "status": "offen",
            "priority": "normal",
            "request_type": "diagnose",
            "fahrzeug": "VW Golf",
            "baujahr": "2018",
            "kilometerstand": "95000",
            "problem": "Motorlampe leuchtet",
            "name": "Lukas Weber",
            "telefon": "+4915112340000",
            "notes": [],
        }

        with patch("app.conversation.existing_ticket.find_ticket_by_id", return_value=ticket), patch(
            "app.conversation.existing_ticket.add_ticket_note"
        ) as add_note:
            state, reply, done = handle_existing_ticket(
                IntakeState(),
                "Ist mein Auto fertig? Ticket WS-20260505-0005",
            )

        self.assertFalse(done)
        self.assertEqual(state.ticket_id, "WS-20260505-0005")
        self.assertIn("Status", reply)
        add_note.assert_called_once()
        self.assertEqual(add_note.call_args.kwargs["note_type"], "customer_message")

    def test_phone_lookup_with_multiple_tickets_asks_for_exact_ticket_number(self) -> None:
        init_db()
        phone = "+49 151 99988877"
        state_a = IntakeState(
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem="Motorlampe leuchtet",
            telefon=phone,
            name="Lookup Test A",
        )
        state_b = IntakeState(
            fahrzeug="Audi A4",
            baujahr="2020",
            kilometerstand="70000",
            request_type="service",
            priority="niedrig",
            problem="Inspektion",
            telefon=phone,
            name="Lookup Test B",
        )
        ticket_a = save_ticket(state_a, workshop_id="demo-werkstatt")
        ticket_b = save_ticket(state_b, workshop_id="demo-werkstatt")

        try:
            _, reply, done = handle_existing_ticket(
                IntakeState(workshop_id="demo-werkstatt"),
                "Meine Nummer ist 0151 99988877",
            )

            self.assertFalse(done)
            self.assertIn("Tickets", reply)
            self.assertIn(ticket_a, reply)
            self.assertIn(ticket_b, reply)
            self.assertIn("genaue Ticketnummer", reply)
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM tickets WHERE ticket_id IN (?, ?)",
                    (ticket_a, ticket_b),
                )
                conn.commit()


class GeneralQuestionTests(unittest.TestCase):
    def test_opening_hours_use_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "Welche Öffnungszeiten habt ihr?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("09:00-17:00", reply)

    def test_informal_saturday_opening_hours_question_uses_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "habt ihr samstags offen?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("Samstag", reply)


    def test_price_overview_uses_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "Habt ihr eine Preisliste?",
        )

        self.assertFalse(done)
        self.assertIn("keine festen Preisangaben", reply)

    def test_contact_question_uses_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "Wie kann ich euch telefonisch erreichen?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("Telefon", reply)

    def test_service_question_uses_workshop_profile(self) -> None:
        init_db()

        state = IntakeState(workshop_id="demo-werkstatt")
        _, reply, done = handle_general_question(
            state,
            "Welche Leistungen macht ihr?",
        )

        self.assertFalse(done)
        self.assertIn("Meier Werkstatt Family", reply)
        self.assertIn("Beschreiben Sie einfach Ihr Anliegen", reply)


class NewRequestTests(unittest.TestCase):
    def test_engine_light_and_jerking_is_diagnose_not_service(self) -> None:
        analysis = analyze_problem(
            "Seit gestern leuchtet die Motorkontrollleuchte und das Auto ruckelt beim Beschleunigen"
        )

        self.assertEqual(analysis["request_type"], "diagnose")
        self.assertEqual(analysis["priority"], "normal")
        self.assertFalse(analysis["flags"]["service_request"])
        self.assertTrue(analysis["flags"]["warning_light"])
        self.assertTrue(analysis["flags"]["performance_issue"])

    def test_invalid_year_does_not_advance_flow(self) -> None:
        state = IntakeState(mode="new", step="baujahr", fahrzeug="VW Golf")

        new_state, reply, done = handle_new_request(state, "irgendwann")

        self.assertFalse(done)
        self.assertEqual(new_state.step, "baujahr")
        self.assertIsNone(new_state.baujahr)
        self.assertIn("vierstelliges Baujahr", reply)

    def test_invalid_kilometerstand_does_not_advance_flow(self) -> None:
        state = IntakeState(
            mode="new",
            step="kilometerstand",
            fahrzeug="VW Golf",
            baujahr="2018",
        )

        new_state, reply, done = handle_new_request(state, "weiss nicht")

        self.assertFalse(done)
        self.assertEqual(new_state.step, "kilometerstand")
        self.assertIsNone(new_state.kilometerstand)
        self.assertIn("Kilometerstand", reply)

    def test_cancel_resets_active_intake_flow(self) -> None:
        state = IntakeState(
            mode="new",
            step="telefon",
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            problem="Motorlampe leuchtet",
        )

        new_state, reply, done = handle_new_request(state, "abbrechen")

        self.assertFalse(done)
        self.assertEqual(new_state.step, "fahrzeug")
        self.assertEqual(new_state.mode, "unknown")
        self.assertIsNone(new_state.fahrzeug)
        self.assertIn("zur", reply.lower())

    def test_german_driveable_answer_is_accepted(self) -> None:
        state = IntakeState(
            mode="new",
            step="fahrbereit",
            fahrzeug="VW Golf",
            baujahr="2017",
            kilometerstand="142000",
            problem="Seit gestern leuchtet die Motorkontrollleuchte und das Auto ruckelt beim Beschleunigen",
            request_type="diagnose",
            priority="normal",
        )

        state, reply, done = handle_new_request(state, "ja, ich kann noch fahren, aber es beschleunigt schlechter")

        self.assertFalse(done)
        self.assertEqual(state.fahrbereit, "ja")
        self.assertEqual(state.step, "followup")
        self.assertIn("Seit wann", reply)

    def test_early_phone_during_followup_is_stored_not_used_as_answer(self) -> None:
        state = IntakeState(
            mode="new",
            step="followup",
            problem="Motorkontrollleuchte leuchtet und das Auto ruckelt",
            followup_questions=["Seit wann besteht das Problem ungefähr?"],
            followup_answers=[],
            followup_index=0,
        )

        new_state, reply, done = handle_new_request(state, "0176 11122233")

        self.assertFalse(done)
        self.assertEqual(new_state.telefon, "017611122233")
        self.assertEqual(new_state.followup_answers, [])
        self.assertIn("Telefonnummer ist gespeichert", reply)
        self.assertIn("Seit wann besteht", reply)

    def test_problem_first_message_is_not_used_as_vehicle_name(self) -> None:
        state, reply, done = handle_new_request(IntakeState(), "karre geht nicht an")

        self.assertFalse(done)
        self.assertIsNone(state.fahrzeug)
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertIn("Verstanden", reply)
        self.assertIn("Marke und Modell", reply)

    def test_problem_first_flow_reuses_problem_after_vehicle_details(self) -> None:
        state, _, done = handle_new_request(IntakeState(), "karre geht nicht an")
        self.assertFalse(done)

        state, reply, done = handle_new_request(state, "BMW 320d")
        self.assertFalse(done)
        self.assertEqual(state.fahrzeug, "BMW 320d")
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertIn("Baujahr", reply)

        state, reply, done = handle_new_request(state, "2018")
        self.assertFalse(done)
        self.assertEqual(state.baujahr, "2018")
        self.assertIn("Kilometerstand", reply)

        state, reply, done = handle_new_request(state, "120000")
        self.assertFalse(done)
        self.assertEqual(state.kilometerstand, "120000")
        self.assertEqual(state.problem, "karre geht nicht an")
        self.assertEqual(state.request_type, "notfall")
        self.assertEqual(state.priority, "hoch")
        self.assertEqual(state.fahrbereit, "nein")
        self.assertIn("Abschleppdienst", reply)

    def test_switching_from_existing_ticket_to_new_request_clears_ticket_context(self) -> None:
        state = IntakeState(
            mode="existing",
            ticket_id="WS-20260505-0005",
            workshop_id="demo-werkstatt",
        )

        new_state, reply, done = handle_new_request(state, "Ich möchte ein Problem melden.")

        self.assertFalse(done)
        self.assertEqual(new_state.mode, "new")
        self.assertIsNone(new_state.ticket_id)
        self.assertEqual(new_state.workshop_id, "demo-werkstatt")
        self.assertIn("Welche Marke", reply)

    def test_skip_name_completes_new_request_without_customer_name(self) -> None:
        state = IntakeState(
            mode="new",
            step="name",
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="service",
            priority="niedrig",
            problem="Inspektion und Oelwechsel",
            telefon="017644411122",
        )

        new_state, reply, done = handle_new_request(state, "ueberspringen")

        self.assertTrue(done)
        self.assertEqual(new_state.step, "fertig")
        self.assertIsNone(new_state.name)
        self.assertIn("Kontakt: Tel. 017644411122", reply)


class QuoteRequestTests(unittest.TestCase):
    def test_switching_from_existing_ticket_to_quote_clears_ticket_context(self) -> None:
        state = IntakeState(
            mode="existing",
            ticket_id="WS-20260505-0005",
            workshop_id="demo-werkstatt",
        )

        new_state, reply, done = handle_quote_request(state, "Was kostet ein Ölwechsel?")

        self.assertFalse(done)
        self.assertEqual(new_state.mode, "quote")
        self.assertIsNone(new_state.ticket_id)
        self.assertEqual(new_state.workshop_id, "demo-werkstatt")
        self.assertIn("Zu welchem Fahrzeug", reply)

    def test_invalid_quote_phone_does_not_complete_flow(self) -> None:
        state = IntakeState(
            mode="quote",
            step="quote_telefon",
            problem="Oelwechsel",
            fahrzeug="VW Golf",
            baujahr="2018",
        )

        new_state, reply, done = handle_quote_request(state, "keine nummer")

        self.assertFalse(done)
        self.assertEqual(new_state.step, "quote_telefon")
        self.assertIsNone(new_state.telefon)
        self.assertIn("Telefonnummer", reply)

    def test_skip_name_completes_quote_request(self) -> None:
        state = IntakeState(
            mode="quote",
            step="quote_name",
            request_type="kostenvoranschlag",
            priority="normal",
            problem="Oelwechsel",
            fahrzeug="VW Golf",
            baujahr="2018",
            telefon="017644433344",
        )

        new_state, reply, done = handle_quote_request(state, "ueberspringen")

        self.assertTrue(done)
        self.assertEqual(new_state.step, "fertig")
        self.assertIsNone(new_state.name)
        self.assertIn("Kostenvoranschlag", reply)


class EndToEndConversationTests(unittest.TestCase):
    WORKSHOP_ID = "demo-werkstatt"

    def _send(self, session_id: str, message: str):
        return process_chat_message(
            workshop_id=self.WORKSHOP_ID,
            session_id=session_id,
            message=message,
            channel="test",
        )

    def _cleanup(self, session_ids: list[str], ticket_ids: list[str]) -> None:
        with get_conn() as conn:
            for session_id in session_ids:
                conn.execute(
                    "DELETE FROM conversation_sessions WHERE session_id = ?",
                    (f"{self.WORKSHOP_ID}:{session_id}",),
                )
            for ticket_id in ticket_ids:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
            conn.commit()

    def test_service_flow_creates_service_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-service"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "Audi A4 2019 120000 km")
            self._send(session_id, "Inspektion und Ölwechsel")
            self._send(session_id, "0176 44411122")
            response = self._send(session_id, "Service Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "service")
            self.assertEqual(ticket["priority"], "niedrig")
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_notfall_flow_creates_high_priority_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-notfall"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "BMW 320d 2017 130000 km")
            self._send(session_id, "Auto springt nicht an und steht auf der Straße")
            self._send(session_id, "ja")
            self._send(session_id, "nein")
            self._send(session_id, "0176 44422233")
            response = self._send(session_id, "Notfall Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "notfall")
            self.assertEqual(ticket["priority"], "hoch")
            self.assertFalse(ticket["fahrbereit"])
            self.assertTrue(ticket["abschleppdienst"])
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_quote_flow_creates_quote_ticket_from_messy_price_question(self) -> None:
        init_db()
        session_id = "test-e2e-quote"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "wieviel kostet ölwechsel")
            self._send(session_id, "VW Polo 2015")
            self._send(session_id, "0176 44433344")
            response = self._send(session_id, "Quote Tester")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "kostenvoranschlag")
            self.assertEqual(ticket["fahrzeug"], "VW Polo")
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_diagnose_flow_with_followups_and_skipped_name_creates_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-diagnose-followups"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "VW Golf 2018 95000 km")
            self._send(
                session_id,
                "Seit gestern leuchtet die Motorkontrollleuchte und das Auto ruckelt beim Beschleunigen",
            )
            self._send(session_id, "ja ich kann noch fahren")
            self._send(session_id, "seit gestern abend")
            self._send(session_id, "gelbe motorlampe")
            self._send(session_id, "ruckelt beim beschleunigen")
            self._send(session_id, "0176 44455566")
            response = self._send(session_id, "ueberspringen")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "diagnose")
            self.assertEqual(ticket["priority"], "normal")
            self.assertTrue(ticket["fahrbereit"])
            self.assertEqual(ticket["telefon"], "017644455566")
            self.assertFalse(ticket["kunde_name"])
            self.assertIn("Ticket-Nr.", response.reply)
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_service_flow_recovers_from_invalid_inputs_and_creates_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-service-invalid-inputs"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "VW Golf")
            invalid_year = self._send(session_id, "irgendwann")
            self.assertFalse(invalid_year.done)
            self.assertEqual(invalid_year.data.get("step"), "baujahr")
            self.assertIn("Baujahr", invalid_year.reply)

            self._send(session_id, "2018")
            invalid_km = self._send(session_id, "weiss nicht")
            self.assertFalse(invalid_km.done)
            self.assertEqual(invalid_km.data.get("step"), "kilometerstand")
            self.assertIn("Kilometerstand", invalid_km.reply)

            self._send(session_id, "95.000 km")
            self._send(session_id, "Inspektion und Oelwechsel")
            invalid_phone = self._send(session_id, "keine nummer")
            self.assertFalse(invalid_phone.done)
            self.assertEqual(invalid_phone.data.get("step"), "telefon")
            self.assertIn("Telefonnummer", invalid_phone.reply)

            self._send(session_id, "+49 176 444 777 88")
            response = self._send(session_id, "ueberspringen")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["fahrzeug"], "VW Golf")
            self.assertEqual(ticket["baujahr"], "2018")
            self.assertEqual(ticket["kilometerstand"], "95000")
            self.assertEqual(ticket["request_type"], "service")
            self.assertEqual(ticket["telefon"], "+4917644477788")
            self.assertFalse(ticket["kunde_name"])
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_general_question_then_new_request_creates_ticket(self) -> None:
        init_db()
        session_id = "test-e2e-general-then-intake"
        ticket_ids: list[str] = []

        try:
            general = self._send(session_id, "Wann habt ihr offen?")
            self.assertFalse(general.done)
            self.assertEqual(general.data.get("mode"), "general")
            self.assertIn("Meier Werkstatt Family", general.reply)

            self._send(session_id, "Ich moechte ein Problem melden.")
            self._send(session_id, "Mercedes C180")
            self._send(session_id, "2016")
            self._send(session_id, "85000")
            self._send(session_id, "Bremsen quietschen beim Bremsen")
            self._send(session_id, "ja, Auto faehrt noch")
            self._send(session_id, "seit einer Woche")
            self._send(session_id, "nur beim Bremsen")
            self._send(session_id, "in der Stadt bei niedriger Geschwindigkeit")
            self._send(session_id, "0176 444 888 99")
            response = self._send(session_id, "Max Mustermann")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["fahrzeug"], "Mercedes C180")
            self.assertEqual(ticket["request_type"], "diagnose")
            self.assertTrue(ticket["fahrbereit"])
            self.assertEqual(ticket["kunde_name"], "Max Mustermann")
            self.assertEqual(len(ticket["followup_answers"]), 3)
        finally:
            self._cleanup([session_id], ticket_ids)

    def test_notfall_flow_recovers_from_invalid_yes_no_answers(self) -> None:
        init_db()
        session_id = "test-e2e-notfall-invalid-yes-no"
        ticket_ids: list[str] = []

        try:
            self._send(session_id, "BMW 320d 2017 130000 km")
            self._send(session_id, "Motor dampft und die Temperatur ist rot")

            invalid_driveable = self._send(session_id, "vielleicht")
            self.assertFalse(invalid_driveable.done)
            self.assertEqual(invalid_driveable.data.get("step"), "fahrbereit")
            self.assertIn("Ja oder Nein", invalid_driveable.reply)

            self._send(session_id, "nein")

            invalid_towing = self._send(session_id, "keine ahnung")
            self.assertFalse(invalid_towing.done)
            self.assertEqual(invalid_towing.data.get("step"), "abschleppdienst")
            self.assertIn("Ja oder Nein", invalid_towing.reply)

            self._send(session_id, "ja")
            self._send(session_id, "Temperatur steigt schnell und Kuehlmittel fehlt")
            self._send(session_id, "0176 444 999 00")
            response = self._send(session_id, "Notfall Kunde")

            ticket_id = str(response.data.get("ticket_id") or "")
            ticket_ids.append(ticket_id)
            ticket = find_ticket_by_id(ticket_id, workshop_id=self.WORKSHOP_ID)

            self.assertTrue(response.done)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["request_type"], "notfall")
            self.assertEqual(ticket["priority"], "hoch")
            self.assertFalse(ticket["fahrbereit"])
            self.assertTrue(ticket["abschleppdienst"])
            self.assertEqual(ticket["kunde_name"], "Notfall Kunde")
            self.assertEqual(ticket["telefon"], "017644499900")
        finally:
            self._cleanup([session_id], ticket_ids)


class TicketTenantTests(unittest.TestCase):
    def _ticket_state(self, *, fahrzeug: str, problem: str, telefon: str) -> IntakeState:
        return IntakeState(
            fahrzeug=fahrzeug,
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem=problem,
            telefon=telefon,
            name="Tenant Test",
        )

    def test_ticket_reads_are_scoped_by_workshop(self) -> None:
        init_db()

        state_a = IntakeState(
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem="Motorlampe leuchtet",
            telefon="+4915112345678",
            name="Lukas Weber",
        )
        state_b = IntakeState(
            fahrzeug="BMW 320d",
            baujahr="2019",
            kilometerstand="88000",
            request_type="service",
            priority="normal",
            problem="Service faellig",
            telefon="+4915112345678",
            name="Anna Klein",
        )

        ticket_a = save_ticket(state_a, workshop_id="tenant-a")
        ticket_b = save_ticket(state_b, workshop_id="tenant-b")

        try:
            self.assertIsNotNone(find_ticket_by_id(ticket_a, workshop_id="tenant-a"))
            self.assertIsNone(find_ticket_by_id(ticket_a, workshop_id="tenant-b"))

            tenant_a_phone_matches = find_tickets_by_phone("+49 151 12345678", workshop_id="tenant-a")
            tenant_b_phone_matches = find_tickets_by_phone("+49 151 12345678", workshop_id="tenant-b")
            tenant_a_local_phone_matches = find_tickets_by_phone("0151 12345678", workshop_id="tenant-a")
            tenant_a_0049_phone_matches = find_tickets_by_phone("0049 151 12345678", workshop_id="tenant-a")
            tenant_a_mobile_without_prefix_matches = find_tickets_by_phone("151 12345678", workshop_id="tenant-a")

            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_phone_matches))
            self.assertFalse(any(t["ticket_id"] == ticket_b for t in tenant_a_phone_matches))
            self.assertTrue(any(t["ticket_id"] == ticket_b for t in tenant_b_phone_matches))
            self.assertFalse(any(t["ticket_id"] == ticket_a for t in tenant_b_phone_matches))
            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_local_phone_matches))
            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_0049_phone_matches))
            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_mobile_without_prefix_matches))

            tenant_a_latest = list_latest_tickets(workshop_id="tenant-a")
            self.assertTrue(any(t["ticket_id"] == ticket_a for t in tenant_a_latest))
            self.assertFalse(any(t["ticket_id"] == ticket_b for t in tenant_a_latest))
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM tickets WHERE ticket_id IN (?, ?)",
                    (ticket_a, ticket_b),
                )
                conn.commit()

    def test_ticket_api_requires_login(self) -> None:
        init_db()

        with self.assertRaises(HTTPException) as ctx:
            tickets(_anonymous_dashboard_request(), workshop_id="demo-werkstatt")

        self.assertEqual(ctx.exception.status_code, 401)

    def test_owner_ticket_api_ignores_foreign_workshop_parameter(self) -> None:
        init_db()

        ticket_a = save_ticket(
            self._ticket_state(
                fahrzeug="VW Golf",
                problem="Motorlampe leuchtet",
                telefon="+4915112345678",
            ),
            workshop_id="tenant-a",
        )
        ticket_b = save_ticket(
            self._ticket_state(
                fahrzeug="BMW 320d",
                problem="Service faellig",
                telefon="+4915222222222",
            ),
            workshop_id="tenant-b",
        )

        try:
            response = tickets(
                _dashboard_request(workshop_id="tenant-a", role="owner"),
                workshop_id="tenant-b",
                limit=20,
            )

            self.assertEqual(response["workshop_id"], "tenant-a")
            self.assertTrue(any(item["ticket_id"] == ticket_a for item in response["items"]))
            self.assertFalse(any(item["ticket_id"] == ticket_b for item in response["items"]))

            with self.assertRaises(HTTPException) as ctx:
                ticket_by_id(
                    _dashboard_request(workshop_id="tenant-a", role="owner"),
                    ticket_b,
                    workshop_id="tenant-b",
                )

            self.assertEqual(ctx.exception.status_code, 404)

            with self.assertRaises(HTTPException) as ctx:
                patch_ticket_status(
                    _dashboard_request(workshop_id="tenant-a", role="owner"),
                    ticket_b,
                    StatusUpdate(status="erledigt"),
                    workshop_id="tenant-b",
                )

            self.assertEqual(ctx.exception.status_code, 404)

            subscription_response = subscription(
                _dashboard_request(workshop_id="tenant-a", role="owner"),
                workshop_id="tenant-b",
            )
            self.assertEqual(subscription_response["workshop_id"], "tenant-a")
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM tickets WHERE ticket_id IN (?, ?)",
                    (ticket_a, ticket_b),
                )
                conn.commit()

    def test_admin_ticket_api_can_switch_workshop_parameter(self) -> None:
        init_db()

        ticket_a = save_ticket(
            self._ticket_state(
                fahrzeug="VW Golf",
                problem="Motorlampe leuchtet",
                telefon="+4915112345678",
            ),
            workshop_id="tenant-a",
        )
        ticket_b = save_ticket(
            self._ticket_state(
                fahrzeug="BMW 320d",
                problem="Service faellig",
                telefon="+4915222222222",
            ),
            workshop_id="tenant-b",
        )

        try:
            response = tickets(
                _dashboard_request(workshop_id="demo-werkstatt", role="admin"),
                workshop_id="tenant-b",
                limit=20,
            )

            self.assertEqual(response["workshop_id"], "tenant-b")
            self.assertTrue(any(item["ticket_id"] == ticket_b for item in response["items"]))
            self.assertFalse(any(item["ticket_id"] == ticket_a for item in response["items"]))

            item = ticket_by_id(
                _dashboard_request(workshop_id="demo-werkstatt", role="admin"),
                ticket_b,
                workshop_id="tenant-b",
            )
            self.assertEqual(item["ticket_id"], ticket_b)
        finally:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM tickets WHERE ticket_id IN (?, ?)",
                    (ticket_a, ticket_b),
                )
                conn.commit()


class TicketMetadataTests(unittest.TestCase):
    def test_ticket_source_is_saved(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="VW Golf",
            baujahr="2018",
            kilometerstand="95000",
            request_type="diagnose",
            priority="normal",
            problem="Motorlampe leuchtet",
            telefon="+4915112345678",
            name="Lukas Weber",
            source="whatsapp",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            ticket = find_ticket_by_id(ticket_id, workshop_id="demo-werkstatt")

            self.assertIsNotNone(ticket)
            self.assertEqual(ticket["source"], "whatsapp")
            self.assertFalse(ticket["customer_question_open"])
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()

    def test_customer_question_open_toggles_with_customer_reply(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="BMW 320d",
            baujahr="2019",
            kilometerstand="88000",
            request_type="diagnose",
            priority="normal",
            problem="Klimaanlage kuehlt nicht",
            telefon="+4915112345678",
            name="Anna Klein",
            source="web_chat",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            ticket = add_ticket_note(
                ticket_id,
                "Kundenfrage über den Chat: Ist mein Auto morgen fertig?",
                note_type="customer_message",
                workshop_id="demo-werkstatt",
            )
            self.assertTrue(ticket["customer_question_open"])

            ticket = add_ticket_note(
                ticket_id,
                "Wir melden uns morgen Vormittag mit einer Einschätzung.",
                note_type="customer_reply",
                workshop_id="demo-werkstatt",
            )
            self.assertFalse(ticket["customer_question_open"])
            self.assertEqual(ticket["status"], "in_bearbeitung")
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()

    def test_customer_reply_does_not_reopen_done_ticket(self) -> None:
        init_db()

        state = IntakeState(
            fahrzeug="Mercedes C-Klasse",
            baujahr="2020",
            kilometerstand="65000",
            request_type="diagnose",
            priority="normal",
            problem="Bremse quietscht",
            telefon="+4915112345678",
            name="Tom Becker",
            source="web_chat",
        )

        ticket_id = save_ticket(state, workshop_id="demo-werkstatt")

        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE tickets SET status = ? WHERE ticket_id = ?",
                    ("erledigt", ticket_id),
                )
                conn.commit()

            ticket = add_ticket_note(
                ticket_id,
                "Ihr Fahrzeug ist fertig.",
                note_type="customer_reply",
                workshop_id="demo-werkstatt",
            )

            self.assertEqual(ticket["status"], "erledigt")
        finally:
            with get_conn() as conn:
                conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
