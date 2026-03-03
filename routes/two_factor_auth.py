"""
routes/two_factor_auth.py
=========================
TOTP 2FA setup, verification, and management.
"""

import io, json, base64
import pyotp
import qrcode

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, session,
)
from flask_login import login_user, login_required, current_user
from werkzeug.security import check_password_hash

from extensions import db
from models import User, TwoFactorAuth
from utils import (
    generate_backup_codes, hash_backup_codes,
    verify_backup_code, log_security_event, get_organization,
)
from constants import DEFAULT_ORG

tfa_bp = Blueprint('tfa', __name__)


@tfa_bp.route('/login/2fa')
def totp_verify_page():
    if 'pending_2fa_user_id' not in session:
        return redirect(url_for('auth.login'))
    user = User.query.get(session['pending_2fa_user_id'])
    if not user:
        session.pop('pending_2fa_user_id', None)
        return redirect(url_for('auth.login'))
    org = get_organization() or DEFAULT_ORG
    return render_template('totp_verify.html', organization=org, username=user.username)


@tfa_bp.route('/settings/2fa')
@login_required
def totp_settings():
    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    return render_template('crew/totp_setting.html', tfa=tfa)


@tfa_bp.route('/settings/security')
@login_required
def security_settings():
    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    google_conn = None
    try:
        google_conn = next(
            (c for c in current_user.oauth_connections if c.provider == 'google'), None
        )
    except Exception:
        pass
    return render_template('crew/security_setup.html', tfa=tfa, google_conn=google_conn)


@tfa_bp.route('/settings/force-2fa-setup')
@login_required
def forced_2fa_setup():
    if not session.get('force_2fa_setup'):
        return redirect(url_for('crew.dashboard'))
    return render_template('forced_2fa_setup.html')


@tfa_bp.route('/api/2fa/complete-forced-setup', methods=['POST'])
@login_required
def complete_forced_2fa():
    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if tfa and tfa.enabled:
        current_user.force_2fa_setup = False
        session.pop('force_2fa_setup', None)
        db.session.commit()
        return jsonify({'success': True, 'redirect': url_for('crew.dashboard')})
    return jsonify({'error': '2FA not yet enabled'}), 400


@tfa_bp.route('/api/2fa/setup', methods=['POST'])
@login_required
def setup_totp():
    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if tfa and tfa.enabled:
        return jsonify({'error': '2FA is already enabled'}), 400

    secret = pyotp.random_base32()

    if not tfa:
        tfa = TwoFactorAuth(user_id=current_user.id, secret=secret, enabled=False)
        db.session.add(tfa)
    else:
        tfa.secret  = secret
        tfa.enabled = False
    db.session.commit()

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.username, issuer_name='ShowWise'
    )

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return jsonify({
        'success':         True,
        'secret':          secret,
        'qr_code':         f'data:image/png;base64,{qr_b64}',
        'provisioning_uri': provisioning_uri,
    })


@tfa_bp.route('/api/2fa/verify-setup', methods=['POST'])
@login_required
def verify_totp_setup():
    data = request.json
    code = (data.get('code') or '').strip()
    tfa  = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()

    if not tfa:
        return jsonify({'error': '2FA not initialized'}), 400

    totp = pyotp.TOTP(tfa.secret)
    if totp.verify(code, valid_window=1):
        tfa.enabled = True
        backup_codes = generate_backup_codes(10)
        tfa.backup_codes = json.dumps(hash_backup_codes(backup_codes))
        db.session.commit()
        log_security_event('2FA_ENABLED', username=current_user.username)
        return jsonify({'success': True, 'backup_codes': backup_codes})

    return jsonify({'error': 'Invalid code. Please try again.'}), 400


@tfa_bp.route('/api/2fa/verify-login', methods=['POST'])
def verify_totp_login():
    data      = request.json
    code      = (data.get('code') or '').strip()
    is_backup = data.get('is_backup', False)
    user_id   = session.get('pending_2fa_user_id')

    if not user_id:
        return jsonify({'error': 'No pending 2FA verification'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    tfa = TwoFactorAuth.query.filter_by(user_id=user.id).first()
    if not tfa or not tfa.enabled:
        return jsonify({'error': '2FA not enabled'}), 400

    verified = False
    if is_backup:
        backup_codes = json.loads(tfa.backup_codes) if tfa.backup_codes else []
        index = verify_backup_code(backup_codes, code)
        if index is not None:
            backup_codes.pop(index)
            tfa.backup_codes = json.dumps(backup_codes)
            db.session.commit()
            verified = True
    else:
        verified = pyotp.TOTP(tfa.secret).verify(code, valid_window=1)

    if verified:
        session.pop('pending_2fa_user_id', None)
        login_user(user, remember=session.pop('pending_2fa_remember', False))
        log_security_event('2FA_LOGIN_SUCCESS', username=user.username)
        return jsonify({
            'success':  True,
            'redirect': url_for('cast.cast_events') if user.is_cast else url_for('crew.dashboard'),
        })

    return jsonify({'error': 'Invalid code. Please try again.'}), 400


@tfa_bp.route('/api/2fa/disable', methods=['POST'])
@login_required
def disable_totp():
    data     = request.json
    password = data.get('password')
    if not check_password_hash(current_user.password_hash, password):
        return jsonify({'error': 'Invalid password'}), 401

    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
    if tfa:
        db.session.delete(tfa)
        db.session.commit()
        log_security_event('2FA_DISABLED', username=current_user.username)
        return jsonify({'success': True, 'message': '2FA disabled successfully'})

    return jsonify({'error': '2FA not enabled'}), 400


@tfa_bp.route('/api/settings/skip-2fa-oauth', methods=['POST'])
@login_required
def toggle_skip_2fa_oauth():
    enabled = bool(request.json.get('enabled', False))
    current_user.skip_2fa_for_oauth = enabled
    db.session.commit()
    log_security_event(
        '2FA_OAUTH_BYPASS_' + ('ENABLED' if enabled else 'DISABLED'),
        username=current_user.username,
    )
    return jsonify({'success': True, 'skip_2fa_for_oauth': current_user.skip_2fa_for_oauth})
