"""Run Alembic migrations programmatically (used at startup and by install.bat)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from nexus.db.base import Database

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def upgrade_to_head(db: Database) -> None:
    def _run(connection) -> None:
        cfg = alembic_config()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    async with db.engine.begin() as conn:
        await conn.run_sync(_run)


async def current_revision(db: Database) -> str | None:
    from sqlalchemy import text

    async with db.engine.connect() as conn:
        try:
            return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        except Exception:
            return None
