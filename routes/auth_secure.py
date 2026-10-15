"""Enhanced Auth Routes with Security"""
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash
from services.security.security_utils import (
    get_client_ip, check_ip_blocked, report_to_security_backend,
    log_security_event, ThreatLevel, SecurityEvent, detect_malicious_patterns
)
from services.security.validation_chain import validate_and_sanitize
from security_integration import showwise_security_middleware, require_input_validation
from extensions import db
from models import User
import hmac
import hashlib

auth_secure_bp = Blueprint('auth_secure', __name__, url_prefix='/auth')


@auth_secure_bp.route('/login', methods=['POST'])
@showwise_security_middleware
def secure_login():
    """Enhanced login with security checks"""
    ip_address = get_client_ip()
    
    # Check IP status
    is_blocked, reason = check_ip_blocked(ip_address)
    if is_blocked:
        log_security_event(
            SecurityEvent.LOGIN_FAILED.value,
            ip_address=ip_address,
            severity=ThreatLevel.HIGH.value,
            description=f'Blocked IP login attempt: {reason}'
        )
        return jsonify({'error': 'Access denied', 'code': 'IP_BLOCKED'}), 403
    
    # Get and validate credentials
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    # Validate email format if email provided
    if '@' in username:
        sanitized, errors = validate_and_sanitize('email', username)
        if errors:
            return jsonify({'error': 'Invalid email format'}), 400
    else:
        sanitized, errors = validate_and_sanitize('username', username)
        if errors:
            return jsonify({'error': 'Invalid username format'}), 400
    
    username = sanitized
    
    # Check for malicious patterns
    threats = detect_malicious_patterns(password)
    if threats:
        log_security_event(
            SecurityEvent.MALICIOUS_PAYLOAD.value,
            ip_address=ip_address,
            severity=ThreatLevel.MEDIUM.value,
            description=f'Malicious pattern in password field: {threats}'
        )
        return jsonify({'error': 'Invalid login attempt'}), 400
    
    # Check rate limiting - allow multiple attempts but log
    attempt_count = session.get('login_attempts', 0)
    if attempt_count >= 5:
        log_security_event(
            'excessive_login_attempts',
            ip_address=ip_address,
            severity=ThreatLevel.HIGH.value,
            description=f'Excessive login attempts from IP: {username}'
        )
        report_to_security_backend(
            'brute_force_attempt',
            ip_address,
            threat_type='brute_force_attack',
            severity='high'
        )
        return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429
    
    # Perform authentication
    user = User.query.filter(
        (User.username == username) | (User.email == username)
    ).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        session['login_attempts'] = attempt_count + 1
        log_security_event(
            SecurityEvent.LOGIN_FAILED.value,
            ip_address=ip_address,
            username=username,
            severity=ThreatLevel.LOW.value,
            description=f'Failed login attempt (attempt {attempt_count + 1})'
        )
        report_to_security_backend(
            'login_failed',
            ip_address,
            threat_type='failed_auth',
            severity='low'
        )
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Check if user is suspended
    if hasattr(user, 'is_suspended') and user.is_suspended:
        log_security_event(
            'suspended_user_login_attempt',
            ip_address=ip_address,
            user_id=user.id,
            username=username,
            severity=ThreatLevel.MEDIUM.value
        )
        return jsonify({'error': 'Account suspended'}), 403
    
    # Check if 2FA is required
    if user.force_2fa_setup or (hasattr(user, 'two_factor_enabled') and user.two_factor_enabled):
        # Return 2FA required status
        session['pre_auth_user_id'] = user.id
        log_security_event(
            '2fa_required',
            ip_address=ip_address,
            user_id=user.id,
            username=username,
            severity=ThreatLevel.LOW.value
        )
        return jsonify({
            'status': '2fa_required',
            'message': 'Two-factor authentication required'
        }), 200
    
    # Successful login
    session.pop('login_attempts', None)
    log_security_event(
        SecurityEvent.LOGIN_SUCCESS.value,
        ip_address=ip_address,
        user_id=user.id,
        username=username,
        severity=ThreatLevel.LOW.value
    )
    
    # Return auth token or session
    return jsonify({
        'status': 'success',
        'message': 'Login successful',
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email
        }
    }), 200


@auth_secure_bp.route('/verify-2fa', methods=['POST'])
@showwise_security_middleware
def verify_2fa():
    """Verify 2FA code and complete login"""
    ip_address = get_client_ip()
    
    data = request.get_json()
    code = data.get('code', '').strip()
    user_id = session.get('pre_auth_user_id')
    
    if not user_id:
        return jsonify({'error': 'No login session'}), 400
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Invalid session'}), 400
    
    # Validate 2FA code (integrate with existing 2FA system)
    # This is pseudo-code - integrate with your actual 2FA verification
    
    log_security_event(
        'login_2fa_verified',
        ip_address=ip_address,
        user_id=user.id,
        username=user.username,
        severity=ThreatLevel.LOW.value
    )
    
    return jsonify({
        'status': 'success',
        'message': 'Login completed'
    }), 200


@auth_secure_bp.route('/logout', methods=['POST'])
@login_required
def secure_logout():
    """Secure logout with logging"""
    ip_address = get_client_ip()
    
    log_security_event(
        'user_logout',
        ip_address=ip_address,
        user_id=current_user.id,
        username=current_user.username,
        severity=ThreatLevel.LOW.value
    )
    
    session.clear()
    return jsonify({'status': 'success', 'message': 'Logged out'}), 200


@auth_secure_bp.route('/password-reset', methods=['POST'])
@showwise_security_middleware
def secure_password_reset():
    """Secure password reset request"""
    ip_address = get_client_ip()
    
    data = request.get_json()
    email = data.get('email', '').strip()
    
    # Validate email
    sanitized, errors = validate_and_sanitize('email', email)
    if errors:
        log_security_event(
            'password_reset_invalid_email',
            ip_address=ip_address,
            severity=ThreatLevel.LOW.value
        )
        return jsonify({'error': 'Invalid email format'}), 400
    
    email = sanitized
    
    # Find user
    user = User.query.filter_by(email=email).first()
    
    if user:
        # Generate reset token
        reset_token = hashlib.sha256(
            (str(user.id) + str(user.email)).encode()
        ).hexdigest()
        
        # Store in database (implement token storage)
        # user.password_reset_token = reset_token
        # db.session.commit()
        
        # Send email
        log_security_event(
            'password_reset_requested',
            ip_address=ip_address,
            user_id=user.id,
            severity=ThreatLevel.LOW.value
        )
    else:
        # For security, don't reveal whether email exists
        log_security_event(
            'password_reset_nonexistent_email',
            ip_address=ip_address,
            severity=ThreatLevel.LOW.value,
            description=f'Reset request for: {email}'
        )
    
    # Always return success message for security
    return jsonify({
        'status': 'success',
        'message': 'If the email exists, a reset link will be sent'
    }), 200


def register_secure_auth(app):
    """Register secure auth routes"""
    app.register_blueprint(auth_secure_bp)
