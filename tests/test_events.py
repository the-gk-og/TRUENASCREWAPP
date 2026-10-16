"""Tests for the rebuilt events / shifts / calendar system.  Run: pytest tests/test_events.py"""
import os, sys
from datetime import datetime, timedelta

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                      # noqa: E402
from extensions import db                       # noqa: E402
from models import (User, Event, Shift, ShiftAssignment, CrewAssignment,   # noqa: E402
                    UserUnavailability, RecurringUnavailability)


class _Client(FlaskClient):
    """The fixture keeps one app context open, which would cache flask-login's
    current_user between requests from different clients; clear it each time."""
    def open(self, *a, **k):
        g.pop('_login_user', None)
        return super().open(*a, **k)


@pytest.fixture()
def app():
    app = create_app('testing')
    app.test_client_class = _Client
    with app.app_context():
        db.create_all()
        for name, admin in (('boss', True), ('alice', False), ('bob', False)):
            db.session.add(User(username=name, is_admin=admin, user_role='crew', email=f'{name}@x.test'))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, username):
    c = app.test_client()
    with app.app_context():
        uid = User.query.filter_by(username=username).first().id
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


@pytest.fixture()
def admin(app): return client_for(app, 'boss')
@pytest.fixture()
def alice(app): return client_for(app, 'alice')


def uid(name): return User.query.filter_by(username=name).first().id
def ics_path(c):
    """The signed-in person's private feed path, e.g. /calendar/ics/<long-slug>."""
    url = c.get('/api/calendar/sync-link').get_json()['url']
    return '/' + url.split('/', 3)[3]
