"""
routes/calendar.py
==================
Calendar page, its JSON feed (consumed by FullCalendar) and the ICS export.

What a person sees
------------------
* Events      - everyone on the crew sees every event.
* Shifts      - a crew member sees *their own* shifts.  Admins can switch to
                everyone's shifts or any one person's.
* Availability (optional) - your own unavailability; admins can overlay the
                whole crew's to spot clashes while rostering.

All stored times are naive wall-clock (venue-local) values, so the feed sends
naive ISO strings and FullCalendar runs with timeZone 'local'.
"""

from datetime import datetime, timedelta
from functools import lru_cache

from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import Event, Shift, ShiftAssignment, User, CrewAssignment
from decorators import crew_required
from services.markdown_service import render_markdown
from services.availability_service import expand_unavailability
from routes.events import (
    ApiError, parse_dt, event_end, fmt_range, is_manager, is_series, DEFAULT_DURATION,
)

calendar_bp = Blueprint('calendar', __name__)

MAX_RANGE = timedelta(days=400)


@lru_cache(maxsize=256)
def _md(text: str) -> str:
    return str(render_markdown(text))


def _iso(dt: datetime, all_day: bool = False) -> str:
    return dt.date().isoformat() if all_day else dt.isoformat(timespec='minutes')


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@calendar_bp.route('/calendar')
@login_required
@crew_required
def calendar():
    crew_users = []
    if is_manager():
        crew_users = User.query.filter(User.user_role.in_(['crew', 'staff'])) \
            .order_by(User.username).all()
    return render_template('/crew/calendar.html', crew_users=crew_users,
                           can_manage=is_manager(), now=datetime.now())


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

@calendar_bp.route('/api/calendar/feed')
@login_required
@crew_required
def feed():
    start = parse_dt(request.args.get('start'), 'start')
    end = parse_dt(request.args.get('end'), 'end')
    if end <= start or (end - start) > MAX_RANGE:
        raise ApiError('Invalid date range')

    manager = is_manager()
    show_events = request.args.get('events', '1') != '0'
    shifts_mode = request.args.get('shifts', 'mine')
    unavail_mode = request.args.get('unavail', 'none')

    out: list[dict] = []
    if show_events:
        out += _event_items(start, end, manager)
    if shifts_mode != 'none':
        out += _shift_items(start, end, shifts_mode, manager)
    if unavail_mode != 'none':
        out += _unavail_items(start, end, unavail_mode, manager)
    return jsonify(out)


def _event_items(start: datetime, end: datetime, manager: bool) -> list[dict]:
    events = Event.query.filter(
        Event.event_date < end,
        or_(Event.event_end_date > start,
            (Event.event_end_date.is_(None)) & (Event.event_date > start - DEFAULT_DURATION)),
    ).order_by(Event.event_date).all()
    mine = {a.event_id for a in CrewAssignment.query.filter_by(crew_member=current_user.username).all()}
    now = datetime.now()

    items = []
    for e in events:
        e_end = event_end(e)
        all_day = bool(e.all_day)
        classes = ['cal-event']
        if e.id in mine:
            classes.append('cal-event-mine')
        if e_end < now:
            classes.append('cal-past')
        items.append({
            'id': f'e-{e.id}',
            'title': e.title,
            'start': _iso(e.event_date, all_day),
            # FullCalendar's all-day end is exclusive
            'end': _iso(e_end + timedelta(days=1), True) if all_day else _iso(e_end),
            'allDay': all_day,
            'classNames': classes,
            'extendedProps': {
                'kind': 'event', 'event_id': e.id, 'location': e.location or '',
                'when': fmt_range(e.event_date, e_end, all_day),
                'description_html': _md(e.description) if e.description else '',
                'on_team': e.id in mine, 'recurring': is_series(e),
                'can_edit': manager or e.created_by == current_user.username,
                'url': f'/events/{e.id}',
            },
        })
    return items


def _shift_items(start, end, mode: str, manager: bool) -> list[dict]:
    q = (db.session.query(ShiftAssignment, Shift, Event, User)
         .join(Shift, ShiftAssignment.shift_id == Shift.id)
         .join(Event, Shift.event_id == Event.id)
         .join(User, ShiftAssignment.user_id == User.id)
         .filter(Shift.shift_date < end, Shift.shift_end_date > start))

    scope = 'mine'
    if manager and mode == 'all':
        scope = 'all'
    elif manager and mode.startswith('user:'):
        try:
            q = q.filter(ShiftAssignment.user_id == int(mode.split(':', 1)[1]))
            scope = 'user'
        except ValueError:
            raise ApiError('Invalid user filter')
    if scope == 'mine':
        q = q.filter(ShiftAssignment.user_id == current_user.id)
    if scope == 'mine' or not manager:
        q = q.filter(ShiftAssignment.status != 'rejected')

    items = []
    for a, shift, event, user in q.order_by(Shift.shift_date).all():
        declined = a.status == 'rejected'
        confirmed = a.status in ('accepted', 'confirmed')
        role = shift.role or 'Shift'
        title = f'{role} · {event.title}' if scope == 'mine' else f'{user.username}: {role}'
        classes = ['cal-shift', 'cal-shift-confirmed' if confirmed else
                   'cal-shift-declined' if declined else 'cal-shift-pending']
        if shift.shift_end_date < datetime.now():
            classes.append('cal-past')
        items.append({
            'id': f's-{a.id}',
            'title': title,
            'start': _iso(shift.shift_date),
            'end': _iso(shift.shift_end_date),
            'allDay': False,
            'classNames': classes,
            'extendedProps': {
                'kind': 'shift', 'assignment_id': a.id, 'event_id': event.id,
                'event_title': event.title, 'username': user.username, 'role': shift.role or '',
                'status': a.status, 'notes': a.notes or '', 'location': shift.location or event.location or '',
                'mine': user.id == current_user.id,
                'when': fmt_range(shift.shift_date, shift.shift_end_date),
                'url': f'/events/{event.id}',
            },
        })
    return items


