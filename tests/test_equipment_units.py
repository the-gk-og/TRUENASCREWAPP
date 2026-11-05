"""Per-unit equipment tracking: units, unit QR tags, scanner lookup, pick list allocation.
Run: pytest tests/test_equipment_units.py"""
import os, sys
from datetime import datetime, timedelta

import pytest
from reportlab.pdfgen.canvas import Canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                          # noqa: E402
from models import Equipment, EquipmentUnit, Event, PickListItem, PickListUnit  # noqa: E402
from tests.test_events import app, admin, alice, client_for        # noqa: E402,F401  (fixtures)

MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


@pytest.fixture()
def mic(app):
    e = Equipment(name='Shure SM58', barcode='MIC', quantity_owned=3)
    db.session.add(e)
    db.session.commit()
    return e.id


def add_units(c, eq_id, **body):
    r = c.post(f'/equipment/{eq_id}/units', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def mk_event(title, days):
    ev = Event(title=title, event_date=datetime.now() + timedelta(days=days))
    db.session.add(ev)
    db.session.commit()
    return ev.id


def mk_line(c, eq_id, event_id, qty=2):
    r = c.post('/picklist/add', json={'equipment_id': eq_id, 'quantity': qty, 'event_id': event_id})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


# ── Creating and managing units ──────────────────────────────────────────────

def test_generate_and_add_units(app, admin, mic):
    made = add_units(admin, mic, count=3)['units']
    assert [u['asset_tag'] for u in made] == ['MIC-01', 'MIC-02', 'MIC-03']

    one = add_units(admin, mic, asset_tag='MIC-SPARE', serial_number='SN123')['unit']
    assert one['serial_number'] == 'SN123' and one['status'] == 'available'
    # Owning 4 units means owning at least 4
    assert db.session.get(Equipment, mic).quantity_owned == 4

    # Generated tags skip ones already in use
    assert add_units(admin, mic, count=1)['units'][0]['asset_tag'] == 'MIC-04'

    units = admin.get(f'/equipment/{mic}/units').get_json()['units']
    assert len(units) == 5 and all(not u['is_out'] for u in units)
    assert admin.get(f'/equipment/{mic}').status_code == 200        # detail page renders units


def test_asset_tags_are_unique_across_units_and_items(app, admin, mic):
    db.session.add(Equipment(name='DI box', barcode='DI-1'))
    db.session.commit()
    add_units(admin, mic, asset_tag='MIC-A')
    assert admin.post(f'/equipment/{mic}/units', json={'asset_tag': 'mic-a'}).status_code == 409
    assert admin.post(f'/equipment/{mic}/units', json={'asset_tag': 'DI-1'}).status_code == 409   # an item barcode
    assert admin.post(f'/equipment/{mic}/units', json={'asset_tag': '  '}).status_code == 400
    assert admin.post(f'/equipment/{mic}/units', json={'count': 0}).status_code == 400


def test_edit_and_remove_unit(app, admin, alice, mic):
    uid = add_units(admin, mic, asset_tag='MIC-A')['unit']['id']
    assert alice.put(f'/equipment/unit/{uid}', json={'status': 'repair'}).status_code == 403
    assert alice.post(f'/equipment/{mic}/units', json={'count': 1}).status_code == 403
    assert admin.put(f'/equipment/unit/{uid}', json={'status': 'broken'}).status_code == 400
    r = admin.put(f'/equipment/unit/{uid}', json={'status': 'repair', 'notes': 'Grille dented'})
    assert r.status_code == 200 and r.get_json()['unit']['status'] == 'repair'
    assert alice.delete(f'/equipment/unit/{uid}').status_code == 403
    assert admin.delete(f'/equipment/unit/{uid}').status_code == 200
    assert db.session.get(EquipmentUnit, uid) is None


def test_deleting_item_removes_its_units(app, admin, mic):
    add_units(admin, mic, count=2)
    assert admin.delete(f'/equipment/delete/{mic}').status_code == 200
    assert EquipmentUnit.query.count() == 0


# ── Unit QR tags and scanning ────────────────────────────────────────────────

def _spy_qr(monkeypatch):
    """Record every URL put into a QR code and every string drawn on the PDF."""
    import qrcode
    urls, drawn = [], []
    orig_add = qrcode.QRCode.add_data
    monkeypatch.setattr(qrcode.QRCode, 'add_data',
                        lambda self, d, *a, **k: (urls.append(d), orig_add(self, d, *a, **k))[1])
    orig_draw = Canvas.drawString
    monkeypatch.setattr(Canvas, 'drawString',
                        lambda self, x, y, t, *a, **k: (drawn.append(t), orig_draw(self, x, y, t, *a, **k))[1])
    return urls, drawn


@pytest.mark.parametrize('layout', ['portrait', 'landscape'])
def test_unit_tags_encode_unit_urls_and_print_asset_tags(app, admin, mic, monkeypatch, layout):
    units = add_units(admin, mic, count=2)['units']
    urls, drawn = _spy_qr(monkeypatch)
    r = admin.post('/equipment/generate-qrcodes', json={
        'equipment_ids': [mic], 'mode': 'unit', 'layout': layout, 'base_url': 'http://x.test'})
    assert r.status_code == 200, r.get_json()
    assert r.data[:4] == b'%PDF'
    assert urls == [f'http://x.test/equipment/unit/{u["id"]}/view' for u in units]
    text = ' '.join(drawn)
    assert '# MIC-01' in text and '# MIC-02' in text and 'Shure SM58' in text


def test_unit_tags_for_chosen_units_only(app, admin, mic, monkeypatch):
    units = add_units(admin, mic, count=3)['units']
    urls, _ = _spy_qr(monkeypatch)
    r = admin.post('/equipment/generate-qrcodes', json={
        'unit_ids': [units[1]['id']], 'mode': 'unit', 'base_url': 'http://x.test'})
    assert r.status_code == 200
    assert urls == [f'http://x.test/equipment/unit/{units[1]["id"]}/view']


def test_item_mode_unchanged_and_unit_mode_needs_units(app, admin, mic, monkeypatch):
    urls, _ = _spy_qr(monkeypatch)
    assert admin.post('/equipment/generate-qrcodes', json={
        'equipment_ids': [mic], 'base_url': 'http://x.test'}).status_code == 200
    assert urls == [f'http://x.test/equipment/{mic}/view']
    r = admin.post('/equipment/generate-qrcodes', json={'equipment_ids': [mic], 'mode': 'unit'})
    assert r.status_code == 404 and 'no units' in r.get_json()['error']


def test_scanning_unit_qr_and_asset_tag(app, admin, alice, mic):
    uid = add_units(admin, mic, asset_tag='MIC-07', serial_number='SN7')['unit']['id']

    # QR URL → JSON used by the in-app scanner
    hit = alice.get(f'/equipment/unit/{uid}/json').get_json()
    assert hit['id'] == mic and hit['name'] == 'Shure SM58'
    assert hit['unit']['asset_tag'] == 'MIC-07' and hit['unit']['serial_number'] == 'SN7'

    # Typed / laser-scanned asset tag through the existing barcode lookup (case-insensitive)
    for code in ('MIC-07', 'mic-07'):
        hit = alice.get(f'/equipment/barcode/{code}').get_json()
        assert hit['id'] == mic and hit['unit']['id'] == uid
    assert alice.get('/equipment/unit/tag/MIC-07').get_json()['unit']['id'] == uid
    # The item's own barcode still resolves to the item, without a unit
    assert 'unit' not in alice.get('/equipment/barcode/MIC').get_json()
    assert alice.get('/equipment/barcode/NOPE').status_code == 404

    # Phone camera opening the QR URL: crew go to the item page focused on the unit
    r = alice.get(f'/equipment/unit/{uid}/view')
    assert r.status_code == 302
    assert r.headers['Location'].endswith(f'/equipment/{mic}?unit={uid}#unit-{uid}')
    page = alice.get(f'/equipment/{mic}?unit={uid}').get_data(as_text=True)
    assert 'id="unit-%d" class="unit-highlight"' % uid in page

    # …and someone not signed in sees the public page naming the unit
    anon = app.test_client()
    page = anon.get(f'/equipment/unit/{uid}/view').get_data(as_text=True)
    assert 'MIC-07' in page and 'SN7' in page


# ── Pick lists: which unit is where ──────────────────────────────────────────

def test_allocate_units_to_pick_list(app, admin, alice, mic):
    u1, u2, u3 = add_units(admin, mic, count=3)['units']
    show = mk_event('Spring Musical', 5)
    line = mk_line(alice, mic, show, qty=2)

    r = alice.post(f'/picklist/{line}/units', json={'unit_id': u1['id']})
    assert r.status_code == 200, r.get_json()
    r = alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-02'})   # by scanned tag
    assert [u['asset_tag'] for u in r.get_json()['units']] == ['MIC-01', 'MIC-02']

    # The line is for 2, and a unit can't be added twice
    assert alice.post(f'/picklist/{line}/units', json={'unit_id': u3['id']}).status_code == 400
    assert alice.post(f'/picklist/{line}/units', json={'unit_id': u1['id']}).status_code == 409

    # Each unit knows where it is
    units = {u['asset_tag']: u for u in alice.get(f'/equipment/{mic}/units').get_json()['units']}
    assert units['MIC-01']['is_out'] and units['MIC-01']['allocations'][0]['event_title'] == 'Spring Musical'
    assert not units['MIC-03']['is_out']
    scan = alice.get(f'/equipment/unit/{u1["id"]}/json').get_json()['unit']
    assert scan['allocations'][0]['event_id'] == show

    # The pick list page and its live-sync poll show the specific units
    page = alice.get(f'/picklist?event_id={show}').get_data(as_text=True)
    assert 'MIC-01' in page and 'MIC-02' in page and f'id="plu-{line}"' in page
    mobile = alice.get(f'/picklist?event_id={show}', headers={'User-Agent': MOBILE_UA}).get_data(as_text=True)
    assert 'mp-list' in mobile and f'id="plu-{line}"' in mobile and 'MIC-02' in mobile
    state = alice.get(f'/picklist/state?event_id={show}').get_json()['items']
    assert [u['asset_tag'] for u in state[0]['units']] == ['MIC-01', 'MIC-02']

    # Packing the line shows on the unit; removing the unit frees it
    alice.post(f'/picklist/toggle/{line}', json={'checked': True})
    assert alice.get(f'/equipment/unit/{u1["id"]}/json').get_json()['unit']['allocations'][0]['is_checked']
    r = alice.delete(f'/picklist/{line}/units/{u1["id"]}')
    assert [u['asset_tag'] for u in r.get_json()['units']] == ['MIC-02']
    assert not alice.get(f'/equipment/unit/{u1["id"]}/json').get_json()['unit']['is_out']


def test_unit_clashes_and_wrong_item(app, admin, alice, mic):
    u1, u2 = add_units(admin, mic, count=2)['units']
    cable = Equipment(name='XLR cable', barcode='XLR')
    db.session.add(cable)
    db.session.commit()
    a, b = mk_event('Show A', 3), mk_event('Show B', 4)
    la, lb = mk_line(alice, mic, a), mk_line(alice, mic, b)
    lc = mk_line(alice, cable.id, a)

    alice.post(f'/picklist/{la}/units', json={'unit_id': u1['id']})
    # Same unit on another current show needs confirmation
    r = alice.post(f'/picklist/{lb}/units', json={'unit_id': u1['id']})
    assert r.status_code == 409 and r.get_json()['conflict'] == 'allocated' and 'Show A' in r.get_json()['error']
    assert alice.post(f'/picklist/{lb}/units', json={'unit_id': u1['id'], 'force': True}).status_code == 200

    # A mic unit can't go on a cable line; units in repair need confirming, retired never
    assert alice.post(f'/picklist/{lc}/units', json={'unit_id': u2['id']}).status_code == 400
    admin.put(f'/equipment/unit/{u2["id"]}', json={'status': 'repair'})
    r = alice.post(f'/picklist/{lb}/units', json={'unit_id': u2['id']})
    assert r.status_code == 409 and r.get_json()['can_force']
    admin.put(f'/equipment/unit/{u2["id"]}', json={'status': 'retired'})
    assert alice.post(f'/picklist/{lb}/units', json={'unit_id': u2['id'], 'force': True}).status_code == 409


def test_finished_events_no_longer_hold_units(app, admin, alice, mic):
    (u1,) = add_units(admin, mic, count=1)['units']
    old = mk_event('Last Week', -7)
    line = mk_line(alice, mic, old)
    assert alice.post(f'/picklist/{line}/units', json={'unit_id': u1['id']}).status_code == 200
    unit = alice.get(f'/equipment/unit/{u1["id"]}/json').get_json()['unit']
    assert not unit['is_out']                     # archived show: unit is back in storage
    new = mk_line(alice, mic, mk_event('Next Week', 7))
    assert alice.post(f'/picklist/{new}/units', json={'unit_id': u1['id']}).status_code == 200


def test_deleting_line_or_unit_cleans_up_allocations(app, admin, alice, mic):
    u1, u2 = add_units(admin, mic, count=2)['units']
    line = mk_line(alice, mic, mk_event('Gig', 2))
    alice.post(f'/picklist/{line}/units', json={'unit_id': u1['id']})
    alice.post(f'/picklist/{line}/units', json={'unit_id': u2['id']})
    admin.delete(f'/equipment/unit/{u2["id"]}')
    assert PickListUnit.query.count() == 1
    alice.delete(f'/picklist/delete/{line}')
    assert PickListUnit.query.count() == 0
    assert db.session.get(EquipmentUnit, u1['id']) is not None
