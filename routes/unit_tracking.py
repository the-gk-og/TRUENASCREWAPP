"""routes/unit_tracking.py — scanning units out to events and back, and per-unit
maintenance history (repairs, inspections, PAT tests) with due dates.

Check-outs are explicit records (UnitCheckout): who scanned the unit out, to
which event, when, and who scanned it back. A pick list allocation (PickListUnit)
is the plan; a check-out is what actually left the building.
"""

import re
from datetime import date, datetime

import os

from flask import Blueprint, render_template, request, jsonify, abort, send_from_directory
from flask_login import login_required, current_user

from extensions import db
from models import (Equipment, EquipmentUnit, Event, PickListItem, PickListUnit,
                    UnitCheckout, UnitMaintenance, UnitQuarantine, BulkCheckout,
                    UNIT_STATUSES, UNIT_STATUS_LABELS, QUARANTINE_OUTCOMES,
                    MAINTENANCE_KINDS, MAINTENANCE_LABELS, MAINTENANCE_RESULTS,
                    latest_due_by_kind, due_state)
from decorators import crew_required

unit_tracking_bp = Blueprint('unit_tracking', __name__)

_UNIT_URL = re.compile(r'/equipment/unit/(\d+)')
_ITEM_URL = re.compile(r'/equipment/(\d+)(?:/view)?(?:[/?#]|$)')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_code(code):
    """What a scanned or typed code points at: ('unit', EquipmentUnit), ('type', Equipment)
    for a group label, or (None, error message)."""
    from routes.equipment import _unit_by_tag
    code = (code or '').strip()
    if not code:
        return None, 'Nothing scanned'
    m = _UNIT_URL.search(code)
    if m:
        unit = db.session.get(EquipmentUnit, int(m.group(1)))
        return ('unit', unit) if unit else (None, 'That item no longer exists')
    unit = _unit_by_tag(code)
    if unit:
        return 'unit', unit
    m = _ITEM_URL.search(code)
    item = (db.session.get(Equipment, int(m.group(1))) if m else
            Equipment.query.filter(db.func.lower(Equipment.barcode) == code.lower()).first())
    if item:
        return 'type', item
    return None, f'Nothing matches "{code}"'


def resolve_scan(code):
    """(unit, None) for an item label / asset tag, else (None, error message)."""
    kind, hit = resolve_code(code)
    if kind == 'unit':
        return hit, None
    if kind == 'type':
        return None, f'That is the group label for {hit.name}'
    return None, hit


def _unit_choice(unit, event=None):
    """A unit as offered in the "which one?" list after scanning a group label."""
    co = unit.open_checkout
    d = _unit_brief(unit)
    d['serial_number'] = unit.serial_number or ''
    d['out_event_id'] = co.event_id if co else None
    d['out_event_title'] = co.event.title if co and co.event else ''
    d['out_here'] = bool(co and event and co.event_id == event.id)
    d['allocated_here'] = bool(event and any(
        l.pick_list_item.event_id == event.id for l in unit.pick_links))
    return d


def quarantine_unit(unit, reason, event=None, photo=None):
    """Pull a unit out of use. Returns the new (or already open) UnitQuarantine."""
    existing = unit.open_quarantine
    if existing:
        return existing
    q = UnitQuarantine(unit_id=unit.id, reason=reason.strip(), photo=photo,
                       event_id=event.id if event else None,
                       quarantined_by=current_user.username, quarantined_at=_now())
    unit.quarantines.insert(0, q)
    unit.status = 'quarantined'
    return q


def open_quarantines(equipment_id=None):
    """Items waiting in quarantine, longest wait first."""
    q = UnitQuarantine.query.filter(UnitQuarantine.released_at.is_(None))
    if equipment_id:
        q = q.join(EquipmentUnit, EquipmentUnit.id == UnitQuarantine.unit_id) \
             .filter(EquipmentUnit.equipment_id == equipment_id)
    return [r.to_dict() for r in q.order_by(UnitQuarantine.quarantined_at.asc()).all()]


def _unit_brief(unit):
    return {
        'id':             unit.id,
        'asset_tag':      unit.asset_tag,
        'equipment_id':   unit.equipment_id,
        'equipment_name': unit.equipment.name if unit.equipment else '',
        'status':         unit.status or 'available',
        'status_label':   UNIT_STATUS_LABELS.get(unit.status or 'available', unit.status),
    }


