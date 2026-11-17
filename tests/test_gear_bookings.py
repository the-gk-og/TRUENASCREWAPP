"""Gear double-booking: event windows and scan-out warnings for reserved units."""
import os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import Event, EventTime                                        # noqa: E402
from services.gear_bookings import event_window, overlaps                  # noqa: E402
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401
from tests.test_unit_tracking import mic, mk_line, scan                    # noqa: E402,F401


def _ev(title, start, hours=3):
    ev = Event(title=title, event_date=start, event_end_date=start + timedelta(hours=hours))
    db.session.add(ev)
    db.session.commit()
    return ev


def test_window_includes_labeled_times(app):
    start = datetime(2030, 5, 1, 19)
    ev = _ev('Show', start)
    db.session.add(EventTime(event_id=ev.id, label='Bump-in', start_time=start - timedelta(days=1),
                             end_time=start - timedelta(hours=20)))
    db.session.commit()
    s, e = event_window(ev)
    assert s == start - timedelta(days=1) and e == start + timedelta(hours=3)


def test_overlaps():
    a = (datetime(2030, 1, 1, 10), datetime(2030, 1, 1, 12))
    assert overlaps(a, (datetime(2030, 1, 1, 11), datetime(2030, 1, 1, 13)))
    assert not overlaps(a, (datetime(2030, 1, 1, 13), datetime(2030, 1, 1, 14)))


def test_scan_out_warns_when_reserved_for_overlapping_event(app, alice, mic):
    start = datetime.now() + timedelta(days=3)
    a, b = _ev('Concert A', start), _ev('Concert B', start + timedelta(hours=1))
    a_id, b_id = a.id, b.id
    line = mk_line(alice, mic, a_id, qty=1)
    assert alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-01'}).status_code == 200
    j = scan(alice, b_id, 'MIC-01').get_json()
    assert j['action'] == 'out'                       # a warning, not a block
    assert any(w['code'] == 'reserved_elsewhere' and 'Concert A' in w['message'] for w in j['warnings'])


def test_no_warning_when_reservation_does_not_overlap(app, alice, mic):
    start = datetime.now() + timedelta(days=3)
    a, b = _ev('Week one', start), _ev('Week two', start + timedelta(days=7))
    a_id, b_id = a.id, b.id
    line = mk_line(alice, mic, a_id, qty=1)
    alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-01'})
    j = scan(alice, b_id, 'MIC-01').get_json()
    assert not any(w['code'] == 'reserved_elsewhere' for w in j['warnings'])


# ── Over-commitment across overlapping events ────────────────────────────────

from models import (BulkCheckout, Equipment, EquipmentUnit, PickListItem,     # noqa: E402
                    UnitCheckout, UnitMaintenance)
from services.gear_bookings import (event_gear_warnings, equipment_bookings,  # noqa: E402
                                    type_status)


def _type(name='Par can', units=4, bulk=None):
    eq = Equipment(name=name, barcode=name.upper().replace(' ', ''),
                   quantity_owned=bulk if bulk is not None else units,
                   tracking='bulk' if bulk is not None else 'individual')
    db.session.add(eq)
    db.session.flush()
    if bulk is None:
        for i in range(units):
            db.session.add(EquipmentUnit(equipment_id=eq.id, asset_tag=f'{eq.barcode}-{i + 1}'))
    db.session.commit()
    return eq


def _line(eq, ev, qty, **kw):
    line = PickListItem(item_name=eq.name, equipment_id=eq.id, event_id=ev.id, quantity=qty, **kw)
    db.session.add(line)
    db.session.commit()
    return line


def test_overlapping_events_that_need_too_many_are_flagged(app):
    start = datetime.now() + timedelta(days=10)
    eq = _type(units=4)
    a, b = _ev('Show A', start), _ev('Show B', start + timedelta(hours=1))
    _line(eq, a, 3)
    lb = _line(eq, b, 2)
    s = type_status(eq, b)
    assert (s['need'], s['peak'], s['usable'], s['short']) == (2, 5, 4, 1)
    assert 'Show A needs 3 at the same time' in s['message']
    rep = event_gear_warnings(b)
    assert rep['count'] == 1 and rep['by_line'][lb.id] == [s['message']]


