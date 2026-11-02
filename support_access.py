"""
ShowWise support access: signed, short-lived, single-use support login tokens.

How it works
  * You hold an Ed25519 PRIVATE key (never on a customer instance).
  * Each instance only has the PUBLIC key (SUPPORT_PUBLIC_KEY) and its own
    SUPPORT_INSTANCE_ID. Tokens are bound to one instance ("aud"), expire in
    minutes, and can be used once.
  * A valid token opens a time-limited support session. There is no database
    user, so the support account never shows up in user lists, rosters,
    shift pickers, emails or exports.
  * Every login attempt and every state-changing request is written to an
    audit log that org admins can read at /support/audit.
  * Feature is OFF unless both env vars are set (all /support/* routes 404).

Env vars
  SUPPORT_PUBLIC_KEY            base64 Ed25519 public key(s), comma separated during rotation
                                (shown in the backend support portal, or from support_keygen.py)
  SUPPORT_INSTANCE_ID           unique id for this deployment, e.g. "greenroom-crew"
  SUPPORT_SESSION_MINUTES       session length after login (default 60)
  SUPPORT_ALLOWED_IPS           optional comma list of IPs/CIDRs allowed to log in
  SUPPORT_TRUST_PROXY_HEADERS   "1" to read CF-Connecting-IP / X-Forwarded-For
  SUPPORT_BLOCKED_PREFIXES      optional comma list of URL prefixes support can't touch
  SUPPORT_LANDING_PATH          where to send support after login (default "/")
  SUPPORT_DB_PATH               sqlite file for audit/replay (default instance/support_access.sqlite)
"""
from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import (Blueprint, abort, current_app, g, redirect,
                   render_template_string, request, session)
from markupsafe import Markup, escape

try:  # Flask-Login is optional; used by the default login hook
    from flask_login import UserMixin, login_user, logout_user, current_user
except ImportError:  # pragma: no cover
    UserMixin = object
    login_user = logout_user = current_user = None

log = logging.getLogger("support_access")

ISSUER = "showwise-support"
MAX_TOKEN_LIFETIME = 30 * 60      # seconds a token may be valid for
CLOCK_SKEW = 30                   # seconds of tolerated clock drift
FAIL_LIMIT, FAIL_WINDOW = 5, 300  # failed logins per IP per window
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# Always off-limits to support, on top of SUPPORT_BLOCKED_PREFIXES: personal account, 2FA and password pages
# belong to the real person, and a restore would overwrite the whole database.
DEFAULT_BLOCKED = ("/settings", "/change-password", "/api/2fa", "/api/settings", "/login/2fa",
                   "/auth/google", "/admin/restore")
SCOPES = ("readonly", "admin")

support_bp = Blueprint("support_access", __name__, url_prefix="/support")
_hooks = {"login": None, "is_admin": None}


class SupportError(Exception):
    """Token rejected. The message is for the audit log only."""


# --------------------------------------------------------------------- config
def _cfg() -> dict:
    e = os.environ.get
    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]
    return {
        "public_key": (e("SUPPORT_PUBLIC_KEY") or "").strip(),
        "instance_id": (e("SUPPORT_INSTANCE_ID") or "").strip(),
        "session_minutes": int(e("SUPPORT_SESSION_MINUTES", "60")),
        "allowed_ips": split(e("SUPPORT_ALLOWED_IPS")),
        "blocked": list(DEFAULT_BLOCKED) + split(e("SUPPORT_BLOCKED_PREFIXES")),
        "trust_proxy": e("SUPPORT_TRUST_PROXY_HEADERS", "0") == "1",
        "landing": e("SUPPORT_LANDING_PATH", "/"),
        "db_path": e("SUPPORT_DB_PATH"),
    }


def _enabled(cfg=None) -> bool:
    cfg = cfg or _cfg()
    return bool(cfg["public_key"] and cfg["instance_id"])


# ------------------------------------------------------------------- storage
_SCHEMA = """
CREATE TABLE IF NOT EXISTS used_tokens(
    jti TEXT PRIMARY KEY, used_at INTEGER NOT NULL, operator TEXT);
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, event TEXT NOT NULL,
    operator TEXT, scope TEXT, ip TEXT, user_agent TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_ip_ts ON audit(ip, ts);
"""


