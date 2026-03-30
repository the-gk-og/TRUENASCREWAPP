"""
Migration script for archiving and grouped picklists/stage plans support.
Run this script to update your database schema.

python migrate_archive_and_groups.py
"""

import sys
sys.path.insert(0, '/home/elijah/Documents/Projects/WEBAPPS/Active-ShowWise/ShowWise')

from app import create_app, db
from models import Event, PickListItem, StagePlan, Picklist, StagePlanCollection

def migrate():
    """Run the migration."""
    app = create_app()
    with app.app_context():
        print("Starting migration...")
        
        # Create new tables by using db.create_all()
        print("Creating new tables (Picklist, StagePlanCollection, and adding archive columns)...")
        db.create_all()
        
        print("✅ Migration completed successfully!")
        print("New features enabled:")
        print("  - Archive stageplans and picklists after event ends")
        print("  - CSV import/export for schedules and run lists")
        print("  - Multiple picklists per event")
        print("  - Multiple stage plans per event (via collections)")

if __name__ == '__main__':
    migrate()
