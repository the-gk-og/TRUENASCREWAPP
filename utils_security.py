"""
utils_security.py
=================
Security utility functions: input validation, sanitization, account lockout checks.
"""

import re
from datetime import datetime, timedelta
from bleach import clean
from werkzeug.utils import secure_filename


# ============================================================================
# INPUT SANITIZATION
# ============================================================================

def sanitize_input(data: str, allow_html: bool = False) -> str:
    """
    Remove potentially dangerous content from user input.
    
    Args:
        data: User input string
        allow_html: If True, allow safe HTML tags (b, i, em, strong, etc)
    
    Returns:
        Sanitized string
    """
    if not isinstance(data, str):
        return str(data)
    
    if allow_html:
        # Allow minimal safe HTML
        allowed_tags = ['b', 'i', 'em', 'strong', 'u', 'p', 'br', 'a', 'ul', 'ol', 'li']
        allowed_attrs = {'a': ['href', 'target']}
        return clean(data, tags=allowed_tags, attributes=allowed_attrs, strip=True)
    else:
        # Remove all HTML/scripts
        return clean(data, tags=[], strip=True)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent directory traversal and malicious filenames.
    
    Args:
        filename: Original filename
    
    Returns:
        Safe filename
    """
    return secure_filename(filename)


def sanitize_sql_identifier(identifier: str) -> str:
    """
    Basic SQL identifier sanitization (table names, column names).
    Note: This is NOT for SQL values - use parameterized queries instead!
    
    Args:
        identifier: Potential SQL identifier
    
    Returns:
        Safe identifier or raises ValueError if dangerous
    """
    # Only allow alphanumeric and underscores
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return identifier


# ============================================================================
# EMAIL VALIDATION
# ============================================================================

def validate_email(email: str) -> bool:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        True if valid email format, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 254


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets security requirements.
    
    Args:
        password: Password to validate
    
    Returns:
        Tuple of (is_valid, message)
    """
    issues = []
    
    if len(password) < 12:
        issues.append("At least 12 characters required")
    if not re.search(r'[A-Z]', password):
        issues.append("Must contain uppercase letter")
    if not re.search(r'[a-z]', password):
        issues.append("Must contain lowercase letter")
    if not re.search(r'[0-9]', password):
        issues.append("Must contain number")
    if not re.search(r'[!@#$%^&*(),.?":{}| <>]', password):
        issues.append("Must contain special character")
    
    is_valid = len(issues) == 0
    message = "; ".join(issues) if issues else "Password is strong"
    
    return is_valid, message


def validate_username(username: str) -> bool:
    """
    Validate username format and length.
    
    Args:
        username: Username to validate
    
    Returns:
        True if valid, False otherwise
    """
    # Alphanumeric, underscore, hyphen, 3-50 chars
    if not re.match(r'^[a-zA-Z0-9_-]{3,50}$', username):
        return False
    return True


# ============================================================================
# ACCOUNT LOCKOUT MANAGEMENT
# ============================================================================

LOCKOUT_THRESHOLD = 5  # Failed attempts before lockout
LOCKOUT_DURATION = 30  # Minutes


def is_account_locked(user) -> bool:
    """
    Check if user account is currently locked.
    Automatically unlocks if lockout duration has passed.
    
    Args:
        user: User model instance
    
    Returns:
        True if account is locked, False otherwise
    """
    if not user.locked_until:
        return False
    
    if datetime.utcnow() < user.locked_until:
        return True
    
    # Lockout duration passed, unlock
    user.locked_until = None
    user.failed_login_attempts = 0
    return False


def record_failed_login(user) -> tuple[bool, str]:
    """
    Record a failed login attempt and potentially lock account.
    
    Args:
        user: User model instance
    
    Returns:
        Tuple of (is_locked, message)
    """
    user.failed_login_attempts += 1
    user.last_login_attempt = datetime.utcnow()
    
    if user.failed_login_attempts >= LOCKOUT_THRESHOLD:
        user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION)
        return True, f"Account locked for {LOCKOUT_DURATION} minutes due to too many failed login attempts"
    
    remaining = LOCKOUT_THRESHOLD - user.failed_login_attempts
    return False, f"Invalid credentials. {remaining} attempts remaining before lockout."


def record_successful_login(user):
    """
    Clear failed login attempts on successful login.
    
    Args:
        user: User model instance
    """
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_attempt = datetime.utcnow()


# ============================================================================
# AUDIT LOGGING
# ============================================================================

def log_audit_action(
    username: str,
    action: str,
    resource_type: str,
    resource_id: str = None,
    resource_name: str = None,
    change_details: dict = None,
    ip_address: str = None,
    user_agent: str = None,
    app_instance: str = None
) -> bool:
    """
    Log an audit action to the security database.
    
    Args:
        username: User who performed action
        action: Action name ("user_created", "shift_deleted", etc)
        resource_type: Type of resource ("user", "shift", "crew", etc)
        resource_id: ID of affected resource
        resource_name: Human-readable name of resource
        change_details: Dict of field changes: {"field": {"old": val, "new": val}}
        ip_address: IP address of request
        user_agent: User agent of request
        app_instance: Which ShowWise instance this occurred on
    
    Returns:
        True on success, False on error
    """
    try:
        from extensions import security_db
        from models_security import AuditLog
        
        audit = AuditLog(
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            change_details=change_details,
            ip_address=ip_address,
            user_agent=user_agent,
            app_instance=app_instance,
        )
        security_db.session.add(audit)
        security_db.session.commit()
        return True
    except Exception as e:
        print(f"ERROR logging audit action: {e}")
        return False


# ============================================================================
# RATE LIMITING HELPERS
# ============================================================================

def get_rate_limit_key(identifier: str, endpoint: str) -> str:
    """
    Generate a rate limit key for storing attempt counts.
    
    Args:
        identifier: IP address or user ID
        endpoint: API endpoint or action
    
    Returns:
        Rate limit key
    """
    return f"ratelimit:{identifier}:{endpoint}"


def check_rate_limit(identifier: str, endpoint: str, max_attempts: int, window_seconds: int) -> bool:
    """
    Check if rate limit has been exceeded (requires Flask-Limiter in app).
    This is a basic helper; use Flask-Limiter decorators in routes for production.
    
    Args:
        identifier: IP address or user ID
        endpoint: API endpoint
        max_attempts: Maximum attempts allowed
        window_seconds: Time window in seconds
    
    Returns:
        True if within limit, False if exceeded
    """
    # Note: For production, use @limiter.limit() decorators on routes
    # This is just a helper for manual checks if needed
    pass
