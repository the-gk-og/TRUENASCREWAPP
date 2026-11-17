"""
models_training.py
==================
Training sign-offs: skills/qualifications, who is signed off on what, and which
shift roles / shifts / equipment types need a skill. Imported at the bottom of
models.py so ``db.create_all()`` (schema_migrations step 3) creates the tables.

Backrefs onto User / Shift / Equipment carry delete-orphan cascades so deleting
a person, shift or equipment type cleans these rows up without touching those
classes.
"""
from datetime import datetime, date

from extensions import db


class Skill(db.Model):
    __tablename__ = 'skill'
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), unique=True, nullable=False)
    description     = db.Column(db.Text)
    # Months a sign-off stays valid; NULL = never expires
    validity_months = db.Column(db.Integer, nullable=True)
    is_active       = db.Column(db.Boolean, default=True)
    created_by      = db.Column(db.String(80))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description or '',
                'validity_months': self.validity_months, 'is_active': bool(self.is_active),
                'assessor_ids': [a.user_id for a in self.assessors],
                'roles': [r.role for r in self.role_requirements],
                'equipment_ids': [e.equipment_id for e in self.equipment_requirements]}


class SkillAssessor(db.Model):
    """A non-admin user allowed to sign people off on this skill."""
    __tablename__ = 'skill_assessor'
    id       = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    skill = db.relationship('Skill', backref=db.backref('assessors', cascade='all, delete-orphan'))
    user  = db.relationship('User', backref=db.backref('skill_assessor_rows', cascade='all, delete-orphan'))


class SkillSignoff(db.Model):
    """One sign-off. History is kept: a revoked row stays with revoked_at set."""
    __tablename__ = 'skill_signoff'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    skill_id   = db.Column(db.Integer, db.ForeignKey('skill.id', ondelete='CASCADE'), nullable=False, index=True)
    signed_by  = db.Column(db.String(80))
    signed_at  = db.Column(db.Date, default=date.today, nullable=False)
    expires_at = db.Column(db.Date, nullable=True)
    note       = db.Column(db.Text)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user  = db.relationship('User', backref=db.backref('skill_signoffs', cascade='all, delete-orphan'))
    skill = db.relationship('Skill', backref=db.backref('signoffs', cascade='all, delete-orphan'))


class RoleSkillRequirement(db.Model):
    """A shift role (matched case-insensitively) that needs a skill."""
    __tablename__ = 'role_skill_requirement'
    id       = db.Column(db.Integer, primary_key=True)
    role     = db.Column(db.String(100), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id', ondelete='CASCADE'), nullable=False)
    skill = db.relationship('Skill', backref=db.backref('role_requirements', cascade='all, delete-orphan'))


class ShiftSkillRequirement(db.Model):
    __tablename__ = 'shift_skill_requirement'
    id       = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id', ondelete='CASCADE'), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id', ondelete='CASCADE'), nullable=False)
    shift = db.relationship('Shift', backref=db.backref('skill_requirements', cascade='all, delete-orphan'))
    skill = db.relationship('Skill', backref=db.backref('shift_requirements', cascade='all, delete-orphan'))


class EquipmentSkillRequirement(db.Model):
    __tablename__ = 'equipment_skill_requirement'
    id           = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id', ondelete='CASCADE'), nullable=False, index=True)
    skill_id     = db.Column(db.Integer, db.ForeignKey('skill.id', ondelete='CASCADE'), nullable=False)
    equipment = db.relationship('Equipment', backref=db.backref('skill_requirements', cascade='all, delete-orphan'))
    skill     = db.relationship('Skill', backref=db.backref('equipment_requirements', cascade='all, delete-orphan'))


class SkillOverride(db.Model):
    """Audit row: an admin assigned someone without a valid sign-off."""
    __tablename__ = 'skill_override'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, nullable=True)     # plain id: the audit row outlives the assignment
    event_id      = db.Column(db.Integer, nullable=True)
    skill_names   = db.Column(db.String(500), nullable=False)
    reason        = db.Column(db.String(500), nullable=False)
    overridden_by = db.Column(db.String(80))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('skill_overrides', cascade='all, delete-orphan'))
