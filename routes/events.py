"""
routes/events.py
================
The events system.

* Events        - create / edit / delete / duplicate, recurring series, Markdown
* Team & shifts - a shift is made *through the event*: add a person, give them
                  start/end times.  One person can have several shifts per event.
* Schedule      - timed running order for the event (Markdown descriptions)
* Notes         - Markdown notes
* Run list      - ordered cue list (drag to reorder)
* PDF export

Permissions
-----------
* Any crew member can create events, add notes, join an event and respond to
  their own shifts.
* The creator of an event (and admins) can edit it.
* Admins manage the team, shifts, schedule and run list, and delete events.
"""

import calendar as _cal
import re
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import (
    Event, CrewAssignment, EventSchedule, EventNote, CrewRunItem, CastRunItem,
    Shift, ShiftAssignment, User, HiredEquipment,
)
from decorators import crew_required
from services.markdown_service import render_markdown
from services.availability_service import find_conflicts
from services.email_service import send_shift_assignment_emails_async
from services.user_names import name_for
from services.notification_service import (
    send_discord_event_announcement, schedule_event_notifications,
)

events_bp = Blueprint('events', __name__)

RECURRENCE_PATTERNS = ('daily', 'weekly', 'biweekly', 'monthly', 'yearly')
MAX_INSTANCES = 400
DEFAULT_DURATION = timedelta(hours=3)
_TZ_SUFFIX = re.compile(r'(?<=\d)([+-]\d{2}:?\d{2})$')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


@events_bp.app_errorhandler(ApiError)
def _handle_api_error(err):
    return jsonify({'error': err.message, **err.extra}), err.status


def is_manager(user=None) -> bool:
    user = user or current_user
    return bool(user.is_authenticated and user.is_admin)


def manager_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_manager():
            raise ApiError('Admin access required', 403)
        return f(*args, **kwargs)
    return wrapper


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('Expected a JSON body')
    return data


def parse_dt(value, field='date') -> datetime:
    """
    Parse a wall-clock datetime: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM[:SS]'.
    Any timezone suffix is ignored on purpose - every time in ShowWise is the
    venue's local wall-clock time.
    """
    if not value or not isinstance(value, str):
        raise ApiError(f'{field} is required')
    v = value.strip().replace('Z', '')
    if 'T' in v:
        v = _TZ_SUFFIX.sub('', v)
    try:
        return datetime.fromisoformat(v).replace(tzinfo=None)
    except ValueError:
        raise ApiError(f'Invalid {field}: {value!r}')


def clean_text(value, field, max_len, required=False) -> str:
    value = '' if value is None else str(value).strip()
    if required and not value:
        raise ApiError(f'{field} is required')
    if len(value) > max_len:
        raise ApiError(f'{field} is too long (max {max_len} characters)')
    return value


def event_end(e: Event) -> datetime:
    return e.event_end_date or (e.event_date + DEFAULT_DURATION)


def _t(dt: datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def _d(dt: datetime) -> str:
    return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}"


def fmt_range(start: datetime, end: datetime | None, all_day: bool = False) -> str:
    if all_day:
        if end and end.date() != start.date():
            return f'{_d(start)} → {_d(end)} (all day)'
        return f'{_d(start)} (all day)'
    if not end:
        return f'{_d(start)}, {_t(start)}'
    if end.date() == start.date():
        return f'{_d(start)}, {_t(start)} – {_t(end)}'
    return f'{_d(start)}, {_t(start)} → {_d(end)}, {_t(end)}'


def series_root_id(e: Event) -> int:
    return e.recurring_event_id or e.id


def is_series(e: Event) -> bool:
    return bool(e.recurrence_pattern or e.recurring_event_id)


def series_members(e: Event, scope: str) -> list[Event]:
    if scope == 'this' or not is_series(e):
        return [e]
    root = series_root_id(e)
    members = Event.query.filter(
        or_(Event.id == root, Event.recurring_event_id == root)
    ).order_by(Event.event_date).all()
    if scope == 'future':
        members = [m for m in members if m.event_date >= e.event_date]
    return members


def can_edit_event(e: Event) -> bool:
    return is_manager() or bool(e.created_by and e.created_by == current_user.username)