def test_peak_does_not_add_events_that_miss_each_other(app):
    # A festival weekend overlaps both a Saturday and a Sunday show, which don't overlap
    sat = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=20)
    eq = _type(units=4)
    fest = _ev('Festival', sat, hours=40)
    _line(eq, fest, 2)
    _line(eq, _ev('Sat show', sat, hours=3), 2)
    _line(eq, _ev('Sun show', sat + timedelta(days=1), hours=3), 2)
    s = type_status(eq, fest)
    assert s['peak'] == 4 and not s['short']


def test_unusable_units_reduce_what_is_free(app, alice):
    start = datetime.now() + timedelta(days=10)
    eq = _type(units=4)
    old = _ev('Old show', datetime.now() - timedelta(days=5))
    ev = _ev('Next show', start)
    u = sorted(eq.units, key=lambda x: x.asset_tag)
    u[0].status = 'repair'
    u[1].status = 'quarantined'
    db.session.add(UnitCheckout(unit_id=u[2].id, event_id=old.id, checked_out_by='alice'))
    db.session.commit()
    _line(eq, ev, 2)
    s = type_status(eq, ev)
    assert (s['usable'], s['short'], s['repair'], s['quarantined']) == (1, 1, 1, 1)
    assert 'still out on Old show' in s['message'] and 'in repair' in s['message']


def test_bulk_types_count_what_is_still_out(app):
    start = datetime.now() + timedelta(days=10)
    eq = _type('Cable', bulk=10)
    old = _ev('Old show', datetime.now() - timedelta(days=5))
    db.session.add(BulkCheckout(equipment_id=eq.id, event_id=old.id, quantity=4))
    db.session.commit()
    ev = _ev('Next', start)
    _line(eq, ev, 8)
    s = type_status(eq, ev)
    assert (s['usable'], s['short']) == (6, 2) and 'still out on Old show' in s['message']


def test_hold_window_makes_events_overlap(app, alice):
    start = datetime.now() + timedelta(days=10)
    eq = _type(units=2)
    a = _ev('Prep heavy', start + timedelta(days=1))
    b = _ev('Day before', start)
    la = _line(eq, a, 2)
    _line(eq, b, 1)
    assert not type_status(eq, a)['short']
    # Collect a's gear a day early: now it's needed while b has one
    r = alice.post(f'/picklist/{la.id}/hold', json={'hold_from': (start - timedelta(hours=1)).isoformat()})
    assert r.status_code == 200, r.get_json()
    assert type_status(eq, a)['short'] == 1
    # Clearing it goes back to the event's own times; bad input is refused
    assert alice.post(f'/picklist/{la.id}/hold', json={'hold_from': ''}).status_code == 200
    assert db.session.get(PickListItem, la.id).hold_from is None
    assert alice.post(f'/picklist/{la.id}/hold', json={'hold_from': 'soon'}).status_code == 400
    assert alice.post(f'/picklist/{la.id}/hold', json={
        'hold_from': start.isoformat(), 'hold_until': (start - timedelta(days=1)).isoformat()}).status_code == 400


# ── Specific units ──────────────────────────────────────────────────────────

def test_units_reserved_ahead_only_clash_when_times_overlap(app, alice, mic):
    start = datetime.now() + timedelta(days=10)
    a, b, c = _ev('A', start), _ev('B', start + timedelta(days=30)), _ev('C', start + timedelta(hours=1))
    la, lb, lc = (mk_line(alice, mic, e.id, qty=1) for e in (a, b, c))
    assert alice.post(f'/picklist/{la}/units', json={'asset_tag': 'MIC-01'}).status_code == 200
    # Next month: reserving it ahead is fine
    assert alice.post(f'/picklist/{lb}/units', json={'asset_tag': 'MIC-01'}).status_code == 200
    # Same evening: needs confirming, and then both lists warn
    r = alice.post(f'/picklist/{lc}/units', json={'asset_tag': 'MIC-01'})
    assert r.status_code == 409 and r.get_json()['conflict'] == 'allocated'
    assert [x['event_title'] for x in r.get_json()['allocations']] == ['A']
    assert alice.post(f'/picklist/{lc}/units', json={'asset_tag': 'MIC-01', 'force': True}).status_code == 200
    rep = event_gear_warnings(a)
    assert any(u['code'] == 'double_booked' and 'C' in u['message'] for u in rep['units'])
    assert not any('B' in u['message'] for u in rep['units'])


