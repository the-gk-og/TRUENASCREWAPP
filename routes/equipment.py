"""routes/equipment.py — Equipment CRUD, barcodes, CSV import."""

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

equipment_bp = Blueprint('equipment', __name__)


@equipment_bp.route('/equipment')
@login_required
@crew_required
def equipment_list():
    equipment      = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    return render_template('/crew/equipment.html', equipment=equipment, equipment_json=equipment_json)


@equipment_bp.route('/equipment/barcode/<barcode>')
@login_required
@crew_required
def equipment_by_barcode(barcode):
    eq = Equipment.query.filter_by(barcode=barcode).first()
    if eq:
        return jsonify(eq.to_dict())
    return jsonify({'error': 'Equipment not found'}), 404


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
    db.session.delete(eq)
    db.session.commit()
    return jsonify({'success': True})


@equipment_bp.route('/equipment/import-csv', methods=['POST'])
@login_required
@crew_required
def import_csv():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        stream     = io.StringIO(request.files['file'].stream.read().decode('utf8'), newline=None)
        csv_reader = csv.DictReader(stream)
        count      = 0
        for row in csv_reader:
            barcode = row.get('barcode') or row.get('Barcode')
            name    = row.get('name')    or row.get('Name')
            if not barcode or not name:
                continue
            if Equipment.query.filter_by(barcode=barcode).first():
                continue
            db.session.add(Equipment(
                barcode=barcode, name=name,
                category=row.get('category') or row.get('Category') or '',
                location=row.get('location') or row.get('Location') or '',
                notes=row.get('notes')       or row.get('Notes')    or '',
            ))
            count += 1
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except Exception as exc:
        return jsonify({'error': f'Import failed: {exc}'}), 400


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
@login_required
@crew_required
def generate_barcodes():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    try:
        import tempfile
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from barcode import Code128
        from barcode.writer import ImageWriter

        data          = request.json
        equipment_ids = data.get('equipment_ids', [])
        barcode_size  = data.get('size', 'medium')

        if not equipment_ids:
            return jsonify({'error': 'No equipment selected'}), 400

        items = Equipment.query.filter(Equipment.id.in_(equipment_ids)).all()
        if not items:
            return jsonify({'error': 'No equipment found'}), 404

        pdf_buffer = io.BytesIO()
        c          = canvas.Canvas(pdf_buffer, pagesize=A4)
        pw, ph     = A4

        sizes = {
            'small':  (60*mm, 40*mm, 8),
            'medium': (80*mm, 50*mm, 10),
            'large':  (100*mm, 60*mm, 12),
        }
        barcode_width, barcode_height, font_size = sizes.get(barcode_size, sizes['medium'])

        margin    = 10*mm
        x_spacing = barcode_width + 5*mm
        y_spacing = barcode_height + 5*mm
        cols      = int((pw - 2*margin) / x_spacing)
        x_start   = margin
        y_start   = ph - margin - barcode_height
        cx, cy, n = x_start, y_start, 0

        for item in items:
            if not item.barcode:
                continue
            try:
                code128 = Code128(item.barcode, writer=ImageWriter())
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                    bc_path = tmp.name[:-4]
                code128.save(bc_path)
                img_path = bc_path + '.png'

                c.drawImage(img_path, cx, cy,
                            width=barcode_width, height=barcode_height-20*mm,
                            preserveAspectRatio=True, mask='auto')
                c.setFont('Helvetica-Bold', font_size)
                tw = c.stringWidth(item.name, 'Helvetica-Bold', font_size)
                c.drawString(cx + (barcode_width-tw)/2, cy + barcode_height - 15*mm, item.name)
                c.setFont('Helvetica', font_size-2)
                nw = c.stringWidth(item.barcode, 'Helvetica', font_size-2)
                c.drawString(cx + (barcode_width-nw)/2, cy - 5*mm, item.barcode)
                try:
                    os.remove(img_path)
                except Exception:
                    pass
            except Exception as exc:
                print(f"Barcode error for {item.id}: {exc}")

            n  += 1
            cx += x_spacing
            if n % cols == 0:
                cx  = x_start
                cy -= y_spacing
                if cy < margin:
                    c.showPage()
                    cy = y_start

        c.save()
        pdf_buffer.seek(0)
        filename = f"equipment_barcodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
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
