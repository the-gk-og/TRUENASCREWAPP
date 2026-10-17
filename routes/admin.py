"""
routes/admin.py
===============
Admin Console: one page (/admin) with tabs

    Overview       what needs attention: pending / declined shifts, upcoming events
    Users          add, edit, delete, roles, 2FA
    Invites        invite codes, email invites, QR / poster
    Notifications  who is emailed when a shift is declined
    Data           backups, restore, CSV export, equipment import

Every endpoint is admin-only.  JSON endpoints answer 403 JSON; the page redirects.
"""

import csv
import io
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint, render_template, request, jsonify, send_file, redirect,
    url_for, flash, Response, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Event, Equipment, CrewAssignment, TwoFactorAuth, InviteCode, PickListItem,
    Shift, ShiftAssignment, TodoItem, UserUnavailability, RecurringUnavailability,
    EmailOTP, OAuthConnection, CastMember,
)
from utils import generate_invite_code, log_security_event, get_organization
from services.user_names import (
    clean_display_name, username_problem, username_taken, email_taken,
    rename_user_references, sync_cast_names, name_for,
)
from constants import DEFAULT_ORG, USER_ROLES
from services.email_service import send_invite_email, send_html_email
from services.settings_service import get_setting, set_setting
from services.shift_notifications import build_decline_email

admin_bp = Blueprint('admin', __name__)

SIGNUP_BASE_URL = os.environ.get('SIGNUP_BASE_URL', os.environ.get('MAIN_SERVER_URL', ''))
BACKUP_DIR = 'backups'
_BACKUP_NAME = re.compile(r'^[A-Za-z0-9_.-]+\.db$')
_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def admin_api(f):
    """Admin-only JSON endpoint."""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return wrapper


def err(message, status=400):
    return jsonify({'error': message}), status


def serialize_user(user: User, tfa=None) -> dict:
    if tfa is None:
        tfa = TwoFactorAuth.query.filter_by(user_id=user.id).first()
    return {
        'id': user.id, 'username': user.username, 'name': user.shown_name,
        'display_name': user.display_name or '', 'email': user.email or '',
        'user_role': user.user_role or 'crew', 'is_admin': bool(user.is_admin),
        'is_cast': bool(user.is_cast),
        'discord_username': user.discord_username or '',
        'created_at': user.created_at.strftime('%d %b %Y') if user.created_at else '',
        'tfa_enabled': bool(tfa and tfa.enabled),
        'force_2fa': bool(getattr(user, 'force_2fa_setup', False)),
    }


def serialize_invite(inv: InviteCode) -> dict:
    now = datetime.utcnow()
    if not inv.is_active:
        state = 'revoked'
    elif inv.expires_at <= now:
        state = 'expired'
    elif inv.use_count >= (inv.max_uses or 1):
        state = 'used'
    else:
        state = 'active'
    return {
        'id': inv.id, 'code': inv.code, 'role': inv.role, 'created_by': name_for(inv.created_by),
        'created_at': inv.created_at.isoformat(), 'expires_at': inv.expires_at.isoformat(),
        'max_uses': inv.max_uses, 'use_count': inv.use_count, 'is_active': inv.is_active,
        'note': inv.note or '', 'used_by': [u.shown_name for u in inv.used_by_users], 'state': state,
    }


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@admin_bp.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('crew.dashboard'))
    now = datetime.now()
    week_ago = now - timedelta(days=7)

    upcoming = (Event.query.filter(Event.event_date >= now - timedelta(hours=3))
                .order_by(Event.event_date).limit(8).all())
    soon = now + timedelta(days=14)
    unstaffed = [e for e in upcoming if e.event_date <= soon and not e.crew_assignments]

    live = (db.session.query(ShiftAssignment, Shift, Event, User)
            .join(Shift, ShiftAssignment.shift_id == Shift.id)
            .join(Event, Shift.event_id == Event.id)
            .join(User, ShiftAssignment.user_id == User.id)
            .filter(Shift.shift_end_date >= now))
    pending = live.filter(ShiftAssignment.status == 'pending').order_by(Shift.shift_date).all()
    declined = (live.filter(ShiftAssignment.status == 'rejected')
                .order_by(ShiftAssignment.responded_at.desc()).limit(10).all())

    def row(a, s, e, u):
        return {'assignment_id': a.id, 'username': u.username, 'name': u.shown_name, 'event_id': e.id, 'event': e.title,
                'role': s.role or 'Shift', 'start': s.shift_date, 'end': s.shift_end_date,
                'reason': a.decline_reason or '', 'responded': a.responded_at}

    users = User.query.order_by(User.username).all()
    tfa = {t.user_id: t for t in TwoFactorAuth.query.all()}
    return render_template(
        'admin/admin.html',
        users=[serialize_user(u, tfa.get(u.id)) for u in users],
        stats={
            'users': len(users), 'users_week': User.query.filter(User.created_at >= week_ago).count(),
            'crew': sum(1 for u in users if not u.is_cast), 'cast': sum(1 for u in users if u.is_cast),
            'events_upcoming': Event.query.filter(Event.event_date >= now).count(),
            'events_week': Event.query.filter(Event.created_at >= week_ago).count(),
            'equipment': Equipment.query.count(),
            'pending': len(pending), 'declined': len(declined),
        },
        upcoming=[{'id': e.id, 'title': e.title, 'start': e.event_date, 'location': e.location or '',
                   'crew': len(e.crew_assignments)} for e in upcoming],
        unstaffed=[e.id for e in unstaffed],
        pending=[row(*r) for r in pending[:8]],
        declined=[row(*r) for r in declined],
        mail_configured=bool(current_app.config.get('MAIL_USERNAME')),
        signup_base_url=SIGNUP_BASE_URL, roles=USER_ROLES,
        now=now,
    )


