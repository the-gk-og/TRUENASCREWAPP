# ShowWise support access (signed tokens)

You keep a private key. Each instance holds only the public key and its own ID.
A token is signed for ONE instance, lasts 1-30 min, and works once. A valid token opens a
time-limited support session as a virtual user (no DB row, so it never appears in lists/exports).

> If you use the backend portal (see support-admin), skip step 1 and take the env values from the portal.

## 1. One-time setup (your machine, manual mode)
    pip install cryptography
    python tools/support_keygen.py          # saves ~/.showwise/support_ed25519.key (chmod 600)
Back the key up somewhere safe. Never put it on a server.

## 2. Per instance (.env)
    SUPPORT_PUBLIC_KEY=<from the portal or keygen; several keys comma-separated during rotation>
    SUPPORT_INSTANCE_ID=<unique per deployment, e.g. greenroom-crew>
    SUPPORT_SESSION_MINUTES=60              # optional
    SUPPORT_ALLOWED_IPS=                    # optional, e.g. your Tailscale/home IP
    SUPPORT_TRUST_PROXY_HEADERS=1           # set behind Cloudflare Tunnel (uses CF-Connecting-IP)
    SUPPORT_BLOCKED_PREFIXES=               # optional, e.g. /admin/secrets,/admin/users/delete
Leave the two required vars unset and the feature is completely off (/support/* returns 404).
Add `cryptography` to requirements.txt.

## 3. Wire into the Flask app (3 edits)
    # app.py, right after app = Flask(...) and BEFORE your own before_request hooks
    from support_access import init_support_access, load_support_user
    init_support_access(app)

    # your Flask-Login user_loader: check the support user first
    @login_manager.user_loader
    def load_user(user_id):
        return load_support_user(user_id) or User.query.get(int(user_id))

Not using Flask-Login? Pass `init_support_access(app, login_hook=fn, is_admin_hook=fn)`.
If you use Flask-WTF CSRFProtect it's exempted automatically.
If a global before_request redirects anonymous users, whitelist `/support/login`.

## 4. Getting in
    python tools/support_mint.py --instance greenroom-crew --operator elijah \
        --url https://crew.greenroom.org                 # read-only (default), 10 min
    python tools/support_mint.py --instance greenroom-crew --scope admin --minutes 15 --url ...
Open the printed link within the token lifetime. A red bar is shown on every page for the session.

## What it enforces
- Ed25519 signature, issuer, instance binding, expiry (30s skew), max 30 min lifetime, single use.
- Failed logins audited; 5 failures per IP per 5 min -> 429.
- `readonly` scope blocks every non-GET request. `admin` can write, and each write is logged.
- Session expires on its own; /support/logout ends it early.
- Audit log at /support/audit (org admins and support), stored in instance/support_access.sqlite.

## Things to adapt / know
- `SupportUser` (support_access.py) is a stand-in with is_admin/role/name fields. If your
  templates or decorators read other `current_user` attributes (e.g. `current_user.id` as an int,
  `crew_role`), add them there.
- Default blocked list is empty because I haven't seen your routes. Add prefixes for password
  changes, user deletion and secret/token settings (Discord bot token, SMTP).
- Rate limiting and replay protection use SQLite, so they hold across gunicorn workers on one
  host. Several containers must share SUPPORT_DB_PATH.
- Tell customers it exists (and that sessions are logged and visible to them).

## Tests
    pip install flask flask-login cryptography && python tests/test_support_access.py