def serialize_event(e: Event) -> dict:
    return {
        'id': e.id,
        'title': e.title,
        'description': e.description or '',
        'location': e.location or '',
        'all_day': bool(e.all_day),
        'event_date': e.event_date.isoformat(timespec='minutes'),
        'event_end_date': event_end(e).isoformat(timespec='minutes'),
        'is_recurring': is_series(e),
        'created_by': e.created_by, 'created_by_name': name_for(e.created_by),
    }


# ---- recurrence ----------------------------------------------------------

def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    y, m = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, _cal.monthrange(y, m)[1]))


def occurrence(start: datetime, pattern: str, interval: int, n: int) -> datetime:
    """The n-th occurrence (n=0 is the start), computed from the start so
    month-end clamping never drifts (31 Jan -> 28 Feb -> 31 Mar)."""
    if pattern == 'daily':
        return start + timedelta(days=interval * n)
    if pattern == 'weekly':
        return start + timedelta(weeks=interval * n)
    if pattern == 'biweekly':
        return start + timedelta(weeks=2 * interval * n)
    if pattern == 'monthly':
        return _add_months(start, interval * n)
    if pattern == 'yearly':
        return _add_months(start, 12 * interval * n)
    raise ApiError(f'Unknown recurrence pattern: {pattern}')


def build_series(parent: Event) -> int:
    """Create the follow-on instances for a recurring parent event."""
    pattern = parent.recurrence_pattern
    if not pattern:
        return 0
    interval = max(1, parent.recurrence_interval or 1)
    end_limit = parent.recurrence_end_date
    count = parent.recurrence_count
    if not end_limit and not count:
        end_limit = parent.event_date + timedelta(days=365)
    duration = event_end(parent) - parent.event_date

    created, n = 0, 1
    while n < MAX_INSTANCES:
        if count and n >= count:
            break
        start = occurrence(parent.event_date, pattern, interval, n)
        if end_limit and start.date() > end_limit.date():
            break
        db.session.add(Event(
            title=parent.title, description=parent.description,
            event_date=start, event_end_date=start + duration,
            all_day=parent.all_day, location=parent.location,
            created_by=parent.created_by, cast_description=parent.cast_description,
            is_recurring_instance=True, recurring_event_id=parent.id,
        ))
        created += 1
        n += 1
    return created


def _read_event_fields(data: dict, existing: Event | None = None) -> dict:
    """Validate the fields shared by create and edit."""
    all_day = bool(data.get('all_day', existing.all_day if existing else False))
    out = {
        'title': clean_text(data.get('title', existing.title if existing else ''),
                            'Title', 200, required=True),
        'description': str(data.get('description', existing.description if existing else '') or '').strip(),
        'location': clean_text(data.get('location', existing.location if existing else ''),
                               'Location', 200),
        'all_day': all_day,
    }
    start_raw = data.get('event_date') or (existing.event_date.isoformat() if existing else None)
    start = parse_dt(start_raw, 'Start')
    end_raw = data.get('event_end_date')
    if end_raw:
        end = parse_dt(end_raw, 'End')
    elif existing and 'event_date' not in data:
        end = event_end(existing)
    elif all_day:
        end = start
    else:
        end = start + DEFAULT_DURATION
    if all_day:
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end.replace(hour=23, minute=59, second=0, microsecond=0)
    if end <= start:
        raise ApiError('End must be after the start')
    out['event_date'], out['event_end_date'] = start, end
    return out


def _notify_new_event(event: Event):
    for fn in (send_discord_event_announcement, schedule_event_notifications):
        try:
            fn(event)
        except Exception as exc:            # never fail a save because Discord is down
            print(f'⚠️  Event notification failed ({fn.__name__}): {exc}')


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@events_bp.route('/events')
@login_required
@crew_required
def events_list():
    now = datetime.now()
    ended = Event.query.filter(
        or_(Event.event_end_date < now,
            (Event.event_end_date.is_(None)) & (Event.event_date < now - DEFAULT_DURATION)))
    upcoming = Event.query.filter(~Event.id.in_(ended.with_entities(Event.id))) \
        .order_by(Event.event_date).all()
    past = ended.order_by(Event.event_date.desc()).limit(50).all()
    mine = {a.event_id for a in CrewAssignment.query.filter_by(crew_member=current_user.username).all()}
    return render_template('/crew/events_list.html', upcoming=upcoming, past=past,
                           mine=mine, now=now, can_manage=is_manager(),
                           event_end=event_end, fmt_range=fmt_range)


