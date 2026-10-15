"""Tests for shift-decline emails, calendar status classes and the Admin Console."""
import os, sqlite3, sys
from datetime import datetime

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                   # noqa: E402
from extensions import db                                    # noqa: E402
from models import User, Event, Shift, ShiftAssignment, AppSetting   # noqa: E402


class _Client(FlaskClient):
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


def client_for(app, name):
    c = app.test_client()
    uid = User.query.filter_by(username=name).first().id
    with c.session_transaction() as s:
        s['_user_id'] = str(uid); s['_fresh'] = True
    return c


def uid(n): return User.query.filter_by(username=n).first().id


@pytest.fixture()
def admin(app): return client_for(app, 'boss')
@pytest.fixture()
def alice(app): return client_for(app, 'alice')
@pytest.fixture()
def mails(monkeypatch):
    sent = []
    import services.email_service as es
    monkeypatch.setattr(es, 'send_html_email', lambda subject, to, html, text=None: sent.append((subject, to, html, text)) or True)
    return sent


def make_shift(admin, user='alice'):
    eid = admin.post('/events/add', json={'title': 'Gala', 'event_date': '2026-11-10T18:00',
                                          'event_end_date': '2026-11-10T22:00', 'location': 'Hall'}).get_json()['id']
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid(user), 'role': 'Sound'})
    return eid, r.get_json()['shift']['assignment_id']


def set_recipients(admin, ids, **kw):
    r = admin.put('/admin/api/notifications', json={'user_ids': ids, 'enabled': True, **kw})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_decline_emails_chosen_admin_once(app, admin, alice, mails):
    eid, aid = make_shift(admin)
    mails.clear()                                                  # ignore the 'you were assigned' email
    set_recipients(admin, [uid('boss')])
    r = alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected', 'reason': 'Exam <b>that</b> day'})
    assert r.status_code == 200
    assert len(mails) == 1
    subject, to, html, text = mails[0]
    assert to == 'boss@x.test' and 'alice' in subject and 'Gala' in subject
    assert 'Exam &lt;b&gt;that&lt;/b&gt; day' in html and '<b>that</b>' not in html      # escaped
    assert 'Reason: Exam' in text and 'Sound' in text and 'Hall' in text
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected'})            # clicking again: no duplicate
    assert len(mails) == 1


def test_decline_not_sent_when_disabled_unset_or_admin_edit(app, admin, alice, mails):
    eid, aid = make_shift(admin)
    mails.clear()
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected'})            # nobody configured
    assert mails == []
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'})
    set_recipients(admin, [uid('boss')], enabled=False)
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected'})
    assert mails == []
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'})
    set_recipients(admin, [uid('boss')])
    admin.put(f'/events/shift-assignments/{aid}', json={'status': 'rejected', 'force': True})   # admin marks it declined
    assert mails == []
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'})
    alice.post(f'/shifts/{db.session.get(ShiftAssignment, aid).shift_id}/reject', json={'reason': 'sick'})
    assert len(mails) == 1 and 'sick' in mails[0][3]


def test_decline_creator_and_missing_email(app, admin, alice, mails):
    eid, aid = make_shift(admin)                                  # event created by boss
    mails.clear()
    out = set_recipients(admin, [uid('bob')], include_event_creator=True)
    bob = User.query.filter_by(username='bob').first(); bob.email = None; db.session.commit()
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected'})
    assert [m[1] for m in mails] == ['boss@x.test']              # bob has no email -> skipped; creator boss included
    assert admin.put('/admin/api/notifications', json={'user_ids': [uid('bob')]}).get_json()['no_email'] == ['bob']


def test_decline_reason_is_stored_and_cleared(app, admin, alice, mails):
    eid, aid = make_shift(admin)
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected', 'reason': 'away'})
    assert db.session.get(ShiftAssignment, aid).decline_reason == 'away'
    assert b'Reason: away' in admin.get(f'/events/{eid}').data
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'})
    assert db.session.get(ShiftAssignment, aid).decline_reason is None


def test_calendar_status_classes(app, admin, alice):
    eid, aid = make_shift(admin)
    def cls():
        feed = alice.get('/api/calendar/feed?start=2026-11-01T00:00&end=2026-12-01T00:00').get_json()
        return [c for i in feed if i['extendedProps']['kind'] == 'shift' for c in i['classNames']]
    assert 'cal-shift-pending' in cls() and 'cal-shift-confirmed' not in cls()
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'accepted'})
    assert 'cal-shift-confirmed' in cls() and 'cal-shift-pending' not in cls()
    alice.post(f'/shifts/assignment/{aid}/respond', json={'status': 'rejected'})
    assert cls() == []                                            # declined shifts leave the crew member's own calendar
    feed = admin.get('/api/calendar/feed?start=2026-11-01T00:00&end=2026-12-01T00:00&shifts=all').get_json()
    assert 'cal-shift-declined' in [c for i in feed for c in i['classNames']]      # admins still see it, greyed
    css = open('static/css/events.css').read()
    for c in ('cal-shift-pending', 'cal-shift-confirmed', 'cal-shift-declined'):
        assert f'.sw-cal .{c}' in css
    assert '.sw-shift-confirmed' not in css                       # old colliding names are gone


