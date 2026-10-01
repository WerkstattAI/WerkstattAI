from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock, patch

import test_conversation_flows  # establish isolated configuration before app imports
import test_whatsapp_reliability as fixtures
from fastapi.testclient import TestClient
from app.auth import SESSION_COOKIE, create_session_token
from app.communication import open_customer_questions
from app.db import get_conn, get_whatsapp_conversation_control, set_whatsapp_conversation_control
from app.manual_dispatch import send_workshop_message
from app.models import IntakeState
from app.tickets import add_ticket_note, find_ticket_by_id, save_ticket
from app.whatsapp import (WhatsAppSendResult, deliver_prepared_whatsapp_reply,
                          save_whatsapp_message, update_whatsapp_message_status)


class DispatchRecoveryTests(unittest.TestCase):
    tearDown = fixtures.WhatsAppReliabilityTests.tearDown

    def setUp(self):
        fixtures.WhatsAppReliabilityTests.setUp(self)
        self.tid = save_ticket(IntakeState(telefon=self.phone, name="Recovery Test"), workshop_id=self.wid,
                               verified_customer_phone=self.phone)
        set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone,
                                          mode="assistant", active_ticket_id=self.tid)
        save_whatsapp_message(workshop_id=self.wid, customer_phone=self.phone, direction="inbound", text="Hallo")
        self.actor = "recovery-owner@example.invalid"

    def send(self, *, mid="dispatch-attempt-one", purpose="workshop_notification", target=None, callback=None):
        return send_workshop_message(
            workshop_id=self.wid, customer_phone=self.phone, phone_number_id="reliability-sender",
            ticket_id=self.tid, text="Unveränderter Nachrichtentext", purpose=purpose,
            reply_to_message_id=target, message_id=mid, source="recovery_test", user=self.actor,
            send=callback or (lambda: WhatsAppSendResult(True, 200, "wamid." + mid, {})),
        )

    def question(self, mid="customer-question-one"):
        add_ticket_note(self.tid, "Wie lange dauert es?", workshop_id=self.wid,
                        sender_role="customer", purpose="customer_question", message_id=mid)

    def row(self, mid="dispatch-attempt-one"):
        with closing(get_conn()) as conn:
            row = conn.execute("SELECT * FROM whatsapp_messages WHERE workshop_id = ? AND message_id = ?",
                               (self.wid, mid)).fetchone()
        return dict(row) if row else None

    def ticket(self):
        return find_ticket_by_id(self.tid, self.wid)

    def age(self, mid="dispatch-attempt-one", *, seconds=360, timestamp=None):
        value = timestamp or (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET dispatch_started_at = ? WHERE workshop_id = ? AND message_id = ?",
                         (value, self.wid, mid))
            conn.commit()

    def crash(self, *, mid="dispatch-attempt-one", purpose="workshop_notification", target=None, age=True):
        def stop_after_reservation():
            raise KeyboardInterrupt("synthetic process interruption before transport finalization")
        with self.assertRaises(KeyboardInterrupt):
            self.send(mid=mid, purpose=purpose, target=target, callback=stop_after_reservation)
        self.assertEqual(self.row(mid)["dispatch_state"], "sending")
        if age:
            self.age(mid)

    def context(self, **kwargs):
        from app.dispatch_recovery import dispatch_recovery_context
        return dispatch_recovery_context(workshop_id=self.wid, customer_phone=self.phone, **kwargs)

    def recover(self, resolution="sent", mid="dispatch-attempt-one", **kwargs):
        from app.dispatch_recovery import resolve_stale_dispatch
        return resolve_stale_dispatch(workshop_id=kwargs.pop("workshop_id", self.wid), message_id=mid,
                                      resolution=resolution, actor_email=kwargs.pop("actor_email", self.actor),
                                      confirmed=kwargs.pop("confirmed", True), **kwargs)

    def test_definitive_failure_can_be_explicitly_retried_with_identical_content_and_new_id(self):
        rejected = Mock(return_value=WhatsAppSendResult(False, 400, None, {}, "rejected"))
        accepted = Mock(return_value=WhatsAppSendResult(True, 200, "wamid.new-attempt", {}))
        self.assertFalse(self.send(callback=rejected).ok)
        original = self.row()
        self.assertFalse(self.send(callback=accepted).ok)
        accepted.assert_not_called()
        self.assertTrue(self.send(mid="dispatch-attempt-two", callback=accepted).ok)
        accepted.assert_called_once()
        self.assertEqual(self.row(), original)
        self.assertEqual(self.row("dispatch-attempt-two")["text"], original["text"])
        self.assertEqual(self.row()["status"], "failed")
        self.assertEqual(self.row("dispatch-attempt-two")["status"], "sent")

    def test_failed_answer_retry_resolves_only_its_original_question(self):
        self.question()
        self.question("customer-question-two")
        self.send(purpose="workshop_answer", target="customer-question-one",
                  callback=lambda: WhatsAppSendResult(False, 400, None, {}, "rejected"))
        self.assertEqual(len(open_customer_questions(self.ticket())), 2)
        self.send(mid="dispatch-attempt-two", purpose="workshop_answer", target="customer-question-one")
        self.assertEqual([n["message_id"] for n in open_customer_questions(self.ticket())], ["customer-question-two"])
        self.assertEqual(self.row()["status"], "failed")
        self.assertEqual(self.ticket()["status"], "offen")

    def test_sent_delivered_and_read_remain_idempotent_with_same_message_id(self):
        sender = Mock(return_value=WhatsAppSendResult(True, 200, "wamid.accepted", {}))
        self.send(callback=sender)
        for status in ("sent", "delivered", "read"):
            update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.accepted", status=status)
            self.assertTrue(self.send(callback=sender).ok)
        sender.assert_called_once()
        self.assertEqual(self.row()["status"], "read")

    def test_unknown_result_and_same_id_never_trigger_a_second_transport_attempt(self):
        sender = Mock(return_value=WhatsAppSendResult(False, None, None, {}, "timeout"))
        self.assertFalse(self.send(callback=sender).ok)
        self.assertFalse(self.send(callback=sender).ok)
        sender.assert_called_once()
        self.assertEqual(self.row()["status"], "unknown")
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_pending_attempt_with_same_id_is_not_repeated_by_manual_submit(self):
        self.crash(age=False)
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET dispatch_state = 'pending', status = 'pending' WHERE workshop_id = ? AND message_id = ?",
                         (self.wid, "dispatch-attempt-one"))
            conn.commit()
        sender = Mock()
        self.assertFalse(self.send(callback=sender).ok)
        sender.assert_not_called()

    def test_crashed_sending_claim_blocks_new_id_and_explicit_resume(self):
        self.crash()
        sender = Mock()
        with self.assertRaises(ValueError):
            self.send(mid="dispatch-attempt-two", callback=sender)
        with self.assertRaises(ValueError):
            set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")
        sender.assert_not_called()

    def test_fresh_sending_is_blocked_but_not_offered_for_recovery(self):
        self.crash(age=False)
        context = self.context()
        self.assertTrue(context["dispatch_blocked"])
        self.assertEqual(context["stale_dispatches"], [])
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_opening_recovery_context_is_read_only_and_never_sends(self):
        self.crash()
        before = self.row()
        with patch("app.whatsapp._post_graph_api_json") as transport:
            for _ in range(3):
                self.assertEqual(len(self.context()["stale_dispatches"]), 1)
        transport.assert_not_called()
        self.assertEqual(self.row(), before)

    def test_automatic_reply_claim_age_uses_dispatch_start_instead_of_old_creation_time(self):
        control = get_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone)
        save_whatsapp_message(
            workshop_id=self.wid, customer_phone=self.phone, direction="outbound", text="Automatische Antwort",
            message_id="automatic-attempt-one", reply_to_wa_message_id="automatic-parent",
            dispatch_state="pending", status="pending", control_revision=control["revision"],
            payload={"sender_role": "assistant", "purpose": "automatic_answer"},
        )
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET created_at = ? WHERE workshop_id = ? AND message_id = ?",
                         ("2020-01-01T00:00:00", self.wid, "automatic-attempt-one"))
            conn.commit()
        def stop_after_fresh_claim(_):
            self.assertIsNotNone(self.row("automatic-attempt-one")["dispatch_started_at"])
            self.assertEqual(self.context()["stale_dispatches"], [])
            raise KeyboardInterrupt("synthetic interrupted automatic HTTP")
        with self.assertRaises(KeyboardInterrupt):
            deliver_prepared_whatsapp_reply(workshop_id=self.wid, customer_phone=self.phone,
                                             reply_to_wa_message_id="automatic-parent", send_message=stop_after_fresh_claim)
        self.age("automatic-attempt-one")
        self.recover("failed", mid="automatic-attempt-one")
        self.assertEqual(self.row("automatic-attempt-one")["status"], "failed")
        self.assertEqual(self.ticket()["notes"], [])

    def test_five_minute_boundary_is_evaluated_against_utc_instants(self):
        self.crash(age=False)
        reference = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
        self.age(timestamp=reference.isoformat())
        self.assertEqual(self.context(now=reference + timedelta(minutes=4, seconds=59))["stale_dispatches"], [])
        self.assertEqual(len(self.context(now=reference + timedelta(minutes=5, microseconds=1))["stale_dispatches"]), 1)
        same_instant_with_offset = (reference + timedelta(minutes=6)).astimezone(timezone(timedelta(hours=2)))
        self.assertEqual(len(self.context(now=same_instant_with_offset)["stale_dispatches"]), 1)

    def test_future_dispatch_timestamp_is_not_considered_stale(self):
        self.crash(age=False)
        self.age(seconds=-600)
        self.assertEqual(self.context()["stale_dispatches"], [])
        with self.assertRaises(ValueError):
            self.recover()

    def test_legacy_sending_without_timestamp_gets_one_fresh_migration_grace_period(self):
        self.crash(age=False)
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET dispatch_started_at = NULL, created_at = ? WHERE workshop_id = ? AND message_id = ?",
                         ("2020-01-01T00:00:00", self.wid, "dispatch-attempt-one"))
            conn.commit()
        fixtures.db.init_db()
        timestamp = self.row()["dispatch_started_at"]
        self.assertIsNotNone(timestamp)
        self.assertEqual(self.context()["stale_dispatches"], [])
        fixtures.db.init_db()
        self.assertEqual(self.row()["dispatch_started_at"], timestamp)

    def test_recovery_requires_explicit_confirmation(self):
        self.crash()
        before = self.row()
        with self.assertRaises(ValueError):
            self.recover(confirmed=False)
        self.assertEqual(self.row(), before)

    def test_recovery_rejects_missing_actor_and_unknown_resolution(self):
        self.crash()
        for kwargs in ({"actor_email": ""}, {"resolution": "retry"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.recover(**kwargs)
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_confirmed_sent_answer_resolves_exact_target_and_unlocks_conversation(self):
        self.question()
        self.question("customer-question-two")
        self.crash(purpose="workshop_answer", target="customer-question-one")
        self.recover()
        self.assertEqual(self.row()["status"], "sent")
        self.assertEqual(self.row()["dispatch_state"], "complete")
        self.assertEqual([n["message_id"] for n in open_customer_questions(self.ticket())], ["customer-question-two"])
        self.assertEqual(self.ticket()["status"], "offen")
        self.assertFalse(self.context()["dispatch_blocked"])
        set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="assistant")

    def test_manual_resolution_records_actor_time_confirmation_and_original_metadata(self):
        self.crash()
        original_payload = json.loads(self.row()["payload_json"])
        result = self.recover()
        payload = json.loads(self.row()["payload_json"])
        audit = payload["manual_resolution"]
        self.assertEqual(audit["resolution"], "sent")
        self.assertEqual(audit["actor_email"], self.actor)
        self.assertIs(audit["confirmed"], True)
        self.assertIsNotNone(datetime.fromisoformat(audit["resolved_at"].replace("Z", "+00:00")).tzinfo)
        self.assertEqual(payload["status_source"], "manual_confirmation")
        self.assertTrue(result["finalized"])
        for key, value in original_payload.items():
            self.assertEqual(payload[key], value)

    def test_confirmed_failed_answer_keeps_question_open_and_allows_new_attempt(self):
        self.question()
        self.crash(purpose="workshop_answer", target="customer-question-one")
        self.recover("failed")
        original = self.row()
        self.assertEqual(original["status"], "failed")
        self.assertEqual(len(open_customer_questions(self.ticket())), 1)
        self.assertTrue(self.send(mid="dispatch-attempt-two", purpose="workshop_answer", target="customer-question-one").ok)
        self.assertEqual(self.row(), original)
        self.assertEqual(open_customer_questions(self.ticket()), [])

    def test_confirmed_notification_never_closes_an_unrelated_customer_question(self):
        self.question()
        self.crash()
        self.recover()
        self.assertEqual(len(open_customer_questions(self.ticket())), 1)
        self.assertEqual(self.ticket()["status"], "offen")

    def test_confirmed_workshop_question_keeps_waiting_for_customer(self):
        self.crash(purpose="workshop_question")
        self.recover()
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_customer")
        self.assertEqual(self.ticket()["status"], "offen")

    def test_customer_reply_after_claim_is_not_overwritten_by_failed_recovery(self):
        from app.customer_handoff import receive_customer_message
        self.crash(purpose="workshop_question")
        receive_customer_message(self.ticket(), "Ja, liegt im Fahrzeug.", workshop_id=self.wid,
                                 message_id="customer-reply-during-interruption")
        state_after_reply = self.ticket()["conversation_state"]
        self.recover("failed")
        self.assertEqual(self.ticket()["conversation_state"], state_after_reply)
        self.assertEqual(self.ticket()["notes"][-1]["reply_to_message_id"], "dispatch-attempt-one")

    def test_newer_employee_action_is_not_undone_by_failed_recovery(self):
        self.crash()
        set_whatsapp_conversation_control(workshop_id=self.wid, customer_phone=self.phone, mode="manual")
        self.recover("failed")
        self.assertEqual(self.ticket()["conversation_state"], "workshop_active")

    def test_sent_recovery_resolves_its_question_but_preserves_newer_customer_information_wait(self):
        self.question()
        self.crash(purpose="workshop_answer", target="customer-question-one")
        add_ticket_note(self.tid, "Bitte zusätzlich den Schlüssel abholen.", workshop_id=self.wid,
                        sender_role="customer", purpose="customer_information", requires_human_action=True,
                        message_id="new-human-action-after-claim")
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_workshop")
        self.recover("sent")
        self.assertEqual(open_customer_questions(self.ticket()), [])
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_workshop")
        self.assertEqual(self.ticket()["notes"][-1]["message_id"], "new-human-action-after-claim")
        self.assertTrue(self.ticket()["notes"][-1]["requires_human_action"])

    def test_meta_success_resolves_its_question_but_preserves_newer_customer_information_wait(self):
        self.question()
        self.crash(purpose="workshop_answer", target="customer-question-one")
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET wa_message_id = ? WHERE workshop_id = ? AND message_id = ?",
                         ("wamid.newer-info", self.wid, "dispatch-attempt-one"))
            conn.commit()
        add_ticket_note(self.tid, "Bitte zusätzlich den Schlüssel abholen.", workshop_id=self.wid,
                        sender_role="customer", purpose="customer_information", requires_human_action=True,
                        message_id="new-human-action-before-meta")
        update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.newer-info", status="delivered")
        self.assertEqual(open_customer_questions(self.ticket()), [])
        self.assertEqual(self.ticket()["conversation_state"], "waiting_for_workshop")

    def test_foreign_workshop_cannot_list_or_resolve_the_claim(self):
        from app.dispatch_recovery import dispatch_recovery_context
        self.crash()
        context = dispatch_recovery_context(workshop_id="another-workshop", customer_phone=self.phone)
        self.assertFalse(context["dispatch_blocked"])
        self.assertEqual(context["stale_dispatches"], [])
        with self.assertRaises((ValueError, KeyError)):
            self.recover(workshop_id="another-workshop")
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_repeated_recovery_is_idempotent_and_does_not_replace_original_actor(self):
        self.crash()
        self.recover("failed")
        before = self.row()
        before_notes = self.ticket()["notes"]
        self.recover("failed", actor_email="another-user@example.invalid")
        self.assertEqual(self.row(), before)
        self.assertEqual(self.ticket()["notes"], before_notes)

    def test_opposite_recovery_cannot_change_an_already_finalized_attempt(self):
        self.crash()
        self.recover("failed")
        before = self.row()
        try:
            self.recover("sent")
        except ValueError:
            pass
        self.assertEqual(self.row(), before)

    def test_regular_finalized_attempt_is_not_eligible_for_recovery(self):
        self.send()
        before = self.row()
        try:
            self.recover("failed")
        except ValueError:
            pass
        self.assertEqual(self.row(), before)

    def test_late_normal_success_cannot_overwrite_manual_failed_resolution(self):
        def late_success():
            self.age()
            self.recover("failed")
            return WhatsAppSendResult(True, 200, "wamid.late-success", {})
        result = self.send(callback=late_success)
        self.assertFalse(result.ok)
        self.assertEqual(self.row()["status"], "failed")
        self.assertEqual(self.row()["dispatch_state"], "complete")
        self.assertEqual(self.ticket()["notes"][-1]["delivery_status"], "failed")

    def test_late_normal_failure_cannot_overwrite_manual_sent_resolution(self):
        self.question()
        def late_failure():
            self.age()
            self.recover("sent")
            return WhatsAppSendResult(False, 400, None, {}, "late rejection")
        result = self.send(purpose="workshop_answer", target="customer-question-one", callback=late_failure)
        self.assertTrue(result.ok)
        self.assertEqual(self.row()["status"], "sent")
        self.assertEqual(open_customer_questions(self.ticket()), [])

    def test_normal_finalizer_and_recovery_compete_for_exactly_one_claim(self):
        from app.whatsapp import finalize_whatsapp_dispatch
        self.crash()
        started_at = self.row()["dispatch_started_at"]
        barrier = Barrier(2)
        def normal():
            barrier.wait(timeout=10)
            return finalize_whatsapp_dispatch(workshop_id=self.wid, message_id="dispatch-attempt-one", status="failed",
                                               expected_dispatch_started_at=started_at)
        def recovery():
            barrier.wait(timeout=10)
            try:
                return self.recover("sent")
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            normal_future = pool.submit(normal)
            recovery_future = pool.submit(recovery)
            normal_result = normal_future.result(timeout=20)
            recovery_future.result(timeout=20)
        expected_status = "failed" if normal_result["finalized"] else "sent"
        self.assertEqual(self.row()["status"], expected_status)
        self.assertEqual(self.ticket()["notes"][-1]["delivery_status"], expected_status)
        self.assertEqual(self.row()["dispatch_state"], "complete")

    def test_two_concurrent_identical_recoveries_only_create_one_audit_and_semantic_result(self):
        self.question()
        self.crash(purpose="workshop_answer", target="customer-question-one")
        barrier = Barrier(2)
        def recover_once(actor):
            barrier.wait(timeout=10)
            return self.recover(actor_email=actor)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(recover_once, [self.actor, "second-owner@example.invalid"]))
        self.assertEqual(sum(bool(result["finalized"]) for result in results), 1)
        self.assertEqual(open_customer_questions(self.ticket()), [])
        self.assertEqual(len(self.ticket()["notes"]), 2)
        self.assertIn(json.loads(self.row()["payload_json"])["manual_resolution"]["actor_email"],
                      {self.actor, "second-owner@example.invalid"})

    def test_late_meta_receipt_does_not_rewrite_confirmed_failed_attempt_or_resolve_question(self):
        self.question()
        self.crash(purpose="workshop_answer", target="customer-question-one")
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET wa_message_id = ? WHERE workshop_id = ? AND message_id = ?",
                         ("wamid.recovery-late-receipt", self.wid, "dispatch-attempt-one"))
            conn.commit()
        self.recover("failed")
        update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.recovery-late-receipt", status="delivered")
        self.assertEqual(self.row()["status"], "failed")
        self.assertEqual(self.ticket()["notes"][-1]["delivery_status"], "failed")
        self.assertEqual(len(open_customer_questions(self.ticket())), 1)

    def test_late_meta_receipts_are_monotone_after_manual_sent_confirmation(self):
        self.crash()
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET wa_message_id = ? WHERE workshop_id = ? AND message_id = ?",
                         ("wamid.recovery-monotone", self.wid, "dispatch-attempt-one"))
            conn.commit()
        self.recover("sent")
        for status in ("read", "delivered", "sent", "failed", "read"):
            update_whatsapp_message_status(workshop_id=self.wid, wa_message_id="wamid.recovery-monotone", status=status)
        self.assertEqual(self.row()["status"], "read")
        self.assertEqual(self.ticket()["notes"][-1]["delivery_status"], "sent")
        self.assertEqual(json.loads(self.row()["payload_json"])["manual_resolution"]["resolution"], "sent")

    def test_retry_rechecks_service_window_instead_of_using_original_permission(self):
        self.send(callback=lambda: WhatsAppSendResult(False, 400, None, {}, "rejected"))
        with closing(get_conn()) as conn:
            conn.execute("UPDATE whatsapp_messages SET customer_message_at = ? WHERE workshop_id = ? AND direction = 'inbound'",
                         ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), self.wid))
            conn.commit()
        sender = Mock()
        with self.assertRaises(ValueError):
            self.send(mid="dispatch-attempt-two", callback=sender)
        sender.assert_not_called()
        self.assertIsNone(self.row("dispatch-attempt-two"))


