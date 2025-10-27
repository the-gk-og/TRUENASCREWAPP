#!/usr/bin/env python3
"""
Migration script to add user_role column to existing ShowWise database
Run this script once after updating to the new version with user roles

Usage:
    python migrate_user_roles.py
"""

import sys
import os
from sqlalchemy import inspect, text

# Add the parent directory to the path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def migrate_user_roles():
    """Add user_role column and migrate existing users"""
    
    print("\n" + "="*60)
    print("ShowWise Database Migration - User Roles")
    print("="*60 + "\n")
    
    # Import Flask app and database
    try:
        from app import app, db, User
        print("✓ Successfully imported Flask app and database")
    except ImportError as e:
        print(f"❌ Error importing app: {e}")
        print("\nMake sure you're running this script from the ShowWise directory")
        sys.exit(1)
    
    with app.app_context():
        try:
            # Check if column already exists
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]
            
            if 'user_role' in columns:
                print("⚠️  Column 'user_role' already exists")
                
                # Ask if user wants to re-migrate data
                response = input("\nDo you want to update existing user roles based on is_cast flag? (y/n): ")
                if response.lower() != 'y':
                    print("\nMigration cancelled.")
                    return
            else:
                print("➜ Adding 'user_role' column to user table...")
                
                # Add the column with SQLite-compatible syntax
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE user ADD COLUMN user_role VARCHAR(20) DEFAULT "crew"'))
                        conn.commit()
                    print("✓ Added 'user_role' column successfully")
                except Exception as e:
                    print(f"❌ Error adding column: {e}")
                    sys.exit(1)
            
            # Migrate existing users
            print("\n➜ Migrating existing user data...")
            users = User.query.all()
            
            if not users:
                print("⚠️  No users found in database")
                return
            
            print(f"   Found {len(users)} users to process")
            
            migrated_count = 0
            for user in users:
                # Check if user_role needs to be set
                current_role = getattr(user, 'user_role', None)
                
                if current_role is None or current_role == '':
                    # Set role based on is_cast flag
                    if user.is_cast:
                        user.user_role = 'cast'
                        print(f"   - {user.username}: set to 'cast'")
                    else:
                        user.user_role = 'crew'
                        print(f"   - {user.username}: set to 'crew'")
                    migrated_count += 1
                else:
                    print(f"   - {user.username}: already has role '{current_role}'")
            
            # Commit changes
            if migrated_count > 0:
                db.session.commit()
                print(f"\n✓ Successfully migrated {migrated_count} user(s)")
            else:
                print("\n✓ All users already have roles assigned")
            
            # Display summary
            print("\n" + "-"*60)
            print("Migration Summary:")
            print("-"*60)
            
            role_counts = {}
            for user in User.query.all():
                role = getattr(user, 'user_role', 'unknown')
                admin_status = " (Admin)" if user.is_admin else ""
                role_counts[role + admin_status] = role_counts.get(role + admin_status, 0) + 1
            
            for role, count in sorted(role_counts.items()):
                print(f"   {role}: {count}")
            
            print("\n" + "="*60)
            print("✓ Migration completed successfully!")
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    try:
        migrate_user_roles()
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)