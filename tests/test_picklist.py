"""Tests for pick list archive, search and live-sync endpoints.  Run: pytest tests/test_picklist.py"""
import os, sys
from datetime import datetime, timedelta

import pytest
from flask import g
from flask.testing import FlaskClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                      # noqa: E402
from extensions import db                       # noqa: E402
from models import User, Event, PickListItem    # noqa: E402

MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148'


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
        db.session.add(User(username='alice', user_role='crew', email='alice@x.test'))
        now = datetime.now()
        evs = {
            'future':  Event(title='Spring Musical',  event_date=now + timedelta(days=10), location='Main Hall'),
            'soon':    Event(title='Assembly',        event_date=now + timedelta(days=2),  location='Gym'),
            'old':     Event(title='Winter Concert',  event_date=now - timedelta(days=30), location='Main Hall'),
            'older':   Event(title='Autumn Showcase', event_date=now - timedelta(days=90)),
            'ongoing': Event(title='Multi Day Expo',  event_date=now - timedelta(days=1),
                             event_end_date=now + timedelta(days=1)),
            'allday':  Event(title='All Day Today',   event_date=now.replace(hour=0, minute=0), all_day=True),
        }
        for e in evs.values():
            db.session.add(e)
        db.session.commit()
        db.session.add(PickListItem(item_name='Gaffer tape', event_id=evs['old'].id))
        db.session.add(PickListItem(item_name='Radio mic',   event_id=evs['future'].id))
        db.session.commit()
        app.evs = {k: v.id for k, v in evs.items()}
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def alice(app):
    c = app.test_client()
    with app.app_context():
        uid = User.query.filter_by(username='alice').first().id
    with c.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    return c


def titles(resp):
    return [r['title'] for r in resp.get_json()['results']]


def test_archive_split(alice):
    res = alice.get('/picklist/search').get_json()['results']
    current  = [r['title'] for r in res if not r['archived']]
    archived = [r['title'] for r in res if r['archived']]
    assert current == ['Multi Day Expo', 'All Day Today', 'Assembly', 'Spring Musical'] or \
           set(current) == {'Multi Day Expo', 'All Day Today', 'Assembly', 'Spring Musical'}
    assert archived == ['Winter Concert', 'Autumn Showcase']          # newest first
    # current always listed before archived
    flags = [r['archived'] for r in res]
    assert flags == sorted(flags)


def test_search_includes_archive_after_current(alice):
    t = titles(alice.get('/picklist/search?q=main hall'))
    assert t == ['Spring Musical', 'Winter Concert']                  # current first, then archived


def test_search_by_item_name_finds_archived(alice):
    assert titles(alice.get('/picklist/search?q=gaffer')) == ['Winter Concert']


def test_search_no_match(alice):
    assert titles(alice.get('/picklist/search?q=zzzz')) == []


def test_pages_render(alice):
    for ua in (None, MOBILE_UA):
        h = {'User-Agent': ua} if ua else {}
        r = alice.get('/picklist', headers=h)
        assert r.status_code == 200 and b'Archive (2)' in r.data
        r = alice.get('/picklist?event_id=%d' % alice.application.evs['old'], headers=h)
        assert r.status_code == 200 and b'Archived' in r.data
        assert b'Gaffer tape' in r.data


def test_toggle_explicit_state_is_idempotent(alice, app):
    with app.app_context():
        item = PickListItem.query.filter_by(item_name='Radio mic').first()
        iid = item.id
    for _ in range(2):    # two people ticking the same item must not cancel out
        r = alice.post(f'/picklist/toggle/{iid}', json={'checked': True})
        assert r.get_json()['is_checked'] is True
    assert alice.post(f'/picklist/toggle/{iid}', json={'checked': False}).get_json()['is_checked'] is False
    assert alice.post(f'/picklist/toggle/{iid}').get_json()['is_checked'] is True      # old flip behaviour kept


def test_state_endpoint(alice, app):
    ev = app.evs['future']
    items = alice.get(f'/picklist/state?event_id={ev}').get_json()['items']
    assert len(items) == 1 and items[0]['checked'] is False
    alice.post(f"/picklist/toggle/{items[0]['id']}", json={'checked': True})
    assert alice.get(f'/picklist/state?event_id={ev}').get_json()['items'][0]['checked'] is True
    assert alice.get('/picklist/state').get_json()['items'] == []        # general list is separate
