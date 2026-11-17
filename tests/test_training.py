"""Training sign-offs: skills, sign-offs, shift blocking + override, gear warnings, matrix.
Run: pytest tests/test_training.py"""
import os, sys
from datetime import date, datetime, timedelta

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                   # noqa: E402
from extensions import db                                    # noqa: E402
from models import (User, Event, Shift, ShiftAssignment, Equipment, EquipmentUnit,  # noqa: E402
                    Skill, SkillSignoff, SkillOverride, ShiftSkillRequirement)
from services import training_service as ts                  # noqa: E402


class _Client(FlaskClient):
    def open(self, *a, **k):
        g.pop('_login_user', None)
        return super().open(*a, **k)


@pytest.fixture()
def app():
    app = create_app('testing')
    app.test_client_class = _Client
    with app.app_context():
        db.create_all()
        for name, admin in (('boss', True), ('alice', False), ('bob', False), ('carol', False)):
            db.session.add(User(username=name, is_admin=admin, user_role='crew', email=f'{name}@x.test'))
        db.session.add(Event(title='Show', event_date=datetime(2030, 11, 10, 18),
                             event_end_date=datetime(2030, 11, 10, 22)))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def client_for(app, username):
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = str(uid(username))
        s['_fresh'] = True
    return c


def uid(n): return User.query.filter_by(username=n).first().id
def eid(): return Event.query.first().id


@pytest.fixture()
def admin(app): return client_for(app, 'boss')
@pytest.fixture()
def alice(app): return client_for(app, 'alice')
@pytest.fixture()
def bob(app): return client_for(app, 'bob')


def make_skill(admin, **kw):
    body = {'name': 'Fly system', 'validity_months': 12, 'roles': ['Flys']}
    body.update(kw)
    r = admin.post('/api/training/skills', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['skill']


def sign(c, who, skill_id, default_expiry=False, **kw):
    """Sign off; with no expiry unless asked (shifts in these tests are in 2030)."""
    if not default_expiry:
        kw.setdefault('expires_at', None)
    return c.post('/api/training/signoffs', json={'user_id': uid(who), 'skill_id': skill_id, **kw})


def add_shift(c, who, role='Flys', **kw):
    body = {'user_id': uid(who), 'role': role, 'start': '2030-11-10T09:00', 'end': '2030-11-10T17:00'}
    body.update(kw)
    return c.post(f'/events/{eid()}/team/add', json=body)


# --------------------------------------------------------------- skills

def test_only_admins_manage_skills(app, admin, alice):
    assert alice.post('/api/training/skills', json={'name': 'Pyro'}).status_code == 403
    s = make_skill(admin, assessor_ids=[uid('alice')])
    assert s['roles'] == ['Flys'] and s['assessor_ids'] == [uid('alice')]
    assert admin.post('/api/training/skills', json={'name': 'fly SYSTEM'}).status_code == 400   # duplicate
    assert admin.put(f"/api/training/skills/{s['id']}", json={'validity_months': 999}).status_code == 400
    assert admin.delete(f"/api/training/skills/{s['id']}").status_code == 200
    assert db.session.get(Skill, s['id']).is_active is False
    assert alice.get('/training/manage').status_code == 403
    assert admin.get('/training/manage').status_code == 200


def test_signoff_defaults_expiry_and_permissions(app, admin, alice, bob):
    s = make_skill(admin, assessor_ids=[uid('alice')])
    assert sign(bob, 'carol', s['id']).status_code == 403            # not an assessor
    assert sign(alice, 'alice', s['id']).status_code == 403          # never yourself
    r = sign(alice, 'carol', s['id'], default_expiry=True, signed_at='2026-01-31', note='Assessed at bump-in')
    assert r.status_code == 200, r.get_json()
    so = r.get_json()['signoff']
    assert so['signed_by'] == 'alice' and so['expires_at'] == '2027-01-31'
    # No expiry when the skill never expires; explicit expiry must be after sign-off date
    s2 = make_skill(admin, name='Sound desk', validity_months=None, roles=[])
    assert sign(admin, 'carol', s2['id'], default_expiry=True).get_json()['signoff']['expires_at'] is None
    assert sign(admin, 'carol', s2['id'], signed_at='2026-05-01', expires_at='2026-04-01').status_code == 400


def test_states_and_revoke(app, admin):
    s = make_skill(admin)
    today = date.today()
    sign(admin, 'alice', s['id'], signed_at=(today - timedelta(days=400)).isoformat(),
         expires_at=(today + timedelta(days=10)).isoformat())
    assert ts.signoff_state(uid('alice'), s['id']) == 'expiring'
    assert ts.signoff_state(uid('alice'), s['id'], on=today + timedelta(days=11)) == 'expired'
    assert ts.signoff_state(uid('bob'), s['id']) == 'none'
    assert [e['signoff'].user_id for e in ts.expiring_signoffs()] == [uid('alice')]
    so = SkillSignoff.query.first()
    assert admin.post(f'/api/training/signoffs/{so.id}/revoke', json={'reason': 'Failed refresher'}).status_code == 200
    assert ts.signoff_state(uid('alice'), s['id']) == 'none'
    assert ts.expiring_signoffs() == []


def test_add_months_clamps_month_end():
    assert ts.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert ts.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)