@events_bp.route('/events/<int:id>', methods=['GET'])
@login_required
@crew_required
def event_detail(id):
    event = Event.query.get_or_404(id)

    # Team: one row per person, each with their shifts for this event.
    shift_rows = (db.session.query(ShiftAssignment, Shift)
                  .join(Shift, ShiftAssignment.shift_id == Shift.id)
                  .filter(Shift.event_id == id)
                  .order_by(Shift.shift_date).all())
    people: dict[int, dict] = {}

    def person(user: User):
        return people.setdefault(user.id, {'user': user, 'crew': None, 'shifts': []})

    for ca in event.crew_assignments:
        user = User.query.filter_by(username=ca.crew_member).first()
        if user:
            person(user)['crew'] = ca
    for assignment, shift in shift_rows:
        if assignment.user:
            person(assignment.user)['shifts'].append({'a': assignment, 's': shift})
    team = sorted(people.values(), key=lambda p: p['user'].shown_name.lower())

    schedules = EventSchedule.query.filter_by(event_id=id).order_by(EventSchedule.scheduled_time).all()
    notes = EventNote.query.filter_by(event_id=id).order_by(EventNote.created_at.desc()).all()
    run_items = CrewRunItem.query.filter_by(event_id=id).order_by(CrewRunItem.order_number).all()
    mine = next((p for p in team if p['user'].id == current_user.id), None)
    manager = is_manager()
    assignable = []
    if manager:
        assignable = (User.query.filter(User.user_role.in_(['crew', 'staff']))
                      .filter(or_(User.is_cast.is_(False), User.is_cast.is_(None)))
                      .order_by(User.username).all())
        assignable.sort(key=lambda u: u.shown_name.lower())

    all_assignments = [x['a'] for p in team for x in p['shifts']]
    page_data = {
        'me': current_user.id,
        'event': {**serialize_event(event), 'series_count': len(series_members(event, 'all'))},
        'users': [{'id': u.id, 'name': u.shown_name} for u in assignable],
        'assignments': {a.id: serialize_assignment(a) for a in all_assignments},
        'schedules': {s.id: {'id': s.id, 'title': s.title, 'time': s.scheduled_time.isoformat(timespec='minutes'),
                             'description': s.description or ''}
                      for s in schedules},
        'runs': {r.id: {'id': r.id, 'title': r.title, 'description': r.description or '',
                        'duration': r.duration or '', 'cue_type': r.cue_type or '', 'notes': r.notes or ''}
                 for r in run_items},
        'notes': {n.id: {'id': n.id, 'content': n.content} for n in notes},
    }

    return render_template(
        '/crew/event_detail.html',
        event=event, now=datetime.now(), team=team,
        my_shifts=mine['shifts'] if mine else [], on_team=mine is not None,
        schedules=schedules, notes=notes, run_items=run_items, page_data=page_data,
        hired=HiredEquipment.query.filter_by(event_id=id).all(),
        assignable=assignable, can_manage=manager, can_edit=can_edit_event(event),
        series_count=len(series_members(event, 'all')),
        is_series=is_series(event), end=event_end(event), fmt_range=fmt_range,
    )


# ---------------------------------------------------------------------------
# Markdown preview (used by every editor)
# ---------------------------------------------------------------------------

@events_bp.route('/api/markdown/preview', methods=['POST'])
@login_required
def markdown_preview():
    data = request.get_json(silent=True) or {}
    return jsonify({'html': str(render_markdown(str(data.get('text', ''))[:20000]))})


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

@events_bp.route('/api/events/<int:id>')
@login_required
@crew_required
def event_json(id):
    """Raw event fields for the edit form (the calendar and list use this)."""
    event = Event.query.get_or_404(id)
    return jsonify({**serialize_event(event), 'can_edit': can_edit_event(event),
                    'can_delete': is_manager(), 'series_count': len(series_members(event, 'all'))})


