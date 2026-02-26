#!/usr/bin/env python
"""
Migration script to add 2FA (Two-Factor Authentication) table
Creates the 'two_factor_auth' table for storing TOTP secrets and backup codes

Usage:
    python migrate_2fa.py
    
This script:
- Creates the two_factor_auth table if it doesn't exist
- Links to existing users via foreign key
- Stores TOTP secrets, backup codes, and enabled status
- Can be run multiple times safely (idempotent)
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import inspect, String, Boolean, Text, Integer, DateTime, ForeignKey

def table_exists(table_name):
    """Check if a table exists in the database"""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()

def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns

def migrate_2fa():
    """Migrate 2FA table"""
    with app.app_context():
        print("=" * 60)
        print("ShowWise 2FA Migration Script")
        print("=" * 60)
        print()
        
        # Check if table exists
        if table_exists('two_factor_auth'):
            print("✓ two_factor_auth table already exists")
            print()
            
            # Check for missing columns (in case of partial migration)
            required_columns = {
                'id': 'Integer',
                'user_id': 'Integer',
                'secret': 'String',
                'enabled': 'Boolean',
                'backup_codes': 'Text',
                'created_at': 'DateTime'
            }
            
            missing = []
            for col_name, col_type in required_columns.items():
                if not column_exists('two_factor_auth', col_name):
                    missing.append(col_name)
            
            if missing:
                print(f"⚠️  Missing columns: {', '.join(missing)}")
                print("   Please restore from backup or manually add columns")
                return False
            
            print("✓ All required columns present")
            print()
            return True
        
        # Table doesn't exist - create it
        print("Creating two_factor_auth table...")
        
        try:
            # Create the table using SQLAlchemy
            with db.engine.connect() as connection:
                # Create the table
                connection.execute(db.text('''
                    CREATE TABLE two_factor_auth (
                        id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        secret VARCHAR(32) NOT NULL,
                        enabled BOOLEAN DEFAULT 0,
                        backup_codes TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        UNIQUE (user_id),
                        FOREIGN KEY (user_id) REFERENCES user (id)
                    )
                '''))
                connection.commit()
            
            print("✓ Created two_factor_auth table")
            print()
            
            # Show table structure
            print("Table structure:")
            print("-" * 60)
            inspector = inspect(db.engine)
            columns = inspector.get_columns('two_factor_auth')
            for col in columns:
                nullable = 'NULL' if col['nullable'] else 'NOT NULL'
                print(f"  {col['name']:<15} {str(col['type']):<15} {nullable}")
            
            print()
            print("✓ Migration completed successfully!")
            print()
            print("Next steps:")
            print("  1. Restart your application")
            print("  2. Users can enable 2FA in their security settings")
            print("  3. Each user's 2FA settings are stored in this table")
            print()
            return True
            
        except Exception as e:
            print(f"✗ Error creating table: {e}")
            print()
            return False

def rollback_2fa():
    """Rollback 2FA table (delete it)"""
    with app.app_context():
        print("WARNING: This will DELETE the two_factor_auth table!")
        response = input("Type 'yes' to confirm: ")
        
        if response.lower() != 'yes':
            print("Rollback cancelled")
            return False
        
        if not table_exists('two_factor_auth'):
            print("⚠️  two_factor_auth table doesn't exist")
            return True
        
        try:
            with db.engine.connect() as connection:
                connection.execute(db.text('DROP TABLE two_factor_auth'))
                connection.commit()
            
            print("✓ two_factor_auth table deleted")
            print()
            print("⚠️  All 2FA data has been lost!")
            print("   Users will need to re-enable 2FA")
            print()
            return True
            
        except Exception as e:
            print(f"✗ Error deleting table: {e}")
            return False

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='ShowWise 2FA Migration Script')
    parser.add_argument('--rollback', action='store_true', help='Delete the 2FA table (WARNING: destructive)')
    args = parser.parse_args()
    
    if args.rollback:
        success = rollback_2fa()
    else:
        success = migrate_2fa()
    
    sys.exit(0 if success else 1)
