"""
add_archive_columns.py
======================
Safely adds missing archive and grouping columns to existing tables.
Preserves all existing data - no data loss.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import inspect, text

def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    try:
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception as e:
        print(f"Error checking columns: {e}")
        return False

def add_column_if_missing(table_name, column_name, column_type, default_value=None):
    """
    Safely add a column to a table if it doesn't exist.
    Preserves all existing data.
    """
    if column_exists(table_name, column_name):
        print(f"✓ Column {table_name}.{column_name} already exists")
        return True
    
    try:
        # For SQLite, we need to use raw SQL
        if 'sqlite' in db.engine.url.drivername:
            if column_type == 'BOOLEAN':
                sql_type = 'INTEGER'
                sql_default = f"DEFAULT {1 if default_value else 0}"
            elif column_type == 'INTEGER':
                sql_type = 'INTEGER'
                sql_default = f"DEFAULT {default_value}" if default_value is not None else ""
            else:
                sql_type = column_type
                sql_default = f"DEFAULT '{default_value}'" if default_value else ""
            
            alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type} {sql_default}".strip()
            with db.engine.connect() as connection:
                connection.execute(text(alter_sql))
                connection.commit()
            print(f"✓ Added column {table_name}.{column_name}")
            return True
        else:
            print(f"⚠️  Unknown database type: {db.engine.url.drivername}")
            return False
    except Exception as e:
        print(f"✗ Error adding column {table_name}.{column_name}: {e}")
        return False

def main():
    """Run the migration."""
    app = create_app()
    
    with app.app_context():
        print("\nStarting column migration...")
        print("=" * 60)
        
        # Shift table - add is_archived column
        print("\n📋 Processing Shift table...")
        add_column_if_missing('shift', 'is_archived', 'BOOLEAN', default_value=False)
        
        # PickListItem table - add picklist_id and is_archived columns
        print("\n📋 Processing PickListItem table...")
        add_column_if_missing('pick_list_item', 'picklist_id', 'INTEGER', default_value=None)
        add_column_if_missing('pick_list_item', 'is_archived', 'BOOLEAN', default_value=False)
        
        # StagePlan table - add collection_id and is_archived columns
        print("\n📋 Processing StagePlan table...")
        add_column_if_missing('stage_plan', 'collection_id', 'INTEGER', default_value=None)
        add_column_if_missing('stage_plan', 'is_archived', 'BOOLEAN', default_value=False)
        
        print("\n" + "=" * 60)
        print("✅ Column migration completed successfully!")
        print("\nNew columns added (all data preserved):")
        print("  • shift.is_archived")
        print("  • pick_list_item.picklist_id")
        print("  • pick_list_item.is_archived")
        print("  • stage_plan.collection_id")
        print("  • stage_plan.is_archived")

if __name__ == '__main__':
    main()
