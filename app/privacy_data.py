"""Tenant-scoped exports and explicit, previewed deletion of operational customer data."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import get_conn, is_postgres

TABLE_KEYS = {
    "tickets": "id",
    "conversation_sessions": "session_id",
    "whatsapp_messages": "id",
    "whatsapp_events": "id",
    "whatsapp_conversation_controls": "customer_phone",
}
MAX_EXPORT_ROWS = 10000
MAX_EXPORT_BYTES = 20 * 1024 * 1024


class PrivacyError(ValueError):
    pass


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hmac.new(settings.auth_secret.encode(), ("privacy:" + value).encode(), hashlib.sha256).hexdigest()


def make_token(*, email: str, workshop_id: str, action: str, selection=None, digest=None) -> str:
    payload = {"email": email, "workshop_id": workshop_id, "action": action,
               "selection": selection, "digest": digest, "expires": int(time.time()) + 600}
    encoded = base64.urlsafe_b64encode(_json(payload).encode()).decode().rstrip("=")
    return encoded + "." + _hash(encoded)


def read_token(token: str, *, email: str, workshop_id: str, action: str) -> dict:
    try:
        if len(token) > 4096:
            raise ValueError
        encoded, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_hash(encoded), signature):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (payload["email"] != email or payload["workshop_id"] != workshop_id or payload["action"] != action
                or payload["expires"] <= int(time.time())):
            raise ValueError
        return payload
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PrivacyError("Die Bestätigung ist ungültig oder abgelaufen. Bitte die Seite neu öffnen.") from None


def normalize_phone(value) -> str:
    text = str(value or "").strip()
    if not text or re.search(r"[^0-9+ ()/.-]", text):
        return ""
    digits = re.sub(r"[^0-9]", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    return digits if 7 <= len(digits) <= 15 else ""


def selection_for(kind: str, value: str) -> dict:
    value = value.strip()
    if kind == "phone":
        value = normalize_phone(value)
        if not value:
            raise PrivacyError("Bitte eine vollständige Telefonnummer eingeben; internationale Nummern mit Ländervorwahl.")
    elif kind == "ticket":
        if not value or len(value) > 128:
            raise PrivacyError("Bitte eine vollständige Ticket-ID eingeben.")
    else:
        raise PrivacyError("Bitte Telefonnummer oder Ticket-ID auswählen.")
    return {"kind": kind, "value": value}


def _session_state(row: dict) -> dict:
    try:
        state = json.loads(row["state_json"])
    except (ValueError, TypeError):
        return {}
    if not isinstance(state, dict):
        return {}
    # Older or damaged records must not break a customer's entire request.
    return {key: state[key] for key in ("ticket_id", "telefon") if isinstance(state.get(key), str)}


def read_records(conn, workshop_id: str, *, lock: bool = False) -> dict:
    records = {}
    total = 0
    size = 0
    for table in TABLE_KEYS:
        suffix = " FOR UPDATE" if lock and is_postgres() else ""
        rows = conn.execute(f"SELECT * FROM {table} WHERE workshop_id = ? ORDER BY {TABLE_KEYS[table]} LIMIT ?{suffix}",
                            (workshop_id, MAX_EXPORT_ROWS + 1)).fetchall()
        records[table] = [dict(row) for row in rows]
        total += len(rows)
        size += len(_json(records[table]).encode())
        if total > MAX_EXPORT_ROWS or size > MAX_EXPORT_BYTES:
            raise PrivacyError("Der Datenbestand ist für den direkten Download zu groß. Bitte einen betreuten Export anfordern.")
    return records


def select_records(records: dict, selection: dict) -> dict:
    selection = selection_for(selection["kind"], selection["value"])
    phone = selection["value"] if selection["kind"] == "phone" else None
    ticket_ids = {selection["value"]} if selection["kind"] == "ticket" else set()
    if phone:
        ticket_ids.update(row["ticket_id"] for row in records["tickets"]
                          if phone in (normalize_phone(row["telefon"]), normalize_phone(row.get("verified_customer_phone"))))
        ticket_ids.update(row["ticket_id"] for row in records["whatsapp_messages"]
                          if row["ticket_id"] and normalize_phone(row["customer_phone"]) == phone)
        ticket_ids.update(row["active_ticket_id"] for row in records["whatsapp_conversation_controls"]
                          if row["active_ticket_id"] and normalize_phone(row["customer_phone"]) == phone)
        for row in records["conversation_sessions"]:
            state = _session_state(row)
            if (state.get("ticket_id")
                    and (normalize_phone(row["phone"]) == phone or normalize_phone(state.get("telefon")) == phone)):
                ticket_ids.add(state["ticket_id"])
    result = {table: [] for table in TABLE_KEYS}
    result["tickets"] = [row for row in records["tickets"] if row["ticket_id"] in ticket_ids]
    for row in records["conversation_sessions"]:
        state = _session_state(row)
        if ((phone and (normalize_phone(row["phone"]) == phone or normalize_phone(state.get("telefon")) == phone))
                or state.get("ticket_id") in ticket_ids):
            result["conversation_sessions"].append(row)
    result["whatsapp_messages"] = [row for row in records["whatsapp_messages"]
        if (phone and normalize_phone(row["customer_phone"]) == phone) or row["ticket_id"] in ticket_ids]
    message_ids = {row["wa_message_id"] for row in result["whatsapp_messages"] if row["wa_message_id"]}
    result["whatsapp_events"] = [row for row in records["whatsapp_events"]
        if (phone and normalize_phone(row["from_phone"]) == phone) or row["wa_message_id"] in message_ids]
    result["whatsapp_conversation_controls"] = [row for row in records["whatsapp_conversation_controls"]
        if (phone and normalize_phone(row["customer_phone"]) == phone) or row["active_ticket_id"] in ticket_ids]
    return result


def fingerprint(records: dict) -> str:
    return _hash(_json(records))


def counts(records: dict) -> dict:
    return {table: len(rows) for table, rows in records.items()}


def _audit(conn, *, workshop_id: str, email: str, action: str, quantities: dict) -> None:
    now = datetime.now(timezone.utc)
    conn.execute("DELETE FROM privacy_operations WHERE created_at < ?", ((now - timedelta(days=90)).isoformat(),))
    conn.execute("INSERT INTO privacy_operations (id, workshop_id, actor_hash, action, counts_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (uuid.uuid4().hex, workshop_id, _hash(email), action, _json(quantities), now.isoformat()))


def preview(workshop_id: str, selection: dict) -> dict:
    with closing(get_conn()) as conn:
        return select_records(read_records(conn, workshop_id), selection)


def export_data(*, workshop_id: str, email: str, selection: dict | None = None, expected_digest: str | None = None) -> bytes:
    with closing(get_conn()) as conn:
        records = read_records(conn, workshop_id)
        if selection is not None:
            records = select_records(records, selection)
            if not expected_digest or not hmac.compare_digest(fingerprint(records), expected_digest):
                raise PrivacyError("Die Daten haben sich geändert. Bitte zuerst eine neue Vorschau öffnen.")
        document = {"format": "werkstattai-export-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                    "workshop_id": workshop_id, "scope": "customer" if selection else "workshop",
                    "selection": selection, "records": records,
                    "notes": ["Arbeitskopie für die Werkstatt. Vor Weitergabe Daten Dritter und interne Notizen prüfen.",
                              "Hosting-Protokolle, Backups, externe WhatsApp-Kopien und bereits heruntergeladene Dateien sind nicht enthalten."]}
        if selection is None:
            workshop = conn.execute("SELECT * FROM workshops WHERE id = ?", (workshop_id,)).fetchone()
            document["workshop"] = dict(workshop) if workshop else None
            document["users"] = [dict(row) for row in conn.execute(
                "SELECT email, workshop_id, role, created_at, updated_at FROM users WHERE workshop_id = ? ORDER BY email", (workshop_id,)).fetchall()]
        encoded = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > MAX_EXPORT_BYTES:
            raise PrivacyError("Der Export ist zu groß. Bitte einen betreuten Export anfordern.")
        _audit(conn, workshop_id=workshop_id, email=email, action="export", quantities=counts(records))
        conn.commit()
        return encoded


def delete_data(*, workshop_id: str, email: str, selection: dict, expected_digest: str) -> dict:
    with closing(get_conn()) as conn:
        if not is_postgres():
            conn.execute("BEGIN IMMEDIATE")
        try:
            records = select_records(read_records(conn, workshop_id, lock=True), selection)
            if not expected_digest or not hmac.compare_digest(fingerprint(records), expected_digest):
                raise PrivacyError("Seit der Vorschau haben sich Daten geändert. Bitte neu prüfen; es wurde nichts gelöscht.")
            if not any(records.values()):
                raise PrivacyError("Es wurden keine zu löschenden Datensätze gefunden.")
            for table, key in TABLE_KEYS.items():
                for row in records[table]:
                    conn.execute(f"DELETE FROM {table} WHERE workshop_id = ? AND {key} = ?", (workshop_id, row[key]))
            quantities = counts(records)
            _audit(conn, workshop_id=workshop_id, email=email, action="delete", quantities=quantities)
            conn.commit()
            return quantities
        except Exception:
            conn.rollback()
            raise
