# Save as migrate_cast_features.py and run: python migrate_cast_features.py

from app import app, db
from sqlalchemy import inspect, text

def migrate_database():
    """Add cast features to existing database"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        
        print("🔄 Adding cast features to database...")
        
        # Add is_cast column to User table
        try:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE user ADD COLUMN is_cast BOOLEAN DEFAULT 0'))
                conn.commit()
            print("✅ Added is_cast column to User table")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                print(f"⚠️  User.is_cast: {e}")
            else:
                print("✓ User.is_cast already exists")
        
        # Add cast_description column to Event table
        try:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE event ADD COLUMN cast_description TEXT'))
                conn.commit()
            print("✅ Added cast_description column to Event table")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                print(f"⚠️  Event.cast_description: {e}")
            else:
                print("✓ Event.cast_description already exists")
        
        # Add user_id to CastMember table
        try:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE cast_member ADD COLUMN user_id INTEGER'))
                conn.commit()
            print("✅ Added user_id column to CastMember table")
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                print(f"⚠️  CastMember.user_id: {e}")
            else:
                print("✓ CastMember.user_id already exists")
        
        # Create new tables
        existing_tables = inspector.get_table_names()
        
        if 'cast_schedule' not in existing_tables:
            print("📅 Creating CastSchedule table...")
            db.create_all()
            print("✅ CastSchedule table created!")
        else:
            print("✓ CastSchedule table already exists")
        
        if 'cast_note' not in existing_tables:
            print("📝 Creating CastNote table...")
            db.create_all()
            print("✅ CastNote table created!")
        else:
            print("✓ CastNote table already exists")
        
        print("\n✅ Migration complete! Cast features are ready to use.")
        print("\nNew features:")
        print("  • Cast accounts created from Cast Management")
        print("  • Cast members see only their events")
        print("  • Separate cast description, schedule, and notes")
        print("  • Only admins can edit cast content")

if __name__ == '__main__':
    migrate_database()