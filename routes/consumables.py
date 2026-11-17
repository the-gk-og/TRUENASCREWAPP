"""routes/consumables.py — stock counted by quantity rather than as individual units.

Gaffer tape, batteries by size, gels by number, lamps, cable ties… Each Consumable has a
current quantity and a low-stock level. Every change is a ConsumableMovement row:

  * use      −N, optionally against an event (crew)
  * restock  +N (crew)
  * count    set the quantity after a stocktake (admin)

When a change takes an item from above its low level to at/below it, gear admins are told
(services.notification_service.send_low_stock_alert). Low items show on the shopping list,
the dashboard and the gear "needs attention" box. Each item has a shelf QR label that opens
its page, where crew can take some or put some back in two taps.
"""

import base64
import io
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, url_for, g, abort
from flask_login import login_required, current_user
from sqlalchemy import func, event as sa_event

from extensions import db
from models import Consumable, ConsumableMovement, Event
from decorators import crew_required

consumables_bp = Blueprint('consumables', __name__)

UNDO_WINDOW = timedelta(minutes=10)
MAX_STEP = 100000


@sa_event.listens_for(Event, 'before_delete')
def _detach_event_usage(mapper, connection, target):
    """Keep usage history when an event is deleted (the row keeps event_title). The FK says
    ON DELETE SET NULL, but SQLite doesn't enforce foreign keys, so do it here too."""
    connection.execute(ConsumableMovement.__table__.update()
                       .where(ConsumableMovement.event_id == target.id).values(event_id=None))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def low_stock_items():
    """Consumables at or below their low level, emptiest (relative to the level) first."""
    items = Consumable.query.filter(Consumable.low_threshold > 0,
                                    Consumable.quantity <= Consumable.low_threshold).all()
    return sorted(items, key=lambda c: (c.quantity / c.low_threshold, c.name.lower()))


@consumables_bp.app_context_processor
def _inject_low_stock():
    def consumables_low():
        """Low consumables for the nav badge, dashboard and gear attention box (once per request)."""
        if 'consumables_low' not in g:
            try:
                g.consumables_low = low_stock_items()
            except Exception:
                g.consumables_low = []
        return g.consumables_low
    return dict(consumables_low=consumables_low)


def _admin_only():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    return None


def _to_buy(c):
    """Suggested amount to buy: the reorder amount, else enough to get back to twice the low level."""
    if c.reorder_qty:
        return c.reorder_qty
    return max(1, c.low_threshold * 2 - c.quantity)


def _item_dict(c):
    return {
        'id': c.id, 'name': c.name, 'category': c.category or '', 'unit': c.unit or 'each',
        'quantity': c.quantity, 'low_threshold': c.low_threshold, 'reorder_qty': c.reorder_qty,
        'location': c.location or '', 'supplier': c.supplier or '', 'supplier_url': c.supplier_url or '',
        'notes': c.notes or '', 'is_low': c.is_low, 'to_buy': _to_buy(c) if c.is_low else 0,
        'url': url_for('consumables.consumable_detail', cid=c.id),
    }


def _move_dict(m):
    return {
        'id': m.id, 'kind': m.kind, 'change': m.change, 'quantity_after': m.quantity_after,
        'event_id': m.event_id, 'event_title': m.event_title or '', 'note': m.note or '',
        'by': m.by_username or '', 'at': m.created_at.strftime('%d %b %Y, %H:%M') if m.created_at else '',
        'consumable_id': m.consumable_id,
    }


def _int(value, name, minimum=0, required=True):
    if value in (None, ''):
        if required:
            raise ValueError(f'{name} is required')
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a whole number')
    if n < minimum or n > MAX_STEP:
        raise ValueError(f'{name} must be between {minimum} and {MAX_STEP}')
    return n


def _apply_fields(c, data, partial=False):
    """Copy editable fields from a JSON body onto c. Raises ValueError on bad input."""
    if not partial or 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            raise ValueError('Name is required')
        c.name = name[:200]
    for key, size in (('category', 100), ('location', 200), ('supplier', 200), ('supplier_url', 500)):
        if not partial or key in data:
            setattr(c, key, (data.get(key) or '').strip()[:size] or None)
    if c.supplier_url and not c.supplier_url.lower().startswith(('http://', 'https://')):
        c.supplier_url = 'https://' + c.supplier_url
    if not partial or 'unit' in data:
        c.unit = (data.get('unit') or '').strip()[:40] or 'each'
    if not partial or 'notes' in data:
        c.notes = (data.get('notes') or '').strip() or None
    if not partial or 'low_threshold' in data:
        c.low_threshold = _int(data.get('low_threshold'), 'Low-stock level', required=False) or 0
    if not partial or 'reorder_qty' in data:
        c.reorder_qty = _int(data.get('reorder_qty'), 'Reorder amount', minimum=1, required=False)