def _event_brief(ev):
    from routes.picklist import _event_is_archived
    return {
        'id':       ev.id,
        'title':    ev.title,
        'date':     ev.event_date.strftime('%d %b %Y') if ev.event_date else '',
        'location': ev.location or '',
        'archived': _event_is_archived(ev),
    }


def _now():
    return datetime.now()       # naive local time, like the rest of the app


def _close(co, note=None):
    co.returned_at = _now()
    co.returned_by = current_user.username
    if note:
        co.notes = f'{co.notes}\n{note}' if co.notes else note


def _picklist_check(unit, event):
    """Compare a unit against the event's pick list. Allocates the unit to a
    matching line with room. Returns (warnings, info)."""
    lines = PickListItem.query.filter_by(event_id=event.id, equipment_id=unit.equipment_id) \
                              .order_by(PickListItem.id).all()
    if any(l.unit_id == unit.id for line in lines for l in line.unit_links):
        return [], None
    name = unit.equipment.name if unit.equipment else 'item'
    if not lines:
        return [{'code': 'not_on_picklist',
                 'message': f'{name} is not on the pick list for {event.title}'}], None
    for line in lines:
        if len(line.unit_links) < (line.quantity or 1):
            db.session.add(PickListUnit(pick_list_item_id=line.id, unit_id=unit.id,
                                        assigned_by=current_user.username))
            return [], f'Added {unit.asset_tag} to the pick list'
    need = sum(l.quantity or 1 for l in lines)
    return [{'code': 'not_allocated',
             'message': f'The pick list only needs {need} × {name}, and {unit.asset_tag} '
                        'is not one of the units allocated'}], None


# ---------------------------------------------------------------------------
# Check-out / return page
# ---------------------------------------------------------------------------

@unit_tracking_bp.route('/equipment/checkout')
@login_required
@crew_required
def checkout_page():
    from routes.picklist import _split_events
    current, archived = _split_events()
    event_id = request.args.get('event_id', type=int)
    event = db.session.get(Event, event_id) if event_id else None
    # Events that still have units out, even if they've finished
    out_event_ids = {eid for (eid,) in db.session.query(UnitCheckout.event_id)
                     .filter(UnitCheckout.returned_at.is_(None)).distinct()}
    stale = [e for e in archived if e.id in out_event_ids]
    return render_template(
        'crew/unit_checkout.html',
        event=_event_brief(event) if event else None,
        events=[_event_brief(e) for e in current],
        stale_events=[_event_brief(e) for e in stale],
        out_counts=_open_counts(),
    )


def _open_counts():
    return dict(db.session.query(UnitCheckout.event_id, db.func.count(UnitCheckout.id))
                .filter(UnitCheckout.returned_at.is_(None)).group_by(UnitCheckout.event_id).all())


@unit_tracking_bp.route('/equipment/checkout/event/<int:event_id>')
@login_required
@crew_required
def checkout_event_state(event_id):
    """What's out for an event, what came back, and what's planned but not out yet."""
    ev = Event.query.get_or_404(event_id)
    rows = UnitCheckout.query.filter_by(event_id=ev.id).order_by(UnitCheckout.checked_out_at.desc()).all()
    out      = [c.to_dict() for c in rows if c.returned_at is None]
    returned = [c.to_dict() for c in rows if c.returned_at is not None]
    out_ids  = {c['unit_id'] for c in out}

    expected = []
    lines = PickListItem.query.filter_by(event_id=ev.id).order_by(PickListItem.id).all()
    for line in lines:
        for link in line.unit_links:
            if link.unit_id not in out_ids:
                d = _unit_brief(link.unit)
                co = link.unit.open_checkout
                d['out_elsewhere'] = co.to_dict() if co else None
                expected.append(d)
    # Item types on the pick list with units, but not every unit picked yet
    unallocated = []
    for line in lines:
        if line.equipment_id and line.equipment and line.equipment.units:
            missing = (line.quantity or 1) - len(line.unit_links)
            if missing > 0:
                unallocated.append({'equipment_id': line.equipment_id,
                                    'equipment_name': line.equipment.name, 'missing': missing})
    bulk = BulkCheckout.query.filter_by(event_id=ev.id).order_by(BulkCheckout.checked_out_at.desc()).all()
    # Bulk types on the pick list that haven't gone out in full yet
    bulk_out_by_type = {}
    for b in bulk:
        bulk_out_by_type[b.equipment_id] = bulk_out_by_type.get(b.equipment_id, 0) + (b.quantity or 0)
    bulk_expected = []
    for line in lines:
        if line.equipment_id and line.equipment and not line.equipment.is_individual:
            taken = bulk_out_by_type.get(line.equipment_id, 0)
            use = min(taken, line.quantity or 1)
            bulk_out_by_type[line.equipment_id] = taken - use
            if (line.quantity or 1) - use > 0:
                bulk_expected.append({'equipment_id': line.equipment_id,
                                      'equipment_name': line.equipment.name,
                                      'missing': (line.quantity or 1) - use})
    resp = jsonify({'event': _event_brief(ev), 'out': out, 'returned': returned,
                    'expected': expected, 'unallocated': unallocated,
                    'bulk_out': [b.to_dict() for b in bulk if b.returned_at is None],
                    'bulk_returned': [b.to_dict() for b in bulk if b.returned_at is not None],
                    'bulk_expected': bulk_expected})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@unit_tracking_bp.route('/equipment/checkout/scan', methods=['POST'])
