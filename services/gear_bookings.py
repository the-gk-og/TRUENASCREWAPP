"""services/gear_bookings.py — reservations, double-booking warnings and "booked on" views.

A pick list line linked to equipment *is* a reservation: it holds that many of the
type for the event's time window (or the line's own hold window, when someone set
one, e.g. picking up a day early for prep). A unit on a line (PickListUnit) reserves
that specific unit. Units already checked out count too: an open check-out holds the
unit for its event, and one that never came back from a finished event holds it
until it is scanned back in.

Everything is naive local time, like the rest of the app.
"""

from datetime import datetime, time as dtime

from extensions import db
from models import (BulkCheckout, Equipment, EquipmentUnit, Event, PickListItem,
                    UnitCheckout, UNIT_STATUS_LABELS)


# ---------------------------------------------------------------------------
# Time windows
# ---------------------------------------------------------------------------

def event_window(event):
    """(start, end) the event holds its equipment for: its own time plus every labeled
    time (Bump-in, Show 1 ...). All-day events and events with no end hold gear until
    the end of their last day."""
    start = event.event_date
    end = event.event_end_date or event.event_date
    times = list(getattr(event, 'times', None) or [])
    for t in times:
        start, end = min(start, t.start_time), max(end, t.end_time)
    if event.all_day:
        start = datetime.combine(start.date(), dtime.min)
    if event.all_day or (not event.event_end_date and not times):
        end = datetime.combine(end.date(), dtime.max)
    return start, max(start, end)


def line_window(line):
    """The window one pick list line holds its gear for, or None for the general list."""
    ev = line.event
    if ev is None:
        return None
    start, end = event_window(ev)
    if line.hold_from:
        start = line.hold_from
    if line.hold_until:
        end = line.hold_until
    return start, max(start, end)


def overlaps(a, b):
    """Do two (start, end) windows share any time?"""
    return a[0] <= b[1] and b[0] <= a[1]


def _union(a, b):
    return b if a is None else (min(a[0], b[0]), max(a[1], b[1]))


def _when(win):
    s, e = win
    if s.date() == e.date():
        return f"{s.strftime('%a')} {s.day} {s.strftime('%b')}"
    return f"{s.strftime('%a')} {s.day} {s.strftime('%b')} – {e.strftime('%a')} {e.day} {e.strftime('%b')}"


def _event_is_archived(ev, now=None):
    from routes.picklist import _event_is_archived as archived
    return archived(ev, now)


# ---------------------------------------------------------------------------
# Demand for one equipment type, per event
# ---------------------------------------------------------------------------

def _demands(eq):
    """{event_id: {event, qty, planned, out, window, line_ids, unit_ids}} for one type.

    qty is what the event needs at once: the pick list quantity, or what is
    actually out to it if that is more."""
    d = {}

    def slot(ev):
        return d.setdefault(ev.id, {'event': ev, 'planned': 0, 'out': 0, 'window': None,
                                    'line_ids': [], 'unit_ids': []})

    for line in PickListItem.query.filter(PickListItem.equipment_id == eq.id,
                                          PickListItem.event_id.isnot(None)).all():
        s = slot(line.event)
        s['planned'] += line.quantity or 1
        s['window'] = _union(s['window'], line_window(line))
        s['line_ids'].append(line.id)
        s['unit_ids'] += [l.unit_id for l in line.unit_links]

    if eq.is_individual:
        rows = (db.session.query(UnitCheckout.event_id, db.func.count(UnitCheckout.id))
                .join(EquipmentUnit, EquipmentUnit.id == UnitCheckout.unit_id)
                .filter(EquipmentUnit.equipment_id == eq.id, UnitCheckout.returned_at.is_(None))
                .group_by(UnitCheckout.event_id).all())
    else:
        rows = {}
        for b in BulkCheckout.query.filter_by(equipment_id=eq.id).filter(BulkCheckout.returned_at.is_(None)):
            rows[b.event_id] = rows.get(b.event_id, 0) + b.outstanding
        rows = list(rows.items())
    for event_id, n in rows:
        ev = db.session.get(Event, event_id)
        if ev is not None and n:
            slot(ev)['out'] += n

    for s in d.values():
        if s['window'] is None:
            s['window'] = event_window(s['event'])
        s['qty'] = max(s['planned'], s['out'])
    return d


