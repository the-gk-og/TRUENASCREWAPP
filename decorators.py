"""
decorators.py
=============
Custom Flask route decorators.
"""

from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user


def crew_required(f):
    """Redirect cast-only users away from crew pages."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_cast:
            flash("Access restricted to crew members.")
            return redirect(url_for('cast.cast_events'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Return 403 JSON or redirect if user is not an admin."""
    from flask import jsonify, request
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            if request.is_json:
                return jsonify({'error': 'Admin access required'}), 403
            flash('Admin access required')
            return redirect(url_for('crew.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
