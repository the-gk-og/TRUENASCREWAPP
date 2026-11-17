"""
routes/calendar.py
==================
Calendar page, its JSON feed (consumed by FullCalendar) and the private ICS sync feed.

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

import secrets
from datetime import datetime, timedelta
from functools import lru_cache

from flask import Blueprint, render_template, request, jsonify, Response, abort, redirect, url_for, make_response
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import Event, EventTime, Shift, ShiftAssignment, User, CrewAssignment
from decorators import crew_required
from services.markdown_service import render_markdown
from services.availability_service import expand_unavailability
from services.event_times import times_for, time_title
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

def _is_phone(ua_string: str) -> bool:
    """Phones get the mobile calendar; tablets are big enough for the full one."""
    ua = (ua_string or '').lower()
    if 'ipad' in ua or 'tablet' in ua:
        return False
    if 'android' in ua and 'mobile' not in ua:      # Android tablets omit the "Mobile" token
        return False
    return any(t in ua for t in ('android', 'iphone', 'ipod', 'mobile', 'windows phone'))


def _calendar_view() -> str:
    """'mobile' or 'desktop'. ?view= wins (and is remembered in a cookie), then the cookie, then the device."""
    for choice in (request.args.get('view'), request.cookies.get('cal_view')):
        if choice in ('mobile', 'desktop'):
            return choice
    return 'mobile' if _is_phone(request.user_agent.string) else 'desktop'


@calendar_bp.route('/calendar')
@login_required
@crew_required
def calendar():
    crew_users = []
    if is_manager():
        crew_users = User.query.filter(User.user_role.in_(['crew', 'staff'])) \
            .order_by(User.username).all()
        crew_users.sort(key=lambda u: u.shown_name.lower())

    view = _calendar_view()
    template = '/crew/calendar_mobile.html' if view == 'mobile' else '/crew/calendar.html'
    resp = make_response(render_template(template, crew_users=crew_users,
                                         can_manage=is_manager(), now=datetime.now()))
    if request.args.get('view') in ('mobile', 'desktop'):
        resp.set_cookie('cal_view', view, max_age=60 * 60 * 24 * 365, samesite='Lax', httponly=True)
    # the response depends on the User-Agent, so caches must not mix the two versions up
    resp.headers['Vary'] = 'User-Agent, Cookie'
    return resp


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
    in_window = db.session.query(EventTime.event_id).filter(
        EventTime.start_time < end, EventTime.end_time > start)
    events = Event.query.filter(or_(
        (Event.event_date < end) & or_(
            Event.event_end_date > start,
            (Event.event_end_date.is_(None)) & (Event.event_date > start - DEFAULT_DURATION)),
        Event.id.in_(in_window),
    )).order_by(Event.event_date).all()
    mine = {a.event_id for a in CrewAssignment.query.filter_by(crew_member=current_user.username).all()}
    now = datetime.now()

    items = []
    for e in events:
        if e.times:
            # One calendar entry per labeled time: "{event} - {label}"
            for t in times_for(e):
                if not (t.start_time < end and t.end_time > start):
                    continue
                classes = ['cal-event']
                if e.id in mine:
                    classes.append('cal-event-mine')
                if t.end_time < now:
                    classes.append('cal-past')
                items.append({
                    'id': f'e-{e.id}-t{t.id}',
                    'title': time_title(e, t),
                    'start': _iso(t.start_time, False),
                    'end': _iso(t.end_time),
                    'allDay': False,
                    'classNames': classes,
                    'extendedProps': {
                        'kind': 'event', 'event_id': e.id, 'time_id': t.id, 'label': t.label,
                        'location': e.location or '',
                        'when': fmt_range(t.start_time, t.end_time),
                        'description_html': _md(e.description) if e.description else '',
                        'on_team': e.id in mine, 'recurring': is_series(e),
                        'can_edit': manager or e.created_by == current_user.username,
                        'url': f'/events/{e.id}',
                    },
                })
        e_end = event_end(e)
        if not (e.event_date < end and e_end > start):
            continue                          # only a labeled time is in this window
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
        title = f'{role} · {event.title}' if scope == 'mine' else f'{user.shown_name}: {role}'
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
                'event_title': event.title, 'username': user.username, 'name': user.shown_name, 'role': shift.role or '',
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
    names = {u.id: u.shown_name for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
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
# ICS subscriptions - one private, unguessable, revocable slug per person.
#   /calendar/ics/<token>      "My schedule": my shifts + events I crew or am cast in
#   /calendar/ics/<token>/all  every event (crew only)
# ---------------------------------------------------------------------------

import hashlib
import os
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from models import CastMember
from services.security import throttle


def _esc(text: str | None) -> str:
    """RFC 5545 TEXT escaping - the backslash must be escaped first."""
    return ((text or '').replace('\\', '\\\\').replace(';', '\;')
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


# A 32-byte token is a 43-character URL-safe slug (256 bits) - not guessable.
TOKEN_BYTES = 32
# Throttles (per process): wrong slugs per IP, and fetches per valid slug.
BAD_TOKEN_LIMIT, BAD_TOKEN_WINDOW = 20, 900
FEED_HIT_LIMIT, FEED_HIT_WINDOW = 120, 3600


def feed_tz() -> ZoneInfo:
    """The venue timezone every stored (naive, wall-clock) time is in."""
    name = (current_app.config.get('CALENDAR_TIMEZONE') or os.environ.get('SHOWWISE_TIMEZONE')
            or 'Australia/Sydney')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('Australia/Sydney')


def is_cast_only(user: User) -> bool:
    return bool(user.is_cast and not user.is_admin)


def ensure_calendar_token(user: User, rotate: bool = False) -> str:
    """Return the user's calendar slug, creating it on first use (or replacing it when rotate=True)."""
    if rotate or not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(TOKEN_BYTES)
        db.session.commit()
    return user.calendar_token


