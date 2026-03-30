"""
security_service.py
===================
Comprehensive IP security management: blacklisting, quarantine, threat detection.
Protects against BurpSuite, SQL injection, XSS, brute force, and other threats.
Integrates with Cloudflare Headers for correct client IP extraction.

Uses the SEPARATE security_db for all security data, allowing multiple
ShowWise instances to share the same security database.
"""

import re
import json
import os
from datetime import datetime, timedelta
from flask import request
from extensions import security_db
from models_security import (
    IPBlacklist,
    IPQuarantine,
    SecurityLog,
    SecurityEvent,
)


# THREAT DETECTION SIGNATURES
# ===========================

BURPSUITE_INDICATORS = {
    'user_agents': [
        r'burpsuite',
        r'owasp.*zap',
        r'sqlmap',
        r'nikto',
        r'acunetix',
        r'nessus',
        r'metasploit',
        r'masscan',
        r'nmap',
    ],
    'header_keys': [
        'x-scanner',
        'x-burp',
        'x-zap',
    ],
}

SQL_INJECTION_PATTERNS = [
    r"union.*select",
    r"select.*from",
    r"insert.*into",
    r"delete.*from",
    r"drop.*table",
    r"exec\s*\(",
    r"execute\s*\(",
    r";.*--",
    r"'\s*or\s*'",
    r'".*or.*"',
    r"1\s*=\s*1",
    r"admin.*--",
]

XSS_PATTERNS = [
    r"<script[^>]*>",
    r"javascript:",
    r"onerror\s*=",
    r"onload\s*=",
    r"onclick\s*=",
    r"<iframe",
    r"<img[^>]*on",
    r"<svg[^>]*on",
]

COMMAND_INJECTION_PATTERNS = [
    r";\s*(cat|ls|rm|wget|curl|bash|sh)",
    r"\|\s*(nc|bash|sh|cmd)",
    r"`[^`]*`",
    r"\$\([^)]*\)",
]


