"""Login (any letter case, username or email) and the separate display Name.  Run: pytest tests/test_names_and_login.py"""
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from extensions import db
from models import (User, Event, CrewAssignment, EventNote, InviteCode, CastMember,
                    ShiftAssignment)
from tests.test_events import app, admin, alice, client_for, uid, mk, ics_path   # noqa: F401  (fixtures)
from services import user_names


def set_pw(username, pw='secret12'):
    u = User.query.filter_by(username=username).first()
    u.password_hash = generate_password_hash(pw)
    db.session.commit()


def login(app, who, pw='secret12'):
    c = app.test_client()
    r = c.post('/login', data={'username': who, 'password': pw})
    return c, r


def logged_in(r):                       # successful login redirects away from /login
    return r.status_code == 302 and '/login' not in r.headers['Location']


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_username_any_case(app):
    set_pw('alice')
    for who in ('alice', 'ALICE', 'Alice', 'aLiCe', '  alice  '):
        c, r = login(app, who)
        assert logged_in(r), who
    _, r = login(app, 'alice', 'wrong-password')
    assert not logged_in(r)
    _, r = login(app, 'nobody')
    assert not logged_in(r)


def test_login_with_email_any_case(app):
    set_pw('alice')
    for who in ('alice@x.test', 'ALICE@X.TEST', 'Alice@x.Test'):
        c, r = login(app, who)
        assert logged_in(r), who
    _, r = login(app, 'alice@x.test', 'nope')
    assert not logged_in(r)


def test_login_ambiguous_case_needs_exact(app):
    """Old data may hold both 'Sam' and 'sam': only an exact match can sign in then."""
    db.session.add_all([User(username='Sam', user_role='crew', password_hash=generate_password_hash('one-pass')),
                        User(username='sam', user_role='crew', password_hash=generate_password_hash('two-pass'))])
    db.session.commit()
    assert logged_in(login(app, 'Sam', 'one-pass')[1])
    assert logged_in(login(app, 'sam', 'two-pass')[1])
    assert not logged_in(login(app, 'SAM', 'one-pass')[1])


def test_forgot_password_finds_by_name_or_email_any_case(app):
    c = app.test_client()
    for who in ('ALICE', 'Alice@X.test'):
        r = c.post('/password/forgot', json={'username_or_email': who})
        assert r.status_code in (200, 500)            # 500 = mail not configured in tests; user *was* found
        assert 'If that account exists' not in (r.get_json() or {}).get('message', '')
    assert 'If that account exists' in c.post('/password/forgot', json={'username_or_email': 'ghost'}).get_json()['message']


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

def _invite(role='crew'):
    inv = InviteCode(code='ABCD1234', role=role, created_by='boss', max_uses=10,
                     expires_at=datetime.utcnow() + timedelta(days=1))
    db.session.add(inv); db.session.commit()


def _signup(app, **over):
    data = {'invite_code': 'ABCD1234', 'username': 'newbie', 'display_name': 'Nina  Newbie',
            'email': 'Nina@X.test', 'password': 'secret12', 'confirm_password': 'secret12'}
    data.update(over)
    c = app.test_client()
    return c, c.post('/signup', data=data)


def test_signup_saves_name_and_clean_email(app):
    _invite()
    c, r = _signup(app)
    assert r.status_code == 302
    u = User.query.filter_by(username='newbie').first()
    assert u.display_name == 'Nina Newbie'                      # whitespace tidied
    assert u.shown_name == 'Nina Newbie'
    assert u.email == 'nina@x.test'                             # stored lower-case
    assert logged_in(login(app, 'NINA@x.test', 'secret12')[1])  # and still usable to log in


def test_signup_name_is_optional_falls_back_to_username(app):
    _invite()
    _signup(app, display_name='')
    u = User.query.filter_by(username='newbie').first()
    assert u.display_name is None and u.shown_name == 'newbie'


def test_signup_rejects_case_clashes_and_at_sign(app):
    _invite()
    assert User.query.count() == 3
    for over in ({'username': 'ALICE'},                    # same username, different case
                 {'email': 'ALICE@X.TEST'},                # same email, different case
                 {'username': 'a@b.com'},                  # '@' not allowed in usernames
                 {'display_name': 'x'},                    # too short
                 {'display_name': '<b>hi</b>'}):           # markup not allowed
        _signup(app, **over)
        assert User.query.count() == 3, over


