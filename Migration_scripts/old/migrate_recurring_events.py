#!/usr/bin/env python
"""
Migration script to add recurring events and unavailability features

This script:
- Adds recurrence columns to the event table
- Creates the user_unavailability table
- Creates the recurring_unavailability table
- Can be run multiple times safely (idempotent)

Usage:
    python migrate_recurring_events.py
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import inspect, String, Integer, DateTime, Boolean, Text, ForeignKey, text

def table_exists(table_name):
    """Check if a table exists in the database"""
    try:
        inspector = inspect(db.engine)
        return table_name in inspector.get_table_names()
    except Exception as e:
        print(f"Error checking table existence: {e}")
        return False

def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    try:
        inspector = inspect(db.engine)
        if table_name not in inspector.get_table_names():
            return False
        columns = [c['name'] for c in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception as e:
        print(f"Error checking column existence: {e}")
        return False

def add_column_to_table(table_name, column_name, column_type, nullable=True, default=None):
    """Add a column to an existing table using raw SQL"""
    try:
        # Get the appropriate SQL dialect
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            if default is not None:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default}"
            else:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        else:
            # MySQL/PostgreSQL style
            nullable_str = "NULL" if nullable else "NOT NULL"
            if default is not None:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {nullable_str} DEFAULT {default}"
            else:
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {nullable_str}"
        
        db.session.execute(text(sql))
        db.session.commit()
        print(f"  ✓ Added column {column_name} to {table_name}")
        return True
    except Exception as e:
        db.session.rollback()
        if 'already exists' in str(e) or 'Duplicate' in str(e) or 'duplicate column name' in str(e):
            print(f"  ✓ Column {column_name} already exists in {table_name}")
            return True
        print(f"  ✗ Error adding column {column_name}: {e}")
        return False

def migrate_recurring_events():
    """Perform the migration"""
    with app.app_context():
        print("=" * 70)
        print("ShowWise Recurring Events & Unavailability Migration")
        print("=" * 70)
        print()
        
        # Step 1: Add columns to event table
        print("Step 1: Adding recurrence columns to 'event' table...")
        if not table_exists('event'):
            print("  ✗ event table does not exist!")
            return False
        
        columns_to_add = [
            ('recurrence_pattern', 'VARCHAR(50)', True, None),
            ('recurrence_interval', 'INTEGER', True, '1'),
            ('recurrence_end_date', 'DATETIME', True, None),
            ('recurrence_count', 'INTEGER', True, None),
            ('is_recurring_instance', 'BOOLEAN', True, '0'),
            ('recurring_event_id', 'INTEGER', True, None),
        ]
        
        added_count = 0
        for col_name, col_type, nullable, default in columns_to_add:
            if not column_exists('event', col_name):
                if add_column_to_table('event', col_name, col_type, nullable, default):
                    added_count += 1
            else:
                print(f"  ✓ Column {col_name} already exists")
        
        print(f"  Added {added_count} new column(s) to event table")
        print()
        
        # Step 2: Create user_unavailability table
        print("Step 2: Creating 'user_unavailability' table...")
        if not table_exists('user_unavailability'):
            try:
                # Create using SQLAlchemy models
                from app import UserUnavailability
                db.create_all()
                print("  ✓ Created user_unavailability table")
            except Exception as e:
                print(f"  ✗ Error creating user_unavailability table: {e}")
                db.session.rollback()
                return False
        else:
            print("  ✓ user_unavailability table already exists")
        
        print()
        
        # Step 3: Create recurring_unavailability table
        print("Step 3: Creating 'recurring_unavailability' table...")
        if not table_exists('recurring_unavailability'):
            try:
                from app import RecurringUnavailability
                db.create_all()
                print("  ✓ Created recurring_unavailability table")
            except Exception as e:
                print(f"  ✗ Error creating recurring_unavailability table: {e}")
                db.session.rollback()
                return False
        else:
            print("  ✓ recurring_unavailability table already exists")
        
        print()
        print("=" * 70)
        print("✓ Migration completed successfully!")
        print("=" * 70)
        return True

if __name__ == '__main__':
    try:
        success = migrate_recurring_events()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Unexpected error during migration: {e}")
        sys.exit(1)
