"""
extensions.py
=============
Flask extension instances — created here, initialised in app.py.
Import from here everywhere else to avoid circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from authlib.integrations.flask_client import OAuth
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Main application database
db = SQLAlchemy()

# Separate security database (can be shared across instances)
security_db = SQLAlchemy()

login_manager = LoginManager()
mail = Mail()
oauth = OAuth()

# CSRF Protection
csrf = CSRFProtect()

# Rate Limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"  # Use memory, or "redis://localhost:6379" for distributed
)

login_manager.login_view = 'auth.login'
