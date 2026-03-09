"""
routes/profile.py
=================
User profile, settings, password change, picture upload/delete,
account info update, and Discord/Google unlink.
"""

import os
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, current_app,
)
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from extensions import db
from models import User, TwoFactorAuth, OAuthConnection, EmailOTP
from utils import get_organization, log_security_event

profile_bp = Blueprint('profile', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_PICTURE_SIZE   = 16 * 1024 * 1024   # 16 MB


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------

@profile_bp.route('/settings')
@login_required
def settings_page():
    tfa = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()

    google_conn = None
    try:
        google_conn = next(
            (c for c in current_user.oauth_connections if c.provider == 'google'), None
        )
    except Exception:
        pass

    email_otp = EmailOTP.query.filter_by(user_id=current_user.id).first()

    return render_template(
        'crew/settings.html',
        tfa=tfa,
        google_conn=google_conn,
        email_otp=email_otp,
    )


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

@profile_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    GET  – render standalone change-password page (cast members use this).
    POST – JSON API used by both the settings page and standalone page.
    """
    if request.method == 'GET':
        org = get_organization()
        return render_template('crew/change_password.html', organization=org)

    data             = request.json or {}
    current_password = (data.get('current_password') or '').strip()
    new_password     = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not current_password:
        return jsonify({'error': 'Current password is required'}), 400

    if not check_password_hash(current_user.password_hash, current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401

    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400

    if new_password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    if current_password == new_password:
        return jsonify({'error': 'New password must be different from your current password'}), 400

    try:
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        log_security_event('PASSWORD_CHANGED', username=current_user.username)

        # Send confirmation email if available
        if current_user.email:
            try:
                from services.email_service import send_password_changed_email
                send_password_changed_email(
                    recipient_email=current_user.email,
                    username=current_user.username,
                    changed_at=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                )
            except Exception:
                pass

        return jsonify({'success': True, 'message': 'Password changed successfully'}), 200

    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Profile picture
# ---------------------------------------------------------------------------

@profile_bp.route('/profile/picture/<username>')
@login_required
def serve_profile_picture(username):
    """Serve a user's profile picture."""
    from flask import send_file, abort
    user = User.query.filter_by(username=username).first_or_404()
    if not user.profile_picture:
        abort(404)
    pic_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users', user.profile_picture)
    if not os.path.exists(pic_path):
        abort(404)
    return send_file(pic_path)


@profile_bp.route('/profile/picture/upload', methods=['POST'])
@login_required
def upload_profile_picture():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not _allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Use PNG, JPG, GIF, or WebP'}), 400

    # Check size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_PICTURE_SIZE:
        return jsonify({'error': 'File too large (max 16 MB)'}), 400

    try:
        ext      = secure_filename(file.filename).rsplit('.', 1)[1].lower()
        filename = f"user_{current_user.id}_profile.{ext}"
        save_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'users')
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, filename)
        file.save(save_path)

        # Delete old picture if different filename
        if current_user.profile_picture and current_user.profile_picture != filename:
            old_path = os.path.join(save_dir, current_user.profile_picture)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        current_user.profile_picture = filename
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile picture updated'}), 200

    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@profile_bp.route('/profile/picture/delete', methods=['POST'])
@login_required
def delete_profile_picture():
    if not current_user.profile_picture:
        return jsonify({'error': 'No profile picture to delete'}), 400

    try:
        pic_path = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'users', current_user.profile_picture
        )
        if os.path.exists(pic_path):
            os.remove(pic_path)

        current_user.profile_picture = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile picture removed'}), 200

    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Account info update (username / email)
# ---------------------------------------------------------------------------

@profile_bp.route('/settings/update-account', methods=['POST'])
@login_required
def update_account_info():
    data     = request.json or {}
    username = (data.get('username') or '').strip() or None
    email    = (data.get('email') or '').strip() or None

    if not username and email is None:
        return jsonify({'error': 'Nothing to update'}), 400

    try:
        if username:
            if len(username) < 3:
                return jsonify({'error': 'Username must be at least 3 characters'}), 400
            existing = User.query.filter_by(username=username).first()
            if existing and existing.id != current_user.id:
                return jsonify({'error': 'That username is already taken'}), 400
            current_user.username = username

        if email is not None:
            if email == '':
                current_user.email = None
            else:
                existing = User.query.filter_by(email=email).first()
                if existing and existing.id != current_user.id:
                    return jsonify({'error': 'An account with that email already exists'}), 400
                current_user.email = email

        db.session.commit()
        log_security_event('ACCOUNT_INFO_UPDATED', username=current_user.username)
        return jsonify({'success': True}), 200

    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Discord unlink
# ---------------------------------------------------------------------------

@profile_bp.route('/settings/link-discord', methods=['POST'])
@login_required
def link_discord():
    data             = request.json or {}
    discord_id       = data.get('discord_id')
    discord_username = data.get('discord_username')

    try:
        current_user.discord_id       = discord_id or None
        current_user.discord_username = discord_username or None
        db.session.commit()
        log_security_event('DISCORD_UPDATED', username=current_user.username)
        return jsonify({'success': True}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Google unlink
# ---------------------------------------------------------------------------

@profile_bp.route('/auth/google/unlink', methods=['POST'])
@login_required
def google_unlink():
    data     = request.json or {}
    password = data.get('password', '')

    if not current_user.password_hash or not check_password_hash(current_user.password_hash, password):
        return jsonify({'error': 'Invalid password'}), 401

    conn = OAuthConnection.query.filter_by(
        user_id=current_user.id, provider='google'
    ).first()

    if not conn:
        return jsonify({'error': 'No Google account linked'}), 404

    try:
        db.session.delete(conn)
        db.session.commit()
        log_security_event('GOOGLE_UNLINK', username=current_user.username)
        return jsonify({'success': True}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500