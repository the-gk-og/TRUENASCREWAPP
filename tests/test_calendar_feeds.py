"""Personal calendar subscriptions (/calendar/ics/<token>[/all])."""
import pytest

from extensions import db
from models import User, Event, CastMember, CastSchedule, EventSchedule, CrewAssignment
from services.security import throttle
from tests.test_events import app, admin, alice, client_for, uid, mk, ics_path   # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _fresh_throttle():
    throttle._failures.clear()
    yield
    throttle._failures.clear()


def body(c, path):
    r = c.get(path)
    assert r.status_code == 200, r.status_code
    return r.data.decode().replace('\r\n ', '')


def test_personal_feed_has_only_my_events_and_shifts(app, admin, alice):
    anon = app.test_client()
    mine = mk(admin, title='Gala', location='Main Hall')
    mk(admin, title='Other Show')
    admin.post(f'/events/{mine}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    path = ics_path(alice)
    b = body(anon, path)
    assert 'SUMMARY:Gala' in b and 'SUMMARY:Sound shift · Gala' in b
    assert 'Other Show' not in b
    assert 'LOCATION:Main Hall' in b and f'/events/{mine}' in b
    # all-events feed has everything
    b_all = body(anon, path + '/all')
    assert 'SUMMARY:Gala' in b_all and 'SUMMARY:Other Show' in b_all
    assert 'shift' not in b_all and 'X-WR-CALNAME:ShowWise - All events' in b_all
    # bob's feed does not contain alice's shift
    assert 'Sound shift' not in body(anon, ics_path(client_for(app, 'bob')))


def test_times_are_utc_from_venue_timezone(app, admin, alice):
    eid = mk(admin, title='Gala', event_date='2026-11-10T18:00', event_end_date='2026-11-10T22:00')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    b = body(app.test_client(), ics_path(alice))
    # Sydney is UTC+11 in November (daylight time)
    assert 'DTSTART:20261110T070000Z' in b and 'DTEND:20261110T110000Z' in b
    assert 'X-WR-TIMEZONE:Australia/Sydney' in b
    app.config['CALENDAR_TIMEZONE'] = 'Europe/London'
    assert 'DTSTART:20261110T180000Z' in body(app.test_client(), ics_path(alice))


def test_labeled_times_included(app, admin, alice):
    eid = mk(admin, title='Panto', times=[{'label': 'Show 1', 'start': '2026-11-10T19:00', 'end': '2026-11-10T21:00'}])
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    b = body(app.test_client(), ics_path(alice))
    assert 'SUMMARY:Panto - Show 1' in b


def test_cast_feed_uses_cast_text_only(app, admin):
    eid = mk(admin, title='Panto', description='CREW SECRET')
    cast = User(username='cassie', is_cast=True, user_role='cast')
    db.session.add(cast); db.session.commit()
    ev = db.session.get(Event, eid)
    ev.cast_description = 'Cast call info'
    db.session.add(CastMember(actor_name='Cassie', character_name='Dame', event_id=eid, user_id=cast.id))
    db.session.add(CastSchedule(event_id=eid, title='Warm-up', scheduled_time=ev.event_date))
    db.session.add(EventSchedule(event_id=eid, title='Crew bump-in', scheduled_time=ev.event_date))
    mk(admin, title='Not mine')
    db.session.commit()
    c = client_for(app, 'cassie')
    link = c.get('/api/calendar/sync-link').get_json()
    assert 'all_url' not in link
    path = '/' + link['url'].split('/', 3)[3]
    b = body(app.test_client(), path)
    assert 'SUMMARY:Panto' in b and 'Cast call info' in b and 'Warm-up' in b
    assert 'CREW SECRET' not in b and 'Crew bump-in' not in b and 'Not mine' not in b
    assert f'/cast-events/{eid}' in b
    assert app.test_client().get(path + '/all').status_code == 404


def test_etag_lets_calendar_apps_skip_unchanged_feeds(app, admin, alice):
    mk(admin, title='Gala')
    anon = app.test_client()
    path = ics_path(alice) + '/all'
    r1 = anon.get(path)
    etag = r1.headers['ETag']
    assert anon.get(path).headers['ETag'] == etag                # stable while nothing changes
    assert anon.get(path, headers={'If-None-Match': etag}).status_code == 304
    mk(admin, title='New Show')
    r3 = anon.get(path, headers={'If-None-Match': etag})
    assert r3.status_code == 200 and 'New Show' in r3.data.decode()


def test_reset_kills_both_feeds(app, alice):
    anon = app.test_client()
    old = ics_path(alice)
    alice.post('/api/calendar/sync-link/reset')
    assert anon.get(old).status_code == 404 and anon.get(old + '/all').status_code == 404


def test_bad_tokens_are_rate_limited(app, alice):
    anon = app.test_client()
    good = ics_path(alice)
    for i in range(20):
        assert anon.get('/calendar/ics/' + 'z' * 43).status_code == 404
    assert anon.get('/calendar/ics/' + 'z' * 43).status_code == 429
    assert anon.get(good).status_code == 429                  # the guessing IP is locked out


def test_valid_token_polling_is_capped(app, alice):
    from routes import calendar as cal
    anon = app.test_client()
    path = ics_path(alice)
    old = cal.FEED_HIT_LIMIT
    cal.FEED_HIT_LIMIT = 3
    try:
        assert [anon.get(path).status_code for _ in range(4)] == [200, 200, 200, 429]
    finally:
        cal.FEED_HIT_LIMIT = old


def test_settings_page_shows_calendar_tab(app, alice):
    html = alice.get('/settings').data.decode()
    assert 'tab-calendar' in html and '/api/calendar/sync-link' in html
