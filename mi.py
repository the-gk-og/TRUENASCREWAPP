# Save as migrate_event_enddate.py and run: python migrate_event_enddate.py

from app import app, db, Event
from sqlalchemy import inspect, text
from datetime import timedelta

def add_event_end_date():
    """Add event_end_date column to Event model"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('event')]
        
        if 'event_end_date' in columns:
            print("✓ event_end_date column already exists")
            return
        
        print("⚙️  Adding event_end_date column...")
        
        try:
            # Add the column
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE event ADD COLUMN event_end_date DATETIME'))
                conn.commit()
                print("✓ Added event_end_date column")
            
            # Set default end dates for existing events (3 hours after start)
            with db.engine.connect() as conn:
                conn.execute(text('''
                    UPDATE event 
                    SET event_end_date = datetime(event_date, '+3 hours')
                    WHERE event_end_date IS NULL
                '''))
                conn.commit()
                print("✓ Set default end dates for existing events")
            
            print("✅ Migration complete!")
            
        except Exception as e:
            print(f"❌ Migration error: {e}")

if __name__ == '__main__':
    add_event_end_date()