"""
models.py
=========
All SQLAlchemy database models for ShowWise.
Equipment gains two optional picture fields:
  picture          – photo of the item itself
  location_picture – photo of the storage location
"""

from datetime import datetime
from extensions import db
from flask_login import UserMixin


class User(UserMixin, db.Model):
    id                    = db.Column(db.Integer, primary_key=True)
    username              = db.Column(db.String(80), unique=True, nullable=False)
    email                 = db.Column(db.String(120), unique=True, nullable=True)
    discord_id            = db.Column(db.String(50), unique=True, nullable=True)
    discord_username      = db.Column(db.String(100), nullable=True)
    password_hash         = db.Column(db.String(200))
    is_admin              = db.Column(db.Boolean, default=False)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    is_cast               = db.Column(db.Boolean, default=False)
    user_role             = db.Column(db.String(20), default='crew')
    force_2fa_setup       = db.Column(db.Boolean, default=False)
    skip_2fa_for_oauth    = db.Column(db.Boolean, default=False)
    profile_picture       = db.Column(db.String(300), nullable=True)
    password_reset_token  = db.Column(db.String(100), nullable=True)
    password_reset_expiry = db.Column(db.DateTime, nullable=True)
    
    # Security: Account lockout after failed login attempts
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until          = db.Column(db.DateTime, nullable=True)
    last_login_attempt    = db.Column(db.DateTime, nullable=True)
    email_verified        = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(200), nullable=True)


class TwoFactorAuth(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    secret       = db.Column(db.String(32), nullable=False)
    enabled      = db.Column(db.Boolean, default=False)
    backup_codes = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='two_factor_auth')


class OAuthConnection(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider         = db.Column(db.String(50), nullable=False)
    provider_user_id = db.Column(db.String(200), nullable=False)
    email            = db.Column(db.String(200))
    access_token     = db.Column(db.String(500))
    refresh_token    = db.Column(db.String(500))
    token_expiry     = db.Column(db.DateTime)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    last_login       = db.Column(db.DateTime)
    user = db.relationship('User', backref='oauth_connections')
    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_user_id', name='unique_provider_user'),
    )


invite_code_uses = db.Table(
    'invite_code_uses',
    db.Column('invite_code_id', db.Integer, db.ForeignKey('invite_code.id'), primary_key=True),
    db.Column('user_id',        db.Integer, db.ForeignKey('user.id'),        primary_key=True),
)


