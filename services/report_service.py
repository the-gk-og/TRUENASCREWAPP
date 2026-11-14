"""services/report_service.py — printable PDFs for an event.

One function builds either the whole event pack or just the parts asked for
(for example only the run list, to hand to the stage manager). The layout is
plain black on white with thin rules, so it prints cleanly and photocopies well.
"""

import io, re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable, KeepTogether
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm

# key -> heading, in the order they are printed
PDF_PARTS = {
    'overview': 'Overview',
    'team':     'Team and shifts',
    'schedule': 'Schedule',
    'run':      'Run list',
    'tasks':    'Tasks',
    'notes':    'Notes',
    'callsheet': 'Call sheet',      # who arrives when: asked for by name, not part of the whole pack
}
PACK_PARTS = [k for k in PDF_PARTS if k != 'callsheet']

INK, MUTED, RULE, SHADE = (colors.HexColor(c) for c in ('#111418', '#5b6472', '#c9ced6', '#f1f3f5'))


def _register_fonts():
    """Use DejaVu Sans when the server has it: it prints accented, Greek and Cyrillic names, which
    the built-in Helvetica can't. Falls back to Helvetica so a missing font never breaks a PDF."""
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for folder in ('/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/TTF', '/usr/share/fonts/dejavu',
                   '/usr/share/fonts/dejavu-sans-fonts', '/Library/Fonts', 'C:/Windows/Fonts'):
        regular, bold = os.path.join(folder, 'DejaVuSans.ttf'), os.path.join(folder, 'DejaVuSans-Bold.ttf')
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont('SW-Regular', regular))
                pdfmetrics.registerFont(TTFont('SW-Bold', bold))
                pdfmetrics.registerFontFamily('SW-Regular', normal='SW-Regular', bold='SW-Bold',
                                              italic='SW-Regular', boldItalic='SW-Bold')
                return 'SW-Regular', 'SW-Bold'
            except Exception:
                break
    return 'Helvetica', 'Helvetica-Bold'


FONT, FONT_BOLD = _register_fonts()
MARGIN = 18 * mm
WIDTH  = A4[0] - 2 * MARGIN


def _style(name, **kw):
    base = dict(fontName=FONT, fontSize=10, leading=13.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    'eyebrow': _style('eyebrow', fontName=FONT_BOLD, fontSize=9, textColor=MUTED, spaceAfter=2),
    'title':   _style('title', fontName=FONT_BOLD, fontSize=22, leading=26, spaceAfter=3),
    'sub':     _style('sub', fontSize=11, leading=15, textColor=MUTED, spaceAfter=10),
    'h2':      _style('h2', fontName=FONT_BOLD, fontSize=13, leading=16, spaceBefore=14, spaceAfter=6),
    'body':    _style('body'),
    'bold':    _style('bold', fontName=FONT_BOLD),
    'small':   _style('small', fontSize=8.5, leading=11.5, textColor=MUTED),
    'head':    _style('head', fontName=FONT_BOLD, fontSize=8, leading=10, textColor=MUTED),
    'big':     _style('big', fontName=FONT_BOLD, fontSize=11, leading=14),
    'num':     _style('num', fontName=FONT_BOLD, fontSize=11, leading=14, alignment=1),
}


class _TickBox(Flowable):
    """An empty square to tick with a pen (filled in when the task is already done)."""
    def __init__(self, done=False, size=9):
        super().__init__()
        self.done, self.width, self.height = done, size, size

    def draw(self):
        c = self.canv
        c.setStrokeColor(INK)
        c.setLineWidth(0.8)
        c.rect(0, 0, self.width, self.height)
        if self.done:
            c.setLineWidth(1.4)
            c.lines([(2, self.height / 2, self.width * .42, 2), (self.width * .42, 2, self.width - 1.5, self.height - 1.5)])


def _plain(text):
    """Markdown or free text -> safe one-paragraph markup (line breaks kept)."""
    text = str(text or '').strip()
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)           # images
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)            # links
    text = re.sub(r'^\s{0,3}#{1,6}\s*', '', text, flags=re.M)       # headings
    text = re.sub(r'(\*\*|__|`|~~)', '', text)
    text = re.sub(r'^\s*[-*+]\s+', '- ', text, flags=re.M)
    return escape(text).replace('\n', '<br/>')


def _p(text, style='body'):
    return Paragraph(_plain(text), S[style])