@admin_bp.route('/admin/overview')
@login_required
def admin_overview():
    """Old URL - the overview is now the first tab of the console."""
    return redirect(url_for('admin.admin_panel') + '#overview')


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _validate_user_fields(data: dict, user: User | None = None):
    """Return (clean_dict, error)."""
    out = {}
    if 'username' in data or user is None:
        name = str(data.get('username') or '').strip()
        problem = username_problem(name, minimum=2, maximum=80)
        if problem:
            return None, problem
        if username_taken(name, exclude_id=user.id if user else None):
            return None, 'That username is already taken'
        out['username'] = name
    if 'display_name' in data:
        display, problem = clean_display_name(data.get('display_name'))
        if problem:
            return None, problem
        out['display_name'] = display
    if 'email' in data:
        email = (str(data.get('email') or '').strip().lower()) or None
        if email:
            if not _EMAIL.match(email):
                return None, 'That email address does not look valid'
            if email_taken(email, exclude_id=user.id if user else None):
                return None, 'That email is already used by another account'
        out['email'] = email
    if 'user_role' in data:
        role = data.get('user_role')
        if role not in USER_ROLES:
            return None, 'Unknown role'
        out['user_role'] = role
    pw = data.get('password')
    if pw:
        if len(pw) < 6:
            return None, 'Password must be at least 6 characters'
        out['password'] = pw
    elif user is None:
        return None, 'A password is required'
    return out, None


@admin_bp.route('/admin/api/users')
@admin_api
def api_users():
    tfa = {t.user_id: t for t in TwoFactorAuth.query.all()}
    return jsonify([serialize_user(u, tfa.get(u.id)) for u in User.query.order_by(User.username).all()])


@admin_bp.route('/admin/users/add', methods=['POST'])
@admin_api
def add_user():
    data = request.get_json(silent=True) or {}
    clean, problem = _validate_user_fields(data)
    if problem:
        return err(problem)
    role = clean.get('user_role', 'crew')
    user = User(username=clean['username'], display_name=clean.get('display_name'), email=clean.get('email'),
                password_hash=generate_password_hash(clean['password']),
                is_admin=bool(data.get('is_admin', False)) and role != 'cast',
                is_cast=(role == 'cast'), user_role=role)
    db.session.add(user)
    db.session.commit()
    log_security_event('ADMIN_ADD_USER', username=current_user.username,
                       description=f'Created user {user.username} ({role})')
    return jsonify({'success': True, 'user': serialize_user(user)})


@admin_bp.route('/admin/users/get/<int:id>')
@admin_api
def get_user(id):
    user = User.query.get_or_404(id)
    return jsonify({**serialize_user(user), 'discord_id': user.discord_id or ''})


