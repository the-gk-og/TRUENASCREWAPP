"""routes/equipment.py — Equipment CRUD, barcodes, CSV import, pictures."""

import io, csv, os
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, send_file, send_from_directory,
)
from flask_login import login_required, current_user

from extensions import db
from models import Equipment, PickListItem
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
    return render_template('crew/equipment_detail.html', item=eq, organisation_name=org_name)


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
    return jsonify({'error': 'Equipment not found'}), 404


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

        if not equipment_ids:
            return jsonify({'error': 'No equipment selected'}), 400

        items = Equipment.query.filter(Equipment.id.in_(equipment_ids)).all()
        if not items:
            return jsonify({'error': 'No equipment found'}), 404

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

        def _truncate(text, max_chars):
            return text[:max_chars] + ('…' if len(text) > max_chars else '')

        def _centred_string(text, font, size, cx, y, width):
            c.setFont(font, size)
            tw = c.stringWidth(text, font, size)
            c.drawString(cx + (width - tw) / 2, y, text)

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
        def _draw_portrait(cx, cy, item, qr_path):
            pad      = 3   * mm
            footer_h = 6.5 * mm
            name_h   = 8   * mm
            asset_h  = 6   * mm
            border_r = 4   * mm

            # Card outline — thick enough to feel like a tag
            c.setStrokeColor(BLACK)
            c.setLineWidth(1.2)
            c.roundRect(cx, cy, card_w, card_h, border_r, stroke=1, fill=0)

            # ── Item name (top, bold, centred) ──
            name_str  = _truncate(item.name, 26)
            name_size = max(8, min(13, int(card_w / 5.5)))
            c.setFillColor(BLACK)
            _centred_string(name_str, 'Helvetica-Bold', name_size,
                            cx, cy + card_h - pad - name_h + 2 * mm, card_w)

            # ── QR code (centred, with rounded light-grey background) ──
            body_h   = card_h - name_h - footer_h - asset_h - 2 * pad
            qr_size  = min(card_w - 6 * pad, body_h - 2 * pad)
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
            asset_str  = _truncate(item.barcode or f'ID-{item.id}', 24)
            asset_label = f'# {asset_str}'
            asset_y     = cy + footer_h + pad * 0.8
            c.setFillColor(MID_GREY)
            _centred_string(asset_label, 'Helvetica', 7,
                            cx, asset_y, card_w)

            # ── Divider above footer ──
            c.setStrokeColor(colors.HexColor('#cccccc'))
            c.setLineWidth(0.5)
            c.line(cx + pad, cy + footer_h - 0.8 * mm,
                   cx + card_w - pad, cy + footer_h - 0.8 * mm)

            # ── Organisation footer (centred, grey) ──
            c.setFillColor(MID_GREY)
            _centred_string(org_name, 'Helvetica', 6.5,
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
        def _draw_landscape(cx, cy, item, qr_path):
            pad      = 2.5 * mm
            footer_h = 5.5 * mm
            border_r = 4   * mm

            body_h = card_h - footer_h

            # Card outline
            c.setStrokeColor(BLACK)
            c.setLineWidth(1.2)
            c.roundRect(cx, cy, card_w, card_h, border_r, stroke=1, fill=0)

            # ── QR with rounded grey background (left) ──
            qr_size = body_h - 2 * pad
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
            text_w  = card_w - (qr_size + 4 * pad)
            mid_y   = cy + footer_h + body_h / 2

            # Item name — bold, centred in text column
            name_str  = _truncate(item.name, 24)
            name_size = max(8, min(12, int(text_w / 6)))
            c.setFillColor(BLACK)
            _centred_string(name_str, 'Helvetica-Bold', name_size,
                            text_x, mid_y + 2 * mm, text_w)

            # Asset number — centred in text column, below name
            asset_str   = _truncate(item.barcode or f'ID-{item.id}', 20)
            asset_label = f'# {asset_str}'
            c.setFillColor(MID_GREY)
            _centred_string(asset_label, 'Helvetica', 7,
                            text_x, mid_y - 4 * mm, text_w)

            # ── Divider above footer ──
            c.setStrokeColor(colors.HexColor('#cccccc'))
            c.setLineWidth(0.5)
            c.line(cx + pad, cy + footer_h - 0.5 * mm,
                   cx + card_w - pad, cy + footer_h - 0.5 * mm)

            # ── Organisation footer ──
            c.setFillColor(MID_GREY)
            _centred_string(org_name, 'Helvetica', 6.5,
                            cx, cy + 1.5 * mm, card_w)

        # ── Paginate and render ───────────────────────────────────────────────
        col_idx = 0
        row_idx = 0

        for item in items:
            try:
                url = f"{base_url}/equipment/{item.id}/view"
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
                    _draw_landscape(cx, cy, item, qr_path)
                else:
                    _draw_portrait(cx, cy, item, qr_path)

                try:
                    os.remove(qr_path)
                except Exception:
                    pass

            except Exception as exc:
                print(f"QR tag error for item {item.id}: {exc}")

            col_idx += 1
            if col_idx >= cols:
                col_idx = 0
                row_idx += 1
                if row_idx >= rows:
                    c.showPage()
                    row_idx = 0

        c.save()
        pdf_buffer.seek(0)
        filename = f"equipment_tags_{layout}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
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