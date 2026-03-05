"""services/file_service.py — File uploads and barcode PDF generation."""
import io
import os
import tempfile
from datetime import datetime

from constants import BARCODE_SIZES


def generate_barcode_pdf(equipment_items, barcode_size: str = 'medium'):
    """Generate a PDF of barcodes for *equipment_items*. Returns (BytesIO, filename)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from barcode import Code128
    from barcode.writer import ImageWriter

    barcode_width_mm, barcode_height_mm, font_size = BARCODE_SIZES.get(barcode_size, BARCODE_SIZES['medium'])
    barcode_width = barcode_width_mm * mm
    barcode_height = barcode_height_mm * mm

    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    page_width, page_height = A4

    margin = 10 * mm
    x_spacing = barcode_width + 5 * mm
    y_spacing = barcode_height + 5 * mm
    cols = int((page_width - 2 * margin) / x_spacing)

    x_start = margin
    y_start = page_height - margin - barcode_height
    current_x, current_y = x_start, y_start
    item_count = 0

    for item in equipment_items:
        if not item.barcode:
            continue
        try:
            code128 = Code128(item.barcode, writer=ImageWriter())
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                barcode_path = tmp_file.name[:-4]
                code128.save(barcode_path)
                image_path = barcode_path + '.png'

            c.drawImage(image_path, current_x, current_y,
                        width=barcode_width, height=barcode_height - 20 * mm, preserveAspectRatio=True, mask='auto')

            c.setFont('Helvetica-Bold', font_size)
            text_w = c.stringWidth(item.name, 'Helvetica-Bold', font_size)
            c.drawString(current_x + (barcode_width - text_w) / 2, current_y + barcode_height - 15 * mm, item.name)

            c.setFont('Helvetica', font_size - 2)
            num_w = c.stringWidth(item.barcode, 'Helvetica', font_size - 2)
            c.drawString(current_x + (barcode_width - num_w) / 2, current_y - 5 * mm, item.barcode)

            try:
                os.remove(image_path)
            except Exception:
                pass
        except Exception as e:
            print(f"❌ Error drawing barcode for item {item.id}: {e}")

        item_count += 1
        current_x += x_spacing
        if item_count % cols == 0:
            current_x = x_start
            current_y -= y_spacing
            if current_y < margin:
                c.showPage()
                current_y = y_start

    c.save()
    pdf_buffer.seek(0)
    filename = f"equipment_barcodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return pdf_buffer, filename