@events_bp.route('/events/add', methods=['POST'])
@login_required
@crew_required
def add_event():
    data = body()
    fields = _read_event_fields(data)
    rec = data.get('recurrence') or {}
    pattern = rec.get('pattern') or data.get('recurrence_pattern')   # legacy key
    if pattern:
        if not is_manager():
            raise ApiError('Only admins can create recurring events', 403)
        if pattern not in RECURRENCE_PATTERNS:
            raise ApiError('Unknown recurrence pattern')

    event = Event(created_by=current_user.username, **fields)
    if pattern:
        event.recurrence_pattern = pattern
        try:
            event.recurrence_interval = max(1, int(rec.get('interval') or data.get('recurrence_interval') or 1))
            cnt = rec.get('count') or data.get('recurrence_count')
            event.recurrence_count = int(cnt) if cnt else None
        except (TypeError, ValueError):
            raise ApiError('Repeat interval and count must be numbers')
        end_raw = rec.get('end_date') or data.get('recurrence_end_date')
        event.recurrence_end_date = parse_dt(end_raw, 'Repeat until') if end_raw else None
        if event.recurrence_count is not None and not (2 <= event.recurrence_count <= MAX_INSTANCES):
            raise ApiError(f'Repeat count must be between 2 and {MAX_INSTANCES}')

    try:
        db.session.add(event)
        db.session.flush()
        created = build_series(event) if pattern else 0
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not save event: {exc}', 500)

    _notify_new_event(event)
    return jsonify({'success': True, 'id': event.id, 'instances': created + 1})


