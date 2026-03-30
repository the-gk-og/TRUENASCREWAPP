"""
models_security.py
==================
Security-specific database models.
These use the separate security_db and are shared across multiple ShowWise instances.
"""

from datetime import datetime
from extensions import security_db


class IPBlacklist(security_db.Model):
    """Permanently blocked/blacklisted IP addresses."""
    __tablename__ = 'ip_blacklist'
    
    id          = security_db.Column(security_db.Integer, primary_key=True)
    ip_address  = security_db.Column(security_db.String(45), unique=True, nullable=False, index=True)
    reason      = security_db.Column(security_db.String(500), nullable=False)
    blocked_by  = security_db.Column(security_db.String(80), nullable=False)
    created_at  = security_db.Column(security_db.DateTime, default=datetime.utcnow, index=True)
    expires_at  = security_db.Column(security_db.DateTime, nullable=True)  # None = permanent
    is_active   = security_db.Column(security_db.Boolean, default=True)


class IPQuarantine(security_db.Model):
    """Suspicious IPs waiting for human review and action."""
    __tablename__ = 'ip_quarantine'
    
    id              = security_db.Column(security_db.Integer, primary_key=True)
    ip_address      = security_db.Column(security_db.String(45), nullable=False, index=True)
    threat_level    = security_db.Column(security_db.String(20), default='medium')  # low, medium, high, critical
    threat_details  = security_db.Column(security_db.Text)  # JSON with threat flags detected
    first_seen      = security_db.Column(security_db.DateTime, default=datetime.utcnow, index=True)
    last_activity   = security_db.Column(security_db.DateTime, default=datetime.utcnow)
    request_count   = security_db.Column(security_db.Integer, default=1)
    status          = security_db.Column(security_db.String(20), default='pending')  # pending, approved, rejected, manual_review
    reviewed_by     = security_db.Column(security_db.String(80), nullable=True)
    reviewed_at     = security_db.Column(security_db.DateTime, nullable=True)
    action_taken    = security_db.Column(security_db.String(500), nullable=True)  # Reason for approval/rejection
    user_agent      = security_db.Column(security_db.String(500), nullable=True)
    is_resolved     = security_db.Column(security_db.Boolean, default=False)
    __table_args__ = (security_db.Index('idx_ip_status', 'ip_address', 'status'),)


class SecurityLog(security_db.Model):
    """Detailed logs of all actions/requests from each IP."""
    __tablename__ = 'security_log'
    
    id              = security_db.Column(security_db.Integer, primary_key=True)
    ip_address      = security_db.Column(security_db.String(45), nullable=False, index=True)
    request_method  = security_db.Column(security_db.String(10), nullable=False)
    request_path    = security_db.Column(security_db.String(500), nullable=False)
    request_headers = security_db.Column(security_db.Text)  # JSON
    response_status = security_db.Column(security_db.Integer)
    user_agent      = security_db.Column(security_db.String(500), nullable=True)
    app_instance    = security_db.Column(security_db.String(100), nullable=True)  # Which ShowWise instance logged this
    threat_flags    = security_db.Column(security_db.Text)  # Comma-separated threat flags: burpsuite, sqli, xss, etc
    created_at      = security_db.Column(security_db.DateTime, default=datetime.utcnow, index=True)
    __table_args__ = (security_db.Index('idx_ip_time', 'ip_address', 'created_at'),)


class SecurityEvent(security_db.Model):
    """High-level security events that trigger alerts."""
    __tablename__ = 'security_event'
    
    id              = security_db.Column(security_db.Integer, primary_key=True)
    event_type      = security_db.Column(security_db.String(100), nullable=False)  # burp_detected, brute_force_attempt, etc
    ip_address      = security_db.Column(security_db.String(45), nullable=False, index=True)
    severity        = security_db.Column(security_db.String(20), default='medium')  # low, medium, high, critical
    description     = security_db.Column(security_db.Text, nullable=False)
    app_instance    = security_db.Column(security_db.String(100), nullable=True)  # Which ShowWise instance detected this
    affected_resource = security_db.Column(security_db.String(500), nullable=True)
    created_at      = security_db.Column(security_db.DateTime, default=datetime.utcnow, index=True)
    is_acknowledged = security_db.Column(security_db.Boolean, default=False)
    acknowledged_at = security_db.Column(security_db.DateTime, nullable=True)
    acknowledged_by = security_db.Column(security_db.String(80), nullable=True)


class AuditLog(security_db.Model):
    """Comprehensive audit log of all admin actions and data changes."""
    __tablename__ = 'audit_log'
    
    id              = security_db.Column(security_db.Integer, primary_key=True)
    username        = security_db.Column(security_db.String(80), nullable=False, index=True)
    action          = security_db.Column(security_db.String(200), nullable=False)  # "user_created", "shift_deleted", "settings_changed"
    resource_type   = security_db.Column(security_db.String(100), nullable=False)  # "user", "shift", "crew", "equipment"
    resource_id     = security_db.Column(security_db.String(200), nullable=True)
    resource_name   = security_db.Column(security_db.String(500), nullable=True)
    change_details  = security_db.Column(security_db.JSON, nullable=True)  # Before/after values: {"field": {"old": val, "new": val}}
    ip_address      = security_db.Column(security_db.String(45), nullable=True)
    user_agent      = security_db.Column(security_db.String(500), nullable=True)
    app_instance    = security_db.Column(security_db.String(100), nullable=True)
    created_at      = security_db.Column(security_db.DateTime, default=datetime.utcnow, index=True)
    __table_args__ = (
        security_db.Index('idx_username_time', 'username', 'created_at'),
        security_db.Index('idx_resource_type', 'resource_type', 'created_at'),
    )
