"""Scanning units out to events and back, and per-unit maintenance history.
Run: pytest tests/test_unit_tracking.py"""
import os, sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import (Equipment, EquipmentUnit, Event, PickListUnit,         # noqa: E402
                    UnitCheckout, UnitMaintenance)
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401  (fixtures)

MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


@pytest.fixture()
def mic(app, admin):
    e = Equipment(name='Shure SM58', barcode='MIC', quantity_owned=3)
    db.session.add(e)
    db.session.commit()
    r = admin.post(f'/equipment/{e.id}/units', json={'count': 3})
    assert r.status_code == 200
    return e.id


def tag(t):
    return EquipmentUnit.query.filter_by(asset_tag=t).first()


def mk_event(title, days=1):
    ev = Event(title=title, event_date=datetime.now() + timedelta(days=days))
    db.session.add(ev)
    db.session.commit()
    return ev.id


def mk_line(c, eq_id, event_id, qty=2):
    r = c.post('/picklist/add', json={'equipment_id': eq_id, 'quantity': qty, 'event_id': event_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def scan(c, event_id, code, **kw):
    return c.post('/equipment/checkout/scan', json={'event_id': event_id, 'code': code, **kw})


# ── Check out / return ───────────────────────────────────────────────────────

def test_scan_out_then_scan_again_returns(app, alice, mic):
    ev = mk_event('Spring Musical')
    line = mk_line(alice, mic, ev)
    assert alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-01'}).status_code == 200

    r = scan(alice, ev, 'MIC-01')
    j = r.get_json()
    assert r.status_code == 200 and j['action'] == 'out' and j['warnings'] == []
    co = UnitCheckout.query.one()
    assert co.checked_out_by == 'alice' and co.event_id == ev and co.returned_at is None

    # Unit, item page and pick list all show it as out
    u = alice.get(f'/equipment/unit/{tag("MIC-01").id}/json').get_json()['unit']
    assert u['checkout']['event_title'] == 'Spring Musical' and u['is_out']
    assert alice.get(f'/equipment/{mic}').status_code == 200
    state = alice.get(f'/picklist/state?event_id={ev}').get_json()
    assert state['items'][0]['units'] == [{'id': tag('MIC-01').id, 'asset_tag': 'MIC-01', 'out': True}]
    s = alice.get(f'/equipment/checkout/event/{ev}').get_json()
    assert [c['asset_tag'] for c in s['out']] == ['MIC-01'] and s['returned'] == []

    # Scanning the unit's QR URL again returns it (auto mode)
    r = scan(alice, ev, f'https://crew.example/equipment/unit/{tag("MIC-01").id}/view')
    assert r.status_code == 200 and r.get_json()['action'] == 'return'
    db.session.refresh(co)
    assert co.returned_by == 'alice' and co.returned_at is not None
    s = alice.get(f'/equipment/checkout/event/{ev}').get_json()
    assert s['out'] == [] and [c['asset_tag'] for c in s['returned']] == ['MIC-01']
    # A returned unit is still "booked" for the show (on its pick list) but not checked out
    u = alice.get(f'/equipment/unit/{tag("MIC-01").id}/json').get_json()['unit']
    assert u['checkout'] is None


def test_explicit_modes_and_return_button(app, alice, mic):
    ev = mk_event('Gig')
    mk_line(alice, mic, ev, qty=3)
    assert scan(alice, ev, 'MIC-02', mode='out').status_code == 200
    r = scan(alice, ev, 'mic-02', mode='out')                     # tags are case-insensitive
    assert r.status_code == 409 and r.get_json()['conflict'] == 'already_out'
    assert scan(alice, ev, 'MIC-03', mode='return').get_json()['conflict'] == 'not_out'

    # Return mode works without an event, from any event
    assert alice.post('/equipment/checkout/scan', json={'code': 'MIC-02', 'mode': 'return'}).status_code == 200

    assert scan(alice, ev, 'MIC-03').status_code == 200
    cid = UnitCheckout.query.filter_by(returned_at=None).one().id
    assert alice.post(f'/equipment/checkout/{cid}/return').status_code == 200
    assert alice.post(f'/equipment/checkout/{cid}/return').status_code == 409
    assert UnitCheckout.query.filter_by(returned_at=None).count() == 0


def test_scan_errors(app, alice, mic):
    ev = mk_event('Gig')
    assert scan(alice, ev, 'NOPE').status_code == 404
    r = scan(alice, ev, 'MIC')                                     # the item barcode, not a unit
    assert r.status_code == 404 and 'unit tags' in r.get_json()['error']
    assert alice.post('/equipment/checkout/scan', json={'code': 'MIC-01'}).status_code == 400   # no event
    assert scan(alice, ev, 'MIC-01', mode='sideways').status_code == 400
    db.session.add(Equipment(name='Gaffer tape', barcode='TAPE'))
    db.session.commit()
    assert 'quantity only' in scan(alice, ev, 'TAPE').get_json()['error']


def test_warns_when_not_on_pick_list_and_auto_allocates(app, alice, mic):
    ev = mk_event('Gig')
    # Nothing on the pick list: checks out with a warning
    j = scan(alice, ev, 'MIC-01').get_json()
    assert j['success'] and [w['code'] for w in j['warnings']] == ['not_on_picklist']

    # Item on the list with room: the scanned unit is allocated to that line
    line = mk_line(alice, mic, ev, qty=1)
    j = scan(alice, ev, 'MIC-02').get_json()
    assert j['warnings'] == [] and j['info']
    assert [l.unit.asset_tag for l in PickListUnit.query.filter_by(pick_list_item_id=line)] == ['MIC-02']

    # Line full and this unit isn't on it
    j = scan(alice, ev, 'MIC-03').get_json()
    assert j['success'] and [w['code'] for w in j['warnings']] == ['not_allocated']
    s = alice.get(f'/equipment/checkout/event/{ev}').get_json()
    assert len(s['out']) == 3


def test_blocks_repair_retired_and_out_elsewhere_until_confirmed(app, admin, alice, mic):
    ev1, ev2 = mk_event('Show A'), mk_event('Show B', 2)
    admin.put(f'/equipment/unit/{tag("MIC-01").id}', json={'status': 'repair'})
    admin.put(f'/equipment/unit/{tag("MIC-02").id}', json={'status': 'retired'})

    for t, code in (('MIC-01', 'status'), ('MIC-02', 'status')):
        r = scan(alice, ev1, t)
        assert r.status_code == 409 and r.get_json()['needs_confirm'] and r.get_json()['conflict'] == code
    assert UnitCheckout.query.count() == 0
    j = scan(alice, ev1, 'MIC-01', force=True).get_json()
    assert j['success'] and 'status' in [w['code'] for w in j['warnings']]
    assert 'repair' in UnitCheckout.query.one().notes

    # Out on Show A; scanning for Show B needs confirmation, then moves it
    assert scan(alice, ev2, 'MIC-03').status_code == 200
    r = scan(alice, ev1, 'MIC-03')
    assert r.status_code == 409 and r.get_json()['conflict'] == 'out_elsewhere'
    assert 'Show B' in r.get_json()['error']
    assert scan(alice, ev1, 'MIC-03', force=True).status_code == 200
    rows = UnitCheckout.query.filter_by(unit_id=tag('MIC-03').id).order_by(UnitCheckout.id).all()
    assert rows[0].event_id == ev2 and rows[0].returned_at is not None and 'Moved to Show A' in rows[0].notes
    assert rows[1].event_id == ev1 and rows[1].returned_at is None

    # Returning in auto mode against the wrong event says so
    assert scan(alice, ev2, 'MIC-03').status_code == 409        # it's out on A: auto tries to check out to B
    j = scan(alice, ev2, 'MIC-03', mode='return').get_json()
    assert j['action'] == 'return' and j['warnings'][0]['code'] == 'other_event'


def test_stale_checkouts_from_finished_events(app, alice, mic):
    past = Event(title='Last week', event_date=datetime.now() - timedelta(days=7))
    db.session.add(past)
    db.session.commit()
    assert scan(alice, past.id, 'MIC-01').status_code == 200
    page = alice.get('/equipment/checkout')
    assert page.status_code == 200 and b'Still out from finished events' in page.data
    assert b'not returned' in alice.get('/dashboard').data
    assert b'still out from finished events' in alice.get('/equipment').data


def test_checkout_page_renders_desktop_and_mobile(app, alice, mic):
    ev = mk_event('Gig')
    for ua in ('Mozilla/5.0 (X11; Linux x86_64)', MOBILE_UA):
        r = alice.get(f'/equipment/checkout?event_id={ev}', headers={'User-Agent': ua})
        assert r.status_code == 200 and b'sw-scanner.js' in r.data and b'Gig' in r.data
        assert alice.get(f'/picklist?event_id={ev}', headers={'User-Agent': ua}).data.count(
            f'/equipment/checkout?event_id={ev}'.encode()) >= 1
    assert alice.get('/equipment/checkout').status_code == 200
    assert alice.get('/equipment/checkout/event/9999').status_code == 404


def test_deleting_event_or_unit_removes_checkouts(app, admin, alice, mic):
    ev = mk_event('Gig')
    scan(alice, ev, 'MIC-01')
    scan(alice, ev, 'MIC-02')
    assert admin.delete(f'/equipment/unit/{tag("MIC-01").id}').status_code == 200
    assert UnitCheckout.query.count() == 1
    assert admin.delete(f'/events/{ev}').status_code == 200
    assert UnitCheckout.query.count() == 0


# ── Maintenance history ──────────────────────────────────────────────────────

def log(c, uid, **body):
    body.setdefault('kind', 'pat')
    body.setdefault('result', 'pass')
    return c.post(f'/equipment/unit/{uid}/maintenance', json=body)


def test_log_maintenance_and_history(app, alice, mic):
    uid = tag('MIC-01').id
    r = log(alice, uid, performed_on='2026-01-10', next_due='2027-01-10', notes='Insulation 200MΩ',
            performed_by='Sparky Ltd')
    assert r.status_code == 200
    rec = r.get_json()['record']
    assert rec['kind_label'] == 'PAT test' and rec['performed_by'] == 'Sparky Ltd' and rec['recorded_by'] == 'alice'
    # Default date is today; default "who" is the logged-in user
    rec = log(alice, uid, kind='inspection', result='note').get_json()['record']
    assert rec['performed_on'] == date.today().isoformat() and rec['performed_by'] == 'alice'

    h = alice.get(f'/equipment/unit/{uid}/history').get_json()
    assert [m['kind'] for m in h['maintenance']] == ['inspection', 'pat']      # newest first
    assert h['maintenance_due']['date'] == '2027-01-10'
    assert alice.get(f'/equipment/unit/{uid}/maintenance').get_json()['records'][1]['notes'] == 'Insulation 200MΩ'


def test_maintenance_validation(app, alice, mic):
    uid = tag('MIC-01').id
    assert log(alice, uid, kind='polish').status_code == 400
    assert log(alice, uid, result='meh').status_code == 400
    assert log(alice, uid, performed_on='yesterday').status_code == 400
    assert log(alice, uid, performed_on=(date.today() + timedelta(days=2)).isoformat()).status_code == 400
    assert log(alice, uid, performed_on='2026-01-10', next_due='2026-01-01').status_code == 400
    assert log(alice, uid, set_status='broken').status_code == 400
    assert alice.post('/equipment/unit/9999/maintenance', json={'kind': 'pat', 'result': 'pass'}).status_code == 404
    assert UnitMaintenance.query.count() == 0


def test_failed_test_sets_repair_and_admin_restores(app, admin, alice, mic):
    uid = tag('MIC-01').id
    r = log(alice, uid, result='fail', set_status='repair', notes='Earth continuity fail')
    assert r.status_code == 200 and r.get_json()['unit']['status'] == 'repair'
    assert db.session.get(EquipmentUnit, uid).status == 'repair'
    # Crew can't put it back in service; admins can
    assert log(alice, uid, kind='repair', result='repaired', set_status='available').status_code == 403
    assert db.session.get(EquipmentUnit, uid).status == 'repair'
    assert log(admin, uid, kind='repair', result='repaired', set_status='available').status_code == 200
    assert db.session.get(EquipmentUnit, uid).status == 'available'
    # A failed test without set_status leaves the status alone
    log(alice, tag('MIC-02').id, result='fail')
    assert tag('MIC-02').status == 'available'


def test_delete_maintenance_is_admin_only(app, admin, alice, mic):
    mid = log(alice, tag('MIC-01').id).get_json()['record']['id']
    assert alice.delete(f'/equipment/maintenance/{mid}').status_code == 403
    assert admin.delete(f'/equipment/maintenance/{mid}').status_code == 200
    assert UnitMaintenance.query.count() == 0


def test_due_dates_overdue_and_due_soon(app, alice, mic):
    today = date.today()
    u1, u2, u3 = (tag(t).id for t in ('MIC-01', 'MIC-02', 'MIC-03'))
    long_ago = (today - timedelta(days=400)).isoformat()
    # MIC-01: PAT overdue
    log(alice, u1, performed_on=long_ago, next_due=(today - timedelta(days=35)).isoformat())
    # MIC-02: PAT was overdue but a newer PAT replaced it (due in a year); inspection due in 10 days
    log(alice, u2, performed_on=long_ago, next_due=(today - timedelta(days=35)).isoformat())
    log(alice, u2, next_due=(today + timedelta(days=365)).isoformat())
    log(alice, u2, kind='inspection', performed_on=long_ago, next_due=(today + timedelta(days=10)).isoformat())
    # MIC-03: due in 3 months (not flagged)
    log(alice, u3, next_due=(today + timedelta(days=90)).isoformat())

    units = {u['asset_tag']: u for u in alice.get(f'/equipment/{mic}/units').get_json()['units']}
    assert units['MIC-01']['maintenance_due']['state'] == 'overdue'
    assert units['MIC-02']['maintenance_due']['state'] == 'due_soon'
    assert units['MIC-02']['maintenance_due']['kind'] == 'inspection'
    assert units['MIC-03']['maintenance_due']['state'] == 'ok'

    from routes.unit_tracking import maintenance_alerts
    alerts = maintenance_alerts()
    assert [(a['asset_tag'], a['due']['state']) for a in alerts] == [('MIC-01', 'overdue'), ('MIC-02', 'due_soon')]

    # Shown on the equipment page, item page and dashboard
    page = alice.get('/equipment').data
    assert b'1 unit overdue for testing' in page and b'1 due within 30 days' in page
    assert b'"maint": {"due_soon": 1, "overdue": 1}' in page or b'"overdue": 1' in page
    detail = alice.get(f'/equipment/{mic}').data
    assert b'Tests and inspections due' in detail and b'overdue since' in detail
    assert b'PAT test' in alice.get('/dashboard').data

    # Retired units drop out of the alerts
    db.session.get(EquipmentUnit, u1).status = 'retired'
    db.session.commit()
    assert [a['asset_tag'] for a in maintenance_alerts()] == ['MIC-02']


def test_detail_page_mobile_has_maintenance_ui(app, alice, mic):
    r = alice.get(f'/equipment/{mic}', headers={'User-Agent': MOBILE_UA})
    assert r.status_code == 200 and b'maintModal' in r.data and b'histModal' in r.data