def type_status(eq, event, extra=0, demands=None):
    """How one equipment type stands for `event`'s window.

    Returns {need, peak, usable, short, others, quarantined, repair, still_out, message}.
    peak is the most needed at any one moment while this event holds the gear
    (this event plus every overlapping one), so two shows that both overlap a
    festival weekend but not each other aren't added together.
    `extra` adds a prospective quantity to this event (for "can I add 3 more?")."""
    demands = demands if demands is not None else _demands(eq)
    mine = demands.get(event.id) or {'event': event, 'qty': 0, 'planned': 0, 'out': 0,
                                     'window': event_window(event), 'line_ids': [], 'unit_ids': []}
    win = mine['window']
    others = {eid: s for eid, s in demands.items()
              if eid != event.id and s['qty'] and overlaps(win, s['window'])}
    need = mine['qty'] + extra

    peak, at_peak = need, []
    for p in sorted({win[0]} | {max(win[0], s['window'][0]) for s in others.values()}):
        live = [s for s in others.values() if s['window'][0] <= p <= s['window'][1]]
        total = need + sum(s['qty'] for s in live)
        if total > peak or (total == peak and not at_peak and live):
            peak, at_peak = total, live

    busy_ids = set(others) | {event.id}
    quarantined = repair = 0
    still_out = []
    if eq.is_individual:
        usable = 0
        for u in eq.units:
            st = u.status or 'available'
            if st in ('retired', 'lost'):
                continue
            if st == 'quarantined':
                quarantined += 1
                continue
            if st == 'repair':
                repair += 1
                continue
            co = u.open_checkout
            if co and co.event_id not in busy_ids:
                still_out.append({'what': u.asset_tag, 'event_id': co.event_id,
                                  'event_title': co.event.title if co.event else ''})
                continue
            usable += 1
    else:
        usable = eq.owned
        for b in BulkCheckout.query.filter_by(equipment_id=eq.id).filter(BulkCheckout.returned_at.is_(None)):
            if b.event_id not in busy_ids and b.outstanding:
                usable -= b.outstanding
                still_out.append({'what': f'{b.outstanding}', 'event_id': b.event_id,
                                  'event_title': b.event.title if b.event else ''})
        usable = max(0, usable)

    short = max(0, peak - usable)
    status = {
        'equipment_id': eq.id, 'equipment_name': eq.name, 'need': need, 'peak': peak,
        'usable': usable, 'short': short, 'line_ids': list(mine['line_ids']),
        'others': [{'event_id': s['event'].id, 'event_title': s['event'].title, 'qty': s['qty'],
                    'when': _when(s['window'])} for s in at_peak],
        'quarantined': quarantined, 'repair': repair, 'still_out': still_out,
    }
    status['message'] = _type_message(status) if short else ''
    return status


def _type_message(s):
    why = []
    for o in s['others']:
        why.append(f"{o['event_title']} needs {o['qty']} at the same time")
    if s['repair']:
        why.append(f"{s['repair']} in repair")
    if s['quarantined']:
        why.append(f"{s['quarantined']} out of use")
    by_event = {}
    for o in s['still_out']:
        by_event.setdefault(o['event_title'], []).append(o['what'])
    for title, what in by_event.items():
        why.append(f"{', '.join(what)} still out on {title}")
    msg = (f"Short {s['short']} × {s['equipment_name']}: {s['peak']} needed at once, "
           f"only {s['usable']} usable")
    return msg + (f" ({'; '.join(why)})" if why else '')


# ---------------------------------------------------------------------------
# Specific units
# ---------------------------------------------------------------------------

def unit_reserved_elsewhere(unit, event, window=None):
    """Other events whose pick lists reserve this unit at a time overlapping `event`."""
    win = window or event_window(event)
    seen, out = set(), []
    for link in unit.pick_links:
        line = link.pick_list_item
        other = line.event
        if other is None or other.id == event.id or other.id in seen:
            continue
        if overlaps(win, line_window(line)):
            seen.add(other.id)
            out.append(other)
    return out


