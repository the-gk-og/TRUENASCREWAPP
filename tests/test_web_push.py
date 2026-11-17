"""Web Push: opt-in per device, per-person kinds, delivery paths and dead-subscription cleanup.
The network sender (push_service._webpush) is always replaced, so nothing leaves the machine."""

import json, os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from extensions import db                                                   # noqa: E402
from models import PushSubscription, ShiftAssignment                        # noqa: E402
from services import push_service                                           # noqa: E402
from services.shift_reminders import send_due_shift_reminders               # noqa: E402
from tests.test_events import app, admin, alice, client_for, uid, mk        # noqa: E402,F401  (fixtures)


class _Resp:
    def __init__(self, code): self.status_code = code


class _Gone(Exception):
    def __init__(self, code): super().__init__(f'push failed {code}'); self.response = _Resp(code)


@pytest.fixture()
def pushes(monkeypatch):
    """Every push 'sent', as (endpoint, payload dict). Endpoints containing 'gone'/'dead' fail."""
    sent = []

    def fake(info, data, key, claims):
        assert key and claims['sub']
        if 'gone' in info['endpoint']:
            raise _Gone(410)
        if 'dead' in info['endpoint']:
            raise _Gone(404)
        if 'flaky' in info['endpoint']:
            raise _Gone(500)
        sent.append((info['endpoint'], json.loads(data)))
    monkeypatch.setattr(push_service, '_webpush', fake)
    monkeypatch.setattr(push_service, '_keys', None)
    return sent


def subscribe(client, endpoint='https://push.example.test/alice-phone'):
    r = client.post('/push/subscribe', json={'subscription': {'endpoint': endpoint,
                                                              'keys': {'p256dh': 'BPk' * 20, 'auth': 'abc123'}}})
    assert r.status_code == 200, r.get_json()


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M')


def test_vapid_keys_generated_once_and_env_wins(app, monkeypatch):
    monkeypatch.setattr(push_service, '_keys', None)
    monkeypatch.delenv('VAPID_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('VAPID_PRIVATE_KEY', raising=False)
    pub, priv, sub = push_service.vapid_keys()
    assert len(pub) == 87 and len(priv) == 43 and sub.startswith('mailto:')      # 65-byte point, 32-byte key
    monkeypatch.setattr(push_service, '_keys', None)
    assert push_service.vapid_keys()[:2] == (pub, priv)                          # kept in the database
    from py_vapid import Vapid
    Vapid.from_string(priv)                                                      # pywebpush can load it
    monkeypatch.setenv('VAPID_PUBLIC_KEY', 'PUB')
    monkeypatch.setenv('VAPID_PRIVATE_KEY', 'PRIV')
    monkeypatch.setenv('VAPID_SUBJECT', 'mailto:crew@venue.test')
    assert push_service.vapid_keys() == ('PUB', 'PRIV', 'mailto:crew@venue.test')


def test_subscribe_unsubscribe_and_key(app, alice, pushes):
    assert alice.get('/push/key').get_json()['publicKey']
    assert alice.post('/push/subscribe', json={'subscription': {'endpoint': 'http://insecure'}}).status_code == 400
    subscribe(alice)
    subscribe(alice)                                                             # same device twice: one row
    assert PushSubscription.query.count() == 1
    # Someone else opts in on the same (shared) phone: the device moves to them
    bob = client_for(app, 'bob')
    subscribe(bob)
    assert PushSubscription.query.one().user_id == uid('bob')
    assert alice.post('/push/unsubscribe', json={'endpoint': 'https://push.example.test/alice-phone'}).status_code == 200
    assert PushSubscription.query.count() == 1                                   # alice can't remove bob's
    bob.post('/push/unsubscribe', json={'endpoint': 'https://push.example.test/alice-phone'})
    assert PushSubscription.query.count() == 0


def test_signed_out_cannot_subscribe(app):
    r = app.test_client().post('/push/subscribe', json={})
    assert r.status_code in (302, 401)


def test_preferences_and_test_push(app, alice, pushes):
    kinds = alice.get('/push/preferences').get_json()
    assert all(k['on'] for k in kinds['kinds']) and kinds['devices'] == 0
    subscribe(alice)
    assert alice.post('/push/test').get_json()['sent'] == 1
    assert pushes[0][1]['url'] == '/crew/my-schedule'

    alice.put('/push/preferences', json={'kinds': {'shift_assigned': False}})
    alice.put('/push/preferences', json={'kinds': {'shift_reminder': False}})    # one at a time keeps the other
    off = {k['key'] for k in alice.get('/push/preferences').get_json()['kinds'] if not k['on']}
    assert off == {'shift_assigned', 'shift_reminder'}
    assert push_service.send_to_user(uid('alice'), 'shift_assigned', 'x') == 0
    alice.put('/push/preferences', json={'kinds': {'shift_assigned': True}})
    assert push_service.send_to_user(uid('alice'), 'shift_assigned', 'x') == 1


def test_dead_subscriptions_are_removed(app, alice, pushes):
    for ep in ('https://push.example.test/gone', 'https://push.example.test/dead',
               'https://push.example.test/flaky', 'https://push.example.test/ok'):
        subscribe(alice, ep)
    assert push_service.send_to_user(uid('alice'), 'shift_assigned', 'Hi') == 1
    left = {s.endpoint for s in PushSubscription.query.all()}
    assert left == {'https://push.example.test/flaky', 'https://push.example.test/ok'}   # 500 is kept


def test_new_shift_is_pushed_even_without_email(app, admin, alice, pushes):
    subscribe(alice)
    from models import User
    User.query.filter_by(username='alice').first().email = None
    db.session.commit()
    eid = mk(admin, title='Gig')
    r = admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound',
                                                    'start': '2026-11-10T18:00', 'end': '2026-11-10T22:00'})
    assert r.status_code == 200, r.get_json()
    assert len(pushes) == 1
    assert pushes[0][1]['title'] == 'New shift: Sound' and pushes[0][1]['url'] == '/crew/my-schedule'
    assert 'Gig' in pushes[0][1]['body']


