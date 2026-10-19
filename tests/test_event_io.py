"""Tests for schedule / run list import-export and PDF / photo attachments.  Run: pytest tests/test_event_io.py"""
import io
import os
import sys
from datetime import datetime, time

import pytest
from flask import g
from flask.testing import FlaskClient
from openpyxl import Workbook, load_workbook
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                     # noqa: E402
from extensions import db                                      # noqa: E402
from models import CrewRunItem, Event, EventAttachment, EventSchedule, User   # noqa: E402


class _Client(FlaskClient):
    def open(self, *a, **k):
        g.pop('_login_user', None)
        return super().open(*a, **k)


@pytest.fixture()
def app(tmp_path):
    app = create_app('testing')
    app.test_client_class = _Client
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    with app.app_context():
        db.create_all()
        for name, admin in (('boss', True), ('alice', False)):
            db.session.add(User(username=name, is_admin=admin, user_role='crew', email=f'{name}@x.test'))
        db.session.add(Event(title='Gala Night', event_date=datetime(2026, 11, 10, 18, 0),
                             event_end_date=datetime(2026, 11, 11, 2, 0), created_by='boss'))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, username):
    c = app.test_client()
    uid = User.query.filter_by(username=username).first().id
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


@pytest.fixture()
def admin(app): return client_for(app, 'boss')
@pytest.fixture()
def alice(app): return client_for(app, 'alice')


def eid(): return Event.query.first().id


def csv_file(text, name='x.csv'):
    return (io.BytesIO(text.encode('utf-8')), name)


def xlsx_file(rows, sheet='Schedule', name='x.xlsx'):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return (buf, name)


def do_import(c, kind, file, mode='append'):
    return c.post(f'/events/{eid()}/io/import/{kind}', data={'file': file, 'mode': mode},
                  content_type='multipart/form-data')


def sched():
    return [(s.scheduled_time, s.title, s.description) for s in
            EventSchedule.query.order_by(EventSchedule.scheduled_time).all()]


def runs():
    return [(r.order_number, r.title, r.duration, r.cue_type, r.description, r.notes) for r in
            CrewRunItem.query.order_by(CrewRunItem.order_number).all()]


# ----------------------------------------------------------------- templates

@pytest.mark.parametrize('kind,headers', [
    ('schedule', ['Date', 'Time', 'Title', 'Description']),
    ('run', ['Title', 'Duration', 'Cue type', 'Description', 'Notes']),
])
def test_templates_download_and_have_right_columns(app, alice, kind, headers):
    r = alice.get(f'/events/{eid()}/io/template/{kind}.xlsx')            # any crew member can download
    assert r.status_code == 200 and 'spreadsheetml' in r.mimetype
    wb = load_workbook(io.BytesIO(r.data))
    assert [c.value for c in wb.worksheets[0][1]] == headers
    assert 'Instructions' in wb.sheetnames
    r = alice.get(f'/events/{eid()}/io/template/{kind}.csv')
    assert r.status_code == 200 and r.data.startswith(b'\xef\xbb\xbf' + headers[0].encode())
    assert alice.get(f'/events/{eid()}/io/template/{kind}.pdf').status_code == 404
    assert alice.get(f'/events/{eid()}/io/template/nope.csv').status_code == 404


@pytest.mark.parametrize('fmt', ['xlsx', 'csv'])
@pytest.mark.parametrize('kind', ['schedule', 'run'])
def test_untouched_template_imports_nothing_but_says_so(app, admin, kind, fmt):
    r = admin.get(f'/events/{eid()}/io/template/{kind}.{fmt}')
    r = do_import(admin, kind, (io.BytesIO(r.data), f'template.{fmt}'))
    assert r.status_code == 400 and 'No rows' in r.get_json()['error']        # examples are ignored


# ------------------------------------------------------------ schedule import

def test_csv_schedule_import_formats(app, admin):
    r = do_import(admin, 'schedule', csv_file(
        'Date,Time,Title,Description\n'
        '10/11/2026,08:00,Bump in,"- unload\n- set stage"\n'      # day/month/year, multi-line markdown
        ',5:30 PM,Doors,\n'                                       # no date -> event day, 12-hour time
        '2026-11-10,6.00pm,Show start,\n'
        '10 Nov 2026,1930,Interval,\n'
        ',00:30,Strike,after midnight\n'))                        # overnight event -> next morning
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['imported'] == 5
    with app.app_context():
        got = sched()
    assert [t for t, _, _ in got] == [
        datetime(2026, 11, 10, 8, 0), datetime(2026, 11, 10, 17, 30), datetime(2026, 11, 10, 18, 0),
        datetime(2026, 11, 10, 19, 30), datetime(2026, 11, 11, 0, 30)]
    assert got[0][2] == '- unload\n- set stage'


