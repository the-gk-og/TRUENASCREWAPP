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

from flask import Flask
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Core configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///production_crew.db')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16 MB

# Email configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@prodcrew.local')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
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

class PickListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    is_checked = db.Column(db.Boolean, default=False)
    added_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'))

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
    crew_assignments = db.relationship('CrewAssignment', backref='event', lazy=True, cascade='all, delete-orphan')
    pick_list_items = db.relationship('PickListItem', backref='event', lazy=True, cascade='all, delete-orphan')
    stage_plans = db.relationship('StagePlan', backref='event', lazy=True, cascade='all, delete-orphan')

class CrewAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    crew_member = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(100))
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Template context functions
@app.context_processor
def inject_functions():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()
    return dict(get_user_by_username=get_user_by_username)

def send_email(subject, recipient, body):
    """Send email notification if email is configured"""
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

def get_user_email(username):
    """Get user email by username"""
    user = User.query.filter_by(username=username).first()
    return user.email if user else None

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

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

@app.route('/equipment')
@login_required
def equipment_list():
    equipment = Equipment.query.all()
    equipment_dict = [{
        'id': e.id,
        'barcode': e.barcode,
        'name': e.name,
        'category': e.category or '',
        'location': e.location or '',
        'notes': e.notes or ''
    } for e in equipment]
    return render_template('equipment.html', equipment=equipment, equipment_json=equipment_dict)

@app.route('/equipment/search')
@login_required
def equipment_search():
    query = request.args.get('q', '')
    equipment = Equipment.query.filter(
        (Equipment.name.contains(query)) | 
        (Equipment.barcode.contains(query)) |
        (Equipment.location.contains(query))
    ).all()
    return jsonify([{
        'id': e.id,
        'barcode': e.barcode,
        'name': e.name,
        'category': e.category,
        'location': e.location,
        'notes': e.notes
    } for e in equipment])

@app.route('/equipment/barcode/<barcode>')
@login_required
def equipment_by_barcode(barcode):
    equipment = Equipment.query.filter_by(barcode=barcode).first()
    if equipment:
        return jsonify({
            'id': equipment.id,
            'barcode': equipment.barcode,
            'name': equipment.name,
            'category': equipment.category,
            'location': equipment.location,
            'notes': equipment.notes
        })
    return jsonify({'error': 'Equipment not found'}), 404

@app.route('/equipment/add', methods=['POST'])
@login_required
def add_equipment():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.json
    equipment = Equipment(
        barcode=data['barcode'],
        name=data['name'],
        category=data.get('category', ''),
        location=data.get('location', ''),
        notes=data.get('notes', '')
    )
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
            
            # Skip if barcode already exists
            if Equipment.query.filter_by(barcode=barcode).first():
                continue
            
            equipment = Equipment(
                barcode=barcode,
                name=name,
                category=row.get('category') or row.get('Category') or '',
                location=row.get('location') or row.get('Location') or '',
                notes=row.get('notes') or row.get('Notes') or ''
            )
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
    sheet_name = data.get('sheet_name', 'Sheet1')
    
    if not sheet_id:
        return jsonify({'error': 'Sheet ID required'}), 400
    
    try:
        # SheetDB API
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
            
            equipment = Equipment(
                barcode=barcode,
                name=name,
                category=row.get('category') or row.get('Category') or '',
                location=row.get('location') or row.get('Location') or '',
                notes=row.get('notes') or row.get('Notes') or ''
            )
            db.session.add(equipment)
            count += 1
        
        db.session.commit()
        return jsonify({'success': True, 'imported': count})
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Failed to fetch from SheetDB: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 400

# Pick List Management
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
    return render_template('picklist.html', items=items, events=events, current_event=event)

@app.route('/picklist/add', methods=['POST'])
@login_required
def add_picklist_item():
    data = request.json
    item = PickListItem(
        item_name=data['item_name'],
        quantity=data.get('quantity', 1),
        added_by=current_user.username,
        event_id=data.get('event_id')
    )
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

# Stage Plans
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
        
        plan = StagePlan(
            title=request.form.get('title', filename),
            filename=filename,
            uploaded_by=current_user.username,
            event_id=request.form.get('event_id')
        )
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

# Events and Calendar
@app.route('/calendar')
@login_required
def calendar():
    events = Event.query.order_by(Event.event_date).all()
    now = datetime.now()
    return render_template('calendar.html', events=events, now=now)

