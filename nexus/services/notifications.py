"""Centralized notification engine with grouping, throttling and deduplication."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.context import Actor
from nexus.core.events import emit
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import Notification, NotificationRead, User

KINDS = {
    "erlc.911": "New in-game emergency call",
    "incident.created": "New incident",
    "incident.priority": "Incident priority change",
    "incident.closed": "Incident closed",
    "unit.assigned": "Unit assignment",
    "unit.status": "Unit status change",
    "bolo.created": "New BOLO",
    "bolo.expired": "BOLO expiration",
    "report.submitted": "Report awaiting review",
    "report.reviewed": "Report reviewed",
    "shift.started": "Shift started",
    "shift.ended": "Shift ended",
    "erlc.status": "Server status change",
    "erlc.api": "API connection issue",
    "erlc.modcall": "In-game moderator call",
    "comms.announcement": "Dispatch announcement",
}


async def notify(
    session: AsyncSession,
    kind: str,
    title: str,
    body: str = "",
    *,
    audience: str = "all",
    user_id: int | None = None,
    department_id: int | None = None,
    link: str = "",
    dedupe_key: str | None = None,
    severity: str = "info",
    data: dict[str, Any] | None = None,
) -> Notification | None:
    """Create (or group into) a notification and emit it to live clients/Discord."""
    throttle = int(await get_setting(session, "notifications.throttle_seconds") or 0)
    if dedupe_key and throttle:
        recent = (await session.execute(
            select(Notification).where(Notification.dedupe_key == dedupe_key,
                                       Notification.created_at > utcnow() - timedelta(seconds=throttle))
            .order_by(Notification.id.desc()).limit(1)
        )).scalar_one_or_none()
        if recent is not None:
            recent.count += 1
            recent.title = title
            recent.body = body[:600]
            return None  # grouped: no new event → no spam
    n = Notification(kind=kind, title=title[:160], body=body[:600], audience="user" if user_id else audience,
                     user_id=user_id, department_id=department_id, link=link, dedupe_key=dedupe_key, severity=severity)
    session.add(n)
    await session.flush()
    emit(session, "notification", {
        "id": n.id, "kind": kind, "title": n.title, "body": n.body, "audience": n.audience, "user_id": user_id,
        "department_id": department_id, "link": link, "severity": severity, "data": data or {},
    }, origin="system")
    return n


def audience_allows(actor: Actor, n: Notification) -> bool:
    if n.audience == "all":
        return True
    if n.audience == "user":
        return n.user_id == actor.user_id
    if n.audience.startswith("perm:"):
        return actor.can(n.audience[5:])
    return False


async def list_for(session: AsyncSession, actor: Actor, *, limit: int = 50, unread_only: bool = False,
                   before_id: int | None = None) -> list[dict[str, Any]]:
    user = await session.get(User, actor.user_id) if actor.user_id else None
    muted = set((user.preferences or {}).get("muted_notifications", [])) if user else set()
    stmt = select(Notification).order_by(Notification.id.desc()).limit(limit * 3)
    if before_id:
        stmt = stmt.where(Notification.id < before_id)
    rows = [n for n in (await session.execute(stmt)).scalars() if audience_allows(actor, n) and n.kind not in muted]
    if actor.department_ids and not actor.can("cad.department.manage"):
        rows = [n for n in rows if n.department_id is None or n.department_id in actor.department_ids]
    rows = rows[:limit]
    read_ids = set()
    if actor.user_id and rows:
        read_ids = set((await session.execute(
            select(NotificationRead.notification_id).where(NotificationRead.user_id == actor.user_id,
                                                           NotificationRead.notification_id.in_([n.id for n in rows]))
        )).scalars())
    out = [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "severity": n.severity,
            "count": n.count, "created_at": n.created_at, "read": n.id in read_ids} for n in rows]
    return [o for o in out if not o["read"]] if unread_only else out


async def mark_read(session: AsyncSession, actor: Actor, ids: list[int] | None = None) -> int:
    if not actor.user_id:
        return 0
    if ids is None:
        ids = [n["id"] for n in await list_for(session, actor, limit=200, unread_only=True)]
    existing = set((await session.execute(
        select(NotificationRead.notification_id).where(NotificationRead.user_id == actor.user_id,
                                                       NotificationRead.notification_id.in_(ids))
    )).scalars()) if ids else set()
    count = 0
    for nid in ids:
        if nid not in existing:
            session.add(NotificationRead(notification_id=nid, user_id=actor.user_id))
            count += 1
    return count