def test_csv_semicolon_and_cp1252(app, admin):
    raw = 'Time;Title;Description\n09:00;Café opens;Crème\n'.encode('cp1252')
    r = do_import(admin, 'schedule', (io.BytesIO(raw), 'euro.csv'))
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        assert sched()[0][1:] == ('Café opens', 'Crème')


def test_xlsx_schedule_real_cells_and_header_variants(app, admin):
    r = do_import(admin, 'schedule', xlsx_file([
        ['Notes about this sheet'],                                # junk above the header is skipped
        ['Start time', 'What happens', 'Details'],
        [time(9, 15), 'Sound check', 'all mics'],
        [datetime(2026, 11, 10, 20, 0), 'Headliner', None],         # full Excel date-time in the time column
        [0.5, 'Lunch', None],                                       # raw Excel fraction of a day = 12:00
    ]))
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        assert [(t.hour, t.minute, n) for t, n, _ in sched()] == [
            (9, 15, 'Sound check'), (12, 0, 'Lunch'), (20, 0, 'Headliner')]


def test_import_picks_the_right_sheet(app, admin):
    wb = Workbook()
    wb.active.title = 'Instructions'
    wb.active.append(['Read me'])
    ws = wb.create_sheet('Schedule')
    ws.append(['Time', 'Title'])
    ws.append(['10:00', 'Real item'])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    assert do_import(admin, 'schedule', (buf, 'two.xlsx')).status_code == 200
    with app.app_context():
        assert sched()[0][1] == 'Real item'


def test_import_is_all_or_nothing_with_row_numbers(app, admin):
    r = do_import(admin, 'schedule', csv_file(
        'Time,Title\n09:00,Fine\nlunchtime,Bad time\n10:00,\n11:00,' + 'x' * 101 + '\n'))
    assert r.status_code == 422
    j = r.get_json()
    rows = {p['row']: p['message'] for p in j['problems']}
    assert set(rows) == {3, 4, 5}
    assert rows[3].startswith('Time:') and 'required' in rows[4] and 'too long' in rows[5]
    with app.app_context():
        assert sched() == []                                       # nothing was saved


def test_replace_vs_append(app, admin):
    do_import(admin, 'schedule', csv_file('Time,Title\n09:00,A\n10:00,B\n'))
    do_import(admin, 'schedule', csv_file('Time,Title\n11:00,C\n'))
    with app.app_context():
        assert [t for _, t, _ in sched()] == ['A', 'B', 'C']
    r = do_import(admin, 'schedule', csv_file('Time,Title\n12:00,D\n'), mode='replace')
    assert r.get_json() == {'success': True, 'imported': 1, 'replaced': 3}
    with app.app_context():
        assert [t for _, t, _ in sched()] == ['D']
    assert do_import(admin, 'schedule', csv_file('Time,Title\n12:00,D\n'), mode='nuke').status_code == 400


# ----------------------------------------------------------- run list import

def test_run_list_import_order_and_append(app, admin):
    r = do_import(admin, 'run', xlsx_file([
        ['Title', 'Duration', 'Cue type', 'Description', 'Notes'],
        ['Walk-in', None, 'Sound', 'Playlist 1', None],
        ['Video', '2 min', 'Video', None, 'wait for MC'],
        [None, None, None, None, None],                             # blank row skipped
        ['Blackout (example)', None, None, None, None],             # example row skipped
        ['Finale', 90, 'Lighting', None, None],                     # a number in a text column
    ], sheet='Run list'))
    assert r.status_code == 200 and r.get_json()['imported'] == 3
    r = do_import(admin, 'run', csv_file('Title,Cue\nExtra,Pyro\n'))
    assert r.status_code == 200
    with app.app_context():
        assert runs() == [
            (1, 'Walk-in', '', 'Sound', 'Playlist 1', ''), (2, 'Video', '2 min', 'Video', '', 'wait for MC'),
            (3, 'Finale', '90', 'Lighting', '', ''), (4, 'Extra', '', 'Pyro', '', '')]


def test_bad_files_get_clear_errors(app, admin):
    assert 'xlsx or .csv' in do_import(admin, 'run', csv_file('x', 'notes.docx')).get_json()['error']
    assert '.xls' in do_import(admin, 'run', csv_file('x', 'old.xls')).get_json()['error']
    assert 'valid .xlsx' in do_import(admin, 'run', csv_file('not a zip', 'fake.xlsx')).get_json()['error']
    assert 'header row' in do_import(admin, 'run', csv_file('Foo,Bar\n1,2\n')).get_json()['error']
    assert 'Choose a file' in admin.post(f'/events/{eid()}/io/import/run', data={},
                                         content_type='multipart/form-data').get_json()['error']
    big = csv_file('Title\n' + 'a\n' * (1024 * 1024 + 10))
    assert 'too big' in do_import(admin, 'run', big).get_json()['error']


