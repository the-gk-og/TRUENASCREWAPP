"""Shift reminder emails (and the admin switch), the call sheet PDF and the run list clock."""

import os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from extensions import db                                                  # noqa: E402
from models import Event, ShiftAssignment                                  # noqa: E402
from services.report_service import duration_minutes                       # noqa: E402
from services.shift_reminders import send_due_shift_reminders              # noqa: E402
from tests.test_events import app, admin, alice, client_for, uid, mk       # noqa: E402,F401  (fixtures)


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M')


def shift(admin, eid, user, start, hours=3):
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid(user), 'role': 'Sound',
                                                    'start': iso(start), 'end': iso(start + timedelta(hours=hours))})
    assert r.status_code == 200, r.get_json()


def test_shift_reminders_go_once_and_can_be_turned_off(app, admin, alice):
    now = datetime.now().replace(second=0, microsecond=0)
    eid = mk(admin, title='Gig', event_date=iso(now + timedelta(hours=20)), event_end_date=iso(now + timedelta(hours=26)))
    shift(admin, eid, 'alice', now + timedelta(hours=20))       # tomorrow: due
    shift(admin, eid, 'bob', now + timedelta(hours=21))         # due, but bob declines
    far = mk(admin, title='Later', event_date=iso(now + timedelta(days=5)), event_end_date=iso(now + timedelta(days=5, hours=3)))
    shift(admin, far, 'alice', now + timedelta(days=5))         # too far away

    bobs = ShiftAssignment.query.filter_by(user_id=uid('bob')).first()
    assert client_for(app, 'bob').post(f'/shifts/assignment/{bobs.id}/respond',
                                       json={'status': 'rejected', 'reason': 'Away'}).status_code == 200

    sent = []
    fake = lambda **kw: sent.append(kw) or True

    # Off in the admin console: nothing goes out
    assert admin.get('/admin/api/notifications').get_json()['shift_reminders'] is True     # on unless turned off
    assert admin.put('/admin/api/notifications', json={'user_ids': [], 'shift_reminders': False}).status_code == 200
    assert admin.get('/admin/api/notifications').get_json()['shift_reminders'] is False
    assert send_due_shift_reminders(now, send=fake) == 0 and not sent

    # Back on: one email, to the person who hasn't declined, and only once
    assert admin.put('/admin/api/notifications', json={'user_ids': [], 'shift_reminders': True}).status_code == 200
    assert send_due_shift_reminders(now, send=fake) == 1
    assert [m['recipient_email'] for m in sent] == ['alice@x.test']
    assert sent[0]['event_title'] == 'Gig' and sent[0]['role'] == 'Sound'
    assert send_due_shift_reminders(now, send=fake) == 0 and len(sent) == 1

    # Saving other notification settings doesn't switch reminders off by accident
    assert admin.put('/admin/api/notifications', json={'user_ids': []}).status_code == 200
    assert admin.get('/admin/api/notifications').get_json()['shift_reminders'] is True
    # Crew can't change it
    assert alice.put('/admin/api/notifications', json={'user_ids': [], 'shift_reminders': False}).status_code in (302, 401, 403)


def test_reminders_wait_until_email_is_set_up(app, admin):
    now = datetime.now().replace(second=0, microsecond=0)
    eid = mk(admin, event_date=iso(now + timedelta(hours=5)), event_end_date=iso(now + timedelta(hours=8)))
    shift(admin, eid, 'alice', now + timedelta(hours=5))
    app.config['MAIL_USERNAME'] = ''
    assert send_due_shift_reminders(now) == 0
    assert ShiftAssignment.query.first().reminder_sent_at is None      # still due once email works


def test_duration_parsing():
    cases = {'5 min': 5, '5': 5, '1h 30': 60, '1h 30m': 90, '1 hour': 60, '90s': 1.5, '2:30': 2.5,
             '1:02:30': 62.5, '4 mins': 4, '': None, 'a while': None}
    for text, want in cases.items():
        assert duration_minutes(text) == want, text


def test_call_sheet_and_run_clock(app, admin, alice):
    eid = mk(admin, title='Awards Night', event_date='2026-11-10T18:00', event_end_date='2026-11-10T22:00')
    shift(admin, eid, 'alice', datetime(2026, 11, 10, 16, 0))
    assert admin.post(f'/events/{eid}/team/add', json={'user_id': uid('bob')}).status_code == 200    # no shift time
    for title, length in (('Welcome', '5 min'), ('Awards', '40 min'), ('Close', '')):
        assert admin.post(f'/events/{eid}/crew-run/add', json={'title': title, 'duration': length}).status_code == 200

    sheet = alice.get(f'/events/{eid}/export-pdf?parts=callsheet')
    assert sheet.status_code == 200 and sheet.data[:4] == b'%PDF'
    assert 'Awards_Night_call_sheet_20261110.pdf' in sheet.headers['Content-Disposition']
    # The call sheet is its own thing, not part of the whole pack
    whole = alice.get(f'/events/{eid}/export-pdf')
    assert 'event_pack' in whole.headers['Content-Disposition']

    # The run list starts at the event start until someone sets a time
    page = admin.get(f'/events/{eid}').data.decode()
    assert '"run_start": "18:00"' in page and 'data-part="callsheet"' in page
    assert alice.put(f'/events/{eid}/run-start', json={'time': '19:30'}).status_code == 403
    assert admin.put(f'/events/{eid}/run-start', json={'time': '7pm'}).status_code == 400
    assert admin.put(f'/events/{eid}/run-start', json={'time': '19:30'}).get_json()['time'] == '19:30'
    assert '"run_start": "19:30"' in admin.get(f'/events/{eid}').data.decode()
    assert alice.get(f'/events/{eid}/export-pdf?parts=run').status_code == 200
    assert admin.put(f'/events/{eid}/run-start', json={'time': ''}).get_json()['time'] == '18:00'

    with app.app_context():
        from services.report_service import run_start_for
        assert run_start_for(db.session.get(Event, eid)) == datetime(2026, 11, 10, 18, 0)


def test_pdf_prints_accented_and_non_latin_names(app, admin):
    from services import report_service
    eid = mk(admin, title='Fête d’été: Привет', location='Salle №2')
    assert admin.post(f'/events/{eid}/crew-run/add', json={'title': 'Ouverture — Ελληνικά', 'duration': '5 min'}).status_code == 200
    r = admin.get(f'/events/{eid}/export-pdf')
    assert r.status_code == 200 and r.data[:4] == b'%PDF'
    if report_service.FONT != 'Helvetica':             # the server has DejaVu: it is embedded in the file
        assert b'DejaVu' in r.data
