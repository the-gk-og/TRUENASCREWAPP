"""routes/profile.py — User settings, profile picture, password change."""

import os
from datetime import datetime

from flask import (
    Blueprint, render_template, request, jsonify,
    send_from_directory,
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, TwoFactorAuth, OAuthConnection
from constants import ALLOWED_IMAGE_EXTENSIONS
from services.email_service import send_password_changed_email

profile_bp = Blueprint('profile', __name__)
UPLOAD_FOLDER = 'uploads'


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
    return render_template('crew/settings.html', tfa=tfa, google_conn=google_conn)


@profile_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'GET':
        return render_template('/crew/change_password.html')
    data             = request.json
    current_password = data.get('current_password')
    new_password     = data.get('new_password')
    confirm_password = data.get('confirm_password')
    if not all([current_password, new_password, confirm_password]):
        return jsonify({'error': 'All fields are required'}), 400
    if not check_password_hash(current_user.password_hash, current_password):
        return jsonify({'error': 'Current password is incorrect'}), 400
    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    if new_password != confirm_password:
        return jsonify({'error': 'New passwords do not match'}), 400
    if current_password == new_password:
        return jsonify({'error': 'New password must be different from current password'}), 400
    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    if current_user.email:
        send_password_changed_email(
            recipient_email=current_user.email, username=current_user.username,
            changed_at=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
        )
    return jsonify({'success': True, 'message': 'Password changed successfully'})


@profile_bp.route('/settings/update-account', methods=['POST'])
@login_required
def update_account_info():
    data = request.json
    if data.get('username') and data['username'] != current_user.username:
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already taken'}), 400
        if len(data['username']) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        current_user.username = data['username']
    if data.get('email') is not None:
        new_email = (data['email'] or '').strip() or None
        if new_email and new_email != current_user.email:
            if User.query.filter_by(email=new_email).first():
                return jsonify({'error': 'Email already in use'}), 400
        current_user.email = new_email
    if 'discord_id'       in data: current_user.discord_id       = (data['discord_id'] or '').strip() or None
    if 'discord_username' in data: current_user.discord_username = (data['discord_username'] or '').strip() or None
    try:
        db.session.commit()
        return jsonify({'success': True, 'username': current_user.username, 'email': current_user.email})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@profile_bp.route('/profile/picture/upload', methods=['POST'])
@login_required
def upload_profile_picture():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': 'Invalid file type'}), 400
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename  = f"{current_user.username}_{timestamp}.{ext}"
        users_dir = os.path.join(UPLOAD_FOLDER, 'users')
        os.makedirs(users_dir, exist_ok=True)
        if current_user.profile_picture:
            old = os.path.join(users_dir, current_user.profile_picture.split('/')[-1])
            if os.path.exists(old):
                try: os.remove(old)
                except Exception: pass
        file.save(os.path.join(users_dir, filename))
        current_user.profile_picture = f"users/{filename}"
        db.session.commit()
        return jsonify({'success': True, 'filename': filename,
                        'url': f"/profile/picture/{current_user.username}"})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@profile_bp.route('/profile/picture/<username>')
@login_required
def view_profile_picture(username):
    user = User.query.filter_by(username=username).first()
    if not user or not user.profile_picture:
        return '', 404
    try:
        return send_from_directory(UPLOAD_FOLDER, user.profile_picture)
    except Exception:
        return '', 404


@profile_bp.route('/profile/picture/delete', methods=['POST'])
@login_required
def delete_profile_picture():
    if current_user.profile_picture:
        old = os.path.join(UPLOAD_FOLDER, 'users', current_user.profile_picture.split('/')[-1])
        if os.path.exists(old):
            try: os.remove(old)
            except Exception: pass
        current_user.profile_picture = None
        db.session.commit()
    return jsonify({'success': True})


@profile_bp.route('/settings/link-discord', methods=['POST'])
@login_required
def link_discord():
    data = request.json
    discord_id       = data.get('discord_id')
    discord_username = data.get('discord_username')
    if discord_id is None and discord_username is None:
        current_user.discord_id = None
        current_user.discord_username = None
    elif not discord_id or not discord_username:
        return jsonify({'error': 'Required fields missing'}), 400
    else:
        current_user.discord_id       = discord_id
        current_user.discord_username = discord_username
    db.session.commit()
    return jsonify({'success': True})


@profile_bp.route('/settings/discord-status')
@login_required
def discord_status():
    if current_user.discord_id:
        return jsonify({'linked': True, 'discord_id': current_user.discord_id,
                        'discord_username': current_user.discord_username})
    return jsonify({'linked': False})


@profile_bp.route('/api/users', methods=['GET'])
@login_required
def api_list_users():
    users = User.query.filter(User.id != current_user.id).all()
    return jsonify({'success': True, 'users': [
        {'username': u.username, 'email': u.email} for u in users
    ]})
