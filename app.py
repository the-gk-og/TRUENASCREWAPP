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



app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
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

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert Equipment to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'barcode': self.barcode,
            'name': self.name,
            'category': self.category or '',
            'location': self.location or '',
            'notes': self.notes or ''
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
    event_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200))
    created_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    discord_message_id = db.Column(db.String(50), nullable=True)
    crew_assignments = db.relationship('CrewAssignment', backref='event', lazy=True, cascade='all, delete-orphan')
    pick_list_items = db.relationship('PickListItem', backref='event', lazy=True, cascade='all, delete-orphan')
    stage_plans = db.relationship('StagePlan', backref='event', lazy=True, cascade='all, delete-orphan')

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
            "title": f"🎭 New Event: {event.title}",
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


# ADD THESE ROUTES TO app.py (before @app.route('/'))

@app.route('/home')
def home():
    """Landing page - accessible to everyone"""
    return render_template('home.html')

@app.route('/learn-more')
def learn_more():
    """Learn more page with detailed features"""
    return render_template('learn_more.html')

@app.route('/contact')
def contact():
    """Contact page"""
    return render_template('contact.html')

@app.route('/contact/send', methods=['POST'])
def send_contact_message():
    """Send contact message"""
    data = request.json
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()
    
    # Validation
    if not all([name, email, subject, message]):
        return jsonify({'error': 'All fields are required'}), 400
    
    if len(message) < 10:
        return jsonify({'error': 'Message must be at least 10 characters'}), 400
    
    # Send email to admin
    try:
        admin_email = app.config['MAIL_DEFAULT_SENDER']
        email_body = f"""
New Contact Message from {name}

Email: {email}
Subject: {subject}

Message:
{message}

---
This is an automated message from the Production Crew Management System contact form.
"""
        send_email(f"Contact Form: {subject}", admin_email, email_body)
        
        # Optional: Send confirmation email to user
        user_email_body = f"""
Hello {name},

Thank you for reaching out to the Production Crew Management System team!

We received your message about: {subject}

We'll get back to you as soon as possible.

Best regards,
Production Crew Management System Team
"""
        send_email("We received your message", email, user_email_body)
        
        return jsonify({'success': True, 'message': 'Message sent successfully! Check your email for confirmation.'})
    except Exception as e:
        print(f"Contact form error: {e}")
        return jsonify({'error': 'Failed to send message. Please try again later.'}), 500


@app.route('/quote', methods=['GET', 'POST'])
def quote():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        organization = request.form.get('organization')
        message = request.form.get('message')

        # You can add email sending or database storage here
        print("Quote enquiry received:")
        print(f"Name: {name}")
        print(f"Email: {email}")
        print(f"Organization: {organization}")
        print(f"Message: {message}")

        flash('Your enquiry has been submitted successfully. We’ll be in touch soon!', 'success')
        return redirect('/quote')

    return render_template('quote.html')


# AUTH ROUTES




@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    upcoming_events = Event.query.filter(Event.event_date >= datetime.now()).order_by(Event.event_date).limit(5).all()
    return render_template('dashboard.html', upcoming_events=upcoming_events)

# EQUIPMENT ROUTES

@app.route('/equipment')
@login_required
def equipment_list():
    equipment = Equipment.query.all()
    equipment_json = [e.to_dict() for e in equipment]
    return render_template('equipment.html', equipment=equipment, equipment_json=equipment_json)

@app.route('/equipment/barcode/<barcode>')
@login_required
def equipment_by_barcode(barcode):
    equipment = Equipment.query.filter_by(barcode=barcode).first()
    if equipment:
        return jsonify(equipment.to_dict())
    return jsonify({'error': 'Equipment not found'}), 404

@app.route('/equipment/add', methods=['POST'])
@login_required
def add_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    equipment = Equipment(barcode=data['barcode'], name=data['name'], category=data.get('category', ''), location=data.get('location', ''), notes=data.get('notes', ''))
    db.session.add(equipment)
    db.session.commit()
    return jsonify({'success': True, 'id': equipment.id})