def _t(dt):
    return dt.strftime('%I:%M %p').lstrip('0').lower()


def _d(dt):
    return dt.strftime('%a %d %b').replace(' 0', ' ')


def _when(start, end=None, all_day=False):
    if all_day:
        return f'{_d(start)} to {_d(end)}, all day' if end and end.date() != start.date() else f'{_d(start)}, all day'
    if not end:
        return f'{_d(start)}, {_t(start)}'
    if end.date() == start.date():
        return f'{_d(start)}, {_t(start)} - {_t(end)}'
    return f'{_d(start)} {_t(start)} to {_d(end)} {_t(end)}'


def duration_minutes(text):
    """'5 min', '1h 30', '2:30' (min:sec), '90s' or a bare number of minutes -> minutes, else None."""
    t = str(text or '').strip().lower()
    if not t:
        return None
    m = re.fullmatch(r'(\d+):(\d{2})(?::(\d{2}))?', t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 60 + b + int(c) / 60 if c else a + b / 60
    total, found = 0.0, False
    for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b', t):
        found = True
        total += float(num) * (60 if unit[0] == 'h' else 1 if unit[0] == 'm' else 1 / 60)
    if found:
        return total
    return float(t) if re.fullmatch(r'\d+(?:\.\d+)?', t) else None


def run_start_for(event):
    """When the run list starts: the time an admin set for this event, else the event's start."""
    from services.settings_service import get_setting
    hhmm = get_setting(f'event.run_start.{event.id}', '') or ''
    m = re.fullmatch(r'(\d{2}):(\d{2})', hhmm)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return event.event_date.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return event.event_date


def _length(minutes):
    minutes = int(round(minutes))
    return f'{minutes // 60} h {minutes % 60:02d} min' if minutes >= 60 else f'{minutes} min'


def _table(head, rows, widths, extra=()):
    data = [[Paragraph(escape(h), S['head']) for h in head]] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 1, INK),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, RULE),
        ('TOPPADDING', (0, 0), (-1, 0), 2), ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 6), ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        *extra,
    ]))
    return t


def _nothing(text):
    return Paragraph(escape(text), S['small'])


# ── sections ────────────────────────────────────────────────────────────────

def _overview(event, end):
    from services.event_times import times_for, range_text
    from services.user_names import name_for
    rows = [['When', _when(event.event_date, end, event.all_day)]]
    for t in times_for(event):
        rows.append([t.label, range_text(t).replace('→', 'to').replace('–', '-')])
    rows.append(['Where', event.location or 'Not set'])
    if event.created_by:
        rows.append(['Organiser', name_for(event.created_by) or event.created_by])
    table = Table([[Paragraph(escape(k), S['small']), _p(v)] for k, v in rows], colWidths=[28 * mm, WIDTH - 28 * mm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 0.5, RULE),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
    ]))
    out = [table]
    if event.description:
        out += [Spacer(1, 8), _p(event.description)]
    return out


def _team(event):
    from extensions import db
    from models import Shift, ShiftAssignment, User
    people = {}
    for ca in event.crew_assignments:
        user = User.query.filter_by(username=ca.crew_member).first()
        if user:
            people.setdefault(user.id, {'user': user, 'role': ca.role or '', 'shifts': []})
    pairs = (db.session.query(ShiftAssignment, Shift).join(Shift, ShiftAssignment.shift_id == Shift.id)
             .filter(Shift.event_id == event.id).order_by(Shift.shift_date).all())
    for a, s in pairs:
        if a.user:
            people.setdefault(a.user.id, {'user': a.user, 'role': '', 'shifts': []})['shifts'].append((a, s))
    if not people:
        return [_nothing('Nobody is on this event yet.')]
    status = lambda st: 'Confirmed' if st in ('accepted', 'confirmed') else 'Declined' if st == 'rejected' else 'Awaiting reply'
    rows = []
    for p in sorted(people.values(), key=lambda p: p['user'].shown_name.lower()):
        name = Paragraph(escape(p['user'].shown_name), S['bold'])
        if not p['shifts']:
            rows.append([name, _nothing('No shift times set'), _p(p['role']), ''])
        for i, (a, s) in enumerate(p['shifts']):
            rows.append([name if i == 0 else '', _p(_when(s.shift_date, s.shift_end_date)), _p(s.role or ''), _p(status(a.status))])
    return [_table(['Name', 'Shift', 'Role', 'Reply'], rows, [WIDTH * .26, WIDTH * .36, WIDTH * .2, WIDTH * .18])]


