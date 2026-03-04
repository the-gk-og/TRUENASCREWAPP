"""routes/todos.py — Personal to-do list for crew members."""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import Event, TodoItem
from decorators import crew_required

todos_bp = Blueprint('todos', __name__)


@todos_bp.route('/todos')
@login_required
@crew_required
def todos():
    user_todos = (
        TodoItem.query
        .filter_by(user_id=current_user.id)
        .order_by(TodoItem.is_completed, TodoItem.due_date.asc().nullslast(), TodoItem.created_at.desc())
        .all()
    )
    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('crew/todos.html', todos=user_todos, events=events)


@todos_bp.route('/todos/add', methods=['POST'])
@login_required
@crew_required
def add_todo():
    data = request.json
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400

    due_date = None
    if data.get('due_date'):
        try:
            due_date = datetime.fromisoformat(data['due_date'])
        except ValueError:
            return jsonify({'error': 'Invalid due date format'}), 400

    todo = TodoItem(
        user_id=current_user.id,
        title=title,
        description=(data.get('description') or '').strip() or None,
        priority=data.get('priority', 'medium'),
        due_date=due_date,
        event_id=data.get('event_id') or None,
    )
    db.session.add(todo)
    db.session.commit()
    return jsonify({'success': True, 'id': todo.id})


@todos_bp.route('/todos/<int:id>/toggle', methods=['POST'])
@login_required
@crew_required
def toggle_todo(id):
    todo = TodoItem.query.get_or_404(id)
    if todo.user_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    todo.is_completed = not todo.is_completed
    todo.completed_at = datetime.utcnow() if todo.is_completed else None
    db.session.commit()
    return jsonify({'success': True, 'is_completed': todo.is_completed})


@todos_bp.route('/todos/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_todo(id):
    todo = TodoItem.query.get_or_404(id)
    if todo.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    db.session.delete(todo)
    db.session.commit()
    return jsonify({'success': True})


@todos_bp.route('/todos/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_todo(id):
    todo = TodoItem.query.get_or_404(id)
    if todo.user_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403

    data = request.json
    if 'title' in data:
        title = data['title'].strip()
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        todo.title = title
    if 'description' in data:
        todo.description = (data['description'] or '').strip() or None
    if 'priority' in data:
        todo.priority = data['priority']
    if 'event_id' in data:
        todo.event_id = data['event_id'] or None
    if 'due_date' in data:
        if data['due_date']:
            try:
                todo.due_date = datetime.fromisoformat(data['due_date'])
            except ValueError:
                return jsonify({'error': 'Invalid due date format'}), 400
        else:
            todo.due_date = None

    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500