import base64, json, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask
from flask_login import LoginManager, login_required, current_user
import support_access as sa
from support_mint import mint_token, b64e

priv = Ed25519PrivateKey.generate()
pub = base64.urlsafe_b64encode(priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()


def make_app(env=True, **extra):
    for k in [k for k in os.environ if k.startswith("SUPPORT_")]:
        del os.environ[k]
    if env:
        os.environ.update({"SUPPORT_PUBLIC_KEY": pub, "SUPPORT_INSTANCE_ID": "inst-a",
                           "SUPPORT_DB_PATH": os.path.join(tempfile.mkdtemp(), "s.sqlite"), **extra})
    app = Flask(__name__)
    app.secret_key = "test"
    lm = LoginManager(app)
    lm.user_loader(lambda uid: sa.load_support_user(uid))
    sa.init_support_access(app)

    @app.route("/")
    @login_required
    def home():
        return f"<html><body>hello {current_user.username}</body></html>"

    @app.route("/edit", methods=["POST"])
    @login_required
    def edit():
        return "ok"
    return app


def audit_events(app):
    with app.app_context(), sa._db() as con:
        return [r[0] for r in con.execute("SELECT event FROM audit ORDER BY id")]


def login(c, tok):
    return c.get("/support/login", query_string={"token": tok})


def test_disabled_by_default():
    c = make_app(env=False).test_client()
    assert c.get("/support/login").status_code == 404
    assert c.get("/support/audit").status_code == 404


def test_login_banner_and_replay():
    app = make_app(); c = app.test_client()
    tok = mint_token(priv, "inst-a", "elijah", "readonly")
    assert login(c, tok).status_code == 302
    page = c.get("/").get_data(as_text=True)
    assert "Support (elijah)" in page and "ShowWise support session" in page
    assert login(app.test_client(), tok).status_code == 403          # replay
    assert audit_events(app) == ["login_ok", "login_failed"]


def test_rejections():
    app = make_app(); c = app.test_client()
    now = time.time()
    assert login(c, mint_token(priv, "other-inst")).status_code == 403           # wrong instance
    assert login(c, mint_token(priv, "inst-a", now=now - 3600)).status_code == 403  # expired
    assert login(c, mint_token(Ed25519PrivateKey.generate(), "inst-a")).status_code == 403  # wrong key
    p, sig = mint_token(priv, "inst-a", scope="readonly").split(".")
    data = json.loads(base64.urlsafe_b64decode(p + "==")); data["scope"] = "admin"
    forged = b64e(json.dumps(data, separators=(",", ":"), sort_keys=True).encode()) + "." + sig
    assert login(c, forged).status_code == 403                                    # tampered scope
    long = mint_token(priv, "inst-a", minutes=120)
    assert login(c, long).status_code == 403                                      # lifetime too long
    assert c.get("/").status_code == 401                                          # never logged in


def test_readonly_blocks_writes_admin_logs_them():
    app = make_app(); c = app.test_client()
    login(c, mint_token(priv, "inst-a", "x", "readonly"))
    assert c.post("/edit").status_code == 403
    app2 = make_app(); c2 = app2.test_client()
    login(c2, mint_token(priv, "inst-a", "x", "admin"))
    assert c2.post("/edit").status_code == 200
    assert "action" in audit_events(app2)


def test_rate_limit():
    app = make_app(); c = app.test_client()
    for _ in range(5):
        assert login(c, "garbage").status_code == 403
    assert login(c, mint_token(priv, "inst-a")).status_code == 429


def test_session_expiry_and_logout():
    app = make_app(); c = app.test_client()
    login(c, mint_token(priv, "inst-a"))
    with c.session_transaction() as sess:
        sess["support"] = {**sess["support"], "exp": int(time.time()) - 1}
    assert c.get("/").status_code == 302
    assert c.get("/").status_code == 401
    assert "session_expired" in audit_events(app)
    c2 = app.test_client(); login(c2, mint_token(priv, "inst-a"))
    c2.get("/support/logout")
    assert c2.get("/").status_code == 401


def test_ip_allowlist_and_blocked_prefix():
    app = make_app(SUPPORT_ALLOWED_IPS="10.0.0.0/8"); c = app.test_client()
    assert login(c, mint_token(priv, "inst-a")).status_code == 403   # test client is 127.0.0.1
    app = make_app(SUPPORT_BLOCKED_PREFIXES="/edit"); c = app.test_client()
    login(c, mint_token(priv, "inst-a", scope="admin"))
    assert c.post("/edit").status_code == 403


def test_audit_page_access():
    app = make_app(); c = app.test_client()
    assert c.get("/support/audit").status_code == 403                # anonymous
    login(c, mint_token(priv, "inst-a"))
    assert c.get("/support/audit").status_code == 200


def test_multiple_public_keys_for_rotation():
    other = Ed25519PrivateKey.generate()
    other_pub = base64.urlsafe_b64encode(other.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()
    app = make_app(SUPPORT_PUBLIC_KEY=f"{other_pub},{pub}")      # new key first, old key still trusted
    assert login(app.test_client(), mint_token(priv, "inst-a")).status_code == 302
    assert login(app.test_client(), mint_token(other, "inst-a")).status_code == 302
    app = make_app(SUPPORT_PUBLIC_KEY=other_pub)                 # old key removed -> rejected
    assert login(app.test_client(), mint_token(priv, "inst-a")).status_code == 403


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
