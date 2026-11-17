"""routes/cases.py — road cases and kits: one tagged case that holds a set of items.

A case is an ordinary EquipmentUnit whose type is marked `is_case`, so it has its own
QR label, check-outs, quarantine and maintenance like any other item. CaseItem rows say
what is packed in it; an item is in at most one case at a time.

Scanning a case on the Scan gear page moves the case and everything in it together
(see case_scan, called from unit_tracking.checkout_scan). Items flagged missing stay
behind until someone marks them found or scans them back into the case.
"""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, abort, url_for
from flask_login import login_required, current_user

from extensions import db
from models import EquipmentUnit, Event, UnitCheckout, CaseItem, UNIT_STATUS_LABELS
from decorators import crew_required

cases_bp = Blueprint('cases', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now()


def _get_case(uid):
    case = db.session.get(EquipmentUnit, uid)
    if not case:
        abort(404)
    if not case.is_case:
        abort(404)
    return case


def content_row(link):
    """One item in a case, with what someone packing it needs to know."""
    from routes.unit_tracking import _unit_brief
    u = link.unit
    co = u.open_checkout
    q = u.open_quarantine
    return {**_unit_brief(u),
            'serial_number': u.serial_number or '',
            'state':         u.state,
            'quarantined':   u.status == 'quarantined',
            'quarantine_reason': q.reason if q else '',
            'missing':       link.missing_at is not None,
            'missing_at':    link.missing_at.strftime('%d %b %Y, %H:%M') if link.missing_at else '',
            'missing_by':    link.missing_by or '',
            'missing_event': link.missing_event.title if link.missing_event else '',
            'checkout_id':   co.id if co else None,
            'out_event_id':  co.event_id if co else None,
            'out_event_title': co.event.title if co and co.event else ''}


def case_dict(case):
    from routes.unit_tracking import _unit_brief
    rows = [content_row(l) for l in case.case_contents]
    rows.sort(key=lambda r: (r['equipment_name'].lower(), r['asset_tag'].lower()))
    return {**_unit_brief(case),
            'url':         url_for('cases.case_page', uid=case.id),
            'contents':    rows,
            'count':       len(rows),
            'quarantined': sum(1 for r in rows if r['quarantined']),
            'missing':     sum(1 for r in rows if r['missing'])}


def add_to_case(case, unit, move=False):
    """Pack `unit` into `case`. Returns (CaseItem, None) or (None, (message, status, extra))."""
    if unit.id == case.id:
        return None, ('A case can’t go inside itself', 400, {})
    if unit.is_case:
        return None, (f'{unit.asset_tag} is a case itself. Cases can’t go inside cases', 400, {})
    link = unit.case_link
    if link and link.case_id == case.id:
        if link.missing_at:                       # scanned back into its case: found
            _clear_missing(link)
            return link, None
        return None, (f'{unit.asset_tag} is already in this case', 409, {'conflict': 'already_here'})
    if link:
        if not move:
            return None, (f'{unit.asset_tag} is packed in {link.case.asset_tag}. Move it to this case?', 409,
                          {'conflict': 'in_other_case', 'needs_confirm': True, 'other_case': link.to_dict()})
        db.session.delete(link)
        db.session.flush()
        db.session.expire(unit, ['case_link'])
    new = CaseItem(case_id=case.id, unit_id=unit.id, added_by=current_user.username, added_at=_now())
    db.session.add(new)
    return new, None


def _clear_missing(link):
    link.missing_at = None
    link.missing_by = None
    link.missing_event_id = None


# ---------------------------------------------------------------------------
# Case page, contents, label
# ---------------------------------------------------------------------------

@cases_bp.route('/equipment/case/<int:uid>')
@login_required
@crew_required
def case_page(uid):
    case = _get_case(uid)
    co = case.open_checkout
    return render_template('crew/case_detail.html', case=case, data=case_dict(case),
                           checkout=co.to_dict() if co else None,
                           quarantine=case.open_quarantine.to_dict() if case.open_quarantine else None)


@cases_bp.route('/equipment/case/<int:uid>/json')
@login_required
@crew_required
def case_json(uid):
    resp = jsonify(case_dict(_get_case(uid)))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@cases_bp.route('/equipment/case/<int:uid>/items', methods=['POST'])
@login_required
@crew_required
def case_add(uid):
    """Body: {code | unit_id, move?}. Packs a scanned item into the case.
    An item in another case answers 409 needs_confirm; resend with move=true."""
    from routes.unit_tracking import resolve_code
    case = _get_case(uid)
    data = request.get_json(silent=True) or {}
    if data.get('unit_id'):
        unit = db.session.get(EquipmentUnit, int(data['unit_id']))
        if not unit:
            return jsonify({'error': 'Item not found', 'conflict': 'not_found'}), 404
    else:
        kind, hit = resolve_code(data.get('code'))
        if kind == 'type':
            return jsonify({'error': f'That is the group label for {hit.name}. Scan the label on the item itself',
                            'conflict': 'group_label'}), 409
        if kind is None:
            return jsonify({'error': hit, 'conflict': 'not_found'}), 404
        unit = hit
    link, err = add_to_case(case, unit, move=bool(data.get('move')))
    if err:
        msg, status, extra = err
        return jsonify({'error': msg, **extra, 'unit': {'id': unit.id, 'asset_tag': unit.asset_tag}}), status
    db.session.commit()
    warnings = []
    if unit.status == 'quarantined':
        warnings.append(f'{unit.asset_tag} is out of use. Take it out of the case until it has been checked')
    elif unit.status in ('repair', 'retired', 'lost'):
        warnings.append(f'{unit.asset_tag} is marked {UNIT_STATUS_LABELS.get(unit.status, unit.status).lower()}')
    return jsonify({'success': True, 'item': content_row(link), 'warnings': warnings,
                    'message': f'{unit.asset_tag} packed in {case.asset_tag}', 'case': case_dict(case)})


@cases_bp.route('/equipment/case/<int:uid>/items/<int:unit_id>', methods=['DELETE'])
@login_required
@crew_required
def case_remove(uid, unit_id):
    case = _get_case(uid)
    link = CaseItem.query.filter_by(case_id=case.id, unit_id=unit_id).first_or_404()
    db.session.delete(link)
    db.session.commit()
    return jsonify({'success': True, 'case': case_dict(case)})


@cases_bp.route('/equipment/case/<int:uid>/items/<int:unit_id>/found', methods=['POST'])
@login_required
@crew_required
def case_found(uid, unit_id):
    case = _get_case(uid)
    link = CaseItem.query.filter_by(case_id=case.id, unit_id=unit_id).first_or_404()
    _clear_missing(link)
    db.session.commit()
    return jsonify({'success': True, 'case': case_dict(case)})


@cases_bp.route('/equipment/case/<int:uid>/label')
@login_required
@crew_required
def case_label(uid):
    """A printable contents sheet with the case's QR code, to tape inside the lid."""
    case = _get_case(uid)
    qr_url = url_for('equipment.unit_view_public', uid=case.id, _external=True)
    return render_template('crew/case_label.html', case=case, data=case_dict(case),
                           qr_url=qr_url, qr_svg=_qr_svg(qr_url), printed=_now().strftime('%d %b %Y'))


def _qr_svg(text):
    """Inline SVG of a QR code, or None when the qrcode package isn't installed."""
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    svg = img.to_string(encoding='unicode') if hasattr(img, 'to_string') else img.to_string().decode()
    return svg[svg.find('<svg'):]


# ---------------------------------------------------------------------------
# Scanning a case on the Scan gear page
# ---------------------------------------------------------------------------

def case_scan(case, event, mode, force):
    """Check a case and everything packed in it out to `event`, or back in.
    Returns (json body, status). Called by unit_tracking.checkout_scan."""
    from routes.unit_tracking import _unit_brief, _picklist_check, _close
    links = list(case.case_contents)
    members = [case] + [l.unit for l in links]
    co = case.open_checkout
    returning = mode == 'return' or (mode == 'auto' and event is not None and (
        (co and co.event_id == event.id) or
        (co is None and any(m.open_checkout and m.open_checkout.event_id == event.id for m in members))))

    # ── Back in: everything that is out comes back, wherever it went ──────────
    if returning:
        missing_ids = {l.unit_id for l in links if l.missing_at}
        out = [m for m in members if m.open_checkout and m.id not in missing_ids]
        if not out:
            return {'error': f'{case.asset_tag} and its contents are not checked out', 'conflict': 'not_out',
                    'unit': _unit_brief(case), 'case': case_dict(case)}, 409
        warnings, done = [], []
        for m in out:
            mco = m.open_checkout
            if event and mco.event_id != event.id:
                warnings.append({'code': 'other_event',
                                 'message': f'{m.asset_tag} was out on {mco.event.title}, not {event.title}'})
            _close(mco)
            done.append(m.id)
        still_out = [l.unit.asset_tag for l in links if l.missing_at and l.unit.open_checkout]
        if still_out:
            warnings.append({'code': 'missing', 'message': 'Still missing: ' + ', '.join(still_out)})
        db.session.commit()
        n = len(done) - (1 if case.id in done else 0)
        return {'success': True, 'action': 'return', 'is_case': True, 'unit': _unit_brief(case),
                'case': case_dict(case), 'moved': done, 'warnings': warnings,
                'event_id': event.id if event else (case.checkouts[0].event_id if case.checkouts else None),
                'message': f'{case.asset_tag} back in with {n} item{"" if n == 1 else "s"}'}, 200

    # ── Out ───────────────────────────────────────────────────────────────────
    if event is None:
        return {'error': 'Pick an event first'}, 400
    if case.status == 'quarantined':
        q = case.open_quarantine
        why = f': {q.reason}' if q and q.reason else ''
        return {'error': f'{case.asset_tag} is out of use{why}. It can’t go out until an admin has checked it',
                'conflict': 'quarantined', 'unit': _unit_brief(case), 'case': case_dict(case)}, 409

    going, left, blockers = [], [], []
    for m in members:
        link = m.case_link if m.id != case.id else None
        mco = m.open_checkout
        if link and link.missing_at:
            left.append({'code': 'missing', 'message': f'{m.asset_tag} is flagged missing from the case, so it stays behind'})
            continue
        if mco and mco.event_id == event.id:
            continue                                               # already out here
        if m.status == 'quarantined':
            q = m.open_quarantine
            left.append({'code': 'quarantined',
                         'message': f'{m.asset_tag} is out of use{": " + q.reason if q and q.reason else ""}. '
                                    'Take it out of the case and leave it behind'})
            continue
        if m.status and m.status != 'available':
            blockers.append({'code': 'status', 'message': f'{m.asset_tag} is marked '
                                                          f'{UNIT_STATUS_LABELS.get(m.status, m.status).lower()}'})
        if mco:
            blockers.append({'code': 'out_elsewhere',
                             'message': f'{m.asset_tag} is still out on {mco.event.title}'})
        going.append(m)
    if blockers and not force:
        return {'error': '; '.join(b['message'] for b in blockers), 'conflict': blockers[0]['code'],
                'needs_confirm': True, 'blockers': blockers, 'is_case': True,
                'unit': _unit_brief(case), 'case': case_dict(case)}, 409
    if not going:
        return {'error': f'{case.asset_tag} and its contents are already checked out to {event.title}',
                'conflict': 'already_out', 'unit': _unit_brief(case), 'case': case_dict(case)}, 409

    warnings = blockers + left
    infos = []
    for m in going:
        mco = m.open_checkout
        if mco:
            _close(mco, note=f'Moved to {event.title} by {current_user.username}')
        w, info = _picklist_check(m, event)
        if m.id != case.id:                    # the case itself rarely sits on a pick list
            warnings += w
        if info:
            infos.append(info)
        db.session.add(UnitCheckout(unit_id=m.id, event_id=event.id, checked_out_by=current_user.username,
                                    checked_out_at=_now(),
                                    notes=f'In case {case.asset_tag}' if m.id != case.id else None))
    db.session.commit()
    n = sum(1 for m in going if m.id != case.id)
    return {'success': True, 'action': 'out', 'is_case': True, 'unit': _unit_brief(case),
            'case': case_dict(case), 'moved': [m.id for m in going], 'warnings': warnings,
            'info': '; '.join(infos) or None, 'event_id': event.id,
            'message': f'{case.asset_tag} checked out to {event.title} with {n} item{"" if n == 1 else "s"}'}, 200


@cases_bp.route('/equipment/case/<int:uid>/missing', methods=['POST'])
@login_required
@crew_required
def case_missing(uid):
    """Body: {unit_id, event_id?, action?: out|return}. Flags an item as not in the case.
    Right after a case scan it also corrects that scan: an item that "went out" with
    the case is put back (it never left); one that "came back" is marked out again."""
    from routes.unit_tracking import UNDO_WINDOW
    case = _get_case(uid)
    data = request.get_json(silent=True) or {}
    link = CaseItem.query.filter_by(case_id=case.id, unit_id=int(data.get('unit_id') or 0)).first()
    if not link:
        return jsonify({'error': 'That item is not in this case'}), 404
    event = db.session.get(Event, int(data['event_id'])) if data.get('event_id') else None
    unit, me, cutoff = link.unit, current_user.username, _now() - UNDO_WINDOW
    link.missing_at, link.missing_by = _now(), me
    link.missing_event_id = event.id if event else None
    note = None
    action = data.get('action')
    if action == 'out':
        co = unit.open_checkout
        if co and co.checked_out_by == me and co.checked_out_at >= cutoff:
            db.session.delete(co)
            note = f'{unit.asset_tag} was not checked out'
    elif action == 'return':
        last = unit.checkouts[0] if unit.checkouts else None
        if last and last.returned_at and last.returned_by == me and last.returned_at >= cutoff \
                and not unit.open_checkout:
            last.returned_at = None
            last.returned_by = None
            last.notes = (f'{last.notes}\n' if last.notes else '') + f'Missing from case {case.asset_tag} when it came back'
            note = f'{unit.asset_tag} is still out on {last.event.title}'
    db.session.commit()
    return jsonify({'success': True, 'case': case_dict(case),
                    'message': f'{unit.asset_tag} flagged missing' + (f'. {note}' if note else '')})


@cases_bp.route('/equipment/case/<int:uid>/undo', methods=['POST'])
@login_required
@crew_required
def case_undo(uid):
    """Body: {action: out|return}. Takes back your own case scan made in the last 10 minutes."""
    from routes.unit_tracking import UNDO_WINDOW
    case = _get_case(uid)
    action = (request.get_json(silent=True) or {}).get('action')
    me, cutoff = current_user.username, _now() - UNDO_WINDOW
    members = [case] + [l.unit for l in case.case_contents]
    n = 0
    if action == 'out':
        for m in members:
            co = m.open_checkout
            if co and co.checked_out_by == me and co.checked_out_at >= cutoff:
                db.session.delete(co)
                n += 1
        message = f'{case.asset_tag} and its contents are back in storage'
    elif action == 'return':
        for m in members:
            last = m.checkouts[0] if m.checkouts else None
            if (last and last.returned_at and last.returned_by == me and last.returned_at >= cutoff
                    and not m.open_checkout and m.status != 'quarantined'):
                last.returned_at = None
                last.returned_by = None
                n += 1
        message = f'{case.asset_tag} and its contents are out again'
    else:
        return jsonify({'error': 'Unknown action'}), 400
    if not n:
        return jsonify({'error': 'Too late to undo that scan. Scan the case again instead'}), 409
    db.session.commit()
    return jsonify({'success': True, 'message': message})
