# Backups and restoration

## What to back up

Everything ERLC Nexus stores lives in two places:

* `config.env` — your settings and secrets
* `data/` — the database (`nexus.db`), logs, downloaded map images and backups

## Built-in backups (SQLite, the default)

**From the website:** System → Database → **Create backup**.

**From the command line:**

```bat
.venv\Scripts\python.exe scripts\backup.py create my-label
.venv\Scripts\python.exe scripts\backup.py list
```

Backups use SQLite's online backup API, so they are consistent even while the bot and
website are running. Each backup is checked with `PRAGMA integrity_check` and must contain
the core tables before it is accepted. Files are written to `data/backups/` as
`nexus-YYYYMMDD-HHMMSS-label.db` and can be downloaded from the Database page.

Tip: copy `data/backups` (or the whole `data` folder) to another drive or cloud folder
regularly — a backup on the same disk won't survive a disk failure.

## Restoring

1. System → Database → **Restore** next to a backup (or `scripts\backup.py restore <file>`).
   The backup is verified and *staged* as `data/restore_pending.db`.
2. Run **stop.bat**, then **start.bat**.
3. Before any component opens the database, the launcher:
   * verifies the staged file again,
   * saves your current database as `nexus-…-before_restore.db`,
   * replaces the database and removes stale WAL files.

Staging avoids replacing a database file that is in use. If anything goes wrong, the
`before_restore` copy can be restored the same way.

Restoring a backup from an older version is supported: migrations run automatically on
start and upgrade the schema.

## Manual restore (if the website won't start)

1. Run `stop.bat` and make sure no ERLC Nexus window is open.
2. Copy `data/nexus.db` somewhere safe.
3. Copy the backup file over `data/nexus.db` and delete `data/nexus.db-wal` and
   `data/nexus.db-shm` if present.
4. Run `start.bat`.

## PostgreSQL

If you set `DATABASE_URL` to PostgreSQL, use the standard tools:

```bash
pg_dump  -Fc -d nexus -f nexus-$(date +%F).dump
pg_restore --clean -d nexus nexus-2026-11-01.dump
```

## Deletion policy

Normal interface actions never permanently erase important records. Persons, vehicles,
incidents, departments, ranks, units and locations are archived (hidden but kept), reports
keep every revision, and the audit log is append-only.
