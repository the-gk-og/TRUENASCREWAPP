#import
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import json
import shutil
import csv
import io
import requests
from datetime import datetime, timedelta
import pytz
import secrets
import string
import threading
import discord
from discord.ext import commands
import os
import requests
from dotenv import load_dotenv
from flask import Response
from datetime import datetime, timedelta
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
import barcode
from barcode.writer import ImageWriter
from PIL import Image
import tempfile
from functools import lru_cache
import base64




#setup
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')

# Session configuration for "Remember Me" functionality
# SESSION_DURATION can be set in .env file (e.g., "7d", "1w", "30d", "1h")
# Default is 1 week if not specified
SESSION_DURATION = os.environ.get('SESSION_DURATION', '1w')

def parse_duration(duration_str):
    """
    Parse duration string into timedelta
    Supports: 1d (1 day), 1w (1 week), 1h (1 hour), 30m (30 minutes)
    Examples: "7d", "1w", "2w", "24h", "30m"
    """
    duration_str = duration_str.strip().lower()
    
    try:
        if duration_str.endswith('w'):
            # Weeks
            weeks = int(duration_str[:-1])
            return timedelta(weeks=weeks)
        elif duration_str.endswith('d'):
            # Days
            days = int(duration_str[:-1])
            return timedelta(days=days)
        elif duration_str.endswith('h'):
            # Hours
            hours = int(duration_str[:-1])
            return timedelta(hours=hours)
        elif duration_str.endswith('m'):
            # Minutes
            minutes = int(duration_str[:-1])
            return timedelta(minutes=minutes)
        else:
            # Default to days if no suffix
            days = int(duration_str)
            return timedelta(days=days)
    except (ValueError, AttributeError):
        # Default to 1 week if parsing fails
        print(f"⚠️  Invalid SESSION_DURATION format: '{duration_str}'. Using default 1 week.")
        return timedelta(weeks=1)

# Set session lifetime
app.config['PERMANENT_SESSION_LIFETIME'] = parse_duration(SESSION_DURATION)
app.config['REMEMBER_COOKIE_DURATION'] = parse_duration(SESSION_DURATION)
app.config['REMEMBER_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'

# Session security settings
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///production_crew.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@prodcrew.local')

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')
DISCORD_GUILD_ID = os.environ.get('DISCORD_GUILD_ID', '')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('backups', exist_ok=True)

notification_tracker = {}

# Organization Settings
ORGANIZATION_SLUG = os.environ.get('ORGANIZATION_SLUG', '')
MAIN_SERVER_URL = os.environ.get('MAIN_SERVER_URL', 'https://sfx-crew.com')

# DATABASE MODELS

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    discord_id = db.Column(db.String(50), unique=True, nullable=True)
    discord_username = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_cast = db.Column(db.Boolean, default=False)
    user_role = db.Column(db.String(20), default='crew')  # NEW: 'crew', 'staff', 'cast'


class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    quantity_owned = db.Column(db.Integer, default=1)

    def to_dict(self):
        """Convert Equipment to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'barcode': self.barcode,
            'name': self.name,
            'category': self.category or '',
            'location': self.location or '',
            'notes': self.notes or '',
            'quantity_owned': self.quantity_owned or 1
        }

class PickListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    is_checked = db.Column(db.Boolean, default=False)
    added_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    equipment = db.relationship('Equipment', backref='pick_list_items')

class StagePlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    uploaded_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))
    


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.DateTime, nullable=False)  # Start date/time
    event_end_date = db.Column(db.DateTime, nullable=True)  # End date/time (NEW)
    location = db.Column(db.String(200))
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    discord_message_id = db.Column(db.String(50), nullable=True)
    crew_assignments = db.relationship('CrewAssignment', backref='event', lazy=True, cascade='all, delete-orphan')
    pick_list_items = db.relationship('PickListItem', backref='event', lazy=True, cascade='all, delete-orphan')
    stage_plans = db.relationship('StagePlan', backref='event', lazy=True, cascade='all, delete-orphan')
    cast_description = db.Column(db.Text)



class CrewAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    crew_member = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(100))
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_via = db.Column(db.String(20), default='webapp')

class EventSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)  # Changed from schedule_type to title
    scheduled_time = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('schedules', cascade='all, delete-orphan'))

class EventNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('notes', cascade='all, delete-orphan'))

class TodoItem(db.Model):
    """Personal to-do list items for users"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    is_completed = db.Column(db.Boolean, default=False)
    due_date = db.Column(db.DateTime, nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='todos')
    event = db.relationship('Event', backref='todos')

class CastMember(db.Model):
    """Cast members for productions"""
    id = db.Column(db.Integer, primary_key=True)
    actor_name = db.Column(db.String(200), nullable=False)
    character_name = db.Column(db.String(200), nullable=False)
    role_type = db.Column(db.String(50), default='lead')
    contact_email = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship('Event', backref='cast_members')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='cast_roles')

class CastSchedule(db.Model):
    """Schedule items specifically for cast members"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    scheduled_time = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('cast_schedules', cascade='all, delete-orphan'))

class CastNote(db.Model):
    """Notes specifically for cast members"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('cast_notes', cascade='all, delete-orphan'))

class HiredEquipment(db.Model):
    """Hired/rented equipment tracking"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    supplier = db.Column(db.String(200))
    hire_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime, nullable=False)
    cost = db.Column(db.String(50))
    quantity = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)
    is_returned = db.Column(db.Boolean, default=False)
    returned_at = db.Column(db.DateTime, nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checklist_items = db.relationship('HiredEquipmentCheckItem', backref='hired_equipment', cascade='all, delete-orphan')
    
    event = db.relationship('Event', backref='hired_equipment')

class HiredEquipmentCheckItem(db.Model):
    """Checklist items for hired equipment returns"""
    id = db.Column(db.Integer, primary_key=True)
    hired_equipment_id = db.Column(db.Integer, db.ForeignKey('hired_equipment.id'), nullable=False)
    item_name = db.Column(db.String(200), nullable=False)
    is_checked = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)

class CrewRunItem(db.Model):
    """Run list items for crew (technical cues, setup steps, etc.)"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    order_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.String(50))  # e.g., "5 min", "30 sec"
    cue_type = db.Column(db.String(50))  # e.g., "Lighting", "Sound", "Props", "Stage"
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('crew_run_items', cascade='all, delete-orphan', order_by='CrewRunItem.order_number'))

class CastRunItem(db.Model):
    """Run list items for cast (scenes, songs, entrances, etc.)"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    order_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.String(50))  # e.g., "10 min"
    item_type = db.Column(db.String(50))  # e.g., "Scene", "Song", "Dance", "Intermission"
    cast_involved = db.Column(db.Text)  # Comma-separated list of characters
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship('Event', backref=db.backref('cast_run_items', cascade='all, delete-orphan', order_by='CastRunItem.order_number'))

# ==================== STAGE PLAN DESIGNER ROUTES ====================

# Add these routes to your app.py file

# ==================== STAGE PLAN DESIGNER ROUTES ====================

class StagePlanTemplate(db.Model):
    """Templates for reusable stage plans"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    design_data = db.Column(db.Text, nullable=False)
    thumbnail = db.Column(db.String(300))
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=False)

