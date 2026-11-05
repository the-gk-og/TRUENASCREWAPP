"""Security hardening checks.  Run: pytest tests/test_security.py"""
import io

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import User
from services.security import throttle
from tests.test_events import app, admin, alice, client_for, uid, mk, ics_path   # noqa: F401  (fixtures)
from tests.test_names_and_login import set_pw, login, logged_in


@pytest.fixture(autouse=True)
def _clean_throttle():
    throttle._failures.clear()
    yield
    throttle._failures.clear()


def test_login_is_throttled_after_repeated_failures(app):
    set_pw('alice')
    for _ in range(5):
        login(app, 'alice', 'wrong-password')
    _, r = login(app, 'alice', 'secret12')          # correct password, but the account is locked out for now
    assert r.status_code == 429


def test_cross_site_post_is_blocked(app):
    c = app.test_client()
    r = c.post('/login', data={'username': 'a', 'password': 'b'}, headers={'Origin': 'https://evil.example'})
    assert r.status_code == 403
    r = c.post('/login', data={'username': 'a', 'password': 'b'}, headers={'Sec-Fetch-Site': 'cross-site'})
    assert r.status_code == 403
    r = c.post('/login', data={'username': 'a', 'password': 'b'}, headers={'Origin': 'http://localhost'})
    assert r.status_code != 403                     # same-origin request is processed normally


def test_security_headers_present(app):
    r = app.test_client().get('/login')
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'frame-ancestors' in r.headers['Content-Security-Policy']


def test_discord_bot_endpoints_are_gone(app):
    """The Discord bot was removed; its unauthenticated-by-session API must not exist."""
    c = app.test_client()
    assert c.get('/discord/list-events', headers={'X-Bot-Secret': 'x'}).status_code == 404
    assert c.post('/discord/create-account', json={'username': 'newbie', 'password': 'longenough123'}).status_code in (403, 404)


def test_password_reset_token_is_hashed_and_single_use(app, monkeypatch):
    import routes.auth as auth
    sent = {}
    monkeypatch.setattr(auth, 'send_password_reset_email',
                        lambda **kw: sent.update(kw) or True)
    c = app.test_client()
    c.post('/password/forgot', json={'username_or_email': 'alice'})
    raw = sent['reset_url'].rsplit('/', 1)[1]
    u = User.query.filter_by(username='alice').first()
    assert u.password_reset_token != raw             # DB holds only the hash
    r = c.post(f'/password/reset/{raw}', json={'new_password': 'short', 'confirm_password': 'short'})
    assert r.status_code == 400                      # below the minimum length
    r = c.post(f'/password/reset/{raw}', json={'new_password': 'a-much-longer-pass', 'confirm_password': 'a-much-longer-pass'})
    assert r.status_code == 200
    r = c.post(f'/password/reset/{raw}', json={'new_password': 'another-long-pass', 'confirm_password': 'another-long-pass'})
    assert r.status_code == 400                      # token cannot be reused


def test_stage_plan_upload_rejects_html(app, admin):
    c = admin
    r = c.post('/stageplans/upload', data={'file': (io.BytesIO(b'<script>alert(1)</script>'), 'x.html')},
               content_type='multipart/form-data')
    assert r.status_code == 400
    r = c.post('/stageplans/upload', data={'file': (io.BytesIO(b'<script>alert(1)</script>'), 'x.png')},
               content_type='multipart/form-data')
    assert r.status_code == 400                      # right extension, not actually an image


def test_app_refuses_to_start_in_production_without_secret_key(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    import importlib, config
    importlib.reload(config)
    import app as app_module
    with pytest.raises(RuntimeError):
        app_module.create_app('production')
    importlib.reload(config)