class DispatchRecoveryAuthenticationTests(unittest.TestCase):
    send = DispatchRecoveryTests.send
    row = DispatchRecoveryTests.row
    ticket = DispatchRecoveryTests.ticket
    age = DispatchRecoveryTests.age
    crash = DispatchRecoveryTests.crash

    def setUp(self):
        DispatchRecoveryTests.setUp(self)
        self.client = TestClient(fixtures.main.app)
        self.path = "/dashboard/whatsapp/messages/dispatch-attempt-one/resolve"
        self.crash()

    def tearDown(self):
        self.client.close()
        fixtures.WhatsAppReliabilityTests.tearDown(self)

    def login_as(self, *, role="owner", workshop_id=None):
        wid = workshop_id or self.wid
        user = {"email": f"recovery-{role}-{wid}@example.invalid", "workshop_id": wid, "role": role}
        with closing(get_conn()) as conn:
            conn.execute("INSERT INTO workshops (id, name) VALUES (?, ?) ON CONFLICT(id) DO NOTHING", (wid, wid))
            conn.execute("INSERT INTO users (email, password_hash, workshop_id, role) VALUES (?, ?, ?, ?)",
                         (user["email"], "unused-test-password-hash", wid, role))
            conn.commit()
        self.client.cookies.set(SESSION_COOKIE, create_session_token(user))
        return user

    def post(self, **extra):
        return self.client.post(self.path, data={
            "workshop_id": self.wid, "resolution": "sent", "confirmed": "true",
            "customer_phone": self.phone, "ticket_id": self.tid, "context": "ticket", **extra,
        }, follow_redirects=False)

    def test_unauthenticated_dashboard_recovery_requires_login_and_leaves_claim_unchanged(self):
        before = self.row()
        response = self.post()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))
        self.assertEqual(self.row(), before)

    def test_authenticated_owner_is_recorded_in_audit_instead_of_submitted_actor(self):
        user = self.login_as()
        response = self.post(actor_email="forged@example.invalid")
        self.assertEqual(response.status_code, 303, response.text)
        audit = json.loads(self.row()["payload_json"])["manual_resolution"]
        self.assertEqual(audit["actor_email"], user["email"])
        self.assertEqual(self.row()["status"], "sent")

    def test_existing_employee_role_can_resolve_own_workshop_dispatch(self):
        self.login_as(role="employee")
        response = self.post(resolution="failed")
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self.row()["status"], "failed")

    def test_owner_cannot_select_another_workshop_in_recovery_form(self):
        self.login_as(workshop_id="different-owner-workshop")
        before = self.row()
        response = self.post()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.row(), before)

    def test_missing_own_workshop_message_cannot_be_resolved_through_foreign_id(self):
        self.login_as(workshop_id="different-owner-workshop")
        response = self.post(workshop_id="different-owner-workshop")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_admin_can_select_workshop_using_existing_dashboard_permissions(self):
        user = self.login_as(role="admin", workshop_id="administration-workshop")
        response = self.post()
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(json.loads(self.row()["payload_json"])["manual_resolution"]["actor_email"], user["email"])

    def test_missing_confirmation_is_rejected_even_with_valid_dashboard_session(self):
        self.login_as()
        response = self.post(confirmed="false")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_revoked_dashboard_session_cannot_resolve_stale_dispatch(self):
        user = self.login_as()
        with closing(get_conn()) as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", ("changed-test-password-hash", user["email"]))
            conn.commit()
        response = self.post()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))
        self.assertEqual(self.row()["dispatch_state"], "sending")

    def test_cross_origin_recovery_is_blocked(self):
        self.login_as()
        response = self.client.post(self.path, data={
            "workshop_id": self.wid, "resolution": "sent", "confirmed": "true",
        }, headers={"Origin": "https://untrusted.example.invalid"}, follow_redirects=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.row()["dispatch_state"], "sending")


if __name__ == "__main__":
    unittest.main()