def mk(c, **kw):
    body = {'title': 'Show', 'event_date': '2026-11-10T18:00', 'event_end_date': '2026-11-10T22:00'}
    body.update(kw)
    r = c.post('/events/add', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def test_create_validate_edit_delete(app, admin, alice):
    assert admin.post('/events/add', json={'title': '', 'event_date': '2026-11-10T18:00'}).status_code == 400
    assert admin.post('/events/add', json={'title': 'x', 'event_date': 'nope'}).status_code == 400
    assert admin.post('/events/add', json={'title': 'x', 'event_date': '2026-11-10T18:00',
                                           'event_end_date': '2026-11-10T17:00'}).status_code == 400
    eid = mk(alice, title='Mine', description='**hi**')           # any crew can create
    assert alice.put(f'/events/{eid}/edit', json={'title': 'Mine 2', 'location': 'Hall'}).status_code == 200
    assert alice.delete(f'/events/{eid}').status_code == 403      # delete is admin only
    assert admin.delete(f'/events/{eid}').status_code == 200
    assert db.session.get(Event, eid) is None


def test_tz_suffix_ignored_and_default_end(app, admin):
    eid = mk(admin, event_date='2026-11-10T18:00:00+11:00', event_end_date=None)
    e = db.session.get(Event, eid)
    assert e.event_date == datetime(2026, 11, 10, 18, 0) and e.event_end_date == datetime(2026, 11, 10, 21, 0)


def test_all_day(app, admin):
    eid = mk(admin, all_day=True, event_date='2026-11-10', event_end_date='2026-11-12')
    e = db.session.get(Event, eid)
    assert e.all_day and e.event_date == datetime(2026, 11, 10) and e.event_end_date == datetime(2026, 11, 12, 23, 59)
    feed = admin.get('/api/calendar/feed?start=2026-11-01T00:00&end=2026-12-01T00:00').get_json()
    it = [i for i in feed if i['id'] == f'e-{eid}'][0]
    assert it['allDay'] and it['start'] == '2026-11-10' and it['end'] == '2026-11-13'  # exclusive end


def test_recurrence_month_end_and_scope(app, admin, alice):
    assert alice.post('/events/add', json={'title': 'r', 'event_date': '2026-11-10T18:00',
                                           'recurrence': {'pattern': 'weekly', 'count': 3}}).status_code == 403
    eid = mk(admin, event_date='2026-01-31T18:00', event_end_date='2026-01-31T20:00',
             recurrence={'pattern': 'monthly', 'count': 4})
    dates = [e.event_date.date().isoformat() for e in Event.query.order_by(Event.event_date)]
    assert dates == ['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30']
    inst = Event.query.filter_by(event_date=datetime(2026, 3, 31, 18)).first()
    # shift "this and following" by an hour
    r = admin.put(f'/events/{inst.id}/edit', json={'title': 'Renamed', 'event_date': '2026-03-31T19:00',
                                                   'event_end_date': '2026-03-31T21:00', 'scope': 'future'})
    assert r.status_code == 200
    got = {e.event_date.date().isoformat(): (e.title, e.event_date.hour) for e in Event.query.all()}
    assert got['2026-01-31'][0] == 'Show' and got['2026-03-31'] == ('Renamed', 19) and got['2026-04-30'] == ('Renamed', 19)
    assert admin.delete(f'/events/{inst.id}?scope=future').get_json()['deleted'] == 2
    assert Event.query.count() == 2
    assert admin.delete(f'/events/{eid}?scope=all').get_json()['deleted'] == 2
    assert Event.query.count() == 0


def test_team_shift_flow(app, admin, alice):
    eid = mk(admin)
    assert alice.post(f'/events/{eid}/team/add', json={'user_id': uid('bob')}).status_code == 403
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound',
                                                    'start': '2026-11-10T16:00', 'end': '2026-11-10T20:00'})
    assert r.status_code == 200, r.get_json()
    aid = r.get_json()['shift']['assignment_id']
    assert CrewAssignment.query.filter_by(event_id=eid, crew_member='alice').count() == 1
    # second shift for same person -> one crew row, two shifts
    r2 = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound',
                                                     'start': '2026-11-11T09:00', 'end': '2026-11-11T12:00'})
    assert r2.status_code == 200 and CrewAssignment.query.filter_by(event_id=eid).count() == 1
    # clash on overlapping shift, then force
    c = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'start': '2026-11-10T19:00', 'end': '2026-11-10T21:00'})
    assert c.status_code == 409 and c.get_json()['conflicts']
    assert admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'start': '2026-11-10T19:00',
                                                       'end': '2026-11-10T21:00', 'force': True}).status_code == 200
    # alice sees it, accepts; bob can't touch it
    assert client_for(app, 'bob').post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'}).status_code == 403
    assert alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'confirmed'}).status_code == 400
    assert alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'}).status_code == 200
    # edit + delete
    assert admin.put(f'/events/shift-assignments/{aid}', json={'start': '2026-11-10T15:00', 'end': '2026-11-10T17:00', 'role': 'FOH'}).status_code == 200
    assert db.session.get(ShiftAssignment, aid).shift.role == 'FOH'
    assert admin.delete(f'/events/shift-assignments/{aid}').status_code == 200
    assert db.session.get(ShiftAssignment, aid) is None
    n_shifts = Shift.query.count()
    assert admin.delete(f'/events/{eid}/team/{uid("alice")}').status_code == 200
    assert Shift.query.count() == 0 < n_shifts
    assert CrewAssignment.query.count() == 0


def test_shared_legacy_shift_is_split_on_edit(app, admin):
    eid = mk(admin)
    s = Shift(event_id=eid, title='old', shift_date=datetime(2026, 11, 10, 17), shift_end_date=datetime(2026, 11, 10, 21),
              positions_needed=2, created_by='boss')
    db.session.add(s); db.session.flush()
    a1 = ShiftAssignment(shift_id=s.id, user_id=uid('alice'), status='accepted')
    a2 = ShiftAssignment(shift_id=s.id, user_id=uid('bob'), status='accepted')
    db.session.add_all([a1, a2]); db.session.commit()
    assert admin.put(f'/events/shift-assignments/{a1.id}', json={'start': '2026-11-10T18:00', 'end': '2026-11-10T20:00'}).status_code == 200
    assert db.session.get(ShiftAssignment, a2.id).shift.shift_date.hour == 17     # bob untouched
    assert db.session.get(ShiftAssignment, a1.id).shift.shift_date.hour == 18


def test_unavailability_conflict(app, admin):
    eid = mk(admin)
    db.session.add(UserUnavailability(user_id=uid('bob'), title='Exam', start_date=datetime(2026, 11, 10, 9),
                                      end_date=datetime(2026, 11, 10, 17)))
    db.session.add(RecurringUnavailability(user_id=uid('alice'), title='Work', start_time='15:00', end_time='17:00',
                                           pattern_type='weekly', days_of_week='["2"]',   # old UI format; Tue (10 Nov 2026)
                                           start_date=datetime(2026, 11, 1)))
    db.session.commit()
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('bob'), 'start': '2026-11-10T16:00', 'end': '2026-11-10T18:00'})
    assert r.status_code == 409 and 'Exam' in r.get_json()['conflicts'][0]['title']
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'start': '2026-11-10T16:00', 'end': '2026-11-10T18:00'})
    assert r.status_code == 409 and 'Work' in r.get_json()['conflicts'][0]['title']


