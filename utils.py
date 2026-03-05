"""
utils.py
========
Shared utility helpers used across the app.
"""

import random
import secrets
import string as _string

from datetime import datetime
from typing import Optional

from flask import current_app
from extensions import db


# ---------------------------------------------------------------------------
# Password & code generators
# ---------------------------------------------------------------------------

def generate_secure_password(length: int = 32) -> str:
    """Generate a cryptographically secure random password."""
    characters = _string.ascii_letters + _string.digits + _string.punctuation
    safe_chars = ''.join(c for c in characters if c not in 'l1LO0|`~')
    return ''.join(secrets.choice(safe_chars) for _ in range(length))


def generate_invite_code(length: int = 16) -> str:
    """Generate a human-readable invite code: ABCD-1234-EFGH-5678."""
    chars = _string.ascii_uppercase + _string.digits
    chars = ''.join(c for c in chars if c not in 'O0I1L')
    segments = [''.join(random.choices(chars, k=4)) for _ in range(4)]
    return '-'.join(segments)


# ---------------------------------------------------------------------------
# Organisation helper
# ---------------------------------------------------------------------------

def get_organization() -> dict:
    """Fetch organisation data from backend API (with simple fallback)."""
    try:
        from backend_integration import get_backend_client
        backend = get_backend_client()
        if backend:
            org_config = backend.get_organization()
            if org_config:
                return org_config
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Security event logging
# ---------------------------------------------------------------------------

def log_security_event(
    event_type: str,
    username: Optional[str] = None,
    description: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Log a security event via the backend client."""
    try:
        from backend_integration import get_backend_client
        from flask import request
        from flask_login import current_user

        backend = get_backend_client()
        if not backend:
            return

        if ip_address is None:
            try:
                ip_address = request.remote_addr
            except Exception:
                ip_address = 'unknown'

        if username is None:
            try:
                username = current_user.username if current_user.is_authenticated else 'anonymous'
            except Exception:
                username = 'unknown'

        log_data = {
            'event_type':  event_type,
            'username':    username,
            'description': description,
            'ip_address':  ip_address,
            'metadata':    metadata or {},
        }
        backend.log_info(
            f"Security Event: {event_type} - User: {username}",
            log_type='auth',
            metadata=log_data,
        )
        print(f"🔐 Security Event: {event_type} ({username})")
    except Exception as exc:
        print(f"⚠️  Could not log security event: {exc}")


# ---------------------------------------------------------------------------
# TOTP / backup-code helpers
# ---------------------------------------------------------------------------

def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate plain-text backup codes (shown once)."""
    codes = []
    for _ in range(count):
        raw = ''.join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    from werkzeug.security import generate_password_hash
    return [generate_password_hash(c.replace('-', '')) for c in codes]


def verify_backup_code(stored_hashes: list[str], provided_code: str) -> Optional[int]:
    """Return the index of the matching backup code, or None."""
    from werkzeug.security import check_password_hash
    provided = provided_code.replace('-', '').strip().upper()
    for i, hashed in enumerate(stored_hashes):
        if check_password_hash(hashed, provided):
            return i
    return None
