"""Bounded owner worklists and an append-only, content-free event cursor."""
from collections import deque
from contextlib import closing
from urllib.parse import urlencode, urlsplit, parse_qsl

from app.db import get_conn
from app.tickets import iter_dashboard_tickets, find_ticket_by_id
from app.communication import customer_task_label, open_customer_tasks


def list_context(value, workshop_id, *, fallback='/dashboard'):
    """Only known local lists and typed/allowlisted parameters may be returned to."""
    try:
        parsed = urlsplit(value if isinstance(value, str) else '')
    except ValueError:
        parsed = urlsplit('')
    path = parsed.path if not parsed.netloc and not parsed.scheme and parsed.path in {'/dashboard', '/dashboard/archive'} else fallback
    allowed = {'status', 'source', 'question_state', 'task_state', 'metric', 'q', 'sort', 'page', 'limit'}
    params = {k: v[:256] for k, v in parse_qsl(parsed.query) if k in allowed} if path == parsed.path else {}
    params['workshop_id'] = workshop_id
    return path + '?' + urlencode(params)


def overview(workshop_id, archive, filters, prepare, stats_for, matches, attention):
    """SQL orders/scopes first; normalized ledger filters precede pagination.

    Keep at most one page, the final page and five attention tickets in memory.
    Aggregate over the complete scope, never over a latest-N sample.
    """
    size, page = filters['limit'], filters['page']
    start = (page - 1) * size
    stats, rows, top, total = stats_for([]), [], [], 0
    tail = deque(maxlen=size)
    for raw in iter_dashboard_tickets(workshop_id, archive=archive, sort=filters['sort']):
        t = prepare(raw)
        item_stats = stats_for([t])
        for key in stats:
            stats[key] += item_stats[key]
        top = attention(top + [t])
        if filters['status'] != 'all' and t['status_ui'] != filters['status']:
            continue
        if filters['source'] != 'all' and t['source'] != filters['source']:
            continue
        question = filters['question_state']
        if question == 'open' and not t['customer_question_open']:
            continue
        if question == 'answered' and not (t['has_customer_question'] and not t['customer_question_open']):
            continue
        task = filters['task_state']
        if task == 'pending' and not t['needs_attention']:
            continue
        if task == 'information' and not any(n['purpose'] == 'customer_information' for n in t['open_tasks']):
            continue
        if task == 'waiting' and t['conversation_state'] != 'waiting_for_customer':
            continue
        if filters['metric'] and not item_stats.get(filters['metric']):
            continue
        if not matches(t, filters['q']):
            continue
        if start <= total < start + size:
            rows.append(t)
        tail.append(t)
        total += 1
    pages = max(1, (total + size - 1) // size)
    if page > pages:
        rows = list(tail)[-(total % size or size):] if total else []
        page = pages
    return dict(tickets=rows, stats=stats, attention_tickets=top, total=total, pages=pages, page=page)


def events(workshop_id, after=None):
    with closing(get_conn()) as conn:
        if after is None:
            row = conn.execute('SELECT MAX(id) AS latest FROM dashboard_events WHERE workshop_id = ?', (workshop_id,)).fetchone()
            return {'cursor': row['latest'] or 0, 'events': [], 'more': False}
        rows = conn.execute('''SELECT e.id, e.ticket_id, e.message_id FROM dashboard_events e
            JOIN tickets t ON t.workshop_id=e.workshop_id AND t.ticket_id=e.ticket_id
            WHERE e.workshop_id = ? AND e.id > ? ORDER BY e.id LIMIT 51''', (workshop_id, after)).fetchall()
    result = []
    for row in rows[:50]:
        ticket = find_ticket_by_id(row['ticket_id'], workshop_id)
        if not ticket:
            continue
        note = next((n for n in open_customer_tasks(ticket) if n['message_id'] == row['message_id']), None)
        if row['message_id'] and not note:
            continue
        result.append({'id': row['id'], 'ticket_id': row['ticket_id'],
                       'label': customer_task_label(note) if note else 'Neue Anfrage',
                       'text': (note['text'] if note else ticket.get('fahrzeug') or 'Neue Anfrage')[:200],
                       'url': '/dashboard/ticket/' + row['ticket_id'] + '?' + urlencode({'workshop_id':workshop_id})
                              + ('#communication-' + row['message_id'] if note else '')})
    return {'cursor': rows[min(len(rows), 50)-1]['id'] if rows else after,
            'events': result, 'more': len(rows) > 50}
