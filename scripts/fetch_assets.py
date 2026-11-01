"""Download the official ERLC map images (https://apidocs.erlc.gg/official-map-images.md)
into data/maps so the live map works offline. Safe to re-run; failures are non-fatal."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexus.services.maps import MAP_STYLES  # noqa: E402


def fetch_maps(dest: Path, styles: list[str] | None = None, timeout: float = 60) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for style in styles or ["fall_postals", "snow_postals"]:
        target = dest / f"{style}.png"
        if target.exists() and target.stat().st_size > 100_000:
            count += 1
            continue
        tmp = target.with_suffix(".part")
        try:
            req = urllib.request.Request(MAP_STYLES[style], headers={"User-Agent": "ERLC-Nexus/1.0 (self-hosted)"})
            with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as fh:
                while chunk := r.read(1 << 16):
                    fh.write(chunk)
            if tmp.stat().st_size < 100_000 or tmp.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("unexpected file")
            tmp.replace(target)
            count += 1
            print(f"  downloaded {style}.png")
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            print(f"  could not download {style}.png ({exc})")
    return count


if __name__ == "__main__":
    from nexus.config import get_settings

    n = fetch_maps(get_settings().data_path / "maps", list(MAP_STYLES))
    print(f"{n} map image(s) available.")
