"""Tests for the admin roster (shift scheduler).  Run: pytest tests/test_roster.py"""
import os, sys
from datetime import datetime

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                   # noqa: E402
from extensions import db                                    # noqa: E402
from models import User, Event, Shift, ShiftAssignment, CrewAssignment, UserUnavailability   # noqa: E402


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
        db.session.add(Event(title='Show', event_date=datetime(2026, 11, 10, 18), event_end_date=datetime(2026, 11, 10, 22)))
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


def uid(n): return User.query.filter_by(username=n).first().id
def eid(): return Event.query.first().id


def make(c, who='alice', **kw):
    body = {'event_id': eid(), 'user_id': uid(who) if who else None, 'role': 'Sound',
            'start': '2026-11-10T09:00', 'end': '2026-11-10T17:00'}
    body.update(kw)
    r = c.post('/api/roster/shift', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['item']


def test_admin_only(app, alice):
    assert alice.get('/api/roster').status_code == 403
    assert alice.post('/api/roster/shift', json={}).status_code == 403
    assert alice.post('/api/roster/drop', json={}).status_code == 403


def test_page_and_data(app, admin):
    assert admin.get('/roster').status_code == 200
    make(admin)
    make(admin, who=None, start='2026-11-11T09:00', end='2026-11-11T12:00')
    d = admin.get('/api/roster?start=2026-11-10&days=7').get_json()
    assert d['start'] == '2026-11-09'                      # snapped to Monday
    assert len(d['shifts']) == 1 and len(d['open']) == 1
    assert {p['username'] for p in d['people']} == {'boss', 'alice', 'bob'}
    assert d['events'][0]['title'] == 'Show'


def test_create_makes_real_event_shift(app, admin):
    item = make(admin)
    a = db.session.get(ShiftAssignment, item['assignment_id'])
    assert a.shift.event_id == eid() and a.status == 'pending'
    assert CrewAssignment.query.filter_by(event_id=eid(), crew_member='alice').count() == 1


def test_validation(app, admin):
    bad = lambda **kw: admin.post('/api/roster/shift', json={
        'event_id': eid(), 'user_id': uid('alice'), 'start': '2026-11-10T09:00', 'end': '2026-11-10T17:00', **kw})
    assert bad(end='2026-11-10T08:00').status_code == 400
    assert bad(event_id=9999).status_code == 400
    assert bad(status='rejected').status_code == 400


def test_clash_and_force(app, admin):
    make(admin)
    r = admin.post('/api/roster/shift', json={'event_id': eid(), 'user_id': uid('alice'), 'start': '2026-11-10T12:00', 'end': '2026-11-10T14:00'})
    assert r.status_code == 409 and r.get_json()['conflicts']
    r = admin.post('/api/roster/shift', json={'event_id': eid(), 'user_id': uid('alice'), 'start': '2026-11-10T12:00', 'end': '2026-11-10T14:00', 'force': True})
    assert r.status_code == 200


def test_unavailability_is_reported(app, admin):
    db.session.add(UserUnavailability(user_id=uid('bob'), title='Exam', start_date=datetime(2026, 11, 10), end_date=datetime(2026, 11, 11)))
    db.session.commit()
    d = admin.get('/api/roster?start=2026-11-09').get_json()
    assert d['unavailable'][0]['title'] == 'Exam'
    r = admin.post('/api/roster/shift', json={'event_id': eid(), 'user_id': uid('bob'), 'start': '2026-11-10T09:00', 'end': '2026-11-10T10:00'})
    assert r.status_code == 409


def test_edit_reassign_and_event_crew_list(app, admin):
    item = make(admin)
    r = admin.put(f"/api/roster/assignment/{item['assignment_id']}", json={'user_id': uid('bob'), 'role': 'Lights', 'start': '2026-11-10T10:00', 'end': '2026-11-10T18:00', 'status': 'accepted'})
    assert r.status_code == 200, r.get_json()
    a = db.session.get(ShiftAssignment, item['assignment_id'])
    assert a.user_id == uid('bob') and a.shift.role == 'Lights'
    crew = {c.crew_member for c in CrewAssignment.query.filter_by(event_id=eid())}
    assert crew == {'bob'}                                  # alice has nothing left on the event


def test_open_shift_assign_and_delete(app, admin):
    item = make(admin, who=None)
    assert item['status'] == 'open'
    r = admin.put(f"/api/roster/open/{item['shift_id']}", json={'event_id': eid(), 'user_id': uid('bob'), 'start': item['start'], 'end': item['end']})
    assert r.status_code == 200 and r.get_json()['item']['user_id'] == uid('bob')
    assert admin.delete(f"/api/roster/open/{item['shift_id']}").status_code == 400    # now has someone on it
    other = make(admin, who=None, start='2026-11-12T09:00', end='2026-11-12T10:00')
    assert admin.delete(f"/api/roster/open/{other['shift_id']}").status_code == 200
    assert db.session.get(Shift, other['shift_id']) is None


def test_drop_moves_person_and_day_keeping_times(app, admin):
    item = make(admin, start='2026-11-10T22:30', end='2026-11-11T02:00')
    r = admin.post('/api/roster/drop', json={'key': item['key'], 'user_id': uid('bob'), 'date': '2026-11-13'})
    assert r.status_code == 200, r.get_json()
    s = db.session.get(Shift, item['shift_id'])
    assert (s.shift_date, s.shift_end_date) == (datetime(2026, 11, 13, 22, 30), datetime(2026, 11, 14, 2, 0))
    assert s.assignments[0].user_id == uid('bob') and s.assignments[0].status == 'pending'


def test_drop_to_unassigned_and_back(app, admin):
    item = make(admin)
    r = admin.post('/api/roster/drop', json={'key': item['key'], 'user_id': None, 'date': '2026-11-10'})
    assert r.status_code == 200 and r.get_json()['item']['status'] == 'open'
    assert ShiftAssignment.query.count() == 0
    r = admin.post('/api/roster/drop', json={'key': f"s:{item['shift_id']}", 'user_id': uid('bob'), 'date': '2026-11-10'})
    assert r.status_code == 200 and r.get_json()['item']['user_id'] == uid('bob')


def test_existing_events_endpoint_still_works_on_roster_shift(app, admin):
    item = make(admin)
    assert admin.delete(f"/events/shift-assignments/{item['assignment_id']}").status_code == 200
    assert Shift.query.count() == 0
