"""services/training_service.py — training sign-offs.

* ``signoff_state(user, skill)``: is the person signed off on a skill today (or on a date)?
* ``skill_gate(...)``: called by every route that puts a person on a shift. Raises a 409
  ``ApiError`` (``skill_block=True``) when they are missing a required skill, unless an
  admin sent ``skill_override_reason``; then it returns the override to record with
  ``record_override`` once the assignment exists.
* ``equipment_skill_warnings(user, equipment)``: soft warnings for checking gear out.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from flask_login import current_user
from sqlalchemy import func

from extensions import db
from models_training import (Skill, SkillSignoff, RoleSkillRequirement, ShiftSkillRequirement,
                             SkillAssessor, SkillOverride)

EXPIRING_DAYS = 30


def _today(on=None) -> date:
    if on is None:
        return date.today()
    return on.date() if isinstance(on, datetime) else on


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def current_signoff(user_id: int, skill_id: int):
    """The latest sign-off that has not been revoked (may be expired)."""
    return (SkillSignoff.query.filter_by(user_id=user_id, skill_id=skill_id)
            .filter(SkillSignoff.revoked_at.is_(None))
            .order_by(SkillSignoff.signed_at.desc(), SkillSignoff.id.desc()).first())


def state_of(signoff, on=None) -> str:
    """'none' | 'expired' | 'expiring' | 'valid' on the given day."""
    if signoff is None:
        return 'none'
    day = _today(on)
    if signoff.expires_at is None:
        return 'valid'
    if signoff.expires_at < day:
        return 'expired'
    if signoff.expires_at <= day + timedelta(days=EXPIRING_DAYS):
        return 'expiring'
    return 'valid'


def signoff_state(user_id: int, skill_id: int, on=None) -> str:
    return state_of(current_signoff(user_id, skill_id), on)


def is_valid(user_id: int, skill_id: int, on=None) -> bool:
    return signoff_state(user_id, skill_id, on) in ('valid', 'expiring')


def can_sign_off(user, skill) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_admin:
        return True
    return SkillAssessor.query.filter_by(skill_id=skill.id, user_id=user.id).first() is not None


def is_assessor(user) -> bool:
    return bool(user and user.is_authenticated and
                (user.is_admin or SkillAssessor.query.filter_by(user_id=user.id).first()))


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def skills_for_role(role) -> list:
    role = (role or '').strip().lower()
    if not role:
        return []
    rows = (RoleSkillRequirement.query.join(Skill)
            .filter(func.lower(RoleSkillRequirement.role) == role, Skill.is_active.is_(True)).all())
    return [r.skill for r in rows]


def parse_skill_ids(raw) -> list:
    if not raw:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for v in raw:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(out))


def required_skills(role=None, shift=None, extra_ids=None) -> list:
    """Active skills needed for a shift: by its role, set on the shift, plus extra ids."""
    found = {s.id: s for s in skills_for_role(role if role is not None else (shift.role if shift else None))}
    if shift is not None:
        for r in getattr(shift, 'skill_requirements', []) or []:
            if r.skill and r.skill.is_active:
                found[r.skill.id] = r.skill
    for sid in extra_ids or []:
        s = db.session.get(Skill, sid)
        if s and s.is_active:
            found[s.id] = s
    return sorted(found.values(), key=lambda s: s.name.lower())


def set_shift_requirements(shift, skill_ids) -> None:
    ids = set(parse_skill_ids(skill_ids))
    for r in list(shift.skill_requirements):
        if r.skill_id not in ids:
            shift.skill_requirements.remove(r)
    have = {r.skill_id for r in shift.skill_requirements}
    for sid in ids - have:
        if db.session.get(Skill, sid):
            shift.skill_requirements.append(ShiftSkillRequirement(skill_id=sid))


def missing_skills(user, skills, on=None) -> list:
    out = []
    for s in skills:
        st = signoff_state(user.id, s.id, on)
        if st not in ('valid', 'expiring'):
            out.append({'id': s.id, 'name': s.name, 'state': st})
    return out


def _describe(missing) -> str:
    parts = [f"{m['name']} ({'expired' if m['state'] == 'expired' else 'not signed off'})" for m in missing]
    return ', '.join(parts)


def skill_gate(user, data: dict, role=None, shift=None, extra_ids=None, on=None):
    """Block assigning ``user`` without the required skills.

    Returns None when everything is fine, or a dict to pass to ``record_override``
    when an admin overrode the block with a reason.
    """
    from routes.events import ApiError
    skills = required_skills(role, shift, extra_ids)
    missing = missing_skills(user, skills, on) if skills else []
    if not missing:
        return None
    reason = str((data or {}).get('skill_override_reason') or '').strip()[:500]
    can_override = bool(current_user.is_authenticated and current_user.is_admin)
    if reason and can_override:
        return {'user_id': user.id, 'skill_names': ', '.join(m['name'] for m in missing),
                'reason': reason, 'missing': missing}
    raise ApiError(f"{user.shown_name} isn't signed off for this shift: {_describe(missing)}", 409,
                   skill_block=True, missing=missing, can_override=can_override,
                   person=user.shown_name)


def record_override(pending, assignment=None, event_id=None) -> None:
    if not pending:
        return
    db.session.add(SkillOverride(
        user_id=pending['user_id'], assignment_id=assignment.id if assignment is not None else None,
        event_id=event_id, skill_names=pending['skill_names'][:500], reason=pending['reason'],
        overridden_by=current_user.username if current_user.is_authenticated else None))


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

def equipment_skill_warnings(user, equipment) -> list:
    if not equipment or not user or not user.is_authenticated:
        return []
    skills = [r.skill for r in getattr(equipment, 'skill_requirements', []) or []
              if r.skill and r.skill.is_active]
    missing = missing_skills(user, skills)
    if not missing:
        return []
    return [{'code': 'skill_missing',
             'message': f'{equipment.name} needs {_describe(missing)}: '
                        f'check {user.shown_name} is allowed to use it'}]


# ---------------------------------------------------------------------------
# Overviews
# ---------------------------------------------------------------------------

def user_skills(user) -> list:
    """Every active skill with this person's current state."""
    rows = []
    for s in Skill.query.filter_by(is_active=True).order_by(Skill.name).all():
        so = current_signoff(user.id, s.id)
        rows.append({'skill': s, 'signoff': so, 'state': state_of(so)})
    return rows


def expiring_signoffs(days: int = EXPIRING_DAYS, user_id=None, on=None) -> list:
    """Current sign-offs that expire within ``days`` (or already have, in the last 30 days)."""
    day = _today(on)
    q = (SkillSignoff.query.join(Skill)
         .filter(Skill.is_active.is_(True), SkillSignoff.revoked_at.is_(None),
                 SkillSignoff.expires_at.isnot(None),
                 SkillSignoff.expires_at <= day + timedelta(days=days),
                 SkillSignoff.expires_at >= day - timedelta(days=30)))
    if user_id is not None:
        q = q.filter(SkillSignoff.user_id == user_id)
    out = []
    for so in q.order_by(SkillSignoff.expires_at).all():
        # Ignore it if a newer sign-off replaced it
        if current_signoff(so.user_id, so.skill_id) is so:
            out.append({'signoff': so, 'state': state_of(so, day),
                        'days': (so.expires_at - day).days})
    return out
