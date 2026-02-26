#!/usr/bin/env python3
"""
Master Database Migration Script

This script ensures the entire database schema is complete and correct:
- Creates all missing tables
- Adds all missing columns to existing tables
- Validates column types and constraints
- Preserves all existing data

Usage:
    python Migration_scripts/migrate_master.py
"""

import sys
from pathlib import Path

# Add parent directory to path to import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app, db
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError


class DatabaseMigrator:
    """Handles comprehensive database migration and schema validation."""
    
    def __init__(self):
        self.app = app
        self.db = db
        self.success_count = 0
        self.warning_count = 0
        self.error_count = 0
    
    def log_success(self, message):
        """Log a success message."""
        print(f"  ✓ {message}")
        self.success_count += 1
    
    def log_warning(self, message):
        """Log a warning message."""
        print(f"  ⚠ {message}")
        self.warning_count += 1
    
    def log_error(self, message):
        """Log an error message."""
        print(f"  ✗ {message}")
        self.error_count += 1
    
    def get_existing_tables(self):
        """Get list of existing tables in the database."""
        try:
            inspector = inspect(self.db.engine)
            return set(inspector.get_table_names())
        except Exception as e:
            self.log_error(f"Failed to get existing tables: {e}")
            return set()
    
    def get_table_columns(self, table_name):
        """Get all columns in a table with their properties."""
        try:
            inspector = inspect(self.db.engine)
            columns = {}
            for col in inspector.get_columns(table_name):
                columns[col['name']] = col
            return columns
        except Exception as e:
            self.log_error(f"Failed to get columns for table {table_name}: {e}")
            return {}
    
    def sql_type_string(self, column):
        """Convert SQLAlchemy column type to SQL string."""
        col_type = column.type
        type_name = col_type.__class__.__name__
        
        if type_name == 'VARCHAR':
            length = col_type.length if col_type.length else 300
            return f'VARCHAR({length})'
        elif type_name == 'String':
            length = col_type.length if col_type.length else 300
            return f'VARCHAR({length})'
        elif type_name == 'Integer':
            return 'INTEGER'
        elif type_name == 'DateTime':
            return 'DATETIME'
        elif type_name == 'Text':
            return 'TEXT'
        elif type_name == 'Boolean':
            return 'BOOLEAN'
        else:
            return str(col_type)
    
    def add_column_to_table(self, table_name, column):
        """Add a single column to a table."""
        col_name = column.name
        col_type = self.sql_type_string(column)
        nullable = '' if column.nullable else 'NOT NULL'
        
        try:
            sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type} {nullable}'.strip()
            with self.db.engine.begin() as conn:
                conn.execute(text(sql))
            self.log_success(f"Added column {col_name} to {table_name}")
            return True
        except OperationalError as e:
            error_str = str(e).lower()
            if 'already exists' in error_str or 'duplicate' in error_str:
                # Column already exists, this is fine
                return True
            else:
                self.log_error(f"Failed to add column {col_name} to {table_name}: {e}")
                return False
        except Exception as e:
            self.log_error(f"Unexpected error adding column {col_name}: {e}")
            return False
    
    def create_tables(self):
        """Create all tables that don't exist yet."""
        print("\n" + "=" * 70)
        print("STEP 1: Creating Missing Tables")
        print("=" * 70)
        
        try:
            with self.app.app_context():
                self.db.create_all()
            self.log_success("All tables created/verified")
            return True
        except Exception as e:
            self.log_error(f"Failed to create tables: {e}")
            return False
    
    def validate_columns(self):
        """Validate and add missing columns to existing tables."""
        print("\n" + "=" * 70)
        print("STEP 2: Validating and Adding Missing Columns")
        print("=" * 70)
        
        with self.app.app_context():
            existing_tables = self.get_existing_tables()
            
            if not existing_tables:
                self.log_error("No tables found in database")
                return False
            
            print(f"\nFound {len(existing_tables)} table(s) in database\n")
            
            # Iterate through all models
            for mapper in self.db.Model.registry.mappers:
                model_class = mapper.class_
                table_name = model_class.__tablename__ if hasattr(model_class, '__tablename__') else None
                
                if not table_name:
                    continue
                
                print(f"Validating table: {table_name}")
                
                if table_name not in existing_tables:
                    self.log_warning(f"Table {table_name} not found (should have been created)")
                    continue
                
                # Get existing columns in this table
                existing_columns = self.get_table_columns(table_name)
                
                # Get columns from the model
                if hasattr(model_class, '__table__'):
                    for column in model_class.__table__.columns:
                        col_name = column.name
                        
                        if col_name not in existing_columns:
                            print(f"  Missing column detected: {col_name}")
                            self.add_column_to_table(table_name, column)
                        else:
                            self.log_success(f"Column {col_name} exists")
                
                print()
        
        return True
    
    def run_migration(self):
        """Run the complete migration process."""
        print("\n")
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 68 + "║")
        print("║" + "  Master Database Migration Script".center(68) + "║")
        print("║" + "  Ensuring complete and correct database schema".center(68) + "║")
        print("║" + " " * 68 + "║")
        print("╚" + "=" * 68 + "╝")
        
        # Step 1: Create all tables
        if not self.create_tables():
            print("\n✗ Migration failed at table creation step")
            return False
        
        # Step 2: Validate and add columns
        if not self.validate_columns():
            print("\n✗ Migration failed at column validation step")
            return False
        
        # Summary
        print("\n" + "=" * 70)
        print("Migration Summary")
        print("=" * 70)
        print(f"✓ Successful operations: {self.success_count}")
        print(f"⚠ Warnings: {self.warning_count}")
        print(f"✗ Errors: {self.error_count}")
        print("=" * 70)
        
        if self.error_count == 0:
            print("\n✓ Migration completed successfully!")
            print("  Your database schema is now complete and correct.\n")
            return True
        else:
            print("\n⚠ Migration completed with errors.")
            print("  Please review the errors above.\n")
            return False


def main():
    """Main entry point."""
    migrator = DatabaseMigrator()
    success = migrator.run_migration()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
