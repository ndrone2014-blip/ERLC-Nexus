"""Database backup and restore (SQLite).

* ``create_backup`` uses SQLite's online backup API, so it is safe while the
  bot and website are running.
* Restores are *staged*: the chosen backup is verified and copied to
  ``data/restore_pending.db``. The launcher (``start.bat`` → ``run.py``) applies
  it before any service opens the database, after saving a safety copy of the
  current database. This avoids replacing a database file that is in use.
For PostgreSQL installs use ``pg_dump`` / ``pg_restore`` (see docs/BACKUP.md).
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from nexus.config import Settings
from nexus.core.context import ValidationFailed

NAME_RE = re.compile(r"^nexus-\d{8}-\d{6}(-[a-z0-9_]+)?\.db$")
REQUIRED_TABLES = {"users", "incidents", "units", "audit_logs", "settings"}


def _db_file(settings: Settings) -> Path:
    url = settings.db_url
    if not url.startswith("sqlite"):
        raise ValidationFailed("Built-in backups support SQLite. Use pg_dump for PostgreSQL (see docs/BACKUP.md).")
    return Path(url.split("///", 1)[1])


def backup_dir(settings: Settings) -> Path:
    p = settings.data_path / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _backup_sync(src: Path, dst: Path) -> None:
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)


def verify_backup(path: Path) -> dict:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise ValidationFailed(f"Not a valid ERLC Nexus backup: {exc}")
    missing = REQUIRED_TABLES - tables
    if ok != "ok" or missing:
        raise ValidationFailed("Backup failed verification" + (f" (missing tables: {', '.join(sorted(missing))})" if missing else ""))
    return {"integrity": ok, "tables": len(tables)}


async def create_backup(settings: Settings, label: str = "") -> dict:
    src = _db_file(settings)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^a-z0-9_]", "", label.lower())[:24]
    dst = backup_dir(settings) / f"nexus-{stamp}{'-' + label if label else ''}.db"
    await asyncio.to_thread(_backup_sync, src, dst)
    info = await asyncio.to_thread(verify_backup, dst)
    return {"name": dst.name, "size": dst.stat().st_size, **info}


def list_backups(settings: Settings) -> list[dict]:
    out = []
    for p in sorted(backup_dir(settings).glob("nexus-*.db"), reverse=True):
        out.append({"name": p.name, "size": p.stat().st_size,
                    "created_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)})
    return out


def backup_path(settings: Settings, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ValidationFailed("Invalid backup name.")
    p = backup_dir(settings) / name
    if not p.exists():
        raise ValidationFailed("Backup not found.")
    return p


def pending_restore_path(settings: Settings) -> Path:
    return settings.data_path / "restore_pending.db"


async def stage_restore(settings: Settings, name: str) -> dict:
    src = backup_path(settings, name)
    info = await asyncio.to_thread(verify_backup, src)
    await asyncio.to_thread(shutil.copy2, src, pending_restore_path(settings))
    return {"staged": name, **info, "message": "Restore staged. Restart ERLC Nexus (stop.bat then start.bat) to apply it."}


def apply_pending_restore(settings: Settings) -> str | None:
    """Called by the launcher before services start. Returns a message or None."""
    pending = pending_restore_path(settings)
    if not pending.exists():
        return None
    verify_backup(pending)
    db = _db_file(settings)
    if db.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safety = backup_dir(settings) / f"nexus-{stamp}-before_restore.db"
        _backup_sync(db, safety)
    for suffix in ("-wal", "-shm"):
        side = Path(str(db) + suffix)
        if side.exists():
            side.unlink()
    shutil.move(str(pending), str(db))
    return "Database restored from staged backup (previous database saved to backups)."
