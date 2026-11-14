"""Item types tracked individually or in bulk, group labels, quarantine, bulk check-out.
Run: pytest tests/test_quarantine_and_bulk.py"""
import io
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import (Equipment, EquipmentUnit, Event, UnitCheckout,         # noqa: E402
                    UnitMaintenance, UnitQuarantine, BulkCheckout)
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401  (fixtures)

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')


def mk_event(title, days=1):
    ev = Event(title=title, event_date=datetime.now() + timedelta(days=days))
    db.session.add(ev)
    db.session.commit()
    return ev.id


def tag(t):
    return EquipmentUnit.query.filter_by(asset_tag=t).first()


@pytest.fixture()
def mic(app, admin):
    r = admin.post('/equipment/add', json={'name': 'Shure SM58', 'barcode': 'MIC',
                                           'quantity_owned': 3, 'tracking': 'individual'})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


@pytest.fixture()
def tape(app, admin):
    r = admin.post('/equipment/add', json={'name': 'Gaffer tape', 'barcode': 'TAPE', 'quantity_owned': 10})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def scan(c, event_id, code=None, **kw):
    return c.post('/equipment/checkout/scan', json={'event_id': event_id, 'code': code, **kw})


# ── Tracking modes ───────────────────────────────────────────────────────────

def test_individual_type_creates_its_items_and_counts_them(app, admin, mic):
    eq = db.session.get(Equipment, mic)
    assert eq.is_individual and [u.asset_tag for u in eq.units] == ['MIC-01', 'MIC-02', 'MIC-03']
    assert eq.to_dict()['quantity_owned'] == 3 and eq.to_dict()['tracking'] == 'individual'
    # Retired and lost items are no longer owned
    assert admin.put(f'/equipment/unit/{tag("MIC-03").id}', json={'status': 'retired'}).status_code == 200
    assert db.session.get(Equipment, mic).owned == 2
    # Typing a quantity does nothing for an individual type: the items are the count
    admin.put(f'/equipment/update/{mic}', json={'quantity_owned': 50})
    assert db.session.get(Equipment, mic).owned == 2


def test_bulk_type_has_no_items_and_can_be_converted(app, admin, tape):
    eq = db.session.get(Equipment, tape)
    assert not eq.is_individual and eq.units == [] and eq.owned == 10
    r = admin.put(f'/equipment/update/{tape}', json={'tracking': 'individual', 'quantity_owned': 4})
    assert r.status_code == 200, r.get_json()
    eq = db.session.get(Equipment, tape)
    assert eq.is_individual and len(eq.units) == 4
    # Back to bulk only once the tagged items are gone
    r = admin.put(f'/equipment/update/{tape}', json={'tracking': 'bulk'})
    assert r.status_code == 409 and '4 tagged items' in r.get_json()['error']
    for u in list(eq.units):
        assert admin.delete(f'/equipment/unit/{u.id}').status_code == 200
    assert admin.put(f'/equipment/update/{tape}', json={'tracking': 'bulk', 'quantity_owned': 6}).status_code == 200
    eq = db.session.get(Equipment, tape)
    assert not eq.is_individual and eq.owned == 6


def test_add_rejects_duplicate_barcode_and_bad_tracking(app, admin, mic):
    assert admin.post('/equipment/add', json={'name': 'X', 'barcode': 'mic'}).status_code == 409
    assert admin.post('/equipment/add', json={'name': 'X', 'barcode': 'MIC-01'}).status_code == 409   # an item's tag
    assert admin.post('/equipment/add', json={'name': 'X', 'barcode': 'Y', 'tracking': 'weird'}).status_code == 400
    assert admin.post('/equipment/add', json={'name': '', 'barcode': 'Y'}).status_code == 400


def test_summary_counts(app, admin, alice, mic, tape):
    from routes.equipment import equipment_summaries
    ev = mk_event('Gig')
    assert scan(alice, ev, 'MIC-01').status_code == 200
    assert alice.post(f'/equipment/unit/{tag("MIC-02").id}/quarantine', json={'reason': 'Dented grille'}).status_code == 200
    assert alice.post('/equipment/checkout/bulk', json={'event_id': ev, 'equipment_id': tape, 'quantity': 4}).status_code == 200
    s = equipment_summaries(Equipment.query.all())
    assert s[mic] == {'owned': 3, 'available': 1, 'out': 1, 'quarantined': 1, 'repair': 0}
    assert s[tape] == {'owned': 10, 'available': 6, 'out': 4, 'quarantined': 0, 'repair': 0}
    assert admin.get('/equipment').status_code == 200
    assert admin.get(f'/equipment/{mic}').status_code == 200
    assert admin.get(f'/equipment/{tape}').status_code == 200


