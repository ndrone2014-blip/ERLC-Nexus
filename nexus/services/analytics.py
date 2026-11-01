"""Analytics. Metrics are only computed from data that actually exists, and
derived numbers are labelled (``derived: True``) with how they were calculated.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import utcnow
from nexus.db.models import (
    ApiSyncRecord,
    AuditLog,
    Department,
    Incident,
    IncidentAssignment,
    IncidentEvent,
    PlayerCountSample,
    Shift,
    Unit,
    User,
)
from nexus.erlc.sync import get_state
from nexus.services import lookups
from nexus.services.shifts import duration_seconds


def period(days: int | None = None, date_from: datetime | None = None, date_to: datetime | None = None) -> tuple[datetime, datetime]:
    end = date_to or utcnow()
    start = date_from or end - timedelta(days=days or 7)
    if start >= end:
        start = end - timedelta(days=1)
    return start, end


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _days(start: datetime, end: datetime) -> list[str]:
    out, d = [], start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= end and len(out) < 400:
        out.append(_day(d))
        d += timedelta(days=1)
    return out


async def server_analytics(s: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    server, fetched = await get_state(s, "server")
    samples = (await s.execute(select(PlayerCountSample).where(PlayerCountSample.ts.between(start, end))
                               .order_by(PlayerCountSample.ts))).scalars().all()
    syncs = (await s.execute(select(ApiSyncRecord.ok, ApiSyncRecord.duration_ms).where(
        ApiSyncRecord.started_at.between(start, end)))).all()
    team_totals: Counter = Counter()
    for sm in samples:
        team_totals.update(sm.teams or {})
    # downsample to at most ~300 points
    step = max(1, len(samples) // 300)
    series = [{"t": sm.ts, "players": sm.players, "max": sm.max_players, "queue": sm.queue} for sm in samples[::step]]
    ok = [d for o, d in syncs if o]
    return {
        "current": None if server is None else {"players": server["current_players"], "max": server["max_players"],
                                                "teams": server.get("teams", {}), "fetched_at": fetched},
        "player_history": series,
        "history_note": "Collected by ERLC Nexus once per minute while the sync service runs.",
        "peak_players": max((sm.players for sm in samples), default=None),
        "average_players": round(mean(sm.players for sm in samples), 1) if samples else None,
        "team_distribution_avg": {k: round(v / len(samples), 2) for k, v in team_totals.items()} if samples else {},
        "api_availability_pct": round(100 * len(ok) / len(syncs), 1) if syncs else None,
        "sync_count": len(syncs), "sync_failures": len(syncs) - len(ok),
        "avg_sync_ms": round(mean(ok)) if ok else None,
        "derived": True,
    }


async def cad_analytics(s: AsyncSession, start: datetime, end: datetime, department_id: int | None = None) -> dict[str, Any]:
    stmt = select(Incident).where(Incident.created_at.between(start, end), Incident.is_archived.is_(False))
    if department_id:
        stmt = stmt.where(Incident.department_id == department_id)
    incs = (await s.execute(stmt)).scalars().all()
    open_keys = set(await lookups.open_status_keys(s))
    cats = await lookups.categories(s)
    prios = {p["level"]: p["name"] for p in await lookups.priorities(s)}
    by_day = {d: 0 for d in _days(start, end)}
    for i in incs:
        by_day[_day(i.created_at)] = by_day.get(_day(i.created_at), 0) + 1
    resolution = [(i.closed_at - i.created_at).total_seconds() for i in incs if i.closed_at and i.status != "cancelled"]
    awaiting = [(i.dispatched_at - i.created_at).total_seconds() for i in incs if i.dispatched_at]
    response = [(i.on_scene_at - i.dispatched_at).total_seconds() for i in incs if i.on_scene_at and i.dispatched_at]
    assignments = (await s.execute(select(func.count()).select_from(IncidentAssignment).join(
        Incident, Incident.id == IncidentAssignment.incident_id).where(Incident.created_at.between(start, end)))).scalar() or 0
    return {
        "total": len(incs),
        "open": sum(1 for i in incs if i.status in open_keys),
        "closed": sum(1 for i in incs if i.status not in open_keys),
        "by_category": dict(Counter(lookups.label(cats, i.category) for i in incs).most_common()),
        "by_priority": {prios.get(k, str(k)): v for k, v in sorted(Counter(i.priority for i in incs).items())},
        "by_source": dict(Counter(i.source for i in incs)),
        "trend": [{"day": d, "count": n} for d, n in by_day.items()],
        "avg_resolution_seconds": round(mean(resolution)) if resolution else None,
        "avg_awaiting_dispatch_seconds": round(mean(awaiting)) if awaiting else None,
        "avg_response_seconds": round(mean(response)) if response else None,
        "unit_assignments": assignments,
        "derived": True,
        "notes": {"avg_resolution_seconds": "closed_at − created_at for closed/resolved incidents",
                  "avg_awaiting_dispatch_seconds": "first dispatch − created_at",
                  "avg_response_seconds": "first on-scene − first dispatch"},
    }


async def department_analytics(s: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    depts = (await s.execute(select(Department).where(Department.is_archived.is_(False)).order_by(Department.sort_order))).scalars().all()
    shifts = (await s.execute(select(Shift).where(Shift.started_at.between(start, end), Shift.status != "rejected"))).scalars().all()
    from nexus.db.models import DepartmentMembership

    members = dict((await s.execute(select(DepartmentMembership.department_id, func.count()).where(
        DepartmentMembership.status == "active").group_by(DepartmentMembership.department_id))).all())
    parts = dict((await s.execute(select(Unit.department_id, func.count(func.distinct(IncidentAssignment.incident_id)))
                                  .join(Unit, Unit.id == IncidentAssignment.unit_id)
                                  .where(IncidentAssignment.assigned_at.between(start, end)).group_by(Unit.department_id))).all())
    units = dict((await s.execute(select(Unit.department_id, func.count()).where(Unit.is_archived.is_(False))
                                  .group_by(Unit.department_id))).all())
    assign_counts = dict((await s.execute(select(Unit.department_id, func.count(IncidentAssignment.id))
                                          .join(Unit, Unit.id == IncidentAssignment.unit_id)
                                          .where(IncidentAssignment.assigned_at.between(start, end))
                                          .group_by(Unit.department_id))).all())
    out = []
    for d in depts:
        ds = [sh for sh in shifts if sh.department_id == d.id]
        people = {sh.user_id for sh in ds}
        out.append({
            "department_id": d.id, "department": d.abbreviation, "color": d.color, "active_members": members.get(d.id, 0),
            "shift_hours": round(sum(duration_seconds(sh) for sh in ds) / 3600, 1), "shifts": len(ds),
            "members_with_shifts": len(people),
            "participation_pct": round(100 * len(people) / members[d.id], 1) if members.get(d.id) else None,
            "incidents_participated": parts.get(d.id, 0), "units": units.get(d.id, 0),
            "assignments_per_unit": round(assign_counts.get(d.id, 0) / units[d.id], 2) if units.get(d.id) else None,
        })
    return out


async def dispatcher_analytics(s: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    incs = (await s.execute(select(Incident).where(Incident.created_at.between(start, end)))).scalars().all()
    open_keys = set(await lookups.open_status_keys(s))
    closed_by = Counter((await s.execute(select(IncidentEvent.user_id).where(
        IncidentEvent.event_type.in_(("closed", "resolved", "cancelled")), IncidentEvent.created_at.between(start, end),
        IncidentEvent.user_id.is_not(None)))).scalars())
    stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"created": 0, "handled": 0, "closed": 0, "durations": [],
                                                            "active": 0})
    for i in incs:
        if i.created_by_user_id:
            stats[i.created_by_user_id]["created"] += 1
        if i.dispatcher_user_id:
            st = stats[i.dispatcher_user_id]
            st["handled"] += 1
            if i.closed_at:
                st["durations"].append((i.closed_at - i.created_at).total_seconds())
            if i.status in open_keys:
                st["active"] += 1
    for uid, n in closed_by.items():
        stats[uid]["closed"] += n
    shift_secs: dict[int, int] = defaultdict(int)
    for sh in (await s.execute(select(Shift).where(Shift.started_at.between(start, end)))).scalars():
        shift_secs[sh.user_id] += duration_seconds(sh)
    names = dict((await s.execute(select(User.id, User.display_name).where(User.id.in_(list(stats) or [-1])))).all())
    rows = []
    for uid, st in stats.items():
        if not (st["handled"] or st["closed"]):
            continue
        rows.append({"user_id": uid, "name": names.get(uid, str(uid)), "calls_created": st["created"],
                     "calls_handled": st["handled"], "calls_closed": st["closed"], "active_workload": st["active"],
                     "avg_handling_seconds": round(mean(st["durations"])) if st["durations"] else None,
                     "shift_hours": round(shift_secs.get(uid, 0) / 3600, 1)})
    # Alphabetical, not ranked: raw counts alone are not a fair performance measure.
    return sorted(rows, key=lambda r: r["name"].lower())


async def activity_report(s: AsyncSession, start: datetime, end: datetime) -> dict[str, Any]:
    rows = (await s.execute(select(AuditLog.category, AuditLog.action).where(AuditLog.created_at.between(start, end)))).all()
    return {"by_category": dict(Counter(c for c, _ in rows)), "top_actions": dict(Counter(a for _, a in rows).most_common(15)),
            "total_events": len(rows)}


def to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()})
    return buf.getvalue()
