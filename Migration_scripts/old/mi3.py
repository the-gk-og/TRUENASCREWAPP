#!/usr/bin/env python3
"""
Simple ShowWise Database Migration
Quick and easy - just run it!
"""

from app import app, db
from datetime import datetime
import os
import shutil

def main():
    print("\n" + "="*60)
    print("ShowWise Database Migration - Simple Version".center(60))
    print("="*60 + "\n")
    
    # Create backup
    db_path = 'production_crew.db'
    if os.path.exists(db_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = 'backups'
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f'backup_{timestamp}.db')
        
        print(f"📦 Creating backup...")
        shutil.copy2(db_path, backup_path)
        print(f"✓ Backup saved: {backup_path}\n")
    
    # Run migrations
    print("🔄 Running migrations...")
    
    with app.app_context():
        try:
            # This will create any missing tables
            db.create_all()
            print("✓ All tables created/verified")
            
            # Check what was added
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            security_tables = [
                'two_factor_auth',
                'oauth_connection', 
                'audit_log',
                'api_token'
            ]
            
            print("\n📋 Security Tables Status:")
            for table in security_tables:
                if table in tables:
                    print(f"  ✓ {table}")
                else:
                    print(f"  ✗ {table} (missing)")
            
            print("\n✅ Migration completed successfully!")
            print("\nYou can now use:")
            print("  • Two-Factor Authentication (TOTP)")
            print("  • Google OAuth Login")
            print("  • Security Audit Logging")
            print("  • API Token Authentication")
            
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            print(f"You can restore from backup: {backup_path}")
            return False
    
    return True

if __name__ == '__main__':
    main()