def _unavail_items(start, end, mode: str, manager: bool) -> list[dict]:
    if manager and mode == 'all':
        ids = [u.id for u in User.query.filter(User.user_role.in_(['crew', 'staff'])).all()]
    else:
        ids = [current_user.id]
    names = {u.id: u.username for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
    items = []
    for w in expand_unavailability(ids, start, end):
        mine = w['user_id'] == current_user.id
        label = w['title'] if mine else f"{names.get(w['user_id'], '?')}: {w['title']}"
        items.append({
            'id': f"x-{w['id']}",
            'title': f'Unavailable – {label}' if mine else f'Unavailable – {label}',
            'start': _iso(w['start'], w['all_day']),
            'end': _iso(w['end'] + timedelta(days=1), True) if w['all_day'] else _iso(w['end']),
            'allDay': w['all_day'],
            'classNames': ['cal-unavail'],
            'editable': False,
            'extendedProps': {'kind': 'unavailability', 'username': names.get(w['user_id'], ''),
                              'mine': mine, 'when': fmt_range(w['start'], w['end'], w['all_day'])},
        })
    return items


# ---------------------------------------------------------------------------
# ICS export (public feed, events only)
# ---------------------------------------------------------------------------

def _esc(text: str | None) -> str:
    """RFC 5545 TEXT escaping - the backslash must be escaped first."""
    return ((text or '').replace('\\', '\\\\').replace(';', '\\;')
            .replace(',', '\\,').replace('\r\n', '\n').replace('\n', '\\n'))


def _fold(line: str) -> str:
    """Fold content lines longer than 75 octets (RFC 5545 section 3.1)."""
    raw, out = line.encode('utf-8'), []
    while len(raw) > 75:
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:      # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode('utf-8'))
        raw = b' ' + raw[cut:]
    out.append(raw.decode('utf-8'))
    return '\r\n'.join(out)


TZ_BLOCK = (
    "BEGIN:VTIMEZONE\r\nTZID:Australia/Sydney\r\n"
    "BEGIN:STANDARD\r\nDTSTART:20240407T030000\r\nTZOFFSETFROM:+1100\r\n"
    "TZOFFSETTO:+1000\r\nTZNAME:AEST\r\nRRULE:FREQ=YEARLY;BYMONTH=4;BYDAY=1SU\r\nEND:STANDARD\r\n"
    "BEGIN:DAYLIGHT\r\nDTSTART:20241006T020000\r\nTZOFFSETFROM:+1000\r\n"
    "TZOFFSETTO:+1100\r\nTZNAME:AEDT\r\nRRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=1SU\r\nEND:DAYLIGHT\r\n"
    "END:VTIMEZONE\r\n"
)


@calendar_bp.route('/calendar/ics')
def calendar_ics():
    stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ShowWise//EN', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', 'X-WR-CALNAME:ShowWise sync', 'X-WR-TIMEZONE:Australia/Sydney',
        'REFRESH-INTERVAL;VALUE=DURATION:PT1H', 'X-PUBLISHED-TTL:PT1H',
    ]
    head = '\r\n'.join(lines) + '\r\n' + TZ_BLOCK
    body = []

    for e in Event.query.order_by(Event.event_date).all():
        e_end = event_end(e)
        body += ['BEGIN:VEVENT', f'UID:event-{e.id}@showwise', f'DTSTAMP:{stamp}']
        if e.all_day:
            body += [f'DTSTART;VALUE=DATE:{e.event_date:%Y%m%d}',
                     f'DTEND;VALUE=DATE:{(e_end + timedelta(days=1)):%Y%m%d}']
        else:
            body += [f'DTSTART;TZID=Australia/Sydney:{e.event_date:%Y%m%dT%H%M%S}',
                     f'DTEND;TZID=Australia/Sydney:{e_end:%Y%m%dT%H%M%S}']
        body.append(f'SUMMARY:{_esc(e.title)}')
        desc = [e.description] if e.description else []
        sched = sorted(e.schedules, key=lambda x: x.scheduled_time)
        if sched:
            desc.append('Schedule:\n' + '\n'.join(
                f"- {s.scheduled_time:%I:%M %p} {s.title}" for s in sched))
        if desc:
            body.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
        if e.location:
            body.append(f'LOCATION:{_esc(e.location)}')
        body += ['STATUS:CONFIRMED', 'END:VEVENT']

    text = head + '\r\n'.join(_fold(l) for l in body) + ('\r\n' if body else '') + 'END:VCALENDAR\r\n'
    return Response(text, mimetype='text/calendar',
                    headers={'Content-Disposition': 'inline; filename="showwise_sync.ics"',
                             'Cache-Control': 'no-cache, must-revalidate'})