def test_row_limit(app, admin):
    r = do_import(admin, 'run', csv_file('Title\n' + ''.join(f'Item {i}\n' for i in range(501))))
    assert r.status_code == 400 and 'Too many rows' in r.get_json()['error']
    with app.app_context():
        assert runs() == []


# ------------------------------------------------------------ export + safety

@pytest.mark.parametrize('fmt', ['xlsx', 'csv'])
def test_export_round_trips(app, admin, fmt):
    do_import(admin, 'schedule', csv_file('Date,Time,Title,Description\n10/11/2026,09:00,Load in,"a, b"\n,17:00,Doors,\n'))
    do_import(admin, 'run', csv_file('Title,Duration,Cue type,Description,Notes\nOne,1 min,Sound,d,n\nTwo,,,,\n'))
    with app.app_context():
        before_s, before_r = sched(), runs()
    for kind in ('schedule', 'run'):
        data = admin.get(f'/events/{eid()}/io/export/{kind}.{fmt}')
        assert data.status_code == 200 and 'gala-night' in data.headers['Content-Disposition'].lower()
        r = do_import(admin, kind, (io.BytesIO(data.data), f'back.{fmt}'), mode='replace')
        assert r.status_code == 200, r.get_json()
    with app.app_context():
        assert sched() == before_s
        assert [x[1:] for x in runs()] == [x[1:] for x in before_r]


@pytest.mark.parametrize('fmt', ['xlsx', 'csv'])
def test_formula_like_text_is_safe_and_round_trips(app, admin, fmt):
    with app.app_context():
        db.session.add(CrewRunItem(event_id=eid(), order_number=1, title='=HYPERLINK("http://evil")',
                                   description='- item one\n- item two', notes='+1 and @x'))
        db.session.commit()
    data = admin.get(f'/events/{eid()}/io/export/run.{fmt}')
    if fmt == 'csv':
        text = data.data.decode('utf-8-sig')
        assert "'=HYPERLINK" in text and "'- item one" in text           # neutralised for Excel
    else:
        ws = load_workbook(io.BytesIO(data.data)).active
        assert ws['A2'].data_type == 's' and ws['A2'].value.startswith('=HYPERLINK')   # stored as text, never a formula
    do_import(admin, 'run', (io.BytesIO(data.data), f'x.{fmt}'), mode='replace')
    with app.app_context():
        r = runs()[0]
        assert r[1] == '=HYPERLINK("http://evil")' and r[4] == '- item one\n- item two' and r[5] == '+1 and @x'


def test_empty_export_still_works(app, alice):
    r = alice.get(f'/events/{eid()}/io/export/schedule.csv')
    assert r.status_code == 200 and r.data.decode('utf-8-sig').strip() == 'Date,Time,Title,Description'


# ---------------------------------------------------------------- permissions

def test_only_admins_import_upload_delete(app, admin, alice):
    assert do_import(alice, 'run', csv_file('Title\nA\n')).status_code == 403
    r = alice.post(f'/events/{eid()}/attachments', data={'target': 'run', 'files': (png_bytes(), 'a.png')},
                   content_type='multipart/form-data')
    assert r.status_code == 403
    aid = upload(admin, 'run', png_bytes(), 'a.png').get_json()['added'][0]['id']
    assert alice.delete(f'/events/attachments/{aid}').status_code == 403
    assert alice.get(f'/events/attachments/{aid}/file').status_code == 200      # crew can view
    anon = app.test_client()
    assert anon.get(f'/events/attachments/{aid}/file').status_code in (301, 302, 401)


# ---------------------------------------------------------------- attachments

