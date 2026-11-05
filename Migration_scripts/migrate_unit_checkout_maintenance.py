#!/usr/bin/env python3
"""
Migration_scripts/migrate_unit_checkout_maintenance.py
======================================================
Adds unit check-out / return records and per-unit maintenance history:

  * `unit_checkout`    — a unit leaving storage for an event, and its return
  * `unit_maintenance` — repairs, inspections and PAT tests, with "next due"

Needs `equipment_unit` (run migrate_equipment_units.py first).
Only new tables, no changes to existing ones. Safe to run multiple times.

Usage:
    python Migration_scripts/migrate_unit_checkout_maintenance.py
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
            _val = _val.strip().strip('"').strip("'")
            os.environ.setdefault(_key.strip(), _val)
    print(f"  · Loaded environment from {env_path}")
else:
    print(f"  · No .env file found at {env_path} — relying on existing environment")

# ── Now safe to import the app ────────────────────────────────────────────────
from sqlalchemy import inspect

from app import create_app
from extensions import db
from models import UnitCheckout, UnitMaintenance  # noqa: F401  (registers tables)

TABLES = ("unit_checkout", "unit_maintenance")


def create_tables(engine):
    """Create whichever of TABLES are missing (create_all never alters tables)."""
    existing = set(inspect(engine).get_table_names())
    if "equipment_unit" not in existing:
        raise SystemExit("  ✗ equipment_unit table is missing — run migrate_equipment_units.py first")
    missing = [t for t in TABLES if t not in existing]
    if not missing:
        print("  · unit_checkout and unit_maintenance already exist — skipped")
        return []
    db.metadata.create_all(engine, tables=[db.metadata.tables[t] for t in missing])
    for t in missing:
        print(f"  ✓ Created {t} table")
    return missing


def run():
    print()
    print("── Unit check-out + maintenance — Database Migration ───────────")
    app = create_app()
    with app.app_context():
        create_tables(db.engine)
    print("  ✓ Migration complete")
    print()


if __name__ == "__main__":
    run()
    sys.exit(0)