@events_bp.route('/events/<int:id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event(id):
    event = Event.query.get_or_404(id)
    if not can_edit_event(event):
        raise ApiError('You can only edit events you created', 403)
    data = body()
    scope = data.get('scope', 'this')
    if scope not in ('this', 'future', 'all'):
        raise ApiError('Invalid scope')

    old_start = event.event_date
    fields = _read_event_fields(data, existing=event)
    d_start = fields['event_date'] - old_start
    new_duration = fields['event_end_date'] - fields['event_date']

    try:
        for m in series_members(event, scope):
            m.title = fields['title']
            m.description = fields['description']
            m.location = fields['location']
            m.all_day = fields['all_day']
            if m.id == event.id:
                m.event_date, m.event_end_date = fields['event_date'], fields['event_end_date']
            else:
                m.event_date = m.event_date + d_start
                m.event_end_date = m.event_date + new_duration
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not save event: {exc}', 500)
    return jsonify({'success': True, 'event': serialize_event(event)})


@events_bp.route('/events/<int:id>/move', methods=['PUT'])
@login_required
@crew_required
@manager_required
def move_event(id):
    """Calendar drag/resize: only the times change, only this event."""
    event = Event.query.get_or_404(id)
    data = body()
    all_day = bool(data.get('all_day'))
    start = parse_dt(data.get('event_date'), 'Start')
    end = parse_dt(data['event_end_date'], 'End') if data.get('event_end_date') else None
    if all_day:
        # FullCalendar's all-day end is exclusive (the next midnight).
        start = start.replace(hour=0, minute=0)
        end = (end - timedelta(days=1)) if end and end.date() > start.date() else start
        end = end.replace(hour=23, minute=59)
    elif end is None:
        end = start + (event_end(event) - event.event_date)
    if end <= start:
        raise ApiError('End must be after the start')
    event.event_date, event.event_end_date, event.all_day = start, end, all_day
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:id>', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_event(id):
    event = Event.query.get_or_404(id)
    scope = request.args.get('scope', 'this')
    if scope not in ('this', 'future', 'all'):
        raise ApiError('Invalid scope')
    try:
        members = series_members(event, scope)
        for m in members:
            db.session.delete(m)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not delete: {exc}', 500)
    return jsonify({'success': True, 'deleted': len(members)})


@events_bp.route('/events/<int:id>/duplicate', methods=['POST'])
@login_required
@crew_required
@manager_required
def duplicate_event(id):
    """Copy an event (plus its schedule and run list, not the team)."""
    src = Event.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    new_start = parse_dt(data['event_date'], 'New date') if data.get('event_date') \
        else src.event_date + timedelta(days=7)
    delta = new_start - src.event_date
    copy = Event(
        title=src.title, description=src.description, location=src.location,
        all_day=src.all_day, event_date=new_start, event_end_date=event_end(src) + delta,
        created_by=current_user.username, cast_description=src.cast_description,
    )
    db.session.add(copy)
    db.session.flush()
    for s in EventSchedule.query.filter_by(event_id=src.id).all():
        db.session.add(EventSchedule(event_id=copy.id, title=s.title, description=s.description,
                                     scheduled_time=s.scheduled_time + delta))
    for r in CrewRunItem.query.filter_by(event_id=src.id).all():
        db.session.add(CrewRunItem(event_id=copy.id, order_number=r.order_number, title=r.title,
                                   description=r.description, duration=r.duration,
                                   cue_type=r.cue_type, notes=r.notes))
    db.session.commit()
    return jsonify({'success': True, 'id': copy.id})


# ---------------------------------------------------------------------------
# Team & shifts
# ---------------------------------------------------------------------------

def _shift_window(data: dict, event: Event):
    start = parse_dt(data['start'], 'Shift start') if data.get('start') else event.event_date
    end = parse_dt(data['end'], 'Shift end') if data.get('end') else event_end(event)
    if end <= start:
        raise ApiError('Shift end must be after the start')
    if (end - start) > timedelta(days=7):
        raise ApiError('A shift cannot be longer than 7 days')
    return start, end


def serialize_assignment(a: ShiftAssignment) -> dict:
    s = a.shift
    return {
        'assignment_id': a.id, 'shift_id': s.id, 'user_id': a.user_id,
        'username': a.user.username if a.user else '?',
        'name': a.user.shown_name if a.user else '?', 'role': s.role or '',
        'start': s.shift_date.isoformat(timespec='minutes'),
        'end': s.shift_end_date.isoformat(timespec='minutes'),
        'status': a.status, 'notes': a.notes or '',
    }


def _drop_shift_if_orphaned(shift: Shift):
    db.session.flush()
    db.session.refresh(shift)
    if not shift.assignments and not shift.is_open:
        db.session.delete(shift)


def _split_shared_shift(a: ShiftAssignment, start, end, role) -> Shift:
    """Legacy shifts could hold several people.  Give this person their own
    copy so editing their times never alters anyone else's."""
    old = a.shift
    clone = Shift(event_id=old.event_id, title=role or old.title, description=old.description,
                  location=old.location, positions_needed=1, is_open=False,
                  created_by=current_user.username, shift_date=start,
                  shift_end_date=end, role=role)
    db.session.add(clone)
    db.session.flush()
    a.shift_id = clone.id
    return clone


def _shift_email_job(user: User, event: Event, shift: Shift, notes: str = '') -> dict:
    """Plain-string arguments for send_shift_assignment_email (it runs after the request ends)."""
    return dict(
        recipient_email=user.email, username=user.shown_name,
        event_title=event.title, shift_title=shift.title,
        shift_date=shift.shift_date.strftime('%a %d %b %Y, %I:%M %p'),
        shift_end_time=shift.shift_end_date.strftime('%I:%M %p'),
        role=shift.role or 'Crew', location=shift.location or event.location or 'TBD',
        positions_needed=1, description=notes,
        shifts_url=request.url_root.rstrip('/') + '/crew/my-schedule',
    )


@events_bp.route('/events/<int:event_id>/team/add', methods=['POST'])
@login_required
@crew_required
@manager_required
def add_team_shift(event_id):
    """Add a person to the event with a shift (call again for more shifts)."""
    event = Event.query.get_or_404(event_id)
    data = body()
    if data.get('user_id'):
        user = db.session.get(User, data['user_id'])
    else:
        user = User.query.filter_by(username=str(data.get('username', ''))).first()
    if not user:
        raise ApiError('Choose a person to add')
    if user.is_cast and not user.is_admin:
        raise ApiError('Cast members are managed from the Cast page')

    start, end = _shift_window(data, event)
    role = clean_text(data.get('role'), 'Role', 100)
    notes = str(data.get('notes') or '').strip()
    status = data.get('status') or 'pending'
    if status not in ('pending', 'accepted', 'confirmed'):
        raise ApiError('Invalid status')

    conflicts = find_conflicts(user.id, start, end)
    if conflicts and not data.get('force'):
        raise ApiError(f'{user.shown_name} has a clash', 409, conflicts=conflicts)

    try:
        ca = CrewAssignment.query.filter_by(event_id=event.id, crew_member=user.username).first()
        if not ca:
            db.session.add(CrewAssignment(event_id=event.id, crew_member=user.username,
                                          role=role or 'Crew Member', assigned_via='webapp'))
        elif role:
            ca.role = role
        shift = Shift(event_id=event.id, title=role or 'Crew', role=role,
                      shift_date=start, shift_end_date=end, location=event.location,
                      positions_needed=1, is_open=False, created_by=current_user.username)
        db.session.add(shift)
        db.session.flush()
        assignment = ShiftAssignment(shift_id=shift.id, user_id=user.id, status=status,
                                     assigned_by=current_user.username, notes=notes)
        db.session.add(assignment)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not add shift: {exc}', 500)

    if user.email and user.id != current_user.id:          # no email for assigning yourself
        send_shift_assignment_emails_async([_shift_email_job(user, event, shift, notes)])
    return jsonify({'success': True, 'shift': serialize_assignment(assignment),
                    'warnings': conflicts})


@events_bp.route('/events/<int:event_id>/team/add-all', methods=['POST'])
@login_required
@crew_required
@manager_required
def add_all_crew(event_id):
    """Add every crew member who isn't on the event yet, using the event's times."""
    event = Event.query.get_or_404(event_id)
    on_team = {c.crew_member for c in event.crew_assignments}
    added = 0
    emails = []
    users = (User.query.filter(User.user_role.in_(['crew', 'staff']))
             .filter(or_(User.is_cast.is_(False), User.is_cast.is_(None))).all())
    for user in users:
        if user.username in on_team:
            continue
        db.session.add(CrewAssignment(event_id=event.id, crew_member=user.username,
                                      role='Crew Member', assigned_via='webapp'))
        shift = Shift(event_id=event.id, title='Crew Member', role='Crew Member',
                      shift_date=event.event_date, shift_end_date=event_end(event),
                      location=event.location, positions_needed=1, is_open=False,
                      created_by=current_user.username)
        db.session.add(shift)
        db.session.flush()
        db.session.add(ShiftAssignment(shift_id=shift.id, user_id=user.id, status='pending',
                                       assigned_by=current_user.username))
        added += 1
        if user.email and user.id != current_user.id:
            emails.append(_shift_email_job(user, event, shift))
    db.session.commit()
    send_shift_assignment_emails_async(emails)
    return jsonify({'success': True, 'added': added})


@events_bp.route('/events/shift-assignments/<int:aid>', methods=['PUT'])
@login_required
@crew_required
@manager_required
def edit_team_shift(aid):
    a = ShiftAssignment.query.get_or_404(aid)
    shift, event = a.shift, a.shift.event
    data = body()
    start, end = _shift_window(
        {'start': data.get('start') or shift.shift_date.isoformat(),
         'end': data.get('end') or shift.shift_end_date.isoformat()}, event)
    role = clean_text(data.get('role', shift.role), 'Role', 100)
    status = data.get('status', a.status)
    if status not in ('pending', 'accepted', 'confirmed', 'rejected'):
        raise ApiError('Invalid status')

    conflicts = [] if status == 'rejected' else \
        find_conflicts(a.user_id, start, end, exclude_assignment_id=a.id)
    if conflicts and not data.get('force'):
        raise ApiError(f'{a.user.shown_name} has a clash', 409, conflicts=conflicts)

    try:
        if len(shift.assignments) > 1:
            shift = _split_shared_shift(a, start, end, role)
        else:
            shift.shift_date, shift.shift_end_date, shift.role = start, end, role
            shift.title = role or shift.title or 'Crew'
        if status != a.status:
            a.status = status
            a.responded_at = datetime.utcnow()
            if status != 'rejected':
                a.decline_reason = None
        if 'notes' in data:
            a.notes = str(data.get('notes') or '').strip()
        ca = CrewAssignment.query.filter_by(event_id=event.id, crew_member=a.user.username).first()
        if ca and role:
            ca.role = role
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not save shift: {exc}', 500)
    return jsonify({'success': True, 'shift': serialize_assignment(a), 'warnings': conflicts})


@events_bp.route('/events/shift-assignments/<int:aid>/move', methods=['PUT'])
@login_required
@crew_required
@manager_required
def move_team_shift(aid):
    """Calendar drag/resize of a shift."""
    a = ShiftAssignment.query.get_or_404(aid)
    data = body()
    start = parse_dt(data.get('start'), 'Start')
    end = parse_dt(data.get('end'), 'End')
    if end <= start:
        raise ApiError('End must be after the start')
    conflicts = find_conflicts(a.user_id, start, end, exclude_assignment_id=a.id)
    if conflicts and not data.get('force'):
        raise ApiError(f'{a.user.shown_name} has a clash', 409, conflicts=conflicts)
    if len(a.shift.assignments) > 1:
        _split_shared_shift(a, start, end, a.shift.role)
    else:
        a.shift.shift_date, a.shift.shift_end_date = start, end
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/shift-assignments/<int:aid>', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_team_shift(aid):
    a = ShiftAssignment.query.get_or_404(aid)
    shift = a.shift
    try:
        db.session.delete(a)
        _drop_shift_if_orphaned(shift)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not delete shift: {exc}', 500)
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/team/<int:user_id>', methods=['DELETE'])
@login_required
@crew_required
def remove_team_member(event_id, user_id):
    """Remove a person and all their shifts from the event.  Admins can remove
    anyone; crew can remove themselves."""
    if not is_manager() and user_id != current_user.id:
        raise ApiError('Permission denied', 403)
    event = Event.query.get_or_404(event_id)
    user = User.query.get_or_404(user_id)
    try:
        rows = (ShiftAssignment.query.join(Shift)
                .filter(Shift.event_id == event.id, ShiftAssignment.user_id == user.id).all())
        for a in rows:
            shift = a.shift
            db.session.delete(a)
            _drop_shift_if_orphaned(shift)
        CrewAssignment.query.filter_by(event_id=event.id, crew_member=user.username).delete()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not remove: {exc}', 500)
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/join', methods=['POST'])
@login_required
@crew_required
def join_event(event_id):
    event = Event.query.get_or_404(event_id)
    if CrewAssignment.query.filter_by(event_id=event.id, crew_member=current_user.username).first():
        raise ApiError('You are already on this event')
    db.session.add(CrewAssignment(event_id=event.id, crew_member=current_user.username,
                                  role='Crew Member', assigned_via='self'))
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Schedule (timed running order)
# ---------------------------------------------------------------------------

def _schedule_payload(data: dict) -> dict:
    return {
        'title': clean_text(data.get('title'), 'Title', 100, required=True),
        'scheduled_time': parse_dt(data.get('scheduled_time'), 'Time'),
        'description': str(data.get('description') or '').strip(),
    }


@events_bp.route('/events/<int:event_id>/schedule/add', methods=['POST'])
@login_required
@crew_required
@manager_required
def add_event_schedule(event_id):
    Event.query.get_or_404(event_id)
    item = EventSchedule(event_id=event_id, **_schedule_payload(body()))
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id})


