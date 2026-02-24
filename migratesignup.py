"""
migrate.py — Run this ONCE to add new columns/tables to your existing database.

Usage:
    python migrate.py

Safe to run multiple times — it checks before altering.
"""

import sqlite3
import os

DB_PATH = 'instance/production_crew.db'

def run_migration():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Run the app first to create it.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    migrations = []

    # ── User.force_2fa_setup column ──────────────────────────────────
    cursor.execute("PRAGMA table_info(user)")
    user_cols = [row[1] for row in cursor.fetchall()]

    if 'force_2fa_setup' not in user_cols:
        cursor.execute("ALTER TABLE user ADD COLUMN force_2fa_setup BOOLEAN DEFAULT 0")
        migrations.append("✓ Added user.force_2fa_setup column")
    else:
        migrations.append("  user.force_2fa_setup already exists — skipped")

    # ── InviteCode table ──────────────────────────────────────────────
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invite_code'")
    if not cursor.fetchone():
        cursor.execute("""
            CREATE TABLE invite_code (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code VARCHAR(32) UNIQUE NOT NULL,
                role VARCHAR(20) DEFAULT 'crew',
                created_by VARCHAR(80) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                max_uses INTEGER DEFAULT 1,
                use_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                note VARCHAR(200)
            )
        """)
        migrations.append("✓ Created invite_code table")
    else:
        migrations.append("  invite_code table already exists — skipped")

    # ── invite_code_uses association table ────────────────────────────
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invite_code_uses'")
    if not cursor.fetchone():
        cursor.execute("""
            CREATE TABLE invite_code_uses (
                invite_code_id INTEGER NOT NULL REFERENCES invite_code(id),
                user_id INTEGER NOT NULL REFERENCES user(id),
                PRIMARY KEY (invite_code_id, user_id)
            )
        """)
        migrations.append("✓ Created invite_code_uses table")
    else:
        migrations.append("  invite_code_uses table already exists — skipped")

    conn.commit()
    conn.close()

    print("\n=== Migration Results ===")
    for m in migrations:
        print(m)
    print("\nDone! You can now restart your Flask app.")

if __name__ == '__main__':
    run_migration()