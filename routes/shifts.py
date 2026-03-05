"""routes/shifts.py — Shift management, assignments, notes, tasks."""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Event, Shift, ShiftAssignment, ShiftNote, ShiftTask, User
from decorators import crew_required
from services.email_service import send_shift_assignment_email

shifts_bp = Blueprint('shifts', __name__)


@shifts_bp.route('/shifts/management')
@login_required
def shift_management():
    if not current_user.is_admin:
        from flask import flash, redirect, url_for
        flash('Admin access required', 'error')
        return redirect(url_for('calendar.calendar'))
    events = Event.query.order_by(Event.event_date).all()
    shifts = Shift.query.join(Event).order_by(Event.event_date, Shift.shift_date).all()
    users  = User.query.filter_by(user_role='crew').all()
    return render_template('/admin/shift_management.html', events=events, shifts=shifts, users=users)


@shifts_bp.route('/api/shifts', methods=['GET'])
@login_required
def get_shifts():
    event_id = request.args.get('event_id', type=int)
    shifts   = Shift.query.filter_by(event_id=event_id).all() if event_id else Shift.query.all()
    result   = []
    for shift in shifts:
        sd = {
            'id': shift.id, 'event_id': shift.event_id, 'title': shift.title,
            'description': shift.description,
            'shift_date': shift.shift_date.isoformat(),
            'shift_end_date': shift.shift_end_date.isoformat(),
            'location': shift.location, 'positions_needed': shift.positions_needed,
            'role': shift.role, 'is_open': shift.is_open,
            'event_title': shift.event.title if shift.event else '',
            'created_by': shift.created_by,
            'assignments_count': len(shift.assignments), 'assignments': [],
        }
        for a in shift.assignments:
            sd['assignments'].append({
                'id': a.id, 'user_id': a.user_id, 'username': a.user.username,
                'status': a.status, 'assigned_by': a.assigned_by,
                'assigned_at': a.assigned_at.isoformat(),
                'responded_at': a.responded_at.isoformat() if a.responded_at else None,
                'notes': a.notes,
            })
        result.append(sd)
    return jsonify(result)


