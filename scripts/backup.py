"""Command-line database backup and restore.

    python scripts/backup.py create [label]      create a verified backup in data/backups
    python scripts/backup.py list                list backups
    python scripts/backup.py restore <file>      stage a restore (applied on next start)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexus.config import get_settings  # noqa: E402
from nexus.services import backup  # noqa: E402


def main(argv: list[str]) -> int:
    s = get_settings()
    cmd = argv[1] if len(argv) > 1 else "create"
    if cmd == "create":
        info = asyncio.run(backup.create_backup(s, argv[2] if len(argv) > 2 else "cli"))
        print(f"Created {info['name']} ({info['size'] // 1024} KB, integrity {info['integrity']})")
    elif cmd == "list":
        for b in backup.list_backups(s):
            print(f"{b['name']}  {b['size'] // 1024} KB  {b['created_at']:%Y-%m-%d %H:%M}")
    elif cmd == "restore" and len(argv) > 2:
        info = asyncio.run(backup.stage_restore(s, Path(argv[2]).name))
        print(info["message"])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