class StagePlanDesign(db.Model):
    """Saved stage plan designs linked to events"""
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('stage_plan_template.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    design_data = db.Column(db.Text, nullable=False)
    thumbnail = db.Column(db.Text)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    event = db.relationship('Event', backref='stage_designs')
    template = db.relationship('StagePlanTemplate', backref='designs')

class StagePlanObject(db.Model):
    """Library of reusable objects (PNG images)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    image_data = db.Column(db.Text, nullable=False)
    default_width = db.Column(db.Integer, default=100)
    default_height = db.Column(db.Integer, default=100)
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=True)




# LOGIN & UTILITIES

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_functions():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()
    return dict(get_user_by_username=get_user_by_username)

def send_email(subject, recipient, body):
    if not app.config['MAIL_USERNAME']:
        return False
    try:
        msg = Message(subject, recipients=[recipient])
        msg.body = body
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
    return None

def send_discord_event_announcement(event):
    """Send event announcement to Discord immediately when created"""
    if not DISCORD_WEBHOOK_URL:
        return
    
    try:
        embed = {
            "title": f"New Event: {event.title}",
            "description": event.description or "No description provided",
            "color": 6366239,  # Indigo
            "fields": [
                {
                    "name": "📅 Date & Time",
                    "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                    "inline": False
                },
                {
                    "name": "📍 Location",
                    "value": event.location or "TBD",
                    "inline": False
                },
                {
                    "name": "🎟️ Event ID",
                    "value": str(event.id),
                    "inline": True
                }
            ],
            "footer": {"text": f"Event ID: {event.id}"}
        }
        
        response = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        
        if response.status_code == 204:
            # Track that we sent the "created" notification
            if event.id not in notification_tracker:
                notification_tracker[event.id] = {}
            notification_tracker[event.id]['created'] = True
            print(f"✓ Posted new event to Discord: {event.title}")
            return True
    except Exception as e:
        print(f"❌ Error posting event to Discord: {e}")
    
    return None

def schedule_event_notifications(event):
    """Schedule notifications for 1 week before, 1 day before, and on the day"""
    
    def send_timed_notification(event_id, notification_type):
        """Send a timed notification"""
        try:
            # Fetch fresh event data
            event = Event.query.get(event_id)
            if not event:
                return
            
            if not DISCORD_WEBHOOK_URL:
                return
            
            # Get all crew members for this event
            crew_members = [a.crew_member for a in event.crew_assignments]
            
            # Fetch Discord IDs for crew members
            discord_mentions = []
            for crew_name in crew_members:
                user = User.query.filter_by(username=crew_name).first()
                if user and user.discord_id:
                    discord_mentions.append(f"<@{user.discord_id}>")
            
            # Check if we've already sent this notification type for this event
            if event_id not in notification_tracker:
                notification_tracker[event_id] = {}
            
            if notification_type in notification_tracker[event_id]:
                print(f"⏭️  Notification '{notification_type}' already sent for event {event_id} - skipping")
                return
            
            # Create the appropriate embed based on notification type
            if notification_type == '1_week_before':
                embed = {
                    "title": f"📅 Event in 1 Week: {event.title}",
                    "description": "Your event is coming up next week! Be prepared!",
                    "color": 16776960,  # Gold/Yellow
                    "fields": [
                        {
                            "name": "📅 Date & Time",
                            "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                            "inline": False
                        },
                        {
                            "name": "📍 Location",
                            "value": event.location or "TBD",
                            "inline": False
                        },
                        {
                            "name": "🎟️ Event ID",
                            "value": str(event.id),
                            "inline": True
                        }
                    ],
                    "footer": {"text": f"Event ID: {event.id}"}
                }
                mention_text = "⏰ Reminder to assigned crew:"
            
            elif notification_type == '1_day_before':
                embed = {
                    "title": f"⏰ Event Tomorrow: {event.title}",
                    "description": "Your event is happening tomorrow! Get ready!",
                    "color": 16753920,  # Orange
                    "fields": [
                        {
                            "name": "📅 Date & Time",
                            "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                            "inline": False
                        },
                        {
                            "name": "📍 Location",
                            "value": event.location or "TBD",
                            "inline": False
                        },
                        {
                            "name": "🎟️ Event ID",
                            "value": str(event.id),
                            "inline": True
                        }
                    ],
                    "footer": {"text": f"Event ID: {event.id}"}
                }
                mention_text = "🚨 Event tomorrow - assigned crew:"
            
            elif notification_type == 'event_today':
                embed = {
                    "title": f"🎭 EVENT TODAY: {event.title}",
                    "description": "Your event is happening RIGHT NOW!",
                    "color": 16711680,  # Red/Bright
                    "fields": [
                        {
                            "name": "📅 Date & Time",
                            "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'),
                            "inline": False
                        },
                        {
                            "name": "📍 Location",
                            "value": event.location or "TBD",
                            "inline": False
                        },
                        {
                            "name": "🎟️ Event ID",
                            "value": str(event.id),
                            "inline": True
                        }
                    ],
                    "footer": {"text": f"Event ID: {event.id}"}
                }
                mention_text = "🎬 EVENT IS HAPPENING NOW - Assigned crew:"
            
            # Send the message
            content = mention_text
            if discord_mentions:
                content += " " + " ".join(discord_mentions)
            else:
                content = mention_text + " (no crew members linked to Discord)"
            
            payload = {
                "content": content,
                "embeds": [embed]
            }
            
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
            
            if response.status_code == 204:
                notification_tracker[event_id][notification_type] = True
                print(f"✓ Posted {notification_type} notification for event {event_id}: {event.title}")
                return True
            else:
                print(f"❌ Failed to post {notification_type} notification: {response.status_code}")
        
        except Exception as e:
            print(f"❌ Error sending {notification_type} notification: {e}")
    
    # Calculate delays for each notification
    now = datetime.utcnow()
    event_time = event.event_date
    
    # 1 week before
    one_week_before = event_time - timedelta(days=7)
    delay_one_week = (one_week_before - now).total_seconds()
    
    # 1 day before
    one_day_before = event_time - timedelta(days=1)
    delay_one_day = (one_day_before - now).total_seconds()
    
    # On the day (at 8:00 AM of event day)
    event_day_morning = event_time.replace(hour=8, minute=0, second=0, microsecond=0)
    delay_event_day = (event_day_morning - now).total_seconds()
    
    # Schedule notifications only if they're in the future
    if delay_one_week > 0:
        print(f"⏱️  Scheduled '1 week before' notification for event {event.id} in {delay_one_week/3600:.1f} hours")
        timer = threading.Timer(delay_one_week, send_timed_notification, args=[event.id, '1_week_before'])
        timer.daemon = True
        timer.start()
    
    if delay_one_day > 0:
        print(f"⏱️  Scheduled '1 day before' notification for event {event.id} in {delay_one_day/3600:.1f} hours")
        timer = threading.Timer(delay_one_day, send_timed_notification, args=[event.id, '1_day_before'])
        timer.daemon = True
        timer.start()
    
    if delay_event_day > 0:
        print(f"⏱️  Scheduled 'event today' notification for event {event.id} in {delay_event_day/3600:.1f} hours")
        timer = threading.Timer(delay_event_day, send_timed_notification, args=[event.id, 'event_today'])
   

def generate_secure_password(length=32):
    """Generate a cryptographically secure random password"""
    # Use a mix of uppercase, lowercase, digits, and special characters
    characters = string.ascii_letters + string.digits + string.punctuation
    # Remove ambiguous characters like l, 1, O, 0, etc.
    safe_chars = ''.join(c for c in characters if c not in 'l1LO0|`~')
    password = ''.join(secrets.choice(safe_chars) for _ in range(length))
    return password


def send_discord_message(event):
    if not DISCORD_WEBHOOK_URL:
        return None
    try:
        embed = {
            "title": f"🎭 New Event: {event.title}",
            "description": event.description or "No description provided",
            "color": 6366239,
            "fields": [
                {"name": "📅 Date & Time", "value": event.event_date.strftime('%B %d, %Y at %I:%M %p'), "inline": False},
                {"name": "📍 Location", "value": event.location or "TBD", "inline": False},
                #{"name": "👥 How to Join", "value": "React with ✋ to add yourself!", "inline": False}
            ],
            "footer": {"text": f"Event ID: {event.id}"}
        }
        response = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        return response.status_code == 204
    except Exception as e:
        print(f"Failed to send Discord message: {e}")
    return None

def crew_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_cast:
            flash("Access restricted to crew members.")
            return redirect(url_for('cast_events'))  # or another cast-only page
        return f(*args, **kwargs)
    return decorated_function

@lru_cache(maxsize=1)
def get_organization():
    """Fetch organization data from main server with caching"""
    try:
        response = requests.get(
            f"{MAIN_SERVER_URL}/api/organizations/{ORGANIZATION_SLUG}", 
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('organization', {})
        else:
            print(f"Error fetching organization: {response.status_code}")
            return {}
    except Exception as e:
        print(f"Error connecting to main server: {e}")
        return {}

# Fallback organization data if API fails
DEFAULT_ORG = {
    'name': 'ShowWise',
    'slug': 'showwise',
    'tagline': 'Crew Management',
    'primary_color': '#6366f1',
    'secondary_color': '#ec4899',
    'logo': '',
    'website': 'https://sfx-crew.com'
}

# AUTH ROUTES

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect('http://sfx-crew.com')



@app.route('/login', methods=['GET', 'POST'])
def login():

    if current_user.is_authenticated:
        print(f"✓ User {current_user.username} already authenticated, redirecting...")
        
    
        if current_user.is_cast:
            return redirect(url_for('cast_events'))
        else:
            return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', 'off') == 'on'
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            
            if remember:
                from flask import session
                session.permanent = True
                print(f"✓ User {username} logged in with 'Remember Me' for {SESSION_DURATION}")
            else:
                print(f"✓ User {username} logged in (session only)")
            
            # Redirect based on user type
            if user.is_cast:
                return redirect(url_for('cast_events'))
            else:
                return redirect(url_for('dashboard'))
        
        flash('Invalid username or password')
    
    # Fetch organization data
    org = get_organization()
    if not org:
        org = DEFAULT_ORG
    
    # Pass organization, session duration, and current datetime to template
    return render_template('login.html', 
                         organization=org, 
                         SESSION_DURATION=SESSION_DURATION,
                         now=datetime.now())
@app.route('/session-info')
@login_required
def session_info():
    """Show current session information (for debugging)"""
    from flask import session
    
    info = {
        'username': current_user.username,
        'is_permanent': session.permanent,
        'session_duration': SESSION_DURATION,
        'expires_in': str(app.config['PERMANENT_SESSION_LIFETIME']),
        'logged_in': current_user.is_authenticated
    }
    
    return jsonify(info)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
@crew_required
def dashboard():
    upcoming_events = Event.query.filter(Event.event_date >= datetime.now()).order_by(Event.event_date).limit(5).all()
    return render_template('/crew/dashboard.html', upcoming_events=upcoming_events)

# EQUIPMENT ROUTES

@app.route('/equipment')
@login_required
@crew_required
def equipment_list():
    equipment = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    return render_template('/crew/equipment.html', equipment=equipment, equipment_json=equipment_json)

@app.route('/equipment/barcode/<barcode>')
@login_required
@crew_required
def equipment_by_barcode(barcode):
    equipment = Equipment.query.filter_by(barcode=barcode).first()
    if equipment:
        return jsonify(equipment.to_dict())
    return jsonify({'error': 'Equipment not found'}), 404

@app.route('/equipment/add', methods=['POST'])
@login_required
@crew_required
def add_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    equipment = Equipment(barcode=data['barcode'], name=data['name'], category=data.get('category', ''), location=data.get('location', ''), notes=data.get('notes', ''))
    quantity_owned = data.get('quantity_owned', 1)
    db.session.add(equipment)
    db.session.commit()
    return jsonify({'success': True, 'id': equipment.id})

@app.route('/equipment/update/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    equipment = Equipment.query.get_or_404(id)
    data = request.json
    equipment.name = data.get('name', equipment.name)
    equipment.category = data.get('category', equipment.category)
    equipment.location = data.get('location', equipment.location)
    equipment.notes = data.get('notes', equipment.notes)
    equipment.quantity_owned = data.get('quantity_owned', equipment.quantity_owned)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/equipment/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    equipment = Equipment.query.get_or_404(id)
    db.session.delete(equipment)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/equipment/import-csv', methods=['POST'])
@login_required
@crew_required
def import_csv():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    try:
        stream = io.StringIO(file.stream.read().decode('utf8'), newline=None)
        csv_reader = csv.DictReader(stream)
        count = 0
        for row in csv_reader:
            barcode = row.get('barcode') or row.get('Barcode')
            name = row.get('name') or row.get('Name')
            if not barcode or not name:
                continue
            if Equipment.query.filter_by(barcode=barcode).first():
                continue
            equipment = Equipment(barcode=barcode, name=name, category=row.get('category') or row.get('Category') or '', location=row.get('location') or row.get('Location') or '', notes=row.get('notes') or row.get('Notes') or '')
            db.session.add(equipment)
            count += 1
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 400

@app.route('/equipment/import-sheetdb', methods=['POST'])
@login_required
@crew_required
def import_sheetdb():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    sheet_id = data.get('sheet_id')
    if not sheet_id:
        return jsonify({'error': 'Sheet ID required'}), 400
    try:
        url = f"https://api.sheetdb.io/v1/search/{sheet_id}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        rows = response.json()
        count = 0
        for row in rows:
            barcode = row.get('barcode') or row.get('Barcode')
            name = row.get('name') or row.get('Name')
            if not barcode or not name:
                continue
            if Equipment.query.filter_by(barcode=barcode).first():
                continue
            equipment = Equipment(barcode=barcode, name=name, category=row.get('category') or row.get('Category') or '', location=row.get('location') or row.get('Location') or '', notes=row.get('notes') or row.get('Notes') or '')
            db.session.add(equipment)
            count += 1
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 400
    


# Add this route to app.py after the equipment routes

@app.route('/equipment/barcodes')
@login_required
@crew_required
def barcode_page():
    """Barcode generation page"""
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('equipment_list'))
    
    equipment = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    return render_template('crew/barcodes.html', equipment=equipment, equipment_json=equipment_json)

@app.route('/equipment/generate-barcodes', methods=['POST'])
@login_required
@crew_required
def generate_barcodes():
    """Generate printable barcodes for selected equipment"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    try:
        import io
        import os
        import tempfile
        from datetime import datetime
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from barcode import Code128
        from barcode.writer import ImageWriter

        data = request.json
        equipment_ids = data.get('equipment_ids', [])
        barcode_size = data.get('size', 'medium')

        # Debugging output
        print("🔧 Received equipment IDs:", equipment_ids)
        print("📏 Selected barcode size:", barcode_size)

        if not equipment_ids:
            return jsonify({'error': 'No equipment selected'}), 400

        equipment_items = Equipment.query.filter(Equipment.id.in_(equipment_ids)).all()

        if not equipment_items:
            return jsonify({'error': 'No equipment found'}), 404

        # PDF setup
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        page_width, page_height = A4

        # Size configurations
        sizes = {
            'small': (60 * mm, 40 * mm, 8),
            'medium': (80 * mm, 50 * mm, 10),
            'large': (100 * mm, 60 * mm, 12)
        }

        barcode_width, barcode_height, font_size = sizes.get(barcode_size, sizes['medium'])

        # Grid layout
        margin = 10 * mm
        x_spacing = barcode_width + 5 * mm
        y_spacing = barcode_height + 5 * mm

        cols = int((page_width - 2 * margin) / x_spacing)
        rows = int((page_height - 2 * margin) / y_spacing)

        x_start = margin
        y_start = page_height - margin - barcode_height

        current_x = x_start
        current_y = y_start
        item_count = 0

        for item in equipment_items:
            if not item.barcode:
                continue  # Skip items with no barcode

            try:
                # Generate barcode image
                code128 = Code128(item.barcode, writer=ImageWriter())
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                    barcode_path = tmp_file.name[:-4]  # remove ".png"
                    code128.save(barcode_path)
                    image_path = barcode_path + '.png'

                # Draw barcode image
                c.drawImage(image_path, current_x, current_y,
                            width=barcode_width, height=barcode_height - 20 * mm,
                            preserveAspectRatio=True, mask='auto')

                # Draw equipment name
                c.setFont('Helvetica-Bold', font_size)
                text_width = c.stringWidth(item.name, 'Helvetica-Bold', font_size)
                text_x = current_x + (barcode_width - text_width) / 2
                c.drawString(text_x, current_y + barcode_height - 15 * mm, item.name)

                # Draw barcode number
                c.setFont('Helvetica', font_size - 2)
                num_width = c.stringWidth(item.barcode, 'Helvetica', font_size - 2)
                num_x = current_x + (barcode_width - num_width) / 2
                c.drawString(num_x, current_y - 5 * mm, item.barcode)

                # Clean up temp file
                try:
                    os.remove(image_path)
                except Exception as cleanup_error:
                    print(f"Cleanup error: {cleanup_error}")

            except Exception as e:
                print(f"❌ Error drawing barcode for item {item.id}: {e}")
                import traceback
                traceback.print_exc()

            item_count += 1
            current_x += x_spacing

            if item_count % cols == 0:
                current_x = x_start
                current_y -= y_spacing

                if current_y < margin:
                    c.showPage()
                    current_y = y_start

        c.save()
        pdf_buffer.seek(0)

        filename = f"equipment_barcodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"🚨 Barcode generation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

    
# PICKLIST ROUTES

@app.route('/picklist')
@login_required
@crew_required
def picklist():
    event_id = request.args.get('event_id')
    if event_id:
        items = PickListItem.query.filter_by(event_id=event_id).all()
        event = Event.query.get(event_id)
    else:
        items = PickListItem.query.filter_by(event_id=None).all()
        event = None
    events = Event.query.order_by(Event.event_date.desc()).all()
    all_equipment = Equipment.query.all()
    equipment_dict = [e.to_dict() for e in all_equipment]
    
    # Get active hired equipment (not returned)
    hired_equipment = HiredEquipment.query.filter_by(is_returned=False).order_by(HiredEquipment.return_date).all()
    
    return render_template('/crew/picklist.html', 
                         items=items, 
                         events=events, 
                         current_event=event, 
                         all_equipment=all_equipment, 
                         all_equipment_json=equipment_dict,
                         hired_equipment=hired_equipment)

@app.route('/picklist/add', methods=['POST'])
@login_required
@crew_required
def add_picklist_item():
    data = request.json
    equipment_id = data.get('equipment_id')
    if equipment_id:
        equipment = Equipment.query.get(equipment_id)
        if not equipment:
            return jsonify({'error': 'Equipment not found'}), 404
        item = PickListItem(item_name=equipment.name, quantity=data.get('quantity', 1), added_by=current_user.username, event_id=data.get('event_id'), equipment_id=equipment_id)
    else:
        item = PickListItem(item_name=data['item_name'], quantity=data.get('quantity', 1), added_by=current_user.username, event_id=data.get('event_id'), equipment_id=None)
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id})

