"""
routes/event_tasks.py
=====================
Tasks for events, for shifts, and for people outside of any event.

* Event task      - made on the event page.  Everyone linked to the event (on its team, or
                    holding one of its shifts) can see it, open it from their Tasks page and
                    tick it off.  It can be given to one person, or left for "anyone on the event".
* Shift task      - an event task attached to one shift.  If the shift belongs to one person and
                    nobody is chosen, the task goes to that person.
* Assigned task   - no event at all: an admin gives a person a task straight from the Tasks page.

Who can do what
---------------
* Create / edit / delete / assign event tasks: admins and the creator of the event.
* Create / edit / delete standalone assigned tasks: admins.
* Tick a task off (or back on): admins, the person it is assigned to, whoever made it, and - for
  event tasks - anyone linked to the event.
* See a task: the same people.  Admins see everything.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from decorators import crew_required
from extensions import db
from models import CrewAssignment, Event, EventTask, Shift, ShiftAssignment, User
from routes.events import (
    ApiError, body, can_edit_event, clean_text, event_end, is_manager, manager_required, parse_dt,
)
from services.user_names import name_for

event_tasks_bp = Blueprint('event_tasks', __name__)

PRIORITIES = ('low', 'medium', 'high')
_PRIORITY_RANK = {'high': 0, 'medium': 1, 'low': 2}


# ---------------------------------------------------------------------------
# Who is linked to what
# ---------------------------------------------------------------------------

def team_user_ids(event: Event) -> set[int]:
    """Everyone on the event: on its crew list or holding one of its shifts."""
    ids = {a.user_id for s in event.shifts for a in s.assignments}
    names = [c.crew_member for c in event.crew_assignments]
    if names:
        ids |= {u.id for u in User.query.filter(User.username.in_(names)).all()}
    return ids


def linked_event_ids(user: User) -> set[int]:
    """Events this person is on (crew list or a shift)."""
    ids = {row[0] for row in (db.session.query(Shift.event_id)
                              .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
                              .filter(ShiftAssignment.user_id == user.id).all())}
    ids |= {row[0] for row in (db.session.query(CrewAssignment.event_id)
                               .filter(CrewAssignment.crew_member == user.username).all())}
    return ids


def is_linked(event: Event, user: User | None = None) -> bool:
    user = user or current_user
    return user.id in team_user_ids(event)


def can_view_task(task: EventTask) -> bool:
    if is_manager() or task.assigned_user_id == current_user.id:
        return True
    return bool(task.event and is_linked(task.event))


def can_manage_task(task: EventTask) -> bool:
    if task.event:
        return can_edit_event(task.event)
    return is_manager()


def can_tick_task(task: EventTask) -> bool:
    return can_view_task(task) or task.created_by == current_user.username


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def shift_label(s: Shift) -> str:
    who = ', '.join(a.user.shown_name for a in s.assignments if a.user)
    when = f"{s.shift_date.strftime('%a')} {s.shift_date.day} {s.shift_date.strftime('%b')}, " \
           f"{s.shift_date.strftime('%I:%M %p').lstrip('0')}"
    bits = [b for b in (s.role, who) if b]
    return f"{' · '.join(bits) or 'Shift'} ({when})"


def serialize_task(t: EventTask) -> dict:
    return {
        'id': t.id,
        'title': t.title,
        'description': t.description or '',
        'priority': t.priority if t.priority in PRIORITIES else 'medium',
        'due': t.due_date.strftime('%Y-%m-%d') if t.due_date else '',
        'done': bool(t.is_completed),
        'completed_by': name_for(t.completed_by) if t.completed_by else '',
        'assignee_id': t.assigned_user_id,
        'assignee': t.assignee.shown_name if t.assignee else '',
        'event_id': t.event_id,
        'event_title': t.event.title if t.event else '',
        'shift_id': t.shift_id,
        'shift': shift_label(t.shift) if t.shift else '',
        'mine': t.assigned_user_id == current_user.id,
    }


def sort_tasks(tasks):
    far = datetime.max
    return sorted(tasks, key=lambda t: (bool(t.is_completed), t.due_date or far,
                                        _PRIORITY_RANK.get(t.priority, 1), t.id))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _assignee(data: dict, event: Event | None):
    """Resolve ``assigned_user_id`` (blank = nobody).  Event tasks can only go to people on the event."""
    raw = data.get('assigned_user_id')
    if raw in (None, '', 0, '0'):
        return None
    try:
        user = db.session.get(User, int(raw))
    except (TypeError, ValueError):
        user = None
    if not user:
        raise ApiError('That person does not exist')
    if user.is_cast and not user.is_admin:
        raise ApiError('Cast members cannot be given tasks')
    if event is not None and user.id not in team_user_ids(event):
        raise ApiError(f'{user.shown_name} is not on this event yet - add them to the team first')
    return user


def _shift_for(data: dict, event: Event):
    raw = data.get('shift_id')
    if raw in (None, '', 0, '0'):
        return None
    try:
        shift = db.session.get(Shift, int(raw))
    except (TypeError, ValueError):
        shift = None
    if not shift or shift.event_id != event.id:
        raise ApiError('That shift is not part of this event')
    return shift


def _apply(task: EventTask, data: dict, event: Event | None, creating: bool):
    """Copy the fields present in ``data`` onto the task (all of them when creating)."""
    if creating or 'title' in data:
        task.title = clean_text(data.get('title'), 'Title', 200, required=True)
    if creating or 'description' in data:
        task.description = clean_text(data.get('description'), 'Description', 4000) or None
    if creating or 'priority' in data:
        pr = str(data.get('priority') or 'medium').lower()
        if pr not in PRIORITIES:
            raise ApiError('Invalid priority')
        task.priority = pr
    if creating or 'due_date' in data:
        task.due_date = parse_dt(data['due_date'], 'Due date') if data.get('due_date') else None

    if creating or 'assigned_user_id' in data:
        user = _assignee(data, event)
        task.assigned_user_id = user.id if user else None
    if event is not None and (creating or 'shift_id' in data):
        shift = _shift_for(data, event)
        task.shift_id = shift.id if shift else None
        # A task on someone's shift goes to that person unless another person was chosen
        if shift and not task.assigned_user_id and len(shift.assignments) == 1:
            task.assigned_user_id = shift.assignments[0].user_id
    if event is None and not task.assigned_user_id:
        raise ApiError('Choose who this task is for')


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@event_tasks_bp.route('/events/<int:event_id>/tasks/add', methods=['POST'])
@login_required
@crew_required
def add_event_task(event_id):
    event = Event.query.get_or_404(event_id)
    if not can_edit_event(event):
        raise ApiError('Only admins and the event creator can add tasks', 403)
    task = EventTask(event_id=event.id, created_by=current_user.username)
    _apply(task, body(), event, creating=True)
    db.session.add(task)
    db.session.commit()
    return jsonify({'success': True, 'task': serialize_task(task)})


@event_tasks_bp.route('/tasks/assign', methods=['POST'])
@login_required
@crew_required
@manager_required
def add_assigned_task():
    """A task for one person that is not part of any event."""
    task = EventTask(created_by=current_user.username)
    _apply(task, body(), None, creating=True)
    db.session.add(task)
    db.session.commit()
    return jsonify({'success': True, 'task': serialize_task(task)})


@event_tasks_bp.route('/event-tasks/<int:task_id>', methods=['PUT'])
@login_required
@crew_required
def edit_event_task(task_id):
    task = EventTask.query.get_or_404(task_id)
    if not can_manage_task(task):
        raise ApiError('Permission denied', 403)
    _apply(task, body(), task.event, creating=False)
    db.session.commit()
    return jsonify({'success': True, 'task': serialize_task(task)})


@event_tasks_bp.route('/event-tasks/<int:task_id>/toggle', methods=['POST'])
@login_required
@crew_required
def toggle_event_task(task_id):
    task = EventTask.query.get_or_404(task_id)
    if not can_tick_task(task):
        raise ApiError('Permission denied', 403)
    data = request.get_json(silent=True) or {}
    done = bool(data['completed']) if 'completed' in data else not task.is_completed
    task.is_completed = done
    task.completed_at = datetime.utcnow() if done else None
    task.completed_by = current_user.username if done else None
    db.session.commit()
    return jsonify({'success': True, 'task': serialize_task(task)})


@event_tasks_bp.route('/event-tasks/<int:task_id>', methods=['DELETE'])
@login_required
@crew_required
def delete_event_task(task_id):
    task = EventTask.query.get_or_404(task_id)
    if not can_manage_task(task):
        raise ApiError('Permission denied', 403)
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# What the pages need
# ---------------------------------------------------------------------------

def tasks_for_event(event: Event) -> list[dict]:
    return [serialize_task(t) for t in sort_tasks(
        EventTask.query.filter_by(event_id=event.id).all())]


def tasks_page_data(user: User) -> dict:
    """Everything the Tasks page shows beyond the personal to-do list."""
    admin = bool(user.is_admin)
    linked = linked_event_ids(user)

    q = EventTask.query
    if not admin:
        cond = [EventTask.assigned_user_id == user.id]
        if linked:
            cond.append(EventTask.event_id.in_(linked))
        q = q.filter(or_(*cond))
    tasks = sort_tasks(q.all())

    mine = [serialize_task(t) for t in tasks if t.assigned_user_id == user.id]

    groups: dict[int, dict] = {}
    for t in tasks:
        if not t.event_id:
            continue
        # People not linked to the event only see the tasks given to them, not its whole list
        if not admin and t.event_id not in linked and t.assigned_user_id != user.id:
            continue
        g = groups.setdefault(t.event_id, {'event': t.event, 'tasks': []})
        g['tasks'].append(serialize_task(t))

    now = datetime.now()
    out = []
    for g in groups.values():
        ev = g['event']
        total, done = len(g['tasks']), sum(1 for t in g['tasks'] if t['done'])
        out.append({
            'id': ev.id, 'title': ev.title, 'date': ev.event_date,
            'upcoming': event_end(ev) >= now, 'tasks': g['tasks'],
            'total': total, 'done': done, 'can_manage': can_edit_event(ev),
        })
    # Upcoming events first (soonest first), then past ones (most recent first)
    out.sort(key=lambda g: (not g['upcoming'],
                            g['date'].timestamp() * (1 if g['upcoming'] else -1)))

    assigned_by_admin = []
    users = []
    if admin:
        assigned_by_admin = [serialize_task(t) for t in tasks if not t.event_id]
        users = [{'id': u.id, 'name': u.shown_name}
                 for u in sorted(User.query.filter(User.user_role.in_(['crew', 'staff']))
                                 .filter(or_(User.is_cast.is_(False), User.is_cast.is_(None))).all(),
                                 key=lambda u: u.shown_name.lower())]
    return {
        'today': datetime.now().strftime('%Y-%m-%d'),
        'mine': mine,
        'open_mine': sum(1 for t in mine if not t['done']),
        'groups': out,
        'assigned': assigned_by_admin,
        'users': users,
        # what the admin's "assign a task" / edit dialogs need
        'admin_json': {'users': users, 'tasks': {t['id']: t for t in assigned_by_admin}},
    }