class SecurityService:
    """Main security service for IP protection and threat detection."""

    @staticmethod
    def get_client_ip():
        """
        Extract client IP from request, respecting Cloudflare tunnel headers.
        
        Priority:
        1. CF-Connecting-IP (Cloudflare)
        2. X-Forwarded-For (from ProxyFix)
        3. Remote addr
        """
        # Cloudflare's client IP header
        if request.headers.get('CF-Connecting-IP'):
            return request.headers.get('CF-Connecting-IP')
        
        # Standard X-Forwarded-For (already processed by ProxyFix)
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        
        # Direct remote address
        return request.remote_addr or '0.0.0.0'

    @staticmethod
    def is_ip_blacklisted(ip_address: str) -> tuple[bool, IPBlacklist | None]:
        """
        Check if IP is blacklisted.
        
        Returns: (is_blacklisted, blacklist_record)
        """
        blacklist = IPBlacklist.query.filter_by(
            ip_address=ip_address,
            is_active=True
        ).first()

        if not blacklist:
            return False, None

        # Check expiration
        if blacklist.expires_at and blacklist.expires_at < datetime.utcnow():
            blacklist.is_active = False
            security_db.session.commit()
            return False, None

        return True, blacklist

    @staticmethod
    def detect_threats(ip_address: str, user_agent: str = None, path: str = None, 
                      query_params: dict = None, body: str = None) -> list[str]:
        """
        Detect and return list of threat flags found in this request.
        
        Returns list like: ['burpsuite', 'sqli', 'xss', 'high_request_rate']
        """
        threats = []
        
        if not user_agent:
            user_agent = request.headers.get('User-Agent', '')

        # --- BurpSuite & Scanner Detection ---
        ua_lower = user_agent.lower()
        for pattern in BURPSUITE_INDICATORS['user_agents']:
            if re.search(pattern, ua_lower, re.IGNORECASE):
                threats.append('burpsuite')
                break

        # Check suspicious headers
        for header_key in BURPSUITE_INDICATORS['header_keys']:
            if request.headers.get(header_key):
                threats.append('burpsuite')
                break

        # --- SQL Injection Detection ---
        payload = f"{path or ''} {body or ''} {str(query_params or {})}"
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, payload, re.IGNORECASE):
                threats.append('sqli')
                break

        # --- XSS Detection ---
        for pattern in XSS_PATTERNS:
            if re.search(pattern, payload, re.IGNORECASE):
                threats.append('xss')
                break

        # --- Command Injection ---
        for pattern in COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, payload, re.IGNORECASE):
                threats.append('cmd_injection')
                break

        # --- Rate Limits (checked later in middleware) ---
        recent_count = SecurityLog.query.filter(
            SecurityLog.ip_address == ip_address,
            SecurityLog.created_at >= datetime.utcnow() - timedelta(minutes=5)
        ).count()

        if recent_count > 100:  # 100+ requests in 5 minutes
            threats.append('high_request_rate')

        return list(set(threats))

    @staticmethod
    def log_request(ip_address: str, request_method: str, request_path: str,
                   response_status: int, threat_flags: list = None, app_instance: str = None):
        """Log request details to SecurityLog."""
        if not threat_flags:
            threat_flags = []

        try:
            headers_dict = {k: v for k, v in dict(request.headers).items()}
        except:
            headers_dict = {}

        log = SecurityLog(
            ip_address=ip_address,
            request_method=request_method,
            request_path=request_path,
            request_headers=json.dumps(headers_dict),
            response_status=response_status,
            user_agent=request.headers.get('User-Agent', ''),
            app_instance=app_instance or os.getenv('SHOWWISE_INSTANCE_NAME', 'default'),
            threat_flags=','.join(threat_flags) if threat_flags else None,
        )
        security_db.session.add(log)
        security_db.session.commit()

    @staticmethod
    def quarantine_ip(ip_address: str, threat_details: list = None, 
                     threat_level: str = 'medium'):
        """Add IP to quarantine for human review."""
        
        # Check if already quarantined
        quarantine = IPQuarantine.query.filter_by(ip_address=ip_address).first()

        if quarantine:
            quarantine.last_activity = datetime.utcnow()
            quarantine.request_count += 1
            quarantine.threat_details = json.dumps(threat_details or [])
            quarantine.threat_level = max(quarantine.threat_level, threat_level)
        else:
            quarantine = IPQuarantine(
                ip_address=ip_address,
                threat_level=threat_level,
                threat_details=json.dumps(threat_details or []),
                user_agent=request.headers.get('User-Agent', ''),
            )
            security_db.session.add(quarantine)

        security_db.session.commit()
        return quarantine

    @staticmethod
    def get_quarantine_list(filters: dict = None) -> list:
        """
        Get list of quarantined IPs with optional filtering.
        
        filters: {
            'status': 'pending',  # pending, approved, rejected, manual_review
            'threat_level': 'critical',  # low, medium, high, critical
            'days': 7  # IPs seen in last N days
        }
        """
        query = IPQuarantine.query

        if filters:
            if filters.get('status'):
                query = query.filter_by(status=filters['status'])
            
            if filters.get('threat_level'):
                query = query.filter_by(threat_level=filters['threat_level'])
            
            if filters.get('days'):
                since = datetime.utcnow() - timedelta(days=filters['days'])
                query = query.filter(IPQuarantine.first_seen >= since)

        return query.order_by(IPQuarantine.last_activity.desc()).all()

    @staticmethod
    def get_security_logs_for_ip(ip_address: str, limit: int = 100) -> list:
        """Get all security logs for a specific IP."""
        return SecurityLog.query.filter_by(
            ip_address=ip_address
        ).order_by(SecurityLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def approve_quarantine(ip_address: str, reviewed_by: str, action: str):
        """Approve a quarantined IP."""
        quarantine = IPQuarantine.query.filter_by(ip_address=ip_address).first()
        
        if quarantine:
            quarantine.status = 'approved'
            quarantine.reviewed_by = reviewed_by
            quarantine.reviewed_at = datetime.utcnow()
            quarantine.action_taken = action
            quarantine.is_resolved = True
            security_db.session.commit()

            # Create security event
            SecurityService.log_security_event(
                event_type='ip_approved',
                ip_address=ip_address,
                severity='low',
                description=f'IP approved by {reviewed_by}: {action}'
            )

    @staticmethod
    def reject_quarantine(ip_address: str, reviewed_by: str, reason: str):
        """Reject and blacklist a quarantined IP."""
        quarantine = IPQuarantine.query.filter_by(ip_address=ip_address).first()
        
        if quarantine:
            quarantine.status = 'rejected'
            quarantine.reviewed_by = reviewed_by
            quarantine.reviewed_at = datetime.utcnow()
            quarantine.action_taken = reason
            quarantine.is_resolved = True
            security_db.session.commit()

            # Add to blacklist
            SecurityService.blacklist_ip(
                ip_address=ip_address,
                reason=f"Rejected from quarantine: {reason}",
                blocked_by=reviewed_by,
                expires_at=datetime.utcnow() + timedelta(days=30)
            )

            # Create security event
            SecurityService.log_security_event(
                event_type='ip_blacklisted',
                ip_address=ip_address,
                severity='high',
                description=f'IP blacklisted by {reviewed_by}: {reason}'
            )

    @staticmethod
    def blacklist_ip(ip_address: str, reason: str, blocked_by: str, 
                    expires_at: datetime = None):
        """Add IP to permanent blacklist."""
        existing = IPBlacklist.query.filter_by(ip_address=ip_address).first()

        if existing:
            existing.reason = reason
            existing.blocked_by = blocked_by
            existing.created_at = datetime.utcnow()
            existing.expires_at = expires_at
            existing.is_active = True
        else:
            blacklist = IPBlacklist(
                ip_address=ip_address,
                reason=reason,
                blocked_by=blocked_by,
                expires_at=expires_at,
            )
            security_db.session.add(blacklist)

        security_db.session.commit()

    @staticmethod
    def whitelist_ip(ip_address: str):
        """Remove IP from blacklist."""
        blacklist = IPBlacklist.query.filter_by(ip_address=ip_address).first()
        
        if blacklist:
            blacklist.is_active = False
            security_db.session.commit()

    @staticmethod
    def log_security_event(event_type: str, ip_address: str, severity: str,
                          description: str, affected_resource: str = None):
        """Log a high-level security event."""
        event = SecurityEvent(
            event_type=event_type,
            ip_address=ip_address,
            severity=severity,
            description=description,
            app_instance=os.getenv('SHOWWISE_INSTANCE_NAME', 'default'),
            affected_resource=affected_resource,
        )
        security_db.session.add(event)
        security_db.session.commit()

    @staticmethod
    def get_security_events(filters: dict = None, limit: int = 100) -> list:
        """
        Get security events with optional filtering.
        
        filters: {
            'event_type': 'burp_detected',
            'severity': 'critical',
            'days': 7,
            'acknowledged': False
        }
        """
        query = SecurityEvent.query

        if filters:
            if filters.get('event_type'):
                query = query.filter_by(event_type=filters['event_type'])
            
            if filters.get('severity'):
                query = query.filter_by(severity=filters['severity'])
            
            if filters.get('days'):
                since = datetime.utcnow() - timedelta(days=filters['days'])
                query = query.filter(SecurityEvent.created_at >= since)
            
            if 'acknowledged' in filters:
                query = query.filter_by(is_acknowledged=filters['acknowledged'])

        return query.order_by(SecurityEvent.created_at.desc()).limit(limit).all()

    @staticmethod
    def acknowledge_security_event(event_id: int, acknowledged_by: str):
        """Mark security event as acknowledged."""
        event = SecurityEvent.query.get(event_id)
        
        if event:
            event.is_acknowledged = True
            event.acknowledged_at = datetime.utcnow()
            event.acknowledged_by = acknowledged_by
            security_db.session.commit()

    @staticmethod
    def get_whitelisted_ips() -> list:
        """Get all active IP whitelist entries (not expired blacklist)."""
        return IPBlacklist.query.filter_by(is_active=False).all()

    @staticmethod
    def get_active_blacklist() -> list:
        """Get all active blacklisted IPs."""
        return IPBlacklist.query.filter_by(is_active=True).all()
