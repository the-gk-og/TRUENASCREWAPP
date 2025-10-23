# Save as migrate_run_lists.py and run: python migrate_run_lists.py

from app import app, db
from sqlalchemy import inspect

def migrate_database():
    """Add run list tables to database"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("🔄 Adding run list features to database...")
        
        # Create CrewRunItem table
        if 'crew_run_item' not in existing_tables:
            print("🎬 Creating CrewRunItem table...")
            db.create_all()
            print("✅ CrewRunItem table created!")
        else:
            print("✓ CrewRunItem table already exists")
        
        # Create CastRunItem table
        if 'cast_run_item' not in existing_tables:
            print("🎭 Creating CastRunItem table...")
            db.create_all()
            print("✅ CastRunItem table created!")
        else:
            print("✓ CastRunItem table already exists")
        
        print("\n✅ Migration complete! Run list features are ready to use.")
        print("\nNew features added:")
        print("  • Crew run lists (technical cues, setup steps)")
        print("  • Cast run lists (scenes, songs, show order)")
        print("  • Drag-and-drop reordering")
        print("  • Duration tracking")
        print("  • Type categorization")

if __name__ == '__main__':
    migrate_database()