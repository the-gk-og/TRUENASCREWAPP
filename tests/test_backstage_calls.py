"""Backstage calls: call desk, display and polling state.  Run: pytest tests/test_backstage_calls.py"""
from datetime import datetime, timedelta

from tests.test_event_tasks import app, admin, alice, bob, make_event, client_for  # noqa: F401
from models import BackstageCall, Event, EventTime
from extensions import db


def future_event(admin):
    start = (datetime.now() + timedelta(hours=2)).replace(microsecond=0, second=0)
    return make_event(admin, event_date=start.strftime('%Y-%m-%dT%H:%M'),
                      event_end_date=(start + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'))


def test_manager_sends_calls_and_display_sees_them(app, admin, alice):
    eid = future_event(admin)
    r = admin.post(f'/events/{eid}/calls', json={'kind': 'half'})
    assert r.status_code == 200
    assert r.get_json()['call']['message'] == 'Half an hour, please'
    s = alice.get(f'/events/{eid}/calls/state').get_json()
    assert s['call']['message'] == 'Half an hour, please'
    assert 'log' not in s                       # crew don't get the log
    assert s['next']['label'] == 'Start'

    admin.post(f'/events/{eid}/calls', json={'kind': 'custom', 'message': 'Fire curtain in'})
    admin.post(f'/events/{eid}/calls', json={'kind': 'clear'})
    s = admin.get(f'/events/{eid}/calls/state').get_json()
    assert s['call'] is None
    assert [c['kind'] for c in s['log']] == ['clear', 'custom', 'half']
    assert BackstageCall.query.filter_by(event_id=eid).count() == 3


def test_permissions_and_validation(app, admin, alice):
    eid = future_event(admin)
    assert alice.post(f'/events/{eid}/calls', json={'kind': 'half'}).status_code == 403
    assert admin.post(f'/events/{eid}/calls', json={'kind': 'nope'}).status_code == 400
    assert admin.post(f'/events/{eid}/calls', json={'kind': 'custom', 'message': ' '}).status_code == 400
    assert admin.post(f'/events/{eid}/calls', json={'kind': 'custom', 'message': 'x' * 201}).status_code == 400
    # Crew: desk redirects to the display; display works.
    r = alice.get(f'/events/{eid}/calls')
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/events/{eid}/calls/display')
    assert alice.get(f'/events/{eid}/calls/display').status_code == 200
    assert admin.get(f'/events/{eid}/calls').status_code == 200
    # Logged out: no access.
    anon = app.test_client()
    assert anon.get(f'/events/{eid}/calls/state').status_code in (302, 401)


def test_next_time_uses_labeled_times(app, admin):
    eid = future_event(admin)
    ev = db.session.get(Event, eid)
    soon = datetime.now() + timedelta(minutes=30)
    db.session.add(EventTime(event_id=eid, label='Bump-in', start_time=soon, end_time=soon + timedelta(hours=1)))
    db.session.commit()
    s = admin.get(f'/events/{eid}/calls/state').get_json()
    assert s['next']['label'] == 'Bump-in'


def test_event_page_links(app, admin, alice):
    eid = future_event(admin)
    html = admin.get(f'/events/{eid}').get_data(as_text=True)
    assert f'/events/{eid}/calls' in html and f'/events/{eid}/calls/display' in html
    html = alice.get(f'/events/{eid}').get_data(as_text=True)
    assert f'/events/{eid}/calls/display' in html and 'Call desk' not in html
