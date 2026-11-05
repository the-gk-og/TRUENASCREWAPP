"""routes/equipment.py — Equipment CRUD, barcodes, CSV import, pictures."""

import io, csv, os
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, send_file, send_from_directory,
)
from flask_login import login_required, current_user

from extensions import db
from models import Equipment, EquipmentUnit, PickListItem, UNIT_STATUSES
from decorators import crew_required

from routes import _is_mobile

equipment_bp = Blueprint('equipment', __name__)

UPLOAD_FOLDER         = 'uploads'
EQUIPMENT_PICS_FOLDER = os.path.join(UPLOAD_FOLDER, 'equipment')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _remove_file(relative_path: str):
    try:
        full = os.path.join(UPLOAD_FOLDER, relative_path)
        if os.path.exists(full):
            os.remove(full)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment')
@login_required
@crew_required
def equipment_list():
    equipment      = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    template = 'crew/equipment_mobile.html' if _is_mobile(request.user_agent.string) else 'crew/equipment.html'
    return render_template(template, equipment=equipment, equipment_json=equipment_json)


# ---------------------------------------------------------------------------
# Detail page  ← NEW
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/<int:id>')
@login_required
@crew_required
def equipment_detail(id):
    eq = Equipment.query.get_or_404(id)
    from flask import current_app
    from utils import get_organization
    org = get_organization() or {}
    org_name = current_app.config.get('ORG_NAME') or org.get('name', 'ShowWise')
    return render_template('crew/equipment_detail.html', item=eq, organisation_name=org_name,
                           units=[u.to_dict() for u in eq.units],
                           unit_statuses=UNIT_STATUSES,
                           highlight_unit=request.args.get('unit', type=int))


# ---------------------------------------------------------------------------
# Public equipment view (for QR scan from outside app; no login, no sidebar)
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/<int:id>/view')
def equipment_view_public(id):
    if current_user.is_authenticated:
        return redirect(url_for('equipment.equipment_detail', id=id))
    eq = Equipment.query.get_or_404(id)
    from flask import current_app
    from utils import get_organization
    org = get_organization() or {}
    org_name = current_app.config.get('ORG_NAME') or org.get('name', 'ShowWise')
    login_url = url_for('auth.login', next=request.url)
    return render_template(
        'crew/equipment_detail_public.html',
        item=eq,
        organisation_name=org_name,
        login_url=login_url,
    )


# ---------------------------------------------------------------------------
# Equipment by ID (JSON) for in-app scanner when QR contains equipment URL
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/<int:id>/json')
@login_required
@crew_required
def equipment_by_id_json(id):
    eq = Equipment.query.get_or_404(id)
    return jsonify(eq.to_dict())


# ---------------------------------------------------------------------------
# Barcode lookup
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/barcode/<barcode>')
@login_required
@crew_required
def equipment_by_barcode(barcode):
    eq = Equipment.query.filter_by(barcode=barcode).first()
    if eq:
        return jsonify(eq.to_dict())
    # A unit's asset tag resolves to its item, with the unit attached
    unit = _unit_by_tag(barcode)
    if unit:
        return jsonify(_unit_payload(unit))
    return jsonify({'error': 'Equipment not found'}), 404


# ---------------------------------------------------------------------------
# Individual units (one row + one QR per physical piece of an item)
# ---------------------------------------------------------------------------

def _unit_by_tag(tag):
    tag = (tag or '').strip()
    if not tag:
        return None
    return (EquipmentUnit.query.filter_by(asset_tag=tag).first()
            or EquipmentUnit.query.filter(db.func.lower(EquipmentUnit.asset_tag) == tag.lower()).first())


def _tag_taken(tag, exclude_unit_id=None):
    """Asset tags share one namespace with item barcodes so a scan is never ambiguous."""
    q = EquipmentUnit.query.filter(db.func.lower(EquipmentUnit.asset_tag) == tag.lower())
    if exclude_unit_id:
        q = q.filter(EquipmentUnit.id != exclude_unit_id)
    if q.first():
        return True
    return Equipment.query.filter(db.func.lower(Equipment.barcode) == tag.lower()).first() is not None


