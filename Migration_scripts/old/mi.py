# Save as migrate_new_features.py and run: python migrate_new_features.py

from app import app, db, TodoItem, CastMember
from sqlalchemy import inspect

def migrate_database():
    """Add new tables for To-Do and Cast features"""
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        print("🔄 Checking database for new features...")
        
        # Check if TodoItem table exists
        if 'todo_item' not in existing_tables:
            print("📝 Creating TodoItem table...")
            db.create_all()
            print("✅ TodoItem table created!")
        else:
            print("✓ TodoItem table already exists")
        
        # Check if CastMember table exists
        if 'cast_member' not in existing_tables:
            print("🎭 Creating CastMember table...")
            db.create_all()
            print("✅ CastMember table created!")
        else:
            print("✓ CastMember table already exists")
        
        print("\n✅ Migration complete! All new features are ready to use.")
        print("\nNew features added:")
        print("  • To-Do List system")
        print("  • Cast Management")
        print("  • Admin Overview Dashboard")
        print("  • Event Export functionality")

if __name__ == '__main__':
    migrate_database()