@app.route('/equipment/update/<int:id>', methods=['PUT'])
@login_required
def update_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    equipment = Equipment.query.get_or_404(id)
    data = request.json
    equipment.name = data.get('name', equipment.name)
    equipment.category = data.get('category', equipment.category)
    equipment.location = data.get('location', equipment.location)
    equipment.notes = data.get('notes', equipment.notes)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/equipment/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_equipment(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    equipment = Equipment.query.get_or_404(id)
    db.session.delete(equipment)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/equipment/import-csv', methods=['POST'])
@login_required
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

# PICKLIST ROUTES

@app.route('/picklist')
@login_required
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
    return render_template('picklist.html', items=items, events=events, current_event=event, all_equipment=all_equipment, all_equipment_json=equipment_dict)

@app.route('/picklist/add', methods=['POST'])
@login_required
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
def toggle_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    item.is_checked = not item.is_checked
    db.session.commit()
    return jsonify({'success': True, 'is_checked': item.is_checked})

@app.route('/picklist/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_picklist_item(id):
    item = PickListItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})

# STAGE PLANS ROUTES

@app.route('/stageplans')
@login_required
def stageplans():
    event_id = request.args.get('event_id')
    if event_id:
        plans = StagePlan.query.filter_by(event_id=event_id).all()
        event = Event.query.get(event_id)
    else:
        plans = StagePlan.query.all()
        event = None
    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template('stageplans.html', plans=plans, events=events, current_event=event)

@app.route('/stageplans/upload', methods=['POST'])
@login_required
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
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/stageplans/delete/<int:id>', methods=['DELETE'])
@login_required
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
def calendar():
    events = Event.query.order_by(Event.event_date).all()
    now = datetime.now()
    return render_template('calendar.html', events=events, now=now)

@app.route('/calendar/ics')
@login_required
def calendar_ics():
    events = Event.query.all()
    ical = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Production Crew//EN\r\n"
    for event in events:
        ical += f"BEGIN:VEVENT\r\nUID:{event.id}@prodcrew\r\nDTSTART:{event.event_date.strftime('%Y%m%dT%H%M%SZ')}\r\nDTEND:{(event.event_date + timedelta(hours=2)).strftime('%Y%m%dT%H%M%SZ')}\r\nSUMMARY:{event.title}\r\n"
        if event.location:
            ical += f"LOCATION:{event.location}\r\n"
        ical += "END:VEVENT\r\n"
    ical += "END:VCALENDAR\r\n"
    return ical, 200, {'Content-Type': 'text/calendar'}

@app.route('/events/add', methods=['POST'])
@login_required
def add_event():
    data = request.json
    event = Event(
        title=data['title'],
        description=data.get('description', ''),
        event_date=datetime.fromisoformat(data['event_date']),
        location=data.get('location', ''),
        created_by=current_user.username
    )
    db.session.add(event)
    db.session.commit()
    send_discord_message(event)
    return jsonify({'success': True, 'id': event.id})

@app.route('/events/<int:id>', methods=['GET'])
@login_required
def event_detail(id):
    event = Event.query.get_or_404(id)
    all_users = User.query.all()
    schedules = EventSchedule.query.filter_by(event_id=id).order_by(EventSchedule.scheduled_time).all()
    return render_template('event_detail.html', event=event, all_users=all_users, schedules=schedules)

@app.route('/events/<int:id>/edit', methods=['PUT'])
@login_required
def edit_event(id):
    event = Event.query.get_or_404(id)
    data = request.json
    
    event.title = data.get('title', event.title)
    event.description = data.get('description', event.description)
    event.location = data.get('location', event.location)
    
    if data.get('event_date'):
        event.event_date = datetime.fromisoformat(data['event_date'])
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})

# EVENT SCHEDULING ROUTES - Add these new routes

@app.route('/events/<int:event_id>/schedule/add', methods=['POST'])
@login_required
def add_event_schedule(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.json
    
    schedule = EventSchedule(
        event_id=event_id,
        title=data['title'],  # Changed from schedule_type to title
        scheduled_time=datetime.fromisoformat(data['scheduled_time']),
        description=data.get('description', '')
    )
    
    db.session.add(schedule)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': schedule.id,
        'scheduled_time': schedule.scheduled_time.isoformat()
    })

