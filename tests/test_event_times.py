"""Labeled event times (Bump-in, Show 1, Show 2).  Run: pytest tests/test_event_times.py"""
import os, sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_events import app, client_for, admin, alice  # noqa: E402,F401
from extensions import db                                      # noqa: E402
from models import Event, EventTime                            # noqa: E402


def _event(app):
    with app.app_context():
        e = Event(title='Panto', event_date=datetime(2030, 5, 1, 9), event_end_date=datetime(2030, 5, 1, 12),
                  created_by='boss')
        db.session.add(e)
        db.session.commit()
        return e.id


def _add(c, eid, label, start, end):
    return c.post(f'/events/{eid}/times/add', json={'label': label, 'start_time': start, 'end_time': end})


def test_add_times_syncs_span_and_calendar(app, admin):
    eid = _event(app)
    assert _add(admin, eid, 'Bump-in', '2030-05-01T16:00', '2030-05-01T18:00').status_code == 200
    assert _add(admin, eid, 'Show 1', '2030-05-01T19:00', '2030-05-01T21:00').status_code == 200
    assert _add(admin, eid, 'Show 2', '2030-05-02T19:00', '2030-05-02T21:00').status_code == 200
    with app.app_context():
        e = db.session.get(Event, eid)
        assert e.event_date == datetime(2030, 5, 1, 16)
        assert e.event_end_date == datetime(2030, 5, 2, 21)
    r = admin.get('/api/calendar/feed?start=2030-04-28T00:00&end=2030-05-05T00:00')
    titles = sorted(i['title'] for i in r.get_json() if i['extendedProps'].get('kind') == 'event')
    assert titles == ['Panto - Bump-in', 'Panto - Show 1', 'Panto - Show 2']


def test_validation_and_permissions(app, admin, alice):
    eid = _event(app)
    assert _add(admin, eid, 'Bad', '2030-05-01T18:00', '2030-05-01T16:00').status_code == 400
    assert _add(admin, eid, '', '2030-05-01T16:00', '2030-05-01T18:00').status_code == 400
    assert _add(alice, eid, 'Nope', '2030-05-01T16:00', '2030-05-01T18:00').status_code == 403


def test_edit_move_delete_time(app, admin):
    eid = _event(app)
    tid = _add(admin, eid, 'Show', '2030-05-01T19:00', '2030-05-01T21:00').get_json()['id']
    assert admin.put(f'/events/times/{tid}/edit', json={
        'label': 'Matinee', 'start_time': '2030-05-01T13:00', 'end_time': '2030-05-01T15:00'}).status_code == 200
    assert admin.put(f'/events/times/{tid}/move', json={
        'event_date': '2030-05-03T13:00', 'event_end_date': '2030-05-03T15:00'}).status_code == 200
    with app.app_context():
        assert db.session.get(Event, eid).event_date == datetime(2030, 5, 3, 13)
        assert db.session.get(EventTime, tid).label == 'Matinee'
    assert admin.delete(f'/events/times/{tid}/delete').status_code == 200
    with app.app_context():
        assert EventTime.query.count() == 0


def test_pages_duplicate_and_ics(app, admin):
    eid = _event(app)
    _add(admin, eid, 'Bump-in', '2030-05-01T16:00', '2030-05-01T18:00')
    _add(admin, eid, 'Show 1', '2030-05-01T19:00', '2030-05-01T21:00')
    for url in (f'/events/{eid}', '/events', '/dashboard', '/calendar'):
        assert admin.get(url).status_code == 200, url
    assert b'Panto - Show 1' in admin.get(f'/events/{eid}').data
    r = admin.post(f'/events/{eid}/duplicate', json={'event_date': '2030-05-08T16:00'})
    new_id = r.get_json()['id']
    with app.app_context():
        ts = db.session.get(Event, new_id).times
        assert sorted(t.label for t in ts) == ['Bump-in', 'Show 1']
        assert min(t.start_time for t in ts) == datetime(2030, 5, 8, 16)


def test_editing_event_keeps_time_driven_dates(app, admin):
    eid = _event(app)
    _add(admin, eid, 'Show', '2030-05-01T19:00', '2030-05-01T21:00')
    r = admin.put(f'/events/{eid}/edit', json={'title': 'Panto II', 'event_date': '2031-01-01T09:00',
                                                 'event_end_date': '2031-01-01T10:00'})
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(Event, eid)
        assert e.title == 'Panto II' and e.event_date == datetime(2030, 5, 1, 19)


def test_when_text_and_cascade(app, admin):
    from services.event_times import when_text
    eid = _event(app)
    _add(admin, eid, 'Show 1', '2030-05-01T19:00', '2030-05-01T21:00')
    with app.app_context():
        e = db.session.get(Event, eid)
        assert when_text(e, '\n').startswith('Show 1: ')
        db.session.delete(e)
        db.session.commit()
        assert EventTime.query.count() == 0
