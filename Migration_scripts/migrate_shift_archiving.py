"""
Migration script for shift archiving support.
Run this script to update your database schema.

python migrate_shift_archiving.py
"""

import sys
sys.path.insert(0, '/home/elijah/Documents/Projects/WEBAPPS/Active-ShowWise/ShowWise')

from app import create_app, db
from models import Shift

def migrate():
    """Run the migration."""
    app = create_app()
    with app.app_context():
        print("Starting shift archiving migration...")
        
        # Create all tables - this will add the is_archived column if it doesn't exist
        print("Creating/updating tables...")
        db.create_all()
        
        print("✅ Shift archiving migration completed successfully!")
        print("\nNew features enabled:")
        print("  - Auto-archive shifts when they end")
        print("  - Manual archive/unarchive of shifts")
        print("  - Query parameter to include/exclude archived shifts")

if __name__ == '__main__':
    migrate()
