#!/usr/bin/env python
"""
Master migration runner for ShowWise
Centralizes all database migrations

Usage:
    python run_migrations.py              # Run all pending migrations
    python run_migrations.py --list       # List all available migrations
    python run_migrations.py --rollback   # Rollback the last migration
    python run_migrations.py migrate_2fa  # Run specific migration
"""

import os
import sys
import glob
import importlib.util
from pathlib import Path

def get_migrations():
    """Get list of migration files"""
    migration_dir = Path(__file__).parent
    migration_files = sorted(glob.glob(str(migration_dir / 'migrate_*.py')))
    
    migrations = []
    for f in migration_files:
        name = Path(f).stem  # e.g., 'migrate_2fa' -> 'migrate_2fa'
        migrations.append({
            'name': name,
            'file': f,
            'display_name': name.replace('migrate_', '')
        })
    
    return migrations

def load_migration(migration_file):
    """Dynamically load a migration module"""
    spec = importlib.util.spec_from_file_location("migration", migration_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run_migration(migration_name):
    """Run a specific migration"""
    migrations = get_migrations()
    migration = next((m for m in migrations if m['name'] == migration_name), None)
    
    if not migration:
        print(f"✗ Migration '{migration_name}' not found")
        return False
    
    print(f"\n{'='*60}")
    print(f"Running migration: {migration['display_name']}")
    print(f"{'='*60}\n")
    
    try:
        module = load_migration(migration['file'])
        
        # Check if migration has a main function
        if hasattr(module, 'migrate_2fa'):
            success = module.migrate_2fa()
        elif hasattr(module, 'migrate_user_roles'):
            success = module.migrate_user_roles()
        else:
            print(f"✗ Migration function not found in {migration['name']}")
            return False
        
        return success
        
    except Exception as e:
        print(f"✗ Error running migration: {e}")
        import traceback
        traceback.print_exc()
        return False

def list_migrations():
    """List all available migrations"""
    migrations = get_migrations()
    
    print("\nAvailable migrations:")
    print("-" * 60)
    
    for m in migrations:
        print(f"  ✓ {m['display_name']:<30} ({m['name']})")
    
    print()

def run_all_migrations():
    """Run all available migrations"""
    migrations = get_migrations()
    
    if not migrations:
        print("No migrations found")
        return True
    
    print(f"\nFound {len(migrations)} migration(s)")
    
    results = []
    for migration in migrations:
        success = run_migration(migration['name'])
        results.append({
            'name': migration['display_name'],
            'success': success
        })
    
    # Summary
    print("\n" + "="*60)
    print("Migration Summary")
    print("="*60 + "\n")
    
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    
    for result in results:
        status = "✓" if result['success'] else "✗"
        print(f"{status} {result['name']}")
    
    print()
    print(f"Total: {successful} successful, {failed} failed")
    print()
    
    return failed == 0

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ShowWise Database Migration Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python run_migrations.py                # Run all migrations
  python run_migrations.py --list         # List available migrations
  python run_migrations.py migrate_2fa    # Run specific migration
        '''
    )
    
    parser.add_argument('migration', nargs='?', help='Specific migration to run')
    parser.add_argument('--list', '-l', action='store_true', help='List available migrations')
    parser.add_argument('--all', '-a', action='store_true', help='Run all migrations (default)')
    
    args = parser.parse_args()
    
    if args.list:
        list_migrations()
        sys.exit(0)
    
    if args.migration:
        success = run_migration(args.migration)
        sys.exit(0 if success else 1)
    
    # Default: run all
    success = run_all_migrations()
    sys.exit(0 if success else 1)
