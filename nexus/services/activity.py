"""Activity feed and audit log queries (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AuditLog, Department

DESCRIPTIONS = {
    "incident.created": "created incident", "incident.updated": "updated incident", "incident.closed": "closed incident",
    "incident.resolved": "resolved incident", "incident.cancelled": "cancelled incident", "incident.reopened": "reopened incident",
    "incident.status_changed": "changed status of", "incident.priority": "changed priority of",
    "incident.unit_assigned": "assigned a unit to", "incident.unit_cleared": "cleared a unit from",
    "incident.note": "added a note to", "unit.status": "changed unit status", "unit.registered": "registered unit",
    "unit.removed": "removed unit", "traffic.started": "opened traffic stop", "traffic.completed": "completed traffic stop",
    "bolo.created": "issued BOLO", "bolo.updated": "updated BOLO", "shift.started": "started a shift",
    "shift.ended": "ended a shift", "person.created": "created person record", "person.updated": "updated person record",
    "vehicle.created": "created vehicle record", "vehicle.updated": "updated vehicle record",
    "report.submitted": "submitted report", "report.review_approve": "approved report",
    "report.review_return": "returned report", "player.kick": "kicked player", "player.ban": "banned player",
    "player.unban": "unbanned player", "server.command": "ran server command", "server.announcement": "sent an announcement",
    "warrant.created": "issued warrant", "case.created": "opened case", "personnel.promoted": "promoted",
    "personnel.demoted": "demoted", "personnel.added": "added personnel", "config.changed": "changed setting",
}

FEED_ACTIONS = [k for k in DESCRIPTIONS if k != "config.changed"]


def entry_dict(a: AuditLog, depts: dict[int, str] | None = None, *, full: bool = False) -> dict[str, Any]:
    d = {"id": a.id, "category": a.category, "action": a.action, "user": a.actor, "user_id": a.user_id,
         "description": f"{a.actor} {DESCRIPTIONS.get(a.action, a.action.replace('.', ' ').replace('_', ' '))}"
                        + (f" {a.target_ref}" if a.target_ref else ""),
         "target_type": a.target_type, "target_id": a.target_id, "reference": a.target_ref,
         "department": (depts or {}).get(a.department_id), "source": a.source, "created_at": a.created_at,
         "link": _link(a)}
    if full:
        d.update({"old": a.old_value, "new": a.new_value, "context": a.context, "ip": a.ip, "hash": a.hash})
    return d


def _link(a: AuditLog) -> str:
    if not a.target_id:
        return ""
    return {"incident": f"/#/cad/incident/{a.target_id}", "person": f"/#/records/person/{a.target_id}",
            "vehicle": f"/#/records/vehicle/{a.target_id}", "bolo": f"/#/records/bolo/{a.target_id}",
            "report": f"/#/records/report/{a.target_id}", "traffic": f"/#/cad/traffic/{a.target_id}",
            "case": f"/#/records/case/{a.target_id}"}.get(a.target_type, "")


async def feed(s: AsyncSession, limit: int = 40, before_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(AuditLog).where(AuditLog.action.in_(FEED_ACTIONS)).order_by(AuditLog.id.desc()).limit(min(limit, 200))
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    depts = dict((await s.execute(select(Department.id, Department.abbreviation))).all())
    return [entry_dict(a, depts) for a in (await s.execute(stmt)).scalars()]


async def audit_search(s: AsyncSession, *, category: str = "", action: str = "", user_id: int | None = None,
                       q: str = "", date_from: datetime | None = None, date_to: datetime | None = None,
                       limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    stmt = select(AuditLog)
    if category:
        stmt = stmt.where(AuditLog.category == category)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    if q:
        stmt = stmt.where(or_(AuditLog.actor.ilike(f"%{q}%"), AuditLog.target_ref.ilike(f"%{q}%"),
                              AuditLog.action.ilike(f"%{q}%")))
    total = (await s.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    depts = dict((await s.execute(select(Department.id, Department.abbreviation))).all())
    rows = (await s.execute(stmt.order_by(AuditLog.id.desc()).limit(min(limit, 500)).offset(offset))).scalars()
    return [entry_dict(a, depts, full=True) for a in rows], total
