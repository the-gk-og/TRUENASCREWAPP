"""Shared Security Utilities"""
import re
import hashlib
import hmac
import bleach
from datetime import datetime
from flask import request, current_app, jsonify
import requests
from enum import Enum

# Sanitization whitelist
ALLOWED_TAGS = ['b', 'i', 'u', 'em', 'strong', 'a', 'p', 'br']
ALLOWED_ATTRIBUTES = {'a': ['href', 'title']}


class ThreatLevel(Enum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


class SecurityEvent(Enum):
    """Security event types for logging"""
    LOGIN_ATTEMPT = 'login_attempt'
    MALICIOUS_PAYLOAD = 'malicious_payload'
    RATE_LIMIT_HIT = 'rate_limit_hit'
    SCANNER_DETECTED = 'scanner_detected'
    FORM_SUBMISSION_BLOCKED = 'form_submission_blocked'
    SUCCESSFUL_AUTH = 'successful_auth'
    FAILED_AUTH = 'failed_auth'


def get_client_ip():
    """Get real client IP from Cloudflare or other proxies"""
    # Cloudflare: CF-Connecting-IP
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')
    
    # Standard proxy headers
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    
    # Fallback to remote address
    return request.remote_addr


def get_cloudflare_metadata():
    """Extract Cloudflare metadata from headers"""
    return {
        'cf_ray': request.headers.get('CF-Ray'),
        'cf_connecting_ip': request.headers.get('CF-Connecting-IP'),
        'cf_country': request.headers.get('CF-IPCountry'),
        'cf_threat_score': request.headers.get('CF-Threat-Score'),
        'cf_bot_score': request.headers.get('CF-Bot-Score'),
        'cf_bot_management': request.headers.get('CF-Bot-Management-Score'),
    }


def detect_scanner_user_agent(user_agent):
    """Detect known security scanners in user agent"""
    scanner_patterns = [
        r'burpsuite',
        r'sqlmap',
        r'acunetix',
        r'nikto',
        r'nessus',
        r'nmap',
        r'masscan',
        r'metasploit',
        r'zap\b',
        r'openvas',
        r'w3af',
        r'dirbuster',
        r'appscan',
        r'skipfish',
        r'sqlninja',
        r'paros',
        r'vega\b',
        r'commix',
        r'xsser',
        r'nuclei',
        r'subfinder',
        r'gobuster',
        r'hydra\b',
        r'hashcat',
        r'john\b',
        r'sqlsus',
        r'webscarab',
        r'ratproxy',
        r'httptunnel',
        r'ipv6-scanner',
        r'ncrack',
        r'thc-ssl-dos',
    ]
    
    if not user_agent:
        return False
    
    user_agent_lower = user_agent.lower()
    return any(re.search(pattern, user_agent_lower) for pattern in scanner_patterns)


def detect_malicious_patterns(data):
    """Detect common attack patterns in data"""
    threats = []
    
    # SQL Injection patterns
    sql_patterns = [
        r"('\s*(or|and)\s*'?|\"\\*(\s*(or|and)\s*)?\")",
        r"(union|select|insert|update|delete|drop|create|alter|exec|execute|script|javascript|eval)",
        r"(;\s*(drop|delete|update|insert|create|alter))",
        r"(-{2}|/\*|\*\/|xp_|sp_)",
    ]
    
    # XSS patterns
    xss_patterns = [
        r'<\s*script[^>]*>',
        r'javascript\s*:',
        r'on\w+\s*=',
        r'<\s*iframe',
        r'<\s*embed',
        r'<\s*object',
        r'eval\s*\(',
        r'expression\s*\(',
    ]
    
    # Command Injection patterns
    cmd_patterns = [
        r'[;&|`$(){}[\]\\]',
        r'(bash|sh|cmd|powershell)\s*(',
    ]
    
    data_lower = str(data).lower()
    
    for pattern in sql_patterns:
        if re.search(pattern, data_lower, re.IGNORECASE):
            threats.append({'type': 'SQL_INJECTION', 'pattern': pattern})
    
    for pattern in xss_patterns:
        if re.search(pattern, data_lower, re.IGNORECASE):
            threats.append({'type': 'XSS', 'pattern': pattern})
    
    for pattern in cmd_patterns:
        if re.search(pattern, str(data)):
            threats.append({'type': 'COMMAND_INJECTION', 'pattern': pattern})
    
    return threats


def sanitize_input(data, allow_html=False):
    """Sanitize user input to prevent attacks"""
    if isinstance(data, str):
        # Remove excessive whitespace
        data = ' '.join(data.split())
        
        # If HTML is allowed, use bleach to sanitize
        if allow_html:
            data = bleach.clean(data, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
        else:
            # Escape HTML entities
            data = bleach.clean(data, tags=[], strip=True)
        
        return data.strip()
    
    elif isinstance(data, dict):
        return {k: sanitize_input(v, allow_html) for k, v in data.items()}
    
    elif isinstance(data, list):
        return [sanitize_input(item, allow_html) for item in data]
    
    return data


def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def hash_string(s):
    """Hash a string"""
    return hashlib.sha256(s.encode()).hexdigest()


def generate_hmac_signature(data, secret):
    """Generate HMAC signature for cross-service communication"""
    return hmac.new(
        secret.encode(),
        data.encode() if isinstance(data, str) else data,
        hashlib.sha256
    ).hexdigest()


def report_to_security_backend(event_type, ip_address, threat_type=None, severity='medium', description=None, service=None):
    """Report security event to central security backend"""
    try:
        backend_url = current_app.config.get('SECURITY_BACKEND_URL', 'http://localhost:5001')
        api_key = current_app.config.get('API_INTEGRATION_KEY', '')
        
        if not api_key or not backend_url:
            return False
        
        # Prepare event data
        event_data = {
            'event_type': event_type,
            'ip_address': ip_address,
            'threat_type': threat_type,
            'severity': severity,
            'description': description,
            'service': service or current_app.config.get('APP_INSTANCE_NAME', 'main'),
            'user_agent': request.headers.get('User-Agent'),
            'cloudflare_ray': request.headers.get('CF-Ray'),
        }
        
        headers = {
            'X-API-Key': api_key,
            'Content-Type': 'application/json',
        }
        
        # Send to backend
        response = requests.post(
            f'{backend_url}/api/ip/report-threat',
            json=event_data,
            headers=headers,
            timeout=5
        )
        
        return response.status_code == 201
    except Exception as e:
        current_app.logger.error(f'Failed to report to security backend: {str(e)}')
        return False


def check_ip_blocked(ip_address):
    """Check if IP is blocked in central security backend"""
    try:
        backend_url = current_app.config.get('SECURITY_BACKEND_URL', 'http://localhost:5001')
        api_key = current_app.config.get('API_INTEGRATION_KEY', '')
        
        if not api_key or not backend_url:
            return False, None
        
        headers = {'X-API-Key': api_key}
        
        response = requests.get(
            f'{backend_url}/api/ip/status/{ip_address}',
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            is_blocked = data.get('is_blocked', False) or data.get('is_quarantined', False)
            reason = data.get('reason') or data.get('block_reason')
            return is_blocked, reason
    except Exception as e:
        current_app.logger.error(f'Failed to check IP status: {str(e)}')
    
    return False, None


def rate_limit_check(ip_address, endpoint, limit=10, window=3600):
    """Check rate limit for IP on specific endpoint"""
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    
    # This is handled by Flask-Limiter decorator at route level
    pass


def log_security_event(event_type, ip_address=None, user_id=None, username=None, 
                       severity=ThreatLevel.LOW.value, description=None, payload=None):
    """Log security event"""
    if ip_address is None:
        ip_address = get_client_ip()
    
    try:
        backend_url = current_app.config.get('SECURITY_BACKEND_URL', 'http://localhost:5001')
        api_key = current_app.config.get('API_INTEGRATION_KEY', '')
        
        if not api_key or not backend_url:
            return False
        
        event_data = {
            'event_type': event_type,
            'ip_address': ip_address,
            'user_id': user_id,
            'username': username,
            'threat_severity': severity,
            'threat_description': description,
            'payload': str(payload)[:500] if payload else None,
            'service': current_app.config.get('APP_INSTANCE_NAME', 'main'),
            'endpoint': request.endpoint,
            'method': request.method,
            'http_status': 200,
        }
        
        headers = {'X-API-Key': api_key}
        
        requests.post(
            f'{backend_url}/api/events/log',
            json=event_data,
            headers=headers,
            timeout=5
        )
        
        return True
    except Exception as e:
        current_app.logger.error(f'Failed to log security event: {str(e)}')
        return False