def test_calendar_feed_scopes(app, admin, alice):
    eid = mk(admin)
    for u in ('alice', 'bob'):
        admin.post(f'/events/{eid}/team/add', json={'user_id': uid(u), 'role': 'Crew',
                                                    'start': '2026-11-10T16:00', 'end': '2026-11-10T20:00', 'force': True})
    q = '?start=2026-11-01T00:00&end=2026-12-01T00:00'
    def kinds(c, extra=''):
        return sorted(i['extendedProps']['kind'] + ':' + i['extendedProps'].get('username', '') for i in c.get('/api/calendar/feed' + q + extra).get_json())
    assert kinds(alice) == ['event:', 'shift:alice']                            # sees events + only own shifts
    assert kinds(alice, '&shifts=all') == ['event:', 'shift:alice']             # can't widen
    assert kinds(admin, '&shifts=all') == ['event:', 'shift:alice', 'shift:bob']
    assert kinds(admin, f'&shifts=user:{uid("bob")}') == ['event:', 'shift:bob']
    assert kinds(admin, '&shifts=none&events=0') == []
    assert alice.get('/api/calendar/feed?start=2026-01-01T00:00&end=2028-01-01T00:00').status_code == 400


def test_move_event_and_shift(app, admin, alice):
    eid = mk(admin)
    assert alice.put(f'/events/{eid}/move', json={'event_date': '2026-11-11T18:00'}).status_code == 403
    assert admin.put(f'/events/{eid}/move', json={'event_date': '2026-11-11T18:00', 'event_end_date': '2026-11-11T22:00'}).status_code == 200
    assert db.session.get(Event, eid).event_date.day == 11
    assert admin.put(f'/events/{eid}/move', json={'all_day': True, 'event_date': '2026-11-12', 'event_end_date': '2026-11-14'}).status_code == 200
    e = db.session.get(Event, eid)
    assert e.all_day and e.event_end_date == datetime(2026, 11, 13, 23, 59)


def test_notes_markdown_and_permissions(app, admin, alice):
    eid = mk(admin)
    r = alice.post(f'/events/{eid}/notes/add', json={'content': 'Bring:\n- cables\n\n<script>x</script>**b**'})
    note = r.get_json()['note']
    assert '<li>cables</li>' in note['html'] and '<script' not in note['html'] and '<strong>b</strong>' in note['html']
    nid = note['id']
    assert client_for(app, 'bob').put(f'/events/notes/{nid}/edit', json={'content': 'x'}).status_code == 403
    assert admin.put(f'/events/notes/{nid}/edit', json={'content': 'ok'}).status_code == 200
    assert alice.delete(f'/events/notes/{nid}/delete').status_code == 200
    assert alice.post('/api/markdown/preview', json={'text': '# T'}).get_json()['html'].startswith('<h1>')


def test_schedule_and_run_list(app, admin, alice):
    eid = mk(admin)
    assert alice.post(f'/events/{eid}/schedule/add', json={'title': 'x', 'scheduled_time': '2026-11-10T17:00'}).status_code == 403
    sid = admin.post(f'/events/{eid}/schedule/add', json={'title': 'Bump in', 'scheduled_time': '2026-11-10T14:00', 'description': '*go*'}).get_json()['id']
    assert admin.put(f'/events/schedule/{sid}/edit', json={'title': 'Bump in 2', 'scheduled_time': '2026-11-10T15:00'}).status_code == 200
    assert admin.post(f'/events/{eid}/schedule/add', json={'title': '', 'scheduled_time': '2026-11-10T15:00'}).status_code == 400
    assert admin.delete(f'/events/schedule/{sid}/delete').status_code == 200
    ids = [admin.post(f'/events/{eid}/crew-run/add', json={'title': t}).get_json()['id'] for t in 'abc']
    admin.post(f'/events/{eid}/crew-run/reorder', json={'item_ids': ids[::-1]})
    admin.delete(f'/events/crew-run/{ids[0]}/delete')
    from models import CrewRunItem
    assert [(i.title, i.order_number) for i in CrewRunItem.query.order_by(CrewRunItem.order_number)] == [('c', 1), ('b', 2)]


