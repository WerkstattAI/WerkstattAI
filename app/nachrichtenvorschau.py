"""Kleine, mandantenbezogene Gesprächsvorschau ohne interne Notizen."""
import json
from datetime import datetime, timezone

from app.communication import PURPOSE_SENDERS
from app.db import get_conn


def letzte_whatsapp_nachrichten(workshop_id, ticket_ids):
    ids = list(dict.fromkeys(str(tid) for tid in ticket_ids if tid))
    if not ids:
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM (SELECT ticket_id, message_id, direction, message_type, text, "
            "created_at, status, payload_json, ROW_NUMBER() OVER "
            "(PARTITION BY ticket_id ORDER BY created_at DESC, id DESC) AS rang "
            "FROM whatsapp_messages WHERE workshop_id = ? AND ticket_id IN ("
            + ','.join('?' for _ in ids) + ") "
            "AND COALESCE(processing_state, '') NOT IN ('echo_pruefung', 'historie_pruefung')) letzte "
            "WHERE rang = 1", [workshop_id, *ids]).fetchall()
    return {row['ticket_id']: dict(row) for row in rows}


def _zeit(wert):
    try:
        zeit = datetime.fromisoformat(str(wert).replace('Z', '+00:00'))
        return zeit.replace(tzinfo=timezone.utc) if zeit.tzinfo is None else zeit
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def letzte_nachricht(notes, whatsapp=None):
    kandidaten = [dict(n) for n in notes if isinstance(n, dict)
                  and n.get('purpose') in PURPOSE_SENDERS and n['purpose'] != 'internal_note']
    if whatsapp:
        item = dict(whatsapp)
        try:
            meta = json.loads(item.get('payload_json') or '{}')
        except (ValueError, TypeError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        kanonisch = next((n for n in notes if isinstance(n, dict)
                          and n.get('message_id') == item.get('message_id')), {})
        rolle = kanonisch.get('sender_role') or meta.get('sender_role')
        item['sender_role'] = rolle or ('customer' if item.get('direction') == 'inbound'
                                      else 'assistant' if meta.get('source') == 'webhook' else 'workshop')
        item['kanal'] = 'WhatsApp'
        if kanonisch.get('purpose', meta.get('purpose')) != 'internal_note':
            kandidaten.append(item)
    if not kandidaten:
        return None
    item = max(enumerate(kandidaten), key=lambda pair: (_zeit(pair[1].get('created_at')), pair[0]))[1]
    rolle = item.get('sender_role') or PURPOSE_SENDERS.get(item.get('purpose'))
    typ = item.get('message_type')
    text = ' '.join(str(item.get('text') or '').split())
    if typ == 'image':
        text = 'Foto' + (' · ' + text if text else '')
    if not text:
        text = {'audio': 'Sprachnachricht', 'video': 'Video', 'document': 'Dokument'}.get(typ, 'Nachricht ohne Text')
    status = item.get('status') or item.get('delivery_status')
    hinweis = {'failed': 'Nicht gesendet', 'unknown': 'Versand unklar', 'pending': 'Versand ausstehend'}.get(status, '')
    return {'text': text[:700], 'sender': {'customer': 'Kunde', 'assistant': 'Assistent',
            'workshop': 'Werkstatt'}.get(rolle, 'Nachricht'), 'created_at': item.get('created_at'),
            'kanal': item.get('kanal'), 'versandhinweis': hinweis}