@contextmanager
def _db():
    path = _cfg()["db_path"] or os.path.join(current_app.instance_path, "support_access.sqlite")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.executescript(_SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _client_ip() -> str:
    if _cfg()["trust_proxy"]:
        ip = request.headers.get("CF-Connecting-IP") or \
             request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if ip:
            return ip
    return request.remote_addr or "?"


def _audit(event, operator=None, scope=None, detail=None):
    with _db() as con:
        con.execute(
            "INSERT INTO audit(ts,event,operator,scope,ip,user_agent,detail) VALUES(?,?,?,?,?,?,?)",
            (int(time.time()), event, operator, scope, _client_ip(),
             (request.headers.get("User-Agent") or "")[:200], (detail or "")[:500]))


def _recent_failures(ip: str) -> int:
    with _db() as con:
        return con.execute(
            "SELECT COUNT(*) FROM audit WHERE event='login_failed' AND ip=? AND ts>?",
            (ip, int(time.time()) - FAIL_WINDOW)).fetchone()[0]


def _consume_jti(jti: str, operator: str) -> bool:
    """Atomically mark a token used. False if it was already used."""
    try:
        with _db() as con:
            con.execute("INSERT INTO used_tokens(jti,used_at,operator) VALUES(?,?,?)",
                        (jti, int(time.time()), operator))
        return True
    except sqlite3.IntegrityError:
        return False


# -------------------------------------------------------------- verification
def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(token: str, cfg: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        p_b64, s_b64 = token.split(".")
        payload_bytes, sig = _b64d(p_b64), _b64d(s_b64)
    except Exception:
        raise SupportError("malformed token")
    keys = []  # SUPPORT_PUBLIC_KEY may hold several keys (comma separated) during rotation
    for part in re.split(r"[,\s]+", cfg["public_key"]):
        if part:
            try:
                keys.append(Ed25519PublicKey.from_public_bytes(_b64d(part)))
            except Exception:
                continue
    if not keys:
        raise SupportError("SUPPORT_PUBLIC_KEY is invalid")
    for key in keys:
        try:
            key.verify(sig, payload_bytes)
            break
        except InvalidSignature:
            continue
    else:
        raise SupportError("bad signature")
    try:
        p = json.loads(payload_bytes)
        assert isinstance(p, dict)
    except Exception:
        raise SupportError("malformed payload")

    if p.get("iss") != ISSUER:
        raise SupportError("wrong issuer")
    if p.get("aud") != cfg["instance_id"]:
        raise SupportError(f"token is for another instance ({str(p.get('aud'))[:40]})")
    iat, exp = p.get("iat"), p.get("exp")
    if not all(isinstance(x, (int, float)) for x in (iat, exp)):
        raise SupportError("missing iat/exp")
    if now > exp + CLOCK_SKEW:
        raise SupportError("token expired")
    if iat > now + CLOCK_SKEW:
        raise SupportError("token issued in the future")
    if exp - iat > MAX_TOKEN_LIFETIME:
        raise SupportError("token lifetime too long")
    if p.get("scope") not in SCOPES:
        raise SupportError("bad scope")
    if not isinstance(p.get("jti"), str) or not 8 <= len(p["jti"]) <= 64:
        raise SupportError("bad jti")
    if not isinstance(p.get("sub"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", p["sub"]):
        raise SupportError("bad operator name")
    return p


def _ip_allowed(ip: str, allowed: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in ipaddress.ip_network(a, strict=False) for a in allowed)
    except ValueError:
        return False


# ---------------------------------------------------------------- the account
class SupportUser(UserMixin):
    """Virtual user. Never stored in the DB, so it can't appear in any list.

    It carries every attribute the ShowWise crew app reads from ``current_user`` (decorators.py,
    templates, settings pages) so pages render for it instead of raising AttributeError.
    """
    is_support = True
    is_active = True

    def __init__(self, operator: str, scope: str):
        self.operator, self.scope = operator, scope
        self.key = f"support:{scope}:{operator}"   # what Flask-Login keeps in the session
        self.id = 0                                # matches no real user row, so personal queries come back empty
        self.username = self.name = self.display_name = self.shown_name = f"Support ({operator})"
        self.email = None
        self.role = self.user_role = "admin"
        self.is_admin = self.is_staff = self.is_superuser = True
        self.is_cast = False
        self.profile_picture = None
        self.discord_id = self.discord_username = None
        self.password_hash = None
        self.oauth_connections = []
        self.calendar_token = None
        self.force_2fa_setup = False
        self.skip_2fa_for_oauth = False
        self.created_at = None

    def get_id(self):
        return self.key


def load_support_user(user_id):
    """Call this first in your Flask-Login user_loader."""
    if not isinstance(user_id, str) or not user_id.startswith("support:"):
        return None
    s = session.get("support")
    if not s or s.get("uid") != user_id or time.time() > s.get("exp", 0):
        return None
    return SupportUser(s["op"], s["scope"])


def _default_login(user):
    if login_user is None:
        raise RuntimeError("Flask-Login not installed: pass login_hook to init_support_access()")
    login_user(user, remember=False)


def _default_is_admin() -> bool:
    return bool(current_user is not None and current_user.is_authenticated
                and getattr(current_user, "is_admin", False))


def _end_session(reason: str):
    s = session.get("support") or {}
    try:
        _audit(reason, s.get("op"), s.get("scope"))
    except Exception:
        log.exception("support audit failed")
    if logout_user is not None:
        logout_user()
    session.pop("support", None)


# ------------------------------------------------------------------- routes
_PASTE_FORM = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Support login</title><body style="font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem">
<h2>Support login</h2><form method=post><textarea name=token rows=5 style="width:100%"
placeholder="Paste support token" autocomplete=off></textarea><p><button>Sign in</button></p></form></body>"""

_AUDIT_PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Support audit log</title><body style="font-family:system-ui;margin:1rem">
<h2>Support access log</h2><p>Every support login attempt and change made during a support session.</p>
<div style="overflow-x:auto"><table border=1 cellpadding=6 style="border-collapse:collapse;font-size:.9rem">
<tr><th>Time (UTC)<th>Event<th>Operator<th>Scope<th>IP<th>Detail</tr>
{% for r in rows %}<tr><td>{{ r[0] }}<td>{{ r[1] }}<td>{{ r[2] or '' }}<td>{{ r[3] or '' }}<td>{{ r[4] or '' }}<td>{{ r[5] or '' }}</tr>
{% endfor %}</table></div></body>"""


@support_bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = _cfg()
    if not _enabled(cfg):
        abort(404)
    ip = _client_ip()
    if _recent_failures(ip) >= FAIL_LIMIT:
        abort(429)
    token = (request.values.get("token") or "").strip()
    if not token:
        return render_template_string(_PASTE_FORM)

    def fail(reason):
        _audit("login_failed", detail=reason)
        abort(403, "Support login failed.")

    if cfg["allowed_ips"] and not _ip_allowed(ip, cfg["allowed_ips"]):
        fail("ip not allowed")
    try:
        p = verify_token(token, cfg)
    except SupportError as e:
        fail(str(e))
    if not _consume_jti(p["jti"], p["sub"]):
        fail("token already used")

    op, scope = p["sub"], p["scope"]
    exp = int(time.time()) + cfg["session_minutes"] * 60
    session.clear()
    session["support"] = {"op": op, "scope": scope, "exp": exp,
                          "uid": f"support:{scope}:{op}"}
    (_hooks["login"] or _default_login)(SupportUser(op, scope))
    _audit("login_ok", op, scope, f"session {cfg['session_minutes']} min")
    return redirect(cfg["landing"])


@support_bp.route("/logout", methods=["GET", "POST"])
def logout():
    if session.get("support"):
        _end_session("logout")
    return redirect("/")


@support_bp.route("/audit")
def audit_view():
    if not _enabled():
        abort(404)
    if not (getattr(g, "support", None) or (_hooks["is_admin"] or _default_is_admin)()):
        abort(403)
    with _db() as con:
        rows = con.execute(
            "SELECT ts,event,operator,scope,ip,detail FROM audit ORDER BY id DESC LIMIT 300").fetchall()
    rows = [(datetime.fromtimestamp(r[0], timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),) + r[1:]
            for r in rows]
    return render_template_string(_AUDIT_PAGE, rows=rows)


# ------------------------------------------------------- guards and the banner
def _guard():
    s = session.get("support")
    if not s:
        return None
    cfg = _cfg()
    if not _enabled(cfg) or time.time() > s.get("exp", 0):
        _end_session("session_expired")
        return redirect("/")
    g.support = s
    if request.path.startswith("/support/"):
        return None
    if s["scope"] == "readonly" and request.method not in SAFE_METHODS:
        _audit("blocked", s["op"], s["scope"], f"read-only: {request.method} {request.path}")
        abort(403, "This support session is read-only.")
    if any(request.path.startswith(p) for p in cfg["blocked"]):
        _audit("blocked", s["op"], s["scope"], f"blocked prefix: {request.method} {request.path}")
        abort(403, "Support access is not permitted here.")
    return None


def _banner(s) -> str:
    until = datetime.fromtimestamp(s["exp"], timezone.utc).strftime("%H:%M UTC")
    return (
        '<div style="position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#b00020;'
        'color:#fff;font:14px system-ui;padding:8px 12px;display:flex;gap:12px;flex-wrap:wrap;'
        'align-items:center;justify-content:center">'
        f"<strong>ShowWise support session</strong> {escape(s['op'])} ({escape(s['scope'])}) until {until}"
        ' &middot; <a href="/support/audit" style="color:#fff">audit log</a>'
        ' &middot; <a href="/support/logout" style="color:#fff">end session</a></div>'
        "<style>html{padding-bottom:44px}</style>")


def _after(resp):
    s = getattr(g, "support", None)
    if not s:
        return resp
    if request.method not in SAFE_METHODS and not request.path.startswith("/support/"):
        try:
            _audit("action", s["op"], s["scope"],
                   f"{request.method} {request.path} -> {resp.status_code}")
        except Exception:
            log.exception("support audit failed")
    if (resp.mimetype == "text/html" and not resp.direct_passthrough
            and not resp.headers.get("Content-Encoding")):
        body = resp.get_data(as_text=True)
        i = body.lower().rfind("</body>")
        if i != -1:
            resp.set_data(body[:i] + _banner(s) + body[i:])
    return resp


def init_support_access(app, login_hook=None, is_admin_hook=None):
    """Call right after creating the app, BEFORE your own before_request hooks."""
    _hooks["login"], _hooks["is_admin"] = login_hook, is_admin_hook
    app.register_blueprint(support_bp)
    app.before_request_funcs.setdefault(None, []).insert(0, _guard)
    app.after_request(_after)
    csrf = app.extensions.get("csrf")  # Flask-WTF CSRFProtect
    if csrf is not None:
        csrf.exempt(support_bp)
    if _enabled():
        app.logger.warning("Support access ENABLED for instance %r", _cfg()["instance_id"])