@login_required
@crew_required
def checkout_scan():
    """Body: {event_id, code | unit_id, mode: auto|out|return, force, damaged?, reason?}.

    auto: a unit already out to this event is returned, anything else is checked out.
    Scanning a group label answers 409 with conflict=choose_unit (individual types:
    the items to pick from) or conflict=choose_quantity (bulk types: how many are free);
    resend with unit_id, or use /equipment/checkout/bulk.
    Quarantined items never go out. Other problems that need a person to decide
    (in repair/retired/lost, out on another event) answer 409 with needs_confirm;
    resend with force=true. Softer problems (not on the pick list) still check out,
    with warnings. A return with damaged=true quarantines the item (reason required).
    """
    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'auto').lower()
    if mode not in ('auto', 'out', 'return'):
        return jsonify({'error': 'Unknown mode'}), 400
    force = bool(data.get('force'))

    event = db.session.get(Event, int(data['event_id'])) if data.get('event_id') else None

    if data.get('unit_id'):
        unit = db.session.get(EquipmentUnit, int(data['unit_id']))
        err = None if unit else 'Item not found'
    else:
        kind, hit = resolve_code(data.get('code'))
        unit, err = (hit, None) if kind == 'unit' else (None, hit)
        if kind == 'type':
            return _group_label_answer(hit, event)
    if not unit:
        return jsonify({'error': err, 'conflict': 'not_found'}), 404

    co = unit.open_checkout
    if event is None and mode != 'return':
        return jsonify({'error': 'Pick an event first'}), 400
    damaged = bool(data.get('damaged'))
    reason  = (data.get('reason') or '').strip()
    if damaged and not reason:
        return jsonify({'error': 'Say what is wrong with it'}), 400

    # ── Return ──────────────────────────────────────────────────────────────
    if mode == 'return' or (mode == 'auto' and co and event and co.event_id == event.id):
        if not co:
            return jsonify({'error': f'{unit.asset_tag} is not checked out', 'conflict': 'not_out',
                            'unit': _unit_brief(unit)}), 409
        warnings = []
        if event and co.event_id != event.id:
            warnings.append({'code': 'other_event',
                             'message': f'{unit.asset_tag} was out on {co.event.title}, not {event.title}'})
        _close(co)
        q = quarantine_unit(unit, reason, event=co.event) if damaged else None
        db.session.commit()
        return jsonify({'success': True, 'action': 'return', 'unit': _unit_brief(unit),
                        'checkout': co.to_dict(), 'warnings': warnings,
                        'quarantine': q.to_dict() if q else None,
                        'message': f'{unit.asset_tag} returned' + (' and quarantined' if q else '')})

    # ── Check out ───────────────────────────────────────────────────────────
    if co and co.event_id == event.id:
        return jsonify({'error': f'{unit.asset_tag} is already checked out to {event.title}',
                        'conflict': 'already_out', 'unit': _unit_brief(unit)}), 409

    if unit.status == 'quarantined':
        q = unit.open_quarantine
        why = f': {q.reason}' if q and q.reason else ''
        return jsonify({'error': f'{unit.asset_tag} is quarantined{why}. It can’t go out until an admin releases it',
                        'conflict': 'quarantined', 'unit': _unit_brief(unit),
                        'quarantine': q.to_dict() if q else None}), 409

    blockers = []
    if unit.status and unit.status != 'available':
        blockers.append({'code': 'status', 'message': f'{unit.asset_tag} is marked '
                                                      f'{UNIT_STATUS_LABELS.get(unit.status, unit.status).lower()}'})
    if co:
        blockers.append({'code': 'out_elsewhere',
                         'message': f'{unit.asset_tag} is still out on {co.event.title} '
                                    f'(since {co.checked_out_at.strftime("%d %b %H:%M")}, '
                                    f'by {co.checked_out_by or "unknown"})'})
    if blockers and not force:
        return jsonify({'error': '; '.join(b['message'] for b in blockers),
                        'conflict': blockers[0]['code'], 'needs_confirm': True,
                        'blockers': blockers, 'unit': _unit_brief(unit)}), 409

    if co:
        _close(co, note=f'Moved to {event.title} by {current_user.username}')
    warnings, info = _picklist_check(unit, event)
    warnings = blockers + warnings          # overridden blockers stay visible in the result
    new = UnitCheckout(unit_id=unit.id, event_id=event.id, checked_out_by=current_user.username,
                       checked_out_at=_now(),
                       notes=('Checked out despite: ' + '; '.join(b['message'] for b in blockers))
                             if blockers else None)
    db.session.add(new)
    db.session.commit()
    return jsonify({'success': True, 'action': 'out', 'unit': _unit_brief(unit),
                    'checkout': new.to_dict(), 'warnings': warnings, 'info': info,
                    'message': f'{unit.asset_tag} checked out to {event.title}'})