def _create_units(eq, count):
    """Add `count` units to `eq`, tagged <barcode>-01, -02, … skipping tags in use."""
    base = (eq.barcode or f'EQ{eq.id}').strip()
    made, n = [], 1
    while len(made) < count:
        tag = f'{base}-{n:02d}'
        n += 1
        if _tag_taken(tag) or any(u.asset_tag == tag for u in made):
            continue
        u = EquipmentUnit(asset_tag=tag, status='available')
        eq.units.append(u)                    # cascades the add; keeps eq.units in step
        made.append(u)
    return made


def _unit_payload(unit):
    """Item dict (as the scanner already expects) with the scanned unit attached."""
    d = unit.equipment.to_dict()
    d['unit'] = unit.to_dict()
    return d


def _clean_status(value, default='available'):
    value = (value or default).strip().lower()
    return value if value in UNIT_STATUSES else None


@equipment_bp.route('/equipment/<int:id>/units')
@login_required
@crew_required
def list_units(id):
    eq = Equipment.query.get_or_404(id)
    return jsonify({'units': [u.to_dict() for u in eq.units]})


@equipment_bp.route('/equipment/<int:id>/units', methods=['POST'])
@login_required
@crew_required
def add_units(id):
    """Body {asset_tag, serial_number?, notes?, status?} adds one unit;
    {count: n} adds n units with generated tags."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq   = Equipment.query.get_or_404(id)
    data = request.get_json(silent=True) or {}

    if data.get('count') is not None:
        try:
            count = int(data['count'])
        except (TypeError, ValueError):
            return jsonify({'error': 'count must be a number'}), 400
        if not 1 <= count <= 500:
            return jsonify({'error': 'count must be between 1 and 500'}), 400
        made = _create_units(eq, count)
        _sync_quantity(eq)
        db.session.commit()
        return jsonify({'success': True, 'units': [u.to_dict(False) for u in made]})

    tag = (data.get('asset_tag') or '').strip()
    if not tag:
        return jsonify({'error': 'Asset tag is required'}), 400
    if len(tag) > 100:
        return jsonify({'error': 'Asset tag is too long'}), 400
    if _tag_taken(tag):
        return jsonify({'error': f'Asset tag "{tag}" is already used by another unit or item'}), 409
    status = _clean_status(data.get('status'))
    if status is None:
        return jsonify({'error': 'Unknown status'}), 400
    u = EquipmentUnit(asset_tag=tag, status=status,
                      serial_number=(data.get('serial_number') or '').strip() or None,
                      notes=(data.get('notes') or '').strip() or None)
    eq.units.append(u)
    _sync_quantity(eq)
    db.session.commit()
    return jsonify({'success': True, 'unit': u.to_dict(False)})


def _sync_quantity(eq):
    """Once an item tracks units, it owns at least that many."""
    if len(eq.units) > (eq.quantity_owned or 0):
        eq.quantity_owned = len(eq.units)


@equipment_bp.route('/equipment/unit/<int:uid>', methods=['PUT'])
@login_required
@crew_required
def update_unit(uid):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    u    = EquipmentUnit.query.get_or_404(uid)
    data = request.get_json(silent=True) or {}
    if 'asset_tag' in data:
        tag = (data.get('asset_tag') or '').strip()
        if not tag:
            return jsonify({'error': 'Asset tag is required'}), 400
        if _tag_taken(tag, exclude_unit_id=u.id):
            return jsonify({'error': f'Asset tag "{tag}" is already used by another unit or item'}), 409
        u.asset_tag = tag
    if 'status' in data:
        status = _clean_status(data.get('status'))
        if status is None:
            return jsonify({'error': 'Unknown status'}), 400
        u.status = status
    if 'serial_number' in data:
        u.serial_number = (data.get('serial_number') or '').strip() or None
    if 'notes' in data:
        u.notes = (data.get('notes') or '').strip() or None
    db.session.commit()
    return jsonify({'success': True, 'unit': u.to_dict()})


@equipment_bp.route('/equipment/unit/<int:uid>', methods=['DELETE'])
@login_required
@crew_required
def delete_unit(uid):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    u = EquipmentUnit.query.get_or_404(uid)
    db.session.delete(u)
    db.session.commit()
    return jsonify({'success': True})


@equipment_bp.route('/equipment/unit/<int:uid>/json')
@login_required
@crew_required
def unit_json(uid):
    return jsonify(_unit_payload(EquipmentUnit.query.get_or_404(uid)))


@equipment_bp.route('/equipment/unit/tag/<path:tag>')
@login_required
@crew_required
def unit_by_tag(tag):
    u = _unit_by_tag(tag)
    if not u:
        return jsonify({'error': 'Unit not found'}), 404
    return jsonify(_unit_payload(u))


@equipment_bp.route('/equipment/unit/<int:uid>/view')
def unit_view_public(uid):
    """Target of a unit QR code. Crew land on the item page with the unit highlighted."""
    u = EquipmentUnit.query.get_or_404(uid)
    if current_user.is_authenticated:
        return redirect(url_for('equipment.equipment_detail', id=u.equipment_id, unit=u.id)
                        + f'#unit-{u.id}')
    from flask import current_app
    from utils import get_organization
    org = get_organization() or {}
    org_name = current_app.config.get('ORG_NAME') or org.get('name', 'ShowWise')
    return render_template(
        'crew/equipment_detail_public.html',
        item=u.equipment, unit=u,
        organisation_name=org_name,
        login_url=url_for('auth.login', next=request.url),
    )


# ---------------------------------------------------------------------------
# Add / Update / Delete
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/add', methods=['POST'])
@login_required
@crew_required
def add_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    eq   = Equipment(
        barcode=data['barcode'], name=data['name'],
        category=data.get('category', ''), location=data.get('location', ''),
        notes=data.get('notes', ''), quantity_owned=data.get('quantity_owned', 1),
    )
    db.session.add(eq)
    db.session.commit()
    return jsonify({'success': True, 'id': eq.id})


@equipment_bp.route('/equipment/update/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq   = Equipment.query.get_or_404(id)
    data = request.json
    eq.name           = data.get('name',           eq.name)
    eq.category       = data.get('category',       eq.category)
    eq.location       = data.get('location',       eq.location)
    eq.notes          = data.get('notes',          eq.notes)
    eq.quantity_owned = data.get('quantity_owned', eq.quantity_owned)
    db.session.commit()
    return jsonify({'success': True})


@equipment_bp.route('/equipment/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq = Equipment.query.get_or_404(id)
    if eq.picture:
        _remove_file(eq.picture)
    if eq.location_picture:
        _remove_file(eq.location_picture)
    db.session.delete(eq)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Equipment picture (photo of the item)
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/<int:id>/picture', methods=['POST'])
@login_required
@crew_required
def upload_equipment_picture(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq = Equipment.query.get_or_404(id)

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not _allowed_image(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400
    from services.upload_security import is_real_image
    if not is_real_image(file):
        return jsonify({'error': 'That file is not a valid image'}), 400

    os.makedirs(EQUIPMENT_PICS_FOLDER, exist_ok=True)

    if eq.picture:
        _remove_file(eq.picture)

    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = f"equipment_{id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    file.save(os.path.join(EQUIPMENT_PICS_FOLDER, filename))

    eq.picture = f"equipment/{filename}"
    db.session.commit()
    return jsonify({'success': True, 'picture_url': url_for('equipment.serve_equipment_picture', id=id)})


@equipment_bp.route('/equipment/<int:id>/picture', methods=['DELETE'])
@login_required
@crew_required
def delete_equipment_picture(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq = Equipment.query.get_or_404(id)
    if eq.picture:
        _remove_file(eq.picture)
        eq.picture = None
        db.session.commit()
    return jsonify({'success': True})


@equipment_bp.route('/equipment/<int:id>/picture/view')
def serve_equipment_picture(id):
    eq = Equipment.query.get_or_404(id)
    if not eq.picture:
        return '', 404
    try:
        return send_from_directory(UPLOAD_FOLDER, eq.picture)
    except Exception:
        return '', 404


# ---------------------------------------------------------------------------
# Location picture (photo of the storage location)  ← NEW
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/<int:id>/location-picture', methods=['POST'])
@login_required
@crew_required
def upload_equipment_location_picture(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq = Equipment.query.get_or_404(id)

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not _allowed_image(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400
    from services.upload_security import is_real_image
    if not is_real_image(file):
        return jsonify({'error': 'That file is not a valid image'}), 400

    os.makedirs(EQUIPMENT_PICS_FOLDER, exist_ok=True)

    if eq.location_picture:
        _remove_file(eq.location_picture)

    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = f"equipment_loc_{id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    file.save(os.path.join(EQUIPMENT_PICS_FOLDER, filename))

    eq.location_picture = f"equipment/{filename}"
    db.session.commit()
    return jsonify({'success': True,
                    'location_picture_url': url_for('equipment.serve_equipment_location_picture', id=id)})


@equipment_bp.route('/equipment/<int:id>/location-picture', methods=['DELETE'])
@login_required
@crew_required
def delete_equipment_location_picture(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    eq = Equipment.query.get_or_404(id)
    if eq.location_picture:
        _remove_file(eq.location_picture)
        eq.location_picture = None
        db.session.commit()
    return jsonify({'success': True})


@equipment_bp.route('/equipment/<int:id>/location-picture/view')
def serve_equipment_location_picture(id):
    eq = Equipment.query.get_or_404(id)
    if not eq.location_picture:
        return '', 404
    try:
        return send_from_directory(UPLOAD_FOLDER, eq.location_picture)
    except Exception:
        return '', 404


# ---------------------------------------------------------------------------
# CSV import  (FIXED: now imports quantity_owned correctly)
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/import-csv', methods=['POST'])
@login_required
@crew_required
def import_csv():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        raw = request.files['file'].stream.read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')

        stream     = io.StringIO(text, newline=None)
        csv_reader = csv.DictReader(stream)

        count   = 0
        skipped = 0
        errors  = []

        for row_num, row in enumerate(csv_reader, start=2):
            def _get(row, *keys):
                for k in keys:
                    for rk, rv in row.items():
                        if rk and rk.strip().lower() == k.lower():
                            return (rv or '').strip()
                return ''

            barcode = _get(row, 'barcode')
            name    = _get(row, 'name')

            if not barcode or not name:
                skipped += 1
                continue

            if Equipment.query.filter_by(barcode=barcode).first():
                skipped += 1
                continue

            qty_raw = _get(row, 'quantity_owned', 'quantity', 'qty')
            try:
                qty = max(1, int(qty_raw)) if qty_raw else 1
            except ValueError:
                qty = 1

            try:
                db.session.add(Equipment(
                    barcode=barcode, name=name,
                    category=_get(row, 'category'),
                    location=_get(row, 'location'),
                    notes=_get(row, 'notes'),
                    quantity_owned=qty,
                ))
                count += 1
            except Exception as row_exc:
                errors.append(f"Row {row_num}: {row_exc}")

        db.session.commit()
        return jsonify({'success': True, 'imported': count, 'skipped': skipped, 'errors': errors})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'Import failed: {exc}'}), 400


# ---------------------------------------------------------------------------
# Barcodes
# ---------------------------------------------------------------------------

@equipment_bp.route('/equipment/barcodes')
@login_required
@crew_required
def barcode_page():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('equipment.equipment_list'))
    equipment      = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    return render_template('crew/barcodes.html', equipment=equipment, equipment_json=equipment_json)


@equipment_bp.route('/equipment/generate-barcodes', methods=['POST'])
@equipment_bp.route('/equipment/generate-qrcodes', methods=['POST'])
@login_required
@crew_required
def generate_barcodes():
    """Generate PDF of QR equipment tags (portrait or landscape) in custom mm sizes."""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    try:
        import tempfile
        import qrcode
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.units import mm
        from reportlab.lib import colors

        data          = request.json
        equipment_ids = data.get('equipment_ids', [])
        layout        = data.get('layout', 'portrait')
        card_w_mm     = float(data.get('card_width_mm',  60 if layout == 'portrait' else 90))
        card_h_mm     = float(data.get('card_height_mm', 80 if layout == 'portrait' else 55))
        base_url      = (data.get('base_url') or request.url_root or '').rstrip('/')

        mode          = data.get('mode', 'item')       # 'item' | 'unit'
        unit_ids      = data.get('unit_ids', [])

        # Each tag: (log id, name, asset label, QR url)
        tags = []
        if mode == 'unit':
            if unit_ids:
                units = EquipmentUnit.query.filter(EquipmentUnit.id.in_(unit_ids)).all()
            elif equipment_ids:
                units = EquipmentUnit.query.filter(EquipmentUnit.equipment_id.in_(equipment_ids)).all()
            else:
                return jsonify({'error': 'No equipment selected'}), 400
            units.sort(key=lambda u: (u.equipment.name.lower(), u.asset_tag))
            if not units:
                return jsonify({'error': 'The selected items have no units yet. '
                                         'Add units on the item page, or print one tag per item.'}), 404
            tags = [(f'unit {u.id}', u.equipment.name, f'# {u.asset_tag}',
                     f'{base_url}/equipment/unit/{u.id}/view') for u in units]
        else:
            if not equipment_ids:
                return jsonify({'error': 'No equipment selected'}), 400
            items = Equipment.query.filter(Equipment.id.in_(equipment_ids)).all()
            if not items:
                return jsonify({'error': 'No equipment found'}), 404
            tags = [(f'item {e.id}', e.name, f"# {e.barcode or f'ID-{e.id}'}",
                     f'{base_url}/equipment/{e.id}/view') for e in items]

        # Org name
        from flask import current_app
        try:
            from utils import get_organization
            org = get_organization() or {}
        except Exception:
            org = {}
        org_name = current_app.config.get('ORG_NAME') or org.get('name', 'ShowWise')

        card_w = card_w_mm * mm
        card_h = card_h_mm * mm
        gap    = 4 * mm
        margin = 8 * mm
        pw, ph = A4

        cols = max(1, int((pw - 2 * margin + gap) / (card_w + gap)))
        rows = max(1, int((ph - 2 * margin + gap) / (card_h + gap)))

        pdf_buffer = io.BytesIO()
        c = rl_canvas.Canvas(pdf_buffer, pagesize=A4)

        BLACK    = colors.black
        WHITE    = colors.white
        MID_GREY = colors.HexColor('#666666')

        LEADING = 1.15  # line height as a multiple of font size

        def _wrap(text, font, size, width):
            """Greedy word-wrap measured in real glyph widths. Words wider than
            the column are broken mid-word so nothing ever overflows."""
            sw = lambda s: c.stringWidth(s, font, size)
            lines, cur = [], ''
            for word in text.split():
                cand = f'{cur} {word}' if cur else word
                if sw(cand) <= width:
                    cur = cand
                    continue
                if cur:
                    lines.append(cur)
                    cur = ''
                while sw(word) > width and len(word) > 1:
                    cut = len(word) - 1
                    while cut > 1 and sw(word[:cut]) > width:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                cur = word
            if cur:
                lines.append(cur)
            return lines or ['']

        def _ellipsize(text, font, size, width):
            if c.stringWidth(text, font, size) <= width:
                return text
            while text and c.stringWidth(text + '…', font, size) > width:
                text = text[:-1]
            return text.rstrip() + '…'

        def _fit_text(text, font, max_size, min_size, width, max_lines,
                      max_height=None):
            """Pick the largest font size (max_size → min_size) at which `text`
            wraps into ≤ max_lines lines within `width` (and `max_height`).
            If it still doesn't fit at min_size, the last line is ellipsized."""
            text  = (text or '').strip()
            width = max(width, 1)
            size  = max_size
            while True:
                lines = _wrap(text, font, size, width)
                n_ok  = len(lines) <= max_lines
                h_ok  = max_height is None or len(lines) * size * LEADING <= max_height
                if (n_ok and h_ok) or size <= min_size:
                    break
                size = max(min_size, size - 0.5)
            if max_height is not None:
                max_lines = max(1, min(max_lines, int(max_height // (size * LEADING))))
            if len(lines) > max_lines:
                rest  = ' '.join(lines[max_lines - 1:])
                lines = lines[:max_lines - 1] + [_ellipsize(rest, font, size, width)]
            return size, lines

        def _centred_string(text, font, size, cx, y, width):
            c.setFont(font, size)
            tw = c.stringWidth(text, font, size)
            c.drawString(cx + (width - tw) / 2, y, text)

        def _centred_lines(lines, font, size, cx, top_y, width):
            """Draw centred lines; top_y is the top of the text block."""
            for i, line in enumerate(lines):
                baseline = top_y - size * 0.8 - i * size * LEADING
                _centred_string(line, font, size, cx, baseline, width)

        # ── PORTRAIT ────────────────────────────────────────────────────────
        #
        #  ┌──────────────────────┐
        #  │                      │
        #  │     Item Name        │  ← bold, centred, top
        #  │                      │
        #  │  ┌────────────────┐  │
        #  │  │                │  │
        #  │  │    QR CODE     │  │  ← large, centred, rounded bg
        #  │  │                │  │
        #  │  └────────────────┘  │
        #  │                      │
        #  │      # ASSET-001     │  ← centred asset number
        #  │                      │
        #  ├──────────────────────┤  ← thin divider
        #  │     Organisation     │  ← small grey footer
        #  └──────────────────────┘
        #
        def _draw_portrait(cx, cy, name, asset_label, qr_path):
            pad      = 3   * mm
            footer_h = 6.5 * mm
            asset_h  = 6   * mm
            border_r = 4   * mm
            text_w   = card_w - 2 * pad - 2 * mm   # keep clear of rounded corners

            # Card outline — thick enough to feel like a tag
            c.setStrokeColor(BLACK)
            c.setLineWidth(1.2)
            c.roundRect(cx, cy, card_w, card_h, border_r, stroke=1, fill=0)

            # ── Item name (top, bold, centred, wrapped up to 3 lines) ──
            # Name may use at most ~35% of the card height; the QR shrinks to fit.
            name_max  = max(8, min(13, int(card_w / 5.5)))
            name_size, name_lines = _fit_text(
                name, 'Helvetica-Bold', name_max, 6, text_w, 3,
                max_height=card_h * 0.35)
            name_h = len(name_lines) * name_size * LEADING + 3 * mm
            c.setFillColor(BLACK)
            _centred_lines(name_lines, 'Helvetica-Bold', name_size,
                           cx + (card_w - text_w) / 2,
                           cy + card_h - pad - 1.5 * mm, text_w)

            # ── QR code (centred, with rounded light-grey background) ──
            body_h   = card_h - name_h - footer_h - asset_h - 2 * pad
            qr_size  = max(8 * mm, min(card_w - 6 * pad, body_h - 2 * pad))
            qr_x     = cx + (card_w - qr_size) / 2
            qr_y     = cy + footer_h + asset_h + (body_h - qr_size) / 2 + pad * 0.5

            # Rounded grey background behind QR
            bg_pad = 2 * mm
            c.setFillColor(colors.HexColor('#eeeeee'))
            c.roundRect(qr_x - bg_pad, qr_y - bg_pad,
                        qr_size + 2 * bg_pad, qr_size + 2 * bg_pad,
                        3 * mm, stroke=0, fill=1)

            c.drawImage(qr_path, qr_x, qr_y,
                        width=qr_size, height=qr_size,
                        preserveAspectRatio=True, mask='auto')

            # ── Asset number (centred, under QR) ──
            asset_size, asset_lines = _fit_text(asset_label, 'Helvetica', 7, 5, text_w, 1)
            asset_y     = cy + footer_h + pad * 0.8
            c.setFillColor(MID_GREY)
            _centred_string(asset_lines[0], 'Helvetica', asset_size,
                            cx, asset_y, card_w)

            # ── Divider above footer ──
            c.setStrokeColor(colors.HexColor('#cccccc'))
            c.setLineWidth(0.5)
            c.line(cx + pad, cy + footer_h - 0.8 * mm,
                   cx + card_w - pad, cy + footer_h - 0.8 * mm)

            # ── Organisation footer (centred, grey) ──
            c.setFillColor(MID_GREY)
            org_size, org_lines = _fit_text(org_name, 'Helvetica', 6.5, 5, text_w, 1)
            _centred_string(org_lines[0], 'Helvetica', org_size,
                            cx, cy + 2 * mm, card_w)

        # ── LANDSCAPE ───────────────────────────────────────────────────────
        #
        #  ┌──────────────────────────────────────┐
        #  │        │   Item Name (bold)           │
        #  │   QR   │                              │
        #  │        │   # ASSET-001 (centred-ish)  │
        #  ├────────┴─────────────────────────────┤
        #  │              Organisation             │
        #  └──────────────────────────────────────┘
        #
        def _draw_landscape(cx, cy, name, asset_label, qr_path):
            pad      = 2.5 * mm
            footer_h = 5.5 * mm
            border_r = 4   * mm

            body_h = card_h - footer_h

            # Card outline
            c.setStrokeColor(BLACK)
            c.setLineWidth(1.2)
            c.roundRect(cx, cy, card_w, card_h, border_r, stroke=1, fill=0)

            # ── QR with rounded grey background (left) ──
            # Never let the QR eat more than ~half the width, so text has room.
            qr_size = min(body_h - 2 * pad, card_w * 0.5)
            qr_x    = cx + pad
            qr_y    = cy + footer_h + (body_h - qr_size) / 2

            bg_pad = 1.5 * mm
            c.setFillColor(colors.HexColor('#eeeeee'))
            c.roundRect(qr_x - bg_pad, qr_y - bg_pad,
                        qr_size + 2 * bg_pad, qr_size + 2 * bg_pad,
                        2.5 * mm, stroke=0, fill=1)

            c.drawImage(qr_path, qr_x, qr_y,
                        width=qr_size, height=qr_size,
                        preserveAspectRatio=True, mask='auto')

            # ── Text block (right of QR) ──
            text_x  = cx + qr_size + 3 * pad
            text_w  = max(10 * mm, card_w - (qr_size + 4 * pad))
            mid_y   = cy + footer_h + body_h / 2
            text_max_h = body_h - 2 * pad
            line_gap   = 2 * mm

            # Asset number — one line, shrunk/ellipsized to the column width
            asset_size, asset_lines = _fit_text(asset_label, 'Helvetica', 7, 5, text_w, 1)
            asset_block = asset_size * LEADING

            # Item name — bold, wrapped (up to 4 lines) in the space left over
            name_max  = max(8, min(12, int(text_w / 6)))
            name_size, name_lines = _fit_text(
                name, 'Helvetica-Bold', name_max, 6, text_w, 4,
                max_height=text_max_h - asset_block - line_gap)
            name_block = len(name_lines) * name_size * LEADING

            # Centre the name + asset block vertically beside the QR
            top_y = mid_y + (name_block + line_gap + asset_block) / 2
            c.setFillColor(BLACK)
            _centred_lines(name_lines, 'Helvetica-Bold', name_size,
                           text_x, top_y, text_w)
            c.setFillColor(MID_GREY)
            _centred_lines(asset_lines, 'Helvetica', asset_size,
                           text_x, top_y - name_block - line_gap, text_w)

            # ── Divider above footer ──
            c.setStrokeColor(colors.HexColor('#cccccc'))
            c.setLineWidth(0.5)
            c.line(cx + pad, cy + footer_h - 0.5 * mm,
                   cx + card_w - pad, cy + footer_h - 0.5 * mm)

            # ── Organisation footer ──
            c.setFillColor(MID_GREY)
            org_size, org_lines = _fit_text(org_name, 'Helvetica', 6.5, 5,
                                            card_w - 2 * pad - 2 * mm, 1)
            _centred_string(org_lines[0], 'Helvetica', org_size,
                            cx, cy + 1.5 * mm, card_w)

        # ── Paginate and render ───────────────────────────────────────────────
        col_idx = 0
        row_idx = 0

        for tag_key, name, asset_label, url in tags:
            try:
                qr  = qrcode.QRCode(version=1, box_size=10, border=2,
                                    error_correction=qrcode.constants.ERROR_CORRECT_M)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color='black', back_color='white')
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                    img.save(tmp.name)
                    qr_path = tmp.name

                cx = margin + col_idx * (card_w + gap)
                cy = ph - margin - card_h - row_idx * (card_h + gap)

                if layout == 'landscape':
                    _draw_landscape(cx, cy, name, asset_label, qr_path)
                else:
                    _draw_portrait(cx, cy, name, asset_label, qr_path)

                try:
                    os.remove(qr_path)
                except Exception:
                    pass

            except Exception as exc:
                print(f"QR tag error for {tag_key}: {exc}")

            col_idx += 1
            if col_idx >= cols:
                col_idx = 0
                row_idx += 1
                if row_idx >= rows:
                    c.showPage()
                    row_idx = 0

        c.save()
        pdf_buffer.seek(0)
        filename = f"equipment_{'unit_' if mode == 'unit' else ''}tags_{layout}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(pdf_buffer, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)

    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(exc)}), 500

@equipment_bp.route('/equipment/<int:id>/quantity-check', methods=['POST'])
@login_required
def check_equipment_quantity(id):
    eq            = Equipment.query.get_or_404(id)
    requested_qty = request.json.get('quantity', 1)
    allocated     = db.session.query(db.func.sum(PickListItem.quantity)).filter(
        PickListItem.equipment_id == id,
        PickListItem.is_checked   == False,
    ).scalar() or 0
    owned     = eq.quantity_owned or 999
    available = owned - allocated
    return jsonify({
        'owned': owned, 'allocated': allocated,
        'available': available, 'requested': requested_qty,
        'warning': requested_qty > available,
    })