@admin_bp.route('/admin/users/edit/<int:id>', methods=['PUT'])
@admin_api
def edit_user(id):
    user = User.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    clean, problem = _validate_user_fields(data, user)
    if problem:
        return err(problem)
    if 'is_admin' in data and id == current_user.id and not data['is_admin']:
        return err('You cannot remove your own admin access', 403)
    if 'username' in clean and clean['username'] != user.username:
        old_username = user.username
        user.username = clean['username']
        rename_user_references(old_username, user.username)     # keep their shifts, notes, events attached
    if 'display_name' in clean:
        user.display_name = clean['display_name']
        db.session.flush()
        sync_cast_names(user)
    if 'email' in clean:
        user.email = clean['email']
    if 'user_role' in clean:
        user.user_role = clean['user_role']
        user.is_cast = clean['user_role'] == 'cast'
    if 'password' in clean:
        user.password_hash = generate_password_hash(clean['password'])
    if 'is_admin' in data:
        user.is_admin = bool(data['is_admin']) and not user.is_cast
    if 'discord_id' in data:
        user.discord_id = (data.get('discord_id') or '').strip() or None
        user.discord_username = (data.get('discord_username') or '').strip() or None
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return err(str(exc), 500)
    return jsonify({'success': True, 'user': serialize_user(user)})


@admin_bp.route('/admin/users/delete/<int:id>', methods=['DELETE'])
@admin_api
def delete_user(id):
    if id == current_user.id:
        return err('You cannot delete yourself')
    user = User.query.get_or_404(id)
    try:
        # Remove everything that points at this user first (none of it cascades)
        for a in ShiftAssignment.query.filter_by(user_id=id).all():
            shift = a.shift
            db.session.delete(a)
            db.session.flush()
            db.session.refresh(shift)
            if not shift.assignments and not shift.is_open:
                db.session.delete(shift)
        CrewAssignment.query.filter_by(crew_member=user.username).delete()
        for model in (TodoItem, UserUnavailability, RecurringUnavailability, TwoFactorAuth, EmailOTP, OAuthConnection):
            model.query.filter_by(user_id=id).delete()
        CastMember.query.filter_by(user_id=id).update({'user_id': None})
        user.invite_code = []
        db.session.delete(user)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return err(f'Could not delete user: {exc}', 500)
    log_security_event('ADMIN_DELETE_USER', username=current_user.username,
                       description=f'Deleted user {user.username}')
    return jsonify({'success': True})


@admin_bp.route('/admin/users/<int:user_id>/force-2fa', methods=['POST'])
@admin_api
def admin_force_2fa(user_id):
    user = User.query.get_or_404(user_id)
    user.force_2fa_setup = True
    db.session.commit()
    log_security_event('ADMIN_FORCE_2FA', username=current_user.username,
                       description=f'Forced 2FA setup for user {user.username}')
    return jsonify({'success': True})


@admin_bp.route('/admin/users/<int:user_id>/clear-force-2fa', methods=['POST'])
@admin_api
def admin_clear_force_2fa(user_id):
    user = User.query.get_or_404(user_id)
    user.force_2fa_setup = False
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Notifications (who hears about declined shifts)
# ---------------------------------------------------------------------------

def _notification_state() -> dict:
    candidates = User.query.filter(or_(User.is_admin.is_(True), User.user_role == 'staff')) \
        .order_by(User.username).all()
    chosen = list(get_setting('notify.shift_declined.user_ids') or [])
    everyone = User.query.filter(User.is_cast.is_(False) | User.is_cast.is_(None)).order_by(User.username).all()
    return {
        'mail_configured': bool(current_app.config.get('MAIL_USERNAME')),
        'enabled': bool(get_setting('notify.shift_declined.enabled')),
        'include_event_creator': bool(get_setting('notify.shift_declined.include_event_creator')),
        'user_ids': chosen,
        'people': [{'id': u.id, 'username': u.username, 'name': u.shown_name, 'email': u.email or '',
                    'is_admin': bool(u.is_admin), 'suggested': u in candidates} for u in everyone],
    }


@admin_bp.route('/admin/api/notifications')
@admin_api
def api_notifications():
    return jsonify(_notification_state())


@admin_bp.route('/admin/api/notifications', methods=['PUT'])
@admin_api
def api_notifications_save():
    data = request.get_json(silent=True) or {}
    ids = data.get('user_ids', [])
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return err('user_ids must be a list of user ids')
    valid = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
    ids = [i for i in dict.fromkeys(ids) if i in valid]
    set_setting('notify.shift_declined.user_ids', ids, current_user.username)
    set_setting('notify.shift_declined.enabled', bool(data.get('enabled', True)), current_user.username)
    set_setting('notify.shift_declined.include_event_creator',
                bool(data.get('include_event_creator', False)), current_user.username)
    db.session.commit()
    return jsonify({'success': True, 'no_email': [valid[i].username for i in ids if not valid[i].email]})


