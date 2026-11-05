"""routes/unit_tracking.py — scanning units out to events and back, and per-unit
maintenance history (repairs, inspections, PAT tests) with due dates.

Check-outs are explicit records (UnitCheckout): who scanned the unit out, to
which event, when, and who scanned it back. A pick list allocation (PickListUnit)
is the plan; a check-out is what actually left the building.
"""

import re
from datetime import date, datetime

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from extensions import db
from models import (Equipment, EquipmentUnit, Event, PickListItem, PickListUnit,
                    UnitCheckout, UnitMaintenance, UNIT_STATUSES,
                    MAINTENANCE_KINDS, MAINTENANCE_LABELS, MAINTENANCE_RESULTS,
                    latest_due_by_kind, due_state)
from decorators import crew_required

unit_tracking_bp = Blueprint('unit_tracking', __name__)

_UNIT_URL = re.compile(r'/equipment/unit/(\d+)')
_ITEM_URL = re.compile(r'/equipment/(\d+)(?:/view)?(?:[/?#]|$)')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_scan(code):
    """(unit, None) for a unit QR URL / asset tag, else (None, error message)."""
    from routes.equipment import _unit_by_tag
    code = (code or '').strip()
    if not code:
        return None, 'Nothing scanned'
    m = _UNIT_URL.search(code)
    if m:
        unit = db.session.get(EquipmentUnit, int(m.group(1)))
        return (unit, None) if unit else (None, 'That unit no longer exists')
    unit = _unit_by_tag(code)
    if unit:
        return unit, None
    m = _ITEM_URL.search(code)
    item = (db.session.get(Equipment, int(m.group(1))) if m else
            Equipment.query.filter(db.func.lower(Equipment.barcode) == code.lower()).first())
    if item:
        if item.units:
            return None, f'That is the {item.name} item tag — scan one of its unit tags instead'
        return None, f'{item.name} is tracked by quantity only (no unit tags)'
    return None, f'No unit matches "{code}"'


def _unit_brief(unit):
    return {
        'id':             unit.id,
        'asset_tag':      unit.asset_tag,
        'equipment_id':   unit.equipment_id,
        'equipment_name': unit.equipment.name if unit.equipment else '',
        'status':         unit.status or 'available',
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
    resp = jsonify({'event': _event_brief(ev), 'out': out, 'returned': returned,
                    'expected': expected, 'unallocated': unallocated})
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@unit_tracking_bp.route('/equipment/checkout/scan', methods=['POST'])
@login_required
@crew_required
def checkout_scan():
    """Body: {event_id, code | unit_id, mode: auto|out|return, force}.

    auto: a unit already out to this event is returned, anything else is checked out.
    Problems that need a person to decide (unit in repair/retired/lost, out on
    another event) answer 409 with needs_confirm; resend with force=true.
    Softer problems (not on the pick list) still check out, with warnings.
    """
    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'auto').lower()
    if mode not in ('auto', 'out', 'return'):
        return jsonify({'error': 'Unknown mode'}), 400
    force = bool(data.get('force'))

    if data.get('unit_id'):
        unit = db.session.get(EquipmentUnit, int(data['unit_id']))
        err = None if unit else 'Unit not found'
    else:
        unit, err = resolve_scan(data.get('code'))
    if not unit:
        return jsonify({'error': err, 'conflict': 'not_found'}), 404

    co = unit.open_checkout
    event = db.session.get(Event, int(data['event_id'])) if data.get('event_id') else None
    if event is None and mode != 'return':
        return jsonify({'error': 'Pick an event first'}), 400

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
        db.session.commit()
        return jsonify({'success': True, 'action': 'return', 'unit': _unit_brief(unit),
                        'checkout': co.to_dict(), 'warnings': warnings,
                        'message': f'{unit.asset_tag} returned'})

    # ── Check out ───────────────────────────────────────────────────────────
    if co and co.event_id == event.id:
        return jsonify({'error': f'{unit.asset_tag} is already checked out to {event.title}',
                        'conflict': 'already_out', 'unit': _unit_brief(unit)}), 409

    blockers = []
    if unit.status and unit.status != 'available':
        blockers.append({'code': 'status', 'message': f'{unit.asset_tag} is marked {unit.status}'})
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
    co = UnitCheckout.query.get_or_404(cid)
    if co.returned_at is not None:
        return jsonify({'error': 'Already returned'}), 409
    _close(co)
    db.session.commit()
    return jsonify({'success': True, 'checkout': co.to_dict()})


@unit_tracking_bp.route('/equipment/unit/<int:uid>/history')
@login_required
@crew_required
def unit_history(uid):
    u = EquipmentUnit.query.get_or_404(uid)
    return jsonify({'unit': _unit_brief(u),
                    'checkouts': [c.to_dict() for c in u.checkouts],
                    'maintenance': [m.to_dict() for m in u.maintenance],
                    'maintenance_due': u.maintenance_due()})


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
