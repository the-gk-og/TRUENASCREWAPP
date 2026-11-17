"""Shift swaps: offer → claim → admin approves.  Run: pytest tests/test_shift_swaps.py"""
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                     # noqa: E402
from models import (User, Event, Shift, ShiftAssignment, ShiftSwap,          # noqa: E402
                    CrewAssignment, UserUnavailability)
from services import shift_swaps                                             # noqa: E402
from services.shift_reminders import due_reminders                           # noqa: E402
from tests.test_events import app, admin, alice, client_for, uid             # noqa: E402,F401


@pytest.fixture()
def bob(app): return client_for(app, 'bob')


@pytest.fixture()
def sent(monkeypatch):
    """Capture emails instead of sending them."""
    out = []
    import services.email_service as es
    monkeypatch.setattr(es, 'send_html_email', lambda subject, to, html, text=None: out.append((subject, to)) or True)
    return out


def _shift(owner='alice', start=None, hours=4, title='Show'):
    start = start or datetime.now() + timedelta(days=3)
    ev = Event(title=title, event_date=start, event_end_date=start + timedelta(hours=hours), created_by='boss')
    db.session.add(ev); db.session.flush()
    sh = Shift(event_id=ev.id, title='LX', role='LX', shift_date=start,
               shift_end_date=start + timedelta(hours=hours), created_by='boss', is_open=False)
    db.session.add(sh); db.session.flush()
    a = ShiftAssignment(shift_id=sh.id, user_id=uid(owner), status='accepted',
                        reminder_sent_at=datetime.now())
    db.session.add(a)
    db.session.add(CrewAssignment(event_id=ev.id, crew_member=owner, role='LX'))
    db.session.commit()
    return a.id