# ── Labels ───────────────────────────────────────────────────────────────────

def test_group_and_item_labels(app, admin, mic, tape, monkeypatch):
    import qrcode
    urls = []
    real = qrcode.QRCode.add_data
    monkeypatch.setattr(qrcode.QRCode, 'add_data',
                        lambda self, data, *a, **k: (urls.append(data), real(self, data, *a, **k))[1])
    post = lambda **body: admin.post('/equipment/generate-qrcodes', json={'base_url': 'http://x.test', **body})
    ids = [u.id for u in db.session.get(Equipment, mic).units]

    assert post(equipment_ids=[mic, tape], mode='group').status_code == 200
    assert urls == [f'http://x.test/equipment/{tape}/view', f'http://x.test/equipment/{mic}/view']   # by name

    urls.clear()
    assert post(equipment_ids=[mic], mode='both').status_code == 200
    assert urls == [f'http://x.test/equipment/{mic}/view'] + [f'http://x.test/equipment/unit/{i}/view' for i in ids]

    urls.clear()
    assert post(unit_ids=ids[:2], mode='both').status_code == 200      # only the ticked items, plus their group label
    assert urls == [f'http://x.test/equipment/{mic}/view'] + [f'http://x.test/equipment/unit/{i}/view' for i in ids[:2]]

    assert post(equipment_ids=[tape], mode='unit').status_code == 404  # bulk types have no item labels
    assert post(equipment_ids=[mic], mode='nonsense').status_code == 400
    assert admin.get('/equipment/barcodes').status_code == 302


# ── Scanning a group label at check-out ──────────────────────────────────────

def test_group_label_asks_which_item(app, alice, mic):
    ev = mk_event('Gig')
    r = scan(alice, ev, 'MIC')
    j = r.get_json()
    assert r.status_code == 409 and j['conflict'] == 'choose_unit' and j['equipment']['id'] == mic
    assert [u['asset_tag'] for u in j['units']] == ['MIC-01', 'MIC-02', 'MIC-03']
    r = scan(alice, ev, f'http://x.test/equipment/{mic}/view')          # the QR on the group label
    assert r.get_json()['conflict'] == 'choose_unit'
    r = scan(alice, ev, unit_id=j['units'][1]['id'])
    assert r.status_code == 200 and r.get_json()['action'] == 'out'
    j = scan(alice, ev, 'MIC').get_json()
    assert [u['out_here'] for u in j['units']] == [False, True, False]


def test_bulk_checkout_and_partial_return(app, alice, tape):
    ev = mk_event('Gig')
    j = scan(alice, ev, 'TAPE').get_json()
    assert j['conflict'] == 'choose_quantity' and j['available'] == 10 and j['owned'] == 10

    out = lambda qty, **kw: alice.post('/equipment/checkout/bulk',
                                       json={'event_id': ev, 'equipment_id': tape, 'quantity': qty, **kw})
    assert out(0).status_code == 400
    r = out(6)
    assert r.status_code == 200
    bid = r.get_json()['checkout']['id']
    r = out(5)                                                         # only 4 left in storage
    assert r.status_code == 409 and r.get_json()['needs_confirm'] and r.get_json()['available'] == 4
    assert out(5, force=True).status_code == 200

    state = alice.get(f'/equipment/checkout/event/{ev}').get_json()
    assert sum(b['outstanding'] for b in state['bulk_out']) == 11

    ret = lambda **body: alice.post(f'/equipment/checkout/bulk/{bid}/return', json=body)
    assert ret(quantity=99).status_code == 400
    j = ret(quantity=2).get_json()['checkout']
    assert j['outstanding'] == 4 and j['is_open']
    j = ret(quantity=1, close=True).get_json()['checkout']             # the other 3 were used up
    assert not j['is_open'] and '3 not returned' in j['notes']
    assert ret().status_code == 409


