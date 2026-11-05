"""Shift notes/tasks are crew-only, tasks can only be edited by their owner,
and the pick-list availability check is date-aware.
Run: pytest tests/test_shift_perms_and_availability.py"""
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                    # noqa: E402
from models import (User, Event, Shift, ShiftNote, ShiftTask, Equipment,     # noqa: E402
                    EquipmentUnit, PickListItem)
from tests.test_events import app, admin, alice, client_for                  # noqa: E402,F401


@pytest.fixture()
def shift(app):
    db.session.add(User(username='cassie', is_cast=True, user_role='cast', email='c@x.test'))
    ev = Event(title='Show', event_date=datetime(2026, 12, 1, 18), event_end_date=datetime(2026, 12, 1, 22))
    db.session.add(ev); db.session.flush()
    sh = Shift(event_id=ev.id, title='Bump in', shift_date=ev.event_date,
               shift_end_date=ev.event_end_date, created_by='boss')
    db.session.add(sh); db.session.flush()
    db.session.add(ShiftNote(shift_id=sh.id, created_by='boss', content='secret crew note'))
    db.session.add(ShiftTask(shift_id=sh.id, title='Rig LX', created_by='boss', assigned_to='alice'))
    db.session.add(ShiftTask(shift_id=sh.id, title='Boss only', created_by='boss'))
    db.session.commit()
    return sh.id


def test_cast_cannot_touch_shift_notes_or_tasks(app, shift):
    cast = client_for(app, 'cassie')
    for method, url, body in [
        ('get',    f'/shifts/{shift}/notes', None),
        ('post',   f'/shifts/{shift}/notes', {'content': 'hi'}),
        ('get',    f'/shifts/{shift}/tasks', None),
        ('post',   f'/shifts/{shift}/tasks', {'title': 'x'}),
        ('put',    f'/shifts/tasks/{ShiftTask.query.first().id}', {'title': 'pwned'}),
    ]:
        r = getattr(cast, method)(url, json=body)
        assert r.status_code in (302, 403), (method, url, r.status_code)
        assert b'secret crew note' not in r.data
    assert ShiftNote.query.count() == 1
    assert ShiftTask.query.count() == 2
    assert ShiftTask.query.filter_by(title='pwned').count() == 0


def test_task_edit_rules(app, admin, alice, shift):
    rig  = ShiftTask.query.filter_by(title='Rig LX').first().id
    boss = ShiftTask.query.filter_by(title='Boss only').first().id
    # Assignee may tick off their task, but not rename it.
    assert alice.put(f'/shifts/tasks/{rig}', json={'is_complete': True}).status_code == 200
    assert db.session.get(ShiftTask, rig).is_complete is True
    assert alice.put(f'/shifts/tasks/{rig}', json={'title': 'Renamed'}).status_code == 403
    # Crew who neither created nor are assigned can't edit at all.
    assert alice.put(f'/shifts/tasks/{boss}', json={'is_complete': True}).status_code == 403
    assert db.session.get(ShiftTask, boss).is_complete is False
    # Creator/admin can edit anything; empty titles are rejected.
    assert admin.put(f'/shifts/tasks/{boss}', json={'title': 'Renamed'}).status_code == 200
    assert admin.put(f'/shifts/tasks/{boss}', json={'title': '  '}).status_code == 400
    assert db.session.get(ShiftTask, boss).title == 'Renamed'


def _event(title, start, hours=4, **kw):
    ev = Event(title=title, event_date=start, event_end_date=start + timedelta(hours=hours), **kw)
    db.session.add(ev); db.session.flush()
    return ev


def _check(client, eq_id, qty, event_id=None):
    r = client.post(f'/equipment/{eq_id}/quantity-check', json={'quantity': qty, 'event_id': event_id})
    assert r.status_code == 200, r.data
    return r.get_json()


def test_availability_is_date_aware(app, admin):
    future = datetime.now() + timedelta(days=30)
    eq = Equipment(name='Wash light', barcode='WASH', quantity_owned=4)
    db.session.add(eq); db.session.flush()
    show_a  = _event('Show A', future)
    show_b  = _event('Show B', future + timedelta(hours=2))           # overlaps A
    show_c  = _event('Show C', future + timedelta(days=60))           # months later
    past    = _event('Old show', datetime.now() - timedelta(days=60))
    db.session.add_all([
        PickListItem(item_name='Wash', equipment_id=eq.id, quantity=3, event_id=show_a.id, is_checked=True),
        PickListItem(item_name='Wash', equipment_id=eq.id, quantity=4, event_id=past.id, is_checked=False),
    ])
    db.session.commit()

    # Packed (ticked) gear on an overlapping show still counts as in use.
    r = _check(admin, eq.id, 2, show_b.id)
    assert (r['owned'], r['allocated'], r['available'], r['warning']) == (4, 3, 1, True)
    # A show months later doesn't compete, and the old unticked list is ignored.
    r = _check(admin, eq.id, 4, show_c.id)
    assert (r['allocated'], r['available'], r['warning']) == (0, 4, False)
    # Lines already on the same event count toward that event.
    assert _check(admin, eq.id, 2, show_a.id)['available'] == 1
    # No event: everything on events that haven't finished.
    assert _check(admin, eq.id, 1)['allocated'] == 3


def test_availability_uses_usable_units_and_zero_owned(app, admin):
    eq = Equipment(name='Spot', barcode='SPOT', quantity_owned=10)
    none = Equipment(name='Gone', barcode='GONE', quantity_owned=0)
    db.session.add_all([eq, none]); db.session.flush()
    for i, status in enumerate(['available', 'available', 'repair', 'retired']):
        db.session.add(EquipmentUnit(equipment_id=eq.id, asset_tag=f'SPOT-{i}', status=status))
    db.session.commit()
    assert _check(admin, eq.id, 3)['owned'] == 2          # only usable units count
    r = _check(admin, none.id, 1)
    assert (r['owned'], r['available'], r['warning']) == (0, 0, True)   # 0 owned is not "999"


def test_cast_cannot_query_availability(app, shift):
    eq = Equipment(name='Mic', barcode='MIC', quantity_owned=1)
    db.session.add(eq); db.session.commit()
    r = client_for(app, 'cassie').post(f'/equipment/{eq.id}/quantity-check', json={'quantity': 1})
    assert r.status_code in (302, 403)