def _webcal(https: str) -> str:
    return 'webcal://' + https.split('://', 1)[1]


def _sync_urls(user: User) -> dict:
    token = ensure_calendar_token(user)
    https = url_for('calendar.calendar_ics_private', token=token, _external=True)
    out = {'url': https, 'webcal_url': _webcal(https)}
    if not is_cast_only(user):
        all_url = url_for('calendar.calendar_ics_all', token=token, _external=True)
        out.update(all_url=all_url, all_webcal_url=_webcal(all_url))
    return out


@calendar_bp.route('/api/calendar/sync-link')
@login_required
def sync_link():
    """The signed-in person's own private subscription URLs."""
    return jsonify(_sync_urls(current_user))


@calendar_bp.route('/api/calendar/sync-link/reset', methods=['POST'])
@login_required
def sync_link_reset():
    """Replace the slug - every old URL stops working immediately."""
    ensure_calendar_token(current_user, rotate=True)
    return jsonify(_sync_urls(current_user))


@calendar_bp.route('/calendar/ics')
@login_required
def calendar_ics():
    """The old open feed is gone: signed-in people are sent to their own private feed instead."""
    return redirect(url_for('calendar.calendar_ics_private', token=ensure_calendar_token(current_user)))


def _user_for_token(token: str) -> User:
    """Look up a slug; unknown slugs reveal nothing and are throttled per IP."""
    ip = throttle.client_ip()
    if throttle.is_blocked('ics_bad', ip, BAD_TOKEN_LIMIT, BAD_TOKEN_WINDOW):
        abort(429)
    user = User.query.filter_by(calendar_token=token).first() if 20 <= len(token) <= 64 else None
    if not user or not secrets.compare_digest(user.calendar_token or '', token):
        throttle.record_failure('ics_bad', ip, BAD_TOKEN_WINDOW)
        abort(404)
    if throttle.is_blocked('ics_hit', token, FEED_HIT_LIMIT, FEED_HIT_WINDOW):
        abort(429)                     # a misbehaving client polling far too often
    throttle.record_failure('ics_hit', token, FEED_HIT_WINDOW)
    return user


def _ics_response(body: str, filename: str):
    resp = Response(body, mimetype='text/calendar', headers={
        'Content-Disposition': f'inline; filename="{filename}"',
        'Cache-Control': 'private, no-cache, must-revalidate',
        'X-Robots-Tag': 'noindex, nofollow',
        'Referrer-Policy': 'no-referrer',
    })
    resp.set_etag(hashlib.sha256(body.encode('utf-8')).hexdigest()[:32])
    return resp.make_conditional(request)          # 304 when nothing changed since the last refresh


@calendar_bp.route('/calendar/ics/<token>')
def calendar_ics_private(token):
    """"My schedule" subscription. No login (calendar apps can't), so the slug *is* the credential."""
    user = _user_for_token(token)
    return _ics_response(_build_ics(user, request.url_root.rstrip('/'), everything=False),
                         'showwise_my_schedule.ics')


@calendar_bp.route('/calendar/ics/<token>/all')
def calendar_ics_all(token):
    """Every event (crew only - cast accounts never see the full crew calendar)."""
    user = _user_for_token(token)
    if is_cast_only(user):
        abort(404)
    return _ics_response(_build_ics(user, request.url_root.rstrip('/'), everything=True),
                         'showwise_all_events.ics')


def _utc(dt: datetime, tz: ZoneInfo) -> str:
    return dt.replace(tzinfo=tz).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _dt_lines(start: datetime, end: datetime, tz: ZoneInfo, all_day: bool = False) -> list[str]:
    if all_day:
        return [f'DTSTART;VALUE=DATE:{start:%Y%m%d}', f'DTEND;VALUE=DATE:{(end + timedelta(days=1)):%Y%m%d}']
    return [f'DTSTART:{_utc(start, tz)}', f'DTEND:{_utc(end, tz)}']


