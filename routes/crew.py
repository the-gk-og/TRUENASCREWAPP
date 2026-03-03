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

    user  = User.query.filter_by(username=data['crew_member']).first()
    event = Event.query.get(data['event_id'])
    if user and user.email and event:
        send_crew_assignment_email(
            recipient_email=user.email, username=user.username,
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
                    recipient_email=user.email, username=user.username,
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
    user = User.query.filter_by(username=assignment.crew_member).first()
    if user and user.email:
        send_event_reminder_email(
            recipient_email=user.email, username=user.username,
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

@crew_bp.route('/my-schedule')
@login_required
@crew_required
def my_schedule():
    shift_assignments = ShiftAssignment.query.filter_by(user_id=current_user.id).all()
    assignments = []
    for sa in shift_assignments:
        shift = sa.shift
        event = shift.event if shift else None
        assignments.append({
            'id': sa.id, 'user_id': sa.user_id,
            'shift_id': shift.id if shift else None,
            'status': sa.status, 'assigned_by': sa.assigned_by,
            'assigned_at': sa.assigned_at.isoformat() if sa.assigned_at else None,
            'responded_at': sa.responded_at.isoformat() if sa.responded_at else None,
            'notes': sa.notes,
            'shift': {
                'id': shift.id, 'title': shift.title,
                'description': shift.description,
                'shift_date': shift.shift_date.isoformat(),
                'shift_end_date': shift.shift_end_date.isoformat(),
                'location': shift.location, 'role': shift.role,
                'positions_needed': shift.positions_needed,
                'event_id': shift.event_id,
                'event': {
                    'id': event.id, 'title': event.title,
                    'event_date': event.event_date.isoformat(),
                    'event_end_date': event.event_end_date.isoformat() if event.event_end_date else None,
                } if event else None,
            } if shift else None,
        })

    crew_assignments_objs = CrewAssignment.query.filter_by(crew_member=current_user.username).all()
    crew_assignments = []
    for ca in crew_assignments_objs:
        event = ca.event
        crew  = event.crew_assignments if event else []
        crew_assignments.append({
            'id': ca.id, 'crew_member': ca.crew_member, 'role': ca.role,
            'assigned_at': ca.assigned_at.isoformat(),
            'event_id': event.id if event else None,
            'event': {
                'id': event.id, 'title': event.title,
                'description': event.description,
                'event_date': event.event_date.isoformat(),
                'event_end_date': event.event_end_date.isoformat() if event.event_end_date else None,
                'location': event.location,
                'crew_assignments': [{'crew_member': c.crew_member, 'role': c.role} for c in crew],
            } if event else None,
        })

    open_shifts = []
    for shift in Shift.query.filter_by(is_open=True).join(Event).order_by(Event.event_date).all():
        event = shift.event
        open_shifts.append({
            'id': shift.id, 'title': shift.title, 'description': shift.description,
            'shift_date': shift.shift_date.isoformat(),
            'shift_end_date': shift.shift_end_date.isoformat(),
            'location': shift.location, 'role': shift.role,
            'positions_needed': shift.positions_needed,
            'assignments_count': len(shift.assignments),
            'event_id': event.id if event else None,
            'event_title': event.title if event else None,
        })

    return render_template(
        '/crew/my_schedule.html',
        assignments=assignments,
        crew_assignments=crew_assignments,
        open_shifts=open_shifts,
        now=datetime.now(),
    )


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
            days_of_week=data.get('days_of_week'),
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
    start_str = request.args.get('start')
    end_str   = request.args.get('end')
    if not start_str or not end_str:
        return jsonify({'error': 'start and end dates required'}), 400
    try:
        start_date = datetime.fromisoformat(start_str)
        end_date   = datetime.fromisoformat(end_str)
    except Exception as exc:
        return jsonify({'error': f'Invalid date format: {exc}'}), 400

    crew_users    = User.query.filter_by(user_role='crew').all()
    unavailabilities = []
    for user in crew_users:
        for u in UserUnavailability.query.filter(
            UserUnavailability.user_id == user.id,
            UserUnavailability.start_date <= end_date,
            UserUnavailability.end_date   >= start_date,
        ).all():
            unavailabilities.append({
                'id': u.id, 'username': user.username, 'title': u.title,
                'start': u.start_date.isoformat(), 'end': u.end_date.isoformat(),
                'description': u.description, 'is_all_day': u.is_all_day,
                'type': 'unavailability',
            })
        for rec in RecurringUnavailability.query.filter(
            RecurringUnavailability.user_id   == user.id,
            RecurringUnavailability.is_active == True,
            RecurringUnavailability.start_date <= end_date,
            (RecurringUnavailability.end_date >= start_date) | (RecurringUnavailability.end_date == None),
        ).all():
            current = start_date
            while current < end_date:
                should = False
                if rec.pattern_type == 'daily':
                    should = True
                elif rec.pattern_type == 'weekly':
                    days   = list(map(int, rec.days_of_week.split(','))) if rec.days_of_week else []
                    form_d = (current.weekday() + 1) % 7
                    should = form_d in days
                elif rec.pattern_type == 'monthly':
                    should = current.day == rec.day_of_month
                if should and current.date() >= rec.start_date.date():
                    if rec.end_date is None or current.date() <= rec.end_date.date():
                        sh, sm = map(int, rec.start_time.split(':'))
                        eh, em = map(int, rec.end_time.split(':'))
                        unavailabilities.append({
                            'id': f'rec-{rec.id}-{current.date()}',
                            'username': user.username, 'title': rec.title,
                            'start': current.replace(hour=sh, minute=sm, second=0).isoformat(),
                            'end':   current.replace(hour=eh, minute=em, second=0).isoformat(),
                            'description': rec.description, 'is_all_day': False,
                            'type': 'recurring_unavailability',
                        })
                current += timedelta(days=1)
    return jsonify({'success': True, 'unavailabilities': unavailabilities})