def _schedule(event):
    from models import EventSchedule
    items = EventSchedule.query.filter_by(event_id=event.id).order_by(EventSchedule.scheduled_time).all()
    if not items:
        return [_nothing('No schedule items.')]
    one_day = len({s.scheduled_time.date() for s in items}) == 1
    rows = [[Paragraph(escape(_t(s.scheduled_time) if one_day else f'{_d(s.scheduled_time)}, {_t(s.scheduled_time)}'), S['big']),
             [Paragraph(escape(s.title), S['big'])] + ([_p(s.description, 'small')] if s.description else [])]
            for s in items]
    w = 24 * mm if one_day else 44 * mm
    return [_table(['Time', 'What'], rows, [w, WIDTH - w])]


def _run(event):
    from models import CrewRunItem
    items = CrewRunItem.query.filter_by(event_id=event.id).order_by(CrewRunItem.order_number, CrewRunItem.id).all()
    if not items:
        return [_nothing('No run list items.')]
    from datetime import timedelta
    lengths = [duration_minutes(r.duration) for r in items]
    timed = any(m is not None for m in lengths)          # no lengths at all: leave the clock column out
    clock, rows = run_start_for(event), []
    for n, (r, mins) in enumerate(zip(items, lengths), start=1):
        what = [Paragraph(escape(r.title), S['big'])]
        if r.description:
            what.append(_p(r.description, 'small'))
        row = [Paragraph(str(n), S['num'])]
        if timed:
            row.append(Paragraph(escape(_t(clock)), S['bold']))
            clock += timedelta(minutes=mins or 0)
        rows.append(row + [what, _p(r.duration or ''), _p(r.cue_type or ''), _p(r.notes or '', 'small')])
    if not timed:
        return [_table(['#', 'Item', 'Length', 'Cue', 'Notes'], rows,
                       [10 * mm, WIDTH * .42, 20 * mm, 22 * mm, WIDTH * .58 - 52 * mm],
                       extra=[('BACKGROUND', (0, 1), (0, -1), SHADE)])]
    missing = sum(1 for m in lengths if m is None)
    total = f'Running time {_length(sum(m or 0 for m in lengths))}, finishing about {_t(clock)}.'
    if missing:
        total += f' {missing} item{"" if missing == 1 else "s"} ha{"s" if missing == 1 else "ve"} no length, so the times after {"it" if missing == 1 else "them"} are early.'
    return [_table(['#', 'Starts', 'Item', 'Length', 'Cue', 'Notes'], rows,
                   [10 * mm, 20 * mm, WIDTH * .38, 20 * mm, 22 * mm, WIDTH * .62 - 72 * mm],
                   extra=[('BACKGROUND', (0, 1), (0, -1), SHADE)]),
            Spacer(1, 6), Paragraph(escape(total), S['small'])]


def _callsheet(event):
    """Who arrives when, earliest first: the page that gets taped to the wall."""
    from extensions import db
    from models import Shift, ShiftAssignment, User, EventSchedule
    pairs = (db.session.query(ShiftAssignment, Shift).join(Shift, ShiftAssignment.shift_id == Shift.id)
             .filter(Shift.event_id == event.id).order_by(Shift.shift_date).all())
    pairs = [(a, s) for a, s in pairs if a.user and a.status != 'rejected']
    one_day = len({s.shift_date.date() for _, s in pairs}) <= 1
    rows, seen = [], set()
    for a, s in sorted(pairs, key=lambda x: (x[1].shift_date, x[0].user.shown_name.lower())):
        seen.add(a.user.id)
        call = _t(s.shift_date) if one_day else f'{_d(s.shift_date)}, {_t(s.shift_date)}'
        rows.append([Paragraph(escape(call), S['big']), Paragraph(escape(a.user.shown_name), S['big']),
                     _p(s.role or ''), _p(f'until {_t(s.shift_end_date)}' if s.shift_end_date else ''),
                     _p('' if a.status in ('accepted', 'confirmed') else 'Not confirmed', 'small')])
    for ca in event.crew_assignments:                     # on the event, but no shift time yet
        user = User.query.filter_by(username=ca.crew_member).first()
        if user and user.id not in seen:
            seen.add(user.id)
            rows.append([_nothing('No time set'), Paragraph(escape(user.shown_name), S['big']), _p(ca.role or ''), '', ''])
    if not rows:
        return [_nothing('Nobody is on this event yet.')]
    w = 26 * mm if one_day else 46 * mm
    out = [_table(['Call', 'Name', 'Role', '', ''], rows, [w, WIDTH * .34, WIDTH * .22, 26 * mm, WIDTH * .44 - w - 26 * mm])]
    if EventSchedule.query.filter_by(event_id=event.id).count():
        out += [Paragraph('Key times', S['h2'])] + _schedule(event)
    return out


