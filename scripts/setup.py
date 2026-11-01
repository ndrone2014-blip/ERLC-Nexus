"""Installer steps 5-10 (called by install.bat / install.sh after dependencies are installed).

Creates directories, creates config.env if missing (never overwrites it),
initialises the database, runs migrations, downloads the official map images
(optional) and reports what still needs configuring.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, WARN, BAD = "[ OK ]", "[WARN]", "[FAIL]"


def step(n: int, text: str) -> None:
    print(f"\n[{n}/10] {text}", flush=True)


def main() -> int:
    results: list[tuple[str, str]] = []

    step(5, "Creating folders")
    for d in ("data", "data/logs", "data/backups", "data/maps"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    print(f"  {OK} data/, data/logs/, data/backups/, data/maps/")

    step(6, "Configuration file")
    cfg = ROOT / "config.env"
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8-sig")
        if re.search(r"^SECRET_KEY=(change-me)?\s*$", text, re.M):
            text = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={secrets.token_urlsafe(48)}", text, count=1, flags=re.M)
            cfg.write_text(text, encoding="utf-8")
            print(f"  {OK} Existing config.env kept; generated the missing SECRET_KEY.")
        else:
            print(f"  {OK} Existing config.env kept (not overwritten).")
    else:
        template = (ROOT / "config.env.example").read_text(encoding="utf-8")
        template = template.replace("SECRET_KEY=change-me", f"SECRET_KEY={secrets.token_urlsafe(48)}", 1)
        cfg.write_text(template, encoding="utf-8")
        print(f"  {OK} Created config.env with a new random SECRET_KEY.")
        results.append(("warn", "Open config.env and fill in your Discord and ERLC settings."))

    from nexus.config import load_settings

    settings = load_settings()

    step(7, "Database & migrations")
    try:
        from nexus.core.seed import seed_all
        from nexus.db.base import Database
        from nexus.db.migrate import current_revision, upgrade_to_head

        async def _init() -> str | None:
            db = Database(settings.db_url)
            try:
                await upgrade_to_head(db)
                async with db.session() as s:
                    await seed_all(s, settings.initial_admin_discord_id)
                return await current_revision(db)
            finally:
                await db.dispose()

        rev = asyncio.run(_init())
        print(f"  {OK} Database ready ({'SQLite: data/nexus.db' if settings.is_sqlite else 'PostgreSQL'}), schema revision {rev}.")
    except Exception as exc:
        print(f"  {BAD} Database setup failed: {exc}")
        results.append(("bad", f"Database setup failed: {exc}"))

    step(8, "Official ERLC map images (optional)")
    try:
        from scripts.fetch_assets import fetch_maps

        got = fetch_maps(settings.data_path / "maps")
        print(f"  {OK} {got} map image(s) available offline." if got else f"  {WARN} Map images will load from api.erlc.gg when needed.")
    except Exception as exc:
        print(f"  {WARN} Skipped ({exc}). The map will load images from api.erlc.gg instead.")

    step(9, "Checking required configuration")
    problems = settings.problems("all")
    for p in problems:
        print(f"  {WARN} {p}")
        results.append(("warn", p))
    if not settings.initial_admin_discord_id:
        msg = "INITIAL_ADMIN_DISCORD_ID is empty: set it to your Discord user ID so you become Owner."
        print(f"  {WARN} {msg}")
        results.append(("warn", msg))
    if not problems:
        print(f"  {OK} Everything required is configured.")

    step(10, "Result")
    bad = [m for k, m in results if k == "bad"]
    if bad:
        print(f"\n  {BAD} Installation finished with errors:")
        for m in bad:
            print(f"     - {m}")
        return 1
    print(f"\n  {OK} ERLC Nexus is installed.")
    if results:
        print("\n  Next steps:")
        for _, m in results:
            print(f"     - {m}")
    print("\n  Then run start.bat and open the website shown in the window.")
    print("  Full guide: README.md\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
