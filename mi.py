# Save this as migrate_db.py in your project root and run it: python migrate_db.py

from app import app, db
from sqlalchemy import inspect, text

def migrate_database():
    """Migrate EventSchedule table to use 'title' instead of 'schedule_type'"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        
        # Check if event_schedule table exists
        if 'event_schedule' not in inspector.get_table_names():
            print("✓ event_schedule table does not exist yet - will be created")
            db.create_all()
            print("✓ Created all tables")
            return
        
        # Check if title column already exists
        columns = [col['name'] for col in inspector.get_columns('event_schedule')]
        
        if 'title' in columns:
            print("✓ 'title' column already exists - no migration needed")
            return
        
        if 'schedule_type' in columns:
            print("⚙️  Migrating schedule_type to title...")
            
            try:
                # Add title column
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE event_schedule ADD COLUMN title VARCHAR(100)'))
                    conn.commit()
                    print("✓ Added 'title' column")
                
                # Copy data from schedule_type to title
                with db.engine.connect() as conn:
                    conn.execute(text('UPDATE event_schedule SET title = schedule_type WHERE title IS NULL'))
                    conn.commit()
                    print("✓ Copied data from schedule_type to title")
                
                # Drop old column (SQLite doesn't support DROP COLUMN easily, so we'll just leave it)
                print("✓ Migration complete! schedule_type column can be manually dropped if desired")
                
            except Exception as e:
                print(f"❌ Migration error: {e}")
                print("Trying SQLite-compatible approach...")
                
                # For SQLite - rebuild table
                try:
                    with db.engine.connect() as conn:
                        # Create new table with correct schema
                        conn.execute(text('''
                            CREATE TABLE event_schedule_new (
                                id INTEGER PRIMARY KEY,
                                event_id INTEGER NOT NULL,
                                title VARCHAR(100) NOT NULL,
                                scheduled_time DATETIME NOT NULL,
                                description TEXT,
                                created_at DATETIME,
                                FOREIGN KEY(event_id) REFERENCES event(id)
                            )
                        '''))
                        
                        # Copy data
                        conn.execute(text('''
                            INSERT INTO event_schedule_new (id, event_id, title, scheduled_time, description, created_at)
                            SELECT id, event_id, schedule_type, scheduled_time, description, created_at
                            FROM event_schedule
                        '''))
                        
                        # Drop old table
                        conn.execute(text('DROP TABLE event_schedule'))
                        
                        # Rename new table
                        conn.execute(text('ALTER TABLE event_schedule_new RENAME TO event_schedule'))
                        
                        conn.commit()
                        print("✓ SQLite migration complete!")
                        
                except Exception as e2:
                    print(f"❌ SQLite migration failed: {e2}")
        else:
            print("✓ Table structure already correct")

if __name__ == '__main__':
    migrate_database()
    print("\n✅ Database migration finished!")