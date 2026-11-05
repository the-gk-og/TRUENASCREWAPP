"""
schema_migrations.py
====================
Automatic, versioned schema upgrades. Runs on every start; nobody has to remember a script.

    python -m schema_migrations           # upgrade now (the Docker image does this before gunicorn)
    python -m schema_migrations --status  # show the version and what an upgrade would change

What one upgrade does, in order (every part is idempotent, so a re-run or a crash halfway is safe):

  1. Takes a file lock, so two gunicorn workers starting together don't migrate at the same time.
  2. Backs up a SQLite database file first, if anything is about to change (kept next to the DB in
     ``backups/``; the newest few are kept).
  3. ``db.create_all()``: creates every table models.py has and the database doesn't.
  4. Runs each numbered step in ``MIGRATIONS`` that is newer than the version stored in the
     ``schema_version`` table, then records it there.
  5. Adds any column models.py has and the table doesn't (with the model's default for existing rows,
     plus its unique/plain index). This step is the safety net for purely additive changes.

Changing the schema
-------------------
* New table or new nullable / simple-default column: just edit models.py. Steps 3 and 5 pick it up.
* Anything else (backfilling data, a computed default, renaming or retyping a column, dropping
  something, a new index on an existing column): append a ``Migration`` to ``MIGRATIONS`` with the
  next number. Write it so it is safe on a database that already has the change, because steps 3 and
  5 may run before it on some installs (check with ``inspect`` first). Never renumber or edit a step
  that has shipped.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, literal, text
from sqlalchemy.engine import Connection, Engine

VERSION_TABLE = 'schema_version'
BACKUPS_KEPT = 5


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    run: Callable[[Connection], None]


# ---------------------------------------------------------------------------
# Helpers for writing steps
# ---------------------------------------------------------------------------

def _q(conn: Connection, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def has_table(conn: Connection, table: str) -> bool:
    return inspect(conn).has_table(table)


def column_names(conn: Connection, table: str) -> set[str]:
    return {c['name'] for c in inspect(conn).get_columns(table)}


def index_names(conn: Connection, table: str) -> set[str]:
    return {i['name'] for i in inspect(conn).get_indexes(table)}


def add_column(conn: Connection, table: str, column: str, ddl: str) -> bool:
    """ALTER TABLE ADD COLUMN unless it is already there. Returns True when it added it."""
    if not has_table(conn, table) or column in column_names(conn, table):
        return False
    conn.execute(text(f'ALTER TABLE {_q(conn, table)} ADD COLUMN {_q(conn, column)} {ddl}'))
    print(f'  ✓ Added {table}.{column}')
    return True


def create_index(conn: Connection, name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if not has_table(conn, table) or name in index_names(conn, table):
        return
    cols = ', '.join(_q(conn, c) for c in columns)
    conn.execute(text(f'CREATE {"UNIQUE " if unique else ""}INDEX {_q(conn, name)} ON {_q(conn, table)} ({cols})'))
    print(f'  ✓ Created index {name}')


# ---------------------------------------------------------------------------
# Numbered steps. Append only; never change one that has shipped.
# ---------------------------------------------------------------------------

def _m1_pre_versioning_columns(conn: Connection) -> None:
    """Columns the old app.ensure_schema() added by hand before this runner existed."""
    add_column(conn, 'event', 'all_day', f'BOOLEAN DEFAULT {_literal(conn, False)}')
    add_column(conn, 'shift_assignment', 'decline_reason', 'VARCHAR(500)')
    add_column(conn, 'user', 'calendar_token', 'VARCHAR(64)')
    add_column(conn, 'user', 'display_name', 'VARCHAR(100)')
    # ADD COLUMN can't carry UNIQUE, so the calendar-token index is made separately.
    create_index(conn, 'ix_user_calendar_token', 'user', ['calendar_token'], unique=True)


MIGRATIONS: list[Migration] = [
    Migration(1, 'pre-versioning columns (all_day, decline_reason, calendar_token, display_name)',
              _m1_pre_versioning_columns),
]

LATEST_VERSION = max(m.version for m in MIGRATIONS)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _ensure_version_table(conn: Connection) -> None:
    if not has_table(conn, VERSION_TABLE):
        conn.execute(text(
            f'CREATE TABLE {_q(conn, VERSION_TABLE)} ('
            f'version INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, applied_at TIMESTAMP NOT NULL)'))


def current_version(conn: Connection) -> int:
    if not has_table(conn, VERSION_TABLE):
        return 0
    return conn.execute(text(f'SELECT MAX(version) FROM {_q(conn, VERSION_TABLE)}')).scalar() or 0


def _missing_columns(conn: Connection, metadata):
    """(table, Column) pairs that models declare and the database lacks, for tables that exist."""
    insp = inspect(conn)
    existing = set(insp.get_table_names())
    for table in metadata.sorted_tables:
        if table.name not in existing:
            continue
        have = {c['name'] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                yield table, col


def _column_ddl(conn: Connection, col) -> str:
    """Type and default for ADD COLUMN. Always nullable: SQLite can't add a NOT NULL column without a
    default, and the ORM fills the value on every insert anyway."""
    ddl = col.type.compile(dialect=conn.dialect)
    default = None
    arg = getattr(col.server_default, 'arg', None)
    if isinstance(arg, str):
        default = _literal(conn, arg)
    elif arg is not None and hasattr(arg, 'compile'):            # server_default=text('...')
        default = str(arg.compile(dialect=conn.dialect))
    elif col.default is not None and getattr(col.default, 'is_scalar', False):
        default = _literal(conn, col.default.arg, col.type)
    return f'{ddl} DEFAULT {default}' if default is not None else ddl


def _literal(conn: Connection, value, type_=None) -> str:
    return str(literal(value, type_).compile(dialect=conn.dialect, compile_kwargs={'literal_binds': True}))


def _sync_missing_columns(conn: Connection, metadata) -> list[str]:
    added = []
    for table, col in list(_missing_columns(conn, metadata)):
        add_column(conn, table.name, col.name, _column_ddl(conn, col))
        added.append(f'{table.name}.{col.name}')
        if col.unique or col.index:
            create_index(conn, f'ix_{table.name}_{col.name}', table.name, [col.name], unique=bool(col.unique))
        if not col.nullable:
            print(f'  · {table.name}.{col.name} was added as nullable (existing rows have no value)')
    return added


def plan(engine: Engine, metadata) -> dict:
    """What an upgrade would do, without changing anything."""
    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        version = current_version(conn)
        return {
            'version': version,
            'latest': LATEST_VERSION,
            'pending_steps': [m for m in MIGRATIONS if m.version > version],
            'missing_tables': [t.name for t in metadata.sorted_tables if t.name not in existing],
            'missing_columns': [f'{t.name}.{c.name}' for t, c in _missing_columns(conn, metadata)],
            'empty': not (existing - {VERSION_TABLE}),
        }


def _sqlite_path(engine: Engine) -> str | None:
    if engine.dialect.name != 'sqlite':
        return None
    path = engine.url.database
    if not path or path == ':memory:' or path.startswith('file:'):
        return None
    return path if os.path.isfile(path) and os.path.getsize(path) > 0 else None


def backup_sqlite(engine: Engine, version: int) -> str | None:
    """Consistent copy of the SQLite file (online backup API) into backups/ next to it."""
    path = _sqlite_path(engine)
    if not path:
        return None
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), 'backups')
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    stamp = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(folder, f'{stem}-pre-migrate-v{version}-{stamp}.db')
    src, dst = sqlite3.connect(path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    prefix = f'{stem}-pre-migrate-'
    old = sorted(f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith('.db'))
    for name in old[:-BACKUPS_KEPT]:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(folder, name))
    return dest


@contextlib.contextmanager
def _lock(engine: Engine):
    """Cross-process lock (one per database URL) so concurrent workers migrate one at a time."""
    try:
        import fcntl
    except ImportError:          # Windows dev box: single process anyway
        yield
        return
    key = hashlib.sha1(engine.url.render_as_string(hide_password=False).encode()).hexdigest()[:16]
    with open(os.path.join(tempfile.gettempdir(), f'showwise-schema-{key}.lock'), 'w') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def upgrade(engine: Engine, metadata, backup: bool = True) -> dict:
    """Bring the database up to the current schema. Raises if a step fails."""
    with _lock(engine):
        before = plan(engine, metadata)
        work = before['pending_steps'] or before['missing_tables'] or before['missing_columns']
        result = {'from': before['version'], 'to': before['version'], 'applied': [],
                  'created_tables': [], 'added_columns': [], 'backup': None}
        if not work:
            return result

        if backup and not before['empty']:
            result['backup'] = backup_sqlite(engine, before['version'])
            if result['backup']:
                print(f'  · Backed up database to {result["backup"]}')

        with engine.begin() as conn:
            _ensure_version_table(conn)
        if before['missing_tables']:
            metadata.create_all(engine)
            result['created_tables'] = before['missing_tables']
            if before['empty']:
                print(f'  ✓ Created {len(before["missing_tables"])} tables in a new database')
            else:
                for name in before['missing_tables']:
                    print(f'  ✓ Created table {name}')

        for step in before['pending_steps']:
            with engine.begin() as conn:
                print(f'  → Schema step {step.version}: {step.name}')
                step.run(conn)
                conn.execute(text(f'INSERT INTO {_q(conn, VERSION_TABLE)} (version, name, applied_at) '
                                  f'VALUES (:v, :n, :t)'),
                             {'v': step.version, 'n': step.name[:200], 't': _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')})
            result['applied'].append(step.version)
            result['to'] = step.version

        with engine.begin() as conn:
            result['added_columns'] = _sync_missing_columns(conn, metadata)

        print(f'✓ Database schema is at version {result["to"]}')
        return result


def upgrade_app(app) -> dict:
    """Upgrade the database bound to a Flask app (uses the app's models)."""
    from extensions import db
    import models  # noqa: F401  (registers every table on db.metadata)
    with app.app_context():
        return upgrade(db.engine, db.metadata)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _bare_app():
    """A Flask app with only the database wired up: no blueprints, backend heartbeat or bots."""
    from flask import Flask
    from config import get_config
    from extensions import db
    app = Flask(__name__)
    app.config.from_object(get_config())
    db.init_app(app)
    return app


def main(argv: list[str]) -> int:
    app = _bare_app()
    if '--status' in argv:
        from extensions import db
        import models  # noqa: F401
        with app.app_context():
            p = plan(db.engine, db.metadata)
        print(f'Schema version {p["version"]} (latest {p["latest"]})')
        for m in p['pending_steps']:
            print(f'  pending step {m.version}: {m.name}')
        for t in p['missing_tables']:
            print(f'  missing table {t}')
        for c in p['missing_columns']:
            print(f'  missing column {c}')
        return 0
    try:
        upgrade_app(app)
    except Exception as exc:
        print(f'✗ Schema upgrade failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