class InviteCode(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    code       = db.Column(db.String(32), unique=True, nullable=False)
    role       = db.Column(db.String(20), default='crew')
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    max_uses   = db.Column(db.Integer, default=1)
    use_count  = db.Column(db.Integer, default=0)
    is_active  = db.Column(db.Boolean, default=True)
    note       = db.Column(db.String(200))
    used_by_users = db.relationship('User', secondary=invite_code_uses, backref='invite_code')


# ---------------------------------------------------------------------------
# Equipment  ← two new picture columns
# ---------------------------------------------------------------------------

class Equipment(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    barcode          = db.Column(db.String(100), unique=True, nullable=False)
    name             = db.Column(db.String(200), nullable=False)
    category         = db.Column(db.String(100))
    location         = db.Column(db.String(200))
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    quantity_owned   = db.Column(db.Integer, default=1)
    # Photo of the item itself
    picture          = db.Column(db.String(300), nullable=True)
    # Photo of where it lives in storage
    location_picture = db.Column(db.String(300), nullable=True)

    def to_dict(self):
        from flask import url_for
        return {
            'id':             self.id,
            'barcode':        self.barcode,
            'name':           self.name,
            'category':       self.category or '',
            'location':       self.location or '',
            'notes':          self.notes or '',
            'quantity_owned': self.quantity_owned or 1,
            'picture_url': (
                url_for('equipment.serve_equipment_picture', id=self.id)
                if self.picture else None
            ),
            'location_picture_url': (
                url_for('equipment.serve_equipment_location_picture', id=self.id)
                if self.location_picture else None
            ),
        }


class HiredEquipment(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    supplier    = db.Column(db.String(200))
    hire_date   = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime, nullable=False)
    cost        = db.Column(db.String(50))
    quantity    = db.Column(db.Integer, default=1)
    notes       = db.Column(db.Text)
    is_returned = db.Column(db.Boolean, default=False)
    returned_at = db.Column(db.DateTime, nullable=True)
    event_id    = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    checklist_items = db.relationship(
        'HiredEquipmentCheckItem', backref='hired_equipment', cascade='all, delete-orphan'
    )
    event = db.relationship('Event', backref='hired_equipment')


class HiredEquipmentCheckItem(db.Model):
    id                 = db.Column(db.Integer, primary_key=True)
    hired_equipment_id = db.Column(db.Integer, db.ForeignKey('hired_equipment.id'), nullable=False)
    item_name          = db.Column(db.String(200), nullable=False)
    is_checked         = db.Column(db.Boolean, default=False)
    notes              = db.Column(db.Text)


class Event(db.Model):
    id                    = db.Column(db.Integer, primary_key=True)
    title                 = db.Column(db.String(200), nullable=False)
    description           = db.Column(db.Text)
    event_date            = db.Column(db.DateTime, nullable=False)
    event_end_date        = db.Column(db.DateTime, nullable=True)
    location              = db.Column(db.String(200))
    created_by            = db.Column(db.String(80))
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    discord_message_id    = db.Column(db.String(50), nullable=True)
    cast_description      = db.Column(db.Text)
    recurrence_pattern    = db.Column(db.String(50), nullable=True)
    recurrence_interval   = db.Column(db.Integer, default=1)
    recurrence_end_date   = db.Column(db.DateTime, nullable=True)
    recurrence_count      = db.Column(db.Integer, nullable=True)
    is_recurring_instance = db.Column(db.Boolean, default=False)
    recurring_event_id    = db.Column(db.Integer, nullable=True)
    crew_assignments = db.relationship('CrewAssignment', backref='event', lazy=True, cascade='all, delete-orphan')
    pick_list_items  = db.relationship('PickListItem',   backref='event', lazy=True, cascade='all, delete-orphan')
    stage_plans      = db.relationship('StagePlan',      backref='event', lazy=True, cascade='all, delete-orphan')


class CrewAssignment(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    event_id     = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    crew_member  = db.Column(db.String(80), nullable=False)
    role         = db.Column(db.String(100))
    assigned_at  = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_via = db.Column(db.String(20), default='webapp')


class EventSchedule(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    event_id       = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    title          = db.Column(db.String(100), nullable=False)
    scheduled_time = db.Column(db.DateTime, nullable=False)
    description    = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.relationship('Event', backref=db.backref('schedules', cascade='all, delete-orphan'))


class EventNote(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    event_id   = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    event = db.relationship('Event', backref=db.backref('notes', cascade='all, delete-orphan'))


class Picklist(db.Model):
    """Groups multiple picklist items for an event."""
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    event_id    = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    created_by  = db.Column(db.String(80))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False)
    items       = db.relationship('PickListItem', backref='picklist', lazy=True, cascade='all, delete-orphan')
    event       = db.relationship('Event', backref='picklists')


class PickListItem(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    item_name    = db.Column(db.String(200), nullable=False)
    quantity     = db.Column(db.Integer, default=1)
    is_checked   = db.Column(db.Boolean, default=False)
    added_by     = db.Column(db.String(80))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    event_id     = db.Column(db.Integer, db.ForeignKey('event.id'))
    picklist_id  = db.Column(db.Integer, db.ForeignKey('picklist.id'), nullable=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    is_archived  = db.Column(db.Boolean, default=False)
    equipment    = db.relationship('Equipment', backref='pick_list_items')


class StagePlanCollection(db.Model):
    """Groups multiple stage plans for an event."""
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    event_id    = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    created_by  = db.Column(db.String(80))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False)
    plans       = db.relationship('StagePlan', backref='collection', lazy=True)
    event       = db.relationship('Event', backref='stage_plan_collections')


class StagePlan(db.Model):
    id                = db.Column(db.Integer, primary_key=True)
    title             = db.Column(db.String(200), nullable=False)
    filename          = db.Column(db.String(300), nullable=False)
    uploaded_by       = db.Column(db.String(80))
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    event_id          = db.Column(db.Integer, db.ForeignKey('event.id'))
    collection_id     = db.Column(db.Integer, db.ForeignKey('stage_plan_collection.id'), nullable=True)
    is_archived       = db.Column(db.Boolean, default=False)


class Shift(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    event_id         = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    title            = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text)
    shift_date       = db.Column(db.DateTime, nullable=False)
    shift_end_date   = db.Column(db.DateTime, nullable=False)
    location         = db.Column(db.String(200))
    positions_needed = db.Column(db.Integer, default=1)
    role             = db.Column(db.String(100))
    is_open          = db.Column(db.Boolean, default=True)
    is_archived      = db.Column(db.Boolean, default=False)
    created_by       = db.Column(db.String(80), nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    event       = db.relationship('Event', backref=db.backref('shifts', cascade='all, delete-orphan'))
    assignments = db.relationship('ShiftAssignment', backref='shift', lazy=True, cascade='all, delete-orphan')


class ShiftAssignment(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    shift_id     = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_by  = db.Column(db.String(80))
    status       = db.Column(db.String(20), default='pending')
    notes        = db.Column(db.Text)
    assigned_at  = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='shift_assignments')


class ShiftNote(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    shift_id   = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    shift = db.relationship('Shift', backref='notes')


class ShiftTask(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    shift_id    = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    is_complete = db.Column(db.Boolean, default=False)
    assigned_to = db.Column(db.String(80))
    created_by  = db.Column(db.String(80), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    shift = db.relationship('Shift', backref='tasks')


class CastMember(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    actor_name     = db.Column(db.String(200), nullable=False)
    character_name = db.Column(db.String(200), nullable=False)
    role_type      = db.Column(db.String(50), default='lead')
    contact_email  = db.Column(db.String(120), nullable=True)
    contact_phone  = db.Column(db.String(50), nullable=True)
    notes          = db.Column(db.Text)
    event_id       = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    event = db.relationship('Event', backref='cast_members')
    user  = db.relationship('User',  backref='cast_roles')


class CastSchedule(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    event_id       = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    title          = db.Column(db.String(100), nullable=False)
    scheduled_time = db.Column(db.DateTime, nullable=False)
    description    = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.relationship('Event', backref=db.backref('cast_schedules', cascade='all, delete-orphan'))


class CastNote(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    event_id   = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    event = db.relationship('Event', backref=db.backref('cast_notes', cascade='all, delete-orphan'))


class CrewRunItem(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    event_id     = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    order_number = db.Column(db.Integer, nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text)
    duration     = db.Column(db.String(50))
    cue_type     = db.Column(db.String(50))
    notes        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.relationship(
        'Event',
        backref=db.backref('crew_run_items', cascade='all, delete-orphan', order_by='CrewRunItem.order_number'),
    )


class CastRunItem(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    event_id      = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    order_number  = db.Column(db.Integer, nullable=False)
    title         = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text)
    duration      = db.Column(db.String(50))
    item_type     = db.Column(db.String(50))
    cast_involved = db.Column(db.Text)
    notes         = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.relationship(
        'Event',
        backref=db.backref('cast_run_items', cascade='all, delete-orphan', order_by='CastRunItem.order_number'),
    )


class StagePlanTemplate(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    design_data = db.Column(db.Text, nullable=False)
    thumbnail   = db.Column(db.String(300))
    created_by  = db.Column(db.String(80))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_public   = db.Column(db.Boolean, default=False)


class StagePlanDesign(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    event_id    = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('stage_plan_template.id'), nullable=True)
    name        = db.Column(db.String(200), nullable=False)
    design_data = db.Column(db.Text, nullable=False)
    thumbnail   = db.Column(db.Text)
    created_by  = db.Column(db.String(80))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    event    = db.relationship('Event', backref='stage_designs')
    template = db.relationship('StagePlanTemplate', backref='designs')


class StagePlanObject(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(200), nullable=False)
    category       = db.Column(db.String(100))
    image_data     = db.Column(db.Text, nullable=False)
    default_width  = db.Column(db.Integer, default=100)
    default_height = db.Column(db.Integer, default=100)
    created_by     = db.Column(db.String(80))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    is_public      = db.Column(db.Boolean, default=True)


class TodoItem(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text)
    priority     = db.Column(db.String(20), default='medium')
    is_completed = db.Column(db.Boolean, default=False)
    due_date     = db.Column(db.DateTime, nullable=True)
    event_id     = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    user  = db.relationship('User',  backref='todos')
    event = db.relationship('Event', backref='todos')


class UserUnavailability(db.Model):
    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title               = db.Column(db.String(200), nullable=False)
    description         = db.Column(db.Text)
    start_date          = db.Column(db.DateTime, nullable=False)
    end_date            = db.Column(db.DateTime, nullable=False)
    is_all_day          = db.Column(db.Boolean, default=False)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    recurrence_pattern  = db.Column(db.String(50), nullable=True)
    recurrence_interval = db.Column(db.Integer, default=1)
    recurrence_end_date = db.Column(db.DateTime, nullable=True)
    recurrence_count    = db.Column(db.Integer, nullable=True)
    user = db.relationship('User', backref='unavailabilities')


class RecurringUnavailability(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title           = db.Column(db.String(200), nullable=False)
    description     = db.Column(db.Text)
    start_time      = db.Column(db.String(5), nullable=False)
    end_time        = db.Column(db.String(5), nullable=False)
    pattern_type    = db.Column(db.String(20), nullable=False)
    days_of_week    = db.Column(db.String(50), nullable=True)
    day_of_month    = db.Column(db.Integer, nullable=True)
    start_date      = db.Column(db.DateTime, nullable=False)
    end_date        = db.Column(db.DateTime, nullable=True)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='recurring_unavailabilities')

class EmailOTP(db.Model):
    """Stores active email-based OTP codes for 2FA.
    
    A user may have either TOTP *or* Email OTP enabled — not both simultaneously.
    The 'enabled' flag marks whether email OTP is the user's chosen 2FA method.
    """
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    enabled    = db.Column(db.Boolean, default=False)
    # Transient OTP fields — reset after each use
    otp_code   = db.Column(db.String(8), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    otp_used   = db.Column(db.Boolean, default=True)   # True = no active code
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='email_otp')
