"""
routes/auth.py
==============
Login, signup, logout, password reset.
"""

import os
import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, session,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, TwoFactorAuth, InviteCode, EmailOTP
from utils import get_organization, generate_invite_code, log_security_event, hash_reset_token
from services.security import throttle
from constants import MIN_PASSWORD_LENGTH
from services.user_names import (
    find_user_by_login, username_taken, username_problem, email_taken, clean_display_name,
)
from constants import DEFAULT_ORG
from config import SESSION_DURATION
from services.email_service import (
    send_welcome_email, send_password_reset_email, send_password_changed_email,
)

auth_bp = Blueprint('auth', __name__)

SIGNUP_BASE_URL = os.environ.get('SIGNUP_BASE_URL', os.environ.get('MAIN_SERVER_URL', ''))
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')


# ---------------------------------------------------------------------------

@auth_bp.route('/')
def index():
    """Signed-in people go to their dashboard; everyone else goes to the login page."""
    if current_user.is_authenticated:
        return redirect(url_for('crew.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_cast:
            return redirect(url_for('cast.cast_events'))
        return redirect(url_for('crew.dashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        remember = request.form.get('remember', 'off') == 'on'

        ip = throttle.client_ip()
        if (throttle.is_blocked('login_ip', ip, 20, 900)
                or throttle.is_blocked('login_user', username.lower(), 5, 900)):
            log_security_event('LOGIN_THROTTLED', username=username, ip_address=ip)
            flash('Too many failed attempts. Please wait 15 minutes and try again.')
            org = get_organization() or DEFAULT_ORG
            return render_template('login.html', organization=org, SESSION_DURATION=SESSION_DURATION,
                                   now=datetime.now(), google_oauth_enabled=bool(GOOGLE_CLIENT_ID)), 429

        # Username or email, in any letter case
        user = find_user_by_login(username)

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            throttle.reset('login_user', username.lower())
            # --- TOTP 2FA check ---
            tfa = TwoFactorAuth.query.filter_by(user_id=user.id).first()
            if tfa and tfa.enabled:
                session['pending_2fa_user_id'] = user.id
                session['pending_2fa_remember'] = remember
                return redirect(url_for('tfa.totp_verify_page'))

            # --- Email OTP check ---
            email_otp_rec = EmailOTP.query.filter_by(user_id=user.id, enabled=True).first()
            if email_otp_rec:
                session['pending_2fa_user_id'] = user.id
                session['pending_2fa_remember'] = remember
                return redirect(url_for('email_otp.email_otp_verify_page'))

            # --- Forced 2FA setup check ---
            if getattr(user, 'force_2fa_setup', False) and (not tfa or not tfa.enabled):
                login_user(user, remember=remember)
                session['force_2fa_setup'] = True
                return redirect(url_for('tfa.forced_2fa_setup'))

            login_user(user, remember=remember)
            if remember:
                session.permanent = True

            return redirect(url_for('cast.cast_events') if user.is_cast else url_for('crew.dashboard'))

        throttle.record_failure('login_ip', ip)
        throttle.record_failure('login_user', username.lower())
        flash('Invalid username, email or password')

    org = get_organization() or DEFAULT_ORG
    return render_template(
        'login.html',
        organization=org,
        SESSION_DURATION=SESSION_DURATION,
        now=datetime.now(),
        google_oauth_enabled=bool(GOOGLE_CLIENT_ID),
    )


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('crew.dashboard'))

    org = get_organization() or DEFAULT_ORG
    prefill_code = request.args.get('invite', '').upper()

    if request.method == 'POST':
        invite_code_str  = request.form.get('invite_code', '').strip().upper()
        username         = request.form.get('username', '').strip()
        display_raw      = request.form.get('display_name', '')
        email            = (request.form.get('email', '').strip().lower()) or None
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        invite = InviteCode.query.filter_by(code=invite_code_str, is_active=True).first()

        if not invite:
            flash('Invalid or expired invite code.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        now = datetime.utcnow()
        if invite.expires_at < now:
            flash('This invite code has expired.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        if invite.max_uses > 0 and invite.use_count >= invite.max_uses:
            flash('This invite code has already been used the maximum number of times.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        problem = username_problem(username, minimum=3, maximum=40)
        if problem:
            flash(problem, 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        if username_taken(username):
            flash('That username is already taken.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        display_name, name_error = clean_display_name(display_raw)
        if name_error:
            flash(name_error, 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        if email and email_taken(email):
            flash('An account with that email already exists.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('signup.html', organization=org, prefill_code=invite_code_str)

        user_role = invite.role
        is_cast   = user_role == 'cast'

        new_user = User(
            username=username,
            display_name=display_name,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=False,
            is_cast=is_cast,
            user_role=user_role,
        )
        db.session.add(new_user)
        db.session.flush()

        invite.use_count += 1
        if invite.max_uses > 0 and invite.use_count >= invite.max_uses:
            invite.is_active = False
        invite.used_by_users.append(new_user)
        db.session.commit()

        if email:
            send_welcome_email(
                recipient_email=email,
                username=username,
                display_name=new_user.shown_name,
                user_role=user_role,
                login_url=request.url_root.rstrip('/') + '/login',
                org=org,
            )

        log_security_event('SIGNUP', username=username,
                           description=f'Signed up via invite code {invite_code_str}')
        login_user(new_user, remember=False)
        flash(f'Welcome, {new_user.shown_name}! Your account has been created.', 'success')
        return redirect(url_for('cast.cast_events') if is_cast else url_for('crew.dashboard'))

    return render_template('signup.html', organization=org, prefill_code=prefill_code)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@auth_bp.route('/password/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        org = get_organization() or DEFAULT_ORG
        return render_template('forgot_password.html', organization=org)

    data               = request.get_json(silent=True) or {}
    username_or_email  = (data.get('username_or_email') or '').strip()

    if not username_or_email:
        return jsonify({'error': 'Username or email required'}), 400

    # Same answer whether or not the account exists / has an email / mail works (no enumeration)
    generic = jsonify({'success': True, 'message': 'If that account exists, an email has been sent'}), 200

    ip = throttle.client_ip()
    if throttle.is_blocked('forgot_ip', ip, 5, 900):
        return jsonify({'error': 'Too many requests. Please try again later.'}), 429
    throttle.record_failure('forgot_ip', ip)

    user = find_user_by_login(username_or_email)
    if not user or not user.email:
        return generic

    try:
        reset_token              = secrets.token_urlsafe(32)
        user.password_reset_token  = hash_reset_token(reset_token)   # only the hash is stored
        user.password_reset_expiry = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

        reset_url = f"{SIGNUP_BASE_URL}/password/reset/{reset_token}"
        org       = get_organization() or DEFAULT_ORG

        sent = send_password_reset_email(
            recipient_email=user.email,
            username=user.username,
            reset_url=reset_url,
            org=org,
        )

        if sent:
            log_security_event('PASSWORD_RESET_REQUESTED', username=user.username)
        else:
            print('Password reset email could not be sent (check email configuration)')
        return generic

    except Exception as exc:
        db.session.rollback()
        print(f"Password forgot error: {exc}")
        return generic


@auth_bp.route('/password/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_hash = hash_reset_token(token)
    if request.method == 'GET':
        user = User.query.filter_by(password_reset_token=token_hash).first()
        if not user or not user.password_reset_expiry \
                or user.password_reset_expiry < datetime.utcnow():
            flash('Password reset link is invalid or has expired', 'error')
            return redirect(url_for('auth.login'))
        org = get_organization() or DEFAULT_ORG
        return render_template('reset_password.html', token=token, organization=org)

    data             = request.get_json(silent=True) or {}
    new_password     = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    user = User.query.filter_by(password_reset_token=token_hash).first()
    if not user:
        return jsonify({'error': 'Invalid reset token'}), 400

    if not user.password_reset_expiry or user.password_reset_expiry < datetime.utcnow():
        user.password_reset_token  = None
        user.password_reset_expiry = None
        db.session.commit()
        return jsonify({'error': 'Reset link has expired'}), 400

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Password must be at least {MIN_PASSWORD_LENGTH} characters'}), 400

    if new_password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    try:
        user.password_hash         = generate_password_hash(new_password)
        user.password_reset_token  = None
        user.password_reset_expiry = None
        db.session.commit()

        log_security_event('PASSWORD_RESET_COMPLETED', username=user.username)

        if user.email:
            send_password_changed_email(
                recipient_email=user.email,
                username=user.shown_name,
                changed_at=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
            )

        return jsonify({'success': True, 'redirect': url_for('auth.login')}), 200

    except Exception as exc:
        db.session.rollback()
        print(f'Password reset error: {exc}')
        return jsonify({'error': 'Could not reset password. Please try again.'}), 500


@auth_bp.route('/session-info')
@login_required
def session_info():
    return jsonify({
        'username':     current_user.username,
        'name':         current_user.shown_name,
        'is_permanent': session.permanent,
        'logged_in':    current_user.is_authenticated,
    })
    