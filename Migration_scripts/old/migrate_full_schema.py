#!/usr/bin/env python3
"""
Comprehensive database schema migration script.

This script ensures the entire database schema matches the SQLAlchemy models.
It will:
1. Create all missing tables
2. Add all missing columns to existing tables
3. Handle both SQLite and other database backends
4. Preserve existing data
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app, db
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError


def get_all_tables():
    """Get all table names from the database."""
    try:
        inspector = inspect(db.engine)
        return inspector.get_table_names()
    except Exception as e:
        print(f"Error getting table names: {e}")
        return []


def get_table_columns(table_name):
    """Get all columns in a table."""
    try:
        inspector = inspect(db.engine)
        columns = inspector.get_columns(table_name)
        return {col['name']: col for col in columns}
    except Exception as e:
        print(f"Error getting columns for {table_name}: {e}")
        return {}


def get_model_columns():
    """Get column definitions from SQLAlchemy models."""
    model_columns = {}
    
    # Get all declared models
    for attr_name in dir(db.Model.registry.mappers):
        try:
            mapper = getattr(db.Model.registry.mappers, attr_name, None)
            if mapper and hasattr(mapper, 'class_'):
                model_class = mapper.class_
                table_name = model_class.__tablename__ if hasattr(model_class, '__tablename__') else None
                if table_name:
                    columns = {}
                    if hasattr(model_class, '__table__'):
                        for col in model_class.__table__.columns:
                            columns[col.name] = {
                                'type': str(col.type),
                                'nullable': col.nullable,
                                'primary_key': col.primary_key,
                                'column_obj': col
                            }
                    model_columns[table_name] = columns
        except Exception:
            pass
    
    return model_columns


def sql_type_from_column(column_obj):
    """Convert SQLAlchemy column type to SQL type string."""
    col_type = column_obj.type
    type_str = str(col_type)
    
    # Handle specific type mappings
    if 'VARCHAR' in type_str:
        length = col_type.length if hasattr(col_type, 'length') else 300
        return f'VARCHAR({length})'
    elif 'INTEGER' in type_str:
        return 'INTEGER'
    elif 'DATETIME' in type_str:
        return 'DATETIME'
    elif 'TEXT' in type_str:
        return 'TEXT'
    elif 'BOOLEAN' in type_str:
        return 'BOOLEAN'
    else:
        return type_str


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    columns = get_table_columns(table_name)
    return column_name in columns


def add_column(table_name, column_name, column_obj):
    """Add a column to a table."""
    try:
        sql_type = sql_type_from_column(column_obj)
        nullable = 'NULL' if column_obj.nullable else 'NOT NULL'
        
        with db.engine.connect() as connection:
            sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {sql_type} {nullable}'
            connection.execute(text(sql))
            connection.commit()
        
        print(f"  ✓ Added column {column_name}")
        return True
    except OperationalError as e:
        if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
            print(f"  ✓ Column {column_name} already exists")
            return True
        else:
            print(f"  ✗ Error adding column {column_name}: {e}")
            return False
    except Exception as e:
        print(f"  ✗ Unexpected error adding column {column_name}: {e}")
        return False


def ensure_schema():
    """Ensure the database schema matches the models."""
    with app.app_context():
        print("\n" + "=" * 60)
        print("Full Database Schema Verification")
        print("=" * 60 + "\n")
        
        # Use Flask-SQLAlchemy's create_all to create missing tables
        print("Creating missing tables...")
        try:
            db.create_all()
            print("✓ All tables created/verified\n")
        except Exception as e:
            print(f"✗ Error creating tables: {e}\n")
            return False
        
        # Now verify and add missing columns
        existing_tables = get_all_tables()
        print(f"Found {len(existing_tables)} tables in database\n")
        
        # Get models from the registry
        all_success = True
        
        for mapper in db.Model.registry.mappers:
            model_class = mapper.class_
            table_name = model_class.__tablename__ if hasattr(model_class, '__tablename__') else None
            
            if not table_name:
                continue
            
            print(f"Checking table: {table_name}")
            
            if table_name not in existing_tables:
                print(f"  ⚠ Table {table_name} not found (should have been created above)")
                continue
            
            # Check columns in this table
            existing_columns = get_table_columns(table_name)
            
            if hasattr(model_class, '__table__'):
                for column in model_class.__table__.columns:
                    col_name = column.name
                    
                    if col_name not in existing_columns:
                        print(f"  Missing column: {col_name}")
                        if not add_column(table_name, col_name, column):
                            all_success = False
                    else:
                        print(f"  ✓ Column {col_name} exists")
            
            print()
        
        return all_success


def main():
    """Main function to run the migration."""
    print("\n")
    success = ensure_schema()
    
    print("=" * 60)
    if success:
        print("✓ Database schema validation completed successfully!")
        print("=" * 60 + "\n")
        return 0
    else:
        print("⚠ Database schema validation completed with some warnings.")
        print("Please review the errors above.")
        print("=" * 60 + "\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