@unit_tracking_bp.route('/equipment/checkout/<int:cid>/return', methods=['POST'])
@login_required
@crew_required
def return_checkout(cid):
    """Body (optional): {damaged: true, reason} to quarantine the item as it comes back."""
    co = UnitCheckout.query.get_or_404(cid)
    if co.returned_at is not None:
        return jsonify({'error': 'Already returned'}), 409
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if data.get('damaged') and not reason:
        return jsonify({'error': 'Say what is wrong with it'}), 400
    _close(co)
    q = quarantine_unit(co.unit, reason, event=co.event) if data.get('damaged') else None
    db.session.commit()
    return jsonify({'success': True, 'checkout': co.to_dict(),
                    'quarantine': q.to_dict() if q else None})


def _group_label_answer(eq, event):
    """A group label was scanned on the check-out page: ask which item, or how many."""
    base = {'equipment': {'id': eq.id, 'name': eq.name, 'tracking': eq.tracking_mode}}
    if eq.is_individual:
        units = [_unit_choice(u, event) for u in eq.units if u.status not in ('retired', 'lost')]
        if not units:
            return jsonify({**base, 'error': f'{eq.name} has no items to check out',
                            'conflict': 'not_found'}), 404
        return jsonify({**base, 'error': f'That is the group label for {eq.name}. Which one?',
                        'conflict': 'choose_unit', 'units': units}), 409
    out_total = sum(b.outstanding for b in eq.bulk_checkouts if b.returned_at is None)
    out_here  = sum(b.outstanding for b in eq.bulk_checkouts
                    if b.returned_at is None and event and b.event_id == event.id)
    return jsonify({**base, 'error': f'How many {eq.name}?', 'conflict': 'choose_quantity',
                    'owned': eq.owned, 'available': max(0, eq.owned - out_total),
                    'out_here': out_here}), 409


# ---------------------------------------------------------------------------
# Bulk (count-only) types: check out and return by number
# ---------------------------------------------------------------------------