@app.route('/picklist/toggle/<int:id>', methods=['POST'])
@login_required
@crew_required
def toggle_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    item.is_checked = not item.is_checked
    db.session.commit()
    return jsonify({'success': True, 'is_checked': item.is_checked})

@app.route('/picklist/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})

# STAGE PLANS ROUTES

@app.route('/stageplans')
@login_required
@crew_required
def stageplans():
    event_id = request.args.get('event_id')
    if event_id:
        plans = StagePlan.query.filter_by(event_id=event_id).all()
        event = Event.query.get(event_id)
    else:
        plans = StagePlan.query.all()
        event = None
    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('/crew/stageplans.html', plans=plans, events=events, current_event=event)

@app.route('/stageplans/upload', methods=['POST'])
@login_required
@crew_required
def upload_stageplan():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if file:
        filename = secure_filename(file.filename)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        plan = StagePlan(title=request.form.get('title', filename), filename=filename, uploaded_by=current_user.username, event_id=request.form.get('event_id'))
        db.session.add(plan)
        db.session.commit()
        return jsonify({'success': True, 'id': plan.id})

@app.route('/uploads/<filename>')
@login_required
@crew_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/stageplans/delete/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stageplan(id):
    plan = StagePlan.query.get_or_404(id)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], plan.filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    db.session.delete(plan)
    db.session.commit()
    return jsonify({'success': True})

# CALENDAR ROUTES

@app.route('/calendar')
@login_required
@crew_required
def calendar():
    events = Event.query.order_by(Event.event_date).all()
    now = datetime.now()
    return render_template('/crew/calendar.html', events=events, now=now)


