"""routes/picklist.py — Pick list item management."""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Event, PickListItem, Equipment, HiredEquipment, Picklist
from decorators import crew_required
from routes import _is_mobile

picklist_bp = Blueprint('picklist', __name__)


@picklist_bp.route('/picklist')
@login_required
@crew_required
def picklist():
    event_id = request.args.get('event_id')
    event    = Event.query.get(event_id) if event_id else None
    items    = PickListItem.query.filter_by(event_id=event_id, is_archived=False).all() if event_id \
               else PickListItem.query.filter_by(event_id=None, is_archived=False).all()
    events          = Event.query.order_by(Event.event_date.desc()).all()
    all_equipment   = Equipment.query.all()
    hired_equipment = HiredEquipment.query.filter_by(is_returned=False).order_by(HiredEquipment.return_date).all()
    picklists       = Picklist.query.filter_by(event_id=event_id, is_archived=False).all() if event_id else []

    template = '/crew/picklist_mobile.html' if _is_mobile(request.user_agent.string) else '/crew/picklist.html'

    return render_template(
        template,
        items=items,
        events=events,
        current_event=event,
        all_equipment=all_equipment,
        all_equipment_json=[e.to_dict() for e in all_equipment],
        equipment_json=[e.to_dict() for e in all_equipment],
        hired_equipment=hired_equipment,
        picklists=picklists,
    )


# ---------------------------------------------------------------------------
# Picklist Group Management
# ---------------------------------------------------------------------------

@picklist_bp.route('/picklists/create', methods=['POST'])
@login_required
@crew_required
def create_picklist():
    """Create a new picklist group."""
    data = request.json
    event_id = data.get('event_id')
    name = data.get('name', '')
    
    if not event_id or not name:
        return jsonify({'error': 'Event ID and name are required'}), 400
    
    Event.query.get_or_404(event_id)
    
    picklist = Picklist(
        name=name,
        event_id=event_id,
        created_by=current_user.username
    )
    db.session.add(picklist)
    db.session.commit()
    
    return jsonify({'success': True, 'id': picklist.id, 'name': picklist.name})


@picklist_bp.route('/picklists/<int:picklist_id>/items', methods=['GET'])
@login_required
@crew_required
def get_picklist_items(picklist_id):
    """Get items in a picklist."""
    picklist = Picklist.query.get_or_404(picklist_id)
    items = PickListItem.query.filter_by(picklist_id=picklist_id, is_archived=False).all()
    
    return jsonify({
        'success': True,
        'picklist': {
            'id': picklist.id,
            'name': picklist.name,
            'event_id': picklist.event_id,
            'created_by': picklist.created_by,
        },
        'items': [
            {
                'id': item.id,
                'item_name': item.item_name,
                'quantity': item.quantity,
                'is_checked': item.is_checked,
                'added_by': item.added_by,
                'equipment_id': item.equipment_id,
            }
            for item in items
        ]
    })


@picklist_bp.route('/picklists/<int:picklist_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_picklist(picklist_id):
    """Delete a picklist group."""
    picklist = Picklist.query.get_or_404(picklist_id)
    db.session.delete(picklist)
    db.session.commit()
    return jsonify({'success': True})


@picklist_bp.route('/picklists/<int:picklist_id>/archive', methods=['PUT'])
@login_required
@crew_required
def archive_picklist_group(picklist_id):
    """Archive a picklist group and its items."""
    picklist = Picklist.query.get_or_404(picklist_id)
    picklist.is_archived = not picklist.is_archived
    
    # Also archive items in this picklist
    for item in picklist.items:
        item.is_archived = picklist.is_archived
    
    db.session.commit()
    return jsonify({'success': True, 'is_archived': picklist.is_archived})


# ---------------------------------------------------------------------------
# Picklist Items
# ---------------------------------------------------------------------------

@picklist_bp.route('/picklist/add', methods=['POST'])
@login_required
@crew_required
def add_picklist_item():
    data         = request.json
    equipment_id = data.get('equipment_id')
    picklist_id  = data.get('picklist_id')
    
    if equipment_id:
        eq = Equipment.query.get(equipment_id)
        if not eq:
            return jsonify({'error': 'Equipment not found'}), 404
        item = PickListItem(item_name=eq.name, quantity=data.get('quantity', 1),
                            added_by=current_user.username, event_id=data.get('event_id'),
                            picklist_id=picklist_id, equipment_id=equipment_id)
    else:
        item = PickListItem(item_name=data['item_name'], quantity=data.get('quantity', 1),
                            added_by=current_user.username, event_id=data.get('event_id'),
                            picklist_id=picklist_id)
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