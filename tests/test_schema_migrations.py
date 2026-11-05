"""Automatic schema upgrades (schema_migrations.py).  Run: pytest tests/test_schema_migrations.py"""
import os, sys, sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schema_migrations as sm               # noqa: E402
from extensions import db                    # noqa: E402
import models                                # noqa: E402,F401  (registers every table)

META = db.metadata


def engine_for(path):
    return create_engine(f'sqlite:///{path}')


def tables(engine):
    return set(inspect(engine).get_table_names())


def cols(engine, table):
    return {c['name'] for c in inspect(engine).get_columns(table)}


def version(engine):
    with engine.connect() as c:
        return sm.current_version(c)


def assert_current(engine):
    assert {t.name for t in META.sorted_tables} <= tables(engine)
    for t in META.sorted_tables:
        assert {c.name for c in t.columns} <= cols(engine, t.name), t.name
    assert version(engine) == sm.LATEST_VERSION
    idx = {i['name']: i for i in inspect(engine).get_indexes('user')}
    assert idx['ix_user_calendar_token']['unique']


@pytest.fixture()
def legacy_db(tmp_path):
    """A database as an install from before versioning looks: no schema_version table, the four
    hand-added columns missing, a newer table missing, and real rows in it."""
    path = tmp_path / 'crew.db'
    eng = engine_for(path)
    META.create_all(eng)
    with eng.begin() as c:
        c.execute(text("INSERT INTO user (id, username, is_admin) VALUES (1, 'alice', 1)"))
        c.execute(text("INSERT INTO event (id, title, event_date) VALUES (7, 'Spring Musical', '2026-03-01 19:00:00')"))
        c.execute(text('DROP INDEX ix_user_calendar_token'))
        c.execute(text('ALTER TABLE user DROP COLUMN calendar_token'))
        c.execute(text('ALTER TABLE user DROP COLUMN display_name'))
        c.execute(text('ALTER TABLE event DROP COLUMN all_day'))
        c.execute(text('ALTER TABLE shift_assignment DROP COLUMN decline_reason'))
        c.execute(text('DROP TABLE event_time'))
    return path, eng


def test_fresh_database_reaches_current_schema(tmp_path):
    eng = engine_for(tmp_path / 'new.db')
    res = sm.upgrade(eng, META)
    assert_current(eng)
    assert res['backup'] is None                       # nothing worth backing up
    assert not (tmp_path / 'backups').exists()
    assert res['applied'] == [m.version for m in sm.MIGRATIONS]


def test_legacy_database_upgrades_without_data_loss(legacy_db):
    path, eng = legacy_db
    res = sm.upgrade(eng, META)
    assert_current(eng)
    assert res['from'] == 0 and res['created_tables'] == ['event_time']
    with eng.connect() as c:
        assert c.execute(text('SELECT username FROM user WHERE id=1')).scalar() == 'alice'
        title, all_day = c.execute(text('SELECT title, all_day FROM event WHERE id=7')).one()
        assert title == 'Spring Musical' and all_day == 0       # existing rows get the default
    # the backup is a readable copy of the database as it was before the upgrade
    backup = res['backup']
    assert backup and os.path.dirname(backup) == str(path.parent / 'backups')
    con = sqlite3.connect(backup)
    try:
        assert con.execute('SELECT username FROM user').fetchall() == [('alice',)]
        assert 'all_day' not in {r[1] for r in con.execute('PRAGMA table_info(event)')}
    finally:
        con.close()


def test_upgrade_is_idempotent(legacy_db):
    _, eng = legacy_db
    sm.upgrade(eng, META)
    again = sm.upgrade(eng, META)
    assert again['applied'] == [] and again['backup'] is None and again['added_columns'] == []
    with eng.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM schema_version')).scalar() == len(sm.MIGRATIONS)


def test_database_with_only_some_old_fixes_applied(legacy_db):
    """Some installs ran some hand scripts / the old ensure_schema already: steps must skip what exists."""
    _, eng = legacy_db
    with eng.begin() as c:
        c.execute(text("ALTER TABLE event ADD COLUMN all_day BOOLEAN DEFAULT 0"))
        c.execute(text("ALTER TABLE user ADD COLUMN calendar_token VARCHAR(64)"))
        c.execute(text("CREATE UNIQUE INDEX ix_user_calendar_token ON user (calendar_token)"))
    sm.upgrade(eng, META)
    assert_current(eng)


