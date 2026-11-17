"""Road cases / kits: packing, scanning a whole case out and in, missing and quarantined items.
Run: pytest tests/test_cases.py"""
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import CaseItem, EquipmentUnit, UnitCheckout                   # noqa: E402
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401  (fixtures)
from tests.test_quarantine_and_bulk import mk_event, tag, scan             # noqa: E402


@pytest.fixture()
def kit(app, admin):
    """Two road cases (RC-01, RC-02) and three mics (MIC-01..03)."""
    r = admin.post('/equipment/add', json={'name': 'Road case', 'barcode': 'RC', 'quantity_owned': 2,
                                           'tracking': 'bulk', 'is_case': True})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['item']['is_case'] and r.get_json()['item']['tracking'] == 'individual'
    r = admin.post('/equipment/add', json={'name': 'Shure SM58', 'barcode': 'MIC',
                                           'quantity_owned': 3, 'tracking': 'individual'})
    assert r.status_code == 200
    return tag('RC-01').id


def pack(c, case_id, code, **kw):
    return c.post(f'/equipment/case/{case_id}/items', json={'code': code, **kw})


def open_out(t):
    return tag(t).open_checkout


# ── Packing ──────────────────────────────────────────────────────────────────

def test_pack_and_unpack_by_scanning(app, alice, kit):
    r = pack(alice, kit, 'MIC-01')
    assert r.status_code == 200, r.get_json()
    assert [c['asset_tag'] for c in r.get_json()['case']['contents']] == ['MIC-01']
    # Scanned the full QR URL too
    assert pack(alice, kit, f'https://x.test/equipment/unit/{tag("MIC-02").id}/view').status_code == 200
    assert alice.get(f'/equipment/case/{kit}/json').get_json()['count'] == 2
    assert pack(alice, kit, 'MIC-01').status_code == 409                    # already here
    r = alice.delete(f'/equipment/case/{kit}/items/{tag("MIC-01").id}')
    assert r.status_code == 200 and r.get_json()['case']['count'] == 1


def test_an_item_is_in_one_case_at_a_time(app, alice, kit):
    other = tag('RC-02').id
    pack(alice, kit, 'MIC-01')
    r = pack(alice, other, 'MIC-01')
    assert r.status_code == 409 and r.get_json()['conflict'] == 'in_other_case' and r.get_json()['needs_confirm']
    r = pack(alice, other, 'MIC-01', move=True)
    assert r.status_code == 200
    assert CaseItem.query.filter_by(unit_id=tag('MIC-01').id).count() == 1
    assert tag('MIC-01').case_link.case_id == other


def test_cases_cant_nest_or_hold_group_labels(app, alice, kit):
    assert pack(alice, kit, 'RC-02').status_code == 400
    assert pack(alice, kit, 'RC-01').status_code == 400
    assert pack(alice, kit, 'MIC').get_json()['conflict'] == 'group_label'
    assert pack(alice, kit, 'NOPE').status_code == 404
    # A normal unit has no case page
    assert alice.get(f'/equipment/case/{tag("MIC-01").id}').status_code == 404


def test_quarantined_item_in_case_is_flagged(app, alice, kit):
    alice.post(f'/equipment/unit/{tag("MIC-02").id}/quarantine', json={'reason': 'Grille dented'})
    r = pack(alice, kit, 'MIC-02')
    assert r.status_code == 200 and r.get_json()['warnings']
    data = alice.get(f'/equipment/case/{kit}/json').get_json()
    assert data['quarantined'] == 1 and data['contents'][0]['quarantine_reason'] == 'Grille dented'


# ── Scanning a whole case ────────────────────────────────────────────────────

def test_case_scan_takes_everything_out_and_back(app, alice, kit):
    ev = mk_event('Gig')
    for t in ('MIC-01', 'MIC-02'):
        pack(alice, kit, t)
    r = scan(alice, ev, 'RC-01')
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d['is_case'] and d['action'] == 'out' and len(d['moved']) == 3
    assert all(open_out(t) and open_out(t).event_id == ev for t in ('RC-01', 'MIC-01', 'MIC-02'))
    assert open_out('MIC-03') is None
    # The event's out list shows all three
    assert len(alice.get(f'/equipment/checkout/event/{ev}').get_json()['out']) == 3
    # Scan again (auto): everything comes back
    r = scan(alice, ev, 'RC-01')
    assert r.status_code == 200 and r.get_json()['action'] == 'return'
    assert all(open_out(t) is None for t in ('RC-01', 'MIC-01', 'MIC-02'))


def test_case_scan_works_without_an_event_for_returns(app, alice, kit):
    """The offline queue replays {event_id, mode, code}; a return needs no event."""
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01')
    scan(alice, ev, 'RC-01')
    r = alice.post('/equipment/checkout/scan', json={'event_id': None, 'mode': 'return', 'code': 'RC-01'})
    assert r.status_code == 200 and r.get_json()['action'] == 'return'
    assert open_out('MIC-01') is None


def test_quarantined_contents_stay_behind(app, alice, kit):
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01'); pack(alice, kit, 'MIC-02')
    alice.post(f'/equipment/unit/{tag("MIC-02").id}/quarantine', json={'reason': 'Crackles'})
    r = scan(alice, ev, 'RC-01')
    assert r.status_code == 200
    assert any(w['code'] == 'quarantined' for w in r.get_json()['warnings'])
    assert open_out('MIC-01') and open_out('MIC-02') is None


