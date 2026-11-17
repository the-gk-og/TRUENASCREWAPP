"""Scan station (kiosk) mode: pairing, the device token's limited reach, badge/PIN sign-in,
scanning as the real person, quarantine, and the idle sign-out.
Run: pytest tests/test_scan_station.py"""
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import (Equipment, EquipmentUnit, Event, ScanStation,          # noqa: E402
                    StationBadge, UnitCheckout, User)
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401  (fixtures)
import routes.scan_station as ss                                           # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def new_station(admin, name='Store room', idle=90):
    r = admin.post('/admin/stations', json={'name': name, 'idle_seconds': idle})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def paired_device(app, admin, name='Store room', idle=90):
    """A fresh browser (no login) paired as a scan station."""
    j = new_station(admin, name, idle)
    dev = app.test_client()
    r = dev.post('/station/pair', data={'code': j['pairing']['code']})
    assert r.status_code == 302 and r.headers['Location'].endswith('/station')
    return dev, j['station']['id']


def badge_for(client):
    """Open the person's badge page (creates their badge) and return the code."""
    assert client.get('/settings/scan-badge').status_code == 200
    with client.session_transaction() as s:
        uid = int(s['_user_id'])
    return StationBadge.query.filter_by(user_id=uid).one().badge_code


@pytest.fixture()
def gear(app, admin):
    e = Equipment(name='Shure SM58', barcode='MIC', quantity_owned=2)
    db.session.add(e)
    db.session.commit()
    assert admin.post(f'/equipment/{e.id}/units', json={'count': 2}).status_code == 200
    ev = Event(title='Spring Musical', event_date=datetime.now() + timedelta(days=1))
    db.session.add(ev)
    db.session.commit()
    return e.id, ev.id


# ── pairing and the device token ─────────────────────────────────────────────

def test_admin_only_can_register(app, admin, alice):
    assert alice.post('/admin/stations', json={'name': 'x'}).status_code in (302, 403)
    assert alice.get('/admin/stations/api').status_code in (302, 403)
    j = new_station(admin)
    assert len(ss._clean_pair_code(j['pairing']['code'])) == 8
    st = db.session.get(ScanStation, j['station']['id'])
    assert st.token_hash is None and st.pairing_hash and j['pairing']['code'] not in (st.pairing_hash or '')
    assert admin.get('/admin/stations').status_code == 200


def test_pairing_sets_token_and_code_is_single_use(app, admin):
    j = new_station(admin)
    dev = app.test_client()
    assert dev.get('/station').status_code == 302                    # not paired: to the pairing page
    assert dev.get('/station/pair').status_code == 200
    assert dev.post('/station/pair', data={'code': 'WRON-GCOD'}).status_code == 400
    r = dev.post('/station/pair', data={'code': j['pairing']['code'].lower()})
    assert r.status_code == 302
    cookie = dev.get_cookie(ss.COOKIE, path='/station')
    assert cookie is not None and cookie.http_only and cookie.path == '/station'
    st = db.session.get(ScanStation, j['station']['id'])
    assert st.token_hash == ss._hash(cookie.value) and st.pairing_hash is None
    assert dev.get('/station').status_code == 200
    # The same code can't pair a second device
    other = app.test_client()
    assert other.post('/station/pair', data={'code': j['pairing']['code']}).status_code == 400


def test_expired_pairing_code_is_refused(app, admin):
    j = new_station(admin)
    st = db.session.get(ScanStation, j['station']['id'])
    st.pairing_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert app.test_client().post('/station/pair', data={'code': j['pairing']['code']}).status_code == 400


DEVICE_FORBIDDEN_GETS = ['/dashboard', '/admin', '/admin/stations', '/admin/stations/api', '/settings',
                         '/settings/scan-badge', '/equipment', '/equipment/checkout', '/events',
                         '/admin/api/users', '/api/search?q=mic', '/picklist']


