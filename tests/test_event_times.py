"""Labeled event times (Bump-in, Show 1, Show 2), set in the create/edit event form.
Run: pytest tests/test_event_times.py"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_events import app, client_for, admin, alice  # noqa: E402,F401
from extensions import db                                      # noqa: E402
from models import Event, EventTime                            # noqa: E402

TIMES = [
    {'label': 'Bump-in', 'start': '2030-05-01T16:00', 'end': '2030-05-01T18:00'},
    {'label': 'Show 1', 'start': '2030-05-01T19:00', 'end': '2030-05-01T21:00'},
    {'label': 'Show 2', 'start': '2030-05-02T19:00', 'end': '2030-05-02T21:00'},
]


def create(c, times=TIMES, **kw):
    body = {'title': 'Panto', 'event_date': '2030-05-01T18:00', 'event_end_date': '2030-05-01T20:00',
            'times': times}
    body.update(kw)
    r = c.post('/events/add', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def test_create_with_times_keeps_dates_and_shows_each_time(app, admin):
    eid = create(admin)
    with app.app_context():
        e = db.session.get(Event, eid)
        assert [t.label for t in e.times] == ['Bump-in', 'Show 1', 'Show 2']
        assert e.event_date == datetime(2030, 5, 1, 16)            # widened to cover Bump-in
        assert e.event_end_date == datetime(2030, 5, 2, 21)        # and Show 2
    feed = admin.get('/api/calendar/feed?start=2030-04-28T00:00&end=2030-05-05T00:00').get_json()
    titles = sorted(i['title'] for i in feed if i['extendedProps'].get('kind') == 'event')
    assert titles == ['Panto - Bump-in', 'Panto - Show 1', 'Panto - Show 2']


def test_dates_typed_in_form_are_not_shrunk(app, admin):
    eid = create(admin, event_date='2030-05-01T08:00', event_end_date='2030-05-03T23:00')
    with app.app_context():
        e = db.session.get(Event, eid)
        assert e.event_date == datetime(2030, 5, 1, 8) and e.event_end_date == datetime(2030, 5, 3, 23)


def test_validation_and_permissions(app, admin, alice):
    bad = [{'label': 'x', 'start': '2030-05-01T18:00', 'end': '2030-05-01T16:00'}]
    r = admin.post('/events/add', json={'title': 'T', 'event_date': '2030-05-01T18:00', 'times': bad})
    assert r.status_code == 400
    r = admin.post('/events/add', json={'title': 'T', 'event_date': '2030-05-01T18:00',
                                        'times': [{'label': '', 'start': '2030-05-01T16:00', 'end': '2030-05-01T18:00'}]})
    assert r.status_code == 400
    eid = create(admin)
    assert alice.put(f'/events/{eid}/edit', json={'title': 'x', 'times': []}).status_code == 403


def test_edit_replaces_times_and_omitting_keeps_them(app, admin):
    eid = create(admin)
    assert admin.put(f'/events/{eid}/edit', json={'title': 'Panto II'}).status_code == 200      # no "times" key
    with app.app_context():
        assert EventTime.query.filter_by(event_id=eid).count() == 3
    new = [{'label': 'Matinee', 'start': '2030-05-01T13:00', 'end': '2030-05-01T15:00'}]
    assert admin.put(f'/events/{eid}/edit', json={'title': 'Panto II', 'times': new}).status_code == 200
    with app.app_context():
        assert [t.label for t in db.session.get(Event, eid).times] == ['Matinee']
    assert admin.put(f'/events/{eid}/edit', json={'title': 'Panto II', 'times': []}).status_code == 200
    with app.app_context():
        assert EventTime.query.count() == 0
    feed = admin.get('/api/calendar/feed?start=2030-04-28T00:00&end=2030-05-05T00:00').get_json()
    assert [i['title'] for i in feed if i['extendedProps'].get('kind') == 'event'] == ['Panto II']


def test_calendar_drag_of_one_time(app, admin):
    eid = create(admin)
    with app.app_context():
        tid = [t.id for t in db.session.get(Event, eid).times if t.label == 'Show 1'][0]
    assert admin.put(f'/events/times/{tid}/move', json={
        'event_date': '2030-05-04T19:00', 'event_end_date': '2030-05-04T21:00'}).status_code == 200
    with app.app_context():
        e = db.session.get(Event, eid)
        assert e.event_end_date == datetime(2030, 5, 4, 21)


def test_pages_duplicate_series_and_ics(app, admin):
    eid = create(admin)
    for url in (f'/events/{eid}', '/events', '/dashboard', '/calendar', f'/api/events/{eid}'):
        assert admin.get(url).status_code == 200, url
    assert b'Show 1' in admin.get(f'/events/{eid}').data
    new_id = admin.post(f'/events/{eid}/duplicate', json={'event_date': '2030-05-08T16:00'}).get_json()['id']
    with app.app_context():
        ts = db.session.get(Event, new_id).times
        assert sorted(t.label for t in ts) == ['Bump-in', 'Show 1', 'Show 2']
        assert min(t.start_time for t in ts) == datetime(2030, 5, 8, 16)
    sid = create(admin, recurrence={'pattern': 'weekly', 'count': 3})
    with app.app_context():
        root = db.session.get(Event, sid)
        kids = Event.query.filter_by(recurring_event_id=sid).all()
        assert len(kids) == 2 and all(len(k.times) == 3 for k in kids)
        assert kids[0].times[0].start_time == root.times[0].start_time.replace(day=8)


def test_series_edit_applies_times_to_every_event(app, admin):
    sid = create(admin, recurrence={'pattern': 'weekly', 'count': 3})
    new = [{'label': 'Show', 'start': '2030-05-01T19:00', 'end': '2030-05-01T21:00'}]
    r = admin.put(f'/events/{sid}/edit', json={'title': 'Panto', 'event_date': '2030-05-01T16:00',
                                                 'event_end_date': '2030-05-02T21:00', 'times': new, 'scope': 'all'})
    assert r.status_code == 200
    with app.app_context():
        starts = sorted(t.start_time for t in EventTime.query.all())
        assert starts == [datetime(2030, 5, 1, 19), datetime(2030, 5, 8, 19), datetime(2030, 5, 15, 19)]


def test_when_text_and_cascade(app, admin):
    from services.event_times import when_text
    eid = create(admin)
    with app.app_context():
        e = db.session.get(Event, eid)
        assert when_text(e, '\n').splitlines()[0].startswith('Bump-in: ')
        db.session.delete(e)
        db.session.commit()
        assert EventTime.query.count() == 0