def _stamp(dt: datetime | None) -> str:
    # Stable per item (not "now"), so an unchanged feed hashes to the same ETag.
    return (dt or datetime(2024, 1, 1)).strftime('%Y%m%dT%H%M%SZ')


def _my_event_ids(user: User) -> tuple[set, set]:
    """(events I'm crewing, events I'm cast in)."""
    crew = {a.event_id for a in CrewAssignment.query.filter_by(crew_member=user.username).all()}
    crew |= {eid for (eid,) in db.session.query(Shift.event_id)
             .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
             .filter(ShiftAssignment.user_id == user.id, ShiftAssignment.status != 'rejected').all()}
    cast = {eid for (eid,) in db.session.query(CastMember.event_id)
            .filter(CastMember.user_id == user.id, CastMember.event_id.isnot(None)).all()}
    return crew, cast


def _build_ics(user: User, site_url: str, everything: bool) -> str:
    tz = feed_tz()
    name = 'ShowWise - All events' if everything else 'ShowWise - ' + user.shown_name
    head = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ShowWise//EN', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', f'X-WR-CALNAME:{_esc(name)}', f'X-WR-TIMEZONE:{tz.key}',
        'REFRESH-INTERVAL;VALUE=DURATION:PT1H', 'X-PUBLISHED-TTL:PT1H',
    ]
    body = []

    crew_ids, cast_ids = (set(), set()) if everything else _my_event_ids(user)
    cast_view = is_cast_only(user)
    q = Event.query
    if not everything:
        q = q.filter(Event.id.in_(crew_ids | cast_ids)) if (crew_ids | cast_ids) else q.filter(False)
    for e in q.order_by(Event.event_date).all():
        # Cast-only people see the cast-facing text, never crew notes/schedules.
        as_cast = cast_view or (e.id in cast_ids and e.id not in crew_ids)
        text = (e.cast_description if as_cast else e.description) or ''
        sched = sorted(e.cast_schedules if as_cast else e.schedules, key=lambda x: x.scheduled_time)
        desc = [text] if text else []
        if sched:
            desc.append('Schedule:\n' + '\n'.join(f"- {s.scheduled_time:%I:%M %p} {s.title}" for s in sched))
        url = f'{site_url}/cast-events/{e.id}' if as_cast else f'{site_url}/events/{e.id}'
        desc.append(f'Open in ShowWise: {url}')
        items = [(f'event-{e.id}@showwise', e.title, e.event_date, event_end(e), bool(e.all_day))]
        items += [(f'event-{e.id}-t{t.id}@showwise', time_title(e, t), t.start_time, t.end_time, False)
                  for t in times_for(e)]
        for uid, title, t_start, t_end, t_all_day in items:
            body += ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{_stamp(e.created_at)}']
            body += _dt_lines(t_start, t_end, tz, t_all_day)
            body.append(f'SUMMARY:{_esc(title)}')
            body.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
            if e.location:
                body.append(f'LOCATION:{_esc(e.location)}')
            body += [f'URL:{url}', 'STATUS:CONFIRMED', 'END:VEVENT']

    if not everything:
        rows = (db.session.query(ShiftAssignment, Shift, Event)
                .join(Shift, ShiftAssignment.shift_id == Shift.id)
                .join(Event, Shift.event_id == Event.id)
                .filter(ShiftAssignment.user_id == user.id, ShiftAssignment.status != 'rejected')
                .order_by(Shift.shift_date).all())
        for a, shift, e in rows:
            confirmed = a.status in ('accepted', 'confirmed')
            role = shift.role or 'Crew'
            body += ['BEGIN:VEVENT', f'UID:shift-{a.id}@showwise', f'DTSTAMP:{_stamp(a.assigned_at)}']
            body += _dt_lines(shift.shift_date, shift.shift_end_date, tz)
            body.append(f'SUMMARY:{_esc(f"{role} shift · {e.title}")}')
            desc = [f'Your shift ({"confirmed" if confirmed else "awaiting your response"})', f'Event: {e.title}']
            if a.notes:
                desc.append(f'Notes: {a.notes}')
            desc.append(f'Open in ShowWise: {site_url}/events/{e.id}')
            body.append(f"DESCRIPTION:{_esc(chr(10).join(desc))}")
            place = shift.location or e.location
            if place:
                body.append(f'LOCATION:{_esc(place)}')
            body += [f'URL:{site_url}/events/{e.id}',
                     f'STATUS:{"CONFIRMED" if confirmed else "TENTATIVE"}', 'END:VEVENT']

    return '\r\n'.join(_fold(l) for l in head + body + ['END:VCALENDAR']) + '\r\n'
