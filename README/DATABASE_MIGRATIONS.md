# Database schema upgrades

ShowWise upgrades its own database schema when it starts. A deploy doesn't need a hand-run
migration script any more.

## What happens on start

- **Docker image**: the container runs `python -m schema_migrations` once, then starts gunicorn.
  If the upgrade fails, the container exits with the error in its log instead of serving a
  half-upgraded app. Look at the log, fix the cause, and start it again. The upgrade is safe to
  re-run.
- **`python app.py` / `start.sh` / `create_app()`**: the same upgrade runs inside `create_app()`.
  It does nothing when the database is already current. If it fails there, it logs
  `⚠️ Schema upgrade failed` and the app still starts, so a dev server comes up.

One upgrade:

1. Takes a file lock, so the two gunicorn workers never migrate at the same time.
2. **Backs up the SQLite file** first, but only if something is about to change and the database
   isn't brand new. The copy goes to `backups/<name>-pre-migrate-v<old version>-<time>.db` next to
   the database (inside the `instance/` volume), and the newest 5 are kept.
3. Creates every table in `models.py` that the database doesn't have.
4. Runs the numbered steps in `schema_migrations.MIGRATIONS` that are newer than the version stored
   in the `schema_version` table.
5. Adds any column in `models.py` that the table is missing. Existing rows get the model's default
   when it is a constant.

Every step checks what the database has before changing it. So an install that ran some of the
old hand scripts, all of them or none ends up in the same place. This includes installs that have
or haven't run `migrate_equipment_units.py`. Nothing is dropped or rewritten.

## Commands

```bash
python -m schema_migrations --status   # current version and what an upgrade would change
python -m schema_migrations            # upgrade now (exit code 1 on failure)
```

Both use `DATABASE_URL` (or the default SQLite file) like the app does.

## Restoring after a bad upgrade

Stop the app, then copy the `*-pre-migrate-*.db` file over the database file and start an older
image. Admin → Backups can restore a backup too.

## Changing the schema (developers)

- **New table, or new nullable column, or a column with a constant default**: edit `models.py`.
  Nothing else is needed.
- **Anything else**: append a `Migration(<next number>, '<what it does>', fn)` to `MIGRATIONS` in
  `schema_migrations.py`. That covers backfilling or computing values, renames, type changes,
  drops, and an index or unique constraint on an existing column. Use the helpers `add_column`,
  `create_index`, `has_table` and `column_names` there.
  - Make the step safe to run on a database that already has the change. Steps 3 and 5 above run
    first on some installs.
  - Never renumber or edit a step that has shipped.
  - Add a test to `tests/test_schema_migrations.py`.

SQLite is the supported and tested database. The runner only uses portable SQL (the dialect
renders types and defaults), but `requirements.txt` ships no Postgres/MySQL driver and nothing
else is tested.