def test_join_leave_and_duplicate(app, admin, alice):
    eid = mk(admin)
    admin.post(f'/events/{eid}/schedule/add', json={'title': 'Doors', 'scheduled_time': '2026-11-10T17:30'})
    assert alice.post(f'/events/{eid}/join').status_code == 200
    assert alice.post(f'/events/{eid}/join').status_code == 400
    assert alice.delete(f'/events/{eid}/team/{uid("alice")}').status_code == 200
    assert alice.delete(f'/events/{eid}/team/{uid("bob")}').status_code == 403
    new = admin.post(f'/events/{eid}/duplicate', json={'event_date': '2026-11-17T18:00'}).get_json()['id']
    from models import EventSchedule
    assert EventSchedule.query.filter_by(event_id=new).first().scheduled_time == datetime(2026, 11, 17, 17, 30)


def test_pages_render(app, admin, alice):
    eid = mk(admin, description='# Hello\n- a\n- b')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    admin.post(f'/events/{eid}/schedule/add', json={'title': 'Doors', 'scheduled_time': '2026-11-10T17:30'})
    admin.post(f'/events/{eid}/crew-run/add', json={'title': 'Cue 1'})
    admin.post(f'/events/{eid}/notes/add', json={'content': 'note'})
    for c in (admin, alice):
        for url in (f'/events/{eid}', '/events', '/calendar', '/crew/my-schedule', ics_path(c)):
            r = c.get(url)
            assert r.status_code == 200, (url, r.status_code)
    assert b'<h1>Hello</h1>' in admin.get(f'/events/{eid}').data
    assert b'Awaiting your response' in alice.get('/crew/my-schedule').data
    assert admin.get('/shifts/management').status_code == 302


def test_ics_escaping_and_folding(app, admin):
    mk(admin, title='A, B; C', description='line1\nline2 \\ x ' + 'y' * 120, location='Hall, North')
    body = admin.get(ics_path(admin)).data.decode()
    assert 'SUMMARY:A\\, B\\; C' in body and 'LOCATION:Hall\\, North' in body
    assert '\\nline2' in body.replace('\r\n ', '')
    assert all(len(l.encode()) <= 75 for l in body.split('\r\n'))


def test_schema_upgrade(app):
    from sqlalchemy import text
    from app import ensure_schema
    db.session.execute(text('ALTER TABLE event DROP COLUMN all_day'))
    db.session.commit()
    ensure_schema(app)
    assert 'all_day' in {c['name'] for c in db.inspect(db.engine).get_columns('event')}


# ---------------------------------------------------------------------------
# Logged-out visitors, private calendar feed, shift emails
# ---------------------------------------------------------------------------

def test_logged_out_goes_to_login_not_home_page(app, alice):
    anon = app.test_client()
    r = anon.get('/')
    assert r.status_code == 302 and r.headers['Location'].endswith('/login')
    assert 'showwise.app' not in r.headers['Location']
    r = anon.get('/calendar')                         # protected page -> login too
    assert r.status_code == 302 and '/login' in r.headers['Location']
    r = alice.get('/')                                # signed in -> dashboard
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')


def test_private_ics_feed(app, admin, alice):
    anon = app.test_client()
    eid = mk(admin, title='Gala')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound', 'notes': 'Bring XLR'})
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('bob'), 'role': 'Lights'})

    path = ics_path(alice)
    token = path.rsplit('/', 1)[1]
    assert path.startswith('/calendar/ics/') and len(token) >= 40
    assert ics_path(alice) == path                    # stable between visits
    assert ics_path(admin) != path                    # different per person

    r = anon.get(path)                                # no login needed (calendar apps can't)
    assert r.status_code == 200 and r.mimetype == 'text/calendar'
    assert 'no-store' not in r.headers.get('Cache-Control', '') and 'private' in r.headers['Cache-Control']
    body = r.data.decode().replace('\r\n ', '')
    assert 'SUMMARY:Gala' in body                                   # the event
    assert 'SUMMARY:Sound shift \u00b7 Gala' in body               # alice's shift
    assert 'Lights' not in body                                     # bob's shift is not in alice's feed
    assert 'STATUS:TENTATIVE' in body and 'Bring XLR' in body
    assert 'X-WR-CALNAME:ShowWise - alice' in body

    # a declined shift drops out of the feed
    a = ShiftAssignment.query.filter_by(user_id=uid('alice')).first()
    a.status = 'rejected'; db.session.commit()
    assert 'Sound shift' not in anon.get(path).data.decode()

    # accepted shifts are CONFIRMED
    a.status = 'accepted'; db.session.commit()
    assert 'STATUS:CONFIRMED' in anon.get(path).data.decode()


