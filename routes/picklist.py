"""routes/picklist.py — Pick list item management."""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Event, PickListItem, Equipment, HiredEquipment
from decorators import crew_required
from routes import _is_mobile

picklist_bp = Blueprint('picklist', __name__)


def _event_is_archived(event, now=None):
    """An event's pick list is archived once the event has finished.

    Uses the end date when there is one, otherwise the start date. All-day
    events stay current until the end of that day. Times in this app are
    naive local time, so datetime.now() is the right comparison.
    """
    now = now or datetime.now()
    ref = event.event_end_date or event.event_date
    if ref is None:
        return False
    if event.all_day:
        return ref.date() < now.date()
    return ref < now


def _split_events(now=None):
    """Return (current, archived). Current: soonest first. Archived: newest first."""
    now = now or datetime.now()
    events = Event.query.order_by(Event.event_date.asc()).all()
    current  = [e for e in events if not _event_is_archived(e, now)]
    archived = [e for e in events if _event_is_archived(e, now)]
    archived.sort(key=lambda e: e.event_date, reverse=True)
    return current, archived


def _event_summary(event, archived):
    return {
        'id':       event.id,
        'title':    event.title,
        'date':     event.event_date.strftime('%d %b %Y, %H:%M'),
        'date_short': event.event_date.strftime('%d %b %Y'),
        'location': event.location or '',
        'archived': archived,
    }


@picklist_bp.route('/picklist')
@login_required
@crew_required
def picklist():
    event_id = request.args.get('event_id', type=int)
    event    = Event.query.get(event_id) if event_id else None
    items    = PickListItem.query.filter_by(event_id=event_id).order_by(PickListItem.id).all() if event_id \
               else PickListItem.query.filter_by(event_id=None).order_by(PickListItem.id).all()

    current_events, archived_events = _split_events()

    # Add-item dropdowns only offer current events (plus the one being viewed, even if archived)
    events = list(current_events)
    if event and event not in events:
        events.append(event)

    all_equipment   = Equipment.query.all()
    hired_equipment = HiredEquipment.query.filter_by(is_returned=False).order_by(HiredEquipment.return_date).all()

    template = '/crew/picklist_mobile.html' if _is_mobile(request.user_agent.string) else '/crew/picklist.html'

    return render_template(
        template,
        items=items,
        events=events,
        current_events=current_events,
        archived_events=archived_events,
        current_event=event,
        current_event_archived=bool(event and _event_is_archived(event)),
        all_equipment=all_equipment,
        all_equipment_json=[e.to_dict() for e in all_equipment],
        equipment_json=[e.to_dict() for e in all_equipment],
        hired_equipment=hired_equipment,
    )


@picklist_bp.route('/picklist/search')
@login_required
@crew_required
def search_picklists():
    """Search pick lists by event title, location, date or item name.

    Current events come first (soonest first), then archived ones (newest first).
    """
    q = (request.args.get('q') or '').strip().lower()
    current_events, archived_events = _split_events()
    if not q:
        return jsonify({'results': [_event_summary(e, False) for e in current_events] +
                                   [_event_summary(e, True)  for e in archived_events]})

    # event_id -> lower-cased item names, in one query
    names = {}
    for ev_id, name in db.session.query(PickListItem.event_id, PickListItem.item_name).all():
        names.setdefault(ev_id, []).append((name or '').lower())

    def matches(e):
        hay = ' '.join([
            (e.title or '').lower(),
            (e.location or '').lower(),
            e.event_date.strftime('%d %b %Y %B %Y %Y-%m-%d').lower(),
        ])
        if all(tok in hay for tok in q.split()):
            return True
        return any(q in n for n in names.get(e.id, []))

    results  = [_event_summary(e, False) for e in current_events  if matches(e)]
    results += [_event_summary(e, True)  for e in archived_events if matches(e)]
    return jsonify({'results': results})


@picklist_bp.route('/picklist/state')
@login_required
@crew_required
def picklist_state():
    """Lightweight snapshot of one list, polled by the page so everyone sees live changes."""
    event_id = request.args.get('event_id', type=int)
    rows = PickListItem.query.filter_by(event_id=event_id).with_entities(
        PickListItem.id, PickListItem.is_checked).all()
    resp = jsonify({'items': [{'id': i, 'checked': bool(c)} for i, c in rows]})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@picklist_bp.route('/picklist/add', methods=['POST'])
@login_required
@crew_required
def add_picklist_item():
    data         = request.json
    equipment_id = data.get('equipment_id')
    if equipment_id:
        eq = Equipment.query.get(equipment_id)
        if not eq:
            return jsonify({'error': 'Equipment not found'}), 404
        item = PickListItem(item_name=eq.name, quantity=data.get('quantity', 1),
                            added_by=current_user.username, event_id=data.get('event_id'),
                            equipment_id=equipment_id)
    else:
        item = PickListItem(item_name=data['item_name'], quantity=data.get('quantity', 1),
                            added_by=current_user.username, event_id=data.get('event_id'))
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id})


@picklist_bp.route('/picklist/toggle/<int:id>', methods=['POST'])
@login_required
@crew_required
def toggle_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    if 'checked' in data:
        # Explicit state: two people tapping at once can't undo each other
        item.is_checked = bool(data['checked'])
    else:
        item.is_checked = not item.is_checked
    db.session.commit()
    return jsonify({'success': True, 'is_checked': item.is_checked})


@picklist_bp.route('/picklist/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})