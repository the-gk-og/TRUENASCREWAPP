"""Tests for event tasks, shift tasks and assigned tasks.  Run: pytest tests/test_event_tasks.py"""
import os, sys

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                      # noqa: E402
from extensions import db                       # noqa: E402
from models import User, Event, Shift, EventTask  # noqa: E402


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
        for name, admin in (('boss', True), ('alice', False), ('bob', False), ('carol', False)):
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
@pytest.fixture()
def bob(app): return client_for(app, 'bob')
@pytest.fixture()
def carol(app): return client_for(app, 'carol')


def uid(name): return User.query.filter_by(username=name).first().id


def make_event(admin, **kw):
    body = {'title': 'Show', 'event_date': '2026-11-10T18:00', 'event_end_date': '2026-11-10T22:00'}
    body.update(kw)
    r = admin.post('/events/add', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def put_on_team(admin, eid, name, role='Sound'):
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid(name), 'role': role, 'force': True})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['shift']['shift_id']


def test_event_task_basics_and_assignment(app, admin, alice):
    eid = make_event(admin)
    put_on_team(admin, eid, 'alice')

    r = admin.post(f'/events/{eid}/tasks/add', json={'title': 'Tape the stage', 'priority': 'high'})
    assert r.status_code == 200
    t = r.get_json()['task']
    assert t['assignee_id'] is None and t['priority'] == 'high' and not t['done']

    # blank title / bad priority are rejected
    assert admin.post(f'/events/{eid}/tasks/add', json={'title': ' '}).status_code == 400
    assert admin.post(f'/events/{eid}/tasks/add', json={'title': 'x', 'priority': 'urgent'}).status_code == 400

    # assign to one person on the event
    r = admin.put(f"/event-tasks/{t['id']}", json={'assigned_user_id': uid('alice')})
    assert r.status_code == 200 and r.get_json()['task']['assignee'] == 'alice'

    # ...but not to someone who isn't on the event
    r = admin.put(f"/event-tasks/{t['id']}", json={'assigned_user_id': uid('bob')})
    assert r.status_code == 400 and 'not on this event' in r.get_json()['error']

    # crew cannot create, edit or delete
    assert alice.post(f'/events/{eid}/tasks/add', json={'title': 'nope'}).status_code == 403
    assert alice.put(f"/event-tasks/{t['id']}", json={'title': 'nope'}).status_code == 403
    assert alice.delete(f"/event-tasks/{t['id']}").status_code == 403


def test_event_creator_can_manage_tasks(app, admin, alice):
    r = alice.post('/events/add', json={'title': 'Mine', 'event_date': '2026-12-01T10:00'})
    eid = r.get_json()['id']
    assert alice.post(f'/events/{eid}/tasks/add', json={'title': 'Sweep'}).status_code == 200


def test_people_on_the_event_can_tick_it_off(app, admin, alice, bob, carol):
    eid = make_event(admin)
    put_on_team(admin, eid, 'alice')
    put_on_team(admin, eid, 'bob')
    tid = admin.post(f'/events/{eid}/tasks/add',
                     json={'title': 'Check cables', 'assigned_user_id': uid('alice')}).get_json()['task']['id']

    # a teammate (not the assignee) can tick it; the tick records who
    r = bob.post(f'/event-tasks/{tid}/toggle', json={'completed': True})
    assert r.status_code == 200 and r.get_json()['task']['done'] and r.get_json()['task']['completed_by'] == 'bob'
    # and untick
    r = alice.post(f'/event-tasks/{tid}/toggle')
    assert not r.get_json()['task']['done'] and r.get_json()['task']['completed_by'] == ''

    # someone not on the event cannot
    assert carol.post(f'/event-tasks/{tid}/toggle').status_code == 403


