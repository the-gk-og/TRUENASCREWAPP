"""
routes/oauth.py
===============
Google OAuth login and account linking.
"""

import os
from datetime import datetime

from flask import (
    Blueprint, redirect, url_for, flash, request, jsonify, session,
)
from flask_login import login_user, login_required, current_user
from werkzeug.security import check_password_hash

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow

from extensions import db
from models import User, OAuthConnection, TwoFactorAuth
from utils import log_security_event

oauth_bp = Blueprint('oauth', __name__)

GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI  = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5001/auth/google/callback')

_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

def _flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        },
        scopes=_SCOPES,
    )


@oauth_bp.route('/auth/google')
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash('Google OAuth is not configured')
        return redirect(url_for('auth.login') if not current_user.is_authenticated
                        else url_for('tfa.security_settings'))

    f = _flow()
    f.redirect_uri = GOOGLE_REDIRECT_URI
    authorization_url, state = f.authorization_url(
        access_type='offline', include_granted_scopes='true', prompt='consent'
    )
    session['oauth_state'] = state
    return redirect(authorization_url)


@oauth_bp.route('/auth/google/link')
@login_required
def google_link_initiate():
    existing = OAuthConnection.query.filter_by(
        user_id=current_user.id, provider='google'
    ).first()
    if existing:
        flash('Google account already linked. Unlink it first to link a different account.')
        return redirect(url_for('tfa.security_settings'))
    return redirect(url_for('oauth.google_login'))


@oauth_bp.route('/auth/google/callback')
def google_callback():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash('Google OAuth is not configured')
        return redirect(url_for('auth.login'))

    state = session.get('oauth_state')
    if not state or state != request.args.get('state'):
        flash('Invalid OAuth state')
        return redirect(url_for('auth.login'))

    error = request.args.get('error')
    if error:
        flash(f'Google login failed: {request.args.get("error_description", error)}')
        return redirect(url_for('auth.login') if not current_user.is_authenticated
                        else url_for('profile.settings_page'))

    is_linking = current_user.is_authenticated

    try:
        f = _flow()
        f.redirect_uri = GOOGLE_REDIRECT_URI
        f.state = state
        f.fetch_token(authorization_response=request.url)
        credentials = f.credentials

        if not credentials or not credentials.id_token:
            flash('Google login failed: No credentials received')
            return redirect(url_for('profile.settings_page') if is_linking else url_for('auth.login'))

        idinfo        = id_token.verify_oauth2_token(
            credentials.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        google_user_id = idinfo['sub']
        email          = idinfo.get('email')

        # ---- LINKING FLOW ----
        if is_linking:
            existing = OAuthConnection.query.filter_by(
                provider='google', provider_user_id=google_user_id
            ).first()
            if existing:
                msg = ('This Google account is already linked to your account'
                       if existing.user_id == current_user.id
                       else 'This Google account is already linked to another account')
                flash(msg)
                return redirect(url_for('profile.settings_page'))

            conn = OAuthConnection(
                user_id=current_user.id, provider='google',
                provider_user_id=google_user_id, email=email,
                access_token=credentials.token, refresh_token=credentials.refresh_token,
                token_expiry=credentials.expiry, last_login=datetime.utcnow(),
            )
            db.session.add(conn)
            db.session.commit()
            log_security_event('GOOGLE_LINK', username=current_user.username)
            flash('✓ Google account linked successfully!')
            return redirect(url_for('profile.settings_page'))

        # ---- LOGIN FLOW ----
        conn = OAuthConnection.query.filter_by(
            provider='google', provider_user_id=google_user_id
        ).first()

        if conn:
            user = conn.user
            conn.access_token   = credentials.token
            conn.refresh_token  = credentials.refresh_token
            conn.token_expiry   = credentials.expiry
            conn.last_login     = datetime.utcnow()
            db.session.commit()

            tfa      = TwoFactorAuth.query.filter_by(user_id=user.id).first()
            skip_2fa = getattr(user, 'skip_2fa_for_oauth', False)
            if tfa and tfa.enabled and not skip_2fa:
                session['pending_2fa_user_id'] = user.id
                session['pending_2fa_remember'] = False
                return redirect(url_for('tfa.totp_verify_page'))

            login_user(user, remember=False)
            log_security_event('GOOGLE_LOGIN', username=user.username)
            flash(f'Welcome back, {user.username}!')
            return redirect(url_for('cast.cast_events') if user.is_cast else url_for('crew.dashboard'))

        # Unknown Google ID — try email match
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            conn = OAuthConnection(
                user_id=existing_user.id, provider='google',
                provider_user_id=google_user_id, email=email,
                access_token=credentials.token, refresh_token=credentials.refresh_token,
                token_expiry=credentials.expiry, last_login=datetime.utcnow(),
            )
            db.session.add(conn)
            db.session.commit()
            login_user(existing_user, remember=False)
            log_security_event('GOOGLE_LOGIN', username=existing_user.username)
            flash(f'Google account linked and signed in, {existing_user.username}!')
            return redirect(url_for('cast.cast_events') if existing_user.is_cast
                            else url_for('crew.dashboard'))

        flash('No ShowWise account found for that Google account. '
              'Please sign up with an invite code first, then link Google from your settings.')
        return redirect(url_for('auth.login'))

    except Exception as exc:
        import traceback
        print(f"Google OAuth error: {exc}\n{traceback.format_exc()}")
        flash(f'Google login failed: {str(exc)[:100]}')
        return redirect(url_for('profile.settings_page') if is_linking else url_for('auth.login'))


@oauth_bp.route('/auth/google/unlink', methods=['POST'])
@login_required
def google_unlink():
    data     = request.json
    password = data.get('password')
    if current_user.password_hash and not check_password_hash(current_user.password_hash, password):
        return jsonify({'error': 'Invalid password'}), 401

    conn = OAuthConnection.query.filter_by(user_id=current_user.id, provider='google').first()
    if conn:
        db.session.delete(conn)
        db.session.commit()
        log_security_event('GOOGLE_UNLINK', username=current_user.username)
        return jsonify({'success': True, 'message': 'Google account unlinked'})

    return jsonify({'error': 'Google account not linked'}), 400