def _tasks(event):
    from routes.event_tasks import tasks_for_event
    tasks = tasks_for_event(event)
    if not tasks:
        return [_nothing('No tasks.')]
    rows = []
    for t in tasks:
        what = [Paragraph(escape(t['title']), S['bold'])]
        if t['description']:
            what.append(_p(t['description'], 'small'))
        due = datetime.strptime(t['due'], '%Y-%m-%d').strftime('%a %d %b').replace(' 0', ' ') if t['due'] else ''
        rows.append([_TickBox(t['done']), what, _p(t['assignee'] or 'Anyone'), _p(due)])
    return [_table(['', 'Task', 'Who', 'Due'], rows, [9 * mm, WIDTH - 9 * mm - 40 * mm - 26 * mm, 40 * mm, 26 * mm])]


def _notes(event):
    from models import EventNote
    from services.user_names import name_for
    notes = EventNote.query.filter_by(event_id=event.id).order_by(EventNote.created_at.desc()).all()
    if not notes:
        return [_nothing('No notes.')]
    out = []
    for n in notes:
        out.append(KeepTogether([
            Paragraph(f'<b>{escape(name_for(n.created_by) or n.created_by or "")}</b> · {n.created_at.strftime("%d %b %Y, %I:%M %p")}', S['small']),
            _p(n.content), Spacer(1, 8)]))
    return out


_BUILD = {'overview': lambda e, end: _overview(e, end), 'team': lambda e, end: _team(e),
          'schedule': lambda e, end: _schedule(e), 'run': lambda e, end: _run(e),
          'tasks': lambda e, end: _tasks(e), 'notes': lambda e, end: _notes(e),
          'callsheet': lambda e, end: _callsheet(e)}


def generate_event_pdf(event_id: int, parts=None):
    """Return (BytesIO, filename). `parts` is a list of PDF_PARTS keys; None or empty means all of them."""
    from models import Event
    event = Event.query.get_or_404(event_id)
    chosen = [k for k in PDF_PARTS if k in (parts or PACK_PARTS)] or list(PACK_PARTS)
    single = len(chosen) == 1
    kind = PDF_PARTS[chosen[0]] if single else 'Event pack'

    end = event.event_end_date
    printed = datetime.now().strftime('%d %b %Y, %I:%M %p').lstrip('0')

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT_BOLD, 9)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, A4[1] - 11 * mm, event.title[:70])
        canvas.setFont(FONT, 9)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - MARGIN, A4[1] - 11 * mm, kind)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, A4[1] - 13 * mm, A4[0] - MARGIN, A4[1] - 13 * mm)
        canvas.setFont(FONT, 8)
        canvas.drawString(MARGIN, 10 * mm, f'ShowWise · printed {printed}')
        canvas.drawRightString(A4[0] - MARGIN, 10 * mm, f'Page {canvas.getPageNumber()}')
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=19 * mm, bottomMargin=17 * mm,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            title=f'{event.title} - {kind}', author='ShowWise')
    story = [Paragraph(escape(kind.upper()), S['eyebrow']),
             Paragraph(escape(event.title), S['title']),
             Paragraph(escape(_when(event.event_date, end, event.all_day) + (f' · {event.location}' if event.location else '')), S['sub'])]
    for key in chosen:
        if not single:
            story.append(Paragraph(escape(PDF_PARTS[key]), S['h2']))
        story += _BUILD[key](event, end)

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    buf.seek(0)
    safe = re.sub(r'\W+', '_', event.title).strip('_') or 'event'
    filename = f"{safe}_{re.sub(r'[^a-z]+', '_', kind.lower())}_{event.event_date.strftime('%Y%m%d')}.pdf"
    return buf, filename