@app.route('/events/schedule/<int:schedule_id>/edit', methods=['PUT'])
@login_required
def edit_event_schedule(schedule_id):
    schedule = EventSchedule.query.get_or_404(schedule_id)
    data = request.json
    
    schedule.schedule_type = data.get('schedule_type', schedule.schedule_type)
    schedule.scheduled_time = datetime.fromisoformat(data['scheduled_time'])
    schedule.description = data.get('description', schedule.description)
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
def delete_event_schedule(schedule_id):
    schedule = EventSchedule.query.get_or_404(schedule_id)
    db.session.delete(schedule)
    db.session.commit()
    return jsonify({'success': True})
# CREW ROUTES

@app.route('/crew/assign', methods=['POST'])
@login_required
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
def remove_crew(id):
    assignment = CrewAssignment.query.get_or_404(id)
    db.session.delete(assignment)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/crew/resend-notification', methods=['POST'])
@login_required
def resend_notification():
    data = request.json
    assignment = CrewAssignment.query.get(data.get('assignment_id'))
    event = Event.query.get(data.get('event_id'))
    
    if not assignment or not event:
        return jsonify({'error': 'Not found'}), 404
    
    user = User.query.filter_by(username=assignment.crew_member).first()
    if user and user.email:
        subject = f"🎭 Reminder: {event.title}"
        body = f"""Hello {user.username},

This is a reminder that you're assigned to:

📋 Event: {event.title}
📅 Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
📍 Location: {event.location or 'TBD'}
👤 Your Role: {assignment.role or 'Crew Member'}

See you there!

Production Crew System"""
        send_email(subject, user.email, body)
        return jsonify({'success': True})
    
    return jsonify({'error': 'User has no email'}), 400

# DISCORD ROUTES

@app.route('/discord-settings')
@login_required
def discord_settings():
    return render_template('discord_settings.html')

@app.route('/settings/link-discord', methods=['POST'])
@login_required
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
    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username exists'}), 400
    user = User(username=data['username'], email=data.get('email'), password_hash=generate_password_hash(data['password']), is_admin=data.get('is_admin', False))
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
    
    # Cannot change another admin's username if you're not them
    if id != current_user.id and user.is_admin:
        return jsonify({'error': 'Cannot modify other admin accounts'}), 403
    
    # Update username if provided and changed
    if data.get('username') and data['username'] != user.username:
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400
        user.username = data['username']
    
    # Update email if provided
    if data.get('email'):
        if data['email'] != user.email and User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already in use'}), 400
        user.email = data['email'] if data['email'].strip() else None
    
    # Update discord if provided
    if 'discord_id' in data:
        user.discord_id = data.get('discord_id') or None
        user.discord_username = data.get('discord_username') or None
    
    # Update password if provided
    if data.get('password'):
        if len(data['password']) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        user.password_hash = generate_password_hash(data['password'])
    
    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        db.session.rollback()
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
        'is_admin': user.is_admin
    })

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
#export routes


