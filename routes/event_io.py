"""
routes/event_io.py
==================
Import / export for an event's schedule and run list, plus PDF / photo uploads.

Spreadsheets (CSV or Excel .xlsx)
---------------------------------
* Download a template (xlsx or csv) - it has the right columns and example rows.
* Export what is on the event now, in exactly the template layout, so an
  exported file can be edited and imported back.
* Import a file.  Either add to what is there or replace it.  An import is
  all-or-nothing: if any row has a problem nothing is changed and every problem
  is listed with its row number.

PDF / photo attachments
-----------------------
* Attached to the schedule or the run list and shown as a gallery on the event.
* Photos are checked, auto-rotated, shrunk and given a thumbnail; PDFs are
  checked and stored as-is.  Files get random names on disk.

Who can do what: any crew member can download templates, export and view
files.  Admins (the same people who can edit the schedule and run list) import,
upload and delete.
"""

import csv
import io
import os
import re
import uuid
import zipfile
from datetime import date, datetime, time, timedelta

from flask import Blueprint, jsonify, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError

from decorators import crew_required
from extensions import db
from models import CrewRunItem, Event, EventAttachment, EventSchedule, event_files_dir
from routes.events import (
    ApiError, _run_payload, _schedule_payload, event_end, manager_required,
)

event_io_bp = Blueprint('event_io', __name__)

MAX_IMPORT_BYTES = 2 * 1024 * 1024         # spreadsheet size
MAX_IMPORT_ROWS = 500
MAX_SCAN_ROWS = 3000                        # blank-row padding in a sheet is skipped, but not forever
MAX_FILE_BYTES = 15 * 1024 * 1024           # one PDF / photo (the app-wide request limit is 16 MB)
MAX_ATTACHMENTS_PER_TARGET = 30
MAX_PIXELS = 60_000_000
MAX_SIDE = 2400
THUMB_SIDE = 400
MAX_PROBLEMS_SHOWN = 25
CUES = ['Lighting', 'Sound', 'Video', 'Stage', 'Fly', 'Pyro', 'Spot', 'Other']

# key, header shown to the user, column width
KINDS = {
    'schedule': {
        'label': 'Schedule', 'sheet': 'Schedule', 'slug': 'schedule',
        'columns': [('date', 'Date', 14), ('time', 'Time', 12), ('title', 'Title', 36), ('description', 'Description', 60)],
        'required': ('time', 'title'),
    },
    'run': {
        'label': 'Run list', 'sheet': 'Run list', 'slug': 'run-list',
        'columns': [('title', 'Title', 36), ('duration', 'Duration', 14), ('cue_type', 'Cue type', 16),
                    ('description', 'Description', 50), ('notes', 'Notes', 40)],
        'required': ('title',),
    },
}

# Other names people use for the same column (compared lower-case, punctuation squashed)
ALIASES = {
    'schedule': {
        'date': {'date', 'day'},
        'time': {'time', 'start', 'start time', 'when', 'at'},
        'title': {'title', 'what happens', 'item', 'name', 'activity', 'event'},
        'description': {'description', 'details', 'detail', 'desc', 'notes', 'note'},
    },
    'run': {
        'title': {'title', 'item', 'name', 'what'},
        'duration': {'duration', 'length', 'dur', 'running time'},
        'cue_type': {'cue type', 'cue', 'type', 'department', 'dept'},
        'description': {'description', 'details', 'detail', 'desc'},
        'notes': {'notes', 'note', 'comments', 'comment'},
    },
}


def _spec(kind: str) -> dict:
    if kind not in KINDS:
        raise ApiError('Unknown list - expected "schedule" or "run"', 404)
    return KINDS[kind]


# ---------------------------------------------------------------------------
# Reading dates, times and cell values
# ---------------------------------------------------------------------------

DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%y', '%d %b %Y', '%d %B %Y',
                '%d %b %y', '%a %d %b %Y', '%A %d %B %Y')
TIME_FORMATS = ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M:%S %p', '%I %p', '%H%M')