@events_bp.route('/events/schedule/<int:schedule_id>/edit', methods=['PUT'])
@login_required
@crew_required
@manager_required
def edit_event_schedule(schedule_id):
    item = EventSchedule.query.get_or_404(schedule_id)
    for k, v in _schedule_payload(body()).items():
        setattr(item, k, v)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_event_schedule(schedule_id):
    db.session.delete(EventSchedule.query.get_or_404(schedule_id))
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Notes (Markdown)
# ---------------------------------------------------------------------------

def _note_json(n: EventNote) -> dict:
    return {'id': n.id, 'content': n.content, 'html': str(render_markdown(n.content)),
            'created_by': n.created_by, 'created_by_name': name_for(n.created_by),
            'created_at': n.created_at.strftime('%d %b %Y, %I:%M %p')}


def _note_for_edit(note_id: int) -> EventNote:
    note = EventNote.query.get_or_404(note_id)
    if note.created_by != current_user.username and not is_manager():
        raise ApiError('You can only change your own notes', 403)
    return note


@events_bp.route('/events/<int:event_id>/notes/add', methods=['POST'])
@login_required
@crew_required
def add_event_note(event_id):
    Event.query.get_or_404(event_id)
    content = clean_text(body().get('content'), 'Note', 20000, required=True)
    note = EventNote(event_id=event_id, content=content, created_by=current_user.username)
    db.session.add(note)
    db.session.commit()
    return jsonify({'success': True, 'id': note.id, 'note': _note_json(note)})