@admin_bp.route('/admin/api/notifications/test', methods=['POST'])
@admin_api
def api_notifications_test():
    """Send a sample 'shift declined' email to the chosen people (or to you if nobody is chosen)."""
    if not current_app.config.get('MAIL_USERNAME'):
        return err('Email is not set up on this server (MAIL_USERNAME / MAIL_SERVER are empty).')
    ids = list(get_setting('notify.shift_declined.user_ids') or [])
    to = [u for u in User.query.filter(User.id.in_(ids)).all() if u.email] if ids else []
    if not to and current_user.email:
        to = [current_user]
    if not to:
        return err('Nobody with an email address is selected, and your own account has no email.')

    class _Fake:           # shaped like a ShiftAssignment, no database rows needed
        decline_reason = 'This is a test - no shift was actually declined.'
        user = type('U', (), {'username': 'Example Person'})()
        shift = type('S', (), {'role': 'Sound', 'shift_date': datetime.now().replace(hour=17, minute=0),
                               'shift_end_date': datetime.now().replace(hour=22, minute=0),
                               'event': type('E', (), {'title': 'Example Event', 'location': 'Main Hall'})()})()
    subject, html, text = build_decline_email(_Fake)
    sent = [u.username for u in to if send_html_email('[TEST] ' + subject, u.email, html, text)]
    if not sent:
        return err('The mail server refused the message - check the server logs and your MAIL_* settings.', 502)
    return jsonify({'success': True, 'sent_to': sent})


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def _db_path() -> str | None:
    url = db.engine.url
    if url.get_backend_name() != 'sqlite' or not url.database or url.database == ':memory:':
        return None
    path = url.database
    return path if os.path.isabs(path) else os.path.join(current_app.instance_path, path)


def _make_backup(prefix='production_crew_backup') -> str:
    src = _db_path()
    if not src or not os.path.exists(src):
        raise RuntimeError('Backups are only available for the SQLite database file.')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    dest = os.path.join(BACKUP_DIR, name)
    s, d = sqlite3.connect(src), sqlite3.connect(dest)
    try:
        s.backup(d)                       # consistent copy even while the app is writing
    finally:
        d.close()
        s.close()
    return name


@admin_bp.route('/admin/backup', methods=['POST'])
@admin_api
def backup_database():
    try:
        return jsonify({'success': True, 'filename': _make_backup()})
    except Exception as exc:
        return err(str(exc), 500)


@admin_bp.route('/admin/backups')
@admin_api
def list_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = []
    for f in os.listdir(BACKUP_DIR):
        if _BACKUP_NAME.match(f):
            p = os.path.join(BACKUP_DIR, f)
            out.append({'name': f, 'size': os.path.getsize(p),
                        'date': datetime.fromtimestamp(os.path.getmtime(p)).isoformat()})
    return jsonify(sorted(out, key=lambda b: b['date'], reverse=True))


@admin_bp.route('/admin/download-backup/<filename>')
@admin_api
def download_backup(filename):
    if not _BACKUP_NAME.match(filename):
        return err('Invalid filename')
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        return err('File not found', 404)
    return send_file(os.path.abspath(path), as_attachment=True, download_name=filename,
                     mimetype='application/octet-stream')


@admin_bp.route('/admin/backups/<filename>', methods=['DELETE'])
@admin_api
def delete_backup(filename):
    if not _BACKUP_NAME.match(filename):
        return err('Invalid filename')
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        return err('File not found', 404)
    os.remove(path)
    return jsonify({'success': True})


@admin_bp.route('/admin/restore', methods=['POST'])
@admin_api
def restore_database():
    upload = request.files.get('file')
    if not upload:
        return err('No file provided')
    target = _db_path()
    if not target:
        return err('Restore is only available for the SQLite database file.')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    tmp = os.path.join(BACKUP_DIR, '_restore_upload.tmp')
    upload.save(tmp)
    try:
        with open(tmp, 'rb') as fh:
            if fh.read(16) != b'SQLite format 3\x00':
                return err('That file is not a SQLite database')
        con = sqlite3.connect(tmp)
        try:
            ok = con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        if not ok or 'user' not in tables:
            return err('That file is damaged or is not a ShowWise database')
        safety = _make_backup('before_restore')           # always keep a way back
        db.session.remove()
        db.engine.dispose()
        shutil.copyfile(tmp, target)
        return jsonify({'success': True, 'message': f'Database restored. Your previous data was saved as {safety}.'})
    except Exception as exc:
        return err(str(exc), 500)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/export-events')