def test_device_token_cannot_reach_other_pages(app, admin, alice, gear):
    eq_id, ev_id = gear
    dev, _ = paired_device(app, admin)
    # Even with someone signed in at the station, the rest of the app sees nobody
    assert dev.post('/station/api/identify', json={'badge': badge_for(alice)}).status_code == 200
    for path in DEVICE_FORBIDDEN_GETS:
        r = dev.get(path)
        assert r.status_code in (302, 401, 403, 404), (path, r.status_code)
        if r.status_code == 302:
            assert '/login' in r.headers['Location'] or '/station' not in r.headers['Location'], path
        assert b'Shure SM58' not in r.data, path
    # Direct writes outside /station are refused too
    for path, body in [('/equipment/checkout/scan', {'event_id': ev_id, 'code': 'MIC-01'}),
                       ('/admin/stations', {'name': 'sneaky'}),
                       ('/admin/users/add', {'username': 'x', 'password': 'y' * 12}),
                       (f'/equipment/unit/{EquipmentUnit.query.first().id}/release', {'outcome': 'available'})]:
        r = dev.post(path, json=body)
        assert r.status_code in (302, 401, 403), (path, r.status_code)
    assert UnitCheckout.query.count() == 0
    assert ScanStation.query.count() == 1


def test_station_cookie_is_only_sent_to_station_paths(app, admin):
    dev, _ = paired_device(app, admin)
    assert dev.get_cookie(ss.COOKIE, path='/station') is not None
    assert dev.get_cookie(ss.COOKIE, path='/') is None


def test_api_needs_a_paired_station(app, admin, alice):
    stranger = app.test_client()
    for path in ('/station/api/whoami', '/station/api/people', '/station/api/events'):
        assert stranger.get(path).status_code == 401
    r = stranger.post('/station/api/identify', json={'badge': badge_for(alice)})
    assert r.status_code == 401 and r.get_json()['code'] == 'no_station'
    # A forged cookie doesn't help
    stranger.set_cookie(ss.COOKIE, 'not-a-real-token', path='/station')
    assert stranger.get('/station/api/whoami').status_code == 401
    # Nor does a logged-in user's session: /station/api needs a station
    assert alice.post('/station/api/scan', json={'code': 'x'}).status_code == 401


def test_revoked_station_is_cut_off(app, admin, alice):
    dev, sid = paired_device(app, admin)
    assert dev.post('/station/api/identify', json={'badge': badge_for(alice)}).status_code == 200
    assert admin.post(f'/admin/stations/{sid}/revoke').status_code == 200
    assert dev.get('/station/api/events').status_code == 401
    assert dev.get('/station').status_code == 302
    assert admin.post(f'/admin/stations/{sid}/pair').status_code == 409


def test_repairing_replaces_the_old_device(app, admin):
    old, sid = paired_device(app, admin)
    code = admin.post(f'/admin/stations/{sid}/pair').get_json()['pairing']['code']
    new = app.test_client()
    assert new.post('/station/pair', data={'code': code}).status_code == 302
    assert new.get('/station/api/whoami').status_code == 200
    assert old.get('/station/api/whoami').status_code == 401


def test_kiosk_page_logs_out_a_real_session(app, admin):
    j = new_station(admin)
    # The admin pairs their own browser: it stops being signed in to the app
    assert admin.post('/station/pair', data={'code': j['pairing']['code']}).status_code == 302
    assert admin.get('/admin/stations/api').status_code in (302, 401, 403)


# ── identifying ──────────────────────────────────────────────────────────────

def test_badge_sign_in_and_new_badge(app, admin, alice):
    dev, _ = paired_device(app, admin)
    code = badge_for(alice)
    assert code.startswith('SWB')
    r = dev.post('/station/api/identify', json={'badge': code.lower()})
    assert r.status_code == 200 and r.get_json()['person']['name'] == 'alice'
    assert dev.get('/station/api/whoami').get_json()['person']['name'] == 'alice'
    assert dev.post('/station/api/identify', json={'badge': 'SWBNOPE'}).status_code == 401
    assert dev.get('/station/api/whoami').get_json()['person'] is None     # a failed try signs out
    # A new badge retires the old one
    assert alice.post('/settings/scan-badge/new').status_code == 200
    assert dev.post('/station/api/identify', json={'badge': code}).status_code == 401
    assert dev.post('/station/api/identify', json={'badge': badge_for(alice)}).status_code == 200


