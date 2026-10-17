"""routes/crew.py — Crew assignments, dashboard, schedule, availability."""

from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, jsonify,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Event, CrewAssignment, User, TodoItem,
    Shift, ShiftAssignment, UserUnavailability, RecurringUnavailability,
)
from decorators import crew_required
from services.user_names import find_user_by_username
from services.email_service import (
    send_crew_assignment_email, send_event_reminder_email,
)

crew_bp = Blueprint('crew', __name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@crew_bp.route('/dashboard')
@login_required
@crew_required
def dashboard():
    now             = datetime.now()
    upcoming_events = Event.query.filter(Event.event_date >= now).order_by(Event.event_date).limit(10).all()

    my_upcoming_events = []
    for event in upcoming_events:
        for a in CrewAssignment.query.filter_by(event_id=event.id).all():
            if a.crew_member.lower() == current_user.username.lower():
                my_upcoming_events.append(event)
                break

    pending_tasks       = TodoItem.query.filter_by(user_id=current_user.id, is_completed=False).order_by(TodoItem.due_date).all()
    week_end            = now + timedelta(days=7)
    events_this_week    = Event.query.filter(Event.event_date >= now, Event.event_date <= week_end).count()
    my_events_this_week = 0

    for event in Event.query.filter(Event.event_date >= now, Event.event_date <= week_end).all():
        for a in CrewAssignment.query.filter_by(event_id=event.id).all():
            if a.crew_member.lower() == current_user.username.lower():
                my_events_this_week += 1
                break

    return render_template(
        '/crew/dashboard.html',
        upcoming_events=upcoming_events,
        my_upcoming_events=my_upcoming_events,
        pending_tasks_count=len(pending_tasks),
        pending_tasks=pending_tasks,
        my_events_this_week=my_events_this_week,
        events_this_week=events_this_week,
        next_event=my_upcoming_events[0] if my_upcoming_events else None,
        now=now,
    )


# ---------------------------------------------------------------------------
# Crew assignment
# ---------------------------------------------------------------------------

@crew_bp.route('/crew/assign', methods=['POST'])
@login_required
@crew_required
def assign_crew():
    data       = request.json
    assignment = CrewAssignment(
        event_id=data['event_id'],
        crew_member=data['crew_member'],
        role=data.get('role', ''),
        assigned_via='webapp',
    )
    db.session.add(assignment)
    db.session.commit()

    user  = find_user_by_username(data['crew_member'])
    event = Event.query.get(data['event_id'])
    if user and user.email and event:
        send_crew_assignment_email(
            recipient_email=user.email, username=user.shown_name,
            event_title=event.title,
            event_date=event.event_date.strftime('%B %d, %Y at %I:%M %p'),
            event_location=event.location or 'TBD',
            role=data.get('role', 'Crew Member'),
            event_description=event.description or '',
        )
    return jsonify({'success': True, 'id': assignment.id})


@crew_bp.route('/crew/remove/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def remove_crew(id):
    assignment = CrewAssignment.query.get_or_404(id)
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({'success': True})


@crew_bp.route('/crew/assign-all', methods=['POST'])
@login_required
@crew_required
def assign_all_crew():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data     = request.json
    event_id = data.get('event_id')
    event    = Event.query.get_or_404(event_id)
    added    = 0
    for user in User.query.filter(User.user_role.in_(['crew', 'crew_admin'])).all():
        if not CrewAssignment.query.filter_by(event_id=event_id, crew_member=user.username).first():
            db.session.add(CrewAssignment(event_id=event_id, crew_member=user.username,
                                          role='Crew Member', assigned_via='webapp'))
            added += 1
            if user.email:
                send_crew_assignment_email(
                    recipient_email=user.email, username=user.shown_name,
                    event_title=event.title,
                    event_date=event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                    event_location=event.location or 'TBD',
                    role='Crew Member',
                )
    db.session.commit()
    return jsonify({'success': True, 'added': added})


@crew_bp.route('/crew/resend-notification', methods=['POST'])
@login_required
@crew_required
def resend_notification():
    data       = request.json
    assignment = CrewAssignment.query.get(data.get('assignment_id'))
    event      = Event.query.get(data.get('event_id'))
    if not assignment or not event:
        return jsonify({'error': 'Not found'}), 404
    user = find_user_by_username(assignment.crew_member)
    if user and user.email:
        send_event_reminder_email(
            recipient_email=user.email, username=user.shown_name,
            event_title=event.title,
            event_date=event.event_date.strftime('%B %d, %Y at %I:%M %p'),
            event_location=event.location or 'TBD',
            role=assignment.role or 'Crew Member',
            reminder_type='tomorrow',
        )
        return jsonify({'success': True})
    return jsonify({'error': 'User has no email'}), 400


# ---------------------------------------------------------------------------
# Join / leave event
# ---------------------------------------------------------------------------

@crew_bp.route('/crew/join-event', methods=['POST'])
@login_required
@crew_required
def join_event_from_calendar():
    data     = request.json
    event_id = data.get('event_id')
    if not event_id:
        return jsonify({'error': 'Event ID required'}), 400
    event = Event.query.get_or_404(event_id)
    if CrewAssignment.query.filter_by(event_id=event_id, crew_member=current_user.username).first():
        return jsonify({'error': 'You are already assigned to this event'}), 400
    try:
        db.session.add(CrewAssignment(
            event_id=event_id, crew_member=current_user.username,
            role='Crew Member', assigned_via='self',
        ))
        db.session.commit()
        return jsonify({'success': True, 'message': 'Successfully joined event'})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@crew_bp.route('/crew/leave-event', methods=['POST'])
@login_required
@crew_required
def leave_event():
    data          = request.json
    assignment_id = data.get('assignment_id')
    if not assignment_id:
        return jsonify({'error': 'Assignment ID required'}), 400
    assignment = CrewAssignment.query.get_or_404(assignment_id)
    if assignment.crew_member != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        event = Event.query.get(assignment.event_id)
        db.session.delete(assignment)
        db.session.commit()
        return jsonify({'success': True, 'message': f'You left {event.title}' if event else 'Assignment removed'})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# My schedule
# ---------------------------------------------------------------------------

@crew_bp.route('/crew/my-schedule')
@login_required
@crew_required
def my_schedule():
    """Everything the current user is rostered on, soonest first."""
    from models import Shift, ShiftAssignment, CrewAssignment, Event
    from datetime import datetime
    from routes.events import event_end, fmt_range

    now = datetime.now()
    rows = (db.session.query(ShiftAssignment, Shift, Event)
            .join(Shift, ShiftAssignment.shift_id == Shift.id)
            .join(Event, Shift.event_id == Event.id)
            .filter(ShiftAssignment.user_id == current_user.id)
            .order_by(Shift.shift_date).all())

    items = []
    events_with_shift = set()
    for a, shift, event in rows:
        events_with_shift.add(event.id)
        items.append({
            'kind': 'shift', 'assignment': a, 'shift': shift, 'event': event,
            'start': shift.shift_date, 'end': shift.shift_end_date,
            'role': shift.role or '', 'status': a.status,
            'when': fmt_range(shift.shift_date, shift.shift_end_date),
            'location': shift.location or event.location or '',
        })

    # On the crew for an event but no shift times yet (self-joined, Discord, older data)
    for ca in CrewAssignment.query.filter_by(crew_member=current_user.username).all():
        event = db.session.get(Event, ca.event_id)
        if not event or event.id in events_with_shift:
            continue
        items.append({
            'kind': 'crew', 'assignment': None, 'shift': None, 'event': event,
            'start': event.event_date, 'end': event_end(event),
            'role': ca.role or '', 'status': 'crew',
            'when': fmt_range(event.event_date, event_end(event), bool(event.all_day)),
            'location': event.location or '',
        })

    items.sort(key=lambda i: i['start'])
    upcoming = [i for i in items if i['end'] >= now]
    past = [i for i in items if i['end'] < now][::-1][:50]
    pending = [i for i in upcoming if i['status'] == 'pending']
    return render_template('/crew/my_schedule.html', upcoming=upcoming, past=past,
                           pending=pending, now=now)

# ---------------------------------------------------------------------------
# Unavailability
# ---------------------------------------------------------------------------

@crew_bp.route('/unavailability/add', methods=['POST'])
@login_required
def add_unavailability():
    data = request.json
    try:
        unavail = UserUnavailability(
            user_id=current_user.id,
            title=data.get('title', 'Unavailable'),
            description=data.get('description', ''),
            start_date=datetime.fromisoformat(data['start_date']),
            end_date=datetime.fromisoformat(data['end_date']),
            is_all_day=data.get('is_all_day', False),
            recurrence_pattern=data.get('recurrence_pattern'),
            recurrence_interval=data.get('recurrence_interval', 1),
            recurrence_end_date=(datetime.fromisoformat(data['recurrence_end_date'])
                                  if data.get('recurrence_end_date') else None),
            recurrence_count=data.get('recurrence_count'),
        )
        db.session.add(unavail)
        db.session.commit()
        return jsonify({'success': True, 'id': unavail.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@crew_bp.route('/unavailability/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_unavailability(id):
    unavail = UserUnavailability.query.get_or_404(id)
    if unavail.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        db.session.delete(unavail)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@crew_bp.route('/unavailability/list', methods=['GET'])
@login_required
def list_unavailabilities():
    user_id = request.args.get('user_id', current_user.id)
    if int(user_id) != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    result = [
        {
            'id': u.id, 'title': u.title, 'description': u.description,
            'start_date': u.start_date.isoformat(), 'end_date': u.end_date.isoformat(),
            'is_all_day': u.is_all_day, 'recurrence_pattern': u.recurrence_pattern,
            'recurrence_interval': u.recurrence_interval,
            'recurrence_end_date': u.recurrence_end_date.isoformat() if u.recurrence_end_date else None,
            'recurrence_count': u.recurrence_count,
        }
        for u in UserUnavailability.query.filter_by(user_id=user_id).all()
    ]
    return jsonify({'success': True, 'unavailabilities': result})


def _normalise_days(value):
    """Accept '1,3', [1, 3] or '["1","3"]' and store '1,3' (Sunday=0 … Saturday=6)."""
    import re
    if value is None or value == '':
        return None
    digits = re.findall(r'[0-6]', ','.join(map(str, value)) if isinstance(value, (list, tuple)) else str(value))
    return ','.join(sorted(set(digits))) or None


@crew_bp.route('/recurring-unavailability/list', methods=['GET'])
@login_required
def list_recurring_unavailabilities():
    rows = RecurringUnavailability.query.filter_by(user_id=current_user.id, is_active=True) \
        .order_by(RecurringUnavailability.start_date).all()
    return jsonify({'success': True, 'patterns': [{
        'id': r.id, 'title': r.title, 'description': r.description,
        'start_time': r.start_time, 'end_time': r.end_time, 'pattern_type': r.pattern_type,
        'days_of_week': r.days_of_week, 'day_of_month': r.day_of_month,
        'start_date': r.start_date.isoformat(),
        'end_date': r.end_date.isoformat() if r.end_date else None,
    } for r in rows]})


@crew_bp.route('/recurring-unavailability/add', methods=['POST'])
@login_required
def add_recurring_unavailability():
    data = request.json
    try:
        r = RecurringUnavailability(
            user_id=current_user.id,
            title=data.get('title', 'Recurring Unavailability'),
            description=data.get('description', ''),
            start_time=data['start_time'], end_time=data['end_time'],
            pattern_type=data['pattern_type'],
            days_of_week=_normalise_days(data.get('days_of_week')),
            day_of_month=data.get('day_of_month'),
            start_date=datetime.fromisoformat(data['start_date']),
            end_date=datetime.fromisoformat(data['end_date']) if data.get('end_date') else None,
            is_active=data.get('is_active', True),
        )
        db.session.add(r)
        db.session.commit()
        return jsonify({'success': True, 'id': r.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@crew_bp.route('/recurring-unavailability/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_recurring_unavailability(id):
    r = RecurringUnavailability.query.get_or_404(id)
    if r.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        db.session.delete(r)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@crew_bp.route('/api/unavailabilities-week', methods=['GET'])
@login_required
def api_unavailabilities_week():
    """Kept for compatibility: everyone's unavailability between start and end."""
    from services.availability_service import expand_unavailability
    try:
        start_date = datetime.fromisoformat(request.args['start'].replace('Z', '')[:19])
        end_date   = datetime.fromisoformat(request.args['end'].replace('Z', '')[:19])
    except (KeyError, ValueError) as exc:
        return jsonify({'error': f'start and end dates required: {exc}'}), 400
    users = {u.id: u.username for u in User.query.filter_by(user_role='crew').all()}
    out = [{
        'id': w['id'], 'username': users.get(w['user_id'], ''), 'title': w['title'],
        'start': w['start'].isoformat(), 'end': w['end'].isoformat(),
        'is_all_day': w['all_day'],
        'type': 'recurring_unavailability' if w['recurring'] else 'unavailability',
    } for w in expand_unavailability(list(users), start_date, end_date)]
    return jsonify({'success': True, 'unavailabilities': out})
