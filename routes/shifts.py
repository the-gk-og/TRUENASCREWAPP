"""
routes/shifts.py
================
Shifts are created through the event page (routes/events.py: "team" routes).
This module holds what is left around them:

* the old "Shift Management" URL (now redirects to the events list)
* a read-only JSON API
* a crew member accepting / declining their own shift
* per-shift notes and tasks (kept for existing data)
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from extensions import db
from models import Shift, ShiftAssignment, ShiftNote, ShiftTask
from services.user_names import name_for
from decorators import crew_required
from services.shift_notifications import notify_shift_declined

shifts_bp = Blueprint('shifts', __name__)


@shifts_bp.route('/shifts/management')
@login_required
def shift_management():
    """Shifts now live inside each event."""
    return redirect(url_for('events.events_list'))


@shifts_bp.route('/api/shifts', methods=['GET'])
@login_required
@crew_required
def get_shifts():
    """Shifts for an event.  Non-admins only see their own."""
    event_id = request.args.get('event_id', type=int)
    q = Shift.query
    if event_id:
        q = q.filter_by(event_id=event_id)
    result = []
    for shift in q.order_by(Shift.shift_date).all():
        rows = [a for a in shift.assignments
                if current_user.is_admin or a.user_id == current_user.id]
        if not current_user.is_admin and not rows:
            continue
        result.append({
            'id': shift.id, 'event_id': shift.event_id,
            'event_title': shift.event.title if shift.event else '',
            'title': shift.title, 'role': shift.role, 'location': shift.location,
            'shift_date': shift.shift_date.isoformat(),
            'shift_end_date': shift.shift_end_date.isoformat(),
            'assignments': [{
                'id': a.id, 'user_id': a.user_id,
                'username': a.user.username if a.user else '?',
                'name': a.user.shown_name if a.user else '?',
                'status': a.status, 'notes': a.notes,
            } for a in rows],
        })
    return jsonify(result)


@shifts_bp.route('/shifts/assignment/<int:assignment_id>/respond', methods=['POST'])
@login_required
def respond_to_shift(assignment_id):
    """Accept or decline a shift.  Admins may also set 'confirmed'/'pending'."""
    assignment = ShiftAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    data = request.get_json(silent=True) or {}
    status = str(data.get('status', '')).lower()
    allowed = {'accepted', 'rejected'}
    if current_user.is_admin:
        allowed |= {'confirmed', 'pending'}
    if status not in allowed:
        return jsonify({'error': 'Invalid status'}), 400
    was_rejected = assignment.status == 'rejected'
    try:
        assignment.status = status
        assignment.responded_at = datetime.utcnow()
        if 'notes' in data:
            assignment.notes = str(data.get('notes') or '').strip()
        if status == 'rejected':
            assignment.decline_reason = str(data.get('reason') or '').strip()[:500] or None
        else:
            assignment.decline_reason = None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    # Only tell the admins when the person themselves declines (not when an admin edits it)
    if status == 'rejected' and not was_rejected and assignment.user_id == current_user.id:
        notify_shift_declined(assignment)
    return jsonify({'success': True, 'status': status})


@shifts_bp.route('/shifts/<int:shift_id>/reject', methods=['POST'])
@login_required
@crew_required
def reject_shift(shift_id):
    assignment = ShiftAssignment.query.filter_by(shift_id=shift_id, user_id=current_user.id).first()
    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404
    was_rejected = assignment.status == 'rejected'
    assignment.status = 'rejected'
    assignment.responded_at = datetime.utcnow()
    assignment.decline_reason = str((request.get_json(silent=True) or {}).get('reason') or '').strip()[:500] or None
    db.session.commit()
    if not was_rejected:
        notify_shift_declined(assignment)
    return jsonify({'success': True})


# --- Notes -----------------------------------------------------------------

@shifts_bp.route('/shifts/<int:shift_id>/notes', methods=['POST'])
@login_required
def add_shift_note(shift_id):
    Shift.query.get_or_404(shift_id)
    note = ShiftNote(shift_id=shift_id, created_by=current_user.username,
                     content=(request.get_json(silent=True) or {}).get('content', ''))
    db.session.add(note)
    db.session.commit()
    return jsonify({'success': True, 'note_id': note.id})


@shifts_bp.route('/shifts/<int:shift_id>/notes', methods=['GET'])
@login_required
def get_shift_notes(shift_id):
    Shift.query.get_or_404(shift_id)
    notes = ShiftNote.query.filter_by(shift_id=shift_id).order_by(ShiftNote.created_at.desc()).all()
    return jsonify({'success': True, 'notes': [
        {'id': n.id, 'content': n.content, 'created_by': n.created_by, 'created_by_name': name_for(n.created_by),
         'created_at': n.created_at.isoformat()} for n in notes]})


@shifts_bp.route('/shifts/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_shift_note(note_id):
    note = ShiftNote.query.get_or_404(note_id)
    if note.created_by != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    db.session.delete(note)
    db.session.commit()
    return jsonify({'success': True})


# --- Tasks -----------------------------------------------------------------

@shifts_bp.route('/shifts/<int:shift_id>/tasks', methods=['POST'])
@login_required
def add_shift_task(shift_id):
    Shift.query.get_or_404(shift_id)
    data = request.get_json(silent=True) or {}
    task = ShiftTask(shift_id=shift_id, title=data.get('title', ''),
                     description=data.get('description', ''),
                     assigned_to=data.get('assigned_to'), created_by=current_user.username)
    db.session.add(task)
    db.session.commit()
    return jsonify({'success': True, 'task_id': task.id})


@shifts_bp.route('/shifts/<int:shift_id>/tasks', methods=['GET'])
@login_required
def get_shift_tasks(shift_id):
    Shift.query.get_or_404(shift_id)
    tasks = ShiftTask.query.filter_by(shift_id=shift_id).order_by(ShiftTask.created_at).all()
    return jsonify({'success': True, 'tasks': [
        {'id': t.id, 'title': t.title, 'description': t.description,
         'is_complete': t.is_complete, 'assigned_to': t.assigned_to, 'assigned_to_name': name_for(t.assigned_to),
         'created_by': t.created_by, 'created_by_name': name_for(t.created_by), 'created_at': t.created_at.isoformat()} for t in tasks]})


@shifts_bp.route('/shifts/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_shift_task(task_id):
    task = ShiftTask.query.get_or_404(task_id)
    data = request.get_json(silent=True) or {}
    for field in ('is_complete', 'title', 'description'):
        if field in data:
            setattr(task, field, data[field])
    db.session.commit()
    return jsonify({'success': True})


@shifts_bp.route('/shifts/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_shift_task(task_id):
    task = ShiftTask.query.get_or_404(task_id)
    if task.created_by != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})
