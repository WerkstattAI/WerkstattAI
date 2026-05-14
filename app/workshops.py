from __future__ import annotations

from typing import Any

from app.db import default_workshop_id, get_conn


DEFAULT_WORKSHOP = {
    "id": "demo-werkstatt",
    "name": "Meier Werkstatt Family",
    "address": "Arnstorfer Str. 5",
    "phone": "123456789",
    "email": "Meierfamily@hjh.de",
    "opening_hours": "Montag bis Freitag: 09:00-17:00; Samstag: 09:00-14:00; Sonntag: geschlossen",
    "services": "Autoreparaturen, Reifenwechsel, Polieren",
    "pricing_info": (
        "Aktuell gibt es noch keine festen Preisangaben. "
        "Die Werkstatt prueft Anfragen individuell und meldet sich mit einer Einschaetzung."
    ),
    "towing_info": "Unsere Werkstatt kooperiert mit dem Abschleppdienst Mueller.",
}


def _normalize_workshop_id(workshop_id: str | None = None) -> str:
    return (workshop_id or default_workshop_id()).strip() or default_workshop_id()


def _row_to_workshop(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "phone": row["phone"],
        "email": row["email"],
        "opening_hours": row["opening_hours"],
        "services": row["services"],
        "pricing_info": row["pricing_info"],
        "towing_info": row["towing_info"],
    }


def get_workshop(workshop_id: str | None = None) -> dict[str, Any]:
    wid = _normalize_workshop_id(workshop_id)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                name,
                address,
                phone,
                email,
                opening_hours,
                services,
                pricing_info,
                towing_info
            FROM workshops
            WHERE id = ?
            LIMIT 1
            """,
            (wid,),
        ).fetchone()

    if not row:
        return {**DEFAULT_WORKSHOP, "id": wid}

    workshop = _row_to_workshop(row)
    for key, value in DEFAULT_WORKSHOP.items():
        if not workshop.get(key):
            workshop[key] = value

    return workshop


def update_workshop(
    workshop_id: str | None = None,
    *,
    name: str,
    address: str,
    phone: str,
    email: str,
    opening_hours: str,
    services: str,
    pricing_info: str,
    towing_info: str,
) -> dict[str, Any]:
    wid = _normalize_workshop_id(workshop_id)
    values = {
        "name": name.strip(),
        "address": address.strip(),
        "phone": phone.strip(),
        "email": email.strip(),
        "opening_hours": opening_hours.strip(),
        "services": services.strip(),
        "pricing_info": pricing_info.strip(),
        "towing_info": towing_info.strip(),
    }

    if not values["name"]:
        raise ValueError("Der Werkstattname darf nicht leer sein.")

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO workshops (
                id,
                name,
                address,
                phone,
                email,
                opening_hours,
                services,
                pricing_info,
                towing_info
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                address = excluded.address,
                phone = excluded.phone,
                email = excluded.email,
                opening_hours = excluded.opening_hours,
                services = excluded.services,
                pricing_info = excluded.pricing_info,
                towing_info = excluded.towing_info,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                wid,
                values["name"],
                values["address"],
                values["phone"],
                values["email"],
                values["opening_hours"],
                values["services"],
                values["pricing_info"],
                values["towing_info"],
            ),
        )
        conn.commit()

    return get_workshop(wid)