def test_pin_sign_in_and_lockout(app, admin, alice):
    dev, _ = paired_device(app, admin)
    assert alice.post('/settings/scan-badge/pin', json={'pin': '12'}).status_code == 400
    assert alice.post('/settings/scan-badge/pin', json={'pin': '1111'}).status_code == 400
    assert alice.post('/settings/scan-badge/pin', json={'pin': '4827'}).status_code == 200
    uid = User.query.filter_by(username='alice').one().id
    people = dev.get('/station/api/people').get_json()['people']
    assert people == [{'id': uid, 'name': 'alice'}]

    assert dev.post('/station/api/identify', json={'user_id': uid, 'pin': '4827'}).status_code == 200
    for _ in range(ss.PIN_MAX_FAILS):
        assert dev.post('/station/api/identify', json={'user_id': uid, 'pin': '0000'}).status_code == 401
    r = dev.post('/station/api/identify', json={'user_id': uid, 'pin': '4827'})
    assert r.status_code == 423                                           # locked, even with the right PIN
    b = StationBadge.query.filter_by(user_id=uid).one()
    b.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert dev.post('/station/api/identify', json={'user_id': uid, 'pin': '4827'}).status_code == 200


def test_cast_cannot_use_station(app, admin):
    db.session.add(User(username='carol', user_role='cast', is_cast=True, email='carol@x.test'))
    db.session.commit()
    carol = client_for(app, 'carol')
    assert carol.get('/settings/scan-badge').status_code == 403
    # Even with a badge row made some other way
    db.session.add(StationBadge(user_id=User.query.filter_by(username='carol').one().id, badge_code='SWBCAROLCAROLCAROL'))
    db.session.commit()
    dev, _ = paired_device(app, admin)
    assert dev.post('/station/api/identify', json={'badge': 'SWBCAROLCAROLCAROL'}).status_code == 401


# ── scanning as the real person ──────────────────────────────────────────────

def test_scan_out_and_back_recorded_as_person(app, admin, alice, gear):
    eq_id, ev_id = gear
    dev, _ = paired_device(app, admin)
    assert dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01'}).status_code == 401  # nobody yet
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})

    events = dev.get('/station/api/events').get_json()['events']
    assert [e['title'] for e in events] == ['Spring Musical']

    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01', 'mode': 'auto'})
    j = r.get_json()
    assert r.status_code == 200 and j['action'] == 'out'
    co = UnitCheckout.query.one()
    assert co.checked_out_by == 'alice' and co.event_id == ev_id

    # Bring it back with "return" mode (no event)
    r = dev.post('/station/api/scan', json={'event_id': None, 'code': 'MIC-01', 'mode': 'return'})
    assert r.status_code == 200 and r.get_json()['action'] == 'return'
    db.session.refresh(co)
    assert co.returned_by == 'alice'

    # Undo the return (only alice, the one who scanned it, may)
    r = dev.post(f'/station/api/undo/{co.id}', json={'action': 'return'})
    assert r.status_code == 200
    db.session.refresh(co)
    assert co.returned_at is None

    # The next person signs in: their scans are theirs
    assert alice.post('/settings/scan-badge/new').status_code == 200
    bob = client_for(app, 'bob')
    dev.post('/station/api/identify', json={'badge': badge_for(bob)})
    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01'})
    assert r.status_code == 200 and r.get_json()['action'] == 'return'
    db.session.refresh(co)
    assert co.returned_by == 'bob'
    # bob can't undo alice's check-out
    r = dev.post(f'/station/api/undo/{co.id}', json={'action': 'out'})
    assert r.status_code == 409


