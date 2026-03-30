"""services/csv_service.py — CSV import/export for events, schedules, run lists."""

import csv
import io
from datetime import datetime
from models import (
    EventSchedule, CastSchedule, CrewRunItem, CastRunItem, PickListItem, Event
)


class CSVExportService:
    """Export event data to CSV format."""
    
    @staticmethod
    def export_event_schedule(event_id):
        """Export EventSchedule items to CSV."""
        schedules = EventSchedule.query.filter_by(event_id=event_id).order_by(EventSchedule.scheduled_time).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Title', 'Scheduled Time', 'Description'])
        
        for schedule in schedules:
            writer.writerow([
                schedule.title,
                schedule.scheduled_time.isoformat() if schedule.scheduled_time else '',
                schedule.description or ''
            ])
        
        return output.getvalue()
    
    @staticmethod
    def export_cast_schedule(event_id):
        """Export CastSchedule items to CSV."""
        schedules = CastSchedule.query.filter_by(event_id=event_id).order_by(CastSchedule.scheduled_time).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Title', 'Scheduled Time', 'Description'])
        
        for schedule in schedules:
            writer.writerow([
                schedule.title,
                schedule.scheduled_time.isoformat() if schedule.scheduled_time else '',
                schedule.description or ''
            ])
        
        return output.getvalue()
    
    @staticmethod
    def export_crew_run_list(event_id):
        """Export CrewRunItem list to CSV."""
        items = CrewRunItem.query.filter_by(event_id=event_id).order_by(CrewRunItem.order_number).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Order', 'Title', 'Description', 'Duration', 'Cue Type', 'Notes'])
        
        for item in items:
            writer.writerow([
                item.order_number,
                item.title,
                item.description or '',
                item.duration or '',
                item.cue_type or '',
                item.notes or ''
            ])
        
        return output.getvalue()
    
    @staticmethod
    def export_cast_run_list(event_id):
        """Export CastRunItem list to CSV."""
        items = CastRunItem.query.filter_by(event_id=event_id).order_by(CastRunItem.order_number).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Order', 'Title', 'Description', 'Duration', 'Type', 'Cast Involved', 'Notes'])
        
        for item in items:
            writer.writerow([
                item.order_number,
                item.title,
                item.description or '',
                item.duration or '',
                item.item_type or '',
                item.cast_involved or '',
                item.notes or ''
            ])
        
        return output.getvalue()
    
    @staticmethod
    def export_picklist(event_id, picklist_id=None):
        """Export PickListItem to CSV."""
        if picklist_id:
            items = PickListItem.query.filter_by(picklist_id=picklist_id).all()
        else:
            items = PickListItem.query.filter_by(event_id=event_id, picklist_id=None).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Item Name', 'Quantity', 'Equipment ID'])
        
        for item in items:
            writer.writerow([
                item.item_name,
                item.quantity,
                item.equipment_id or ''
            ])
        
        return output.getvalue()