def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@unit_tracking_bp.route('/equipment/checkout/bulk', methods=['POST'])
@login_required
@crew_required
def bulk_checkout():
    """Body: {event_id, equipment_id, quantity, force?}. Taking more than is in
    storage answers 409 with needs_confirm (stock counts drift); resend with force."""
    data  = request.get_json(silent=True) or {}
    eq    = db.session.get(Equipment, _int(data.get('equipment_id'), 0))
    event = db.session.get(Event, _int(data.get('event_id'), 0))
    if not eq:
        return jsonify({'error': 'Equipment not found'}), 404
    if not event:
        return jsonify({'error': 'Pick an event first'}), 400
    if eq.is_individual:
        return jsonify({'error': f'{eq.name} is tracked item by item. Scan an item label'}), 400
    qty = _int(data.get('quantity'))
    if not qty or qty < 1:
        return jsonify({'error': 'Enter how many'}), 400
    out_total = sum(b.outstanding for b in eq.bulk_checkouts if b.returned_at is None)
    free = max(0, eq.owned - out_total)
    if qty > free and not data.get('force'):
        return jsonify({'error': f'Only {free} of {eq.owned} {eq.name} should be in storage',
                        'conflict': 'not_enough', 'needs_confirm': True, 'available': free}), 409
    b = BulkCheckout(equipment_id=eq.id, event_id=event.id, quantity=qty,
                     checked_out_by=current_user.username, checked_out_at=_now())
    db.session.add(b)
    db.session.commit()
    return jsonify({'success': True, 'action': 'out', 'checkout': b.to_dict(),
                    'message': f'{qty} × {eq.name} checked out to {event.title}'})


@unit_tracking_bp.route('/equipment/checkout/bulk/<int:bid>/return', methods=['POST'])
@login_required
@crew_required
def bulk_return(bid):
    """Body: {quantity?} (default: everything still out). The record closes once all
    of it is back; send {close: true} to close it short (the rest was used up or lost)."""
    b = BulkCheckout.query.get_or_404(bid)
    if b.returned_at is not None:
        return jsonify({'error': 'Already returned'}), 409
    data = request.get_json(silent=True) or {}
    qty = _int(data.get('quantity'), b.outstanding)
    if qty < 0 or qty > b.outstanding:
        return jsonify({'error': f'Only {b.outstanding} still out'}), 400
    b.quantity_returned = (b.quantity_returned or 0) + qty
    if b.quantity_returned >= b.quantity or data.get('close'):
        short = b.quantity - b.quantity_returned
        b.returned_at = _now()
        b.returned_by = current_user.username
        if short > 0:
            note = f'{short} not returned'
            b.notes = f'{b.notes}\n{note}' if b.notes else note
    db.session.commit()
    return jsonify({'success': True, 'checkout': b.to_dict()})


# ---------------------------------------------------------------------------
# Quarantine: pull a possibly damaged item out of use until an admin clears it
# ---------------------------------------------------------------------------

QUARANTINE_PICS_FOLDER = os.path.join('uploads', 'quarantine')
_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _save_quarantine_photo(file, unit_id):
    """Validated upload -> path relative to uploads/. Raises ValueError with a message."""
    name = file.filename or ''
    ext = name.rsplit('.', 1)[1].lower() if '.' in name else ''
    if ext not in _IMAGE_EXTS:
        raise ValueError('Photo must be a png, jpg, gif or webp image')
    from services.upload_security import is_real_image
    if not is_real_image(file):
        raise ValueError('That file is not a valid image')
    os.makedirs(QUARANTINE_PICS_FOLDER, exist_ok=True)
    filename = f'quarantine_{unit_id}_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.{ext}'
    file.save(os.path.join(QUARANTINE_PICS_FOLDER, filename))
    return f'quarantine/{filename}'


@unit_tracking_bp.route('/equipment/unit/<int:uid>/quarantine', methods=['POST'])
@login_required
@crew_required
def quarantine(uid):
    """Any crew member can quarantine an item. JSON {reason, event_id?} or a form with
    reason, an optional photo file and the event it came back damaged from."""
    u = EquipmentUnit.query.get_or_404(uid)
    data = request.form if request.form else (request.get_json(silent=True) or {})
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'Say what is wrong with it'}), 400
    if u.status == 'quarantined':
        return jsonify({'error': f'{u.asset_tag} is already quarantined'}), 409
    if u.status in ('retired', 'lost'):
        return jsonify({'error': f'{u.asset_tag} is marked {u.status}'}), 409
    photo = None
    file = request.files.get('photo')
    if file and file.filename:
        try:
            photo = _save_quarantine_photo(file, u.id)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    event = db.session.get(Event, _int(data.get('event_id'), 0)) if data.get('event_id') else None
    q = quarantine_unit(u, reason, event=event, photo=photo)
    db.session.commit()
    return jsonify({'success': True, 'quarantine': q.to_dict(), 'unit': _unit_brief(u)})