# --------------------------------------------------------------- shift blocking

def test_role_requirement_blocks_assignment(app, admin):
    s = make_skill(admin)
    r = add_shift(admin, 'alice', role='flys')                       # case-insensitive role match
    assert r.status_code == 409
    d = r.get_json()
    assert d['skill_block'] and d['can_override'] and d['missing'][0]['name'] == 'Fly system'
    assert 'not signed off' in d['error']
    assert ShiftAssignment.query.count() == 0
    # Other roles are fine
    assert add_shift(admin, 'alice', role='Sound').status_code == 200
    # Signed off: allowed
    sign(admin, 'alice', s['id'])
    assert add_shift(admin, 'alice', role='Flys', start='2030-11-11T09:00', end='2030-11-11T17:00').status_code == 200


def test_expired_signoff_blocks_at_shift_date(app, admin):
    s = make_skill(admin)
    sign(admin, 'alice', s['id'], signed_at='2026-01-01', expires_at='2030-11-01')   # expires before the shift
    r = add_shift(admin, 'alice')
    assert r.status_code == 409 and r.get_json()['missing'][0]['state'] == 'expired'


def test_admin_override_is_recorded(app, admin):
    make_skill(admin)
    r = add_shift(admin, 'alice', skill_override_reason='Shadowing Bob, supervised')
    assert r.status_code == 200, r.get_json()
    o = SkillOverride.query.one()
    assert o.user_id == uid('alice') and o.reason == 'Shadowing Bob, supervised'
    assert o.skill_names == 'Fly system' and o.overridden_by == 'boss'
    assert o.assignment_id == ShiftAssignment.query.one().id
    # The matrix shows it to admins
    assert b'Shadowing Bob' in admin.get('/training/matrix').data


def test_explicit_shift_requirements(app, admin):
    s = make_skill(admin, name='Pyro', roles=[])
    r = add_shift(admin, 'alice', role='Crew', required_skill_ids=[s['id']])
    assert r.status_code == 409
    sign(admin, 'alice', s['id'])
    r = add_shift(admin, 'alice', role='Crew', required_skill_ids=[s['id']])
    assert r.status_code == 200
    assert ShiftSkillRequirement.query.one().skill_id == s['id']


def test_edit_role_rechecks(app, admin):
    make_skill(admin)
    a = add_shift(admin, 'alice', role='Sound').get_json()['shift']
    r = admin.put(f"/events/shift-assignments/{a['assignment_id']}", json={'role': 'Flys'})
    assert r.status_code == 409 and r.get_json()['skill_block']
    # Changing only the notes doesn't re-check
    assert admin.put(f"/events/shift-assignments/{a['assignment_id']}", json={'notes': 'hi'}).status_code == 200


def test_bulk_add_skips_untrained_then_override(app, admin):
    s = make_skill(admin)
    sign(admin, 'bob', s['id'])
    body = {'user_ids': [uid('alice'), uid('bob')], 'role': 'Flys',
            'start': '2030-11-10T09:00', 'end': '2030-11-10T17:00'}
    d = admin.post(f'/events/{eid()}/team/bulk-add', json=body).get_json()
    assert d['added'] == 1
    assert d['skipped'][0]['user_id'] == uid('alice') and d['skipped'][0]['skill']
    d = admin.post(f'/events/{eid()}/team/bulk-add',
                   json={**body, 'user_ids': [uid('alice')], 'skill_override_reason': 'Trainee'}).get_json()
    assert d['added'] == 1 and SkillOverride.query.one().reason == 'Trainee'