class CSVImportService:
    """Import event data from CSV format."""
    
    @staticmethod
    def import_event_schedule(event_id, csv_content):
        """Import EventSchedule items from CSV."""
        from extensions import db
        
        lines = csv_content.strip().split('\n')
        reader = csv.reader(lines)
        next(reader)  # Skip header
        
        count = 0
        for row in reader:
            if len(row) < 2:
                continue
            
            title = row[0].strip()
            scheduled_time_str = row[1].strip()
            description = row[2].strip() if len(row) > 2 else ''
            
            try:
                # Handle both ISO format and common datetime formats
                if 'T' in scheduled_time_str:
                    scheduled_time = datetime.fromisoformat(scheduled_time_str)
                else:
                    # Try to parse as common format
                    scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M:%S')
                
                schedule = EventSchedule(
                    event_id=event_id,
                    title=title,
                    scheduled_time=scheduled_time,
                    description=description
                )
                db.session.add(schedule)
                count += 1
            except Exception as e:
                print(f"Error importing schedule row: {e}")
                continue
        
        db.session.commit()
        return count
    
    @staticmethod
    def import_cast_schedule(event_id, csv_content):
        """Import CastSchedule items from CSV."""
        from extensions import db
        
        lines = csv_content.strip().split('\n')
        reader = csv.reader(lines)
        next(reader)  # Skip header
        
        count = 0
        for row in reader:
            if len(row) < 2:
                continue
            
            title = row[0].strip()
            scheduled_time_str = row[1].strip()
            description = row[2].strip() if len(row) > 2 else ''
            
            try:
                if 'T' in scheduled_time_str:
                    scheduled_time = datetime.fromisoformat(scheduled_time_str)
                else:
                    scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M:%S')
                
                schedule = CastSchedule(
                    event_id=event_id,
                    title=title,
                    scheduled_time=scheduled_time,
                    description=description
                )
                db.session.add(schedule)
                count += 1
            except Exception as e:
                print(f"Error importing cast schedule row: {e}")
                continue
        
        db.session.commit()
        return count
    
    @staticmethod
    def import_crew_run_list(event_id, csv_content):
        """Import CrewRunItem from CSV."""
        from extensions import db
        
        lines = csv_content.strip().split('\n')
        reader = csv.reader(lines)
        next(reader)  # Skip header
        
        count = 0
        for row in reader:
            if len(row) < 2:
                continue
            
            try:
                order_number = int(row[0].strip()) if row[0].strip() else 0
                title = row[1].strip()
                description = row[2].strip() if len(row) > 2 else ''
                duration = row[3].strip() if len(row) > 3 else None
                cue_type = row[4].strip() if len(row) > 4 else None
                notes = row[5].strip() if len(row) > 5 else None
                
                item = CrewRunItem(
                    event_id=event_id,
                    order_number=order_number,
                    title=title,
                    description=description,
                    duration=duration,
                    cue_type=cue_type,
                    notes=notes
                )
                db.session.add(item)
                count += 1
            except Exception as e:
                print(f"Error importing crew run item: {e}")
                continue
        
        db.session.commit()
        return count
    
    @staticmethod
    def import_cast_run_list(event_id, csv_content):
        """Import CastRunItem from CSV."""
        from extensions import db
        
        lines = csv_content.strip().split('\n')
        reader = csv.reader(lines)
        next(reader)  # Skip header
        
        count = 0
        for row in reader:
            if len(row) < 2:
                continue
            
            try:
                order_number = int(row[0].strip()) if row[0].strip() else 0
                title = row[1].strip()
                description = row[2].strip() if len(row) > 2 else ''
                duration = row[3].strip() if len(row) > 3 else None
                item_type = row[4].strip() if len(row) > 4 else None
                cast_involved = row[5].strip() if len(row) > 5 else None
                notes = row[6].strip() if len(row) > 6 else None
                
                item = CastRunItem(
                    event_id=event_id,
                    order_number=order_number,
                    title=title,
                    description=description,
                    duration=duration,
                    item_type=item_type,
                    cast_involved=cast_involved,
                    notes=notes
                )
                db.session.add(item)
                count += 1
            except Exception as e:
                print(f"Error importing cast run item: {e}")
                continue
        
        db.session.commit()
        return count
    
    @staticmethod
    def import_picklist(event_id, csv_content, picklist_id=None):
        """Import PickListItem from CSV."""
        from extensions import db
        from decorators import login_required, current_user
        from flask_login import current_user
        
        lines = csv_content.strip().split('\n')
        reader = csv.reader(lines)
        next(reader)  # Skip header
        
        count = 0
        for row in reader:
            if len(row) < 1:
                continue
            
            try:
                item_name = row[0].strip()
                quantity = int(row[1].strip()) if len(row) > 1 and row[1].strip() else 1
                equipment_id = int(row[2].strip()) if len(row) > 2 and row[2].strip() else None
                
                item = PickListItem(
                    event_id=event_id,
                    picklist_id=picklist_id,
                    item_name=item_name,
                    quantity=quantity,
                    equipment_id=equipment_id,
                    added_by='import'
                )
                db.session.add(item)
                count += 1
            except Exception as e:
                print(f"Error importing picklist item: {e}")
                continue
        
        db.session.commit()
        return count
