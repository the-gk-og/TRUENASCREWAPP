#!/usr/bin/env python3
"""
Kept for muscle memory: schema upgrades are automatic now and live in schema_migrations.py.

The app upgrades its database on every start (and the Docker image does it once before gunicorn),
so you don't need to run this. It is the same as:

    python -m schema_migrations            # upgrade now
    python -m schema_migrations --status   # show what an upgrade would change
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schema_migrations import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
