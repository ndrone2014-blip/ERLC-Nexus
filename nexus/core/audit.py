"""Append-only, hash-chained audit logging.

Each row stores ``prev_hash`` and ``hash = sha256(prev_hash + canonical row)``.
``verify_chain`` detects edited or deleted rows. There is no API to edit or
delete audit rows.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.context import Actor
from nexus.db.base import utcnow
from nexus.db.models import AuditLog

CATEGORIES = ("erlc", "cad", "mdt", "department", "system")


def _canonical(row: AuditLog) -> str:
    return json.dumps(
        {
            "category": row.category, "action": row.action, "user_id": row.user_id, "actor": row.actor,
            "target_type": row.target_type, "target_id": row.target_id, "target_ref": row.target_ref,
            "old": row.old_value, "new": row.new_value, "context": row.context,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
        sort_keys=True, default=str,
    )


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


async def audit(
    session: AsyncSession,
    actor: Actor,
    category: str,
    action: str,
    *,
    target_type: str = "",
    target_id: Any = None,
    target_ref: str = "",
    department_id: int | None = None,
    old: Any = None,
    new: Any = None,
    context: dict | None = None,
) -> AuditLog:
    if category not in CATEGORIES:
        raise ValueError(f"unknown audit category {category}")
    last = (await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))).scalar()
    row = AuditLog(
        category=category, action=action, user_id=actor.user_id, actor=actor.name,
        target_type=target_type, target_id=str(target_id) if target_id is not None else None,
        target_ref=target_ref, department_id=department_id, old_value=_jsonable(old), new_value=_jsonable(new),
        context=_jsonable(context), source=actor.source, ip=actor.ip, created_at=utcnow(), prev_hash=last or "",
    )
    row.hash = hashlib.sha256((row.prev_hash + _canonical(row)).encode()).hexdigest()
    session.add(row)
    return row


async def verify_chain(session: AsyncSession, limit: int | None = None) -> dict:
    """Recompute hashes. Returns {"ok": bool, "checked": n, "broken_at": id|None}."""
    stmt = select(AuditLog).order_by(AuditLog.id)
    rows = (await session.execute(stmt)).scalars().all()
    prev = ""
    checked = 0
    for row in rows if limit is None else rows[-limit:]:
        if limit is None and row.prev_hash != prev:
            return {"ok": False, "checked": checked, "broken_at": row.id, "reason": "chain link mismatch"}
        expected = hashlib.sha256((row.prev_hash + _canonical(row)).encode()).hexdigest()
        if expected != row.hash:
            return {"ok": False, "checked": checked, "broken_at": row.id, "reason": "row content modified"}
        prev = row.hash
        checked += 1
    return {"ok": True, "checked": checked, "broken_at": None}


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """Return (old, new) dicts containing only changed keys."""
    old, new = {}, {}
    for k, v in after.items():
        if before.get(k) != v:
            old[k] = before.get(k)
            new[k] = v
    return old, new
