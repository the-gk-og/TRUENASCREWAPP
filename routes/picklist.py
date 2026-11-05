"""routes/picklist.py — Pick list item management."""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Event, PickListItem, PickListUnit, Equipment, EquipmentUnit, HiredEquipment
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

    # Units that can be allocated, for each item type on this list that tracks units
    unit_options = {}
    for it in items:
        if it.equipment and it.equipment.units and it.equipment_id not in unit_options:
            unit_options[it.equipment_id] = [u.to_dict() for u in it.equipment.units]

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
        unit_options=unit_options,
        item_units={it.id: [_unit_chip(u) for u in it.units] for it in items},
    )


def _unit_chip(unit):
    return {'id': unit.id, 'asset_tag': unit.asset_tag}


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
    units = {}
    if rows:
        for item_id, unit_id, tag in db.session.query(
                PickListUnit.pick_list_item_id, EquipmentUnit.id, EquipmentUnit.asset_tag
        ).join(EquipmentUnit, EquipmentUnit.id == PickListUnit.unit_id).filter(
                PickListUnit.pick_list_item_id.in_([r[0] for r in rows])
        ).order_by(PickListUnit.id).all():
            units.setdefault(item_id, []).append({'id': unit_id, 'asset_tag': tag})
    resp = jsonify({'items': [{'id': i, 'checked': bool(c), 'units': units.get(i, [])}
                              for i, c in rows]})
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


# ---------------------------------------------------------------------------
# Which physical units are allocated to a pick list line
# ---------------------------------------------------------------------------

@picklist_bp.route('/picklist/<int:item_id>/units', methods=['POST'])
@login_required
@crew_required
def assign_unit(item_id):
    """Allocate one unit to a pick list line. Body: {unit_id} or {asset_tag}
    (so a scanned/typed tag works), plus force=true to override a clash."""
    item = PickListItem.query.get_or_404(item_id)
    data = request.get_json(silent=True) or {}
    if not item.equipment_id:
        return jsonify({'error': 'This line is not linked to an equipment item'}), 400

    unit = None
    if data.get('unit_id'):
        unit = db.session.get(EquipmentUnit, int(data['unit_id']))
    elif data.get('asset_tag'):
        from routes.equipment import _unit_by_tag
        unit = _unit_by_tag(data['asset_tag'])
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    if unit.equipment_id != item.equipment_id:
        return jsonify({'error': f'{unit.asset_tag} is a {unit.equipment.name}, '
                                 f'not a {item.equipment.name}'}), 400
    if any(l.unit_id == unit.id for l in item.unit_links):
        return jsonify({'error': f'{unit.asset_tag} is already on this line'}), 409
    if len(item.unit_links) >= (item.quantity or 1):
        return jsonify({'error': f'This line is for {item.quantity or 1}; '
                                 'remove a unit or raise the quantity first'}), 400

    force = bool(data.get('force'))
    if unit.status in ('retired', 'lost') or (unit.status == 'repair' and not force):
        return jsonify({'error': f'{unit.asset_tag} is marked {unit.status}',
                        'conflict': 'status', 'can_force': unit.status == 'repair'}), 409
    clashes = [a for a in unit.allocations() if a['pick_list_item_id'] != item.id]
    if clashes and not force:
        where = ', '.join(a['event_title'] for a in clashes)
        return jsonify({'error': f'{unit.asset_tag} is already allocated to {where}',
                        'conflict': 'allocated', 'can_force': True,
                        'allocations': clashes}), 409

    db.session.add(PickListUnit(pick_list_item_id=item.id, unit_id=unit.id,
                                assigned_by=current_user.username))
    db.session.commit()
    return jsonify({'success': True, 'units': [_unit_chip(u) for u in item.units]})


@picklist_bp.route('/picklist/<int:item_id>/units/<int:unit_id>', methods=['DELETE'])
@login_required
@crew_required
def unassign_unit(item_id, unit_id):
    item = PickListItem.query.get_or_404(item_id)
    link = PickListUnit.query.filter_by(pick_list_item_id=item.id, unit_id=unit_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    return jsonify({'success': True, 'units': [_unit_chip(u) for u in item.units]})