def test_bulk_checkout_refuses_individual_types(app, alice, mic):
    ev = mk_event('Gig')
    r = alice.post('/equipment/checkout/bulk', json={'event_id': ev, 'equipment_id': mic, 'quantity': 1})
    assert r.status_code == 400


# ── Quarantine ───────────────────────────────────────────────────────────────

def test_crew_quarantine_blocks_checkout_and_allocation(app, admin, alice, mic):
    u = tag('MIC-01')
    assert alice.post(f'/equipment/unit/{u.id}/quarantine', json={'reason': ' '}).status_code == 400
    r = alice.post(f'/equipment/unit/{u.id}/quarantine', json={'reason': 'Cuts out when moved'})
    assert r.status_code == 200 and r.get_json()['unit']['status'] == 'quarantined'
    q = UnitQuarantine.query.one()
    assert q.quarantined_by == 'alice' and q.released_at is None
    assert alice.post(f'/equipment/unit/{u.id}/quarantine', json={'reason': 'again'}).status_code == 409

    ev = mk_event('Gig')
    r = scan(alice, ev, 'MIC-01', force=True)                          # no override, even with force
    assert r.status_code == 409 and r.get_json()['conflict'] == 'quarantined'
    assert 'Cuts out when moved' in r.get_json()['error']
    assert UnitCheckout.query.count() == 0

    line = alice.post('/picklist/add', json={'equipment_id': mic, 'quantity': 2, 'event_id': ev}).get_json()['id']
    r = alice.post(f'/picklist/{line}/units', json={'unit_id': u.id, 'force': True})
    assert r.status_code == 409 and r.get_json()['conflict'] == 'quarantined' and not r.get_json()['can_force']

    # It drops out of what's free for an event
    j = alice.post(f'/equipment/{mic}/quantity-check', json={'quantity': 1}).get_json()
    assert j['owned'] == 2

    # The status field can't put it in or out of quarantine
    assert admin.put(f'/equipment/unit/{u.id}', json={'status': 'available'}).status_code == 409
    assert admin.put(f'/equipment/unit/{tag("MIC-02").id}', json={'status': 'quarantined'}).status_code == 400
    r = admin.post(f'/equipment/unit/{u.id}/maintenance',
                   json={'kind': 'repair', 'result': 'repaired', 'set_status': 'available'})
    assert r.status_code == 409


def test_only_admin_releases_and_release_is_logged(app, admin, alice, mic):
    u = tag('MIC-01')
    alice.post(f'/equipment/unit/{u.id}/quarantine', json={'reason': 'Dropped'})
    assert alice.post(f'/equipment/unit/{u.id}/release', json={'note': 'fine'}).status_code == 403
    assert admin.post(f'/equipment/unit/{u.id}/release', json={'outcome': 'available'}).status_code == 400   # no note
    assert admin.post(f'/equipment/unit/{u.id}/release', json={'outcome': 'melted'}).status_code == 400
    r = admin.post(f'/equipment/unit/{u.id}/release',
                   json={'outcome': 'available', 'kind': 'inspection', 'note': 'Tested, no fault found'})
    assert r.status_code == 200, r.get_json()
    assert tag('MIC-01').status == 'available'
    q = UnitQuarantine.query.one()
    assert q.released_by == 'boss' and q.outcome == 'available'
    m = UnitMaintenance.query.one()
    assert m.kind == 'inspection' and m.result == 'pass' and 'Dropped' in m.notes and 'no fault' in m.notes
    assert admin.post(f'/equipment/unit/{u.id}/release', json={'note': 'x'}).status_code == 409   # not quarantined now

    ev = mk_event('Gig')
    assert scan(alice, ev, 'MIC-01').status_code == 200                # usable again


def test_release_can_retire_or_send_for_repair(app, admin, alice, mic):
    a, b = tag('MIC-01'), tag('MIC-02')
    for u in (a, b):
        alice.post(f'/equipment/unit/{u.id}/quarantine', json={'reason': 'Broken'})
    assert admin.post(f'/equipment/unit/{a.id}/release', json={'outcome': 'retired'}).status_code == 200
    assert admin.post(f'/equipment/unit/{b.id}/release', json={'outcome': 'repair', 'note': 'Sent to workshop'}).status_code == 200
    assert tag('MIC-01').status == 'retired' and tag('MIC-02').status == 'repair'
    assert UnitMaintenance.query.count() == 0
    assert db.session.get(Equipment, mic).owned == 2