@admin_api
def export_events_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Event', 'Event start', 'Event end', 'Location', 'Person', 'Email', 'Role',
                'Shift start', 'Shift end', 'Shift status'])
    f = lambda d: d.strftime('%Y-%m-%d %H:%M') if d else ''
    for e in Event.query.order_by(Event.event_date).all():
        people = {}
        for c in e.crew_assignments:
            people[c.crew_member] = {'role': c.role, 'shifts': []}
        for a, s in (db.session.query(ShiftAssignment, Shift).join(Shift)
                     .filter(Shift.event_id == e.id).order_by(Shift.shift_date).all()):
            if a.user:
                people.setdefault(a.user.username, {'role': s.role, 'shifts': []})['shifts'].append((a, s))
        if not people:
            w.writerow([e.title, f(e.event_date), f(e.event_end_date), e.location or '', 'No crew assigned'])
        for name, info in people.items():
            user = User.query.filter_by(username=name).first()
            base = [e.title, f(e.event_date), f(e.event_end_date), e.location or '',
                    user.shown_name if user else name, user.email if user and user.email else '']
            if not info['shifts']:
                w.writerow(base + [info['role'] or '', '', '', 'no shift times'])
            for a, s in info['shifts']:
                w.writerow(base + [s.role or info['role'] or '', f(s.shift_date), f(s.shift_end_date), a.status])
    return Response(out.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=events_crew_{datetime.now():%Y%m%d}.csv'})


# ---------------------------------------------------------------------------
# Invite codes
# ---------------------------------------------------------------------------

def _new_code() -> str:
    code = generate_invite_code()
    while InviteCode.query.filter_by(code=code).first():
        code = generate_invite_code()
    return code


def _parse_expiry(value):
    try:
        dt = datetime.fromisoformat(str(value or '')[:16])
    except ValueError:
        return None, 'Invalid expiry date'
    if dt <= datetime.utcnow():
        return None, 'Expiry must be in the future'
    return dt, None


@admin_bp.route('/admin/invites')
@admin_api
def list_invites():
    return jsonify([serialize_invite(i) for i in InviteCode.query.order_by(InviteCode.created_at.desc()).all()])


@admin_bp.route('/admin/invites/generate', methods=['POST'])
@admin_api
def generate_invite():
    data = request.get_json(silent=True) or {}
    expires_at, problem = _parse_expiry(data.get('expires_at'))
    if problem:
        return err(problem)
    role = data.get('role', 'crew')
    if role not in USER_ROLES:
        return err('Unknown role')
    try:
        uses = max(1, min(500, int(data.get('max_uses', 1))))
    except (TypeError, ValueError):
        return err('Max uses must be a number')
    invite = InviteCode(code=_new_code(), role=role, created_by=current_user.username,
                        expires_at=expires_at, max_uses=uses, note=str(data.get('note') or '')[:200])
    db.session.add(invite)
    db.session.commit()
    return jsonify({'success': True, 'code': invite.code, 'id': invite.id})


@admin_bp.route('/admin/invites/email', methods=['POST'])
@admin_api
def email_invite():
    data = request.get_json(silent=True) or {}
    to = str(data.get('email') or '').strip()
    name = str(data.get('name') or '').strip() or 'there'
    if not _EMAIL.match(to):
        return err('A valid email address is required')
    expires_at, problem = _parse_expiry(data.get('expires_at'))
    if problem:
        return err(problem)
    role = data.get('role', 'crew')
    if role not in USER_ROLES:
        return err('Unknown role')
    invite = InviteCode(code=_new_code(), role=role, created_by=current_user.username,
                        expires_at=expires_at, max_uses=1, note=f'Email invite to {to}')
    db.session.add(invite)
    db.session.commit()
    base = (data.get('base_url') or SIGNUP_BASE_URL or request.url_root).rstrip('/')
    sent = send_invite_email(
        recipient_email=to, recipient_name=name, signup_url=f'{base}/signup?invite={invite.code}',
        invite_code=invite.code, role_label=role.capitalize(), expires_at=expires_at,
        org=get_organization() or DEFAULT_ORG)
    if not sent:
        return jsonify({'success': False, 'error': 'Email could not be sent (is email set up?).',
                        'code': invite.code}), 500
    return jsonify({'success': True, 'code': invite.code})


@admin_bp.route('/admin/invites/<int:invite_id>/revoke', methods=['POST'])
@admin_api
def revoke_invite(invite_id):
    InviteCode.query.get_or_404(invite_id).is_active = False
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/admin/invites/<int:invite_id>', methods=['DELETE'])
@admin_api
def delete_invite(invite_id):
    inv = InviteCode.query.get_or_404(invite_id)
    inv.used_by_users = []
    db.session.delete(inv)
    db.session.commit()
    return jsonify({'success': True})
