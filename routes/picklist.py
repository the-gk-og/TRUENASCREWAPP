"""routes/picklist.py — Pick list item management."""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Event, PickListItem, Equipment, HiredEquipment
from decorators import crew_required

picklist_bp = Blueprint('picklist', __name__)


@picklist_bp.route('/picklist')
@login_required
@crew_required
def picklist():
    event_id = request.args.get('event_id')
    event    = Event.query.get(event_id) if event_id else None
    items    = PickListItem.query.filter_by(event_id=event_id).all() if event_id \
               else PickListItem.query.filter_by(event_id=None).all()
    events        = Event.query.order_by(Event.event_date.desc()).all()
    all_equipment = Equipment.query.all()
    hired_equipment = HiredEquipment.query.filter_by(is_returned=False).order_by(HiredEquipment.return_date).all()
    return render_template('/crew/picklist.html',
                           items=items, events=events, current_event=event,
                           all_equipment=all_equipment,
                           all_equipment_json=[e.to_dict() for e in all_equipment],
                           hired_equipment=hired_equipment)


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
