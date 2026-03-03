"""routes/cast.py — Cast members, scheduling, notes, cast portal."""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db
from models import Event, CastMember, CastSchedule, CastNote, User
from decorators import crew_required
from services.email_service import send_cast_assignment_email, send_cast_welcome_email

cast_bp = Blueprint('cast', __name__)


@cast_bp.route('/cast')
@login_required
@crew_required
def cast_list():
    cast_members = CastMember.query.order_by(CastMember.character_name).all()
    events       = Event.query.order_by(Event.event_date.desc()).all()
    cast_json    = [{
        'id': c.id, 'actor_name': c.actor_name, 'character_name': c.character_name,
        'role_type': c.role_type, 'contact_email': c.contact_email,
        'contact_phone': c.contact_phone, 'notes': c.notes, 'event_id': c.event_id,
    } for c in cast_members]
    return render_template('/cast/cast.html', cast_members=cast_members,
                           events=events, cast_json=cast_json)


@cast_bp.route('/cast-events')
@login_required
def cast_events():
    if not current_user.is_cast and not current_user.is_admin:
        flash('Cast access required')
        return redirect(url_for('crew.dashboard'))
    if current_user.is_admin:
        events = Event.query.order_by(Event.event_date).all()
    else:
        events = Event.query.join(CastMember).filter(
            CastMember.user_id == current_user.id
        ).order_by(Event.event_date).all()
    return render_template('/cast/cast_events.html', events=events, now=datetime.now())


@cast_bp.route('/cast-events/<int:id>')
@login_required
def cast_event_detail(id):
    if not current_user.is_cast and not current_user.is_admin:
        flash('Cast access required')
        return redirect(url_for('crew.dashboard'))
    event = Event.query.get_or_404(id)
    if not current_user.is_admin:
        cast_member = CastMember.query.filter_by(event_id=id, user_id=current_user.id).first()
        if not cast_member:
            flash('You are not cast in this event')
            return redirect(url_for('cast.cast_events'))
    else:
        cast_member = None
    cast_schedules = CastSchedule.query.filter_by(event_id=id).order_by(CastSchedule.scheduled_time).all()
    cast_notes     = CastNote.query.filter_by(event_id=id).order_by(CastNote.created_at.desc()).all()
    cast_members   = CastMember.query.filter_by(event_id=id).all()
    return render_template('/cast/cast_event_detail.html',
                           event=event, cast_member=cast_member,
                           cast_schedules=cast_schedules,
                           cast_notes=cast_notes, cast_members=cast_members)


@cast_bp.route('/cast/add', methods=['POST'])
@login_required
def add_cast():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    user = (User.query.get(data['user_id']) if data.get('user_id')
            else User.query.filter_by(username=data.get('actor_name')).first())
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if not user.is_cast:
        user.is_cast = True
    cast = CastMember(
        actor_name=user.username, character_name=data['character_name'],
        role_type=data.get('role_type', 'lead'),
        contact_email=data.get('contact_email') or user.email,
        contact_phone=data.get('contact_phone'),
        notes=data.get('notes', ''),
        event_id=data.get('event_id'), user_id=user.id,
    )
    db.session.add(cast)
    db.session.commit()
    if cast.event_id and user.email:
        event = Event.query.get(cast.event_id)
        if event:
            send_cast_assignment_email(
                recipient_email=user.email, username=user.username,
                event_title=event.title,
                event_date=event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                event_location=event.location or 'TBD',
                character_name=cast.character_name, role_type=cast.role_type,
            )
    return jsonify({'success': True, 'id': cast.id})


@cast_bp.route('/cast/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_cast(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    cast = CastMember.query.get_or_404(id)
    data = request.json
    for f in ('actor_name', 'character_name', 'role_type', 'contact_email',
              'contact_phone', 'notes', 'event_id'):
        setattr(cast, f, data.get(f, getattr(cast, f)))
    db.session.commit()
    return jsonify({'success': True})


@cast_bp.route('/cast/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_cast(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    cast = CastMember.query.get_or_404(id)
    db.session.delete(cast)
    db.session.commit()
    return jsonify({'success': True})


@cast_bp.route('/cast/create-account', methods=['POST'])
@login_required
@crew_required
def create_cast_account():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data     = request.json
    username = data.get('username')
    password = data.get('password')
    email    = data.get('email')
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    user = User(username=username, password_hash=generate_password_hash(password),
                email=email, is_cast=True, is_admin=False)
    db.session.add(user)
    db.session.commit()
    if email:
        send_cast_welcome_email(recipient_email=email, username=username, password=password)
    return jsonify({'success': True, 'user_id': user.id, 'username': username})


@cast_bp.route('/cast/users')
@login_required
def get_cast_users():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    cast_users = User.query.filter_by(is_cast=True).all()
    return jsonify({'users': [{'id': u.id, 'username': u.username, 'email': u.email}
                               for u in cast_users]})


# Cast schedules
@cast_bp.route('/events/<int:event_id>/cast-schedule/add', methods=['POST'])
@login_required
def add_cast_schedule(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    try:
        s = CastSchedule(
            event_id=event_id, title=data.get('title', ''),
            scheduled_time=datetime.fromisoformat(data['scheduled_time']),
            description=data.get('description', ''),
        )
        db.session.add(s)
        db.session.commit()
        return jsonify({'success': True, 'id': s.id,
                        'scheduled_time': s.scheduled_time.isoformat()})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@cast_bp.route('/events/cast-schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_schedule(schedule_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    s = CastSchedule.query.get_or_404(schedule_id)
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})


# Cast notes
@cast_bp.route('/events/<int:event_id>/cast-notes/add', methods=['POST'])
@login_required
def add_cast_note(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    note = CastNote(event_id=event_id, content=data['content'],
                    created_by=current_user.username)
    db.session.add(note)
    db.session.commit()
    return jsonify({'success': True, 'id': note.id, 'note': {
        'id': note.id, 'content': note.content, 'created_by': note.created_by,
        'created_at': note.created_at.strftime('%b %d, %Y at %I:%M %p'),
    }})


@cast_bp.route('/events/cast-notes/<int:note_id>/edit', methods=['PUT'])
@login_required
def edit_cast_note(note_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    note = CastNote.query.get_or_404(note_id)
    note.content    = request.json['content']
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


@cast_bp.route('/events/cast-notes/<int:note_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_note(note_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    note = CastNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    return jsonify({'success': True})


@cast_bp.route('/events/<int:id>/edit-cast', methods=['PUT'])
@login_required
def edit_event_cast(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    event = Event.query.get_or_404(id)
    event.cast_description = request.json.get('cast_description', event.cast_description)
    db.session.commit()
    return jsonify({'success': True})