def _text(v) -> str:
    """A cell as clean text.  Undo the leading ' that CSV export adds to stop formulas running."""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'Yes' if v else 'No'
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, timedelta):                       # Excel [h]:mm durations
        mins = int(v.total_seconds() // 60)
        return f'{mins // 60}:{mins % 60:02d}'
    if isinstance(v, time):
        return f'{v.hour}:{v.minute:02d}'
    if isinstance(v, (datetime, date)):
        return v.strftime('%Y-%m-%d')
    s = str(v).replace('\r\n', '\n').replace('\r', '\n').strip()
    if s[:1] == "'" and s[1:2] in ('=', '+', '-', '@'):
        s = s[1:]
    return s


def _parse_date_str(s: str) -> date:
    s = re.sub(r'\s+', ' ', s.strip().rstrip(','))
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f'Couldn\'t read "{s}" as a date (use day/month/year, e.g. 25/10/2026)')


def _parse_time_str(s: str) -> time:
    raw = s
    s = s.strip().upper()
    s = re.sub(r'\s*([AP])\.?\s*M\.?$', r' \1M', s)       # "9.30 a.m." -> "9.30 AM"
    s = re.sub(r'(?<=\d)\.(?=\d)', ':', s)                  # "9.30" -> "9:30"
    s = re.sub(r'\s+', ' ', s)
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f'Couldn\'t read "{raw}" as a time (use e.g. 09:30 or 9:30 AM)')


