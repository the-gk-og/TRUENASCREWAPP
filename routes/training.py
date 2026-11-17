"""
routes/training.py
==================
Training sign-offs.

Pages
  /training                 your own skills (and anything expiring)
  /training/people/<id>     one person's skills (themselves, admins, assessors)
  /training/matrix          people × skills grid with expiring-soon list (admins, assessors)
  /training/manage          define skills, who may sign them off, which roles / gear need them (admins)

API (JSON)
  GET    /api/training/skills
  POST   /api/training/skills                 (admin) {name, description, validity_months, assessor_ids, roles, equipment_ids}
  PUT    /api/training/skills/<id>            (admin) same fields, plus is_active
  DELETE /api/training/skills/<id>            (admin) archives it (history is kept)
  POST   /api/training/signoffs               {user_id, skill_id, signed_at?, expires_at?, note?}
  POST   /api/training/signoffs/<id>/revoke   {reason?}
  GET    /api/training/users/<id>
"""
from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from decorators import crew_required
from extensions import db
from models import User, Equipment
from models_training import (Skill, SkillAssessor, SkillSignoff, RoleSkillRequirement,
                             EquipmentSkillRequirement, SkillOverride)
from routes.events import ApiError, body, manager_required, clean_text
from services import training_service as ts

training_bp = Blueprint('training', __name__)


def _people():
    """Crew and staff (not cast-only accounts), by name."""
    users = (User.query.filter(or_(User.is_cast.is_(False), User.is_cast.is_(None), User.is_admin.is_(True)))
             .all())
    return sorted(users, key=lambda u: u.shown_name.lower())


def _can_view_person(user) -> bool:
    return current_user.id == user.id or ts.is_assessor(current_user)


def _parse_date(value, label):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ApiError(f'{label} is not a valid date')


def _signoff_dict(so):
    if so is None:
        return None
    return {'id': so.id, 'user_id': so.user_id, 'skill_id': so.skill_id,
            'signed_by': so.signed_by or '', 'signed_by_name': _name(so.signed_by),
            'signed_at': so.signed_at.isoformat() if so.signed_at else None,
            'expires_at': so.expires_at.isoformat() if so.expires_at else None,
            'note': so.note or '', 'state': ts.state_of(so),
            'revoked_at': so.revoked_at.isoformat() if so.revoked_at else None}


def _name(username):
    if not username:
        return ''
    u = User.query.filter_by(username=username).first()
    return u.shown_name if u else username


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _person_page(user):
    history = (SkillSignoff.query.filter_by(user_id=user.id)
               .order_by(SkillSignoff.signed_at.desc(), SkillSignoff.id.desc()).all())
    signable = [s.id for s in Skill.query.filter_by(is_active=True).all()
                if user.id != current_user.id and ts.can_sign_off(current_user, s)]
    return render_template('crew/training.html', person=user, rows=ts.user_skills(user),
                           history=history, signable=signable,
                           expiring=ts.expiring_signoffs(user_id=user.id),
                           is_me=user.id == current_user.id,
                           assessor=ts.is_assessor(current_user), name_for=_name)


@training_bp.route('/training')
@login_required
@crew_required
def my_training():
    return _person_page(current_user)


