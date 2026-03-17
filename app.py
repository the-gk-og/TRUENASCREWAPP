"""
app.py
======
ShowWise — Flask application factory.
"""
from flask import Flask, render_template, request
import os
import atexit

from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from extensions import db, login_manager, mail, oauth
from routes import register_blueprints
from services.email_service import init_email_service


def create_app(config_name: str | None = None):
    """Application factory."""
    app = Flask(__name__, static_folder='static', static_url_path='/static')

    # Load config
    if config_name:
        from config import config_map
        app.config.from_object(config_map.get(config_name, get_config()))
    else:
        app.config.from_object(get_config())

    # Trust proxy headers (Cloudflare / nginx / tunnels)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Initialise extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    init_email_service(app, mail)

    # --- Authlib OAuth (Google PKCE) ---
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        },
    )

    # User loader
    from models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Context processor
    @app.context_processor
    def inject_globals():
        from models import User as _User
        def get_user_by_username(username):
            return _User.query.filter_by(username=username).first()
        return dict(
            get_user_by_username=get_user_by_username,
            app=app,
            ORG_SLUG=app.config.get('ORGANIZATION_SLUG', ''),
        )

    # ---------------------------------------------------------------------------
    # Kill-switch check
    # Reads the in-memory flag kept fresh by the background ping scheduler.
    # Zero network cost per request.
    # ---------------------------------------------------------------------------
    @app.before_request
    def check_service_status():
        if request.path.startswith('/static'):
            return
        from routes.backend import get_kill_switch_state
        enabled, reason = get_kill_switch_state()
        if enabled:
            return render_template('suspended.html', reason=reason), 503

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html') if os.path.exists('templates/404.html') else 'Not Found', 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('500.html') if os.path.exists('templates/500.html') else 'Server Error', 500

    # Ensure upload dirs exist
    for sub in ('', 'users', 'stageplans', 'picklists', 'documents'):
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], sub), exist_ok=True)
    os.makedirs('backups', exist_ok=True)

    # Register all blueprints
    register_blueprints(app)

    # Backend client + ping scheduler
    with app.app_context():
        try:
            from routes.backend import init_backend_client, start_ping_scheduler
            backend = init_backend_client(app)
            if backend:
                backend.log_info('Application starting', 'system', {'version': '1.0.0'})

                # Org config — cached internally; CONFIG_REFRESH env var controls TTL
                org_config = backend.get_organization()
                if org_config:
                    app.config['ORG_NAME']      = org_config.get('name')
                    app.config['ORG_LOGO']      = org_config.get('logo')
                    app.config['PRIMARY_COLOR'] = org_config.get('primary_color')
                    print(f"✓ Loaded config for: {org_config.get('name')}")

                # Start kill-switch ping scheduler (replaces old heartbeat)
                start_ping_scheduler(app, backend)

        except Exception as exc:
            print(f"⚠️  Backend init error: {exc}")

        # Rocket.Chat
        try:
            from rocketchat_client import init_rocketchat
            rc = init_rocketchat()
            if rc.is_connected():
                print(f"✓ Connected to Rocket.Chat at {rc.server_url}")
        except Exception:
            pass

    return app


def init_db(app):
    """Create tables and default admin if missing."""
    from models import User
    from werkzeug.security import generate_password_hash
    import string, secrets as _secrets

    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            chars    = string.ascii_letters + string.digits + string.punctuation
            safe     = ''.join(c for c in chars if c not in 'l1LO0|`~')
            password = ''.join(_secrets.choice(safe) for _ in range(32))
            db.session.add(User(
                username='admin',
                password_hash=generate_password_hash(password),
                is_admin=True,
            ))
            db.session.commit()
            print("\n" + "="*60)
            print("🎭 SHOWWISE — DATABASE INITIALIZED")
            print("="*60)
            print(f"\n  Username: admin\n  Password: {password}\n")
            print("⚠️  Change this password after first login!\n")
            print("="*60 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app = create_app()
    init_db(app)
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)