def test_damaged_return_quarantines(app, alice, mic):
    ev = mk_event('Gig')
    scan(alice, ev, 'MIC-01')
    scan(alice, ev, 'MIC-02')
    assert scan(alice, ev, 'MIC-01', mode='return', damaged=True).status_code == 400    # needs a reason
    r = scan(alice, ev, 'MIC-01', mode='return', damaged=True, reason='Cracked body')
    j = r.get_json()
    assert r.status_code == 200 and j['action'] == 'return' and j['quarantine']['reason'] == 'Cracked body'
    assert tag('MIC-01').status == 'quarantined'
    q = UnitQuarantine.query.one()
    assert q.event_id == ev

    co = UnitCheckout.query.filter_by(unit_id=tag('MIC-02').id).one()
    r = alice.post(f'/equipment/checkout/{co.id}/return', json={'damaged': True, 'reason': 'Bent'})
    assert r.status_code == 200 and tag('MIC-02').status == 'quarantined'


def test_quarantine_photo_upload_and_timeline(app, admin, alice, mic, tmp_path, monkeypatch):
    import routes.unit_tracking as ut
    monkeypatch.setattr(ut, 'QUARANTINE_PICS_FOLDER', str(tmp_path))
    u = tag('MIC-01')
    r = alice.post(f'/equipment/unit/{u.id}/quarantine', content_type='multipart/form-data',
                   data={'reason': 'Screen cracked', 'photo': (io.BytesIO(b'not an image'), 'x.png')})
    assert r.status_code == 400 and tag('MIC-01').status == 'available'
    r = alice.post(f'/equipment/unit/{u.id}/quarantine', content_type='multipart/form-data',
                   data={'reason': 'Screen cracked', 'photo': (io.BytesIO(PNG), 'crack.png')})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['quarantine']['photo_url']
    assert len(os.listdir(tmp_path)) == 1

    admin.post(f'/equipment/unit/{u.id}/release', json={'outcome': 'available', 'kind': 'repair', 'note': 'New screen'})
    h = alice.get(f'/equipment/unit/{u.id}/history').get_json()
    kinds = [t['kind'] for t in h['timeline']]
    assert kinds[-1] == 'created' and set(kinds) >= {'quarantine', 'release', 'maintenance'}
    assert len(h['quarantines']) == 1 and h['quarantines'][0]['outcome_label'] == 'Back in use'


def test_migration_marks_types_with_units_individual(app):
    """Step 2 on an old database: types that already had tagged units become individual."""
    import schema_migrations as sm
    a = Equipment(name='Mic', barcode='A', quantity_owned=2)
    b = Equipment(name='Tape', barcode='B', quantity_owned=5)
    db.session.add_all([a, b]); db.session.flush()
    db.session.add(EquipmentUnit(equipment_id=a.id, asset_tag='A-01'))
    db.session.commit()
    db.session.execute(db.text('UPDATE equipment SET tracking = NULL'))
    db.session.commit()
    with db.engine.begin() as conn:
        sm._m2_equipment_tracking(conn)
    db.session.expire_all()
    assert db.session.get(Equipment, a.id).tracking == 'individual'
    assert db.session.get(Equipment, b.id).tracking == 'bulk'


# ── Top bar search and scan ──────────────────────────────────────────────────

def test_search_and_scan_lookup(app, admin, alice, mic, tape):
    mk_event('Shure showcase')
    groups = {g['label']: g['hits'] for g in alice.get('/api/search?q=shure').get_json()['groups']}
    assert [h['title'] for h in groups['Equipment']] == ['Shure SM58']
    assert [h['title'] for h in groups['Events']] == ['Shure showcase']
    groups = {g['label']: g['hits'] for g in alice.get('/api/search?q=mic-02').get_json()['groups']}
    assert groups['Items'][0]['title'] == 'MIC-02' and '#unit-' in groups['Items'][0]['url']
    assert alice.get('/api/search?q=x').get_json()['groups'] == []

    j = alice.post('/api/scan', json={'code': 'MIC-02'}).get_json()
    assert j['kind'] == 'unit' and j['unit']['asset_tag'] == 'MIC-02' and j['unit']['state'] == 'available'
    j = alice.post('/api/scan', json={'code': 'TAPE'}).get_json()
    assert j['kind'] == 'type' and j['equipment']['summary']['owned'] == 10
    assert alice.post('/api/scan', json={'code': 'NOPE'}).status_code == 404