def test_ics_bad_and_old_urls(app, alice):
    anon = app.test_client()
    assert anon.get('/calendar/ics/' + 'x' * 43).status_code == 404
    assert anon.get('/calendar/ics/short').status_code == 404
    assert anon.get('/calendar/ics/1').status_code == 404
    r = anon.get('/calendar/ics')                     # the old open feed needs a login now
    assert r.status_code == 302 and '/login' in r.headers['Location']
    r = alice.get('/calendar/ics')                    # signed in: sent to your own private link
    assert r.status_code == 302 and r.headers['Location'].endswith(ics_path(alice))


def test_ics_link_reset_and_cast_blocked(app, alice):
    anon = app.test_client()
    old = ics_path(alice)
    assert anon.get(old).status_code == 200
    new_url = alice.post('/api/calendar/sync-link/reset').get_json()
    assert new_url['webcal_url'].startswith('webcal://') and new_url['url'].startswith('http')
    assert anon.get(old).status_code == 404                           # old slug is dead
    assert anon.get('/' + new_url['url'].split('/', 3)[3]).status_code == 200
    # cast-only accounts never get a crew feed
    cast = User(username='cassie', is_cast=True, user_role='cast', calendar_token='c' * 43)
    db.session.add(cast); db.session.commit()
    assert anon.get('/calendar/ics/' + 'c' * 43).status_code == 404


def _outbox(app):
    from extensions import mail
    app.config['MAIL_USERNAME'] = 'sender@x.test'
    return mail.record_messages()


def test_shift_assignment_sends_email(app, admin):
    eid = mk(admin, title='Gala', location='Main Hall')
    with _outbox(app) as outbox:
        r = admin.post(f'/events/{eid}/team/add',
                       json={'user_id': uid('alice'), 'role': 'Sound', 'notes': '<b>Bring</b> XLR\nbag'})
        assert r.status_code == 200
        assert len(outbox) == 1
        m = outbox[0]
        assert m.recipients == ['alice@x.test'] and 'New shift assigned' in m.subject
        assert 'Gala' in m.html and 'Sound' in m.html and 'Main Hall' in m.html
        assert 'View my shifts' in m.html and '/crew/my-schedule' in m.html
        assert '&lt;b&gt;Bring&lt;/b&gt;' in m.html and '<b>Bring</b>' not in m.html     # user text is escaped
        assert '{%' not in m.html and 'Positions' not in m.html
        # assigning yourself does not email you
        admin.post(f'/events/{eid}/team/add', json={'user_id': uid('boss'), 'role': 'Lead'})
        assert len(outbox) == 1


def test_add_all_crew_emails_everyone_but_you(app, admin):
    eid = mk(admin, title='Gala')
    with _outbox(app) as outbox:
        assert admin.post(f'/events/{eid}/team/add-all').get_json()['added'] == 3
        assert sorted(m.recipients[0] for m in outbox) == ['alice@x.test', 'bob@x.test']


def test_no_email_when_mail_not_configured(app, admin):
    from extensions import mail
    eid = mk(admin)
    with mail.record_messages() as outbox:           # MAIL_USERNAME is empty in tests
        assert admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'}).status_code == 200
        assert outbox == []


def test_calendar_token_schema_upgrade(app):
    from sqlalchemy import text
    from app import ensure_schema
    db.session.execute(text('DROP INDEX IF EXISTS ix_user_calendar_token'))
    db.session.execute(text('ALTER TABLE user DROP COLUMN calendar_token'))
    db.session.commit()
    ensure_schema(app)
    insp = db.inspect(db.engine)
    assert 'calendar_token' in {c['name'] for c in insp.get_columns('user')}
    assert any(i['name'] == 'ix_user_calendar_token' and i['unique'] for i in insp.get_indexes('user'))