def test_shift_task_defaults_to_the_shift_holder(app, admin, alice):
    eid = make_event(admin)
    sid = put_on_team(admin, eid, 'alice')
    r = admin.post(f'/events/{eid}/tasks/add', json={'title': 'Focus the spots', 'shift_id': sid})
    t = r.get_json()['task']
    assert t['shift_id'] == sid and t['assignee'] == 'alice' and 'Sound' in t['shift']

    # a shift from a different event is refused
    other = make_event(admin, title='Other')
    osid = put_on_team(admin, other, 'alice')
    assert admin.post(f'/events/{eid}/tasks/add', json={'title': 'x', 'shift_id': osid}).status_code == 400


def test_deleting_a_shift_keeps_its_task_deleting_the_event_removes_it(app, admin, alice):
    eid = make_event(admin)
    sid = put_on_team(admin, eid, 'alice')
    tid = admin.post(f'/events/{eid}/tasks/add', json={'title': 'T', 'shift_id': sid}).get_json()['task']['id']

    aid = admin.get('/api/shifts', query_string={'event_id': eid}).get_json()[0]['assignments'][0]['id']
    assert admin.delete(f'/events/shift-assignments/{aid}').status_code == 200
    t = db.session.get(EventTask, tid)
    assert t is not None and t.shift_id is None and t.event_id == eid

    assert admin.delete(f'/events/{eid}').status_code == 200
    assert db.session.get(EventTask, tid) is None


def test_assigned_task_outside_an_event(app, admin, alice, bob):
    # admin only
    assert alice.post('/tasks/assign', json={'title': 'x', 'assigned_user_id': uid('bob')}).status_code == 403
    # a person is required
    assert admin.post('/tasks/assign', json={'title': 'Order gaff tape'}).status_code == 400
    r = admin.post('/tasks/assign', json={'title': 'Order gaff tape', 'assigned_user_id': uid('alice'), 'due_date': '2026-11-01'})
    assert r.status_code == 200
    t = r.get_json()['task']
    assert t['event_id'] is None and t['assignee'] == 'alice' and t['due'] == '2026-11-01'

    # the assignee can tick it, nobody else can
    assert alice.post(f"/event-tasks/{t['id']}/toggle").status_code == 200
    assert bob.post(f"/event-tasks/{t['id']}/toggle").status_code == 403
    # only admins edit it
    assert alice.put(f"/event-tasks/{t['id']}", json={'title': 'x'}).status_code == 403
    assert admin.put(f"/event-tasks/{t['id']}", json={'title': 'Order tape'}).status_code == 200


def test_pages_render_and_show_the_right_tasks(app, admin, alice, bob, carol):
    eid = make_event(admin, title='Panto')
    sid = put_on_team(admin, eid, 'alice')
    put_on_team(admin, eid, 'bob')
    admin.post(f'/events/{eid}/tasks/add', json={'title': 'EVENT-WIDE-TASK'})
    admin.post(f'/events/{eid}/tasks/add', json={'title': 'SHIFT-TASK', 'shift_id': sid})
    admin.post('/tasks/assign', json={'title': 'LOOSE-TASK', 'assigned_user_id': uid('carol')})

    page = admin.get(f'/events/{eid}')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'EVENT-WIDE-TASK' in html and 'SHIFT-TASK' in html and 'data-act="add-task"' in html
    assert 'data-act="add-shift-task"' in html and '0/1 tasks' in html

    # a team member sees the tasks but no edit controls
    html = bob.get(f'/events/{eid}').get_data(as_text=True)
    assert 'EVENT-WIDE-TASK' in html and 'data-act="add-task"' not in html and 'data-act="del-task"' not in html

    # Tasks page: linked people see the event's tasks, others only what is theirs
    html = alice.get('/todos').get_data(as_text=True)
    assert 'Open event' in html and 'EVENT-WIDE-TASK' in html and 'SHIFT-TASK' in html and 'LOOSE-TASK' not in html
    html = carol.get('/todos').get_data(as_text=True)
    assert 'LOOSE-TASK' in html and 'EVENT-WIDE-TASK' not in html and 'Open event' not in html
    html = admin.get('/todos').get_data(as_text=True)
    assert 'LOOSE-TASK' in html and 'EVENT-WIDE-TASK' in html and 'data-et="assign"' in html
