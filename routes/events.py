"""routes/events.py — Event CRUD, scheduling, notes, PDF export, run lists."""

import os, io, re, json
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, send_file, Response,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Event, CrewAssignment, EventSchedule, EventNote,
    CrewRunItem, CastRunItem, User, StagePlan,
)
from decorators import crew_required
from services.notification_service import (
    send_discord_event_announcement, schedule_event_notifications,
)

events_bp = Blueprint('events', __name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@events_bp.route('/events/add', methods=['POST'])
@login_required
@crew_required
def add_event():
    data       = request.json
    start_date = datetime.fromisoformat(data['event_date'])
    end_date   = (datetime.fromisoformat(data['event_end_date'])
                  if data.get('event_end_date') else start_date + timedelta(hours=3))
    event = Event(
        title=data['title'], description=data.get('description', ''),
        event_date=start_date, event_end_date=end_date,
        location=data.get('location', ''), created_by=current_user.username,
    )
    db.session.add(event)
    db.session.commit()
    send_discord_event_announcement(event)
    schedule_event_notifications(event)
    return jsonify({'success': True, 'id': event.id})


@events_bp.route('/events/<int:id>', methods=['GET'])
@login_required
@crew_required
def event_detail(id):
    event     = Event.query.get_or_404(id)
    all_users = User.query.all()
    schedules = EventSchedule.query.filter_by(event_id=id).order_by(EventSchedule.scheduled_time).all()
    from models import Shift, ShiftAssignment
    shifts     = Shift.query.filter_by(event_id=id).all()
    shifts_data = []
    for shift in shifts:
        assignments  = ShiftAssignment.query.filter_by(shift_id=shift.id).all()
        assigned_cnt = sum(1 for a in assignments if a.status in ('accepted', 'confirmed'))
        shifts_data.append({
            'id': shift.id, 'title': shift.title, 'role': shift.role,
            'shift_date': shift.shift_date.isoformat(),
            'shift_end_date': shift.shift_end_date.isoformat() if shift.shift_end_date else None,
            'positions_needed': shift.positions_needed, 'location': shift.location,
            'assigned_count': assigned_cnt, 'is_open': shift.is_open,
            'assignments': [
                {
                    'id': a.id, 'user_id': a.user_id, 'status': a.status,
                    'username': (User.query.get(a.user_id).username
                                 if User.query.get(a.user_id) else 'Unknown'),
                }
                for a in assignments
            ],
        })
    return render_template('/crew/event_detail.html',
                           event=event, all_users=all_users,
                           schedules=schedules, shifts_data=shifts_data)


@events_bp.route('/events/<int:id>', methods=['DELETE'])
@login_required
@crew_required
def delete_event(id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event(id):
    event = Event.query.get_or_404(id)
    data  = request.json
    event.title       = data.get('title',       event.title)
    event.description = data.get('description', event.description)
    event.location    = data.get('location',    event.location)
    if data.get('event_date'):
        event.event_date = datetime.fromisoformat(data['event_date'])
    if data.get('event_end_date'):
        event.event_end_date = datetime.fromisoformat(data['event_end_date'])
    elif data.get('event_date'):
        event.event_end_date = event.event_date + timedelta(hours=3)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/schedule/add', methods=['POST'])
@login_required
@crew_required
def add_event_schedule(event_id):
    Event.query.get_or_404(event_id)
    data = request.json
    try:
        schedule = EventSchedule(
            event_id=event_id,
            title=data.get('title', ''),
            scheduled_time=datetime.fromisoformat(data['scheduled_time']),
            description=data.get('description', ''),
        )
        db.session.add(schedule)
        db.session.commit()
        return jsonify({'success': True, 'id': schedule.id,
                        'scheduled_time': schedule.scheduled_time.isoformat()})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@events_bp.route('/events/schedule/<int:schedule_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_event_schedule(schedule_id):
    schedule = EventSchedule.query.get_or_404(schedule_id)
    try:
        db.session.delete(schedule)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/notes/add', methods=['POST'])
@login_required
@crew_required
def add_event_note(event_id):
    Event.query.get_or_404(event_id)
    data = request.json
    note = EventNote(event_id=event_id, content=data['content'],
                     created_by=current_user.username)
    db.session.add(note)
    db.session.commit()
    return jsonify({'success': True, 'id': note.id, 'note': {
        'id': note.id, 'content': note.content,
        'created_by': note.created_by,
        'created_at': note.created_at.strftime('%b %d, %Y at %I:%M %p'),
    }})


@events_bp.route('/events/notes/<int:note_id>/edit', methods=['PUT'])
@login_required
@crew_required
def edit_event_note(note_id):
    note = EventNote.query.get_or_404(note_id)
    note.content    = request.json['content']
    note.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/notes/<int:note_id>/delete', methods=['DELETE'])
@login_required
@crew_required
def delete_event_note(note_id):
    note = EventNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Crew run list
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/crew-run/add', methods=['POST'])
@login_required
def add_crew_run_item(event_id):
    Event.query.get_or_404(event_id)
    data      = request.json
    max_order = db.session.query(db.func.max(CrewRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    item = CrewRunItem(
        event_id=event_id, order_number=max_order+1,
        title=data['title'], description=data.get('description', ''),
        duration=data.get('duration', ''), cue_type=data.get('cue_type', ''),
        notes=data.get('notes', ''),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id, 'order_number': item.order_number})


@events_bp.route('/events/crew-run/<int:item_id>/edit', methods=['PUT'])
@login_required
def edit_crew_run_item(item_id):
    item = CrewRunItem.query.get_or_404(item_id)
    data = request.json
    item.title       = data.get('title',       item.title)
    item.description = data.get('description', item.description)
    item.duration    = data.get('duration',    item.duration)
    item.cue_type    = data.get('cue_type',    item.cue_type)
    item.notes       = data.get('notes',       item.notes)
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/crew-run/<int:item_id>/delete', methods=['DELETE'])
@login_required
def delete_crew_run_item(item_id):
    item     = CrewRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    order    = item.order_number
    db.session.delete(item)
    for i in CrewRunItem.query.filter(
        CrewRunItem.event_id == event_id,
        CrewRunItem.order_number > order,
    ).all():
        i.order_number -= 1
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/crew-run/reorder', methods=['POST'])
@login_required
def reorder_crew_run_items(event_id):
    for idx, item_id in enumerate(request.json.get('item_ids', []), start=1):
        item = CrewRunItem.query.get(item_id)
        if item and item.event_id == event_id:
            item.order_number = idx
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Cast run list
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/cast-run/add', methods=['POST'])
@login_required
def add_cast_run_item(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    Event.query.get_or_404(event_id)
    data      = request.json
    max_order = db.session.query(db.func.max(CastRunItem.order_number)).filter_by(event_id=event_id).scalar() or 0
    item = CastRunItem(
        event_id=event_id, order_number=max_order+1,
        title=data['title'], description=data.get('description', ''),
        duration=data.get('duration', ''), item_type=data.get('item_type', ''),
        cast_involved=data.get('cast_involved', ''), notes=data.get('notes', ''),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'id': item.id, 'order_number': item.order_number})


@events_bp.route('/events/cast-run/<int:item_id>/edit', methods=['PUT'])
@login_required
def edit_cast_run_item(item_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item = CastRunItem.query.get_or_404(item_id)
    data = request.json
    for f in ('title', 'description', 'duration', 'item_type', 'cast_involved', 'notes'):
        setattr(item, f, data.get(f, getattr(item, f)))
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/cast-run/<int:item_id>/delete', methods=['DELETE'])
@login_required
def delete_cast_run_item(item_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    item     = CastRunItem.query.get_or_404(item_id)
    event_id = item.event_id
    order    = item.order_number
    db.session.delete(item)
    for i in CastRunItem.query.filter(
        CastRunItem.event_id == event_id,
        CastRunItem.order_number > order,
    ).all():
        i.order_number -= 1
    db.session.commit()
    return jsonify({'success': True})


@events_bp.route('/events/<int:event_id>/cast-run/reorder', methods=['POST'])
@login_required
def reorder_cast_run_items(event_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    for idx, item_id in enumerate(request.json.get('item_ids', []), start=1):
        item = CastRunItem.query.get(item_id)
        if item and item.event_id == event_id:
            item.order_number = idx
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Recurring events
# ---------------------------------------------------------------------------

@events_bp.route('/events/create-recurring', methods=['POST'])
@login_required
@crew_required
def create_recurring_event():
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    data = request.json
    try:
        start = datetime.fromisoformat(data['event_date'])
        end   = (datetime.fromisoformat(data['event_end_date'])
                 if data.get('event_end_date') else start + timedelta(hours=3))
        event = Event(
            title=data['title'], description=data.get('description', ''),
            event_date=start, event_end_date=end,
            location=data.get('location', ''), created_by=current_user.username,
            recurrence_pattern=data.get('recurrence_pattern'),
            recurrence_interval=data.get('recurrence_interval', 1),
            recurrence_end_date=(datetime.fromisoformat(data['recurrence_end_date'])
                                 if data.get('recurrence_end_date') else None),
            recurrence_count=data.get('recurrence_count'),
        )
        db.session.add(event)
        db.session.commit()
        _generate_recurring_instances(event)
        send_discord_event_announcement(event)
        return jsonify({'success': True, 'id': event.id})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


def _generate_recurring_instances(parent: Event) -> None:
    if not parent.recurrence_pattern:
        return
    current = parent.event_date
    count   = 0
    while True:
        count += 1
        if parent.recurrence_count and count > parent.recurrence_count:
            break
        if parent.recurrence_end_date and current > parent.recurrence_end_date:
            break
        if count > 1:
            duration = ((parent.event_end_date - parent.event_date)
                        if parent.event_end_date else timedelta(hours=3))
            db.session.add(Event(
                title=parent.title, description=parent.description,
                event_date=current, event_end_date=current + duration,
                location=parent.location, created_by=parent.created_by,
                is_recurring_instance=True, recurring_event_id=parent.id,
            ))
        p = parent.recurrence_pattern
        i = parent.recurrence_interval or 1
        if p == 'daily':
            current += timedelta(days=i)
        elif p == 'weekly':
            current += timedelta(weeks=i)
        elif p == 'biweekly':
            current += timedelta(weeks=2*i)
        elif p == 'monthly':
            try:
                m = current.month + i
                y = current.year + (m-1) // 12
                current = current.replace(year=y, month=((m-1) % 12) + 1)
            except ValueError:
                current = (current.replace(day=28) + timedelta(days=4))
                current = current - timedelta(days=current.day)
        elif p == 'yearly':
            current = current.replace(year=current.year + i)
        if count > 1000:
            break
    db.session.commit()


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/export-pdf')
@login_required
@crew_required
def export_event_pdf(event_id):
    """Export event brief as a PDF."""
    from services.report_service import generate_event_pdf
    try:
        pdf_buffer, filename = generate_event_pdf(event_id)
        return send_file(pdf_buffer, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# CSV Export/Import
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/export-csv/<export_type>')
@login_required
@crew_required
def export_event_csv(event_id, export_type):
    """Export event data to CSV."""
    from services.csv_service import CSVExportService
    
    Event.query.get_or_404(event_id)
    
    try:
        if export_type == 'event_schedule':
            csv_data = CSVExportService.export_event_schedule(event_id)
            filename = f"event_schedule_{event_id}.csv"
        elif export_type == 'cast_schedule':
            csv_data = CSVExportService.export_cast_schedule(event_id)
            filename = f"cast_schedule_{event_id}.csv"
        elif export_type == 'crew_run_list':
            csv_data = CSVExportService.export_crew_run_list(event_id)
            filename = f"crew_run_list_{event_id}.csv"
        elif export_type == 'cast_run_list':
            csv_data = CSVExportService.export_cast_run_list(event_id)
            filename = f"cast_run_list_{event_id}.csv"
        else:
            return jsonify({'error': 'Invalid export type'}), 400
        
        return send_file(
            io.BytesIO(csv_data.encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(exc)}), 500


@events_bp.route('/events/download-csv-template/<template_type>')
@login_required
@crew_required
def download_csv_template(template_type):
    """Download CSV template for importing data."""
    templates = {
        'event_schedule': 'Title,Scheduled Time,Description\nExample Item,2024-03-27T10:00:00,Optional description',
        'cast_schedule': 'Title,Scheduled Time,Description\nExample Item,2024-03-27T10:00:00,Optional description',
        'crew_run_list': 'Order,Title,Description,Duration,Cue Type,Notes\n1,Example,Description,5 mins,Cue,Notes',
        'cast_run_list': 'Order,Title,Description,Duration,Type,Cast Involved,Notes\n1,Example,Description,5 mins,Type,Cast Names,Notes',
        'picklist': 'Item Name,Quantity,Equipment ID\nExample Item,1,',
    }
    
    if template_type not in templates:
        return jsonify({'error': 'Invalid template type'}), 400
    
    csv_data = templates[template_type]
    return send_file(
        io.BytesIO(csv_data.encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{template_type}_template.csv"
    )


@events_bp.route('/events/<int:event_id>/import-csv', methods=['POST'])
@login_required
@crew_required
def import_event_csv(event_id):
    """Import event data from CSV."""
    from services.csv_service import CSVImportService
    
    Event.query.get_or_404(event_id)
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    import_type = request.form.get('import_type', '')
    
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        content = file.read().decode('utf-8')
        
        if import_type == 'event_schedule':
            count = CSVImportService.import_event_schedule(event_id, content)
        elif import_type == 'cast_schedule':
            count = CSVImportService.import_cast_schedule(event_id, content)
        elif import_type == 'crew_run_list':
            count = CSVImportService.import_crew_run_list(event_id, content)
        elif import_type == 'cast_run_list':
            count = CSVImportService.import_cast_run_list(event_id, content)
        elif import_type == 'picklist':
            picklist_id = request.form.get('picklist_id')
            count = CSVImportService.import_picklist(event_id, content, picklist_id)
        else:
            return jsonify({'error': 'Invalid import type'}), 400
        
        return jsonify({'success': True, 'count': count, 'message': f'Successfully imported {count} items'})
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# Archiving
# ---------------------------------------------------------------------------

@events_bp.route('/events/<int:event_id>/auto-archive', methods=['POST'])
@login_required
@crew_required
def auto_archive_event_items(event_id):
    """Auto-archive stage plans and picklists after event ends."""
    from models import StagePlan, Picklist
    
    event = Event.query.get_or_404(event_id)
    now = datetime.utcnow()
    
    # Archive stage plans and picklists if event has ended
    if event.event_end_date and event.event_end_date < now:
        stage_plans = StagePlan.query.filter_by(event_id=event_id, is_archived=False).all()
        picklists = Picklist.query.filter_by(event_id=event_id, is_archived=False).all()
        
        for plan in stage_plans:
            plan.is_archived = True
        for picklist in picklists:
            picklist.is_archived = True
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'archived_stage_plans': len(stage_plans),
            'archived_picklists': len(picklists)
        })
    
    return jsonify({'success': False, 'message': 'Event has not ended yet'})


@events_bp.route('/events/stageplans/<int:plan_id>/archive', methods=['PUT'])
@login_required
@crew_required
def archive_stage_plan(plan_id):
    """Manually archive a stage plan."""
    from models import StagePlan
    
    plan = StagePlan.query.get_or_404(plan_id)
    plan.is_archived = not plan.is_archived
    db.session.commit()
    
    return jsonify({'success': True, 'is_archived': plan.is_archived})


@events_bp.route('/events/picklists/<int:picklist_id>/archive', methods=['PUT'])
@login_required
@crew_required
def archive_picklist(picklist_id):
    """Manually archive a picklist."""
    from models import Picklist
    
    picklist = Picklist.query.get_or_404(picklist_id)
    picklist.is_archived = not picklist.is_archived
    db.session.commit()
    
    return jsonify({'success': True, 'is_archived': picklist.is_archived})