@shifts_bp.route('/shifts/add', methods=['POST'])
@login_required
def add_shift():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    try:
        shift = Shift(
            event_id=data['event_id'], title=data.get('title', ''),
            description=data.get('description', ''),
            shift_date=datetime.fromisoformat(data['shift_date']),
            shift_end_date=datetime.fromisoformat(data['shift_end_date']),
            location=data.get('location', ''),
            positions_needed=int(data.get('positions_needed', 1)),
            role=data.get('role', ''), is_open=data.get('is_open', True),
            created_by=current_user.username,
        )
        db.session.add(shift)
        db.session.commit()
        return jsonify({'success': True, 'id': shift.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/edit', methods=['PUT'])
@login_required
def edit_shift(shift_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    shift = Shift.query.get_or_404(shift_id)
    data  = request.json
    try:
        shift.title            = data.get('title',            shift.title)
        shift.description      = data.get('description',      shift.description)
        shift.shift_date       = datetime.fromisoformat(data['shift_date'])
        shift.shift_end_date   = datetime.fromisoformat(data['shift_end_date'])
        shift.location         = data.get('location',         shift.location)
        shift.positions_needed = int(data.get('positions_needed', shift.positions_needed))
        shift.role             = data.get('role',             shift.role)
        shift.is_open          = data.get('is_open',          shift.is_open)
        shift.updated_at       = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>', methods=['DELETE'])
@login_required
def delete_shift(shift_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    shift = Shift.query.get_or_404(shift_id)
    try:
        db.session.delete(shift)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/assign', methods=['POST'])
@login_required
def assign_shift(shift_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    shift = Shift.query.get_or_404(shift_id)
    data  = request.json
    try:
        user = User.query.get_or_404(data['user_id'])
        if ShiftAssignment.query.filter_by(shift_id=shift_id, user_id=user.id).first():
            return jsonify({'error': 'User already assigned to this shift'}), 409
        assignment = ShiftAssignment(
            shift_id=shift_id, user_id=user.id,
            assigned_by=current_user.username, status='pending',
            notes=data.get('notes', ''),
        )
        db.session.add(assignment)
        db.session.commit()
        if user.email and shift.event:
            event = shift.event
            send_shift_assignment_email(
                recipient_email=user.email, username=user.username,
                event_title=event.title, shift_title=shift.title,
                shift_date=shift.shift_date.strftime('%B %d, %Y at %I:%M %p'),
                shift_end_time=shift.shift_end_date.strftime('%I:%M %p'),
                role=shift.role or 'General Crew',
                location=shift.location or event.location or 'TBD',
                positions_needed=shift.positions_needed,
                description=shift.description or '',
            )
        return jsonify({'success': True, 'id': assignment.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/claim', methods=['POST'])
@login_required
def claim_shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    if not shift.is_open:
        return jsonify({'error': 'This shift is no longer open for claims'}), 400
    if ShiftAssignment.query.filter_by(shift_id=shift_id, user_id=current_user.id).first():
        return jsonify({'error': 'You already claimed this shift'}), 409
    confirmed = ShiftAssignment.query.filter_by(shift_id=shift_id, status='confirmed').count()
    if confirmed >= shift.positions_needed:
        return jsonify({'error': 'This shift is already full'}), 400
    try:
        db.session.add(ShiftAssignment(
            shift_id=shift_id, user_id=current_user.id,
            assigned_by='self', status='confirmed', notes='Self-claimed',
        ))
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/assignment/<int:assignment_id>/respond', methods=['POST'])
@login_required
def respond_to_shift(assignment_id):
    assignment = ShiftAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    data   = request.json
    status = data.get('status', '').lower()
    if status not in ('accepted', 'rejected', 'confirmed'):
        return jsonify({'error': 'Invalid status'}), 400
    try:
        assignment.status       = status
        assignment.responded_at = datetime.utcnow()
        assignment.notes        = data.get('notes', assignment.notes)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/assignment/<int:assignment_id>', methods=['DELETE'])
@login_required
def delete_shift_assignment(assignment_id):
    assignment = ShiftAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    try:
        db.session.delete(assignment)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/reject', methods=['POST'])
@login_required
@crew_required
def reject_shift(shift_id):
    assignment = ShiftAssignment.query.filter_by(shift_id=shift_id, user_id=current_user.id).first()
    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404
    if assignment.status not in ('accepted', 'pending', 'confirmed'):
        return jsonify({'error': f'Cannot reject a {assignment.status} shift'}), 400
    try:
        assignment.status       = 'rejected'
        assignment.responded_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


# Notes
@shifts_bp.route('/shifts/<int:shift_id>/notes', methods=['POST'])
@login_required
def add_shift_note(shift_id):
    Shift.query.get_or_404(shift_id)
    try:
        note = ShiftNote(shift_id=shift_id, created_by=current_user.username,
                         content=request.json.get('content', ''))
        db.session.add(note)
        db.session.commit()
        return jsonify({'success': True, 'note_id': note.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/notes', methods=['GET'])
@login_required
def get_shift_notes(shift_id):
    Shift.query.get_or_404(shift_id)
    notes = ShiftNote.query.filter_by(shift_id=shift_id).order_by(ShiftNote.created_at.desc()).all()
    return jsonify({'success': True, 'notes': [
        {'id': n.id, 'content': n.content, 'created_by': n.created_by,
         'created_at': n.created_at.isoformat()} for n in notes
    ]})


@shifts_bp.route('/shifts/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_shift_note(note_id):
    note = ShiftNote.query.get_or_404(note_id)
    if note.created_by != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    try:
        db.session.delete(note)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


# Tasks
@shifts_bp.route('/shifts/<int:shift_id>/tasks', methods=['POST'])
@login_required
def add_shift_task(shift_id):
    Shift.query.get_or_404(shift_id)
    data = request.json
    try:
        task = ShiftTask(shift_id=shift_id, title=data.get('title', ''),
                         description=data.get('description', ''),
                         assigned_to=data.get('assigned_to'),
                         created_by=current_user.username)
        db.session.add(task)
        db.session.commit()
        return jsonify({'success': True, 'task_id': task.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/<int:shift_id>/tasks', methods=['GET'])
@login_required
def get_shift_tasks(shift_id):
    Shift.query.get_or_404(shift_id)
    tasks = ShiftTask.query.filter_by(shift_id=shift_id).order_by(ShiftTask.created_at).all()
    return jsonify({'success': True, 'tasks': [
        {'id': t.id, 'title': t.title, 'description': t.description,
         'is_complete': t.is_complete, 'assigned_to': t.assigned_to,
         'created_by': t.created_by, 'created_at': t.created_at.isoformat()} for t in tasks
    ]})


@shifts_bp.route('/shifts/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_shift_task(task_id):
    task = ShiftTask.query.get_or_404(task_id)
    data = request.json
    try:
        if 'is_complete' in data: task.is_complete  = data['is_complete']
        if 'title'       in data: task.title        = data['title']
        if 'description' in data: task.description  = data['description']
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@shifts_bp.route('/shifts/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_shift_task(task_id):
    task = ShiftTask.query.get_or_404(task_id)
    if task.created_by != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    try:
        db.session.delete(task)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
