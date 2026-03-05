"""tests/test_auth.py — Basic auth route tests."""

import pytest
from app import create_app
from extensions import db


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_login_page(client):
    r = client.get('/login')
    assert r.status_code == 200


def test_signup_page(client):
    r = client.get('/signup')
    assert r.status_code == 200