def unit_issues(unit, event, window=None):
    """Why a unit reserved for `event` might not be there: [{code, message}]."""
    win = window or event_window(event)
    tag = unit.asset_tag
    issues = []
    st = unit.status or 'available'
    if st != 'available':
        q = unit.open_quarantine if st == 'quarantined' else None
        why = f': {q.reason}' if q and q.reason else ''
        issues.append({'code': st, 'message': f'{tag} is {UNIT_STATUS_LABELS.get(st, st).lower()}{why}'})
    co = unit.open_checkout
    if co and co.event_id != event.id:
        title = co.event.title if co.event else 'another event'
        if co.event and overlaps(win, event_window(co.event)):
            issues.append({'code': 'out_overlapping', 'message': f'{tag} is out on {title}, which overlaps'})
        else:
            issues.append({'code': 'still_out', 'message': f'{tag} is still out on {title} and not back yet'})
    for other in unit_reserved_elsewhere(unit, event, win):
        issues.append({'code': 'double_booked', 'message': f'{tag} is also reserved for {other.title} '
                                                           f'({_when(event_window(other))})'})
    due = unit.maintenance_due()
    if due and due['state'] != 'ok':
        from datetime import date
        when = date.fromisoformat(due['date'])
        if when <= win[1].date():
            issues.append({'code': 'maintenance',
                           'message': f"{tag}: {due['kind_label']} "
                                      f"{'overdue since' if due['state'] == 'overdue' else 'due'} {due['date_text']}"})
    return issues


# ---------------------------------------------------------------------------
# What the pick list and event page show
# ---------------------------------------------------------------------------

def event_gear_warnings(event):
    """Everything over-committed for one event.

    Returns {'types': [type_status with short > 0], 'units': [{unit_id, asset_tag,
    line_id, code, message}], 'by_line': {line_id: [message]}, 'count': n}."""
    lines = PickListItem.query.filter(PickListItem.event_id == event.id,
                                      PickListItem.equipment_id.isnot(None)).order_by(PickListItem.id).all()
    report = {'types': [], 'units': [], 'by_line': {}, 'count': 0}
    done = set()
    for line in lines:
        eq = line.equipment
        if eq is None:
            continue
        if eq.id not in done:
            done.add(eq.id)
            s = type_status(eq, event)
            if s['short']:
                report['types'].append(s)
                for lid in s['line_ids']:
                    report['by_line'].setdefault(lid, []).append(s['message'])
        win = line_window(line)
        for link in line.unit_links:
            for issue in unit_issues(link.unit, event, win):
                report['units'].append({'unit_id': link.unit_id, 'asset_tag': link.unit.asset_tag,
                                        'line_id': line.id, **issue})
                report['by_line'].setdefault(line.id, []).append(issue['message'])
    report['count'] = len(report['types']) + len(report['units'])
    return report


def equipment_bookings(eq, now=None):
    """Upcoming commitments for one type ("booked on"), soonest first.

    Each row: {event_id, event_title, when, start, end, qty, planned, out, units:[tag],
    short, message}. Events that have finished only show while gear is still out."""
    now = now or datetime.now()
    demands = _demands(eq)
    tags = {u.id: u.asset_tag for u in eq.units}
    rows = []
    for eid, s in demands.items():
        ev = s['event']
        if s['window'][1] < now and not s['out']:
            continue
        st = type_status(eq, ev, demands=demands)
        rows.append({'event_id': eid, 'event_title': ev.title, 'when': _when(s['window']),
                     'start': s['window'][0], 'end': s['window'][1],
                     'qty': s['qty'], 'planned': s['planned'], 'out': s['out'],
                     'finished': _event_is_archived(ev, now),
                     'units': sorted(tags[u] for u in set(s['unit_ids']) if u in tags),
                     'short': st['short'], 'message': st['message']})
    rows.sort(key=lambda r: r['start'])
    return rows


def unit_bookings(unit, now=None):
    """Upcoming reservations and the open check-out for one unit, soonest first."""
    now = now or datetime.now()
    rows = []
    for link in unit.pick_links:
        line = link.pick_list_item
        win = line_window(line)
        if win is None or win[1] < now:
            continue
        ev = line.event
        clash = unit_reserved_elsewhere(unit, ev, win)
        rows.append({'event_id': ev.id, 'event_title': ev.title, 'when': _when(win), 'start': win[0],
                     'kind': 'reserved', 'clash': [o.title for o in clash]})
    co = unit.open_checkout
    if co and co.event:
        rows.append({'event_id': co.event_id, 'event_title': co.event.title,
                     'when': _when(event_window(co.event)), 'start': event_window(co.event)[0],
                     'kind': 'out', 'clash': []})
    rows.sort(key=lambda r: r['start'])
    for r in rows:
        r['start'] = r['start'].isoformat(timespec='minutes')
    return rows
