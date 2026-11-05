#!/usr/bin/env python3
"""
Migration_scripts/migrate_email_otp.py
=======================================
Adds the `email_otp` table required for email-based OTP 2FA.

Safe to run multiple times — skips work that is already done.

Usage:
    python Migration_scripts/migrate_email_otp.py
"""

import os
import sys
from pathlib import Path

# ── Locate repo root and load .env before importing the app ──────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

env_path = ROOT / ".env"
if env_path.exists():
    with open(env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _val = _line.partition("=")
            # Strip optional surrounding quotes from value
            _val = _val.strip().strip('"').strip("'")
            os.environ.setdefault(_key.strip(), _val)
    print(f"  · Loaded environment from {env_path}")
else:
    print(f"  · No .env file found at {env_path} — relying on existing environment")

# ── Now safe to import the app ────────────────────────────────────────────────
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app import create_app
from extensions import db

app = create_app()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _column_exists(engine, table: str, column: str) -> bool:
    cols = {c["name"] for c in inspect(engine).get_columns(table)}
    return column in cols


def _add_column(conn, table: str, col_def: str, label: str):
    """ALTER TABLE … ADD COLUMN …, silently ignoring 'already exists'."""
    try:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col_def}'))
        print(f"  ✓ Added column {label}")
    except OperationalError as exc:
        if "already exists" in str(exc).lower() or "duplicate" in str(exc).lower():
            print(f"  · Column {label} already present — skipped")
        else:
            raise


# ---------------------------------------------------------------------------
# Step 1 — create the email_otp table (if absent)
# ---------------------------------------------------------------------------

CREATE_EMAIL_OTP = """
CREATE TABLE IF NOT EXISTS email_otp (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL UNIQUE REFERENCES "user"(id),
    enabled    BOOLEAN NOT NULL DEFAULT 0,
    otp_code   VARCHAR(8),
    otp_expiry DATETIME,
    otp_used   BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_email_otp_table(engine):
    print("\n── Step 1: email_otp table ──────────────────────────────────────")
    if _table_exists(engine, "email_otp"):
        print("  · email_otp table already exists — skipped")
        return

    with engine.begin() as conn:
        conn.execute(text(CREATE_EMAIL_OTP))
    print("  ✓ Created email_otp table")


# ---------------------------------------------------------------------------
# Step 2 — verify every expected column is present
# ---------------------------------------------------------------------------

EMAIL_OTP_COLUMNS = [
    ("user_id",    'INTEGER NOT NULL REFERENCES "user"(id)'),
    ("enabled",    "BOOLEAN NOT NULL DEFAULT 0"),
    ("otp_code",   "VARCHAR(8)"),
    ("otp_expiry", "DATETIME"),
    ("otp_used",   "BOOLEAN NOT NULL DEFAULT 1"),
    ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
    ("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
]


def verify_email_otp_columns(engine):
    print("\n── Step 2: Verify email_otp columns ─────────────────────────────")
    with engine.begin() as conn:
        for col_name, col_def in EMAIL_OTP_COLUMNS:
            if not _column_exists(engine, "email_otp", col_name):
                _add_column(conn, "email_otp", f'"{col_name}" {col_def}', col_name)
            else:
                print(f"  · Column {col_name} already present — skipped")


# ---------------------------------------------------------------------------
# Step 3 — ensure User table has columns added alongside EmailOTP
# ---------------------------------------------------------------------------

USER_EXTRA_COLUMNS = [
    ("force_2fa_setup",       "BOOLEAN DEFAULT 0"),
    ("skip_2fa_for_oauth",    "BOOLEAN DEFAULT 0"),
    ("profile_picture",       "VARCHAR(300)"),
    ("password_reset_token",  "VARCHAR(100)"),
    ("password_reset_expiry", "DATETIME"),
]


def verify_user_columns(engine):
    print("\n── Step 3: Verify related User columns ──────────────────────────")
    with engine.begin() as conn:
        for col_name, col_def in USER_EXTRA_COLUMNS:
            if not _column_exists(engine, "user", col_name):
                _add_column(conn, "user", f'"{col_name}" {col_def}', f"user.{col_name}")
            else:
                print(f"  · Column user.{col_name} already present — skipped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║           Email OTP 2FA — Database Migration                ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    with app.app_context():
        engine = db.engine

        create_email_otp_table(engine)
        verify_email_otp_columns(engine)
        verify_user_columns(engine)

        print("\n── Step 4: SQLAlchemy create_all safety pass ────────────────────")
        try:
            db.create_all()
            print("  ✓ create_all completed")
        except Exception as exc:
            print(f"  ⚠ create_all warning: {exc}")

    print()
    print("════════════════════════════════════════════════════════════════")
    print("  ✓ Migration complete — email_otp 2FA is ready to use.")
    print("════════════════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    run()
    sys.exit(0)