"""
routes/roster.py
================
Admin shift scheduler ("Roster").

A grid with every person down the left and a column per day.  Each box holds
that person's shifts for the day.  Admins can create, edit, assign, drag and
delete shifts without leaving the page.

It is a different *view* of the same data the events system uses:

* a roster shift is a normal ``Shift`` + ``ShiftAssignment`` that belongs to an
  ``Event``, so it shows up on the event page, My Schedule and the calendar
* clash / unavailability checks use ``find_conflicts`` (409 + ``force`` to override)
* people get the same "you've been assigned a shift" email, and declines still
  notify the people chosen in Admin Console -> Notifications
* a shift with nobody on it is an *open shift*; it sits in the "Unassigned" row
  until it is dragged (or assigned) to someone
"""

from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import Event, CrewAssignment, Shift, ShiftAssignment, User
from decorators import crew_required
from services.availability_service import find_conflicts, expand_unavailability
from services.email_service import send_shift_assignment_emails_async
from routes.events import (
    ApiError, manager_required, body, parse_dt, clean_text, event_end,
    _shift_email_job, _split_shared_shift,
)

roster_bp = Blueprint('roster', __name__)

STATUSES = ('pending', 'accepted', 'confirmed', 'rejected')
MAX_DAYS = 14
MAX_SHIFT = timedelta(days=7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monday(d):
    return d - timedelta(days=d.weekday())


def _parse_day(value, default):
    try:
        return datetime.strptime((value or '')[:10], '%Y-%m-%d')
    except ValueError:
        return default


def _roster_users():
    """Everyone who can be rostered: crew/staff/admins, no cast-only or suspended users."""
    q = User.query.filter(or_(User.is_cast.is_(False), User.is_cast.is_(None), User.is_admin.is_(True)))
    return [u for u in q.all() if (u.user_role or 'crew') != 'suspended']


def _window(data, event=None):
    start = parse_dt(data.get('start'), 'Shift start')
    end = parse_dt(data.get('end'), 'Shift end')
    if end <= start:
        raise ApiError('Shift end must be after the start')
    if end - start > MAX_SHIFT:
        raise ApiError('A shift cannot be longer than 7 days')
    return start, end


def _found(model, pk):
    row = db.session.get(model, pk)
    if row is None:
        raise ApiError('Shift not found', 404)
    return row


def _get_event(event_id):
    event = db.session.get(Event, event_id) if event_id else None
    if not event:
        raise ApiError('Choose an event for this shift')
    return event


def _get_user(user_id):
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        raise ApiError('Choose a person')
    if user.is_cast and not user.is_admin:
        raise ApiError('Cast members are managed from the Cast page')
    return user


def _status(data, default='pending'):
    status = data.get('status') or default
    if status not in STATUSES:
        raise ApiError('Invalid status')
    return status


def _ensure_crew_row(event, user, role):
    ca = CrewAssignment.query.filter_by(event_id=event.id, crew_member=user.username).first()
    if not ca:
        db.session.add(CrewAssignment(event_id=event.id, crew_member=user.username,
                                      role=role or 'Crew Member', assigned_via='webapp'))
    elif role:
        ca.role = role


def _tidy_crew_row(event_id, user):
    """Remove the person from the event's crew list once they have no shifts left on it."""
    left = (ShiftAssignment.query.join(Shift)
            .filter(Shift.event_id == event_id, ShiftAssignment.user_id == user.id).count())
    if not left:
        CrewAssignment.query.filter_by(event_id=event_id, crew_member=user.username).delete()


def _check_clash(user_id, start, end, data, exclude_assignment_id=None):
    conflicts = find_conflicts(user_id, start, end, exclude_assignment_id=exclude_assignment_id)
    if conflicts and not data.get('force'):
        who = db.session.get(User, user_id)
        raise ApiError(f'{who.shown_name} has a clash', 409, conflicts=conflicts)
    return conflicts


def _drop_if_empty(shift):
    db.session.flush()
    db.session.refresh(shift)
    if not shift.assignments and not shift.is_open:
        db.session.delete(shift)


def _item(shift, assignment=None):
    """One box entry."""
    ev = shift.event
    return {
        'key': f'a:{assignment.id}' if assignment else f's:{shift.id}',
        'assignment_id': assignment.id if assignment else None,
        'shift_id': shift.id,
        'user_id': assignment.user_id if assignment else None,
        'event_id': shift.event_id,
        'event': ev.title if ev else '',
        'role': shift.role or '',
        'start': shift.shift_date.isoformat(timespec='minutes'),
        'end': shift.shift_end_date.isoformat(timespec='minutes'),
        'status': assignment.status if assignment else 'open',
        'notes': (assignment.notes if assignment else '') or '',
        'location': shift.location or (ev.location if ev else '') or '',
    }


def _email_new_assignment(user, event, shift, notes=''):
    if user.email and user.id != current_user.id:
        send_shift_assignment_emails_async([_shift_email_job(user, event, shift, notes)])


# ---------------------------------------------------------------------------
# Page + data
# ---------------------------------------------------------------------------

@roster_bp.route('/roster')
@login_required
@crew_required
@manager_required
def roster_page():
    return render_template('admin/roster.html')


@roster_bp.route('/api/roster')
@login_required
@crew_required
@manager_required
def roster_data():
    today = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    start = _monday(_parse_day(request.args.get('start'), today))
    days = min(max(request.args.get('days', 7, type=int), 1), MAX_DAYS)
    end = start + timedelta(days=days)

    shifts = (Shift.query.filter(Shift.shift_date < end, Shift.shift_end_date > start)
              .order_by(Shift.shift_date).all())
    items, open_items, have_shifts = [], [], set()
    for s in shifts:
        if not s.assignments:
            open_items.append(_item(s))
        for a in s.assignments:
            items.append(_item(s, a))
            have_shifts.add(a.user_id)

    users = _roster_users()
    known = {u.id for u in users}
    users += [u for u in User.query.filter(User.id.in_(have_shifts - known)).all()] if have_shifts - known else []
    users.sort(key=lambda u: u.shown_name.lower())

    unavailable = [
        {'user_id': w['user_id'], 'title': w['title'],
         'start': w['start'].isoformat(timespec='minutes'), 'end': w['end'].isoformat(timespec='minutes')}
        for w in expand_unavailability([u.id for u in users], start, end)
    ]

    # events that can take a shift: running in (or near) the window, plus the next few upcoming
    events = (Event.query.filter(Event.event_date < end + timedelta(days=60),
                                 or_(Event.event_end_date.is_(None), Event.event_end_date > start - timedelta(days=30)))
              .order_by(Event.event_date).limit(300).all())
    return jsonify({
        'start': start.date().isoformat(), 'days': days,
        'people': [{'id': u.id, 'name': u.shown_name, 'username': u.username,
                    'avatar': u.profile_picture or '', 'role': u.user_role or 'crew'} for u in users],
        'shifts': items,
        'open': open_items,
        'unavailable': unavailable,
        'events': [{'id': e.id, 'title': e.title,
                    'start': e.event_date.isoformat(timespec='minutes'),
                    'end': event_end(e).isoformat(timespec='minutes'),
                    'all_day': bool(e.all_day)} for e in events],
    })


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@roster_bp.route('/api/roster/shift', methods=['POST'])
@login_required
@crew_required
@manager_required
def create_shift():
    """Create a shift.  With ``user_id`` it is assigned; without, it is an open shift."""
    data = body()
    event = _get_event(data.get('event_id'))
    start, end = _window(data)
    role = clean_text(data.get('role'), 'Role', 100)
    notes = str(data.get('notes') or '').strip()
    user = _get_user(data['user_id']) if data.get('user_id') else None
    status = _status(data)
    if status == 'rejected':
        raise ApiError('A new shift cannot start out declined')
    conflicts = _check_clash(user.id, start, end, data) if user else []

    try:
        shift = Shift(event_id=event.id, title=role or 'Crew', role=role,
                      shift_date=start, shift_end_date=end, location=event.location,
                      positions_needed=1, is_open=user is None,
                      created_by=current_user.username)
        db.session.add(shift)
        db.session.flush()
        assignment = None
        if user:
            _ensure_crew_row(event, user, role)
            assignment = ShiftAssignment(shift_id=shift.id, user_id=user.id, status=status,
                                         assigned_by=current_user.username, notes=notes)
            db.session.add(assignment)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not create shift: {exc}', 500)
    if user:
        _email_new_assignment(user, event, shift, notes)
    return jsonify({'success': True, 'item': _item(shift, assignment), 'warnings': conflicts})


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------

@roster_bp.route('/api/roster/assignment/<int:aid>', methods=['PUT'])
@login_required
@crew_required
@manager_required
def edit_assignment(aid):
    """Edit an assigned shift: event, person, role, times, status, notes."""
    a = _found(ShiftAssignment, aid)
    data = body()
    old_event, old_user = a.shift.event, a.user
    event = _get_event(data.get('event_id') or a.shift.event_id)
    user = _get_user(data.get('user_id') or a.user_id)
    start, end = _window({'start': data.get('start') or a.shift.shift_date.isoformat(),
                          'end': data.get('end') or a.shift.shift_end_date.isoformat()})
    role = clean_text(data.get('role', a.shift.role), 'Role', 100)
    status = _status(data, a.status)
    person_changed = user.id != a.user_id

    conflicts = [] if status == 'rejected' else _check_clash(user.id, start, end, data, exclude_assignment_id=a.id)
    try:
        shift = a.shift
        if len(shift.assignments) > 1:
            shift = _split_shared_shift(a, start, end, role)
        shift.shift_date, shift.shift_end_date, shift.role = start, end, role
        shift.title = role or shift.title or 'Crew'
        shift.event_id = event.id
        if event.location and not shift.location:
            shift.location = event.location
        a.user_id = user.id
        if person_changed:
            a.assigned_by = current_user.username
            a.status = 'pending' if status == 'rejected' else status
            a.responded_at, a.decline_reason = None, None
        elif status != a.status:
            a.status, a.responded_at = status, datetime.utcnow()
            if status != 'rejected':
                a.decline_reason = None
        if 'notes' in data:
            a.notes = str(data.get('notes') or '').strip()
        _ensure_crew_row(event, user, role)
        db.session.flush()
        if person_changed:
            _tidy_crew_row(old_event.id, old_user)
        if old_event.id != event.id:
            _tidy_crew_row(old_event.id, user)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not save shift: {exc}', 500)
    if person_changed:
        _email_new_assignment(user, event, a.shift, a.notes or '')
    return jsonify({'success': True, 'item': _item(a.shift, a), 'warnings': conflicts})


@roster_bp.route('/api/roster/open/<int:shift_id>', methods=['PUT'])
@login_required
@crew_required
@manager_required
def edit_open_shift(shift_id):
    """Edit an unassigned shift; give ``user_id`` to assign it to someone."""
    shift = _found(Shift, shift_id)
    if shift.assignments:
        raise ApiError('This shift already has someone on it')
    data = body()
    event = _get_event(data.get('event_id') or shift.event_id)
    start, end = _window({'start': data.get('start') or shift.shift_date.isoformat(),
                          'end': data.get('end') or shift.shift_end_date.isoformat()})
    role = clean_text(data.get('role', shift.role), 'Role', 100)
    user = _get_user(data['user_id']) if data.get('user_id') else None
    status = _status(data)
    conflicts = _check_clash(user.id, start, end, data) if user else []
    notes = str(data.get('notes') or '').strip()
    try:
        shift.event_id, shift.shift_date, shift.shift_end_date = event.id, start, end
        shift.role, shift.title = role, role or shift.title or 'Crew'
        assignment = None
        if user:
            shift.is_open = False
            _ensure_crew_row(event, user, role)
            assignment = ShiftAssignment(shift_id=shift.id, user_id=user.id, status=status,
                                         assigned_by=current_user.username, notes=notes)
            db.session.add(assignment)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not save shift: {exc}', 500)
    if user:
        _email_new_assignment(user, event, shift, notes)
    return jsonify({'success': True, 'item': _item(shift, assignment), 'warnings': conflicts})


@roster_bp.route('/api/roster/open/<int:shift_id>', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_open_shift(shift_id):
    shift = _found(Shift, shift_id)
    if shift.assignments:
        raise ApiError('This shift has people on it - remove them first')
    db.session.delete(shift)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Drag & drop: move a shift to another person and/or day, keeping its times
# ---------------------------------------------------------------------------

@roster_bp.route('/api/roster/drop', methods=['POST'])
@login_required
@crew_required
@manager_required
def drop_shift():
    """
    Body: ``{key: 'a:12' | 's:7', user_id: int | null, date: 'YYYY-MM-DD', force?}``
    The shift keeps its time of day and length; only the day and person change.
    ``user_id`` null means the Unassigned row.
    """
    data = body()
    kind, _, raw = str(data.get('key', '')).partition(':')
    if kind not in ('a', 's') or not raw.isdigit():
        raise ApiError('Unknown shift')
    target_day = _parse_day(data.get('date'), None)
    if target_day is None:
        raise ApiError('Choose a day')
    new_user = _get_user(data['user_id']) if data.get('user_id') else None

    if kind == 'a':
        a = _found(ShiftAssignment, int(raw))
        shift = a.shift
    else:
        a = None
        shift = _found(Shift, int(raw))
        if shift.assignments:
            raise ApiError('This shift already has someone on it')

    length = shift.shift_end_date - shift.shift_date
    start = datetime.combine(target_day.date(), shift.shift_date.time())
    end = start + length
    event = shift.event

    conflicts = []
    if new_user and not (a and a.status == 'rejected'):
        conflicts = _check_clash(new_user.id, start, end, data, exclude_assignment_id=a.id if a else None)

    try:
        notify = None
        if a is not None:
            old_user = a.user
            if len(shift.assignments) > 1:
                shift = _split_shared_shift(a, start, end, shift.role)
            shift.shift_date, shift.shift_end_date = start, end
            if new_user is None:                      # back to the Unassigned row
                db.session.delete(a)
                shift.is_open = True
                db.session.flush()
                _tidy_crew_row(shift.event_id, old_user)
                a = None
            elif new_user.id != a.user_id:            # handed to someone else
                a.user_id, a.status = new_user.id, 'pending'
                a.assigned_by, a.responded_at, a.decline_reason = current_user.username, None, None
                _ensure_crew_row(event, new_user, shift.role)
                db.session.flush()
                _tidy_crew_row(shift.event_id, old_user)
                notify = new_user
        else:
            shift.shift_date, shift.shift_end_date = start, end
            if new_user:
                shift.is_open = False
                a = ShiftAssignment(shift_id=shift.id, user_id=new_user.id, status='pending',
                                    assigned_by=current_user.username)
                db.session.add(a)
                _ensure_crew_row(event, new_user, shift.role)
                notify = new_user
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f'Could not move shift: {exc}', 500)
    if notify:
        _email_new_assignment(notify, event, shift)
    return jsonify({'success': True, 'item': _item(shift, a), 'warnings': conflicts})
