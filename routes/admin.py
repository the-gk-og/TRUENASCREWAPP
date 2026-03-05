"""routes/admin.py — Admin dashboard, users, backups, invites."""

import os, io, csv, shutil, json
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, jsonify,
    send_file, redirect, url_for, flash, Response,
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Event, Equipment, CrewAssignment, TwoFactorAuth,
    InviteCode, PickListItem,
)
from decorators import crew_required
from utils import generate_invite_code, log_security_event, get_organization
from constants import DEFAULT_ORG
from services.email_service import send_invite_email

admin_bp = Blueprint('admin', __name__)

SIGNUP_BASE_URL = os.environ.get('SIGNUP_BASE_URL', os.environ.get('MAIN_SERVER_URL', ''))


@admin_bp.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('crew.dashboard'))
    raw_users = User.query.all()
    users = []
    for user in raw_users:
        tfa = TwoFactorAuth.query.filter_by(user_id=user.id).first()
        users.append({
            'id': user.id, 'username': user.username, 'email': user.email,
            'is_cast': user.is_cast,
            'created_at': user.created_at.strftime('%b %d, %Y') if user.created_at else 'N/A',
            'discord_username': user.discord_username,
            'is_admin': user.is_admin, 'user_role': user.user_role,
            'tfa_enabled': bool(tfa and tfa.enabled),
            'force_2fa': getattr(user, 'force_2fa_setup', False),
        })
    return render_template('admin/admin.html', users=users)


@admin_bp.route('/admin/overview')
@login_required
@crew_required
def admin_overview():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('crew.dashboard'))
    now          = datetime.now()
    week_ago     = now - timedelta(days=7)
    upcoming     = Event.query.filter(Event.event_date >= now).order_by(Event.event_date).limit(10).all()
    active_crew  = db.session.query(CrewAssignment.crew_member).join(Event).filter(
        Event.event_date >= now).distinct().count()
    eq_usage     = db.session.query(Equipment.category,
                                     db.func.count(PickListItem.id).label('usage_count')
                                    ).outerjoin(PickListItem).group_by(Equipment.category).all()
    return render_template('/admin/admin_overview.html',
        total_users=User.query.count(),
        total_equipment=Equipment.query.count(),
        total_events=Event.query.count(),
        upcoming_events=upcoming,
        recent_users=User.query.filter(User.created_at >= week_ago).count(),
        recent_equipment=Equipment.query.filter(Equipment.created_at >= week_ago).count(),
        recent_events=Event.query.filter(Event.created_at >= week_ago).count(),
        active_crew=active_crew, equipment_usage=eq_usage,
    )