def test_added_to_event_is_pushed(app, admin, alice, pushes):
    subscribe(alice)
    eid = mk(admin, title='Panto')
    assert admin.post('/crew/assign', json={'event_id': eid, 'crew_member': 'alice'}).status_code == 200
    assert pushes[-1][1]['title'] == 'Added to Panto' and pushes[-1][1]['url'] == f'/events/{eid}'


def test_shift_reminder_push_without_email(app, admin, alice, pushes):
    app.config['MAIL_USERNAME'] = ''                                             # email not set up at all
    now = datetime.now().replace(second=0, microsecond=0)
    eid = mk(admin, title='Gig', event_date=iso(now + timedelta(hours=20)), event_end_date=iso(now + timedelta(hours=26)))
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound',
                                                'start': iso(now + timedelta(hours=20)),
                                                'end': iso(now + timedelta(hours=23))})
    pushes.clear()
    # Turned off by alice: not sent and not marked done
    alice.put('/push/preferences', json={'kinds': {'shift_reminder': False}})
    subscribe(alice)
    assert send_due_shift_reminders(now) == 0
    assert ShiftAssignment.query.first().reminder_sent_at is None
    alice.put('/push/preferences', json={'kinds': {'shift_reminder': True}})
    assert send_due_shift_reminders(now) == 1
    assert pushes[0][1]['title'] == 'Shift tomorrow: Gig' or pushes[0][1]['title'] == 'Shift today: Gig'
    assert send_due_shift_reminders(now) == 0 and len(pushes) == 1             # only once


def test_declined_shift_pushes_the_chosen_admins(app, admin, alice, pushes):
    subscribe(admin, 'https://push.example.test/boss-laptop')
    assert admin.put('/admin/api/notifications', json={'user_ids': [uid('boss')]}).status_code == 200
    eid = mk(admin, title='Gig')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound',
                                                'start': '2026-11-10T18:00', 'end': '2026-11-10T22:00'})
    a = ShiftAssignment.query.filter_by(user_id=uid('alice')).first()
    assert alice.post(f'/shifts/assignment/{a.id}/respond', json={'status': 'rejected'}).status_code == 200
    assert [(ep, p['title'], p['url']) for ep, p in pushes] == [
        ('https://push.example.test/boss-laptop', 'Shift declined: alice', f'/events/{eid}')]