def _split_date_time(v):
    """Return (date|None, time|None) for whatever is in a Date or Time cell."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, datetime):
        if v.year < 1910:                                  # Excel's "time only" epoch
            return None, v.time().replace(second=0, microsecond=0)
        if v.hour == 0 and v.minute == 0 and v.second == 0:
            return v.date(), None
        return v.date(), v.time().replace(second=0, microsecond=0)
    if isinstance(v, date):
        return v, None
    if isinstance(v, time):
        return None, v.replace(second=0, microsecond=0)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 0 <= v < 1:                                     # fraction of a day
            secs = round(v * 86400)
            return None, time(secs // 3600 % 24, secs // 60 % 60)
        if v >= 1:
            from openpyxl.utils.datetime import from_excel
            return _split_date_time(from_excel(v))
        raise ValueError(f'Couldn\'t read {v} as a date or time')
    s = str(v).strip()
    m = re.match(r'^(.+?)[ T]+(\d{1,2}[:.]\d{2}.*|\d{1,2}\s*[AaPp]\.?[Mm]\.?)$', s)
    if m:                                                  # "25/10/2026 09:30"
        return _parse_date_str(m.group(1)), _parse_time_str(m.group(2))
    try:
        return _parse_date_str(s), None
    except ValueError:
        pass
    return None, _parse_time_str(s.zfill(4) if re.fullmatch(r'\d{3,4}', s) else s)


def _when(date_cell, time_cell, event: Event) -> datetime:
    """Combine the Date and Time cells.  A missing date means the day the event starts."""
    def split(cell, label):
        try:
            return _split_date_time(cell)
        except ValueError as e:
            raise ValueError(f'{label}: {e}')

    d_from_date, t_from_date = split(date_cell, 'Date')
    d_from_time, t_from_time = split(time_cell, 'Time')
    when = t_from_time or t_from_date
    if when is None and isinstance(time_cell, datetime):   # a real Excel date-time at exactly midnight
        when = time(0, 0)
    if when is None:
        raise ValueError('Time is required')
    day = d_from_date or d_from_time
    if day is None:
        dt = datetime.combine(event.event_date.date(), when)
        # Overnight events: 00:30 on a 6pm-2am event belongs to the next morning.
        if dt < event.event_date and dt + timedelta(days=1) <= event_end(event):
            dt += timedelta(days=1)
        return dt
    return datetime.combine(day, when)


# ---------------------------------------------------------------------------
# Reading the uploaded file into rows
# ---------------------------------------------------------------------------

def _read_csv(data: bytes) -> list[list]:
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252', errors='replace')   # Excel on Windows "CSV (Comma delimited)"
    sample = text[:4096]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter
    except csv.Error:
        delim = ','
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i >= MAX_SCAN_ROWS:
            break
        rows.append(row)
    return rows


def _read_xlsx(data: bytes, kind: str) -> list[list]:
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 60 * 1024 * 1024:
                raise ApiError('That spreadsheet is too large to import')
    except zipfile.BadZipFile:
        raise ApiError('That doesn\'t look like a valid .xlsx file. Save it as .xlsx or .csv and try again.')
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ApiError('Couldn\'t open that spreadsheet. Save it as .xlsx or .csv and try again.')
    try:
        names = wb.sheetnames
        preferred = [n for n in names if _norm(n) in (_norm(KINDS[kind]['sheet']), 'schedule', 'run list',
                                                       'run sheet', 'runsheet', 'run')]
        ordered = preferred + [n for n in names if n not in preferred and _norm(n) != 'instructions']
        for name in ordered or names:
            rows = []
            for i, row in enumerate(wb[name].iter_rows(values_only=True)):
                if i >= MAX_SCAN_ROWS:
                    break
                rows.append(list(row))
            if _find_header(kind, rows)[0] is not None:
                return rows
        raise ApiError(_no_header_message(kind))
    finally:
        wb.close()


def _norm(v) -> str:
    return re.sub(r'[\s_\-]+', ' ', str(v or '').strip().lower().rstrip('*').strip())


def _no_header_message(kind: str) -> str:
    need = ' and '.join(h for k, h, _ in KINDS[kind]['columns'] if k in KINDS[kind]['required'])
    return (f'Couldn\'t find a header row with {need} columns. '
            f'Download the template to see the layout.')


def _find_header(kind: str, rows: list[list]):
    """(index of header row, {field: column index}) or (None, None)."""
    for idx, row in enumerate(rows[:20]):
        cols = {}
        for ci, cell in enumerate(row):
            h = _norm(cell)
            if not h:
                continue
            for key, names in ALIASES[kind].items():
                if h in names and key not in cols:
                    cols[key] = ci
                    break
        if all(r in cols for r in KINDS[kind]['required']):
            return idx, cols
    return None, None


def _read_upload(kind: str):
    f = request.files.get('file')
    if not f or not f.filename:
        raise ApiError('Choose a file to import')
    name = f.filename.lower()
    data = f.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise ApiError('That file is too big to import (max 2 MB)')
    if name.endswith('.xls'):
        raise ApiError('Old .xls files aren\'t supported. In Excel choose Save As, then .xlsx or .csv.')
    if name.endswith(('.xlsx', '.xlsm')):
        return _read_xlsx(data, kind)
    if name.endswith(('.csv', '.txt', '.tsv')):
        rows = _read_csv(data)
        if _find_header(kind, rows)[0] is None:
            raise ApiError(_no_header_message(kind))
        return rows
    raise ApiError('Import a .xlsx or .csv file')


# ---------------------------------------------------------------------------
# Turning rows into validated records
# ---------------------------------------------------------------------------

def _cell(row, cols, key):
    i = cols.get(key)
    return row[i] if i is not None and i < len(row) else None


def _is_blank(row) -> bool:
    return all(_text(c) == '' for c in row)


def _is_example(title: str) -> bool:
    return title.lower().rstrip().endswith('(example)')


def _build(kind: str, rows: list[list], event: Event):
    """Return (records, problems).  records are payload dicts ready for the models."""
    h_idx, cols = _find_header(kind, rows)
    records, problems = [], []
    for offset, row in enumerate(rows[h_idx + 1:], start=h_idx + 2):    # 1-based sheet row number
        if _is_blank(row):
            continue
        title = _text(_cell(row, cols, 'title'))
        if _is_example(title):
            continue
        try:
            if kind == 'schedule':
                if not title:
                    raise ApiError('Title is required')
                when = _when(_cell(row, cols, 'date'), _cell(row, cols, 'time'), event)
                payload = _schedule_payload({
                    'title': title,
                    'scheduled_time': when.isoformat(timespec='minutes'),
                    'description': _text(_cell(row, cols, 'description')),
                })
            else:
                payload = _run_payload({
                    'title': title,
                    'description': _text(_cell(row, cols, 'description')),
                    'duration': _text(_cell(row, cols, 'duration')),
                    'cue_type': _text(_cell(row, cols, 'cue_type')),
                    'notes': _text(_cell(row, cols, 'notes')),
                })
        except ApiError as e:
            problems.append({'row': offset, 'message': e.message})
            continue
        except ValueError as e:
            problems.append({'row': offset, 'message': str(e)})
            continue
        records.append(payload)
        if len(records) > MAX_IMPORT_ROWS:
            raise ApiError(f'Too many rows - the limit is {MAX_IMPORT_ROWS} per import')
    return records, problems


@event_io_bp.route('/events/<int:event_id>/io/import/<kind>', methods=['POST'])
@login_required
@crew_required
@manager_required
def import_rows(event_id, kind):
    event = Event.query.get_or_404(event_id)
    _spec(kind)
    mode = request.form.get('mode', 'append')
    if mode not in ('append', 'replace'):
        raise ApiError('Mode must be "append" or "replace"')

    rows = _read_upload(kind)
    records, problems = _build(kind, rows, event)
    if problems:
        shown = problems[:MAX_PROBLEMS_SHOWN]
        n = len(problems)
        raise ApiError(f'Nothing was imported - {n} {"row has a problem" if n == 1 else "rows have problems"}. '
                       f'Fix {"it" if n == 1 else "them"} in the file and try again.',
                       422, problems=shown, more=max(0, n - len(shown)))
    if not records:
        raise ApiError('No rows to import. Add your items under the header row '
                       '(rows marked "(example)" are ignored).')

    replaced = 0
    if kind == 'schedule':
        if mode == 'replace':
            replaced = EventSchedule.query.filter_by(event_id=event_id).delete(synchronize_session=False)
        for rec in records:
            db.session.add(EventSchedule(event_id=event_id, **rec))
    else:
        start = 0
        if mode == 'replace':
            replaced = CrewRunItem.query.filter_by(event_id=event_id).delete(synchronize_session=False)
        else:
            start = db.session.query(db.func.max(CrewRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
        for i, rec in enumerate(records, start=1):
            db.session.add(CrewRunItem(event_id=event_id, order_number=start + i, **rec))
    db.session.commit()
    return jsonify({'success': True, 'imported': len(records), 'replaced': replaced})


# ---------------------------------------------------------------------------
# Template + export
# ---------------------------------------------------------------------------

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _slug(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '-', text or '').strip('-')[:40] or 'event'


def _csv_safe(v) -> str:
    """Stop spreadsheet apps running a cell as a formula (CSV injection). Import undoes this."""
    s = '' if v is None else str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@') else s


def _example_rows(kind: str, event: Event) -> list[list]:
    d = event.event_date.date()
    if kind == 'schedule':
        return [
            [d, time(8, 0), 'Bump in (example)', 'Crew call. Unload truck and set stage.'],
            [d, time(17, 30), 'Doors open (example)', '- House lights to preset\n- Walk-in music on'],
            [None, time(18, 0), 'Show start (example)', 'Leave Date blank to use the event\'s day.'],
        ]
    return [
        ['Walk-in (example)', '', 'Sound', 'Playlist 1 at -12 dB'],
        ['Opening video (example)', '2 min', 'Video', 'Play from Q-Lab, cue 1', 'Wait for MC to finish'],
        ['Blackout (example)', '', 'Lighting', 'Cue 12 - snap to black'],
    ]


def _xlsx(kind: str, event: Event, rows: list[list], *, template: bool) -> io.BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    spec = KINDS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = spec['sheet']
    head_fill = PatternFill('solid', fgColor='1F2937')
    for ci, (key, label, width) in enumerate(spec['columns'], start=1):
        c = ws.cell(row=1, column=ci, value=label)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = head_fill
        c.alignment = Alignment(vertical='center')
        ws.column_dimensions[c.column_letter].width = width
    ws.freeze_panes = 'A2'

    keys = [k for k, _, _ in spec['columns']]
    for r, row in enumerate(rows, start=2):
        for ci, v in enumerate(row, start=1):
            if ci > len(keys):
                break
            c = ws.cell(row=r, column=ci)
            if isinstance(v, str):
                c.value = v
                c.data_type = 's'                     # never let Excel treat text as a formula
            else:
                c.value = v
            key = keys[ci - 1]
            if key == 'date':
                c.number_format = 'dd/mm/yyyy'
            elif key == 'time':
                c.number_format = 'hh:mm'
            elif key in ('duration', 'cue_type'):
                c.number_format = '@'
            if key in ('description', 'notes'):
                c.alignment = Alignment(wrap_text=True, vertical='top')
            else:
                c.alignment = Alignment(vertical='top')
            if template:
                c.font = Font(italic=True, color='808080')

    # Text-format the empty rows below so typed "5 min" / "9:30" aren't mangled
    last = max(len(rows) + 1, 1)
    for r in range(last + 1, last + 201):
        for ci, key in enumerate(keys, start=1):
            if key in ('duration', 'cue_type', 'title'):
                ws.cell(row=r, column=ci).number_format = '@'
            elif key == 'date':
                ws.cell(row=r, column=ci).number_format = 'dd/mm/yyyy'
            elif key == 'time':
                ws.cell(row=r, column=ci).number_format = 'hh:mm'
    if kind == 'run':
        dv = DataValidation(type='list', formula1='"' + ','.join(CUES) + '"', allow_blank=True,
                            showErrorMessage=False)
        ws.add_data_validation(dv)
        dv.add(f'C2:C{last + 200}')

    if template:
        ins = wb.create_sheet('Instructions')
        ins.column_dimensions['A'].width = 110
        if kind == 'schedule':
            lines = [
                f'{spec["label"]} import - {event.title}',
                '',
                'Fill in the "Schedule" sheet, save, then use Import on the event page.',
                '',
                'Time (required): 09:30, 9:30 AM or a real Excel time.',
                'Date (optional): day/month/year, e.g. 25/10/2026. Leave blank to use the day the event starts.',
                '   For an overnight event, a time after midnight with no date lands on the next morning.',
                'Title (required): up to 100 characters.',
                'Description (optional): Markdown works, e.g. "- item" for a bullet list.',
            ]
        else:
            lines = [
                f'{spec["label"]} import - {event.title}',
                '',
                'Fill in the "Run list" sheet, save, then use Import on the event page.',
                '',
                'The run order is the order of the rows.',
                'Title (required): up to 200 characters.',
                'Duration (optional): free text, e.g. "5 min".',
                'Cue type (optional): pick from the list or type your own, e.g. Lighting, Sound, Video.',
                'Description (optional): Markdown works.  Notes (optional): plain text.',
            ]
        lines += ['',
                  'Rows whose title ends with "(example)" are ignored, so you can leave the examples in or delete them.',
                  'Column headings must stay in row 1.  Import accepts .xlsx and .csv.']
        for i, line in enumerate(lines, start=1):
            c = ins.cell(row=i, column=1, value=line)
            c.alignment = Alignment(wrap_text=True)
            if i == 1:
                c.font = Font(bold=True, size=13)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _csv_bytes(kind: str, rows: list[list]) -> io.BytesIO:
    spec = KINDS[kind]
    out = io.StringIO(newline='')
    w = csv.writer(out)
    w.writerow([label for _, label, _ in spec['columns']])
    for row in rows:
        cells = []
        for v in row:
            if isinstance(v, datetime):
                v = v.strftime('%Y-%m-%d %H:%M')
            elif isinstance(v, date):
                v = v.strftime('%Y-%m-%d')
            elif isinstance(v, time):
                v = v.strftime('%H:%M')
            cells.append(_csv_safe(v))
        w.writerow(cells)
    # utf-8 with a BOM so Excel shows accents and emoji correctly
    return io.BytesIO(out.getvalue().encode('utf-8-sig'))


def _current_rows(kind: str, event_id: int) -> list[list]:
    if kind == 'schedule':
        items = EventSchedule.query.filter_by(event_id=event_id).order_by(
            EventSchedule.scheduled_time, EventSchedule.id).all()
        return [[s.scheduled_time.date(), s.scheduled_time.time().replace(second=0, microsecond=0),
                 s.title, s.description or ''] for s in items]
    items = CrewRunItem.query.filter_by(event_id=event_id).order_by(
        CrewRunItem.order_number, CrewRunItem.id).all()
    return [[r.title, r.duration or '', r.cue_type or '', r.description or '', r.notes or ''] for r in items]


def _send(buf: io.BytesIO, fmt: str, filename: str):
    return send_file(buf, mimetype=XLSX_MIME if fmt == 'xlsx' else 'text/csv', as_attachment=True,
                     download_name=filename, max_age=0)


def _check_fmt(fmt: str):
    if fmt not in ('xlsx', 'csv'):
        raise ApiError('Format must be xlsx or csv', 404)


@event_io_bp.route('/events/<int:event_id>/io/template/<kind>.<fmt>')
@login_required
@crew_required
def download_template(event_id, kind, fmt):
    event = Event.query.get_or_404(event_id)
    spec = _spec(kind)
    _check_fmt(fmt)
    rows = _example_rows(kind, event)
    buf = _xlsx(kind, event, rows, template=True) if fmt == 'xlsx' else _csv_bytes(kind, rows)
    return _send(buf, fmt, f'{spec["slug"]}-template.{fmt}')


@event_io_bp.route('/events/<int:event_id>/io/export/<kind>.<fmt>')
@login_required
@crew_required
def export_rows(event_id, kind, fmt):
    event = Event.query.get_or_404(event_id)
    spec = _spec(kind)
    _check_fmt(fmt)
    rows = _current_rows(kind, event_id)
    buf = _xlsx(kind, event, rows, template=False) if fmt == 'xlsx' else _csv_bytes(kind, rows)
    return _send(buf, fmt, f'{_slug(event.title)}-{spec["slug"]}.{fmt}')


# ---------------------------------------------------------------------------
# PDF / photo attachments
# ---------------------------------------------------------------------------

def _clean_name(name: str) -> str:
    name = os.path.basename((name or '').replace('\\', '/'))
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()
    return name[:200] or 'file'


def serialize_attachment(a: EventAttachment) -> dict:
    file_url = url_for('event_io.attachment_file', aid=a.id)
    return {
        'id': a.id, 'target': a.target, 'kind': a.kind, 'name': a.original_name or 'file',
        'size': a.size_bytes or 0, 'url': file_url, 'download': file_url + '?download=1',
        'thumb': url_for('event_io.attachment_thumb', aid=a.id) if a.thumb_name else None,
    }


def attachments_for_event(event_id: int) -> dict:
    """{'schedule': [...], 'run': [...]} for the event page."""
    out = {'schedule': [], 'run': []}
    for a in EventAttachment.query.filter_by(event_id=event_id).order_by(EventAttachment.id).all():
        out.setdefault(a.target, []).append(serialize_attachment(a))
    return out


def _process_image(data: bytes):
    """Validate, orient, shrink.  Returns (main_bytes, thumb_bytes, ext, mimetype)."""
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        if fmt not in ('JPEG', 'PNG', 'WEBP'):
            raise ApiError('Only PDF, JPG, PNG or WebP files can be uploaded')
        if img.width * img.height > MAX_PIXELS:
            raise ApiError('That image is too large')
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ApiError('Only PDF, JPG, PNG or WebP files can be uploaded')

    img = ImageOps.exif_transpose(img)                       # phone photos: honour rotation
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    def flatten(im):                                         # JPEG has no transparency
        if im.mode in ('RGBA', 'LA', 'P'):
            im = im.convert('RGBA')
            bg = Image.new('RGB', im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            return bg
        return im.convert('RGB')

    main = io.BytesIO()
    if fmt == 'PNG':                                         # keep screenshots / run sheets crisp
        out = img if img.mode in ('RGB', 'RGBA', 'L') else img.convert('RGBA')
        out.save(main, 'PNG', optimize=True)
        ext, mime = 'png', 'image/png'
    else:
        flatten(img).save(main, 'JPEG', quality=88, optimize=True, progressive=True)
        ext, mime = 'jpg', 'image/jpeg'

    thumb = io.BytesIO()
    t = flatten(img)
    t.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
    t.save(thumb, 'JPEG', quality=80, optimize=True)
    return main.getvalue(), thumb.getvalue(), ext, mime


def _store_one(event: Event, target: str, f) -> EventAttachment:
    data = f.read(MAX_FILE_BYTES + 1)
    if not data:
        raise ApiError('That file is empty')
    if len(data) > MAX_FILE_BYTES:
        raise ApiError(f'Too large (max {MAX_FILE_BYTES // (1024 * 1024)} MB per file)')

    folder = event_files_dir()
    os.makedirs(folder, exist_ok=True)
    base = uuid.uuid4().hex
    written = []
    try:
        if b'%PDF-' in data[:1024]:
            kind, ext, mime, thumb_name, body = 'pdf', 'pdf', 'application/pdf', None, data
        else:
            body, thumb_bytes, ext, mime = _process_image(data)
            kind, thumb_name = 'image', f'{base}_t.jpg'
            with open(os.path.join(folder, thumb_name), 'wb') as fh:
                fh.write(thumb_bytes)
            written.append(thumb_name)
        stored = f'{base}.{ext}'
        with open(os.path.join(folder, stored), 'wb') as fh:
            fh.write(body)
        written.append(stored)
        att = EventAttachment(
            event_id=event.id, target=target, kind=kind, stored_name=stored, thumb_name=thumb_name,
            original_name=_clean_name(f.filename), mimetype=mime, size_bytes=len(body),
            uploaded_by=current_user.username)
        db.session.add(att)
        db.session.flush()
        return att
    except Exception:
        for name in written:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        raise


@event_io_bp.route('/events/<int:event_id>/attachments', methods=['POST'])
@login_required
@crew_required
@manager_required
def upload_attachments(event_id):
    event = Event.query.get_or_404(event_id)
    target = request.form.get('target', '')
    if target not in KINDS:
        raise ApiError('Choose whether the file is for the schedule or the run list')
    files = [f for f in request.files.getlist('files') + request.files.getlist('file') if f and f.filename]
    if not files:
        raise ApiError('Choose a PDF or photo to upload')

    existing = EventAttachment.query.filter_by(event_id=event_id, target=target).count()
    added, errors = [], []
    for f in files:
        if existing + len(added) >= MAX_ATTACHMENTS_PER_TARGET:
            errors.append({'name': _clean_name(f.filename),
                           'error': f'Limit of {MAX_ATTACHMENTS_PER_TARGET} files reached'})
            continue
        try:
            added.append(_store_one(event, target, f))
        except ApiError as e:
            errors.append({'name': _clean_name(f.filename), 'error': e.message})
    db.session.commit()

    payload = {'success': bool(added), 'added': [serialize_attachment(a) for a in added], 'errors': errors}
    if not added:
        payload['error'] = errors[0]['error'] if len(errors) == 1 else 'None of the files could be uploaded'
        return jsonify(payload), 400
    return jsonify(payload)


def _attachment_or_404(aid: int) -> EventAttachment:
    return EventAttachment.query.get_or_404(aid)


def _serve(name: str, mimetype: str, download_name=None, as_attachment=False):
    resp = send_from_directory(event_files_dir(), name, mimetype=mimetype,
                               as_attachment=as_attachment, download_name=download_name, max_age=3600)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@event_io_bp.route('/events/attachments/<int:aid>/file')
@login_required
@crew_required
def attachment_file(aid):
    a = _attachment_or_404(aid)
    return _serve(a.stored_name, a.mimetype or 'application/octet-stream',
                  download_name=a.original_name, as_attachment=request.args.get('download') == '1')


@event_io_bp.route('/events/attachments/<int:aid>/thumb')
@login_required
@crew_required
def attachment_thumb(aid):
    a = _attachment_or_404(aid)
    if not a.thumb_name:
        raise ApiError('No thumbnail', 404)
    return _serve(a.thumb_name, 'image/jpeg')


@event_io_bp.route('/events/attachments/<int:aid>', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def delete_attachment(aid):
    db.session.delete(_attachment_or_404(aid))
    db.session.commit()                      # the files are removed once this commits
    return jsonify({'success': True})