def test_admin_permissions(app, alice):
    assert alice.get('/admin').status_code == 302
    for method, url in (('get', '/admin/api/users'), ('get', '/admin/api/notifications'), ('put', '/admin/api/notifications'),
                        ('post', '/admin/users/add'), ('get', '/admin/invites'), ('post', '/admin/backup'),
                        ('get', '/admin/export-events'), ('post', '/admin/api/notifications/test')):
        assert getattr(alice, method)(url).status_code == 403, url


def test_admin_pages_render_and_old_overview_redirects(app, admin):
    r = admin.get('/admin')
    assert r.status_code == 200 and b'Admin Console' in r.data and b'id="admin-data"' in r.data
    assert admin.get('/admin/overview').headers['Location'].endswith('/admin#overview')
    assert admin.get('/admin/api/users').get_json()[0]['username'] == 'alice'
    assert admin.get('/admin/export-events').status_code == 200


def test_user_crud_and_validation(app, admin):
    bad = lambda **k: admin.post('/admin/users/add', json={'username': 'zed', 'password': 'secret1', **k})
    assert bad(password='x').status_code == 400
    assert bad(email='nope').status_code == 400
    assert bad(email='alice@x.test').status_code == 400
    assert bad(user_role='wizard').status_code == 400
    assert admin.post('/admin/users/add', json={'username': 'ALICE', 'password': 'secret1'}).status_code == 400
    r = bad(email='zed@x.test', user_role='staff', is_admin=True)
    assert r.status_code == 200
    zid = r.get_json()['user']['id']
    assert admin.put(f'/admin/users/edit/{zid}', json={'email': 'bob@x.test'}).status_code == 400
    assert admin.put(f'/admin/users/edit/{zid}', json={'user_role': 'cast'}).get_json()['user']['is_admin'] is True  # edit keeps flags unless sent
    assert admin.put(f'/admin/users/edit/{uid("boss")}', json={'is_admin': False}).status_code == 403
    assert admin.delete(f'/admin/users/delete/{uid("boss")}').status_code == 400


def test_delete_user_with_shifts_cleans_up(app, admin, alice):
    eid, aid = make_shift(admin)
    assert admin.delete(f'/admin/users/delete/{uid("alice")}').status_code == 200
    assert db.session.get(ShiftAssignment, aid) is None and Shift.query.count() == 0
    assert admin.get(f'/events/{eid}').status_code == 200


def test_invites_flow(app, admin):
    exp = '2099-01-01T10:00'
    assert admin.post('/admin/invites/generate', json={'expires_at': '2000-01-01T10:00'}).status_code == 400
    assert admin.post('/admin/invites/generate', json={'expires_at': exp, 'role': 'x'}).status_code == 400
    r = admin.post('/admin/invites/generate', json={'expires_at': exp, 'role': 'crew', 'max_uses': 3, 'note': 'hi'})
    iid = r.get_json()['id']
    inv = admin.get('/admin/invites').get_json()[0]
    assert inv['state'] == 'active' and inv['max_uses'] == 3
    admin.post(f'/admin/invites/{iid}/revoke')
    assert admin.get('/admin/invites').get_json()[0]['state'] == 'revoked'
    assert admin.delete(f'/admin/invites/{iid}').status_code == 200
    assert admin.post('/admin/invites/email', json={'email': 'bad', 'expires_at': exp}).status_code == 400


def test_notification_test_requires_mail(app, admin):
    assert admin.get('/admin/api/notifications').get_json()['mail_configured'] is False
    r = admin.post('/admin/api/notifications/test')
    assert r.status_code == 400 and 'not set up' in r.get_json()['error']


def test_backup_and_restore_safety(app, admin, tmp_path, monkeypatch):
    import routes.admin as ra
    monkeypatch.chdir(tmp_path)
    assert admin.post('/admin/backup').status_code == 500                 # in-memory test DB: clear error, no crash
    live = tmp_path / 'live.db'
    con = sqlite3.connect(live); con.execute('create table user(id int)'); con.commit(); con.close()
    monkeypatch.setattr(ra, '_db_path', lambda: str(live))
    name = admin.post('/admin/backup').get_json()['filename']
    assert name in [b['name'] for b in admin.get('/admin/backups').get_json()]
    assert admin.get(f'/admin/download-backup/{name}').status_code == 200
    assert admin.get('/admin/download-backup/..%2Fapp.py').status_code in (400, 404)
    import io
    bad = admin.post('/admin/restore', data={'file': (io.BytesIO(b'not a database'), 'x.db')}, content_type='multipart/form-data')
    assert bad.status_code == 400 and 'not a SQLite' in bad.get_json()['error']
    nouser = tmp_path / 'other.db'
    con = sqlite3.connect(nouser); con.execute('create table foo(id int)'); con.commit(); con.close()
    bad = admin.post('/admin/restore', data={'file': (open(nouser, 'rb'), 'o.db')}, content_type='multipart/form-data')
    assert bad.status_code == 400 and 'not a ShowWise' in bad.get_json()['error']
    assert admin.delete(f'/admin/backups/{name}').status_code == 200
    assert admin.delete('/admin/backups/evil.sh').status_code == 400


def test_schema_upgrade_adds_both_columns(app):
    from sqlalchemy import text
    from app import ensure_schema
    db.session.execute(text('ALTER TABLE shift_assignment DROP COLUMN decline_reason'))
    db.session.commit()
    ensure_schema(app)
    assert 'decline_reason' in {c['name'] for c in db.inspect(db.engine).get_columns('shift_assignment')}
