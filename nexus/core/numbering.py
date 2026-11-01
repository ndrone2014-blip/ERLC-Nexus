"""Human-readable record numbers, e.g. NX-2026-000001."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import utcnow
from nexus.db.models import Counter

PREFIXES = {
    "incident": None,  # configurable (cad.incident_prefix, default NX)
    "person": "P",
    "vehicle": "V",
    "bolo": "BOLO",
    "warrant": "W",
    "case": "CASE",
    "traffic": "TS",
    "report": "RPT",
}


async def next_number(session: AsyncSession, kind: str, prefix: str | None = None) -> str:
    prefix = prefix or PREFIXES.get(kind) or kind.upper()
    year = utcnow().year
    key = f"{kind}:{year}"
    row = (await session.execute(select(Counter).where(Counter.key == key).with_for_update())).scalar_one_or_none()
    if row is None:
        row = Counter(key=key, value=0)
        session.add(row)
    row.value += 1
    await session.flush()
    return f"{prefix}-{year}-{row.value:06d}"