@app.route('/events/<int:event_id>/export-pdf')
@login_required
def export_event_pdf(event_id):
    """Export event details to PDF, including stage plan images"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from io import BytesIO
        import os

        event = Event.query.get_or_404(event_id)

        # Create PDF in memory
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        styles = getSampleStyleSheet()
        story = []

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#6366f1'),
            spaceAfter=12,
            alignment=1  # Center
        )

        section_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#6366f1'),
            spaceAfter=8,
            spaceBefore=8
        )

        # Title
        story.append(Paragraph(f"🎭 {event.title}", title_style))
        story.append(Spacer(1, 0.2*inch))

        # Event Details
        story.append(Paragraph("Event Details", section_style))
        details_data = [
            ['Date & Time:', event.event_date.strftime('%B %d, %Y at %I:%M %p')],
            ['Location:', event.location or 'N/A'],
            ['Created By:', event.created_by or 'N/A'],
        ]
        details_table = Table(details_data, colWidths=[1.5*inch, 4.5*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f4ff')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(details_table)
        story.append(Spacer(1, 0.2*inch))

        # Description
        if event.description:
            story.append(Paragraph("Description", section_style))
            story.append(Paragraph(event.description, styles['Normal']))
            story.append(Spacer(1, 0.2*inch))

        # Event Notes
        if hasattr(event, 'notes') and event.notes:
            story.append(Paragraph("Event Notes", section_style))
            for note in sorted(event.notes, key=lambda x: x.created_at, reverse=True):
                note_text = f"<b>{note.created_by}</b> ({note.created_at.strftime('%b %d, %Y')}): {note.content}"
                story.append(Paragraph(note_text, styles['Normal']))
                story.append(Spacer(1, 0.1*inch))
            story.append(Spacer(1, 0.2*inch))

        # Schedule
        if hasattr(event, 'schedules') and event.schedules:
            story.append(Paragraph("Schedule", section_style))
            schedule_data = [['Title', 'Time', 'Description']]
            for schedule in sorted(event.schedules, key=lambda x: x.scheduled_time):
                schedule_data.append([
                    schedule.title,
                    schedule.scheduled_time.strftime('%I:%M %p'),
                    schedule.description or 'N/A'
                ])
            schedule_table = Table(schedule_data, colWidths=[1.5*inch, 1*inch, 2.5*inch])
            schedule_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366f1')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            story.append(schedule_table)
            story.append(Spacer(1, 0.2*inch))

        # Pick List
        if hasattr(event, 'pick_list_items') and event.pick_list_items:
            story.append(Paragraph("Pick List", section_style))
            picklist_data = [['Item', 'Qty', 'Location', 'Status']]
            for item in event.pick_list_items:
                picklist_data.append([
                    item.item_name,
                    str(item.quantity),
                    item.equipment.location if item.equipment else 'N/A',
                    '✓ Gathered' if item.is_checked else '○ Pending'
                ])
            picklist_table = Table(picklist_data, colWidths=[2*inch, 0.5*inch, 1.5*inch, 1*inch])
            picklist_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            story.append(picklist_table)
            story.append(Spacer(1, 0.2*inch))

        # Stage Plans with Images
        if hasattr(event, 'stage_plans') and event.stage_plans:
            story.append(Paragraph("Stage Plans", section_style))
            for plan in event.stage_plans:
                story.append(Paragraph(f"{plan.title} (uploaded by {plan.uploaded_by})", styles['Normal']))
                image_file = os.path.join('uploads', plan.filename)
                if os.path.exists(image_file):
                    img = Image(image_file, width=5.5*inch, height=3.5*inch)
                    img.hAlign = 'CENTER'
                    story.append(img)
                    story.append(Spacer(1, 0.2*inch))
                else:
                    story.append(Paragraph("Image not available", styles['Normal']))
                    story.append(Spacer(1, 0.1*inch))
                    
        # Crew Assignments
        if hasattr(event, 'crew_assignments') and event.crew_assignments:
            story.append(Paragraph("Attending Crew", section_style))
            crew_data = [['Crew Member', 'Role', 'Notification Status']]
            for assignment in event.crew_assignments:
                user = User.query.filter_by(username=assignment.crew_member).first()
                status = 'Email: Yes' if (user and user.email) else 'Email: No'
                crew_data.append([
                    assignment.crew_member,
                    assignment.role or 'Crew Member',
                    status
                ])
            crew_table = Table(crew_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
            crew_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ec4899')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            story.append(crew_table)

        # Build PDF
        doc.build(story)
        pdf_buffer.seek(0)

        # Sanitize filename
        import re
        safe_title = re.sub(r'\W+', '_', event.title)
        filename = f"{safe_title}_Details.pdf"

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
# Add these routes to your app.py (in the routes section)

@app.route('/events/<int:event_id>/notes/add', methods=['POST'])
@login_required
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
def delete_event_note(note_id):
    """Delete an event note"""
    note = EventNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({'success': True})


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    
    # Start Flask app
    app.run(host='0.0.0.0', port=port, debug=False)