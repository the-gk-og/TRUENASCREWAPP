"""routes/discord.py — Discord bot integration endpoints."""

import os
from datetime import datetime
from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models import User, Event, CrewAssignment, Equipment, PickListItem

discord_bp = Blueprint('discord', __name__)
DISCORD_BOT_SECRET = os.environ.get('DISCORD_BOT_SECRET', 'change-this-secret')

def _auth(data):
    return data.get('secret') == DISCORD_BOT_SECRET

@discord_bp.route('/discord/join-event', methods=['POST'])
def discord_join_event():
    data = request.json
    if not _auth(data): return jsonify({'error': 'Unauthorized'}), 401
    event = Event.query.get(data.get('event_id'))
    if not event: return jsonify({'error': 'Event not found'}), 404
    user  = User.query.filter_by(discord_id=data.get('discord_id')).first()
    if not user: return jsonify({'error': 'Discord account not linked'}), 400
    if CrewAssignment.query.filter_by(event_id=event.id, crew_member=user.username).first():
        return jsonify({'error': 'Already assigned'}), 400
    db.session.add(CrewAssignment(event_id=event.id, crew_member=user.username, assigned_via='discord'))
    db.session.commit()
    return jsonify({'success': True})

@discord_bp.route('/discord/leave-event', methods=['POST'])
def discord_leave_event():
    data = request.json
    if not _auth(data): return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.filter_by(discord_id=data.get('discord_id')).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    assignment = CrewAssignment.query.filter_by(event_id=data.get('event_id'), crew_member=user.username).first()
    if assignment:
        db.session.delete(assignment)
        db.session.commit()
    return jsonify({'success': True})

@discord_bp.route('/discord/link-existing', methods=['POST'])
def discord_link_existing():
    data = request.json
    if not _auth(data): return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.filter_by(username=data.get('username')).first()
    if not user or not check_password_hash(user.password_hash, data.get('password', '')):
        return jsonify({'error': 'Invalid username or password'}), 401
    user.discord_id       = data.get('discord_id')
    user.discord_username = data.get('discord_username')
    db.session.commit()
    return jsonify({'success': True, 'username': user.username})

@discord_bp.route('/discord/check-link/<discord_id>')
def discord_check_link(discord_id):
    user = User.query.filter_by(discord_id=discord_id).first()
    if user:
        return jsonify({'linked': True, 'username': user.username,
                        'event_count': CrewAssignment.query.filter_by(crew_member=user.username).count()})
    return jsonify({'linked': False}), 404

@discord_bp.route('/discord/user-events/<discord_id>')
def discord_user_events(discord_id):
    user = User.query.filter_by(discord_id=discord_id).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    events = []
    for a in CrewAssignment.query.filter_by(crew_member=user.username).all():
        event = Event.query.get(a.event_id)
        if event:
            events.append({'id': event.id, 'title': event.title,
                           'date': event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                           'location': event.location or 'TBD', 'role': a.role or 'Crew Member'})
    return jsonify({'events': events})

@discord_bp.route('/discord/list-events')
def discord_list_events():
    events = Event.query.filter(Event.event_date >= datetime.now()).order_by(Event.event_date).limit(10).all()
    return jsonify({'events': [{'id': e.id, 'title': e.title,
                                'date': e.event_date.strftime('%B %d, %Y at %I:%M %p'),
                                'location': e.location or 'TBD',
                                'crew_count': len(e.crew_assignments)} for e in events]})

@discord_bp.route('/discord/event-crew/<int:event_id>')
def discord_event_crew(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify({'event_title': event.title,
                    'crew': [{'name': a.crew_member, 'role': a.role or 'Crew Member'}
                             for a in event.crew_assignments]})

@discord_bp.route('/discord/add-event', methods=['POST'])
def discord_add_event():
    data = request.json
    if not _auth(data): return jsonify({'error': 'Unauthorized'}), 401
    try:
        event_date = datetime.strptime(data['date'], '%Y-%m-%d %H:%M')
        event      = Event(title=data['title'], event_date=event_date,
                           location=data.get('location', 'TBD'), created_by='Discord Bot')
        db.session.add(event)
        db.session.commit()
        return jsonify({'success': True, 'event_id': event.id})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400

@discord_bp.route('/discord/create-account', methods=['POST'])
def discord_create_account():
    data = request.json
    if not _auth(data): return jsonify({'error': 'Unauthorized'}), 401
    username = data.get('username')
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    user = User(username=username, password_hash=generate_password_hash(data.get('password', '')), is_admin=False)
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'username': username})

@discord_bp.route('/discord/search-equipment/<query>')
def discord_search_equipment(query):
    items = Equipment.query.filter(
        (Equipment.name.contains(query)) | (Equipment.barcode.contains(query))
    ).limit(10).all()
    return jsonify({'equipment': [e.to_dict() for e in items]})

@discord_bp.route('/discord/pick-list/<int:event_id>')
def discord_pick_list(event_id):
    event = Event.query.get_or_404(event_id)
    items = PickListItem.query.filter_by(event_id=event_id).all()
    return jsonify({'event_title': event.title, 'items': [{
        'id': i.id, 'name': i.item_name, 'quantity': i.quantity, 'is_checked': i.is_checked,
        'location': i.equipment.location if i.equipment else 'N/A',
        'category': i.equipment.category if i.equipment else 'N/A',
    } for i in items]})