@app.route('/calendar/ics')
@login_required
def calendar_ics():
    """Generate iCalendar format for Google Calendar subscription"""
    events = Event.query.all()
    
    ical = "BEGIN:VCALENDAR\r\n"
    ical += "VERSION:2.0\r\n"
    ical += "PRODID:-//Production Crew//Production Crew System//EN\r\n"
    ical += "CALSCALE:GREGORIAN\r\n"
    ical += "METHOD:PUBLISH\r\n"
    ical += "X-WR-CALNAME:Production Crew Events\r\n"
    ical += "X-WR-TIMEZONE:UTC\r\n"
    
    for event in events:
        ical += "BEGIN:VEVENT\r\n"
        ical += f"UID:{event.id}@prodcrew\r\n"
        ical += f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}\r\n"
        ical += f"DTSTART:{event.event_date.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        ical += f"DTEND:{(event.event_date + timedelta(hours=2)).strftime('%Y%m%dT%H%M%SZ')}\r\n"
        ical += f"SUMMARY:{event.title}\r\n"
        ical += f"DESCRIPTION:{event.description or 'Production Crew Event'}\r\n"
        if event.location:
            ical += f"LOCATION:{event.location}\r\n"
        ical += "END:VEVENT\r\n"
    
    ical += "END:VCALENDAR\r\n"
    
    return ical, 200, {'Content-Type': 'text/calendar', 'Content-Disposition': 'attachment; filename="prodcrew.ics"'}

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
    return jsonify({'success': True, 'id': event.id})

@app.route('/events/<int:id>')
@login_required
def event_detail(id):
    event = Event.query.get_or_404(id)
    all_users = User.query.all()
    return render_template('event_detail.html', event=event, all_users=all_users)

@app.route('/events/update/<int:id>', methods=['PUT'])
@login_required
def update_event(id):
    event = Event.query.get_or_404(id)
    data = request.json
    event.title = data.get('title', event.title)
    event.description = data.get('description', event.description)
    if 'event_date' in data:
        event.event_date = datetime.fromisoformat(data['event_date'])
    event.location = data.get('location', event.location)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/events/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})

# Crew Assignment
@app.route('/crew/assign', methods=['POST'])
@login_required
def assign_crew():
    data = request.json
    assignment = CrewAssignment(
        event_id=data['event_id'],
        crew_member=data['crew_member'],
        role=data.get('role', '')
    )
    db.session.add(assignment)
    db.session.commit()
    
    # Send email ONLY to the assigned crew member
    event = Event.query.get(data['event_id'])
    
    # Find user by username to get their email
    user = User.query.filter_by(username=data['crew_member']).first()
    
    if user and user.email:
        subject = f"🎭 You're assigned to: {event.title}"
        body = f"""Hello {user.username},

You have been assigned to an upcoming production event!

📋 Event Details:
  • Event: {event.title}
  • Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
  • Location: {event.location or 'TBD'}
  • Your Role: {data.get('role', 'Crew Member')}

{f'📝 Description: {event.description}' if event.description else ''}

Please log in to the Production Crew Management System to view:
  • Pick lists for items to gather
  • Stage plans for setup
  • Other crew members assigned to this event
  • Event details and updates

Let me know if you have any questions!

Best regards,
Production Crew System
"""
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
    assignment_id = data.get('assignment_id')
    event_id = data.get('event_id')
    
    assignment = CrewAssignment.query.get_or_404(assignment_id)
    event = Event.query.get_or_404(event_id)
    user = User.query.filter_by(username=assignment.crew_member).first()
    
    if not user or not user.email:
        return jsonify({'error': 'User has no email address'}), 400
    
    subject = f"🎭 You're assigned to: {event.title}"
    body = f"""Hello {user.username},

You have been assigned to an upcoming production event!

📋 Event Details:
  • Event: {event.title}
  • Date & Time: {event.event_date.strftime('%B %d, %Y at %I:%M %p')}
  • Location: {event.location or 'TBD'}
  • Your Role: {assignment.role or 'Crew Member'}

{f'📝 Description: {event.description}' if event.description else ''}

Please log in to the Production Crew Management System to view:
  • Pick lists for items to gather
  • Stage plans for setup
  • Other crew members assigned to this event
  • Event details and updates

Let me know if you have any questions!

Best regards,
Production Crew System
"""
    
    if send_email(subject, user.email, body):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to send email'}), 500

# Admin Routes
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
        return jsonify({'error': 'Username already exists'}), 400
    
    if data.get('email') and User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400
    
    user = User(
        username=data['username'],
        email=data.get('email'),
        password_hash=generate_password_hash(data['password']),
        is_admin=data.get('is_admin', False)
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'success': True, 'id': user.id})

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
        db_file = 'production_crew.db'
        backup_file = f'backups/production_crew_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        os.makedirs('backups', exist_ok=True)
        shutil.copy(db_file, backup_file)
        return jsonify({'success': True, 'file': backup_file})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/restore', methods=['POST'])
@login_required
def restore_database():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        db.session.close()
        file.save('production_crew_restore.db')
        shutil.copy('production_crew_restore.db', 'production_crew.db')
        os.remove('production_crew_restore.db')
        return jsonify({'success': True, 'message': 'Database restored. Please refresh the page.'})
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
            backups.append({
                'name': file,
                'size': os.path.getsize(path),
                'date': datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            })
    return jsonify(backups)

@app.route('/admin/download-backup/<filename>')
@login_required
def download_backup(filename):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    return send_from_directory('backups', filename)

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Default admin user created: username='admin', password='admin123'")

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)