# Users CRUD
@admin_bp.route('/admin/users/add', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username exists'}), 400
    user_role = data.get('user_role', 'crew')
    user = User(
        username=data['username'], email=data.get('email'),
        password_hash=generate_password_hash(data['password']),
        is_admin=data.get('is_admin', False),
        is_cast=(user_role == 'cast'), user_role=user_role,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/admin/users/get/<int:id>', methods=['GET'])
@login_required
def get_user(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    user = User.query.get_or_404(id)
    return jsonify({
        'id': user.id, 'username': user.username, 'email': user.email or '',
        'discord_id': user.discord_id or '', 'discord_username': user.discord_username or '',
        'is_admin': user.is_admin, 'user_role': user.user_role,
    })


@admin_bp.route('/admin/users/edit/<int:id>', methods=['PUT'])
@login_required
def edit_user(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    user = User.query.get_or_404(id)
    data = request.json
    if data.get('username') and data['username'] != user.username:
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400
        user.username = data['username']
    if data.get('email') is not None:
        email = data['email'].strip() if data['email'] else None
        if email and email != user.email and User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already in use'}), 400
        user.email = email
    if 'discord_id' in data:
        user.discord_id       = (data['discord_id'] or '').strip() or None
        user.discord_username = (data.get('discord_username') or '').strip() or None
    if data.get('password') and len(data['password']) >= 6:
        user.password_hash = generate_password_hash(data['password'])
    if 'user_role' in data:
        user.user_role = data['user_role']
        user.is_cast   = (data['user_role'] == 'cast')
    if 'is_admin' in data:
        if id == current_user.id and not data['is_admin']:
            return jsonify({'error': 'Cannot remove your own admin privileges'}), 403
        user.is_admin = data['is_admin']
    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@admin_bp.route('/admin/users/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_user(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})


# 2FA admin controls
@admin_bp.route('/admin/users/<int:user_id>/force-2fa', methods=['POST'])
@login_required
def admin_force_2fa(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    user = User.query.get_or_404(user_id)
    user.force_2fa_setup = True
    db.session.commit()
    log_security_event('ADMIN_FORCE_2FA', username=current_user.username,
                       description=f'Forced 2FA setup for user {user.username}')
    return jsonify({'success': True})


@admin_bp.route('/admin/users/<int:user_id>/clear-force-2fa', methods=['POST'])
@login_required
def admin_clear_force_2fa(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    user = User.query.get_or_404(user_id)
    user.force_2fa_setup = False
    db.session.commit()
    return jsonify({'success': True})


# Backups
@admin_bp.route('/admin/backup', methods=['POST'])
@login_required
def backup_database():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    try:
        os.makedirs('backups', exist_ok=True)
        filename = f"production_crew_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy('production_crew.db', os.path.join('backups', filename))
        return jsonify({'success': True, 'filename': filename})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@admin_bp.route('/admin/download-backup/<filename>')
@login_required
def download_backup(filename):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    path = os.path.join('backups', filename)
    if not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404
    return send_file(path, as_attachment=True, download_name=filename,
                     mimetype='application/octet-stream')


@admin_bp.route('/admin/restore', methods=['POST'])
@login_required
def restore_database():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        request.files['file'].save('production_crew_restore.db')
        shutil.copy('production_crew_restore.db', 'production_crew.db')
        os.remove('production_crew_restore.db')
        return jsonify({'success': True, 'message': 'Database restored'})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@admin_bp.route('/admin/backups')
@login_required
def list_backups():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    os.makedirs('backups', exist_ok=True)
    backups = []
    for f in os.listdir('backups'):
        if f.endswith('.db'):
            path = os.path.join('backups', f)
            backups.append({
                'name': f, 'size': os.path.getsize(path),
                'date': datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            })
    return jsonify(backups)


# CSV export
@admin_bp.route('/admin/export-events')
@login_required
@crew_required
def export_events_csv():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Event Title', 'Date', 'Time', 'Location', 'Crew Member',
                     'Role', 'Email', 'Status'])
    now = datetime.now()
    for event in Event.query.order_by(Event.event_date).all():
        if event.crew_assignments:
            for a in event.crew_assignments:
                user = User.query.filter_by(username=a.crew_member).first()
                writer.writerow([
                    event.title, event.event_date.strftime('%Y-%m-%d'),
                    event.event_date.strftime('%I:%M %p'), event.location or 'N/A',
                    a.crew_member, a.role or 'Crew Member',
                    user.email if user and user.email else 'N/A',
                    'Upcoming' if event.event_date >= now else 'Past',
                ])
        else:
            writer.writerow([
                event.title, event.event_date.strftime('%Y-%m-%d'),
                event.event_date.strftime('%I:%M %p'), event.location or 'N/A',
                'No crew assigned', '', '',
                'Upcoming' if event.event_date >= now else 'Past',
            ])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=events_crew_{datetime.now().strftime("%Y%m%d")}.csv',
    })


# Invite codes
@admin_bp.route('/admin/invites')
@login_required
def list_invites():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    invites = InviteCode.query.order_by(InviteCode.created_at.desc()).all()
    return jsonify([{
        'id': inv.id, 'code': inv.code, 'role': inv.role,
        'created_by': inv.created_by,
        'created_at': inv.created_at.isoformat(),
        'expires_at': inv.expires_at.isoformat(),
        'max_uses': inv.max_uses, 'use_count': inv.use_count,
        'is_active': inv.is_active, 'note': inv.note,
        'used_by': [u.username for u in inv.used_by_users],
    } for inv in invites])


@admin_bp.route('/admin/invites/generate', methods=['POST'])
@login_required
def generate_invite():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    try:
        expires_at = datetime.fromisoformat(data['expires_at'])
    except (KeyError, ValueError):
        return jsonify({'error': 'Invalid expiry date'}), 400
    if expires_at <= datetime.utcnow():
        return jsonify({'error': 'Expiry must be in the future'}), 400
    code = generate_invite_code()
    while InviteCode.query.filter_by(code=code).first():
        code = generate_invite_code()
    invite = InviteCode(code=code, role=data.get('role', 'crew'),
                        created_by=current_user.username, expires_at=expires_at,
                        max_uses=int(data.get('max_uses', 1)), note=data.get('note', ''))
    db.session.add(invite)
    db.session.commit()
    return jsonify({'success': True, 'code': code, 'id': invite.id})


@admin_bp.route('/admin/invites/email', methods=['POST'])
@login_required
def email_invite():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data            = request.json
    recipient_email = (data.get('email') or '').strip()
    recipient_name  = (data.get('name') or '').strip() or 'there'
    if not recipient_email:
        return jsonify({'error': 'Email address required'}), 400
    try:
        expires_at = datetime.fromisoformat(data.get('expires_at', ''))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid expiry date'}), 400
    if expires_at <= datetime.utcnow():
        return jsonify({'error': 'Expiry must be in the future'}), 400
    code = generate_invite_code()
    while InviteCode.query.filter_by(code=code).first():
        code = generate_invite_code()
    invite = InviteCode(code=code, role=data.get('role', 'crew'),
                        created_by=current_user.username, expires_at=expires_at,
                        max_uses=1, note=f'Email invite to {recipient_email}')
    db.session.add(invite)
    db.session.commit()
    base_url   = (data.get('base_url') or SIGNUP_BASE_URL or request.url_root).rstrip('/')
    signup_url = f"{base_url}/signup?invite={code}"
    org        = get_organization() or DEFAULT_ORG
    sent = send_invite_email(
        recipient_email=recipient_email, recipient_name=recipient_name,
        signup_url=signup_url, invite_code=code,
        role_label=data.get('role', 'crew').capitalize(),
        expires_at=expires_at, org=org,
    )
    if not sent:
        return jsonify({'success': False, 'error': 'Email could not be sent.', 'code': code}), 500
    return jsonify({'success': True, 'code': code})


@admin_bp.route('/admin/invites/<int:invite_id>/revoke', methods=['POST'])
@login_required
def revoke_invite(invite_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    invite = InviteCode.query.get_or_404(invite_id)
    invite.is_active = False
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/admin/invites/<int:invite_id>', methods=['DELETE'])
@login_required
def delete_invite(invite_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    invite = InviteCode.query.get_or_404(invite_id)
    db.session.delete(invite)
    db.session.commit()
    return jsonify({'success': True})