@events_bp.route('/events/notes/<int:note_id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event_note(note_id):
    note = _note_for_edit(note_id)
    note.content = clean_text(body().get('content'), 'Note', 20000, required=True)
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'note': _note_json(note)})


@events_bp.route('/events/notes/<int:note_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_event_note(note_id):
    db.session.delete(_note_for_edit(note_id))
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Crew run list
# ---------------------------------------------------------------------------

def _run_payload(data: dict) -> dict:
    return {
        'title': clean_text(data.get('title'), 'Title', 200, required=True),
        'description': str(data.get('description') or '').strip(),
        'duration': clean_text(data.get('duration'), 'Duration', 50),
        'cue_type': clean_text(data.get('cue_type'), 'Cue type', 50),
        'notes': str(data.get('notes') or '').strip(),
    }


def _renumber(model, event_id: int):
    for i, item in enumerate(model.query.filter_by(event_id=event_id)
                             .order_by(model.order_number, model.id).all(), start=1):
        item.order_number = i


@events_bp.route('/events/<int:event_id>/crew-run/add', methods=['POST'])
@login_required
@crew_required
@manager_required
def add_crew_run_item(event_id):
    Event.query.get_or_404(event_id)
    max_order = db.session.query(db.func.max(CrewRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    item = CrewRunItem(event_id=event_id, order_number=max_order + 1, **_run_payload(body()))
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id, 'order_number': item.order_number})


@events_bp.route('/events/crew-run/<int:item_id>/edit', methods=['PUT'])
@login_required
@crew_required
@manager_required
def edit_crew_run_item(item_id):
    item = CrewRunItem.query.get_or_404(item_id)
    for k, v in _run_payload(body()).items():
        setattr(item, k, v)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/crew-run/<int:item_id>/delete', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_crew_run_item(item_id):
    item = CrewRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    db.session.delete(item)
    db.session.flush()
    _renumber(CrewRunItem, event_id)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/crew-run/reorder', methods=['POST'])
@login_required
@crew_required
@manager_required
def reorder_crew_run_items(event_id):
    ids = body().get('item_ids', [])
    items = {i.id: i for i in CrewRunItem.query.filter_by(event_id=event_id).all()}
    n = 0
    for item_id in ids:
        if item_id in items:
            n += 1
            items[item_id].order_number = n
    for item in sorted(items.values(), key=lambda i: i.order_number):
        if item.id not in ids:
            n += 1
            item.order_number = n
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Cast run list (used by the cast pages; behaviour unchanged)
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/cast-run/add', methods=['POST'])
@login_required
def add_cast_run_item(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    Event.query.get_or_404(event_id)
    data = request.json
    max_order = db.session.query(db.func.max(CastRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    item = CastRunItem(
        event_id=event_id, order_number=max_order + 1,
        title=data['title'], description=data.get('description', ''),
        duration=data.get('duration', ''), item_type=data.get('item_type', ''),
        cast_involved=data.get('cast_involved', ''), notes=data.get('notes', ''),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id, 'order_number': item.order_number})


@events_bp.route('/events/cast-run/<int:item_id>/edit', methods=['PUT'])
@login_required
def edit_cast_run_item(item_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = CastRunItem.query.get_or_404(item_id)
    data = request.json
    for f in ('title', 'description', 'duration', 'item_type', 'cast_involved', 'notes'):
        setattr(item, f, data.get(f, getattr(item, f)))
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/cast-run/<int:item_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_run_item(item_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = CastRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    db.session.delete(item)
    db.session.flush()
    _renumber(CastRunItem, event_id)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/cast-run/reorder', methods=['POST'])
@login_required
def reorder_cast_run_items(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    for idx, item_id in enumerate(request.json.get('item_ids', []), start=1):
        item = db.session.get(CastRunItem, item_id)
        if item and item.event_id == event_id:
            item.order_number = idx
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Legacy URL (kept so older clients keep working)
# ---------------------------------------------------------------------------

@events_bp.route('/events/create-recurring', methods=['POST'])
@login_required
@crew_required
@manager_required
def create_recurring_event():
    return add_event()


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/export-pdf')
@login_required
@crew_required
def export_event_pdf(event_id):
    from services.report_service import generate_event_pdf
    try:
        pdf_buffer, filename = generate_event_pdf(event_id)
        return send_file(pdf_buffer, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(exc)}), 500
