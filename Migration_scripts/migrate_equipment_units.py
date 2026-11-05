#!/usr/bin/env python3
"""
Migration_scripts/migrate_equipment_units.py
============================================
Adds per-unit equipment tracking:

  * `equipment_unit`  — one row per physical, individually tagged unit
  * `pick_list_unit`  — which units are allocated to which pick list line

Units are OPT-IN per item: running this creates the (empty) tables only.
Many items are consumables or bulk stock (gaffer tape, cable bundles) where
one QR per piece is just noise, so nothing is created unless you ask for it —
either from the item's detail page ("Generate units") or with --backfill here.

Safe to run multiple times — skips work that is already done.

Usage:
    python Migration_scripts/migrate_equipment_units.py
    python Migration_scripts/migrate_equipment_units.py --backfill
        # also create `quantity_owned` units (tagged <barcode>-01, -02, …) for
        # every item that has no units yet
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
from models import Equipment, EquipmentUnit, PickListUnit  # noqa: F401  (registers tables)

app = create_app()

TABLES = ("equipment_unit", "pick_list_unit")


def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


# ---------------------------------------------------------------------------
# Step 1 — create the tables (create_all only ever adds missing tables)
# ---------------------------------------------------------------------------

def create_tables(engine):
    print("\n── Step 1: unit tables ──────────────────────────────────────────")
    missing = [t for t in TABLES if not _table_exists(engine, t)]
    if not missing:
        print("  · equipment_unit and pick_list_unit already exist — skipped")
        return
    db.metadata.create_all(engine, tables=[db.metadata.tables[t] for t in missing])
    for t in missing:
        print(f"  ✓ Created {t} table")


# ---------------------------------------------------------------------------
# Step 2 — optional backfill
# ---------------------------------------------------------------------------

def backfill_units():
    print("\n── Step 2: Backfill units from quantity_owned ───────────────────")
    from routes.equipment import _create_units
    made = 0
    for eq in Equipment.query.order_by(Equipment.id).all():
        if eq.units:
            print(f"  · {eq.name!r} already has {len(eq.units)} unit(s) — skipped")
            continue
        n = max(1, eq.quantity_owned or 1)
        _create_units(eq, n)
        made += n
        print(f"  ✓ {eq.name!r}: created {n} unit(s)")
    db.session.commit()
    print(f"  ✓ Backfill complete — {made} unit(s) created")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(backfill=False):
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║         Equipment units — Database Migration                ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    with app.app_context():
        create_tables(db.engine)
        if backfill:
            backfill_units()
        else:
            print("\n── Step 2: Backfill skipped (units are opt-in; pass --backfill) ─")

    print()
    print("════════════════════════════════════════════════════════════════")
    print("  ✓ Migration complete — per-unit equipment tracking is ready.")
    print("════════════════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    run(backfill="--backfill" in sys.argv[1:])
    sys.exit(0)
