"""
extensions.py
=============
Flask extension instances — created here, initialised in app.py.
Import from here everywhere else to avoid circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

login_manager.login_view = 'auth.login'
