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
from extensions import db, security_db, login_manager, mail, oauth, csrf, limiter
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

    # Initialise main database
    db.init_app(app)
    
    # Initialise separate security database (shared across instances)
    # Security database uses its own isolated connection
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    
    security_db_uri = app.config.get('SECURITY_DATABASE_URI', 'sqlite:///security.db')
    security_engine = create_engine(security_db_uri, echo=False)
    security_db.metadata.bind = security_engine
    security_db.session = scoped_session(sessionmaker(bind=security_engine))
    
    login_manager.init_app(app)
    mail.init_app(app)
    init_email_service(app, mail)

    # Initialize CSRF protection
    csrf.init_app(app)
    
    # Initialize Rate Limiter
    limiter.init_app(app)

    # --- NEW: Authlib OAuth (Google PKCE) ---
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
    # ----------------------------------------

    # User loader
    from models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Context processor
    @app.context_processor
    def inject_globals():
        from models import User as _User
        from datetime import datetime
        def get_user_by_username(username):
            return _User.query.filter_by(username=username).first()
        return dict(
            get_user_by_username=get_user_by_username,
            app=app,
            ORG_SLUG=app.config.get('ORGANIZATION_SLUG', ''),
            now=datetime.utcnow,  # Add now() function for templates
        )

    # ========================================================================
    # SECURITY: IP Blacklist & Threat Detection Middleware
    # ========================================================================
    @app.before_request
    def security_check():
        """
        Main security middleware:
        1. Extract Cloudflare client IP
        2. Check IP blacklist
        3. Detect threats (BurpSuite, SQLi, XSS, etc.)
        4. Log all requests
        5. Quarantine suspicious IPs
        """
        if request.path.startswith('/static') or request.path.startswith('/security'):
            return

        from services.security_service import SecurityService

        try:
            # Get client IP (Cloudflare-aware)
            client_ip = SecurityService.get_client_ip()

            # Check if blacklisted
            is_blacklisted, blacklist_record = SecurityService.is_ip_blacklisted(client_ip)
            if is_blacklisted:
                SecurityService.log_security_event(
                    event_type='blacklisted_access_attempt',
                    ip_address=client_ip,
                    severity='high',
                    description=f'Blacklisted IP attempted access to {request.path}'
                )
                return render_template('security/blocked.html', 
                    reason=blacklist_record.reason), 403

            # Detect threats
            query_params = dict(request.args)
            body = request.get_data(as_text=True)[:500]  # First 500 chars
            threats = SecurityService.detect_threats(
                ip_address=client_ip,
                user_agent=request.headers.get('User-Agent'),
                path=request.path,
                query_params=query_params,
                body=body
            )

            # Handle critical threats
            if threats:
                threat_level = 'critical' if 'burpsuite' in threats else 'high'
                
                # Quarantine immediately
                SecurityService.quarantine_ip(
                    ip_address=client_ip,
                    threat_details=threats,
                    threat_level=threat_level
                )

                # Log security event
                SecurityService.log_security_event(
                    event_type='threat_detected',
                    ip_address=client_ip,
                    severity=threat_level,
                    description=f'Threats detected: {", ".join(threats)} on path {request.path}'
                )

                # Block BurpSuite and other scanners immediately
                if 'burpsuite' in threats:
                    return render_template('security/blocked.html',
                        reason='Security scanning tools are not permitted'), 403

                # For other threats, log and let through (but quarantined)
                SecurityService.log_request(
                    ip_address=client_ip,
                    request_method=request.method,
                    request_path=request.path,
                    response_status=200,
                    threat_flags=threats
                )
            else:
                # Normal request - log it
                SecurityService.log_request(
                    ip_address=client_ip,
                    request_method=request.method,
                    request_path=request.path,
                    response_status=200
                )

        except Exception as e:
            print(f"⚠️  Security check error: {e}")
            # Don't block on security errors
            pass

    # Kill switch & error handlers
    @app.before_request
    def check_service_status():
        if request.path.startswith('/static'):
            return
        try:
            from backend_integration import get_backend_client
            backend = get_backend_client()
            if backend:
                enabled, reason = backend.check_kill_switch()
                if enabled:
                    return render_template('suspended.html', reason=reason), 503
        except Exception:
            pass

    # =============================================================================
    # SECURITY: Response Headers (Prevent common attacks)
    # =============================================================================
    @app.after_request
    def set_security_headers(response):
        """Add security headers to prevent clickjacking, MIME sniffing, XSS, etc."""
        # Prevent clickjacking attacks
        response.headers['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS filter in browsers
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Force HTTPS (production only)
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        # Content Security Policy - restrictive defaults
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        
        # Referrer policy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Prevent browsers from opening potentially dangerous files
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        
        return response

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

    # Register all blueprints (OAuth now ready)
    register_blueprints(app)

    # Backend client
    with app.app_context():
        try:
            from backend_integration import init_backend_client
            backend = init_backend_client(app)
            if backend:
                backend.log_info('Application starting', 'system', {'version': '1.0.0'})
                org_config = backend.get_organization()
                if org_config:
                    app.config['ORG_NAME']      = org_config.get('name')
                    app.config['ORG_LOGO']      = org_config.get('logo')
                    app.config['PRIMARY_COLOR'] = org_config.get('primary_color')
                    print(f"✓ Loaded config for: {org_config.get('name')}")
                _start_heartbeat(app, backend)
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


def _start_heartbeat(app, backend):
    from apscheduler.schedulers.background import BackgroundScheduler

    def send_heartbeat():
        with app.app_context():
            from models import User, Event
            try:
                metadata = {
                    'users':        User.query.count(),
                    'events':       Event.query.count(),
                    'organization': os.getenv('ORGANIZATION_SLUG', 'Unknown'),
                }
            except Exception:
                metadata = {}
            backend.send_heartbeat('online', metadata)

    scheduler = BackgroundScheduler()
    scheduler.add_job(send_heartbeat, 'interval', minutes=5)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    print("✓ Uptime tracking enabled")


def init_db(app):
    """Create tables and default admin if missing."""
    from models import User
    from werkzeug.security import generate_password_hash
    import string, secrets as _secrets

    with app.app_context():
        db.create_all()
        security_db.metadata.create_all(security_db.metadata.bind)
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