def test_quarantined_case_cant_go_out(app, alice, kit):
    ev = mk_event('Gig')
    alice.post(f'/equipment/unit/{kit}/quarantine', json={'reason': 'Broken latch'})
    r = scan(alice, ev, 'RC-01')
    assert r.status_code == 409 and r.get_json()['conflict'] == 'quarantined'


def test_contents_out_elsewhere_need_confirm(app, alice, kit):
    ev1, ev2 = mk_event('One'), mk_event('Two', days=2)
    pack(alice, kit, 'MIC-01')
    assert scan(alice, ev1, 'MIC-01').status_code == 200
    r = scan(alice, ev2, 'RC-01')
    assert r.status_code == 409 and r.get_json()['needs_confirm'] and r.get_json()['is_case']
    r = scan(alice, ev2, 'RC-01', force=True, mode='out')
    assert r.status_code == 200
    assert open_out('MIC-01').event_id == ev2


def test_flag_missing_on_the_way_out(app, alice, kit):
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01'); pack(alice, kit, 'MIC-02')
    scan(alice, ev, 'RC-01')
    r = alice.post(f'/equipment/case/{kit}/missing',
                   json={'unit_id': tag('MIC-02').id, 'event_id': ev, 'action': 'out'})
    assert r.status_code == 200
    assert open_out('MIC-02') is None                 # it never left
    assert tag('MIC-02').case_link.missing_at is not None
    # Next time the case goes out, the missing item is left behind
    scan(alice, ev, 'RC-01')                          # back in
    r = scan(alice, ev, 'RC-01')
    assert r.get_json()['action'] == 'out' and open_out('MIC-02') is None
    assert any(w['code'] == 'missing' for w in r.get_json()['warnings'])
    # Found: scanning it back into the case clears the flag
    assert pack(alice, kit, 'MIC-02').status_code == 200
    assert tag('MIC-02').case_link.missing_at is None


def test_flag_missing_on_return_keeps_it_out(app, alice, kit):
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01'); pack(alice, kit, 'MIC-02')
    scan(alice, ev, 'RC-01')
    scan(alice, ev, 'RC-01')                          # back in
    r = alice.post(f'/equipment/case/{kit}/missing',
                   json={'unit_id': tag('MIC-01').id, 'event_id': ev, 'action': 'return'})
    assert r.status_code == 200
    co = open_out('MIC-01')
    assert co and co.event_id == ev and 'Missing from case' in co.notes
    assert alice.post(f'/equipment/case/{kit}/items/{tag("MIC-01").id}/found').status_code == 200
    assert tag('MIC-01').case_link.missing_at is None


def test_undo_a_case_scan(app, alice, kit):
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01')
    scan(alice, ev, 'RC-01')
    assert alice.post(f'/equipment/case/{kit}/undo', json={'action': 'out'}).status_code == 200
    assert UnitCheckout.query.count() == 0
    scan(alice, ev, 'RC-01'); scan(alice, ev, 'RC-01')
    assert alice.post(f'/equipment/case/{kit}/undo', json={'action': 'return'}).status_code == 200
    assert open_out('RC-01') and open_out('MIC-01')


def test_single_item_from_a_case_warns(app, alice, kit):
    ev = mk_event('Gig')
    pack(alice, kit, 'MIC-01')
    r = scan(alice, ev, 'MIC-01')
    assert r.status_code == 200 and any(w['code'] == 'in_case' for w in r.get_json()['warnings'])


# ── Pages ────────────────────────────────────────────────────────────────────

def test_pages_show_membership_and_contents(app, admin, kit):
    pack(admin, kit, 'MIC-01')
    mic_type = tag('MIC-01').equipment_id
    page = admin.get(f'/equipment/{mic_type}').get_data(as_text=True)
    assert 'In case RC-01' in page
    page = admin.get(f'/equipment/case/{kit}').get_data(as_text=True)
    assert 'MIC-01' in page and 'Print contents label' in page
    label = admin.get(f'/equipment/case/{kit}/label').get_data(as_text=True)
    assert 'RC-01' in label and 'MIC-01' in label
    # The case's QR lands on the case page; a scan look-up points there too
    r = admin.get(f'/equipment/unit/{kit}/view')
    assert r.status_code == 302 and f'/equipment/case/{kit}' in r.headers['Location']
    assert admin.post('/api/scan', json={'code': 'RC-01'}).get_json()['url'] == f'/equipment/case/{kit}'
    assert tag('MIC-01').to_dict()['in_case']['case_tag'] == 'RC-01'


def test_deleting_case_or_item_cleans_up(app, admin, kit):
    pack(admin, kit, 'MIC-01'); pack(admin, kit, 'MIC-02')
    assert admin.delete(f'/equipment/unit/{tag("MIC-01").id}').status_code == 200
    assert CaseItem.query.count() == 1
    assert admin.delete(f'/equipment/unit/{kit}').status_code == 200
    assert CaseItem.query.count() == 0 and tag('MIC-02') is not None


def test_cant_unmark_case_type_while_packed(app, admin, kit):
    pack(admin, kit, 'MIC-01')
    rc_type = tag('RC-01').equipment_id
    assert admin.put(f'/equipment/update/{rc_type}', json={'is_case': False}).status_code == 409
    admin.delete(f'/equipment/case/{kit}/items/{tag("MIC-01").id}')
    assert admin.put(f'/equipment/update/{rc_type}', json={'is_case': False}).status_code == 200