@pytest.mark.parametrize('table', [t.name for t in META.sorted_tables])
def test_any_missing_table_is_created(tmp_path, table):
    """Covers new feature tables (e.g. per-unit equipment tracking) whether or not their hand-run
    migration script was ever run: with or without the table, the upgrade ends in the same place."""
    eng = engine_for(tmp_path / 'x.db')
    META.create_all(eng, tables=[t for t in META.sorted_tables if t.name != table])
    sm.upgrade(eng, META)
    assert_current(eng)


def test_existing_feature_table_and_rows_are_left_alone(tmp_path):
    eng = engine_for(tmp_path / 'x.db')
    META.create_all(eng)                                  # e.g. someone ran the hand script already
    with eng.begin() as c:
        c.execute(text("INSERT INTO equipment (id, barcode, name) VALUES (3, 'MIC-1', 'SM58')"))
    sm.upgrade(eng, META)
    with eng.connect() as c:
        assert c.execute(text('SELECT name FROM equipment WHERE id=3')).scalar() == 'SM58'
    assert version(eng) == sm.LATEST_VERSION


def test_missing_not_null_column_gets_model_default(tmp_path):
    eng = engine_for(tmp_path / 'x.db')
    META.create_all(eng)
    with eng.begin() as c:
        c.execute(text("INSERT INTO event (id, title, event_date) VALUES (1, 'E', '2026-01-01')"))
        c.execute(text("INSERT INTO event_attachment (id, event_id, kind, stored_name, target) "
                       "VALUES (1, 1, 'pdf', 'a.pdf', 'run')"))
        c.execute(text('ALTER TABLE event_attachment DROP COLUMN target'))
    res = sm.upgrade(eng, META)
    assert 'event_attachment.target' in res['added_columns']
    with eng.connect() as c:
        assert c.execute(text('SELECT target FROM event_attachment WHERE id=1')).scalar() == 'schedule'


def test_new_step_runs_once_and_failed_step_is_retried(legacy_db, monkeypatch):
    _, eng = legacy_db
    sm.upgrade(eng, META)
    calls = []

    def step(conn):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('boom')
        sm.add_column(conn, 'user', 'nickname', 'VARCHAR(40)')

    nxt = sm.LATEST_VERSION + 1
    monkeypatch.setattr(sm, 'MIGRATIONS', sm.MIGRATIONS + [sm.Migration(nxt, 'nickname', step)])
    monkeypatch.setattr(sm, 'LATEST_VERSION', nxt)
    with pytest.raises(RuntimeError):
        sm.upgrade(eng, META)
    assert version(eng) == nxt - 1                         # not recorded, so it runs again
    res = sm.upgrade(eng, META)
    assert res['applied'] == [nxt] and 'nickname' in cols(eng, 'user')
    sm.upgrade(eng, META)
    assert len(calls) == 2


def test_backups_are_pruned(legacy_db, monkeypatch):
    path, eng = legacy_db
    monkeypatch.setattr(sm, 'BACKUPS_KEPT', 2)
    for i in range(4):
        sm.backup_sqlite(eng, i)
    assert len(os.listdir(path.parent / 'backups')) == 2


def test_app_startup_upgrades_legacy_database(legacy_db, monkeypatch):
    """The real start path: create_app() upgrades the configured database."""
    import config
    from app import create_app
    path, eng = legacy_db
    monkeypatch.setattr(config.TestingConfig, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{path}')
    create_app('testing')
    assert_current(eng)


def test_cli_upgrade_and_status(legacy_db, monkeypatch, capsys):
    import config
    path, eng = legacy_db
    # config reads DATABASE_URL at import time, so point the active config class at the test file
    monkeypatch.setattr(config.get_config(), 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{path}')
    assert sm.main(['--status']) == 0
    assert 'missing table event_time' in capsys.readouterr().out
    assert sm.main([]) == 0
    assert_current(eng)
    assert sm.main(['--status']) == 0
    out = capsys.readouterr().out
    assert f'Schema version {sm.LATEST_VERSION}' in out and 'missing' not in out
