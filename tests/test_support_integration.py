"""Support login against the REAL crew app (not a stub): token -> session -> pages render -> limits hold.

Run from the repo root:  python tests/test_support_integration.py
"""
import base64, os, sys, tempfile, time

tmp = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

priv = Ed25519PrivateKey.generate()
pub = base64.urlsafe_b64encode(priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
# support_access reads these at request time, so every test needs them set. They are applied
# only while this module builds its app and inside its own tests (fixture below), never left
# behind in os.environ where they would leak into other test modules or be clobbered by them.
ENV = {"SUPPORT_PUBLIC_KEY": pub, "SUPPORT_INSTANCE_ID": "inst-crew", "SUPPORT_DB_PATH": f"{tmp}/support.sqlite",
       "SECRET_KEY": "x" * 40, "DATABASE_URL": f"sqlite:///{tmp}/crew.db", "FLASK_ENV": "testing"}
_saved_env = dict(os.environ)
os.environ.update(ENV)

import pytest

from support_mint import mint_token
from werkzeug.security import generate_password_hash
from app import create_app
from extensions import db
from models import User

app = create_app("testing")
app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp}/crew.db", WTF_CSRF_ENABLED=False)
with app.app_context():
    db.create_all()
    db.session.add(User(username="boss", email="b@x.io", password_hash=generate_password_hash("pw-123456"), is_admin=True, is_cast=False))
    db.session.commit()

os.environ.clear()
os.environ.update(_saved_env)


@pytest.fixture(autouse=True)
def _support_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def token(scope="readonly", minutes=10, instance="inst-crew", operator="elijah"):
    return mint_token(priv, instance, operator, scope, minutes)


def support_client(scope="readonly"):
    c = app.test_client()
    r = c.get("/support/login", query_string={"token": token(scope)})
    assert r.status_code == 302, (r.status_code, r.get_data(as_text=True)[:200])
    return c


def pages(client):
    """Every parameter-less GET page that needs a login, minus the ones that log out or call out."""
    skip = ("/logout", "/support/", "/static", "/auth/google", "/discord/")
    out = []
    for rule in app.url_map.iter_rules():
        if "GET" in rule.methods and not rule.arguments and not rule.rule.startswith(skip):
            out.append(rule.rule)
    return sorted(set(out))


def test_login_lands_on_a_working_page():
    c = support_client()
    r = c.get("/", follow_redirects=True)
    assert r.status_code == 200, r.status_code
    assert b"ShowWise support session" in r.data                       # red banner on every page


def test_no_page_breaks_for_support_that_works_for_admin():
    admin = app.test_client()
    admin.post("/login", data={"username": "boss", "password": "pw-123456"})
    sup = support_client("admin")
    broken = []
    for path in pages(sup):
        a = admin.get(path, follow_redirects=False).status_code
        b = sup.get(path, follow_redirects=False).status_code
        if b >= 500 and a < 500:
            broken.append((path, a, b))
    assert not broken, broken


def test_readonly_cannot_write_and_blocked_areas_are_off_limits():
    c = support_client("readonly")
    assert c.post("/admin/users/add", data={"username": "evil", "password": "x"}).status_code == 403
    assert c.get("/settings").status_code == 403                       # personal settings are never support's
    assert c.get("/change-password").status_code == 403
    adm = support_client("admin")
    assert adm.get("/settings").status_code == 403
    assert adm.post("/admin/restore").status_code == 403


def test_token_is_single_use_and_bound_to_one_instance():
    t = token()
    assert app.test_client().get("/support/login", query_string={"token": t}).status_code == 302
    assert app.test_client().get("/support/login", query_string={"token": t}).status_code == 403      # replay
    assert app.test_client().get("/support/login", query_string={"token": token(instance="other")}).status_code == 403
    assert app.test_client().get("/support/login", query_string={"token": token(minutes=5)[:-3] + "xxx"}).status_code == 403


def test_support_user_never_appears_in_user_lists_and_audit_is_written():
    c = support_client("admin")
    with app.app_context():
        assert User.query.filter(User.username.like("Support%")).count() == 0
    assert c.get("/support/audit").status_code == 200
    assert b"login_ok" in c.get("/support/audit").data


def test_stale_session_id_is_not_a_crash():
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = "support:admin:ghost"                       # looks like a support session, but none exists
    assert c.get("/", follow_redirects=True).status_code == 200        # lands on the login page


def test_plain_users_are_unaffected():
    c = app.test_client()
    r = c.post("/login", data={"username": "boss", "password": "pw-123456"}, follow_redirects=True)
    assert r.status_code == 200 and b"ShowWise support session" not in r.data


if __name__ == "__main__":
    os.environ.update(ENV)
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
