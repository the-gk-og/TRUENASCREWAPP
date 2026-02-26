#!/usr/bin/env python3
"""
Migration script to add missing columns to the user table.

This script handles the migration for SQLite and other database backends.
It will:
1. Check if specific columns exist in the user table
2. Add any missing columns with appropriate types and constraints
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app, db
from sqlalchemy import inspect, String, DateTime, text
from sqlalchemy.exc import OperationalError


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    try:
        inspector = inspect(db.engine)
        columns = inspector.get_columns(table_name)
        return any(col['name'] == column_name for col in columns)
    except Exception as e:
        print(f"Error checking column existence: {e}")
        return False


def add_missing_columns():
    """Add missing columns to user table if they don't exist."""
    with app.app_context():
        table_name = 'user'
        
        # Define columns to be added: (column_name, sql_type)
        columns_to_add = [
            ('profile_picture', 'VARCHAR(300)'),
            ('password_reset_token', 'VARCHAR(100)'),
            ('password_reset_expiry', 'DATETIME'),
        ]
        
        all_success = True
        
        for column_name, sql_type in columns_to_add:
            print(f"Checking if {column_name} column exists in {table_name} table...")
            
            if column_exists(table_name, column_name):
                print(f"✓ Column {column_name} already exists in {table_name} table")
                continue
            
            print(f"✗ Column {column_name} not found in {table_name} table")
            print(f"Adding {column_name} column to {table_name} table...")
            
            try:
                # Get the database dialect to handle database-specific syntax
                dialect = db.engine.dialect.name
                
                with db.engine.connect() as connection:
                    connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {sql_type}'))
                    connection.commit()
                
                print(f"✓ Successfully added {column_name} column to {table_name} table")
                
            except OperationalError as e:
                if 'already exists' in str(e) or 'duplicate column' in str(e):
                    print(f"✓ Column {column_name} already exists (caught via error)")
                else:
                    print(f"✗ Error adding column: {e}")
                    all_success = False
            except Exception as e:
                print(f"✗ Unexpected error: {e}")
                all_success = False
        
        return all_success


def main():
    """Main function to run the migration."""
    print("=" * 60)
    print("User Table Columns Migration")
    print("=" * 60)
    
    success = add_missing_columns()
    
    print("=" * 60)
    if success:
        print("Migration completed successfully!")
        return 0
    else:
        print("Migration completed with some errors. Please check above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
