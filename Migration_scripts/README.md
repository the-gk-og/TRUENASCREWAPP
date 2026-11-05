# Migration scripts

**You don't need to run anything here when you deploy.** Schema upgrades are automatic: see
[`README/DATABASE_MIGRATIONS.md`](../README/DATABASE_MIGRATIONS.md) and `schema_migrations.py`.

- `migrate_master.py`: a wrapper around `python -m schema_migrations` (kept so old habits still work).
- `old/`: the hand-run scripts from before automatic upgrades. They're kept for reference only. Most
  import a module-level `app` that no longer exists, so they won't run. Everything they did is
  covered by the automatic upgrade.

One-off data jobs (not schema changes) can still live here as scripts, e.g. the optional
`--backfill` of `migrate_equipment_units.py`.
