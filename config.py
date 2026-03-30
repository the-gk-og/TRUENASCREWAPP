"""
config.py
=========
All configuration for the ShowWise Flask application.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def parse_duration(duration_str: str) -> timedelta:
    """
    Parse duration string into timedelta.
    Supports: 1d (day), 1w (week), 1h (hour), 30m (minute).
    """
    duration_str = (duration_str or '1w').strip().lower()
    try:
        if duration_str.endswith('w'):
            return timedelta(weeks=int(duration_str[:-1]))
        elif duration_str.endswith('d'):
            return timedelta(days=int(duration_str[:-1]))
        elif duration_str.endswith('h'):
            return timedelta(hours=int(duration_str[:-1]))
        elif duration_str.endswith('m'):
            return timedelta(minutes=int(duration_str[:-1]))
        else:
            return timedelta(days=int(duration_str))
    except (ValueError, AttributeError):
        print(f"⚠️  Invalid SESSION_DURATION format: '{duration_str}'. Using default 1 week.")
        return timedelta(weeks=1)


SESSION_DURATION = os.environ.get('SESSION_DURATION', '1w')
_session_lifetime = parse_duration(SESSION_DURATION)


class BaseConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')

    # Main application database
    # Defaults to SQLite (overridden in Production)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 'sqlite:///production_crew.db'
    )
    
    # Separate security database (shared across instances in production)
    # Defaults: File-based SQLite for development/beta testing
    #          Override in production with PostgreSQL URL
    # This design allows:
    #   - Local testing without database server (dev/beta)
    #   - Production deployment with centralized security DB (shared across instances)
    SECURITY_DATABASE_URI = os.environ.get(
        'SECURITY_DATABASE_URL', 'sqlite:///security.db'
    )
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Uploads
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Session / Remember-me
    PERMANENT_SESSION_LIFETIME = _session_lifetime
    REMEMBER_COOKIE_DURATION   = _session_lifetime

    # Development defaults (safe + simple)
    SESSION_COOKIE_SECURE      = False
    SESSION_COOKIE_HTTPONLY    = True
    SESSION_COOKIE_SAMESITE    = 'Lax'

    REMEMBER_COOKIE_SECURE     = False
    REMEMBER_COOKIE_HTTPONLY   = True
    REMEMBER_COOKIE_SAMESITE   = 'Lax'

    # Mail
    MAIL_SERVER         = os.environ.get('MAIL_SERVER', '')
    MAIL_PORT           = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS        = os.environ.get('MAIL_USE_TLS', True)
    MAIL_USERNAME       = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD       = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@prodcrew.local')

    # Organisation
    ORGANIZATION_SLUG = os.environ.get('ORGANIZATION_SLUG', '')
    MAIN_SERVER_URL   = os.environ.get('MAIN_SERVER_URL', 'https://showwise.app')
    SIGNUP_BASE_URL   = os.environ.get('SIGNUP_BASE_URL', os.environ.get('MAIN_SERVER_URL', ''))

    # Discord
    DISCORD_BOT_TOKEN   = os.environ.get('DISCORD_BOT_TOKEN', '')
    DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')
    DISCORD_GUILD_ID    = os.environ.get('DISCORD_GUILD_ID', '')
    DISCORD_BOT_SECRET  = os.environ.get('DISCORD_BOT_SECRET', 'change-this-secret')

    # Google OAuth
    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    GOOGLE_REDIRECT_URI  = os.environ.get(
        'GOOGLE_REDIRECT_URI', 'http://localhost:5001/auth/google/callback'
    )


class DevelopmentConfig(BaseConfig):
    """
    Development Configuration
    - Local SQLite for both main and security databases
    - Perfect for local development with instant setup
    """
    DEBUG = True
    # Dev stays simple: no secure cookies, SameSite=Lax is fine.


class BetaConfig(BaseConfig):
    """
    Beta/Testing Configuration
    - File-based SQLite for easy testing without database server
    - Can be deployed easily to staging/UAT environments
    - Great for testing new features before production rollout
    - Use: FLASK_ENV=beta python app.py
    """
    DEBUG = True
    
    # Always use separate file-based SQLite unless explicitly overridden
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 'sqlite:///beta_crew.db'
    )
    SECURITY_DATABASE_URI = os.environ.get(
        'SECURITY_DATABASE_URL', 'sqlite:///beta_security.db'
    )
    
    # No secure cookies for easier testing across different machines
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_SAMESITE = 'Lax'


class ProductionConfig(BaseConfig):
    """
    Production Configuration
    - Requires PostgreSQL (or other server) for main database
    - Requires server-based security database (shared across instances)
    - All secure cookie settings enabled for HTTPS/Cloudflare
    """
    DEBUG = False
    
    # Production REQUIRES explicit database URLs (cannot use defaults)
    # Set DATABASE_URL and SECURITY_DATABASE_URL to PostgreSQL (or other server) URLs
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SECURITY_DATABASE_URI = os.environ.get('SECURITY_DATABASE_URL')
    
    if not SQLALCHEMY_DATABASE_URI or not SECURITY_DATABASE_URI:
        raise ValueError(
            "PRODUCTION REQUIRES: DATABASE_URL and SECURITY_DATABASE_URL env vars. "
            "Set these to PostgreSQL (or other server) database URLs.\n"
            "Cannot use file-based SQLite in production."
        )

    # Required for Google OAuth PKCE + Cloudflare HTTPS
    SESSION_COOKIE_SECURE      = True
    SESSION_COOKIE_SAMESITE    = "None"

    REMEMBER_COOKIE_SECURE     = True
    REMEMBER_COOKIE_SAMESITE   = "None"


class TestingConfig(BaseConfig):
    """
    Testing Configuration (Unit Tests)
    - In-memory databases for fast, isolated tests
    - No I/O overhead or data persistence
    """
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECURITY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


# Configuration mapping: FLASK_ENV -> Config class
# Usage:
#   FLASK_ENV=development  -> Local development (file-based SQLite)
#   FLASK_ENV=beta         -> Beta/UAT testing (separate file-based SQLite)
#   FLASK_ENV=production   -> Production (requires PostgreSQL URLs)
#   FLASK_ENV=testing      -> Unit tests (in-memory SQLite)
config_map = {
    'development': DevelopmentConfig,  # Local dev with default SQLite
    'beta':        BetaConfig,         # Beta testing with separate SQLite DBs
    'production':  ProductionConfig,   # Production with PostgreSQL
    'testing':     TestingConfig,      # Unit tests with in-memory DBs
    'default':     DevelopmentConfig,  # Fallback to development
}


def get_config():
    """Get configuration class based on FLASK_ENV environment variable."""
    env = os.environ.get('FLASK_ENV', 'default')
    return config_map.get(env, DevelopmentConfig)
