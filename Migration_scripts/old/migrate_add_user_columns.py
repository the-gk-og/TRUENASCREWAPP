#!/usr/bin/env python
"""
Simple Migration Script - Add New User Columns
Adds profile_picture, password_reset_token, and password_reset_expiry columns to User table
if they don't already exist.

Usage:
    python migrate_add_user_columns.py
"""

import os
import sys
from datetime import datetime
import sqlite3

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import db, app, User

def check_column_exists(db_path, table_name, column_name):
    """Check if a column exists in SQLite table"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        return column_name in columns
    except Exception as e:
        print(f"⚠️  Error checking column: {e}")
        return False

def run_migration():
    """Run the migration"""
    print("\n" + "="*70)
    print("🔄 MIGRATION: Add User Profile & Password Reset Columns")
    print("="*70 + "\n")
    
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'production_crew.db')
    
    # Check if database exists
    if not os.path.exists(db_path):
        print("❌ Database file not found at:", db_path)
        print("   Initialize the app first by running: python app.py")
        return False
    
    print(f"📁 Database: {db_path}\n")
    
    with app.app_context():
        try:
            # Check for each new column
            columns_to_add = [
                ('profile_picture', 'VARCHAR(300)'),
                ('password_reset_token', 'VARCHAR(100)'),
                ('password_reset_expiry', 'DATETIME')
            ]
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            columns_added = []
            columns_skipped = []
            
            for col_name, col_type in columns_to_add:
                if check_column_exists(db_path, 'user', col_name):
                    print(f"✓ Column already exists: {col_name}")
                    columns_skipped.append(col_name)
                else:
                    # Add the column
                    try:
                        sql = f"ALTER TABLE user ADD COLUMN {col_name} {col_type}"
                        cursor.execute(sql)
                        conn.commit()
                        print(f"✓ Added column: {col_name} ({col_type})")
                        columns_added.append(col_name)
                    except Exception as e:
                        print(f"✗ Failed to add {col_name}: {e}")
                        conn.close()
                        return False
            
            conn.close()
            
            # Summary
            print("\n" + "-"*70)
            print("✅ Migration Summary:")
            print("-"*70)
            if columns_added:
                print(f"  Columns added: {', '.join(columns_added)}")
            if columns_skipped:
                print(f"  Columns already exist: {', '.join(columns_skipped)}")
            
            print(f"\n  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("\n" + "="*70)
            print("✅ Migration completed successfully!")
            print("="*70 + "\n")
            
            return True
            
        except Exception as e:
            print(f"\n❌ Migration failed with error:")
            print(f"   {type(e).__name__}: {e}")
            print("\n" + "="*70 + "\n")
            return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