@unit_tracking_bp.route('/equipment/unit/<int:uid>/release', methods=['POST'])
@login_required
@crew_required
def release(uid):
    """Admin closes a quarantine. Body: {outcome: available|repair|retired, note,
    kind?: inspection|repair|pat, next_due?}. Putting an item back in service
    logs the inspection or repair that cleared it, so a note is required."""
    if not current_user.is_admin:
        return jsonify({'error': 'Only admins can release an item from quarantine'}), 403
    u = EquipmentUnit.query.get_or_404(uid)
    q = u.open_quarantine
    if u.status != 'quarantined' or not q:
        return jsonify({'error': f'{u.asset_tag} is not quarantined'}), 409
    data = request.get_json(silent=True) or {}
    outcome = (data.get('outcome') or 'available').strip().lower()
    if outcome not in QUARANTINE_OUTCOMES:
        return jsonify({'error': 'Unknown outcome'}), 400
    note = (data.get('note') or '').strip()
    rec = None
    if outcome == 'available':
        kind = (data.get('kind') or 'inspection').strip().lower()
        if kind not in MAINTENANCE_KINDS:
            return jsonify({'error': 'Unknown check type'}), 400
        if not note:
            return jsonify({'error': 'Say what was checked or fixed'}), 400
        try:
            next_due = _parse_date(data.get('next_due'), 'Next due date')
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        if next_due and next_due <= date.today():
            return jsonify({'error': 'Next due date must be in the future'}), 400
        rec = UnitMaintenance(unit_id=u.id, kind=kind, performed_on=date.today(),
                              result='repaired' if kind == 'repair' else 'pass',
                              performed_by=current_user.username, recorded_by=current_user.username,
                              notes=f'Released from quarantine ({q.reason}). {note}', next_due=next_due)
        db.session.add(rec)
    q.released_at  = _now()
    q.released_by  = current_user.username
    q.outcome      = outcome
    q.release_note = note or None
    u.status = outcome
    db.session.commit()
    return jsonify({'success': True, 'quarantine': q.to_dict(), 'unit': _unit_brief(u),
                    'record': rec.to_dict() if rec else None})


@unit_tracking_bp.route('/equipment/quarantine/<int:qid>/photo')
@login_required
@crew_required
def quarantine_photo(qid):
    q = UnitQuarantine.query.get_or_404(qid)
    if not q.photo:
        abort(404)
    folder, filename = os.path.split(q.photo)
    return send_from_directory(os.path.join(os.path.abspath('uploads'), folder), filename)


@unit_tracking_bp.route('/equipment/unit/<int:uid>/history')
@login_required
@crew_required
def unit_history(uid):
    u = EquipmentUnit.query.get_or_404(uid)
    return jsonify({'unit': _unit_brief(u),
                    'checkouts': [c.to_dict() for c in u.checkouts],
                    'maintenance': [m.to_dict() for m in u.maintenance],
                    'quarantines': [q.to_dict() for q in u.quarantines],
                    'timeline': unit_timeline(u),
                    'maintenance_due': u.maintenance_due()})


def unit_timeline(u):
    """Everything that has happened to one item, newest first: check-outs, returns,
    tests and repairs, quarantines and releases."""
    rows = []

    def add(when, kind, title, detail='', by='', sort=None, **extra):
        rows.append((sort or when or datetime.min, len(rows),
                     {'kind': kind, 'title': title, 'detail': detail, 'by': by or '',
                      'when': when.strftime('%d %b %Y, %H:%M') if isinstance(when, datetime) and (when.hour or when.minute)
                              else (when.strftime('%d %b %Y') if when else ''), **extra}))

    for c in u.checkouts:
        add(c.checked_out_at, 'out', f'Checked out to {c.event.title if c.event else "an event"}',
            by=c.checked_out_by)
        if c.returned_at:
            add(c.returned_at, 'return', f'Returned from {c.event.title if c.event else "an event"}',
                detail=c.notes or '', by=c.returned_by)
    for m in u.maintenance:
        when = datetime.combine(m.performed_on, datetime.min.time()) if m.performed_on else None
        add(when, 'maintenance', f'{MAINTENANCE_LABELS.get(m.kind, m.kind)}: {m.result}',
            detail=' · '.join(x for x in (m.notes, f'next due {m.next_due.strftime("%d %b %Y")}' if m.next_due else '') if x),
            by=m.performed_by, maintenance_id=m.id)
    for q in u.quarantines:
        d = q.to_dict()
        add(q.quarantined_at, 'quarantine', 'Quarantined', detail=q.reason or '', by=q.quarantined_by,
            photo_url=d['photo_url'],
            event_title=d['event_title'])
        if q.released_at:
            add(q.released_at, 'release', f'Quarantine closed: {QUARANTINE_OUTCOMES.get(q.outcome, q.outcome or "released")}',
                detail=q.release_note or '', by=q.released_by)
    if u.created_at:
        # created_at is stored in UTC and everything else in local time: always list it first
        add(datetime.combine(u.created_at.date(), datetime.min.time()), 'created', 'Added to inventory',
            sort=datetime.min)
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r[2] for r in rows]


