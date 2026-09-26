from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


def normalize_customer_phone(value: str | None) -> str:
    """Normalize a complete phone number for equality, never substring search.

    National numbers are interpreted as German numbers, matching the product's
    existing intake. Invalid, short and ambiguous values cannot authorize access.
    """
    raw = str(value or "").strip()
    if not raw or not re.fullmatch(r"\+?[0-9 ()/.-]+", raw):
        return ""
    digits = re.sub(r"[^0-9]", "", raw)
    if raw.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        return ""
    return digits


@dataclass(frozen=True)
class CustomerAccess:
    """Server-created evidence, separate from customer-supplied intake data.

    Browser access comes from ticket IDs in an owned server-side conversation.
    WhatsApp access comes exclusively from the verified webhook sender. A phone
    entered into chat or IntakeState must never be passed as verified_phone.
    """

    workshop_id: str
    allowed_ticket_ids: frozenset[str] = field(default_factory=frozenset)
    verified_phone: str | None = None

    def allows(self, ticket: Mapping[str, Any] | None) -> bool:
        if not ticket or not self.workshop_id:
            return False
        if str(ticket.get("workshop_id") or "") != self.workshop_id:
            return False
        ticket_id = str(ticket.get("ticket_id") or "")
        if not ticket_id:
            return False
        if self.verified_phone is not None:
            # An old remembered ID cannot override WhatsApp sender ownership.
            verified = normalize_customer_phone(self.verified_phone)
            return bool(verified and verified == normalize_customer_phone(ticket.get("verified_customer_phone")))
        return ticket_id in self.allowed_ticket_ids