@app.route('/calendar/ics')
def calendar_ics():
    """Generate iCalendar format for ShowWise sync with schedules"""
    events = Event.query.all()

    ical = "BEGIN:VCALENDAR\r\n"
    ical += "VERSION:2.0\r\n"
    ical += "PRODID:-//ShowWise//EN\r\n"
    ical += "CALSCALE:GREGORIAN\r\n"
    ical += "METHOD:PUBLISH\r\n"
    ical += "X-WR-CALNAME:ShowWise sync\r\n"
    ical += "X-WR-TIMEZONE:Australia/Sydney\r\n"
    ical += "REFRESH-INTERVAL;VALUE=DURATION:PT1H\r\n"
    ical += "X-WR-CALDESC:Production events and scheduling\r\n"

    # Add timezone block for Australia/Sydney
    ical += (
        "BEGIN:VTIMEZONE\r\n"
        "TZID:Australia/Sydney\r\n"
        "X-LIC-LOCATION:Australia/Sydney\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:20240407T030000\r\n"
        "TZOFFSETFROM:+1100\r\n"
        "TZOFFSETTO:+1000\r\n"
        "TZNAME:AEST\r\n"
        "END:STANDARD\r\n"
        "BEGIN:DAYLIGHT\r\n"
        "DTSTART:20241006T020000\r\n"
        "TZOFFSETFROM:+1000\r\n"
        "TZOFFSETTO:+1100\r\n"
        "TZNAME:AEDT\r\n"
        "END:DAYLIGHT\r\n"
        "END:VTIMEZONE\r\n"
    )

    for event in events:
        start_time = event.event_date.strftime('%Y%m%dT%H%M%S')
        
        # Calculate end time - check if event has end date, otherwise default to 3 hours after start
        if hasattr(event, 'event_end_date') and event.event_end_date:
            end_time = event.event_end_date.strftime('%Y%m%dT%H%M%S')
        else:
            # Default: 3 hours duration
            end_time = (event.event_date + timedelta(hours=3)).strftime('%Y%m%dT%H%M%S')
        
        created_time = datetime.now().strftime('%Y%m%dT%H%M%S')

        # Escape special characters for iCalendar format
        def ical_escape(text):
            if not text:
                return ''
            return text.replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;').replace('\\', '\\\\')

        title = ical_escape(event.title)
        location = ical_escape(event.location or '')
        
        # Build description with event details and schedules
        description_parts = []
        if event.description:
            description_parts.append(ical_escape(event.description))
        
        # Add schedule information if exists
        if hasattr(event, 'schedules') and event.schedules:
            description_parts.append("\\n\\n--- SCHEDULE ---")
            for schedule in sorted(event.schedules, key=lambda x: x.scheduled_time):
                schedule_time = schedule.scheduled_time.strftime('%I:%M %p')
                schedule_text = f"\\n• {schedule_time} - {ical_escape(schedule.title)}"
                if schedule.description:
                    schedule_text += f": {ical_escape(schedule.description)}"
                description_parts.append(schedule_text)
        
        # Add crew information
        if event.crew_assignments:
            description_parts.append("\\n\\n--- CREW ---")
            for assignment in event.crew_assignments:
                crew_text = f"\\n• {ical_escape(assignment.crew_member)}"
                if assignment.role:
                    crew_text += f" ({ical_escape(assignment.role)})"
                description_parts.append(crew_text)
        
        description = ''.join(description_parts)

        # Main event
        ical += "BEGIN:VEVENT\r\n"
        ical += f"UID:{event.id}-showwise@localhost\r\n"
        ical += f"DTSTAMP;TZID=Australia/Sydney:{created_time}\r\n"
        ical += f"DTSTART;TZID=Australia/Sydney:{start_time}\r\n"
        ical += f"DTEND;TZID=Australia/Sydney:{end_time}\r\n"
        ical += f"SUMMARY:{title}\r\n"

        if description:
            ical += f"DESCRIPTION:{description}\r\n"
        if location:
            ical += f"LOCATION:{location}\r\n"

        ical += "STATUS:CONFIRMED\r\n"
        ical += "END:VEVENT\r\n"
        
        # Add individual schedule items as separate events (optional - you can remove this if you prefer them only in description)
        if hasattr(event, 'schedules') and event.schedules:
            for idx, schedule in enumerate(event.schedules):
                schedule_start = schedule.scheduled_time.strftime('%Y%m%dT%H%M%S')
                # Schedule events are 30 minutes by default
                schedule_end = (schedule.scheduled_time + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%S')
                
                ical += "BEGIN:VEVENT\r\n"
                ical += f"UID:{event.id}-schedule-{schedule.id}@localhost\r\n"
                ical += f"DTSTAMP;TZID=Australia/Sydney:{created_time}\r\n"
                ical += f"DTSTART;TZID=Australia/Sydney:{schedule_start}\r\n"
                ical += f"DTEND;TZID=Australia/Sydney:{schedule_end}\r\n"
                ical += f"SUMMARY:{ical_escape(event.title)} - {ical_escape(schedule.title)}\r\n"
                
                if schedule.description:
                    ical += f"DESCRIPTION:{ical_escape(schedule.description)}\r\n"
                if location:
                    ical += f"LOCATION:{location}\r\n"
                
                ical += "STATUS:CONFIRMED\r\n"
                ical += f"RELATED-TO:{event.id}-showwise@localhost\r\n"  # Link to main event
                ical += "END:VEVENT\r\n"

    ical += "END:VCALENDAR\r\n"

    return Response(ical, mimetype='text/calendar', headers={
        'Content-Disposition': 'inline; filename="showwise_sync.ics"',
        'Cache-Control': 'no-cache, must-revalidate'
    })

  
# EVENT ROUTES
@app.route('/events/add', methods=['POST'])
@login_required
@crew_required
def add_event():
    data = request.json
    
    # Parse dates
    start_date = datetime.fromisoformat(data['event_date'])
    
    # Handle end date - if not provided, default to 3 hours after start
    if data.get('event_end_date'):
        end_date = datetime.fromisoformat(data['event_end_date'])
    else:
        end_date = start_date + timedelta(hours=3)
    
    event = Event(
        title=data['title'],
        description=data.get('description', ''),
        event_date=start_date,
        event_end_date=end_date,
        location=data.get('location', ''),
        created_by=current_user.username
    )
    db.session.add(event)
    db.session.commit()
    
    # Send Discord notification and schedule reminders
    send_discord_event_announcement(event)
    schedule_event_notifications(event)
    
    return jsonify({'success': True, 'id': event.id})


@app.route('/events/<int:id>', methods=['GET'])
@login_required
@crew_required
def event_detail(id):
    event = Event.query.get_or_404(id)
    all_users = User.query.all()
    schedules = EventSchedule.query.filter_by(event_id=id).order_by(EventSchedule.scheduled_time).all()
    return render_template('/crew/event_detail.html', event=event, all_users=all_users, schedules=schedules)

@app.route('/events/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_event(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})

# EVENT SCHEDULING ROUTES 

@app.route('/events/<int:event_id>/schedule/add', methods=['POST'])
@login_required
@crew_required
def add_event_schedule(event_id):
    """Add a schedule item to an event"""
    event = Event.query.get_or_404(event_id)
    data = request.json
    
    try:
        # Parse the datetime correctly
        scheduled_time = datetime.fromisoformat(data['scheduled_time'])
        
        schedule = EventSchedule(
            event_id=event_id,
            title=data.get('title', ''),
            scheduled_time=scheduled_time,
            description=data.get('description', ''),
        )
        
        db.session.add(schedule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'id': schedule.id,
            'scheduled_time': schedule.scheduled_time.isoformat()
        })
    except Exception as e:
        db.session.rollback()
        print(f"Schedule add error: {e}")
        return jsonify({'error': str(e)}), 400


@app.route('/events/<int:id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event(id):
    event = Event.query.get_or_404(id)
    data = request.json
    
    event.title = data.get('title', event.title)
    event.description = data.get('description', event.description)
    event.location = data.get('location', event.location)
    
    if data.get('event_date'):
        event.event_date = datetime.fromisoformat(data['event_date'])
    
    if data.get('event_end_date'):
        event.event_end_date = datetime.fromisoformat(data['event_end_date'])
    elif data.get('event_date'):
        # If start date changed but no end date provided, update end date to maintain 3-hour duration
        event.event_end_date = event.event_date + timedelta(hours=3)
    
    db.session.commit()
    return jsonify({'success': True})



@app.route('/events/schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_event_schedule(schedule_id):
    """Delete a schedule item"""
    schedule = EventSchedule.query.get_or_404(schedule_id)
    
    try:
        db.session.delete(schedule)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Schedule delete error: {e}")
        return jsonify({'error': str(e)}), 400
    
# CREW ROUTES

@app.route('/crew/assign', methods=['POST'])
@login_required
@crew_required
def assign_crew():
    data = request.json
    assignment = CrewAssignment(event_id=data['event_id'], crew_member=data['crew_member'], role=data.get('role', ''), assigned_via='webapp')
    db.session.add(assignment)
    db.session.commit()
    
    # Send email notification if user has email
    user = User.query.filter_by(username=data['crew_member']).first()
    event = Event.query.get(data['event_id'])
    if user and user.email and event:
        subject = f"🎭 You're assigned to: {event.title}"
        body = f"""Hello {user.username},

You have been assigned to an upcoming production event!

📋 Event Details:
  • Event: {event.title}
  • Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
  • Location: {event.location or 'TBD'}
  • Your Role: {data.get('role', 'Crew Member')}

📝 Description: {event.description or 'No description'}

Please log in to the Production Crew Management System to view:
  • Pick lists for items to gather
  • Stage plans for setup
  • Other crew members assigned to this event
  • Event details and updates

Let me know if you have any questions!

Best regards,
Production Crew System"""
        send_email(subject, user.email, body)
    
    return jsonify({'success': True, 'id': assignment.id})

@app.route('/crew/remove/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def remove_crew(id):
    assignment = CrewAssignment.query.get_or_404(id)
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/crew/resend-notification', methods=['POST'])
@login_required
@crew_required
def resend_notification():
    data = request.json
    assignment = CrewAssignment.query.get(data.get('assignment_id'))
    event = Event.query.get(data.get('event_id'))
    
    if not assignment or not event:
        return jsonify({'error': 'Not found'}), 404
    
    user = User.query.filter_by(username=assignment.crew_member).first()
    if user and user.email:
        subject = f"Reminder: {event.title}"
        body = f"""Hello {user.username},

This is a reminder that you're assigned to:

📋 Event: {event.title}
📅 Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
📍 Location: {event.location or 'TBD'}
👤 Your Role: {assignment.role or 'Crew Member'}

See you there!

ShowWise System"""
        send_email(subject, user.email, body)
        return jsonify({'success': True})
    
    return jsonify({'error': 'User has no email'}), 400

# DISCORD ROUTES

@app.route('/discord-settings')
@login_required
@crew_required
def discord_settings():
    return render_template('/crew/discord_settings.html')

@app.route('/settings/link-discord', methods=['POST'])
@login_required
@crew_required
def link_discord():
    data = request.json
    discord_id = data.get('discord_id')
    discord_username = data.get('discord_username')
    if discord_id is None and discord_username is None:
        current_user.discord_id = None
        current_user.discord_username = None
        db.session.commit()
        return jsonify({'success': True})
    if not discord_id or not discord_username:
        return jsonify({'error': 'Required fields missing'}), 400
    current_user.discord_id = discord_id
    current_user.discord_username = discord_username
    db.session.commit()
    return jsonify({'success': True})

@app.route('/settings/discord-status')
@login_required
@crew_required
def discord_status():
    if current_user.discord_id:
        return jsonify({'linked': True, 'discord_id': current_user.discord_id, 'discord_username': current_user.discord_username})
    return jsonify({'linked': False})

@app.route('/discord/join-event', methods=['POST'])
def discord_join_event():
    data = request.json
    if data.get('secret') != os.environ.get('DISCORD_BOT_SECRET', 'change-this-secret'):
        return jsonify({'error': 'Unauthorized'}), 401
    event_id = data.get('event_id')
    discord_id = data.get('discord_id')
    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404
    user = User.query.filter_by(discord_id=discord_id).first()
    if not user:
        return jsonify({'error': 'Discord account not linked'}), 400
    existing = CrewAssignment.query.filter_by(event_id=event_id, crew_member=user.username).first()
    if existing:
        return jsonify({'error': 'Already assigned'}), 400
    assignment = CrewAssignment(event_id=event_id, crew_member=user.username, assigned_via='discord')
    db.session.add(assignment)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/discord/link-existing', methods=['POST'])
def discord_link_existing():
    """Link Discord to existing account"""
    data = request.json
    if data.get('secret') != os.environ.get('DISCORD_BOT_SECRET', 'change-this-secret'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = data.get('username')
    password = data.get('password')
    discord_id = data.get('discord_id')
    discord_username = data.get('discord_username')
    
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid username or password'}), 401
    
    user.discord_id = discord_id
    user.discord_username = discord_username
    db.session.commit()
    
    return jsonify({'success': True, 'username': username})

@app.route('/discord/check-link/<discord_id>')
def discord_check_link(discord_id):
    """Check if a Discord ID is linked"""
    user = User.query.filter_by(discord_id=discord_id).first()
    
    if user:
        event_count = CrewAssignment.query.filter_by(crew_member=user.username).count()
        return jsonify({
            'linked': True,
            'username': user.username,
            'event_count': event_count
        })
    
    return jsonify({'linked': False}), 404

@app.route('/discord/user-events/<discord_id>')
def discord_user_events(discord_id):
    """Get user's events"""
    user = User.query.filter_by(discord_id=discord_id).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    assignments = CrewAssignment.query.filter_by(crew_member=user.username).all()
    events = []
    for assignment in assignments:
        event = Event.query.get(assignment.event_id)
        if event:
            events.append({'id': event.id, 'title': event.title, 'date': event.event_date.strftime('%B %d, %Y at %I:%M %p'), 'location': event.location or 'TBD', 'role': assignment.role or 'Crew Member'})
    return jsonify({'events': events})

@app.route('/discord/create-account', methods=['POST'])
def discord_create_account():
    """Create new account from Discord"""
    data = request.json
    if data.get('secret') != os.environ.get('DISCORD_BOT_SECRET'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = data.get('username')
    password = data.get('password')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    user = User(username=username, password_hash=generate_password_hash(password), is_admin=False)
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'username': username})

@app.route('/discord/search-equipment/<query>')
def discord_search_equipment(query):
    """Search equipment"""
    equipment = Equipment.query.filter(
        (Equipment.name.contains(query)) | (Equipment.barcode.contains(query))
    ).limit(10).all()
    return jsonify({'equipment': [e.to_dict() for e in equipment]})

@app.route('/discord/list-events')
def discord_list_events():
    """List upcoming events"""
    events = Event.query.filter(Event.event_date >= datetime.now()).order_by(Event.event_date).limit(10).all()
    return jsonify({'events': [{'id': e.id, 'title': e.title, 'date': e.event_date.strftime('%B %d, %Y at %I:%M %p'), 'location': e.location or 'TBD', 'crew_count': len(e.crew_assignments)} for e in events]})

@app.route('/discord/event-crew/<int:event_id>')
def discord_event_crew(event_id):
    """Get crew for event"""
    event = Event.query.get_or_404(event_id)
    return jsonify({'event_title': event.title, 'crew': [{'name': a.crew_member, 'role': a.role or 'Crew Member'} for a in event.crew_assignments]})

@app.route('/discord/add-event', methods=['POST'])
def discord_add_event():
    """Create event from Discord"""
    data = request.json
    if data.get('secret') != os.environ.get('DISCORD_BOT_SECRET'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        event_date = datetime.strptime(data['date'], '%Y-%m-%d %H:%M')
        event = Event(title=data['title'], event_date=event_date, location=data.get('location', 'TBD'), created_by='Discord Bot')
        db.session.add(event)
        db.session.commit()
        send_discord_message(event)
        return jsonify({'success': True, 'event_id': event.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/discord/leave-event', methods=['POST'])
def discord_leave_event():
    """Leave event"""
    data = request.json
    if data.get('secret') != os.environ.get('DISCORD_BOT_SECRET'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    event_id = data.get('event_id')
    discord_id = data.get('discord_id')
    
    user = User.query.filter_by(discord_id=discord_id).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    assignment = CrewAssignment.query.filter_by(event_id=event_id, crew_member=user.username).first()
    
    if assignment:
        db.session.delete(assignment)
        db.session.commit()
    
    return jsonify({'success': True})

@app.route('/discord/pick-list/<int:event_id>')
def discord_pick_list(event_id):
    """Get pick list for event (Discord API)"""
    event = Event.query.get_or_404(event_id)
    items = PickListItem.query.filter_by(event_id=event_id).all()
    
    items_data = []
    for item in items:
        items_data.append({
            'id': item.id,
            'name': item.item_name,
            'quantity': item.quantity,
            'is_checked': item.is_checked,
            'location': item.equipment.location if item.equipment else 'N/A',
            'category': item.equipment.category if item.equipment else 'N/A'
        })
    
    return jsonify({
        'event_title': event.title,
        'items': items_data
    })


# ADMIN ROUTES

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))

    raw_users = User.query.all()

    # Serialize users for JSON and template rendering
    users = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_cast": user.is_cast,
            "created_at": user.created_at.strftime('%b %d, %Y') if user.created_at else "N/A",
            "discord_username": user.discord_username,
            "is_admin": user.is_admin,
            "user_role": user.user_role
        }
        for user in raw_users
    ]

    return render_template('admin/admin.html', users=users)


@app.route('/admin/users/add', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username exists'}), 400
    
    user_role = data.get('user_role', 'crew')
    is_cast = user_role == 'cast'
    
    user = User(
        username=data['username'], 
        email=data.get('email'), 
        password_hash=generate_password_hash(data['password']), 
        is_admin=data.get('is_admin', False),
        is_cast=is_cast,
        user_role=user_role
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/users/delete/<int:id>', methods=['DELETE'])
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

@app.route('/admin/backup', methods=['POST'])
@login_required
def backup_database():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    try:
        os.makedirs('backups', exist_ok=True)
        backup_filename = f"production_crew_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        backup_path = os.path.join('backups', backup_filename)
        shutil.copy('production_crew.db', backup_path)
        return jsonify({'success': True, 'filename': backup_filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/download-backup/<filename>')
@login_required
def download_backup(filename):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Verify filename is safe
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    backup_path = os.path.join('backups', filename)
    if not os.path.exists(backup_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(backup_path, as_attachment=True, download_name=filename, mimetype='application/octet-stream')

@app.route('/admin/restore', methods=['POST'])
@login_required
def restore_database():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    try:
        file.save('production_crew_restore.db')
        shutil.copy('production_crew_restore.db', 'production_crew.db')
        os.remove('production_crew_restore.db')
        return jsonify({'success': True, 'message': 'Database restored'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/backups')
@login_required
def list_backups():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    os.makedirs('backups', exist_ok=True)
    backups = []
    for file in os.listdir('backups'):
        if file.endswith('.db'):
            path = os.path.join('backups', file)
            backups.append({'name': file, 'size': os.path.getsize(path), 'date': datetime.fromtimestamp(os.path.getmtime(path)).isoformat()})
    return jsonify(backups)

@app.route('/admin/users/edit/<int:id>', methods=['PUT'])
@login_required
def edit_user(id):
    """Edit user data (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    user = User.query.get_or_404(id)
    data = request.json
    
    print(f"\n=== EDITING USER {id} ===")
    print(f"Current user_role: {getattr(user, 'user_role', 'NOT SET')}")
    print(f"Data received: {data}")
    
    # Update username if provided and changed
    if data.get('username') and data['username'] != user.username:
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400
        user.username = data['username']
        print(f"Updated username to: {user.username}")
    
    # Update email if provided
    if data.get('email') is not None:
        if data['email'] and data['email'] != user.email:
            if User.query.filter_by(email=data['email']).first():
                return jsonify({'error': 'Email already in use'}), 400
            user.email = data['email'].strip() if data['email'].strip() else None
        elif not data['email']:
            user.email = None
        print(f"Updated email to: {user.email}")
    
    # Update discord if provided
    if 'discord_id' in data:
        user.discord_id = data.get('discord_id').strip() if data.get('discord_id') else None
        user.discord_username = data.get('discord_username').strip() if data.get('discord_username') else None
        print(f"Updated discord to: {user.discord_username}")
    
    # Update password if provided
    if data.get('password') and len(data['password']) > 0:
        if len(data['password']) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        user.password_hash = generate_password_hash(data['password'])
        print("Updated password")
    
    # Update role
    if 'user_role' in data:
        print(f"Attempting to update user_role from '{getattr(user, 'user_role', 'NOT SET')}' to '{data['user_role']}'")
        
        # Check if the column exists
        try:
            user.user_role = data['user_role']
            user.is_cast = (data['user_role'] == 'cast')
            print(f"Successfully set user_role to: {user.user_role}")
        except Exception as e:
            print(f"ERROR setting user_role: {e}")
            return jsonify({'error': f'Database error: {str(e)}. Did you run the migration script?'}), 500
    
    # Update admin status if provided
    if 'is_admin' in data:
        if id == current_user.id and not data['is_admin']:
            return jsonify({'error': 'Cannot remove your own admin privileges'}), 403
        user.is_admin = data['is_admin']
        print(f"Updated is_admin to: {user.is_admin}")
    
    try:
        db.session.commit()
        print(f"✓ Committed changes. Final user_role: {getattr(user, 'user_role', 'NOT SET')}")
        print("=== END EDIT ===\n")
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        db.session.rollback()
        print(f"✗ Commit failed: {e}")
        print("=== END EDIT ===\n")
        return jsonify({'error': str(e)}), 500
    

@app.route('/admin/users/get/<int:id>', methods=['GET'])
@login_required
def get_user(id):
    """Get user data for editing (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    user = User.query.get_or_404(id)
    return jsonify({
        'id': user.id,
        'username': user.username,
        'email': user.email or '',
        'discord_id': user.discord_id or '',
        'discord_username': user.discord_username or '',
        'is_admin': user.is_admin,
        'user_role': user.user_role
    })



@app.route('/crew/assign-all', methods=['POST'])
@login_required
@crew_required
def assign_all_crew():
    """Assign all crew members to an event"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    event_id = data.get('event_id')
    
    event = Event.query.get_or_404(event_id)
    
    # Get all users who are crew (not cast, not staff-only)
    crew_users = User.query.filter(
        User.user_role.in_(['crew', 'crew_admin'])
    ).all()
    
    added_count = 0
    for user in crew_users:
        # Check if already assigned
        existing = CrewAssignment.query.filter_by(
            event_id=event_id, 
            crew_member=user.username
        ).first()
        
        if not existing:
            assignment = CrewAssignment(
                event_id=event_id,
                crew_member=user.username,
                role='Crew Member',
                assigned_via='webapp'
            )
            db.session.add(assignment)
            added_count += 1
            
            # Send email notification
            if user.email:
                subject = f"🎭 You're assigned to: {event.title}"
                body = f"""Hello {user.username},

You have been assigned to an upcoming production event!

📋 Event Details:
  • Event: {event.title}
  • Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
  • Location: {event.location or 'TBD'}
  • Your Role: Crew Member

Please log in to ShowWise to view full event details.

Best regards,
ShowWise System"""
                send_email(subject, user.email, body)
    
    db.session.commit()
    return jsonify({'success': True, 'added': added_count})

# DATABASE INIT

def init_db():
    with app.app_context():
        db.create_all()
        
        # Check if admin user already exists
        existing_admin = User.query.filter_by(username='admin').first()
        
        if not existing_admin:
            # Generate a secure random password
            admin_password = generate_secure_password(32)
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash(admin_password),
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
            
            # Print to terminal with clear formatting
            print("\n" + "="*80)
            print("🎭 PRODUCTION CREW MANAGEMENT SYSTEM - INITIALIZATION")
            print("="*80)
            print("\n✓ Database initialized successfully!")
            print("\n" + "-"*80)
            print("📋 DEFAULT ADMIN ACCOUNT CREATED")
            print("-"*80)
            print(f"\n  Username: admin")
            print(f"  Password: {admin_password}\n")
            print("-"*80)
            print("\n⚠️  IMPORTANT SECURITY NOTES:")
            print("   • Save this password in a secure location")
            print("   • Change this password immediately after first login")
            print("   • Do not share this password")
            print("   • Each admin should have their own account\n")
            print("="*80 + "\n")
        else:
            print("✓ Admin user already exists - skipping initialization")

# PDF EXPORT ROUTE
# Replace the /events/<int:event_id>/export-pdf route in app.py with this FIXED version

from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from io import BytesIO
import os
import re
from datetime import datetime

@app.route('/events/<int:event_id>/export-pdf')
@login_required
@crew_required
def export_event_pdf(event_id):
    """Export modern event brief to PDF with proper text wrapping"""
    try:
        event = Event.query.get_or_404(event_id)

        # Custom header/footer
        def add_header_footer(canvas, doc):
            canvas.saveState()
            
            # Header - Modern gradient bar
            canvas.setFillColorRGB(0.39, 0.49, 0.94)  # Primary color
            canvas.rect(0, letter[1] - 40, letter[0], 40, fill=True, stroke=False)
            
            # Header text
            canvas.setFillColorRGB(1, 1, 1)
            canvas.setFont('Helvetica-Bold', 16)
            canvas.drawString(20 * mm, letter[1] - 25, "EVENT BRIEF")
            
            canvas.setFont('Helvetica', 10)
            canvas.drawRightString(letter[0] - 20 * mm, letter[1] - 25, f"Event ID: {event.id}")
            
            # Footer
            canvas.setFillColorRGB(0.5, 0.5, 0.5)
            canvas.setFont('Helvetica', 8)
            canvas.drawString(20 * mm, 15 * mm, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
            canvas.drawRightString(letter[0] - 20 * mm, 15 * mm, f"Page {canvas.getPageNumber()}")
            
            # Footer line
            canvas.setStrokeColorRGB(0.8, 0.8, 0.8)
            canvas.setLineWidth(0.5)
            canvas.line(20 * mm, 20 * mm, letter[0] - 20 * mm, 20 * mm)
            
            canvas.restoreState()

        # Create PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer, 
            pagesize=letter,
            topMargin=50,
            bottomMargin=30,
            leftMargin=20*mm,
            rightMargin=20*mm
        )
        
        story = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=colors.HexColor('#6366f1'),
            spaceAfter=8,
            spaceBefore=20,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )

        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#6b7280'),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )

        section_header_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1f2937'),
            spaceAfter=12,
            spaceBefore=20,
            fontName='Helvetica-Bold',
            leftIndent=0
        )

        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor('#374151'),
            fontName='Helvetica'
        )

        # Style for wrapping text in tables
        wrapped_style = ParagraphStyle(
            'WrappedText',
            parent=styles['Normal'],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#374151'),
            fontName='Helvetica',
            wordWrap='CJK'
        )

        small_wrapped_style = ParagraphStyle(
            'SmallWrapped',
            parent=styles['Normal'],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor('#4b5563'),
            fontName='Helvetica',
            wordWrap='CJK'
        )

        note_header_style = ParagraphStyle(
            'NoteHeader',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#78350f'),
            fontName='Helvetica-Bold',
            wordWrap='CJK'
        )

        note_body_style = ParagraphStyle(
            'NoteBody',
            parent=styles['Normal'],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#78350f'),
            fontName='Helvetica',
            wordWrap='CJK'
        )

        highlight_style = ParagraphStyle(
            'Highlight',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#1f2937'),
            fontName='Helvetica-Bold',
            leftIndent=10
        )

        # Title
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph(event.title, title_style))
        
        # Subtitle with date
        subtitle_text = f"{event.event_date.strftime('%A, %B %d, %Y')}"
        story.append(Paragraph(subtitle_text, subtitle_style))
        
        # Decorative line
        story.append(HRFlowable(
            width="100%",
            thickness=2,
            color=colors.HexColor('#e5e7eb'),
            spaceBefore=10,
            spaceAfter=20
        ))

        # ==================== EVENT OVERVIEW ====================
        story.append(Paragraph("EVENT OVERVIEW", section_header_style))
        
        overview_data = []
        
        # Time information
        start_time = event.event_date.strftime('%I:%M %p')
        if hasattr(event, 'event_end_date') and event.event_end_date:
            end_time = event.event_end_date.strftime('%I:%M %p')
            duration = (event.event_end_date - event.event_date).total_seconds() / 3600
            time_info = f"{start_time} - {end_time} ({duration:.1f} hours)"
        else:
            time_info = f"{start_time} (Duration: TBD)"
        
        overview_data.append([Paragraph('<b>Time:</b>', body_style), Paragraph(time_info, body_style)])
        overview_data.append([Paragraph('<b>Location:</b>', body_style), Paragraph(event.location or 'To Be Determined', body_style)])
        overview_data.append([Paragraph('<b>Created By:</b>', body_style), Paragraph(event.created_by or 'N/A', body_style)])
        overview_data.append([Paragraph('<b>Created:</b>', body_style), Paragraph(event.created_at.strftime('%B %d, %Y'), body_style)])
        
        overview_table = Table(overview_data, colWidths=[1.5*inch, 4.5*inch])
        overview_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1f2937')),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        story.append(overview_table)
        story.append(Spacer(1, 0.2*inch))

        # Description
        if event.description:
            story.append(Paragraph("DESCRIPTION", section_header_style))
            # Replace newlines with <br/> tags for proper formatting
            desc_text = event.description.replace('\n', '<br/>')
            story.append(Paragraph(desc_text, body_style))
            story.append(Spacer(1, 0.2*inch))

        # ==================== EVENT SCHEDULE ====================
        if hasattr(event, 'schedules') and event.schedules:
            story.append(Paragraph("EVENT SCHEDULE", section_header_style))
            
            schedule_data = [[
                Paragraph('<b>Time</b>', wrapped_style),
                Paragraph('<b>Activity</b>', wrapped_style),
                Paragraph('<b>Details</b>', wrapped_style)
            ]]
            
            for schedule in sorted(event.schedules, key=lambda x: x.scheduled_time):
                time_str = schedule.scheduled_time.strftime('%I:%M %p')
                
                # Wrap long descriptions properly
                desc_text = schedule.description or ''
                
                schedule_data.append([
                    Paragraph(time_str, wrapped_style),
                    Paragraph(schedule.title, wrapped_style),
                    Paragraph(desc_text, small_wrapped_style)
                ])
            
            schedule_table = Table(schedule_data, colWidths=[1*inch, 1.8*inch, 3.2*inch])
            schedule_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f3f4f6')])
            ]))
            story.append(schedule_table)
            story.append(Spacer(1, 0.2*inch))

        # ==================== EVENT NOTES ====================
        if hasattr(event, 'notes') and event.notes:
            story.append(Paragraph("EVENT NOTES", section_header_style))
            
            for note in sorted(event.notes, key=lambda x: x.created_at, reverse=True):
                # Create note content with proper wrapping
                note_header = f"<b>{note.created_by}</b> • {note.created_at.strftime('%b %d, %Y at %I:%M %p')}"
                
                note_data = [[
                    Paragraph(note_header, note_header_style)
                ], [
                    Paragraph(note.content, note_body_style)
                ]]
                
                note_table = Table(note_data, colWidths=[5.8*inch])
                note_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fef3c7')),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#78350f')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                    ('LEFTPADDING', (0, 0), (-1, -1), 12),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#fbbf24')),
                ]))
                story.append(note_table)
                story.append(Spacer(1, 0.1*inch))
            
            story.append(Spacer(1, 0.1*inch))

        # ==================== CREW ASSIGNMENTS ====================
        if hasattr(event, 'crew_assignments') and event.crew_assignments:
            story.append(Paragraph("CREW ASSIGNMENTS", section_header_style))
            
            crew_data = [[
                Paragraph('<b>Crew Member</b>', wrapped_style),
                Paragraph('<b>Role</b>', wrapped_style),
                Paragraph('<b>Contact</b>', wrapped_style)
            ]]
            
            for assignment in event.crew_assignments:
                user = User.query.filter_by(username=assignment.crew_member).first()
                email = user.email if user and user.email else 'N/A'
                crew_data.append([
                    Paragraph(assignment.crew_member, wrapped_style),
                    Paragraph(assignment.role or 'Crew Member', wrapped_style),
                    Paragraph(email, small_wrapped_style)
                ])
            
            crew_table = Table(crew_data, colWidths=[2*inch, 2*inch, 2*inch])
            crew_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ec4899')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fce7f3')])
            ]))
            story.append(crew_table)
            story.append(Spacer(1, 0.2*inch))

        # ==================== PICK LIST ====================
        if hasattr(event, 'pick_list_items') and event.pick_list_items:
            story.append(Paragraph("EQUIPMENT PICK LIST", section_header_style))
            
            checked_count = sum(1 for item in event.pick_list_items if item.is_checked)
            total_count = len(event.pick_list_items)
            progress_text = f"Progress: {checked_count}/{total_count} items gathered"
            story.append(Paragraph(progress_text, highlight_style))
            story.append(Spacer(1, 0.1*inch))
            
            picklist_data = [[
                Paragraph('<b>✓</b>', wrapped_style),
                Paragraph('<b>Item</b>', wrapped_style),
                Paragraph('<b>Qty</b>', wrapped_style),
                Paragraph('<b>Location</b>', wrapped_style),
                Paragraph('<b>Category</b>', wrapped_style)
            ]]
            
            for item in event.pick_list_items:
                checkbox = '✓' if item.is_checked else '☐'
                location = item.equipment.location if item.equipment else 'N/A'
                category = item.equipment.category if item.equipment else 'N/A'
                picklist_data.append([
                    Paragraph(checkbox, wrapped_style),
                    Paragraph(item.item_name, wrapped_style),
                    Paragraph(str(item.quantity), wrapped_style),
                    Paragraph(location, small_wrapped_style),
                    Paragraph(category, small_wrapped_style)
                ])
            
            picklist_table = Table(picklist_data, colWidths=[0.4*inch, 2.2*inch, 0.6*inch, 1.6*inch, 1.2*inch])
            picklist_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ecfdf5')])
            ]))
            story.append(picklist_table)
            story.append(Spacer(1, 0.2*inch))

        # ==================== STAGE PLANS ====================
        if hasattr(event, 'stage_plans') and event.stage_plans:
            story.append(PageBreak())
            story.append(Paragraph("STAGE PLANS", section_header_style))
            
            for plan in event.stage_plans:
                story.append(Paragraph(f"<b>{plan.title}</b>", highlight_style))
                story.append(Paragraph(f"Uploaded by {plan.uploaded_by} on {plan.created_at.strftime('%b %d, %Y')}", body_style))
                story.append(Spacer(1, 0.1*inch))
                
                image_file = os.path.join('uploads', plan.filename)
                if os.path.exists(image_file) and plan.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    try:
                        img = Image(image_file, width=5.5*inch, height=3.5*inch)
                        img.hAlign = 'CENTER'
                        story.append(img)
                    except:
                        story.append(Paragraph("Image could not be loaded", body_style))
                else:
                    story.append(Paragraph(f"File: {plan.filename} (not displayed)", body_style))
                
                story.append(Spacer(1, 0.3*inch))

        # Build PDF
        doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
        pdf_buffer.seek(0)

        # Generate filename
        safe_title = re.sub(r'\W+', '_', event.title)
        filename = f"{safe_title}_Event_Brief_{event.event_date.strftime('%Y%m%d')}.pdf"

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except ImportError as e:
        print(f"Import error: {e}")
        return jsonify({'error': 'reportlab not installed. Run: pip install reportlab'}), 500
    except Exception as e:
        print(f"PDF export error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500            
#note routs

@app.route('/events/<int:event_id>/notes/add', methods=['POST'])
@login_required
@crew_required
def add_event_note(event_id):
    """Add a note to an event"""
    event = Event.query.get_or_404(event_id)
    data = request.json
    
    note = EventNote(
        event_id=event_id,
        content=data['content'],
        created_by=current_user.username
    )
    db.session.add(note)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': note.id,
        'note': {
            'id': note.id,
            'content': note.content,
            'created_by': note.created_by,
            'created_at': note.created_at.strftime('%b %d, %Y at %I:%M %p')
        }
    })

@app.route('/events/notes/<int:note_id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event_note(note_id):
    """Edit an event note"""
    note = EventNote.query.get_or_404(note_id)
    data = request.json
    
    note.content = data['content']
    note.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/events/notes/<int:note_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_event_note(note_id):
    """Delete an event note"""
    note = EventNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({'success': True})

# ==================== ADMIN OVERVIEW ====================
@app.route('/admin/overview')
@login_required
@crew_required
def admin_overview():
    """Enhanced overview dashboard for admins/teachers"""
    if not current_user.is_admin:
        flash('Admin access required')
        return redirect(url_for('dashboard'))
    
    # Get statistics
    total_users = User.query.count()
    total_equipment = Equipment.query.count()
    total_events = Event.query.count()
    
    # Upcoming events with crew counts
    upcoming_events = Event.query.filter(
        Event.event_date >= datetime.now()
    ).order_by(Event.event_date).limit(10).all()
    
    # Recent activity (last 7 days)
    week_ago = datetime.now() - timedelta(days=7)
    recent_users = User.query.filter(User.created_at >= week_ago).count()
    recent_equipment = Equipment.query.filter(Equipment.created_at >= week_ago).count()
    recent_events = Event.query.filter(Event.created_at >= week_ago).count()
    
    # Active crew members (assigned to upcoming events)
    active_crew = db.session.query(CrewAssignment.crew_member).join(Event).filter(
        Event.event_date >= datetime.now()
    ).distinct().count()
    
    # Equipment usage statistics
    equipment_usage = db.session.query(
        Equipment.category,
        db.func.count(PickListItem.id).label('usage_count')
    ).outerjoin(PickListItem).group_by(Equipment.category).all()
    
    return render_template('/admin/admin_overview.html',
        total_users=total_users,
        total_equipment=total_equipment,
        total_events=total_events,
        upcoming_events=upcoming_events,
        recent_users=recent_users,
        recent_equipment=recent_equipment,
        recent_events=recent_events,
        active_crew=active_crew,
        equipment_usage=equipment_usage
    )

# ==================== EXPORT EVENTS ====================
@app.route('/admin/export-events')
@login_required
@crew_required
def export_events_csv():
    """Export all events with crew members to CSV"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Event Title', 'Date', 'Time', 'Location', 'Crew Member', 'Role', 'Email', 'Status'])
    
    # Get all events with crew
    events = Event.query.order_by(Event.event_date).all()
    
    for event in events:
        if event.crew_assignments:
            for assignment in event.crew_assignments:
                user = User.query.filter_by(username=assignment.crew_member).first()
                writer.writerow([
                    event.title,
                    event.event_date.strftime('%Y-%m-%d'),
                    event.event_date.strftime('%I:%M %p'),
                    event.location or 'N/A',
                    assignment.crew_member,
                    assignment.role or 'Crew Member',
                    user.email if user and user.email else 'N/A',
                    'Upcoming' if event.event_date >= datetime.now() else 'Past'
                ])
        else:
            # Event with no crew
            writer.writerow([
                event.title,
                event.event_date.strftime('%Y-%m-%d'),
                event.event_date.strftime('%I:%M %p'),
                event.location or 'N/A',
                'No crew assigned',
                '',
                '',
                'Upcoming' if event.event_date >= datetime.now() else 'Past'
            ])
    
    # Prepare response
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=events_crew_{datetime.now().strftime("%Y%m%d")}.csv'}
    )

# ==================== TO-DO LIST ROUTES ====================
@app.route('/todos')
@login_required
@crew_required
def todos():
    """User's personal to-do list"""
    user_todos = TodoItem.query.filter_by(user_id=current_user.id).order_by(
        TodoItem.is_completed.asc(),
        TodoItem.priority.desc(),
        TodoItem.due_date.asc()
    ).all()
    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('/crew/todos.html', todos=user_todos, events=events)

@app.route('/todos/add', methods=['POST'])
@login_required
@crew_required
def add_todo():
    """Add a new to-do item"""
    data = request.json
    todo = TodoItem(
        user_id=current_user.id,
        title=data['title'],
        description=data.get('description', ''),
        priority=data.get('priority', 'medium'),
        due_date=datetime.fromisoformat(data['due_date']) if data.get('due_date') else None,
        event_id=data.get('event_id')
    )
    db.session.add(todo)
    db.session.commit()
    return jsonify({'success': True, 'id': todo.id})

@app.route('/todos/<int:id>/toggle', methods=['POST'])
@login_required
@crew_required
def toggle_todo(id):
    """Toggle to-do completion status"""
    todo = TodoItem.query.get_or_404(id)
    if todo.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    todo.is_completed = not todo.is_completed
    todo.completed_at = datetime.utcnow() if todo.is_completed else None
    db.session.commit()
    return jsonify({'success': True, 'is_completed': todo.is_completed})

@app.route('/todos/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_todo(id):
    """Delete a to-do item"""
    todo = TodoItem.query.get_or_404(id)
    if todo.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(todo)
    db.session.commit()
    return jsonify({'success': True})

# ==================== CAST MANAGEMENT ROUTES ====================
@app.route('/cast')
@login_required
@crew_required
def cast_list():
    """View all cast members"""
    cast_members = CastMember.query.order_by(CastMember.character_name).all()
    events = Event.query.order_by(Event.event_date.desc()).all()
    
    # Convert to JSON for JavaScript
    cast_json = [{
        'id': c.id,
        'actor_name': c.actor_name,
        'character_name': c.character_name,
        'role_type': c.role_type,
        'contact_email': c.contact_email,
        'contact_phone': c.contact_phone,
        'notes': c.notes,
        'event_id': c.event_id
    } for c in cast_members]
    
    return render_template('/cast/cast.html', cast_members=cast_members, events=events, cast_json=cast_json)



@app.route('/cast/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_cast(id):
    """Update cast member"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    cast = CastMember.query.get_or_404(id)
    data = request.json
    
    cast.actor_name = data.get('actor_name', cast.actor_name)
    cast.character_name = data.get('character_name', cast.character_name)
    cast.role_type = data.get('role_type', cast.role_type)
    cast.contact_email = data.get('contact_email', cast.contact_email)
    cast.contact_phone = data.get('contact_phone', cast.contact_phone)
    cast.notes = data.get('notes', cast.notes)
    cast.event_id = data.get('event_id', cast.event_id)
    
    db.session.commit()
    return jsonify({'success0': True})

@app.route('/cast/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_cast(id):
    """Delete cast member"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    cast = CastMember.query.get_or_404(id)
    db.session.delete(cast)
    db.session.commit()
    return jsonify({'success': True})





        
    

# Add these routes to your app.py

# ==================== CAST DASHBOARD ====================
@app.route('/cast-events')
@login_required
def cast_events():
    """Events page for cast members - shows only their events"""
    if not current_user.is_cast and not current_user.is_admin:
        flash('Cast access required')
        return redirect(url_for('dashboard'))
    
    # Get events where user is cast member
    if current_user.is_admin:
        # Admins see all events
        events = Event.query.order_by(Event.event_date).all()
    else:
        # Cast members see only their events
        events = Event.query.join(CastMember).filter(
            CastMember.user_id == current_user.id
        ).order_by(Event.event_date).all()
    
    now = datetime.now()
    return render_template('/cast/cast_events.html', events=events, now=now)

# ==================== CAST EVENT DETAIL ====================
@app.route('/cast-events/<int:id>')
@login_required
def cast_event_detail(id):
    """Event detail page for cast members"""
    if not current_user.is_cast and not current_user.is_admin:
        flash('Cast access required')
        return redirect(url_for('dashboard'))
    
    event = Event.query.get_or_404(id)
    
    # Check if user is cast in this event (unless admin)
    if not current_user.is_admin:
        cast_member = CastMember.query.filter_by(
            event_id=id,
            user_id=current_user.id
        ).first()
        
        if not cast_member:
            flash('You are not cast in this event')
            return redirect(url_for('/cast/cast_events'))
    else:
        cast_member = None
    
    # Get cast-specific data
    cast_schedules = CastSchedule.query.filter_by(event_id=id).order_by(CastSchedule.scheduled_time).all()
    cast_notes = CastNote.query.filter_by(event_id=id).order_by(CastNote.created_at.desc()).all()
    cast_members = CastMember.query.filter_by(event_id=id).all()
    
    return render_template('/cast/cast_event_detail.html', 
                         event=event, 
                         cast_member=cast_member,
                         cast_schedules=cast_schedules,
                         cast_notes=cast_notes,
                         cast_members=cast_members)

# ==================== ADMIN: CREATE CAST ACCOUNT ====================
@app.route('/cast/create-account', methods=['POST'])
@login_required
@crew_required
def create_cast_account():
    """Create a new cast member account (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    # Check if username already exists
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    # Create user with cast access
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        email=email,
        is_cast=True,
        is_admin=False
    )
    db.session.add(user)
    db.session.commit()
    
    # Send welcome email if email provided
    if email:
        subject = "🎭 Welcome to ShowWise Cast Portal"
        body = f"""Hello {username},

Welcome to the ShowWise Cast Portal!

Your account has been created by your production team.

Login Credentials:
  • Username: {username}
  • Password: {password}

IMPORTANT: Please change your password after your first login.

You can now access:
  • Your production schedules
  • Cast-specific notes and information
  • Call times and rehearsal information
  • Communication with the production team

Login at: {request.url_root}login

Break a leg!
ShowWise Production Team"""
        send_email(subject, email, body)
    
    return jsonify({'success': True, 'user_id': user.id, 'username': username})

# ==================== ADMIN: UPDATE CAST/EVENT LINKING ====================
@app.route('/cast/add', methods=['POST'])
@login_required
def add_cast():
    """Add a cast member to an event (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    
    # Get the user by username or user_id
    user = None
    if data.get('user_id'):
        user = User.query.get(data['user_id'])
    elif data.get('actor_name'):
        user = User.query.filter_by(username=data['actor_name']).first()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Ensure user has cast access
    if not user.is_cast:
        user.is_cast = True
    
    # Create cast member record
    cast = CastMember(
        actor_name=user.username,
        character_name=data['character_name'],
        role_type=data.get('role_type', 'lead'),
        contact_email=data.get('contact_email') or user.email,
        contact_phone=data.get('contact_phone'),
        notes=data.get('notes', ''),
        event_id=data.get('event_id'),
        user_id=user.id
    )
    db.session.add(cast)
    db.session.commit()
    
    # Send notification if event specified
    if cast.event_id and user.email:
        event = Event.query.get(cast.event_id)
        subject = f"🎭 You've been cast in: {event.title}"
        body = f"""Hello {user.username},

You have been cast in an upcoming production!

📋 Production Details:
  • Event: {event.title}
  • Character: {cast.character_name}
  • Role: {cast.role_type}
  • Date: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
  • Location: {event.location or 'TBD'}

Login to ShowWise Cast Portal to view:
  • Cast-specific schedules and call times
  • Production notes
  • Your character information

Break a leg!
ShowWise Production Team"""
        send_email(subject, user.email, body)
    
    return jsonify({'success': True, 'id': cast.id})

# ==================== ADMIN: CAST SCHEDULE MANAGEMENT ====================
@app.route('/events/<int:event_id>/cast-schedule/add', methods=['POST'])
@login_required
def add_cast_schedule(event_id):
    """Add cast schedule item (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    
    try:
        scheduled_time = datetime.fromisoformat(data['scheduled_time'])
        
        schedule = CastSchedule(
            event_id=event_id,
            title=data.get('title', ''),
            scheduled_time=scheduled_time,
            description=data.get('description', ''),
        )
        
        db.session.add(schedule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'id': schedule.id,
            'scheduled_time': schedule.scheduled_time.isoformat()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@app.route('/events/cast-schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_schedule(schedule_id):
    """Delete cast schedule item (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    schedule = CastSchedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    
    return jsonify({'success': True})

# ==================== ADMIN: CAST NOTE MANAGEMENT ====================
@app.route('/events/<int:event_id>/cast-notes/add', methods=['POST'])
@login_required
def add_cast_note(event_id):
    """Add cast note (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    
    note = CastNote(
        event_id=event_id,
        content=data['content'],
        created_by=current_user.username
    )
    db.session.add(note)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': note.id,
        'note': {
            'id': note.id,
            'content': note.content,
            'created_by': note.created_by,
            'created_at': note.created_at.strftime('%b %d, %Y at %I:%M %p')
        }
    })

@app.route('/events/cast-notes/<int:note_id>/edit', methods=['PUT'])
@login_required
def edit_cast_note(note_id):
    """Edit cast note (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    note = CastNote.query.get_or_404(note_id)
    data = request.json
    
    note.content = data['content']
    note.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/events/cast-notes/<int:note_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_note(note_id):
    """Delete cast note (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    note = CastNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({'success': True})

# ==================== ADMIN: UPDATE EVENT CAST DESCRIPTION ====================
@app.route('/events/<int:id>/edit-cast', methods=['PUT'])
@login_required
def edit_event_cast(id):
    """Update cast-specific event details (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    event = Event.query.get_or_404(id)
    data = request.json
    
    event.cast_description = data.get('cast_description', event.cast_description)
    
    db.session.commit()
    return jsonify({'success': True})

# ==================== GET ALL CAST USERS (for admin dropdown) ====================
@app.route('/cast/users')
@login_required
def get_cast_users():
    """Get all users with cast access (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    cast_users = User.query.filter_by(is_cast=True).all()
    return jsonify({
        'users': [{
            'id': u.id,
            'username': u.username,
            'email': u.email
        } for u in cast_users]
    })

# Add these routes to app.py

# ==================== CHANGE PASSWORD ====================
@app.route('/change-password')
@login_required
def change_password_page():
    """Password change page for all users"""
    return render_template('/crew/change_password.html')

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Handle password change request"""
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')
    
    # Validation
    if not current_password or not new_password or not confirm_password:
        return jsonify({'error': 'All fields are required'}), 400
    
    # Check current password
    if not check_password_hash(current_user.password_hash, current_password):
        return jsonify({'error': 'Current password is incorrect'}), 400
    
    # Check new password length
    if len(new_password) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    
    # Check passwords match
    if new_password != confirm_password:
        return jsonify({'error': 'New passwords do not match'}), 400
    
    # Check new password is different
    if current_password == new_password:
        return jsonify({'error': 'New password must be different from current password'}), 400
    
    # Update password
    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    
    # Send confirmation email if email exists
    if current_user.email:
        subject = "Password Changed - ShowWise"
        body = f"""Hello {current_user.username},

Your ShowWise password has been successfully changed.

If you did not make this change, please contact your administrator immediately.

Changed at: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

ShowWise Team"""
        send_email(subject, current_user.email, body)
    
    return jsonify({'success': True, 'message': 'Password changed successfully'})

# ==================== HIRED EQUIPMENT ROUTES ====================

from datetime import datetime, timedelta


@app.route('/hired-equipment')
@login_required
def hired_equipment_list():
    """View all hired equipment"""
    hired = HiredEquipment.query.order_by(HiredEquipment.return_date).all()
    events = Event.query.order_by(Event.event_date.desc()).all()
    
    active_hired = [h for h in hired if not h.is_returned]
    returned_hired = [h for h in hired if h.is_returned]

    hired_json = [{
        'id': h.id,
        'name': h.name,
        'supplier': h.supplier,
        'hire_date': h.hire_date.isoformat(),
        'return_date': h.return_date.isoformat(),
        'cost': h.cost,
        'quantity': h.quantity,
        'notes': h.notes,
        'is_returned': h.is_returned,
        'event_id': h.event_id
    } for h in hired]

    upcoming_threshold = datetime.now() + timedelta(days=7)

    return render_template(
        'crew/hired_equipment.html',
        active_hired=active_hired,
        returned_hired=returned_hired,
        events=events,
        hired_json=hired_json,
        upcoming_threshold=upcoming_threshold,
        now=datetime.now()  # 👈 Add this line
    )


@app.route('/hired-equipment/add', methods=['POST'])
@login_required
def add_hired_equipment():
    """Add hired equipment"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    hired = HiredEquipment(
        name=data['name'],
        supplier=data.get('supplier', ''),
        hire_date=datetime.fromisoformat(data['hire_date']),
        return_date=datetime.fromisoformat(data['return_date']),
        cost=data.get('cost', ''),
        quantity=data.get('quantity', 1),
        notes=data.get('notes', ''),
        event_id=data.get('event_id')
    )
    db.session.add(hired)
    db.session.commit()
    
    # Add default checklist items
    default_items = [
        'All items present',
        'No damage',
        'Clean condition',
        'All accessories included',
        'Documentation returned'
    ]
    
    for item_name in default_items:
        check_item = HiredEquipmentCheckItem(
            hired_equipment_id=hired.id,
            item_name=item_name
        )
        db.session.add(check_item)
    
    db.session.commit()
    return jsonify({'success': True, 'id': hired.id})

@app.route('/hired-equipment/<int:id>', methods=['PUT'])
@login_required
def update_hired_equipment(id):
    """Update hired equipment"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    hired = HiredEquipment.query.get_or_404(id)
    data = request.json
    
    hired.name = data.get('name', hired.name)
    hired.supplier = data.get('supplier', hired.supplier)
    hired.hire_date = datetime.fromisoformat(data['hire_date']) if data.get('hire_date') else hired.hire_date
    hired.return_date = datetime.fromisoformat(data['return_date']) if data.get('return_date') else hired.return_date
    hired.cost = data.get('cost', hired.cost)
    hired.quantity = data.get('quantity', hired.quantity)
    hired.notes = data.get('notes', hired.notes)
    hired.event_id = data.get('event_id', hired.event_id)
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/hired-equipment/<int:id>', methods=['DELETE'])
@login_required
def delete_hired_equipment(id):
    """Delete hired equipment"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    hired = HiredEquipment.query.get_or_404(id)
    db.session.delete(hired)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/hired-equipment/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_hired():
    """Delete multiple hired equipment items"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        data = request.json
        ids = data.get('ids', [])
        
        print(f"Received bulk delete request for IDs: {ids}")  # Debug log
        
        if not ids:
            return jsonify({'error': 'No items selected'}), 400
        
        # Delete items one by one to ensure cascade works
        deleted_count = 0
        for item_id in ids:
            item = HiredEquipment.query.get(item_id)
            if item:
                db.session.delete(item)
                deleted_count += 1
        
        db.session.commit()
        print(f"Successfully deleted {deleted_count} items")  # Debug log
        
        return jsonify({'success': True, 'deleted': deleted_count})
    
    except Exception as e:
        db.session.rollback()
        print(f"Error in bulk delete: {str(e)}")  # Debug log
        return jsonify({'error': str(e)}), 500

@app.route('/hired-equipment/<int:id>/return', methods=['POST'])
@login_required
def mark_hired_returned(id):
    """Mark hired equipment as returned"""
    hired = HiredEquipment.query.get_or_404(id)
    hired.is_returned = True
    hired.returned_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})

@app.route('/hired-equipment/<int:id>/checklist/toggle/<int:item_id>', methods=['POST'])
@login_required
def toggle_hired_checklist(id, item_id):
    """Toggle checklist item"""
    item = HiredEquipmentCheckItem.query.get_or_404(item_id)
    item.is_checked = not item.is_checked
    db.session.commit()
    return jsonify({'success': True, 'is_checked': item.is_checked})

@app.route('/hired-equipment/<int:id>/checklist/add', methods=['POST'])
@login_required
def add_hired_checklist_item(id):
    """Add custom checklist item"""
    data = request.json
    item = HiredEquipmentCheckItem(
        hired_equipment_id=id,
        item_name=data['item_name'],
        notes=data.get('notes', '')
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id})

@app.route('/hired-equipment/import-csv', methods=['POST'])
@login_required
def import_hired_csv():
    """Import hired equipment from CSV"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        stream = io.StringIO(file.stream.read().decode('utf8'), newline=None)
        csv_reader = csv.DictReader(stream)
        count = 0
        
        for row in csv_reader:
            name = row.get('name') or row.get('Name')
            hire_date = row.get('hire_date') or row.get('Hire Date')
            return_date = row.get('return_date') or row.get('Return Date')
            
            if not name or not hire_date or not return_date:
                continue
            
            hired = HiredEquipment(
                name=name,
                supplier=row.get('supplier') or row.get('Supplier') or '',
                hire_date=datetime.strptime(hire_date, '%Y-%m-%d'),
                return_date=datetime.strptime(return_date, '%Y-%m-%d'),
                cost=row.get('cost') or row.get('Cost') or '',
                quantity=int(row.get('quantity') or row.get('Quantity') or 1),
                notes=row.get('notes') or row.get('Notes') or ''
            )
            db.session.add(hired)
            count += 1
        
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 400


# ==================== EQUIPMENT QUANTITY TRACKING ====================

@app.route('/hired-equipment/<int:id>/checklist', methods=['GET'])
@login_required
def get_hired_checklist(id):
    """Get checklist items for hired equipment"""
    items = HiredEquipmentCheckItem.query.filter_by(hired_equipment_id=id).all()
    return jsonify([{
        'id': item.id,
        'item_name': item.item_name,
        'is_checked': item.is_checked,
        'notes': item.notes or ''
    } for item in items])

@app.route('/equipment/<int:id>/quantity-check', methods=['POST'])
@login_required
def check_equipment_quantity(id):
    """Check if equipment quantity is available"""
    equipment = Equipment.query.get_or_404(id)
    data = request.json
    requested_qty = data.get('quantity', 1)
    
    # Count how many are already allocated in active pick lists
    allocated = db.session.query(db.func.sum(PickListItem.quantity)).filter(
        PickListItem.equipment_id == id,
        PickListItem.is_checked == False
    ).scalar() or 0
    
    owned = equipment.quantity_owned if hasattr(equipment, 'quantity_owned') else 999
    available = owned - allocated
    
    return jsonify({
        'owned': owned,
        'allocated': allocated,
        'available': available,
        'requested': requested_qty,
        'warning': requested_qty > available
    })

# Add these routes to app.py

# ==================== CREW RUN LIST ROUTES ====================

@app.route('/events/<int:event_id>/crew-run/add', methods=['POST'])
@login_required

def add_crew_run_item(event_id):
    """Add crew run list item (admin/crew)"""
    event = Event.query.get_or_404(event_id)
    data = request.json
    
    # Get the highest order number
    max_order = db.session.query(db.func.max(CrewRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    
    run_item = CrewRunItem(
        event_id=event_id,
        order_number=max_order + 1,
        title=data['title'],
        description=data.get('description', ''),
        duration=data.get('duration', ''),
        cue_type=data.get('cue_type', ''),
        notes=data.get('notes', '')
    )
    
    db.session.add(run_item)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': run_item.id,
        'order_number': run_item.order_number
    })

@app.route('/events/crew-run/<int:item_id>/edit', methods=['PUT'])
@login_required

def edit_crew_run_item(item_id):
    """Edit crew run list item"""
    item = CrewRunItem.query.get_or_404(item_id)
    data = request.json
    
    item.title = data.get('title', item.title)
    item.description = data.get('description', item.description)
    item.duration = data.get('duration', item.duration)
    item.cue_type = data.get('cue_type', item.cue_type)
    item.notes = data.get('notes', item.notes)
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/crew-run/<int:item_id>/delete', methods=['DELETE'])
@login_required

def delete_crew_run_item(item_id):
    """Delete crew run list item"""
    item = CrewRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    order = item.order_number
    
    db.session.delete(item)
    
    # Reorder remaining items
    items_to_reorder = CrewRunItem.query.filter(
        CrewRunItem.event_id == event_id,
        CrewRunItem.order_number > order
    ).all()
    
    for item in items_to_reorder:
        item.order_number -= 1
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/<int:event_id>/crew-run/reorder', methods=['POST'])
@login_required

def reorder_crew_run_items(event_id):
    """Reorder crew run list items"""
    data = request.json
    item_ids = data.get('item_ids', [])
    
    for index, item_id in enumerate(item_ids, start=1):
        item = CrewRunItem.query.get(item_id)
        if item and item.event_id == event_id:
            item.order_number = index
    
    db.session.commit()
    return jsonify({'success': True})

# ==================== CAST RUN LIST ROUTES ====================

@app.route('/events/<int:event_id>/cast-run/add', methods=['POST'])
@login_required
def add_cast_run_item(event_id):
    """Add cast run list item (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    event = Event.query.get_or_404(event_id)
    data = request.json
    
    # Get the highest order number
    max_order = db.session.query(db.func.max(CastRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    
    run_item = CastRunItem(
        event_id=event_id,
        order_number=max_order + 1,
        title=data['title'],
        description=data.get('description', ''),
        duration=data.get('duration', ''),
        item_type=data.get('item_type', ''),
        cast_involved=data.get('cast_involved', ''),
        notes=data.get('notes', '')
    )
    
    db.session.add(run_item)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': run_item.id,
        'order_number': run_item.order_number
    })

@app.route('/events/cast-run/<int:item_id>/edit', methods=['PUT'])
@login_required
def edit_cast_run_item(item_id):
    """Edit cast run list item (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    item = CastRunItem.query.get_or_404(item_id)
    data = request.json
    
    item.title = data.get('title', item.title)
    item.description = data.get('description', item.description)
    item.duration = data.get('duration', item.duration)
    item.item_type = data.get('item_type', item.item_type)
    item.cast_involved = data.get('cast_involved', item.cast_involved)
    item.notes = data.get('notes', item.notes)
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/cast-run/<int:item_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_run_item(item_id):
    """Delete cast run list item (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    item = CastRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    order = item.order_number
    
    db.session.delete(item)
    
    # Reorder remaining items
    items_to_reorder = CastRunItem.query.filter(
        CastRunItem.event_id == event_id,
        CastRunItem.order_number > order
    ).all()
    
    for item in items_to_reorder:
        item.order_number -= 1
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/<int:event_id>/cast-run/reorder', methods=['POST'])
@login_required
def reorder_cast_run_items(event_id):
    """Reorder cast run list items (admin only)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    item_ids = data.get('item_ids', [])
    
    for index, item_id in enumerate(item_ids, start=1):
        item = CastRunItem.query.get(item_id)
        if item and item.event_id == event_id:
            item.order_number = index
    
    db.session.commit()
    return jsonify({'success': True})




# ==================== STAGE PLAN DESIGNER ROUTES ====================
# Add ALL these routes BEFORE the "if __name__ == '__main__':" line
@app.route('/stage-designer')
@login_required
@crew_required
def stage_designer():
    """Main stage plan designer interface"""
    events = Event.query.order_by(Event.event_date.desc()).all()
    templates = StagePlanTemplate.query.filter(
        (StagePlanTemplate.is_public == True) | 
        (StagePlanTemplate.created_by == current_user.username)
    ).order_by(StagePlanTemplate.created_at.desc()).all()
    
    objects = StagePlanObject.query.filter(
        (StagePlanObject.is_public == True) | 
        (StagePlanObject.created_by == current_user.username)
    ).order_by(StagePlanObject.category, StagePlanObject.name).all()
    
    return render_template('crew/stage_designer.html', 
                         events=events, 
                         templates=templates,
                         objects=objects)

# DESIGN ROUTES
@app.route('/stage-designer/design', methods=['POST'])
@login_required
@crew_required
def create_stage_design():
    """Create new stage plan design"""
    try:
        data = request.json
        print(f"Creating design: {data.get('name')}")
        
        # Save thumbnail to file if provided
        thumbnail_filename = None
        if data.get('thumbnail'):
            try:
                # Extract base64 image data
                thumbnail_data = data['thumbnail'].split(',')[1] if ',' in data['thumbnail'] else data['thumbnail']
                thumbnail_bytes = base64.b64decode(thumbnail_data)
                
                # Generate filename
                safe_name = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in data['name'])
                thumbnail_filename = f"designer_thumb_{int(datetime.now().timestamp())}_{safe_name}.png"
                thumbnail_path = os.path.join(app.config['UPLOAD_FOLDER'], thumbnail_filename)
                
                # Save thumbnail
                with open(thumbnail_path, 'wb') as f:
                    f.write(thumbnail_bytes)
                
                print(f"✓ Saved thumbnail: {thumbnail_filename}")
            except Exception as e:
                print(f"⚠️ Could not save thumbnail: {e}")
        
        design = StagePlanDesign(
            name=data['name'],
            design_data=json.dumps(data['design_data']),
            thumbnail=thumbnail_filename,  # Store filename instead of data URL
            event_id=data.get('event_id'),
            created_by=current_user.username
        )
        db.session.add(design)
        db.session.flush()
        
        # Save to Stage Plans if requested
        if data.get('save_to_stageplans'):
            try:
                safe_name = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in data['name'])
                filename = f"designer_{design.id}_{safe_name}.json"
                
                stage_plan = StagePlan(
                    title=data['name'],
                    filename=thumbnail_filename if thumbnail_filename else filename,  # Use thumbnail as filename
                    uploaded_by=current_user.username,
                    event_id=data.get('event_id')
                )
                db.session.add(stage_plan)
                print(f"✓ Created stage plan entry: {stage_plan.title}")
            except Exception as e:
                print(f"⚠️ Could not create stage plan entry: {e}")
        
        db.session.commit()
        
        print(f"Design created successfully with ID: {design.id}")
        return jsonify({'success': True, 'design_id': design.id})
    except Exception as e:
        db.session.rollback()
        print(f"Error creating design: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/stage-designer/design/<int:id>', methods=['PUT'])
@login_required
@crew_required
def update_stage_design(id):
    """Update existing stage plan design"""
    try:
        design = StagePlanDesign.query.get_or_404(id)
        data = request.json
        
        print(f"Updating design {id}: {data.get('name')}")
        
        # Update thumbnail if provided
        thumbnail_filename = design.thumbnail
        if data.get('thumbnail'):
            try:
                # Delete old thumbnail if exists
                if design.thumbnail and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], design.thumbnail)):
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], design.thumbnail))
                
                # Save new thumbnail
                thumbnail_data = data['thumbnail'].split(',')[1] if ',' in data['thumbnail'] else data['thumbnail']
                thumbnail_bytes = base64.b64decode(thumbnail_data)
                
                safe_name = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in data['name'])
                thumbnail_filename = f"designer_thumb_{int(datetime.now().timestamp())}_{safe_name}.png"
                thumbnail_path = os.path.join(app.config['UPLOAD_FOLDER'], thumbnail_filename)
                
                with open(thumbnail_path, 'wb') as f:
                    f.write(thumbnail_bytes)
                
                print(f"✓ Updated thumbnail: {thumbnail_filename}")
            except Exception as e:
                print(f"⚠️ Could not update thumbnail: {e}")
        
        design.name = data.get('name', design.name)
        design.design_data = json.dumps(data['design_data'])
        design.thumbnail = thumbnail_filename
        design.event_id = data.get('event_id')
        design.updated_at = datetime.utcnow()
        
        # Update associated stage plan if it exists
        if data.get('save_to_stageplans'):
            stage_plan = StagePlan.query.filter(
                StagePlan.filename.like(f'designer_%') & 
                (StagePlan.uploaded_by == current_user.username)
            ).filter(
                StagePlan.title == design.name
            ).first()
            
            if stage_plan:
                stage_plan.title = design.name
                stage_plan.event_id = design.event_id
                stage_plan.filename = thumbnail_filename if thumbnail_filename else stage_plan.filename
                print(f"✓ Updated stage plan entry")
            else:
                safe_name = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in design.name)
                filename = thumbnail_filename if thumbnail_filename else f"designer_{design.id}_{safe_name}.json"
                
                stage_plan = StagePlan(
                    title=design.name,
                    filename=filename,
                    uploaded_by=current_user.username,
                    event_id=design.event_id
                )
                db.session.add(stage_plan)
                print(f"✓ Created new stage plan entry")
        
        db.session.commit()
        
        print(f"Design {id} updated successfully")
        return jsonify({'success': True, 'design_id': design.id})
    except Exception as e:
        db.session.rollback()
        print(f"Error updating design: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/stage-designer/designs')
@login_required
@crew_required
def list_stage_designs():
    """List all stage plan designs"""
    try:
        designs = StagePlanDesign.query.order_by(StagePlanDesign.updated_at.desc()).all()
        return jsonify([{
            'id': d.id,
            'name': d.name,
            'event_id': d.event_id,
            'event_name': d.event.title if d.event else None,
            'thumbnail': url_for('uploaded_file', filename=d.thumbnail) if d.thumbnail else None,
            'created_by': d.created_by,
            'created_at': d.created_at.isoformat(),
            'updated_at': d.updated_at.isoformat(),
            'description': d.event.description if d.event else None
        } for d in designs])
    except Exception as e:
        print(f"Error listing designs: {e}")
        return jsonify([])

@app.route('/stage-designer/design/<int:id>/data')
@login_required
@crew_required
def get_stage_design(id):
    """Get design data for editing"""
    try:
        design = StagePlanDesign.query.get_or_404(id)
        return jsonify({
            'id': design.id,
            'name': design.name,
            'design_data': json.loads(design.design_data),
            'event_id': design.event_id,
            'thumbnail': design.thumbnail
        })
    except Exception as e:
        print(f"Error getting design {id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stage-designer/design/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_design(id):
    """Delete a stage plan design"""
    try:
        design = StagePlanDesign.query.get_or_404(id)
        db.session.delete(design)
        db.session.commit()
        print(f"Design {id} deleted")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting design {id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# TEMPLATE ROUTES
@app.route('/stage-designer/template', methods=['POST'])
@login_required
@crew_required
def save_stage_template():
    """Save design as template (ADMIN ONLY)"""
    if not current_user.is_admin:
        print(f"User {current_user.username} tried to save template without admin access")
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        data = request.json
        print(f"Saving template: {data.get('name')}")
        
        template = StagePlanTemplate(
            name=data['name'],
            description=data.get('description', ''),
            design_data=json.dumps(data['design_data']),
            thumbnail=data.get('thumbnail'),
            created_by=current_user.username,
            is_public=data.get('is_public', True)
        )
        db.session.add(template)
        db.session.commit()
        
        print(f"Template created successfully with ID: {template.id}")
        return jsonify({'success': True, 'id': template.id})
    except Exception as e:
        db.session.rollback()
        print(f"Error saving template: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/stage-designer/templates')
@login_required
@crew_required
def get_stage_templates():
    """Get all templates"""
    try:
        templates = StagePlanTemplate.query.filter(
            (StagePlanTemplate.is_public == True) | 
            (StagePlanTemplate.created_by == current_user.username)
        ).order_by(StagePlanTemplate.created_at.desc()).all()
        
        return jsonify([{
            'id': t.id,
            'name': t.name,
            'description': t.description,
            'thumbnail': url_for('uploaded_file', filename=t.thumbnail) if t.thumbnail else None,
            'created_by': t.created_by,
            'created_at': t.created_at.isoformat()
        } for t in templates])
    except Exception as e:
        print(f"Error getting templates: {e}")
        return jsonify([])

@app.route('/stage-designer/template/<int:id>/data')
@login_required
@crew_required
def get_stage_template(id):
    """Get template data"""
    try:
        template = StagePlanTemplate.query.get_or_404(id)
        return jsonify({
            'id': template.id,
            'name': template.name,
            'design_data': json.loads(template.design_data)
        })
    except Exception as e:
        print(f"Error getting template {id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stage-designer/template/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_template(id):
    """Delete a template (ADMIN ONLY)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        template = StagePlanTemplate.query.get_or_404(id)
        db.session.delete(template)
        db.session.commit()
        print(f"Template {id} deleted")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting template {id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# OBJECT LIBRARY ROUTES
@app.route('/stage-designer/object', methods=['POST'])
@login_required
@crew_required
def upload_stage_object():
    """Upload a new object to the library (ADMIN ONLY)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        data = request.json
        print(f"Uploading object: {data.get('name')}")
        
        obj = StagePlanObject(
            name=data['name'],
            category=data.get('category', 'Uncategorized'),
            image_data=data['image_data'],
            default_width=data.get('default_width', 100),
            default_height=data.get('default_height', 100),
            created_by=current_user.username,
            is_public=data.get('is_public', True)
        )
        db.session.add(obj)
        db.session.commit()
        
        print(f"Object created successfully with ID: {obj.id}")
        return jsonify({'success': True, 'id': obj.id})
    except Exception as e:
        db.session.rollback()
        print(f"Error uploading object: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/stage-designer/objects')
@login_required
@crew_required
def get_stage_objects():
    """Get all objects in the library"""
    try:
        objects = StagePlanObject.query.filter(
            (StagePlanObject.is_public == True) | 
            (StagePlanObject.created_by == current_user.username)
        ).order_by(StagePlanObject.category, StagePlanObject.name).all()
        
        return jsonify([{
            'id': obj.id,
            'name': obj.name,
            'category': obj.category,
            'image_data': obj.image_data,
            'default_width': obj.default_width,
            'default_height': obj.default_height
        } for obj in objects])
    except Exception as e:
        print(f"Error getting objects: {e}")
        return jsonify([])

@app.route('/stage-designer/objects/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_stage_object(id):
    """Delete an object from the library (ADMIN ONLY)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Admin access required'}), 403
    
    try:
        obj = StagePlanObject.query.get_or_404(id)
        db.session.delete(obj)
        db.session.commit()
        print(f"Object {id} deleted")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting object {id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Add this new route to load designer plans on the stage plans page
@app.route('/stageplans/from-designer/<int:design_id>')
@login_required
@crew_required
def view_designer_plan(design_id):
    """Redirect to designer to view a saved design"""
    return redirect(url_for('stage_designer', design_id=design_id))

# RUN APP

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5001))
    
    # Start Flask app
    app.run(host='0.0.0.0', port=port, debug=False)