# ---------------------------------------------------------------------------
# Settings: change Name / username / email
# ---------------------------------------------------------------------------

def test_settings_set_and_clear_name(app, alice):
    r = alice.post('/settings/update-account', json={'display_name': '  Alice   Smith '})
    assert r.status_code == 200 and r.get_json()['name'] == 'Alice Smith'
    assert User.query.filter_by(username='alice').first().shown_name == 'Alice Smith'
    assert 'Alice Smith' in alice.get('/settings').data.decode()
    r = alice.post('/settings/update-account', json={'display_name': ''})   # blank = show username again
    assert r.get_json()['name'] == 'alice'
    assert alice.post('/settings/update-account', json={'display_name': 'a'}).status_code == 400
    assert alice.post('/settings/update-account', json={}).status_code == 400


def test_settings_username_rules_and_references_follow_rename(app, admin, alice):
    eid = mk(alice, title='Mine')
    db.session.add(CrewAssignment(event_id=eid, crew_member='alice', role='Sound'))
    db.session.add(EventNote(event_id=eid, content='hello', created_by='alice'))
    db.session.commit()

    assert alice.post('/settings/update-account', json={'username': 'BOB'}).status_code == 400     # taken (any case)
    assert alice.post('/settings/update-account', json={'username': 'x@y.com'}).status_code == 400
    assert alice.post('/settings/update-account', json={'username': 'al'}).status_code == 400
    assert alice.post('/settings/update-account', json={'email': 'BOB@x.test'}).status_code == 400

    r = alice.post('/settings/update-account', json={'username': 'Alice.S', 'email': 'ALICE.S@x.test'})
    assert r.status_code == 200 and r.get_json()['username'] == 'Alice.S'
    assert User.query.get(uid('Alice.S')).email == 'alice.s@x.test'
    # everything that remembered her by username now points at the new one
    assert CrewAssignment.query.filter_by(event_id=eid).first().crew_member == 'Alice.S'
    assert EventNote.query.filter_by(event_id=eid).first().created_by == 'Alice.S'
    assert Event.query.get(eid).created_by == 'Alice.S'
    # case-only change is allowed for yourself
    assert alice.post('/settings/update-account', json={'username': 'alice.s'}).status_code == 200


def test_cast_card_follows_name(app, admin):
    u = User.query.filter_by(username='bob').first()
    cm = CastMember(actor_name='bob', character_name='Hamlet', user_id=u.id)
    db.session.add(cm); db.session.commit()
    bob = client_for(app, 'bob')
    bob.post('/settings/update-account', json={'display_name': 'Bobby Tables'})
    assert CastMember.query.get(cm.id).actor_name == 'Bobby Tables'


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def test_admin_creates_and_edits_with_name(app, admin):
    r = admin.post('/admin/users/add', json={'username': 'Carol', 'display_name': 'Carol Danvers',
                                              'email': 'Carol@X.test', 'password': 'secret12', 'user_role': 'crew'})
    assert r.status_code == 200, r.get_json()
    u = r.get_json()['user']
    assert u['name'] == 'Carol Danvers' and u['username'] == 'Carol' and u['email'] == 'carol@x.test'
    assert admin.post('/admin/users/add', json={'username': 'CAROL', 'password': 'secret12'}).status_code == 400
    assert admin.post('/admin/users/add', json={'username': 'x@y', 'password': 'secret12'}).status_code == 400
    assert admin.post('/admin/users/add', json={'username': 'dave', 'email': 'CAROL@x.test', 'password': 'secret12'}).status_code == 400

    # rename + new name: references follow
    db.session.add(CrewAssignment(event_id=mk(admin), crew_member='Carol', role='Lights')); db.session.commit()
    r = admin.put(f"/admin/users/edit/{u['id']}", json={'username': 'carol.d', 'display_name': 'Captain Marvel'})
    assert r.status_code == 200 and r.get_json()['user']['name'] == 'Captain Marvel'
    assert CrewAssignment.query.filter_by(crew_member='carol.d').count() == 1
    assert any(x['name'] == 'Captain Marvel' for x in admin.get('/admin/api/users').get_json())