def test_unit_issues_cover_status_still_out_and_maintenance(app, alice, mic):
    from datetime import date
    start = datetime.now() + timedelta(days=10)
    ev, old = _ev('Gig', start), _ev('Last gig', datetime.now() - timedelta(days=3))
    line = mk_line(alice, mic, ev.id, qty=3)
    for t in ('MIC-01', 'MIC-02', 'MIC-03'):
        alice.post(f'/picklist/{line}/units', json={'asset_tag': t})
    u1, u2, u3 = (EquipmentUnit.query.filter_by(asset_tag=t).one() for t in ('MIC-01', 'MIC-02', 'MIC-03'))
    u1.status = 'repair'
    db.session.add(UnitCheckout(unit_id=u2.id, event_id=old.id, checked_out_by='alice'))
    db.session.add(UnitMaintenance(unit_id=u3.id, kind='pat', performed_on=date.today() - timedelta(days=360),
                                   result='pass', next_due=date.today() + timedelta(days=5)))
    db.session.commit()
    codes = {u['asset_tag']: u['code'] for u in event_gear_warnings(ev)['units']}
    assert codes == {'MIC-01': 'repair', 'MIC-02': 'still_out', 'MIC-03': 'maintenance'}


# ── Where people see it ─────────────────────────────────────────────────────

def test_warnings_show_on_pick_list_event_page_and_json(app, alice):
    start = datetime.now() + timedelta(days=10)
    eq = _type(units=1)
    a, b = _ev('Show A', start), _ev('Show B', start + timedelta(hours=1))
    _line(eq, a, 1)
    lb = _line(eq, b, 1)
    page = alice.get(f'/picklist?event_id={b.id}').get_data(as_text=True)
    assert 'gearClashes' in page and 'Short 1 × Par can' in page and 'pl-item clash' in page
    page = alice.get(f'/events/{b.id}').get_data(as_text=True)
    assert 'gearClashes' in page and 'Show A needs 1 at the same time' in page
    j = alice.get(f'/picklist/warnings?event_id={b.id}').get_json()
    assert j['count'] == 1 and str(lb.id) in j['by_line']
    # No clash, no banner
    other = _ev('Quiet', start + timedelta(days=40))
    _line(_type('Haze', units=2), other, 1)
    assert 'gearClashes' not in alice.get(f'/picklist?event_id={other.id}').get_data(as_text=True)


def test_booked_on_views(app, alice, mic):
    start = datetime.now() + timedelta(days=10)
    a, b = _ev('Matinee', start), _ev('Evening', start + timedelta(days=2))
    old = _ev('Done', datetime.now() - timedelta(days=9))
    la = mk_line(alice, mic, a.id, qty=1)
    mk_line(alice, mic, b.id, qty=2)
    mk_line(alice, mic, old.id, qty=1)
    alice.post(f'/picklist/{la}/units', json={'asset_tag': 'MIC-02'})
    eq = db.session.get(Equipment, mic)
    rows = equipment_bookings(eq)
    assert [(r['event_title'], r['qty'], r['units']) for r in rows] == [('Matinee', 1, ['MIC-02']), ('Evening', 2, [])]
    page = alice.get(f'/equipment/{mic}').get_data(as_text=True)
    assert 'Booked on' in page and 'Matinee' in page and 'Evening' in page and 'Done' not in page.split('Booked on')[1].split('</section>')[0]
    j = alice.get(f'/equipment/{mic}/bookings').get_json()
    assert [r['event_title'] for r in j['bookings']] == ['Matinee', 'Evening']
    uid = EquipmentUnit.query.filter_by(asset_tag='MIC-02').one().id
    j = alice.get(f'/equipment/unit/{uid}/bookings').get_json()
    assert [(r['event_title'], r['kind']) for r in j['bookings']] == [('Matinee', 'reserved')]
