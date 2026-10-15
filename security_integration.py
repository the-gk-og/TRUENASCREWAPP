"""ShowWise Main App - Security Integration Module"""
from flask import request, jsonify, redirect, url_for
from functools import wraps
from services.security.security_utils import (
    get_client_ip, detect_scanner_user_agent, detect_malicious_patterns,
    check_ip_blocked, report_to_security_backend, log_security_event,
    ThreatLevel, SecurityEvent
)
from services.security.middleware import security_middleware, block_malicious_payload
from services.security.validation_chain import validate_and_sanitize


def showwise_security_middleware(f):
    """Enhanced security middleware for ShowWise main app"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip_address = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        
        # 1. Check for blocked IP
        is_blocked, block_reason = check_ip_blocked(ip_address)
        if is_blocked:
            log_security_event(
                SecurityEvent.FORM_SUBMISSION_BLOCKED.value,
                ip_address=ip_address,
                severity=ThreatLevel.HIGH.value,
                description=f'Blocked IP access attempt: {block_reason}'
            )
            return jsonify({
                'error': 'Access denied - Your IP has been blocked',
                'code': 'IP_BLOCKED',
                'message': 'Please contact support if you believe this is in error'
            }), 403
        
        # 2. Detect security scanners
        if detect_scanner_user_agent(user_agent):
            log_security_event(
                SecurityEvent.SCANNER_DETECTED.value,
                ip_address=ip_address,
                severity=ThreatLevel.CRITICAL.value,
                description=f'Security scanner detected: {user_agent}'
            )
            report_to_security_backend(
                'scanner_detected',
                ip_address,
                threat_type='security_scanner',
                severity='critical'
            )
            return jsonify({
                'error': 'Forbidden - Security scanner detected',
                'code': 'SCANNER_BLOCKED'
            }), 403
        
        # 3. Check request payload for malicious patterns
        if request.is_json:
            try:
                data = request.get_json(silent=True)
                if data:
                    threats = detect_malicious_patterns(str(data))
                    if threats:
                        log_security_event(
                            SecurityEvent.MALICIOUS_PAYLOAD.value,
                            ip_address=ip_address,
                            severity=ThreatLevel.CRITICAL.value,
                            description=f'Malicious payload detected: {", ".join([t["type"] for t in threats])}'
                        )
                        report_to_security_backend(
                            'malicious_payload',
                            ip_address,
                            threat_type='attack_payload',
                            severity='critical'
                        )
                        return jsonify({
                            'error': 'Request blocked - Malicious content detected',
                            'code': 'PAYLOAD_BLOCKED'
                        }), 400
            except Exception:
                pass
        
        # 4. Proceed to handler
        return f(*args, **kwargs)
    
    return decorated_function


def require_input_validation(field_validators):
    """Decorator to validate and sanitize specific form fields"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = get_client_ip()
            
            # Validate each field
            for field_name, field_type in field_validators.items():
                value = request.form.get(field_name) or (request.get_json() or {}).get(field_name)
                
                if value is None:
                    continue  # Skip optional fields
                
                sanitized, errors = validate_and_sanitize(field_type, value)
                
                if errors:
                    log_security_event(
                        'validation_failed',
                        ip_address=ip_address,
                        severity=ThreatLevel.MEDIUM.value,
                        description=f'Validation failed for {field_name}: {errors}'
                    )
                    return jsonify({
                        'error': f'Invalid {field_name}',
                        'details': errors
                    }), 400
                
                # Replace value with sanitized version in request context
                if request.is_json:
                    # For JSON requests, we'd need to handle this differently
                    pass
                else:
                    # For form data
                    request.form = request.form.copy()
                    request.form[field_name] = sanitized
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def audit_sensitive_action(action_name):
    """Decorator to audit sensitive operations"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = get_client_ip()
            user_id = getattr(request, 'user_id', None)
            username = getattr(request, 'username', None)
            
            result = f(*args, **kwargs)
            
            # Log after successful execution
            log_security_event(
                f'audit_{action_name}',
                ip_address=ip_address,
                user_id=user_id,
                username=username,
                severity=ThreatLevel.LOW.value,
                description=f'Action: {action_name}'
            )
            
            return result
        
        return decorated_function
    return decorator


def secure_api_endpoint(f):
    """Decorator combining all security checks for API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Apply all security checks
        @showwise_security_middleware
        @block_malicious_payload
        def wrapper():
            return f(*args, **kwargs)
        
        return wrapper()
    
    return decorated_function


# Security utilities for use in routes
def sanitize_form_data(form_data):
    """Sanitize all form data"""
    sanitized = {}
    for key, value in form_data.items():
        if isinstance(value, str):
            sanitized[key] = value.strip()
        else:
            sanitized[key] = value
    return sanitized