def test_every_main_page_renders(app, admin, alice, mic, tape):
    ev = mk_event('Gig')
    alice.post(f'/equipment/unit/{tag("MIC-01").id}/quarantine', json={'reason': 'Broken'})
    for c in (admin, alice):
        for url in ('/dashboard', '/equipment', f'/equipment/{mic}', f'/equipment/{tape}', '/picklist',
                    f'/picklist?event_id={ev}', '/equipment/checkout', f'/equipment/checkout?event_id={ev}',
                    '/events', f'/events/{ev}', '/calendar', '/hired-equipment', '/todos', '/settings'):
            r = c.get(url)
            assert r.status_code == 200, (url, r.status_code)


def test_manage_page_is_for_admins(app, admin, alice, mic, tape):
    page = admin.get('/equipment/manage')
    assert page.status_code == 200
    assert b'Manage equipment' in page.data and b'Import CSV' in page.data and b'Print labels' in page.data

    r = alice.get('/equipment/manage')                                   # crew are sent back to the list
    assert r.status_code == 302 and r.headers['Location'].endswith('/equipment')

    # The list is for finding gear: the admin tools are not on it
    listing = admin.get('/equipment').data
    assert b'Import CSV' not in listing and b'/equipment/manage' in listing
    assert b'Import CSV' not in alice.get('/equipment').data

    # The old QR generator link lands on the manage page, ready to print
    assert admin.get('/equipment/barcodes').headers['Location'].endswith('/equipment/manage?labels=1')


# ── Busy-event helpers: undo, opening on today's event, the today card ──────

def test_undo_your_own_scan(app, admin, alice, mic):
    ev = mk_event('Gig')
    cid = scan(alice, ev, 'MIC-01').get_json()['checkout']['id']
    undo = lambda c, i, action: c.post(f'/equipment/checkout/{i}/undo', json={'action': action})

    assert undo(admin, cid, 'out').status_code == 409            # someone else's scan
    assert undo(alice, cid, 'sideways').status_code == 400
    assert undo(alice, cid, 'return').status_code == 409         # it hasn't come back
    assert undo(alice, cid, 'out').status_code == 200            # wrong item: as if it never left
    assert UnitCheckout.query.count() == 0

    cid = scan(alice, ev, 'MIC-01').get_json()['checkout']['id']
    assert scan(alice, ev, 'MIC-01').get_json()['action'] == 'return'
    assert undo(alice, cid, 'return').status_code == 200         # scanned back by mistake: out again
    assert tag('MIC-01').open_checkout.id == cid

    # Too late once ten minutes have passed
    co = db.session.get(UnitCheckout, cid)
    co.checked_out_at = datetime.now() - timedelta(minutes=11)
    db.session.commit()
    assert undo(alice, cid, 'out').status_code == 409


def test_scan_page_opens_on_todays_event(app, admin, alice, mic):
    assert b'no events yet' in alice.get('/equipment/checkout').data
    later = mk_event('Next week', days=7)
    page = alice.get('/equipment/checkout').data.decode()
    assert f'const EVENT_ID = {later};' in page                   # nothing today: the next one coming up

    today = Event(title='Tonight', event_date=datetime.now().replace(hour=23, minute=59))
    db.session.add(today)
    db.session.commit()
    page = alice.get('/equipment/checkout').data.decode()
    assert f'const EVENT_ID = {today.id};' in page and 'Tonight' in page
    assert f'const EVENT_ID = {later};' in alice.get(f'/equipment/checkout?event_id={later}').data.decode()
    assert 'const EVENT_ID = null;' in alice.get('/equipment/checkout?choose=1').data.decode()

    # The dashboard leads with today's event and its three buttons
    dash = alice.get('/dashboard').data.decode()
    assert 'On today' in dash and f'/equipment/checkout?event_id={today.id}' in dash and f'/picklist?event_id={today.id}' in dash