# ---------------------------------------------------------------------------
# Maintenance history
# ---------------------------------------------------------------------------

def _parse_date(value, label, required=False):
    value = (value or '').strip() if isinstance(value, str) else value
    if not value:
        if required:
            raise ValueError(f'{label} is required')
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f'{label} must be a date (YYYY-MM-DD)')


@unit_tracking_bp.route('/equipment/unit/<int:uid>/maintenance')
@login_required
@crew_required
def list_maintenance(uid):
    u = EquipmentUnit.query.get_or_404(uid)
    return jsonify({'records': [m.to_dict() for m in u.maintenance],
                    'maintenance_due': u.maintenance_due()})


@unit_tracking_bp.route('/equipment/unit/<int:uid>/maintenance', methods=['POST'])
@login_required
@crew_required
def add_maintenance(uid):
    """Body: {kind, result, performed_on?, performed_by?, notes?, next_due?, set_status?}.
    Any crew member can log a check and flag a unit for repair; putting a unit
    back into service (or retiring it) is for admins."""
    u = EquipmentUnit.query.get_or_404(uid)
    data = request.get_json(silent=True) or {}
    kind   = (data.get('kind') or '').strip().lower()
    result = (data.get('result') or '').strip().lower()
    if kind not in MAINTENANCE_KINDS:
        return jsonify({'error': 'Type must be one of: ' + ', '.join(MAINTENANCE_LABELS.values())}), 400
    if result not in MAINTENANCE_RESULTS:
        return jsonify({'error': 'Result must be one of: ' + ', '.join(MAINTENANCE_RESULTS)}), 400
    try:
        performed_on = _parse_date(data.get('performed_on'), 'Date') or date.today()
        next_due     = _parse_date(data.get('next_due'), 'Next due date')
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if performed_on > date.today():
        return jsonify({'error': 'Date can’t be in the future'}), 400
    if next_due and next_due <= performed_on:
        return jsonify({'error': 'Next due date must be after the date of this check'}), 400

    set_status = (data.get('set_status') or '').strip().lower() or None
    if set_status:
        if set_status not in UNIT_STATUSES:
            return jsonify({'error': 'Unknown status'}), 400
        if set_status == 'quarantined':
            return jsonify({'error': 'Use “Quarantine” to pull an item out of use'}), 400
        if u.status == 'quarantined' and set_status != 'quarantined':
            return jsonify({'error': f'{u.asset_tag} is quarantined. Release it from quarantine instead'}), 409
        if set_status != 'repair' and not current_user.is_admin:
            return jsonify({'error': 'Only admins can change a unit to ' + set_status}), 403

    rec = UnitMaintenance(unit_id=u.id, kind=kind, result=result, performed_on=performed_on,
                          performed_by=(data.get('performed_by') or '').strip()[:120]
                                       or current_user.username,
                          notes=(data.get('notes') or '').strip() or None,
                          next_due=next_due, recorded_by=current_user.username)
    db.session.add(rec)
    if set_status:
        u.status = set_status
    db.session.commit()
    return jsonify({'success': True, 'record': rec.to_dict(),
                    'unit': {**_unit_brief(u), 'maintenance_due': u.maintenance_due()}})


@unit_tracking_bp.route('/equipment/maintenance/<int:mid>', methods=['DELETE'])
@login_required
@crew_required
def delete_maintenance(mid):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    rec = UnitMaintenance.query.get_or_404(mid)
    db.session.delete(rec)
    db.session.commit()
    return jsonify({'success': True})