def _change_stock(c, kind, change, event=None, note=''):
    """Record a movement and update the quantity. Sends the low-stock alert when c crosses its level.
    Returns the movement. Caller commits (this function commits too, before alerting)."""
    was_low = c.is_low
    c.quantity = max(0, (c.quantity or 0) + change)
    m = ConsumableMovement(
        consumable=c, kind=kind, change=change, quantity_after=c.quantity,
        event_id=event.id if event else None, event_title=event.title if event else None,
        note=(note or '').strip()[:300] or None, by_username=current_user.username,
    )
    db.session.add(m)
    db.session.commit()
    if c.is_low and not was_low:
        _alert(c)
    return m


def _alert(c):
    from services import notification_service
    try:
        notification_service.send_low_stock_alert(
            c, by=current_user.shown_name,
            url=url_for('consumables.consumable_detail', cid=c.id, _external=True))
    except Exception as exc:                                 # an alert must never break a stock change
        print(f'❌ Low-stock alert failed: {exc}')


def _event_choices(now=None):
    """Events people are likely to be using stock for: the last fortnight and the next two months."""
    now = now or datetime.now()
    return (Event.query.filter(Event.event_date >= now - timedelta(days=14),
                               Event.event_date <= now + timedelta(days=60))
            .order_by(Event.event_date).all())


def _default_event(events, now=None):
    """Today's event, if there is one."""
    now = now or datetime.now()
    today = now.date()
    for e in events:
        end = (e.event_end_date or e.event_date).date()
        if e.event_date.date() <= today <= end:
            return e.id
    return None


def _qr_data_uri(text):
    import qrcode
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@consumables_bp.route('/consumables')
@login_required
@crew_required
def consumables_list():
    items = Consumable.query.order_by(func.lower(Consumable.category), func.lower(Consumable.name)).all()
    categories = sorted({c.category for c in items if c.category}, key=str.lower)
    return render_template('crew/consumables.html', items=items, items_json=[_item_dict(c) for c in items],
                           categories=categories, low_count=sum(1 for c in items if c.is_low))


@consumables_bp.route('/consumables/shopping-list')
@login_required
@crew_required
def shopping_list():
    rows = [(c, _to_buy(c)) for c in low_stock_items()]
    by_supplier = {}
    for c, n in rows:
        by_supplier.setdefault(c.supplier or '', []).append((c, n))
    groups = sorted(by_supplier.items(), key=lambda kv: (kv[0] == '', kv[0].lower()))
    return render_template('crew/consumables_shopping.html', groups=groups, total=len(rows),
                           now=datetime.now())