def test_quarantined_unit_cannot_go_out(app, admin, alice, gear):
    eq_id, ev_id = gear
    dev, _ = paired_device(app, admin)
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    unit = EquipmentUnit.query.filter_by(asset_tag='MIC-02').one()
    r = dev.post(f'/station/api/problem/{unit.id}', json={'reason': 'Grille dented', 'event_id': ev_id})
    assert r.status_code == 200
    db.session.refresh(unit)
    assert unit.status == 'quarantined' and unit.open_quarantine.quarantined_by == 'alice'
    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-02', 'force': True})
    assert r.status_code == 409 and r.get_json()['conflict'] == 'quarantined'
    assert UnitCheckout.query.count() == 0


def test_problem_on_an_item_that_is_out_returns_it_first(app, admin, alice, gear):
    eq_id, ev_id = gear
    dev, _ = paired_device(app, admin)
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01'})
    unit = EquipmentUnit.query.filter_by(asset_tag='MIC-01').one()
    assert dev.post(f'/station/api/problem/{unit.id}', json={'reason': 'Crackles'}).status_code == 200
    db.session.refresh(unit)
    assert unit.open_checkout is None and unit.status == 'quarantined'


def test_lookup_records_nothing(app, admin, alice, gear):
    dev, _ = paired_device(app, admin)
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    r = dev.post('/station/api/lookup', json={'code': 'MIC-01'})
    assert r.status_code == 200 and r.get_json()['kind'] == 'unit'
    assert UnitCheckout.query.count() == 0


def test_group_label_and_bulk(app, admin, alice, gear):
    eq_id, ev_id = gear
    cables = Equipment(name='XLR 10m', barcode='XLR', quantity_owned=20, tracking='bulk') \
        if 'tracking' in Equipment.__table__.c else None
    dev, _ = paired_device(app, admin)
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC'})
    assert r.status_code == 409 and r.get_json()['conflict'] == 'choose_unit'
    unit_id = r.get_json()['units'][0]['id']
    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'unit_id': unit_id, 'mode': 'out'})
    assert r.status_code == 200
    if cables is not None:
        db.session.add(cables)
        db.session.commit()
        r = dev.post('/station/api/bulk', json={'event_id': ev_id, 'equipment_id': cables.id, 'quantity': 4})
        assert r.status_code == 200
        assert r.get_json()['checkout']['checked_out_by'] == 'alice'


def test_idle_sign_out(app, admin, alice, gear, monkeypatch):
    eq_id, ev_id = gear
    dev, sid = paired_device(app, admin, idle=30)
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    assert dev.get('/station/api/events').status_code == 200
    real = ss.time.time
    monkeypatch.setattr(ss.time, 'time', lambda: real() + 31)
    r = dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01'})
    assert r.status_code == 401 and r.get_json()['code'] == 'no_person'
    assert UnitCheckout.query.count() == 0


def test_logout_and_station_switch(app, admin, alice, gear):
    eq_id, ev_id = gear
    dev, _ = paired_device(app, admin, name='Door A')
    dev.post('/station/api/identify', json={'badge': badge_for(alice)})
    assert dev.post('/station/api/logout').status_code == 200
    assert dev.post('/station/api/scan', json={'event_id': ev_id, 'code': 'MIC-01'}).status_code == 401


def test_deleting_a_user_removes_their_badge(app, admin):
    bob = client_for(app, 'bob')
    badge_for(bob)
    uid = User.query.filter_by(username='bob').one().id
    assert admin.delete(f'/admin/users/delete/{uid}').status_code == 200
    assert StationBadge.query.count() == 0


def test_kiosk_and_badge_pages_render(app, admin, alice):
    dev, _ = paired_device(app, admin)
    r = dev.get('/station')
    assert r.status_code == 200 and b'Scan your badge' in r.data and r.headers['Cache-Control'] == 'no-store'
    r = alice.get('/settings/scan-badge')
    assert r.status_code == 200 and b'data:image/png;base64' in r.data
    assert b'Scan badge' in alice.get('/settings').data
