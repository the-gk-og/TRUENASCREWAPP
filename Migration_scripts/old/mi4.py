#!/usr/bin/env python3
"""
ShowWise Database Migration (sqschemify version)
Adds: skip_2fa_for_oauth BOOLEAN DEFAULT 0
"""

import os
import shutil
import sqlite3
from datetime import datetime

# Import your sqschemify models + engine
# Adjust this import to match your project structure
from db_models import engine   # SQLAlchemy engine created by sqschemify


DB_PATH = "production_crew.db"


def backup_database():
    if not os.path.exists(DB_PATH):
        print("⚠️  Database not found:", DB_PATH)
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)

    backup_path = os.path.join(backup_dir, f"backup_{timestamp}.db")
    shutil.copy2(DB_PATH, backup_path)

    print(f"📦 Backup created: {backup_path}")
    return backup_path


def column_exists():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(user);")
    columns = [col[1] for col in cursor.fetchall()]

    conn.close()
    return "skip_2fa_for_oauth" in columns


def run_migration():
    print("🔄 Running migration: Add skip_2fa_for_oauth column...")

    if column_exists():
        print("✓ Column already exists — nothing to do.")
        return True

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "ALTER TABLE user ADD COLUMN skip_2fa_for_oauth BOOLEAN DEFAULT 0;"
        )
        conn.commit()
        conn.close()

        print("✓ Column added successfully.")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("ShowWise Database Migration (sqschemify)".center(60))
    print("="*60 + "\n")

    backup_path = backup_database()
    if backup_path is None:
        return

    success = run_migration()

    if success:
        print("\n✅ Migration completed successfully!")
        print("New feature enabled:")
        print("  • skip_2fa_for_oauth (BOOLEAN, default 0)")
    else:
        print("\n⚠️ Migration failed.")
        print(f"You can restore from backup: {backup_path}")


if __name__ == "__main__":
    main()