def _offer(client, aid, **body):
    r = client.post(f'/shifts/assignment/{aid}/swap', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['swap']['id']


def test_offer_claim_approve_moves_shift(app, admin, alice, bob, sent):
    aid = _shift()
    assert b'Offer swap' in alice.get('/crew/my-schedule').data
    sid = _offer(alice, aid, note='exam')
    assert b'Offered for swap' in alice.get('/crew/my-schedule').data
    # Bob sees it and claims it
    assert [s['id'] for s in bob.get('/api/shifts/swaps').get_json()['open']] == [sid]
    assert alice.get('/api/shifts/swaps').get_json()['open'] == []          # not your own
    assert b'Shifts up for grabs' in bob.get('/crew/my-schedule').data
    assert bob.post(f'/shifts/swaps/{sid}/claim').status_code == 200
    assert db.session.get(ShiftSwap, sid).status == 'claimed'
    assert ('Shift swap to approve: bob', 'boss@x.test') in sent
    # Only an admin can approve
    assert bob.post(f'/shifts/swaps/{sid}/approve').status_code == 403
    assert alice.post(f'/shifts/swaps/{sid}/approve').status_code == 403
    assert [s['id'] for s in admin.get('/api/shifts/swaps').get_json()['to_approve']] == [sid]
    assert b'Swaps to approve' in admin.get('/crew/my-schedule').data
    sent.clear()
    assert admin.post(f'/shifts/swaps/{sid}/approve').status_code == 200

    a = db.session.get(ShiftAssignment, aid)
    assert a.user_id == uid('bob') and a.status == 'accepted'
    assert a.reminder_sent_at is None                                      # reminder follows bob
    assert [x.user.username for x, _ in due_reminders(a.shift.shift_date - timedelta(hours=1))] == ['bob']
    ev_id = a.shift.event_id
    assert CrewAssignment.query.filter_by(event_id=ev_id, crew_member='bob').count() == 1
    assert CrewAssignment.query.filter_by(event_id=ev_id, crew_member='alice').count() == 0
    assert sorted(to for _, to in sent) == ['alice@x.test', 'bob@x.test']
    assert db.session.get(ShiftSwap, sid).status == 'approved'


def test_reject_keeps_shift_and_notifies(app, admin, alice, bob, sent):
    aid = _shift()
    sid = _offer(alice, aid)
    bob.post(f'/shifts/swaps/{sid}/claim')
    sent.clear()
    assert admin.post(f'/shifts/swaps/{sid}/reject').status_code == 200
    assert db.session.get(ShiftAssignment, aid).user_id == uid('alice')
    assert db.session.get(ShiftSwap, sid).status == 'rejected'
    assert sorted(to for _, to in sent) == ['alice@x.test', 'bob@x.test']
    # It's closed: can't approve or claim now, and a new offer is allowed
    assert admin.post(f'/shifts/swaps/{sid}/approve').status_code == 409
    _offer(alice, aid)


def test_offer_rules(app, alice, bob):
    aid = _shift()
    assert bob.post(f'/shifts/assignment/{aid}/swap', json={}).status_code == 403   # not bob's shift
    _offer(alice, aid)
    assert alice.post(f'/shifts/assignment/{aid}/swap', json={}).status_code == 400  # already up for swap
    past = _shift(start=datetime.now() - timedelta(hours=1))
    assert alice.post(f'/shifts/assignment/{past}/swap', json={}).status_code == 400
    db.session.add(User(username='cassie', is_cast=True, user_role='cast'))
    db.session.commit()
    other = _shift(title='Other')
    r = alice.post(f'/shifts/assignment/{other}/swap', json={'to_user_ids': [uid('cassie')]})
    assert r.status_code == 400                                             # cast can't take crew shifts
    cast = client_for(app, 'cassie')
    assert cast.get('/api/shifts/swaps').status_code in (302, 403)


def test_offer_to_specific_people(app, admin, alice, bob, sent):
    db.session.add(User(username='carl', user_role='crew', email='carl@x.test'))
    db.session.commit()
    aid = _shift()
    sid = _offer(alice, aid, to_user_ids=[uid('carl')])
    assert sent == [('Shift offered to you by alice', 'carl@x.test')]
    assert bob.get('/api/shifts/swaps').get_json()['open'] == []
    assert bob.post(f'/shifts/swaps/{sid}/claim').status_code == 400
    carl = client_for(app, 'carl')
    assert [s['id'] for s in carl.get('/api/shifts/swaps').get_json()['open']] == [sid]
    assert carl.post(f'/shifts/swaps/{sid}/claim').status_code == 200


def test_claim_checks_clashes_and_availability(app, alice, bob):
    start = datetime.now() + timedelta(days=5)
    aid = _shift(start=start)
    sid = _offer(alice, aid)
    _shift(owner='bob', start=start + timedelta(hours=1), title='Other show')   # bob is busy
    r = bob.post(f'/shifts/swaps/{sid}/claim')
    assert r.status_code == 409 and r.get_json()['conflicts'][0]['type'] == 'shift'

    aid2 = _shift(start=start + timedelta(days=2), title='Later')
    sid2 = _offer(alice, aid2)
    db.session.add(UserUnavailability(user_id=uid('bob'), title='Holiday',
                                      start_date=start + timedelta(days=1), end_date=start + timedelta(days=4)))
    db.session.commit()
    r = bob.post(f'/shifts/swaps/{sid2}/claim')
    assert r.status_code == 409 and r.get_json()['conflicts'][0]['type'] == 'unavailable'
    assert db.session.get(ShiftSwap, sid2).status == 'open'


def test_approve_rechecks_clash_and_force(app, admin, alice, bob):
    start = datetime.now() + timedelta(days=5)
    aid = _shift(start=start)
    sid = _offer(alice, aid)
    assert bob.post(f'/shifts/swaps/{sid}/claim').status_code == 200
    _shift(owner='bob', start=start, title='Booked since')                 # bob got busy after claiming
    assert admin.post(f'/shifts/swaps/{sid}/approve').status_code == 409
    assert admin.post(f'/shifts/swaps/{sid}/approve', json={'force': True}).status_code == 200
    assert db.session.get(ShiftAssignment, aid).user_id == uid('bob')


def test_withdraw_and_cancel(app, admin, alice, bob):
    aid = _shift()
    sid = _offer(alice, aid)
    assert alice.post(f'/shifts/swaps/{sid}/withdraw').status_code == 403
    bob.post(f'/shifts/swaps/{sid}/claim')
    assert bob.post(f'/shifts/swaps/{sid}/withdraw').status_code == 200
    assert db.session.get(ShiftSwap, sid).status == 'open'
    assert bob.post(f'/shifts/swaps/{sid}/cancel').status_code == 403     # not bob's offer
    assert alice.post(f'/shifts/swaps/{sid}/cancel').status_code == 200
    assert db.session.get(ShiftSwap, sid).status == 'cancelled'
    assert bob.post(f'/shifts/swaps/{sid}/claim').status_code == 409


def test_offers_expire_when_shift_starts(app, admin, alice, bob):
    start = datetime.now() + timedelta(days=1)
    aid = _shift(start=start)
    sid = _offer(alice, aid)
    bob.post(f'/shifts/swaps/{sid}/claim')
    assert shift_swaps.expire_started(start - timedelta(minutes=1)) == 0
    assert shift_swaps.expire_started(start) == 1
    assert db.session.get(ShiftSwap, sid).status == 'expired'
    assert admin.post(f'/shifts/swaps/{sid}/approve').status_code == 409
    assert db.session.get(ShiftAssignment, aid).user_id == uid('alice')


def test_removing_person_drops_their_swaps(app, admin, alice):
    aid = _shift()
    sid = _offer(alice, aid)
    ev_id = db.session.get(ShiftAssignment, aid).shift.event_id
    assert admin.delete(f'/events/{ev_id}/team/{uid("alice")}').status_code == 200
    assert db.session.get(ShiftSwap, sid) is None
