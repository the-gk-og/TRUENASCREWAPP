# ShowWise Database Migration Guide

## Overview

This directory contains database migration scripts for ShowWise. Migrations are used to:
- Create new database tables
- Add columns to existing tables
- Update schema safely without losing data
- Track database changes over time

## Quick Start

### Run All Migrations
```bash
cd Migration_scripts
python run_migrations.py
```

### Run Specific Migration (2FA)
```bash
python run_migrations.py migrate_2fa
```

### List Available Migrations
```bash
python run_migrations.py --list
```

## Available Migrations

### 1. migrate_2fa.py - Two-Factor Authentication

**Purpose**: Creates the `two_factor_auth` table for storing TOTP secrets and backup codes

**What it creates**:
```
two_factor_auth table:
├── id (Primary Key)
├── user_id (Foreign Key → user.id)
├── secret (TOTP secret string)
├── enabled (Boolean - is 2FA active?)
├── backup_codes (JSON array of codes)
└── created_at (Timestamp)
```

**Features**:
- ✓ Checks if table already exists (safe to run multiple times)
- ✓ Validates all required columns
- ✓ Creates indexes and foreign keys automatically
- ✓ Can be rolled back if needed

**Usage**:
```bash
# Run the migration
python migrate_2fa.py

# Rollback (WARNING: destructive)
python migrate_2fa.py --rollback
```

**After Migration**:
- Users can enable 2FA in their security settings
- TOTP secrets are stored securely
- Backup codes are hashed before storage

## Migration File Structure

Each migration file should follow this pattern:

```python
#!/usr/bin/env python
"""Description of what this migration does"""

import os
import sys
from app import app, db

def migrate_feature_name():
    """Main migration function"""
    with app.app_context():
        print("Running migration...")
        try:
            # Create tables, add columns, etc.
            db.session.commit()
            print("✓ Migration completed")
            return True
        except Exception as e:
            print(f"✗ Migration failed: {e}")
            return False

if __name__ == '__main__':
    success = migrate_feature_name()
    sys.exit(0 if success else 1)
```

## Creating New Migrations

When adding a new feature that requires database changes:

1. **Create migration file**:
   ```bash
   cd Migration_scripts
   cp migrate_template.py migrate_newfeature.py
   ```

2. **Edit the file**:
   - Update function name (`migrate_newfeature()`)
   - Add your database changes
   - Include error handling
   - Add rollback option if applicable

3. **Test locally**:
   ```bash
   python migrate_newfeature.py
   ```

4. **Add to run_migrations.py**:
   - The runner automatically picks up files named `migrate_*.py`
   - No additional registration needed

5. **Document in this file**:
   - Add section under "Available Migrations"
   - Describe what the migration does
   - Note any special requirements

## Best Practices

### 1. **Always Test First**
```bash
# Test on development database
python migrate_feature.py

# Verify tables/columns created
sqlite3 production_crew.db ".schema table_name"
```

### 2. **Make Migrations Idempotent**
Migrations should be safe to run multiple times:

```python
# ✓ GOOD - Check if exists first
if not table_exists('my_table'):
    # Create table
    pass

# ✗ BAD - Will fail if run twice
CREATE TABLE my_table (...)  # Will error if exists
```

### 3. **Include Rollback Support**
Provide a way to undo changes (with warning):

```python
def rollback_feature():
    """Rollback the migration"""
    print("WARNING: This will DELETE data!")
    confirm = input("Type 'yes' to confirm: ")
    if confirm == 'yes':
        # Drop table or remove column
        pass
```

### 4. **Use Transactions**
Wrap changes in transactions for atomicity:

```python
try:
    db.session.add(obj)
    db.session.commit()
    print("✓ Success")
except Exception as e:
    db.session.rollback()
    print(f"✗ Failed: {e}")
```

### 5. **Log Everything**
Provide clear output:

```python
print("Creating new_table...")
print("✓ Table created")
print("✓ Indexes created")
print("✓ Foreign keys created")
```

## Troubleshooting

### Migration fails with "table already exists"
**Solution**: The script checks for this. If it fails:
```bash
# Check if table exists
sqlite3 production_crew.db ".schema table_name"

# If corrupt, you may need to restore from backup
```

### Migration fails with "Foreign key constraint failed"
**Solution**: Ensure parent table exists:
```bash
# Check if user table exists
sqlite3 production_crew.db ".schema user"
```

### Want to undo a migration
```bash
# For 2FA
python migrate_2fa.py --rollback
```

## Production Deployment

### Before deploying:
1. **Backup database**
   ```bash
   cp production_crew.db production_crew.db.backup
   ```

2. **Test migration on copy**
   ```bash
   cp production_crew.db.backup test_crew.db
   # Run migration on test database
   ```

3. **Schedule during maintenance window**
   - Run when users aren't active
   - Have rollback plan ready

### Deployment steps:
```bash
# 1. Stop the application
systemctl stop showwise

# 2. Backup database
cp production_crew.db production_crew.db.before-migration

# 3. Run migration
python run_migrations.py

# 4. Verify success
python run_migrations.py --list

# 5. Start application
systemctl start showwise

# 6. Monitor logs
tail -f /var/log/showwise/app.log
```

### If migration fails:
```bash
# 1. Stop application immediately
systemctl stop showwise

# 2. Restore backup
cp production_crew.db.before-migration production_crew.db

# 3. Investigate error
# 4. Fix migration script
# 5. Start application
systemctl start showwise
```

## Migration History

### v1.0 - 2FA Support
- **File**: migrate_2fa.py
- **Date**: February 2026
- **Changes**: Added two_factor_auth table
- **Status**: ✓ Deployed

## File Listing

```
Migration_scripts/
├── README.md                    # This file
├── migrate_2fa.py               # 2FA table migration
├── run_migrations.py            # Master migration runner
├── mi.py                        # Legacy migrations (old)
├── mi2.py                       # Legacy migrations (old)
├── mi3.py                       # Legacy migrations (old)
├── mi-usertags.py               # Legacy migrations (old)
└── mi-stageplan.py              # Legacy migrations (old)
```

## Support

If a migration fails:

1. **Check the error message** - it usually tells you what went wrong
2. **Review the migration script** - verify the logic
3. **Check database state** - ensure prerequisites are met
4. **Restore from backup** if needed
5. **Contact support** with:
   - Migration name
   - Error message
   - Database state (run `.schema`)

## References

- [Flask-SQLAlchemy Docs](https://flask-sqlalchemy.palletsprojects.com/)
- [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/)
- [Database Migration Best Practices](https://en.wikipedia.org/wiki/Schema_migration)