@training_bp.route('/training/people/<int:user_id>')
@login_required
@crew_required
def person_training(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if not _can_view_person(user):
        abort(403)
    return _person_page(user)


@training_bp.route('/training/matrix')
@login_required
@crew_required
def matrix():
    if not ts.is_assessor(current_user):
        abort(403)
    skills = Skill.query.filter_by(is_active=True).order_by(Skill.name).all()
    people = _people()
    grid = {}
    current = {}
    for so in (SkillSignoff.query.filter(SkillSignoff.revoked_at.is_(None))
               .order_by(SkillSignoff.signed_at, SkillSignoff.id).all()):
        current[(so.user_id, so.skill_id)] = so        # later rows win
    for p in people:
        for s in skills:
            so = current.get((p.id, s.id))
            grid[(p.id, s.id)] = {'state': ts.state_of(so), 'signoff': so}
    signable = {s.id for s in skills if ts.can_sign_off(current_user, s)}
    overrides = (SkillOverride.query.order_by(SkillOverride.created_at.desc()).limit(25).all()
                 if current_user.is_admin else [])
    return render_template('crew/training_matrix.html', skills=skills, people=people, grid=grid,
                           signable=signable, expiring=ts.expiring_signoffs(),
                           overrides=overrides, name_for=_name)


@training_bp.route('/training/manage')
@login_required
@crew_required
def manage():
    if not current_user.is_admin:
        abort(403)
    skills = Skill.query.order_by(Skill.is_active.desc(), Skill.name).all()
    return render_template('crew/training_manage.html', skills=skills,
                           people=[{'id': u.id, 'name': u.shown_name} for u in _people()],
                           equipment=[{'id': e.id, 'name': e.name}
                                      for e in Equipment.query.order_by(Equipment.name).all()],
                           skills_json=[s.to_dict() for s in skills])


# ---------------------------------------------------------------------------
# Skills API
# ---------------------------------------------------------------------------

@training_bp.route('/api/training/skills')
@login_required
@crew_required
def list_skills():
    return jsonify({'skills': [s.to_dict() for s in
                               Skill.query.filter_by(is_active=True).order_by(Skill.name).all()]})


def _apply_skill(skill, data, creating=False):
    if creating or 'name' in data:
        name = clean_text(data.get('name'), 'Name', 100)
        if not name:
            raise ApiError('Give the skill a name')
        with db.session.no_autoflush:
            clash = Skill.query.filter(db.func.lower(Skill.name) == name.lower()).first()
        if clash and clash is not skill:
            raise ApiError(f'There is already a skill called {clash.name}')
        skill.name = name
    if 'description' in data:
        skill.description = str(data.get('description') or '').strip()[:2000] or None
    if 'validity_months' in data:
        raw = data.get('validity_months')
        if raw in (None, '', 0, '0'):
            skill.validity_months = None
        else:
            try:
                months = int(raw)
            except (TypeError, ValueError):
                raise ApiError('Valid for must be a number of months')
            if not 1 <= months <= 240:
                raise ApiError('Valid for must be between 1 and 240 months')
            skill.validity_months = months
    if 'is_active' in data:
        skill.is_active = bool(data.get('is_active'))
    db.session.add(skill)
    db.session.flush()
    if 'assessor_ids' in data:
        ids = set(ts.parse_skill_ids(data.get('assessor_ids')))
        for a in list(skill.assessors):
            if a.user_id not in ids:
                skill.assessors.remove(a)
        have = {a.user_id for a in skill.assessors}
        for uid in ids - have:
            if db.session.get(User, uid):
                skill.assessors.append(SkillAssessor(user_id=uid))
    if 'roles' in data:
        raw = data.get('roles') or []
        if isinstance(raw, str):
            raw = raw.split(',')
        roles = {}
        for r in raw:
            r = str(r or '').strip()[:100]
            if r:
                roles.setdefault(r.lower(), r)
        for row in list(skill.role_requirements):
            if row.role.lower() not in roles:
                skill.role_requirements.remove(row)
        have = {row.role.lower() for row in skill.role_requirements}
        for key, r in roles.items():
            if key not in have:
                skill.role_requirements.append(RoleSkillRequirement(role=r))
    if 'equipment_ids' in data:
        ids = set(ts.parse_skill_ids(data.get('equipment_ids')))
        for row in list(skill.equipment_requirements):
            if row.equipment_id not in ids:
                skill.equipment_requirements.remove(row)
        have = {row.equipment_id for row in skill.equipment_requirements}
        for eid in ids - have:
            if db.session.get(Equipment, eid):
                skill.equipment_requirements.append(EquipmentSkillRequirement(equipment_id=eid))


@training_bp.route('/api/training/skills', methods=['POST'])
@login_required
@crew_required
@manager_required
def create_skill():
    data = body()
    skill = Skill(created_by=current_user.username, is_active=True)
    try:
        _apply_skill(skill, data, creating=True)
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    return jsonify({'success': True, 'skill': skill.to_dict()})


@training_bp.route('/api/training/skills/<int:skill_id>', methods=['PUT'])
@login_required
@crew_required
@manager_required
def update_skill(skill_id):
    skill = db.session.get(Skill, skill_id) or abort(404)
    try:
        _apply_skill(skill, body())
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    return jsonify({'success': True, 'skill': skill.to_dict()})


@training_bp.route('/api/training/skills/<int:skill_id>', methods=['DELETE'])
@login_required
@crew_required
@manager_required
def archive_skill(skill_id):
    """Archive: it stops being required anywhere and leaves the matrix; sign-off history stays."""
    skill = db.session.get(Skill, skill_id) or abort(404)
    skill.is_active = False
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Sign-offs API
# ---------------------------------------------------------------------------

@training_bp.route('/api/training/signoffs', methods=['POST'])
@login_required
@crew_required
def sign_off():
    data = body()
    user = db.session.get(User, ts.parse_skill_ids(data.get('user_id'))[0]) if data.get('user_id') else None
    skill = db.session.get(Skill, ts.parse_skill_ids(data.get('skill_id'))[0]) if data.get('skill_id') else None
    if not user or not skill:
        raise ApiError('Choose a person and a skill', 404)
    if not skill.is_active:
        raise ApiError(f'{skill.name} is archived')
    if not ts.can_sign_off(current_user, skill):
        raise ApiError(f'You are not authorised to sign people off on {skill.name}', 403)
    if user.id == current_user.id:
        raise ApiError('You cannot sign yourself off; ask another assessor', 403)
    signed_at = _parse_date(data.get('signed_at'), 'Signed off on') or date.today()
    if signed_at > date.today():
        raise ApiError('The sign-off date cannot be in the future')
    if 'expires_at' in data:
        expires_at = _parse_date(data.get('expires_at'), 'Expiry')
    else:
        expires_at = ts.add_months(signed_at, skill.validity_months) if skill.validity_months else None
    if expires_at and expires_at <= signed_at:
        raise ApiError('The expiry must be after the sign-off date')
    so = SkillSignoff(user_id=user.id, skill_id=skill.id, signed_by=current_user.username,
                      signed_at=signed_at, expires_at=expires_at,
                      note=str(data.get('note') or '').strip()[:2000] or None)
    db.session.add(so)
    db.session.commit()
    return jsonify({'success': True, 'signoff': _signoff_dict(so)})


@training_bp.route('/api/training/signoffs/<int:signoff_id>/revoke', methods=['POST'])
@login_required
@crew_required
def revoke(signoff_id):
    so = db.session.get(SkillSignoff, signoff_id) or abort(404)
    if not ts.can_sign_off(current_user, so.skill):
        raise ApiError('You are not authorised to change this sign-off', 403)
    if so.revoked_at:
        raise ApiError('This sign-off was already revoked')
    reason = str((body() or {}).get('reason') or '').strip()[:500]
    so.revoked_at, so.revoked_by = datetime.utcnow(), current_user.username
    if reason:
        so.note = f'{so.note}\nRevoked: {reason}' if so.note else f'Revoked: {reason}'
    db.session.commit()
    return jsonify({'success': True})


@training_bp.route('/api/training/users/<int:user_id>')
@login_required
@crew_required
def user_api(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if not _can_view_person(user):
        raise ApiError('Permission denied', 403)
    return jsonify({'user_id': user.id, 'name': user.shown_name, 'skills': [
        {'skill_id': r['skill'].id, 'name': r['skill'].name, 'state': r['state'],
         'signoff': _signoff_dict(r['signoff'])} for r in ts.user_skills(user)]})


# ---------------------------------------------------------------------------
# Reminders for templates (dashboard)
# ---------------------------------------------------------------------------

@training_bp.app_context_processor
def _training_helpers():
    def training_reminders():
        """Your own sign-offs expiring soon, plus (for assessors) a count across everyone."""
        if not current_user.is_authenticated:
            return {'mine': [], 'team': 0}
        try:
            mine = ts.expiring_signoffs(user_id=current_user.id)
            team = len(ts.expiring_signoffs()) if ts.is_assessor(current_user) else 0
        except Exception:                      # never break a page over reminders
            return {'mine': [], 'team': 0}
        return {'mine': mine, 'team': team}
    return {'training_reminders': training_reminders}