def maintenance_alerts(today=None, equipment_id=None, include_ok=False):
    """Units whose next test/inspection is overdue or due soon, most urgent first.
    Retired and lost units are left out."""
    q = UnitMaintenance.query.join(EquipmentUnit, EquipmentUnit.id == UnitMaintenance.unit_id) \
        .filter(EquipmentUnit.status.notin_(('retired', 'lost')))
    if equipment_id:
        q = q.filter(EquipmentUnit.equipment_id == equipment_id)
    by_unit = {}
    for rec in q.all():
        by_unit.setdefault(rec.unit_id, []).append(rec)
    out = []
    for unit_id, recs in by_unit.items():
        due = due_state(latest_due_by_kind(recs), today)
        if not due or (due['state'] == 'ok' and not include_ok):
            continue
        u = recs[0].unit
        out.append({**_unit_brief(u), 'due': due})
    out.sort(key=lambda a: a['due']['date'])
    return out


def stale_checkouts():
    """Open check-outs whose event has finished: gear that should be back by now."""
    from routes.picklist import _event_is_archived
    rows = UnitCheckout.query.filter(UnitCheckout.returned_at.is_(None)).all()
    return [c.to_dict() for c in rows if c.event and _event_is_archived(c.event)]


# ---------------------------------------------------------------------------
# Top bar: search everything, and "what did I just scan?"
# ---------------------------------------------------------------------------

def _unit_url(u):
    from flask import url_for
    return url_for('equipment.equipment_detail', id=u.equipment_id, unit=u.id) + f'#unit-{u.id}'


@unit_tracking_bp.route('/api/search')
@login_required
@crew_required
def global_search():
    """Equipment types, individual items and events matching ?q= (every word must match)."""
    from flask import url_for
    q = (request.args.get('q') or '').strip().lower()
    resp_empty = jsonify({'groups': []})
    if len(q) < 2:
        return resp_empty
    words = q.split()

    def match(*fields):
        hay = ' '.join(f or '' for f in fields).lower()
        return all(w in hay for w in words)

    def like_any(*cols):
        return db.or_(*[db.func.lower(c).contains(words[0]) for c in cols])

    groups = []
    types = [e for e in Equipment.query.filter(like_any(
        Equipment.name, Equipment.barcode, Equipment.category, Equipment.location)).limit(200)
             if match(e.name, e.barcode, e.category, e.location)]
    types.sort(key=lambda e: (not (e.name or '').lower().startswith(q), (e.name or '').lower()))
    if types:
        groups.append({'label': 'Equipment', 'hits': [
            {'title': e.name, 'meta': ' · '.join(x for x in (e.category, e.location) if x),
             'url': url_for('equipment.equipment_detail', id=e.id)} for e in types[:6]]})

    units = [u for u in EquipmentUnit.query.filter(like_any(
        EquipmentUnit.asset_tag, EquipmentUnit.serial_number)).limit(200)
             if match(u.asset_tag, u.serial_number)]
    units.sort(key=lambda u: u.asset_tag.lower())
    if units:
        groups.append({'label': 'Items', 'hits': [
            {'title': u.asset_tag,
             'meta': ' · '.join(x for x in (u.equipment.name if u.equipment else '',
                                            UNIT_STATUS_LABELS.get(u.status or 'available')
                                            if (u.status or 'available') != 'available' else '') if x),
             'url': _unit_url(u)} for u in units[:6]]})

    events = [e for e in Event.query.filter(like_any(Event.title, Event.location))
              .order_by(Event.event_date.desc()).limit(200) if match(e.title, e.location)]
    if events:
        groups.append({'label': 'Events', 'hits': [
            {'title': e.title,
             'meta': ' · '.join(x for x in (e.event_date.strftime('%d %b %Y') if e.event_date else '',
                                            e.location) if x),
             'url': url_for('events.event_detail', id=e.id)} for e in events[:6]]})
    resp = jsonify({'groups': groups})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@unit_tracking_bp.route('/api/scan', methods=['POST'])
@login_required
@crew_required
def scan_lookup():
    """Body: {code}. Says what a scanned label is, with enough to show a result card."""
    from flask import url_for
    from routes.equipment import equipment_summaries
    kind, hit = resolve_code((request.get_json(silent=True) or {}).get('code'))
    if kind is None:
        return jsonify({'error': hit}), 404
    eq = hit.equipment if kind == 'unit' else hit
    d = {'kind': kind, 'equipment': {**eq.to_dict(), 'summary': equipment_summaries([eq])[eq.id]},
         'url': url_for('equipment.equipment_detail', id=eq.id)}
    if kind == 'unit':
        d['unit'] = hit.to_dict()
        d['url'] = _unit_url(hit)
    return jsonify(d)
