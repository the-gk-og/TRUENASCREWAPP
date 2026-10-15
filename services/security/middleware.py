"""Security Middleware for Flask Apps"""
from flask import request, jsonify, current_app
from functools import wraps
from services.security.security_utils import (
    get_client_ip, detect_scanner_user_agent, detect_malicious_patterns,
    log_security_event, check_ip_blocked, report_to_security_backend,
    get_cloudflare_metadata, ThreatLevel, SecurityEvent
)


def security_middleware(f):
    """Main security middleware decorator for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip_address = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        
        # Check for blocked IP
        is_blocked, reason = check_ip_blocked(ip_address)
        if is_blocked:
            log_security_event(
                SecurityEvent.FORM_SUBMISSION_BLOCKED.value,
                ip_address=ip_address,
                severity=ThreatLevel.MEDIUM.value,
                description=f'Blocked IP attempted access: {reason}'
            )
            return jsonify({'error': 'Access denied', 'code': 'IP_BLOCKED'}), 403
        
        # Check for scanner
        if detect_scanner_user_agent(user_agent):
            log_security_event(
                SecurityEvent.SCANNER_DETECTED.value,
                ip_address=ip_address,
                severity=ThreatLevel.HIGH.value,
                description=f'Scanner detected: {user_agent}'
            )
            report_to_security_backend(
                'scanner_detected',
                ip_address,
                threat_type='security_scanner',
                severity='high',
                description=user_agent
            )
            return jsonify({'error': 'Forbidden', 'code': 'SCANNER_DETECTED'}), 403
        
        # Check Cloudflare threat score
        if current_app.config.get('CHECK_CLOUDFLARE_THREAT', True):
            cf_metadata = get_cloudflare_metadata()
            if cf_metadata.get('cf_threat_score'):
                try:
                    threat_score = int(cf_metadata['cf_threat_score'])
                    if threat_score > 50:
                        log_security_event(
                            'cf_threat_detected',
                            ip_address=ip_address,
                            severity=ThreatLevel.MEDIUM.value,
                            description=f'Cloudflare threat score: {threat_score}'
                        )
                except (ValueError, TypeError):
                    pass
        
        # Call the actual route handler
        return f(*args, **kwargs)
    
    return decorated_function


def block_malicious_payload(f):
    """Decorator to block requests with malicious payloads"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip_address = get_client_ip()
        
        # Check request data
        data = request.get_json(silent=True) or {}
        payload_str = str(data)
        
        threats = detect_malicious_patterns(payload_str)
        if threats:
            log_security_event(
                SecurityEvent.MALICIOUS_PAYLOAD.value,
                ip_address=ip_address,
                severity=ThreatLevel.HIGH.value,
                description=f'Malicious payload detected: {", ".join([t["type"] for t in threats])}',
                payload=payload_str[:200]
            )
            report_to_security_backend(
                'malicious_payload_detected',
                ip_address,
                threat_type='malicious_payload',
                severity='high',
                description=', '.join([t['type'] for t in threats])
            )
            return jsonify({
                'error': 'Request blocked',
                'code': 'MALICIOUS_PAYLOAD',
                'threats': [t['type'] for t in threats]
            }), 400
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_audit_logging(event_name):
    """Decorator to log audit events"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = get_client_ip()
            result = f(*args, **kwargs)
            
            # Log successful completion
            log_security_event(
                event_name,
                ip_address=ip_address,
                severity=ThreatLevel.LOW.value,
                description=f'Event: {event_name}'
            )
            
            return result
        return decorated_function
    return decorator