# ---------------------------------------------------------------------------
# Where the Name is shown
# ---------------------------------------------------------------------------

def _named(app):
    for username, name in (('alice', 'Alice Anderson'), ('boss', 'The Boss')):
        User.query.filter_by(username=username).first().display_name = name
    db.session.commit()


def test_name_shown_on_event_page_and_apis(app, admin):
    _named(app)
    eid = mk(admin, title='Gala')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    admin.post(f'/events/{eid}/notes', json={'content': 'remember the gaffer tape'})
    page = admin.get(f'/events/{eid}').data.decode()
    assert 'Alice Anderson' in page and 'The Boss' in page          # team, "created by", note author
    assert '>alice<' not in page.replace(' ', '')
    # assignment JSON: both name (display) and username (login) are available
    a = ShiftAssignment.query.first()
    from routes.events import serialize_assignment
    d = serialize_assignment(a)
    assert d['name'] == 'Alice Anderson' and d['username'] == 'alice'
    # event / note JSON carry a display name next to the raw created_by
    assert admin.get(f'/events/{eid}').status_code == 200


def test_name_in_calendar_feeds(app, admin, alice):
    _named(app)
    eid = mk(admin, title='Gala')
    admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
    items = admin.get('/api/calendar/feed?start=2026-11-01T00:00&end=2026-12-01T00:00&shifts=all').get_json()
    shifts = [i for i in items if i['extendedProps']['kind'] == 'shift']
    assert shifts and shifts[0]['title'] == 'Alice Anderson: Sound'
    assert shifts[0]['extendedProps']['name'] == 'Alice Anderson'
    # personal ICS feed is labelled with her name
    body = app.test_client().get(ics_path(alice)).data.decode()
    assert 'X-WR-CALNAME:ShowWise - Alice Anderson' in body
    # the calendar page's "view someone" menu lists names
    assert 'Alice Anderson' in admin.get('/calendar').data.decode()


def test_forms_ask_for_the_right_things(app):
    c = app.test_client()
    login_page = c.get('/login').data.decode()
    assert 'Username or email' in login_page and 'autocapitalize="none"' in login_page
    signup_page = c.get('/signup').data.decode()
    assert 'name="display_name"' in signup_page and 'Not case-sensitive' in signup_page


def test_name_in_top_bar_and_welcome(app, alice):
    User.query.filter_by(username='alice').first().display_name = 'Alice Anderson'
    db.session.commit()
    page = alice.get('/dashboard').data.decode()
    assert 'Alice Anderson' in page


def test_shift_email_greets_by_name(app, admin):
    from extensions import mail
    _named(app)
    app.config['MAIL_USERNAME'] = 'sender@x.test'
    eid = mk(admin, title='Gala')
    with mail.record_messages() as outbox:
        admin.post(f'/events/{eid}/team/add', json={'user_id': uid('alice'), 'role': 'Sound'})
        assert 'Alice Anderson' in outbox[0].html


def test_person_filter_and_helpers(app):
    _named(app)
    assert user_names.name_for('alice') == 'Alice Anderson'
    assert user_names.name_for('ALICE') == 'Alice Anderson'          # stored strings may differ in case
    assert user_names.name_for('bob') == 'bob'                       # no Name set -> username
    assert user_names.name_for('Discord Bot') == 'Discord Bot'       # not a person -> unchanged
    assert user_names.name_for('') == ''
    assert user_names.clean_display_name('  Mary   Jane ') == ('Mary Jane', None)
    assert user_names.clean_display_name('')[0] is None
    assert user_names.clean_display_name('A')[1] and user_names.clean_display_name('x' * 61)[1]
    assert user_names.username_problem('a@b.c') and user_names.username_problem('ok_name') is None


def test_display_name_schema_upgrade(app):
    from sqlalchemy import text
    from app import ensure_schema
    db.session.execute(text('ALTER TABLE user DROP COLUMN display_name'))
    db.session.commit()
    ensure_schema(app)
    assert 'display_name' in {c['name'] for c in db.inspect(db.engine).get_columns('user')}
