"""services/report_service.py — PDF generation for event briefs."""

import io, os, re
from datetime import datetime

from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, PageBreak, Image, HRFlowable,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_CENTER


def generate_event_pdf(event_id: int):
    """Return (BytesIO, filename) for an event brief PDF."""
    from models import Event, User
    event = Event.query.get_or_404(event_id)

    def add_header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColorRGB(0.39, 0.49, 0.94)
        canvas.rect(0, letter[1] - 40, letter[0], 40, fill=True, stroke=False)
        canvas.setFillColorRGB(1, 1, 1)
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(20 * mm, letter[1] - 25, "EVENT BRIEF")
        canvas.setFont('Helvetica', 10)
        canvas.drawRightString(letter[0] - 20 * mm, letter[1] - 25, f"Event ID: {event.id}")
        canvas.setFillColorRGB(0.5, 0.5, 0.5)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(20 * mm, 15 * mm, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
        canvas.drawRightString(letter[0] - 20 * mm, 15 * mm, f"Page {canvas.getPageNumber()}")
        canvas.setStrokeColorRGB(0.8, 0.8, 0.8)
        canvas.line(20 * mm, 20 * mm, letter[0] - 20 * mm, 20 * mm)
        canvas.restoreState()

    pdf_buffer = io.BytesIO()
    doc        = SimpleDocTemplate(pdf_buffer, pagesize=letter,
                                   topMargin=50, bottomMargin=30,
                                   leftMargin=20*mm, rightMargin=20*mm)
    story  = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=28,
                                  textColor=colors.HexColor('#6366f1'), spaceAfter=8,
                                  spaceBefore=20, alignment=TA_CENTER, fontName='Helvetica-Bold')
    sub_style   = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=11,
                                  textColor=colors.HexColor('#6b7280'), spaceAfter=20,
                                  alignment=TA_CENTER)
    sec_style   = ParagraphStyle('Sec', parent=styles['Heading2'], fontSize=14,
                                  textColor=colors.HexColor('#1f2937'), spaceAfter=12,
                                  spaceBefore=20, fontName='Helvetica-Bold')
    body_style  = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10,
                                  leading=14, textColor=colors.HexColor('#374151'))
    wrap_style  = ParagraphStyle('Wrap', parent=styles['Normal'], fontSize=9,
                                  leading=12, textColor=colors.HexColor('#374151'))
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8,
                                  leading=11, textColor=colors.HexColor('#4b5563'))
    note_h_sty  = ParagraphStyle('NoteH', parent=styles['Normal'], fontSize=9,
                                  textColor=colors.HexColor('#78350f'), fontName='Helvetica-Bold')
    note_b_sty  = ParagraphStyle('NoteB', parent=styles['Normal'], fontSize=9,
                                  leading=12, textColor=colors.HexColor('#78350f'))

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(event.title, title_style))
    story.append(Paragraph(event.event_date.strftime('%A, %B %d, %Y'), sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#e5e7eb'),
                             spaceBefore=10, spaceAfter=20))

    story.append(Paragraph("EVENT OVERVIEW", sec_style))
    start_time = event.event_date.strftime('%I:%M %p')
    if event.event_end_date:
        duration = (event.event_end_date - event.event_date).total_seconds() / 3600
        time_info = f"{start_time} - {event.event_end_date.strftime('%I:%M %p')} ({duration:.1f} hours)"
    else:
        time_info = f"{start_time} (Duration: TBD)"

    ov_data = [
        [Paragraph('<b>Time:</b>',       body_style), Paragraph(time_info, body_style)],
        [Paragraph('<b>Location:</b>',   body_style), Paragraph(event.location or 'TBD', body_style)],
        [Paragraph('<b>Created By:</b>', body_style), Paragraph(event.created_by or 'N/A', body_style)],
        [Paragraph('<b>Created:</b>',    body_style), Paragraph(event.created_at.strftime('%B %d, %Y'), body_style)],
    ]
    ov_table = Table(ov_data, colWidths=[1.5*inch, 4.5*inch])
    ov_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'), ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
    ]))
    story.append(ov_table)
    story.append(Spacer(1, 0.2*inch))

    if event.description:
        story.append(Paragraph("DESCRIPTION", sec_style))
        story.append(Paragraph(event.description.replace('\n', '<br/>'), body_style))
        story.append(Spacer(1, 0.2*inch))

    if getattr(event, 'schedules', None):
        story.append(Paragraph("EVENT SCHEDULE", sec_style))
        rows = [[Paragraph('<b>Time</b>', wrap_style),
                 Paragraph('<b>Activity</b>', wrap_style),
                 Paragraph('<b>Details</b>', wrap_style)]]
        for s in sorted(event.schedules, key=lambda x: x.scheduled_time):
            rows.append([
                Paragraph(s.scheduled_time.strftime('%I:%M %p'), wrap_style),
                Paragraph(s.title, wrap_style),
                Paragraph(s.description or '', small_style),
            ])
        t = Table(rows, colWidths=[1*inch, 1.8*inch, 3.2*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2*inch))

    if getattr(event, 'notes', None):
        story.append(Paragraph("EVENT NOTES", sec_style))
        for note in sorted(event.notes, key=lambda x: x.created_at, reverse=True):
            nd = [
                [Paragraph(f"<b>{note.created_by}</b> • {note.created_at.strftime('%b %d, %Y at %I:%M %p')}", note_h_sty)],
                [Paragraph(note.content, note_b_sty)],
            ]
            nt = Table(nd, colWidths=[5.8*inch])
            nt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fef3c7')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#78350f')),
                ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#fbbf24')),
            ]))
            story.append(nt)
            story.append(Spacer(1, 0.1*inch))

    if getattr(event, 'crew_assignments', None):
        story.append(Paragraph("CREW ASSIGNMENTS", sec_style))
        rows = [[Paragraph('<b>Crew Member</b>', wrap_style),
                 Paragraph('<b>Role</b>', wrap_style),
                 Paragraph('<b>Contact</b>', wrap_style)]]
        for a in event.crew_assignments:
            u = User.query.filter_by(username=a.crew_member).first()
            rows.append([
                Paragraph(a.crew_member, wrap_style),
                Paragraph(a.role or 'Crew Member', wrap_style),
                Paragraph(u.email if u and u.email else 'N/A', small_style),
            ])
        t = Table(rows, colWidths=[2*inch, 2*inch, 2*inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ec4899')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fce7f3')]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2*inch))

    doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    pdf_buffer.seek(0)
    safe_title = re.sub(r'\W+', '_', event.title)
    filename   = f"{safe_title}_Event_Brief_{event.event_date.strftime('%Y%m%d')}.pdf"
    return pdf_buffer, filename