def png_bytes(size=(50, 30), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    buf.seek(0)
    return buf


def jpg_bytes(size=(4000, 3000), orientation=None):
    img = Image.new('RGB', size, (10, 120, 200))
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    img.save(buf, 'JPEG', exif=exif)
    buf.seek(0)
    return buf


PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def upload(c, target, data, name):
    return c.post(f'/events/{eid()}/attachments', data={'target': target, 'files': (data, name)},
                  content_type='multipart/form-data')


def stored_files(app):
    d = os.path.join(app.config['UPLOAD_FOLDER'], 'event_files')
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_upload_photo_pdf_and_serve(app, admin):
    r = upload(admin, 'schedule', jpg_bytes(orientation=6), 'IMG_0001.JPG')
    assert r.status_code == 200, r.get_json()
    photo = r.get_json()['added'][0]
    assert photo['kind'] == 'image' and photo['thumb'] and photo['name'] == 'IMG_0001.JPG'
    full = admin.get(photo['url'])
    img = Image.open(io.BytesIO(full.data))
    assert full.mimetype == 'image/jpeg' and max(img.size) == 2400
    assert img.size == (1800, 2400)                                   # 4000x3000 rotated by EXIF, then shrunk
    thumb = Image.open(io.BytesIO(admin.get(photo['thumb']).data))
    assert max(thumb.size) == 400
    assert full.headers['X-Content-Type-Options'] == 'nosniff'

    pdf = upload(admin, 'run', io.BytesIO(PDF), '../../etc/Run Sheet.pdf').get_json()['added'][0]
    assert pdf['kind'] == 'pdf' and pdf['thumb'] is None and pdf['name'] == 'Run Sheet.pdf'
    served = admin.get(pdf['url'])
    assert served.mimetype == 'application/pdf' and served.data == PDF
    dl = admin.get(pdf['download'])
    assert 'attachment' in dl.headers['Content-Disposition'] and 'Run Sheet.pdf' in dl.headers['Content-Disposition']
    assert admin.get(pdf['url'].replace('/file', '/thumb')).status_code == 404
    assert all(len(n) < 60 and '/' not in n for n in stored_files(app))     # random names, nothing from the upload


def test_png_stays_png_and_alpha_ok(app, admin):
    buf = io.BytesIO()
    Image.new('RGBA', (60, 40), (0, 0, 0, 0)).save(buf, 'PNG'); buf.seek(0)
    a = upload(admin, 'schedule', buf, 'shot.png').get_json()['added'][0]
    assert admin.get(a['url']).mimetype == 'image/png'
    assert admin.get(a['thumb']).mimetype == 'image/jpeg'


def test_rejects_wrong_types_even_with_right_extension(app, admin):
    for data, name in ((io.BytesIO(b'MZ\x90\x00 pretend exe'), 'run.pdf'), (io.BytesIO(b'<script>alert(1)</script>'), 'x.jpg'),
                       (io.BytesIO(b'hello'), 'notes.txt'), (io.BytesIO(b''), 'empty.png')):
        r = upload(admin, 'run', data, name)
        assert r.status_code == 400, name
    gif = io.BytesIO(); Image.new('P', (5, 5)).save(gif, 'GIF'); gif.seek(0)
    assert upload(admin, 'run', gif, 'x.gif').status_code == 400
    assert upload(admin, 'nope', png_bytes(), 'a.png').status_code == 400
    assert stored_files(app) == []                                     # nothing left behind
    with app.app_context():
        assert EventAttachment.query.count() == 0


def test_multi_upload_partial_failure(app, admin):
    r = admin.post(f'/events/{eid()}/attachments', content_type='multipart/form-data', data={
        'target': 'schedule', 'files': [(png_bytes(), 'a.png'), (io.BytesIO(b'junk'), 'b.png'), (io.BytesIO(PDF), 'c.pdf')]})
    j = r.get_json()
    assert r.status_code == 200 and len(j['added']) == 2 and [e['name'] for e in j['errors']] == ['b.png']


def test_per_target_limit(app, admin):
    with app.app_context():
        for i in range(30):
            db.session.add(EventAttachment(event_id=eid(), target='run', kind='pdf', stored_name=f'f{i}.pdf'))
        db.session.commit()
    r = upload(admin, 'run', io.BytesIO(PDF), 'one-too-many.pdf')
    assert r.status_code == 400 and 'Limit' in r.get_json()['errors'][0]['error']
    assert upload(admin, 'schedule', io.BytesIO(PDF), 'other-list.pdf').status_code == 200


def test_delete_attachment_removes_files(app, admin):
    a = upload(admin, 'schedule', png_bytes(), 'a.png').get_json()['added'][0]
    assert len(stored_files(app)) == 2                                 # image + thumbnail
    assert admin.delete(f'/events/attachments/{a["id"]}').status_code == 200
    assert stored_files(app) == []
    assert admin.get(a['url']).status_code == 404


def test_deleting_the_event_removes_its_files(app, admin):
    upload(admin, 'schedule', png_bytes(), 'a.png')
    upload(admin, 'run', io.BytesIO(PDF), 'b.pdf')
    assert len(stored_files(app)) == 3
    assert admin.delete(f'/events/{eid()}').status_code == 200
    assert stored_files(app) == []
    with app.app_context():
        assert EventAttachment.query.count() == 0


def test_event_page_has_menu_and_gallery_data(app, admin, alice):
    a = upload(admin, 'schedule', png_bytes(), 'plan.png').get_json()['added'][0]
    html = admin.get(f'/events/{eid()}').get_data(as_text=True)
    assert 'data-act="io"' in html and 'data-gallery="schedule"' in html and 'data-gallery="run"' in html
    assert 'event-io.js' in html and a['thumb'] in html
    page = alice.get(f'/events/{eid()}').get_data(as_text=True)
    assert 'data-act="io"' in page and '"can_manage": false' in page.replace('":false', '": false')
