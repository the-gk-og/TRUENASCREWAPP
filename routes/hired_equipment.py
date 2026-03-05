"""routes/hired_equipment.py — Hired / rented equipment tracking."""

import io
import csv
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import HiredEquipment, HiredEquipmentCheckItem, Event
from decorators import crew_required

hired_equipment_bp = Blueprint('hired_equipment', __name__)


def _upcoming_threshold():
    return datetime.now() + timedelta(days=7)


def _hired_to_dict(item):
    return {
        'id':          item.id,
        'name':        item.name,
        'supplier':    item.supplier or '',
        'hire_date':   item.hire_date.isoformat(),
        'return_date': item.return_date.isoformat(),
        'cost':        item.cost or '',
        'quantity':    item.quantity or 1,
        'notes':       item.notes or '',
        'is_returned': item.is_returned,
        'event_id':    item.event_id,
    }


@hired_equipment_bp.route('/hired-equipment')
@login_required
@crew_required
def hired_equipment_list():
    active_hired   = HiredEquipment.query.filter_by(is_returned=False).order_by(HiredEquipment.return_date).all()
    returned_hired = HiredEquipment.query.filter_by(is_returned=True).order_by(HiredEquipment.return_date.desc()).all()
    events         = Event.query.order_by(Event.event_date.desc()).all()
    all_hired      = active_hired + returned_hired
    return render_template(
        'crew/hired_equipment.html',
        active_hired=active_hired,
        returned_hired=returned_hired,
        events=events,
        upcoming_threshold=_upcoming_threshold(),
        hired_json=[_hired_to_dict(h) for h in all_hired],
        now=datetime.now(),
    )


@hired_equipment_bp.route('/hired-equipment/add', methods=['POST'])
@login_required
@crew_required
def add_hired_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    try:
        item = HiredEquipment(
            name=data['name'],
            supplier=data.get('supplier', ''),
            hire_date=datetime.fromisoformat(data['hire_date']),
            return_date=datetime.fromisoformat(data['return_date']),
            cost=data.get('cost'),
            quantity=data.get('quantity', 1),
            notes=data.get('notes', ''),
            event_id=data.get('event_id') or None,
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({'success': True, 'id': item.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@hired_equipment_bp.route('/hired-equipment/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_hired_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = HiredEquipment.query.get_or_404(id)
    data = request.json
    try:
        if 'name'        in data: item.name        = data['name']
        if 'supplier'    in data: item.supplier     = data['supplier']
        if 'hire_date'   in data: item.hire_date    = datetime.fromisoformat(data['hire_date'])
        if 'return_date' in data: item.return_date  = datetime.fromisoformat(data['return_date'])
        if 'cost'        in data: item.cost         = data['cost']
        if 'quantity'    in data: item.quantity     = data['quantity']
        if 'notes'       in data: item.notes        = data['notes']
        if 'event_id'    in data: item.event_id     = data['event_id'] or None
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@hired_equipment_bp.route('/hired-equipment/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_hired_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = HiredEquipment.query.get_or_404(id)
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@hired_equipment_bp.route('/hired-equipment/<int:id>/return', methods=['POST'])
@login_required
@crew_required
def mark_returned(id):
    item = HiredEquipment.query.get_or_404(id)
    item.is_returned = True
    item.returned_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Checklist  (model: HiredEquipmentCheckItem — fields: item_name, is_checked, notes)
# ---------------------------------------------------------------------------

@hired_equipment_bp.route('/hired-equipment/<int:hired_id>/checklist')
@login_required
@crew_required
def get_checklist(hired_id):
    HiredEquipment.query.get_or_404(hired_id)
    items = (
        HiredEquipmentCheckItem.query
        .filter_by(hired_equipment_id=hired_id)
        .order_by(HiredEquipmentCheckItem.id)
        .all()
    )
    return jsonify({'items': [
        {'id': i.id, 'label': i.item_name, 'is_checked': i.is_checked, 'notes': i.notes}
        for i in items
    ]})


@hired_equipment_bp.route('/hired-equipment/<int:hired_id>/checklist/add', methods=['POST'])
@login_required
@crew_required
def add_checklist_item(hired_id):
    HiredEquipment.query.get_or_404(hired_id)
    label = (request.json.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'Label is required'}), 400
    item = HiredEquipmentCheckItem(hired_equipment_id=hired_id, item_name=label)
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id})


@hired_equipment_bp.route('/hired-equipment/<int:hired_id>/checklist/toggle/<int:item_id>', methods=['POST'])
@login_required
@crew_required
def toggle_checklist_item(hired_id, item_id):
    item = HiredEquipmentCheckItem.query.filter_by(
        id=item_id, hired_equipment_id=hired_id
    ).first_or_404()
    item.is_checked = not item.is_checked
    db.session.commit()
    return jsonify({'success': True, 'is_checked': item.is_checked})


@hired_equipment_bp.route('/hired-equipment/<int:hired_id>/checklist/<int:item_id>', methods=['DELETE'])
@login_required
@crew_required
def delete_checklist_item(hired_id, item_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = HiredEquipmentCheckItem.query.filter_by(
        id=item_id, hired_equipment_id=hired_id
    ).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Bulk delete
# ---------------------------------------------------------------------------

@hired_equipment_bp.route('/hired-equipment/bulk-delete', methods=['POST'])
@login_required
@crew_required
def bulk_delete_hired_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    ids = request.json.get('ids', [])
    if not ids:
        return jsonify({'error': 'No IDs provided'}), 400
    try:
        HiredEquipment.query.filter(HiredEquipment.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'success': True, 'deleted': len(ids)})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@hired_equipment_bp.route('/hired-equipment/import-csv', methods=['POST'])
@login_required
@crew_required
def import_hired_csv():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        stream = io.StringIO(request.files['file'].stream.read().decode('utf-8'), newline=None)
        reader = csv.DictReader(stream)
        count  = 0
        for row in reader:
            name        = row.get('name')        or row.get('Name')
            hire_date   = row.get('hire_date')   or row.get('Hire Date')
            return_date = row.get('return_date') or row.get('Return Date')
            if not (name and hire_date and return_date):
                continue
            try:
                db.session.add(HiredEquipment(
                    name=name,
                    supplier=row.get('supplier') or row.get('Supplier') or '',
                    hire_date=datetime.fromisoformat(hire_date),
                    return_date=datetime.fromisoformat(return_date),
                    cost=row.get('cost') or row.get('Cost') or None,
                    notes=row.get('notes') or row.get('Notes') or '',
                ))
                count += 1
            except Exception:
                continue
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'Import failed: {exc}'}), 400