@consumables_bp.route('/consumables/<int:cid>')
@login_required
@crew_required
def consumable_detail(cid):
    c = Consumable.query.get_or_404(cid)
    events = _event_choices()
    history = c.movements.limit(100).all()
    used_30 = -sum(m.change for m in c.movements.filter(
        ConsumableMovement.kind == 'use',
        ConsumableMovement.created_at >= datetime.utcnow() - timedelta(days=30)).all())
    return render_template('crew/consumable_detail.html', c=c, item_json=_item_dict(c),
                           events=events, default_event=_default_event(events),
                           history=history, used_30=used_30,
                           undo_minutes=int(UNDO_WINDOW.total_seconds() // 60))


@consumables_bp.route('/consumables/event/<int:event_id>')
@login_required
@crew_required
def event_usage(event_id):
    ev = Event.query.get_or_404(event_id)
    moves = (ConsumableMovement.query.filter_by(event_id=event_id)
             .order_by(ConsumableMovement.created_at.desc()).all())
    totals = {}
    for m in moves:
        t = totals.setdefault(m.consumable_id, {'item': m.consumable, 'used': 0, 'returned': 0})
        if m.change < 0:
            t['used'] += -m.change
        else:
            t['returned'] += m.change
    totals = sorted(totals.values(), key=lambda t: t['item'].name.lower())
    return render_template('crew/consumables_event.html', event=ev, moves=moves, totals=totals)


@consumables_bp.route('/consumables/labels')
@login_required
@crew_required
def labels():
    ids = [int(x) for x in request.args.get('ids', '').split(',') if x.strip().isdigit()]
    q = Consumable.query
    if ids:
        q = q.filter(Consumable.id.in_(ids))
    items = q.order_by(func.lower(Consumable.name)).all()
    if not items:
        abort(404)
    labels = [(c, _qr_data_uri(url_for('consumables.consumable_detail', cid=c.id, _external=True)))
              for c in items]
    return render_template('crew/consumables_labels.html', labels=labels)


# ---------------------------------------------------------------------------
# JSON: items
# ---------------------------------------------------------------------------

@consumables_bp.route('/consumables/<int:cid>/json')
@login_required
@crew_required
def consumable_json(cid):
    c = Consumable.query.get_or_404(cid)
    return jsonify({'item': _item_dict(c), 'history': [_move_dict(m) for m in c.movements.limit(50)]})


@consumables_bp.route('/consumables/add', methods=['POST'])
@login_required
@crew_required
def add_consumable():
    denied = _admin_only()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    c = Consumable(quantity=0)
    try:
        _apply_fields(c, data)
        start = _int(data.get('quantity'), 'Quantity', required=False) or 0
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    db.session.add(c)
    db.session.flush()
    if start:
        _change_stock(c, 'count', start, note='Starting stock')
    db.session.commit()
    return jsonify({'success': True, 'id': c.id, 'item': _item_dict(c)})


@consumables_bp.route('/consumables/<int:cid>', methods=['PUT'])
@login_required
@crew_required
def update_consumable(cid):
    denied = _admin_only()
    if denied:
        return denied
    c = Consumable.query.get_or_404(cid)
    was_low = c.is_low
    try:
        _apply_fields(c, request.get_json(silent=True) or {}, partial=True)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    db.session.commit()
    if c.is_low and not was_low:                 # raising the level above what's on the shelf
        _alert(c)
    return jsonify({'success': True, 'item': _item_dict(c)})


@consumables_bp.route('/consumables/<int:cid>', methods=['DELETE'])
@login_required
@crew_required
def delete_consumable(cid):
    denied = _admin_only()
    if denied:
        return denied
    c = Consumable.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# JSON: stock changes
# ---------------------------------------------------------------------------

def _body():
    return request.get_json(silent=True) or {}


@consumables_bp.route('/consumables/<int:cid>/use', methods=['POST'])
@login_required
@crew_required
def use_stock(cid):
    c = Consumable.query.get_or_404(cid)
    data = _body()
    try:
        n = _int(data.get('amount', 1), 'Amount', minimum=1)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if n > c.quantity:
        return jsonify({'error': f'Only {c.quantity} {c.unit or "each"} in stock. '
                                 'If the count is wrong, ask an admin to correct it.'}), 409
    event = None
    if data.get('event_id'):
        event = Event.query.get(data.get('event_id'))
        if not event:
            return jsonify({'error': 'That event no longer exists'}), 404
    m = _change_stock(c, 'use', -n, event=event, note=data.get('note'))
    return jsonify({'success': True, 'item': _item_dict(c), 'movement': _move_dict(m)})


@consumables_bp.route('/consumables/<int:cid>/restock', methods=['POST'])
@login_required
@crew_required
def restock(cid):
    c = Consumable.query.get_or_404(cid)
    data = _body()
    try:
        n = _int(data.get('amount'), 'Amount', minimum=1)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    event = Event.query.get(data['event_id']) if data.get('event_id') else None
    m = _change_stock(c, 'restock', n, event=event, note=data.get('note'))
    return jsonify({'success': True, 'item': _item_dict(c), 'movement': _move_dict(m)})


@consumables_bp.route('/consumables/<int:cid>/count', methods=['POST'])
@login_required
@crew_required
def stock_count(cid):
    """Stocktake: set the quantity to what's actually on the shelf."""
    denied = _admin_only()
    if denied:
        return denied
    c = Consumable.query.get_or_404(cid)
    data = _body()
    try:
        n = _int(data.get('quantity'), 'Quantity')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    m = _change_stock(c, 'count', n - c.quantity, note=data.get('note') or 'Stock count')
    return jsonify({'success': True, 'item': _item_dict(c), 'movement': _move_dict(m)})


@consumables_bp.route('/consumables/movement/<int:mid>/undo', methods=['POST'])
@login_required
@crew_required
def undo_movement(mid):
    """Take back your own last change to an item, within a few minutes (wrong button in a hurry)."""
    m = ConsumableMovement.query.get_or_404(mid)
    c = m.consumable
    latest = c.movements.first()
    if m.by_username != current_user.username and not current_user.is_admin:
        return jsonify({'error': 'You can only undo your own changes'}), 403
    if latest is None or latest.id != m.id:
        return jsonify({'error': 'Something else has changed this item since. Use or restock to correct it'}), 409
    if not current_user.is_admin and (m.created_at is None or datetime.utcnow() - m.created_at > UNDO_WINDOW):
        return jsonify({'error': 'Too late to undo that. Use or restock to correct it'}), 409
    c.quantity = max(0, c.quantity - m.change)
    db.session.delete(m)
    db.session.commit()
    return jsonify({'success': True, 'item': _item_dict(c)})


@consumables_bp.route('/consumables/event/<int:event_id>/json')
@login_required
@crew_required
def event_usage_json(event_id):
    Event.query.get_or_404(event_id)
    moves = (ConsumableMovement.query.filter_by(event_id=event_id)
             .order_by(ConsumableMovement.created_at.desc()).all())
    out = [dict(_move_dict(m), name=m.consumable.name, unit=m.consumable.unit or 'each') for m in moves]
    return jsonify({'movements': out})
