"""Consumables: stock counted by quantity, usage / restock history, shopping list and low-stock alerts.
Run: pytest tests/test_consumables.py"""
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import Consumable, ConsumableMovement, Event                   # noqa: E402
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401  (fixtures)


@pytest.fixture()
def alerts(monkeypatch):
    """Capture low-stock alerts instead of posting to Discord / sending email."""
    sent = []
    from services import notification_service
    monkeypatch.setattr(notification_service, 'send_low_stock_alert',
                        lambda item, by='', url='': sent.append((item.name, item.quantity, by, url)))
    return sent


def add(c, **kw):
    body = {'name': 'Gaffer tape, black', 'category': 'Tape', 'unit': 'rolls',
            'quantity': 10, 'low_threshold': 3, 'location': 'Shelf B2', 'supplier': 'Stage Supplies'}
    body.update(kw)
    r = c.post('/consumables/add', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def mk_event(title='Spring Musical', days=0):
    ev = Event(title=title, event_date=datetime.now() + timedelta(days=days))
    db.session.add(ev)
    db.session.commit()
    return ev.id


# ── Items ────────────────────────────────────────────────────────────────────

def test_admin_adds_edits_deletes_crew_cannot(app, admin, alice):
    assert alice.post('/consumables/add', json={'name': 'AA'}).status_code == 403
    assert admin.post('/consumables/add', json={'name': ''}).status_code == 400
    assert admin.post('/consumables/add', json={'name': 'x', 'low_threshold': 'lots'}).status_code == 400

    cid = add(admin, supplier_url='example.com/tape')
    c = db.session.get(Consumable, cid)
    assert (c.quantity, c.low_threshold, c.unit, c.supplier_url) == (10, 3, 'rolls', 'https://example.com/tape')
    # The starting stock is in the history
    (m,) = c.movements.all()
    assert (m.kind, m.change, m.quantity_after, m.by_username) == ('count', 10, 10, 'boss')

    assert alice.put(f'/consumables/{cid}', json={'name': 'Hacked'}).status_code == 403
    r = admin.put(f'/consumables/{cid}', json={'location': 'LX cupboard', 'reorder_qty': 6})
    assert r.status_code == 200 and r.get_json()['item']['location'] == 'LX cupboard'
    assert db.session.get(Consumable, cid).name == 'Gaffer tape, black'      # partial update keeps the rest

    assert alice.delete(f'/consumables/{cid}').status_code == 403
    assert admin.delete(f'/consumables/{cid}').status_code == 200
    assert Consumable.query.count() == 0 and ConsumableMovement.query.count() == 0


def test_pages_render(app, admin, alice):
    cid = add(admin)
    for c in (admin, alice):
        assert c.get('/consumables').status_code == 200
        assert c.get('/consumables/shopping-list').status_code == 200
        page = c.get(f'/consumables/{cid}')
        assert page.status_code == 200 and b'Gaffer tape, black' in page.data
    assert admin.get('/consumables/labels').status_code == 200
    r = admin.get(f'/consumables/labels?ids={cid}')
    assert r.status_code == 200 and b'data:image/png;base64,' in r.data
    assert admin.get(f'/consumables/{cid}/json').get_json()['item']['quantity'] == 10


def test_empty_list_page(app, alice):
    r = alice.get('/consumables')
    assert r.status_code == 200 and b'No consumables yet' in r.data
    assert alice.get('/consumables/labels').status_code == 404


# ── Use / restock ────────────────────────────────────────────────────────────

def test_use_and_restock_with_history(app, admin, alice, alerts):
    cid = add(admin)
    ev = mk_event()
    r = alice.post(f'/consumables/{cid}/use', json={'amount': 2, 'event_id': ev, 'note': 'marking out'})
    assert r.status_code == 200 and r.get_json()['item']['quantity'] == 8
    r = alice.post(f'/consumables/{cid}/restock', json={'amount': 5})
    assert r.get_json()['item']['quantity'] == 13

    hist = alice.get(f'/consumables/{cid}/json').get_json()['history']
    assert [(h['kind'], h['change'], h['quantity_after']) for h in hist] == [
        ('restock', 5, 13), ('use', -2, 8), ('count', 10, 10)]
    assert hist[1]['event_title'] == 'Spring Musical' and hist[1]['by'] == 'alice' and hist[1]['note'] == 'marking out'
    assert alerts == []


def test_use_validation(app, admin, alice):
    cid = add(admin, quantity=2)
    assert alice.post(f'/consumables/{cid}/use', json={'amount': 0}).status_code == 400
    assert alice.post(f'/consumables/{cid}/use', json={'amount': 'two'}).status_code == 400
    assert alice.post(f'/consumables/{cid}/restock', json={}).status_code == 400
    r = alice.post(f'/consumables/{cid}/use', json={'amount': 3})
    assert r.status_code == 409 and 'Only 2' in r.get_json()['error']
    assert alice.post(f'/consumables/{cid}/use', json={'amount': 1, 'event_id': 9999}).status_code == 404
    assert alice.post('/consumables/9999/use', json={'amount': 1}).status_code == 404
    assert db.session.get(Consumable, cid).quantity == 2


def test_default_amount_is_one(app, admin, alice):
    cid = add(admin)
    assert alice.post(f'/consumables/{cid}/use', json={}).get_json()['item']['quantity'] == 9


def test_stock_count_admin_only(app, admin, alice, alerts):
    cid = add(admin)
    assert alice.post(f'/consumables/{cid}/count', json={'quantity': 4}).status_code == 403
    assert admin.post(f'/consumables/{cid}/count', json={'quantity': -1}).status_code == 400
    r = admin.post(f'/consumables/{cid}/count', json={'quantity': 7})
    assert r.get_json()['item']['quantity'] == 7 and r.get_json()['movement']['change'] == -3


def test_undo_own_latest_change(app, admin, alice):
    cid = add(admin)
    m1 = alice.post(f'/consumables/{cid}/use', json={'amount': 4}).get_json()['movement']['id']
    bob = client_for(app, 'bob')
    assert bob.post(f'/consumables/movement/{m1}/undo').status_code == 403      # not bob's
    r = alice.post(f'/consumables/movement/{m1}/undo')
    assert r.status_code == 200 and r.get_json()['item']['quantity'] == 10
    assert db.session.get(ConsumableMovement, m1) is None

    m2 = alice.post(f'/consumables/{cid}/use', json={'amount': 1}).get_json()['movement']['id']
    bob.post(f'/consumables/{cid}/restock', json={'amount': 1})
    assert alice.post(f'/consumables/movement/{m2}/undo').status_code == 409     # not the latest any more

    m3 = alice.post(f'/consumables/{cid}/use', json={'amount': 1}).get_json()['movement']['id']
    mv = db.session.get(ConsumableMovement, m3)
    mv.created_at = datetime.utcnow() - timedelta(minutes=30)
    db.session.commit()
    assert alice.post(f'/consumables/movement/{m3}/undo').status_code == 409     # too late
    assert admin.post(f'/consumables/movement/{m3}/undo').status_code == 200     # admins can still fix it


# ── Low stock: alerts, shopping list, dashboard ──────────────────────────────

def test_alert_only_when_crossing_threshold(app, admin, alice, alerts):
    cid = add(admin, quantity=5, low_threshold=3)
    alice.post(f'/consumables/{cid}/use', json={'amount': 1})                    # 4: fine
    assert alerts == []
    alice.post(f'/consumables/{cid}/use', json={'amount': 1})                    # 3: crosses
    assert len(alerts) == 1
    name, qty, by, url = alerts[0]
    assert (name, qty, by) == ('Gaffer tape, black', 3, 'alice') and url.endswith(f'/consumables/{cid}')
    alice.post(f'/consumables/{cid}/use', json={'amount': 2})                    # still low: no repeat
    assert len(alerts) == 1
    alice.post(f'/consumables/{cid}/restock', json={'amount': 10})               # back above
    alice.post(f'/consumables/{cid}/use', json={'amount': 9})                    # crosses again
    assert len(alerts) == 2


def test_new_item_below_level_and_zero_threshold_do_not_alert(app, admin, alice, alerts):
    add(admin, name='AA batteries', quantity=1, low_threshold=4)                 # created low: no alert
    cid = add(admin, name='Cable ties', quantity=2, low_threshold=0)
    alice.post(f'/consumables/{cid}/use', json={'amount': 2})                    # 0, but no level set
    assert alerts == []
    assert db.session.get(Consumable, cid).is_low is False


def test_raising_threshold_above_stock_alerts(app, admin, alerts):
    cid = add(admin, quantity=5, low_threshold=2)
    admin.put(f'/consumables/{cid}', json={'low_threshold': 6})
    assert len(alerts) == 1


def test_shopping_list(app, admin, alice, alerts):
    add(admin, name='Gel L201', quantity=1, low_threshold=2, supplier='Rosco', reorder_qty=10)
    add(admin, name='9V batteries', quantity=1, low_threshold=4, supplier='')
    add(admin, name='Gaffer tape', quantity=20, low_threshold=3)
    page = alice.get('/consumables/shopping-list').get_data(as_text=True)
    assert 'Gel L201' in page and '9V batteries' in page and 'Gaffer tape' not in page
    assert 'Rosco' in page and 'No supplier set' in page
    assert '<strong>10</strong>' in page          # reorder amount
    assert '<strong>7</strong>' in page           # 9V: back to twice the level (8) minus 1 on hand

    from routes.consumables import low_stock_items
    assert [c.name for c in low_stock_items()] == ['9V batteries', 'Gel L201']    # emptiest first


def test_low_stock_on_dashboard_and_gear_attention(app, admin, alice):
    add(admin, name='Gel L201', quantity=1, low_threshold=2)
    dash = admin.get('/dashboard').get_data(as_text=True)
    assert '1 consumable running low' in dash and 'Gel L201' in dash
    assert 'consumable running low' not in alice.get('/dashboard').get_data(as_text=True)   # admins only
    manage = admin.get('/equipment/manage').get_data(as_text=True)
    assert '1 consumable low' in manage and 'Gel L201' in manage


def test_send_low_stock_alert_emails_admins(app, monkeypatch):
    from services import notification_service, email_service
    sent = []
    monkeypatch.setattr(email_service, 'send_email', lambda subject, to, body: sent.append((subject, to)) or True)
    monkeypatch.setattr(notification_service, 'DISCORD_WEBHOOK_URL', '')
    c = Consumable(name='AA batteries', unit='each', quantity=2, low_threshold=4)
    db.session.add(c)
    db.session.commit()
    out = notification_service.send_low_stock_alert(c, by='Alice', url='http://x/consumables/1')
    assert out == {'discord': False, 'emailed': 1}
    assert sent == [('Low stock: AA batteries', 'boss@x.test')]


# ── Per-event usage ──────────────────────────────────────────────────────────

def test_event_usage(app, admin, alice):
    tape = add(admin)
    aa = add(admin, name='AA batteries', unit='each', quantity=40, low_threshold=8)
    ev = mk_event('Gig')
    other = mk_event('Other show')
    alice.post(f'/consumables/{tape}/use', json={'amount': 3, 'event_id': ev})
    alice.post(f'/consumables/{aa}/use', json={'amount': 12, 'event_id': ev})
    alice.post(f'/consumables/{aa}/restock', json={'amount': 4, 'event_id': ev, 'note': 'unused spares'})
    alice.post(f'/consumables/{aa}/use', json={'amount': 1, 'event_id': other})

    moves = alice.get(f'/consumables/event/{ev}/json').get_json()['movements']
    assert sorted((m['name'], m['change']) for m in moves) == [
        ('AA batteries', -12), ('AA batteries', 4), ('Gaffer tape, black', -3)]
    page = alice.get(f'/consumables/event/{ev}').get_data(as_text=True)
    assert 'AA batteries' in page and '<strong>8</strong>' in page and 'unused spares' in page

    # Deleting the event keeps the history, with the title it had
    admin.delete(f'/events/{ev}')
    db.session.expire_all()
    m = ConsumableMovement.query.filter_by(change=-12).one()
    assert m.event_title == 'Gig' and m.event_id is None
    assert alice.get(f'/consumables/{aa}').status_code == 200