def test_roster_routes_are_gated(app, admin):
    s = make_skill(admin)
    body = {'event_id': eid(), 'user_id': uid('alice'), 'role': 'Flys',
            'start': '2030-11-10T09:00', 'end': '2030-11-10T17:00'}
    assert admin.post('/api/roster/shift', json=body).status_code == 409
    # Open shift with an explicit requirement, then drop someone on it
    r = admin.post('/api/roster/shift', json={**body, 'user_id': None, 'role': 'Crew',
                                              'required_skill_ids': [s['id']]})
    assert r.status_code == 200, r.get_json()
    shift = Shift.query.filter_by(is_open=True).one()
    r = admin.post('/api/roster/drop', json={'key': f's:{shift.id}', 'user_id': uid('alice'), 'date': '2030-11-10'})
    assert r.status_code == 409 and r.get_json()['skill_block']
    r = admin.put(f'/api/roster/open/{shift.id}', json={'user_id': uid('alice'), 'skill_override_reason': 'Cover'})
    assert r.status_code == 200 and SkillOverride.query.count() == 1


def test_non_admin_cannot_override(app, admin):
    """The gate itself only honours an override reason from an admin."""
    from flask_login import login_user
    from routes.events import ApiError
    make_skill(admin)
    alice_user = db.session.get(User, uid('alice'))
    with app.test_request_context():
        login_user(db.session.get(User, uid('bob')))
        with pytest.raises(ApiError) as exc:
            ts.skill_gate(alice_user, {'skill_override_reason': 'please'}, role='Flys')
        assert exc.value.extra['can_override'] is False


# --------------------------------------------------------------- gear warning

def test_checkout_warns_when_scanner_not_signed_off(app, admin, alice):
    s = make_skill(admin, name='Pyro', roles=[])
    eq = Equipment(barcode='PYRO1', name='Flash pot', tracking='individual')
    db.session.add(eq)
    db.session.flush()
    db.session.add(EquipmentUnit(equipment_id=eq.id, asset_tag='FP-1'))
    db.session.commit()
    admin.put(f"/api/training/skills/{s['id']}", json={'equipment_ids': [eq.id]})
    unit = EquipmentUnit.query.one()
    r = alice.post('/equipment/checkout/scan', json={'event_id': eid(), 'unit_id': unit.id, 'mode': 'out'})
    assert r.status_code == 200, r.get_json()
    codes = [w['code'] for w in r.get_json()['warnings']]
    assert 'skill_missing' in codes
    # Signed off: no skill warning
    alice.post('/equipment/checkout/scan', json={'event_id': eid(), 'unit_id': unit.id, 'mode': 'return'})
    sign(admin, 'alice', s['id'])
    r = alice.post('/equipment/checkout/scan', json={'event_id': eid(), 'unit_id': unit.id, 'mode': 'out'})
    assert 'skill_missing' not in [w['code'] for w in r.get_json()['warnings']]


# --------------------------------------------------------------- pages

def test_pages_and_visibility(app, admin, alice, bob):
    s = make_skill(admin, assessor_ids=[uid('alice')])
    sign(admin, 'bob', s['id'], signed_at=date.today().isoformat(),
         expires_at=(date.today() + timedelta(days=5)).isoformat())
    assert b'Fly system' in bob.get('/training').data
    assert b'Needs renewing' in bob.get('/training').data
    assert bob.get('/training/matrix').status_code == 403
    assert bob.get(f"/training/people/{uid('carol')}").status_code == 403
    assert bob.get(f"/training/people/{uid('bob')}").status_code == 200
    m = alice.get('/training/matrix')                                # assessors see the matrix
    assert m.status_code == 200 and b'Expiring soon' in m.data
    assert admin.get(f"/training/people/{uid('bob')}").status_code == 200
    j = alice.get(f"/api/training/users/{uid('bob')}").get_json()
    assert j['skills'][0]['state'] == 'expiring'
    # Dashboard reminder
    assert b'Your Fly system sign-off' in bob.get('/dashboard').data


def test_deleting_user_cleans_up(app, admin):
    s = make_skill(admin, assessor_ids=[uid('carol')])
    sign(admin, 'carol', s['id'])
    assert admin.delete(f"/admin/users/delete/{uid('carol')}").status_code == 200
    assert SkillSignoff.query.count() == 0
    assert db.session.get(Skill, s['id']).assessors == []
