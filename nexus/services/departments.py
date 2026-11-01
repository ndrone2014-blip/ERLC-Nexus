"""Departments, ranks and personnel."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.core.audit import audit
from nexus.core.context import Actor, Conflict, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.permissions import validate_keys
from nexus.db.base import utcnow
from nexus.db.models import (
    Department,
    DepartmentHistory,
    DepartmentMembership,
    Incident,
    IncidentAssignment,
    Rank,
    Report,
    Shift,
    TrafficStop,
    Unit,
    UnitMembership,
    User,
)

KINDS = ("law", "fire", "ems", "dot", "dispatch", "civilian", "other")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def dept_dict(d: Department, *, ranks: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "name": d.name, "abbreviation": d.abbreviation, "kind": d.kind, "color": d.color,
           "logo_url": d.logo_url, "description": d.description, "callsign_format": d.callsign_format,
           "unit_types": d.unit_types or [], "discord_role_id": d.discord_role_id, "notify_channel_id": d.notify_channel_id,
           "sort_order": d.sort_order, "is_archived": d.is_archived}
    if ranks:
        out["ranks"] = [rank_dict(r) for r in d.ranks if not r.is_archived]
    return out


def rank_dict(r: Rank) -> dict[str, Any]:
    return {"id": r.id, "department_id": r.department_id, "name": r.name, "abbreviation": r.abbreviation,
            "sort_order": r.sort_order, "is_supervisor": r.is_supervisor, "is_command": r.is_command,
            "permissions": r.permissions or []}


async def list_departments(s: AsyncSession, *, include_archived: bool = False) -> list[Department]:
    stmt = select(Department).options(selectinload(Department.ranks)).order_by(Department.sort_order, Department.name)
    if not include_archived:
        stmt = stmt.where(Department.is_archived.is_(False))
    return list((await s.execute(stmt)).scalars())


async def get_department(s: AsyncSession, ref: int | str) -> Department:
    stmt = select(Department).options(selectinload(Department.ranks))
    if isinstance(ref, int) or str(ref).isdigit():
        d = (await s.execute(stmt.where(Department.id == int(ref)))).scalar_one_or_none()
    else:
        d = (await s.execute(stmt.where(func.upper(Department.abbreviation) == str(ref).upper()))).scalar_one_or_none()
    if d is None:
        raise NotFound("Department not found.")
    return d


def _dept_values(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for f in ("name", "abbreviation", "kind", "color", "logo_url", "description", "callsign_format", "unit_types",
              "discord_role_id", "notify_channel_id", "sort_order"):
        if f not in data:
            continue
        v = data[f]
        if f == "kind" and v not in KINDS:
            raise ValidationFailed(f"Department type must be one of: {', '.join(KINDS)}.")
        if f == "color" and not COLOR_RE.match(v or ""):
            raise ValidationFailed("Color must be a hex value like #3b82f6.")
        if f == "abbreviation":
            v = (v or "").strip().upper()
            if not re.match(r"^[A-Z0-9\-]{1,12}$", v):
                raise ValidationFailed("Abbreviation must be 1-12 letters/numbers.")
        if f == "unit_types":
            v = [str(x).strip()[:32] for x in (v.split(",") if isinstance(v, str) else v or []) if str(x).strip()]
        if f in ("discord_role_id", "notify_channel_id"):
            v = str(v).strip() or None if v else None
            if v and not v.isdigit():
                raise ValidationFailed("Discord IDs must be numeric.")
        if f == "callsign_format" and not v:
            raise ValidationFailed("Callsign format cannot be empty.")
        if f == "logo_url" and v and not str(v).startswith(("https://", "http://", "/")):
            raise ValidationFailed("Logo must be a URL.")
        if isinstance(v, str):
            v = v.strip()[:2000 if f == "description" else 300]
        out[f] = v
    return out


async def save_department(s: AsyncSession, actor: Actor, data: dict[str, Any], dept_id: int | None = None) -> Department:
    actor.require("cad.department.manage")
    vals = _dept_values(data)
    if dept_id is None:
        if not vals.get("name") or not vals.get("abbreviation"):
            raise ValidationFailed("Name and abbreviation are required.")
        for col in ("name", "abbreviation"):
            if (await s.execute(select(Department.id).where(func.lower(getattr(Department, col)) == vals[col].lower()))).scalar():
                raise Conflict(f"A department with that {col} already exists.")
        d = Department(**{"kind": "law", "callsign_format": "{abbr}-{seq:02}", **vals})
        s.add(d)
        await s.flush()
        for i, name in enumerate(data.get("ranks") or []):
            s.add(Rank(department_id=d.id, name=str(name)[:60], sort_order=i, is_command=i == 0))
        await audit(s, actor, "department", "department.created", target_type="department", target_id=d.id,
                    target_ref=d.abbreviation, new=vals)
    else:
        d = await get_department(s, dept_id)
        before = dept_dict(d)
        for k, v in vals.items():
            setattr(d, k, v)
        await audit(s, actor, "department", "department.updated", target_type="department", target_id=d.id,
                    target_ref=d.abbreviation, old={k: before[k] for k in vals}, new=vals)
    emit(s, "department.changed", {"id": d.id}, origin=actor.source)
    return d


async def archive_department(s: AsyncSession, actor: Actor, dept_id: int, archived: bool = True) -> Department:
    actor.require("cad.department.manage")
    d = await get_department(s, dept_id)
    d.is_archived = archived
    await audit(s, actor, "department", "department.archived" if archived else "department.restored",
                target_type="department", target_id=d.id, target_ref=d.abbreviation)
    emit(s, "department.changed", {"id": d.id}, origin=actor.source)
    return d


# ---- ranks ----------------------------------------------------------------------


async def save_rank(s: AsyncSession, actor: Actor, dept_id: int, data: dict[str, Any], rank_id: int | None = None) -> Rank:
    if not actor.can_manage_department(dept_id, "dept.ranks.manage"):
        raise Forbidden("You cannot manage ranks for this department.")
    d = await get_department(s, dept_id)
    perms = data.get("permissions")
    if perms is not None:
        bad = validate_keys(perms)
        if bad:
            raise ValidationFailed(f"Unknown permissions: {', '.join(bad)}")
        if not actor.can("system.permissions") and perms:
            raise Forbidden("Only permission administrators can attach permissions to ranks.")
    name = (data.get("name") or "").strip()
    if rank_id is None:
        if not name:
            raise ValidationFailed("Rank name is required.")
        if any(r.name.lower() == name.lower() and not r.is_archived for r in d.ranks):
            raise Conflict("That rank already exists.")
        r = Rank(department_id=d.id, name=name[:60], abbreviation=(data.get("abbreviation") or "")[:12],
                 sort_order=int(data.get("sort_order", len(d.ranks))), is_supervisor=bool(data.get("is_supervisor")),
                 is_command=bool(data.get("is_command")), permissions=perms or [])
        s.add(r)
        await s.flush()
        await audit(s, actor, "department", "rank.created", target_type="rank", target_id=r.id, target_ref=r.name,
                    department_id=d.id)
    else:
        r = await s.get(Rank, rank_id)
        if r is None or r.department_id != d.id:
            raise NotFound("Rank not found.")
        before = rank_dict(r)
        if name:
            r.name = name[:60]
        for f in ("abbreviation", "is_supervisor", "is_command"):
            if f in data:
                setattr(r, f, data[f])
        if "sort_order" in data:
            r.sort_order = int(data["sort_order"])
        if perms is not None:
            r.permissions = perms
        await audit(s, actor, "department", "rank.updated", target_type="rank", target_id=r.id, target_ref=r.name,
                    department_id=d.id, old=before, new=rank_dict(r))
    emit(s, "department.changed", {"id": d.id}, origin=actor.source)
    return r


async def reorder_ranks(s: AsyncSession, actor: Actor, dept_id: int, rank_ids: list[int]) -> None:
    if not actor.can_manage_department(dept_id, "dept.ranks.manage"):
        raise Forbidden("You cannot manage ranks for this department.")
    d = await get_department(s, dept_id)
    by_id = {r.id: r for r in d.ranks}
    if set(rank_ids) - set(by_id):
        raise ValidationFailed("Rank list contains ranks from another department.")
    for i, rid in enumerate(rank_ids):
        by_id[rid].sort_order = i
    await audit(s, actor, "department", "rank.reordered", target_type="department", target_id=d.id,
                target_ref=d.abbreviation, new=rank_ids)


async def delete_rank(s: AsyncSession, actor: Actor, dept_id: int, rank_id: int) -> None:
    if not actor.can_manage_department(dept_id, "dept.ranks.manage"):
        raise Forbidden("You cannot manage ranks for this department.")
    r = await s.get(Rank, rank_id)
    if r is None or r.department_id != dept_id:
        raise NotFound("Rank not found.")
    in_use = (await s.execute(select(func.count()).select_from(DepartmentMembership).where(
        DepartmentMembership.rank_id == rank_id, DepartmentMembership.status != "removed"))).scalar()
    if in_use:
        raise Conflict(f"{in_use} member(s) still hold this rank. Reassign them first.")
    r.is_archived = True  # keep history intact
    await audit(s, actor, "department", "rank.deleted", target_type="rank", target_id=r.id, target_ref=r.name,
                department_id=dept_id)


# ---- personnel ------------------------------------------------------------------


def member_dict(m: DepartmentMembership, on_shift: set[int] | None = None, units: dict[int, str] | None = None) -> dict[str, Any]:
    return {"id": m.id, "user_id": m.user_id, "name": m.user.name if m.user else None,
            "discord_id": m.user.discord_id if m.user else None, "avatar_url": m.user.avatar_url if m.user else "",
            "roblox_username": m.user.roblox_username if m.user else None,
            "department_id": m.department_id, "rank_id": m.rank_id, "rank": m.rank.name if m.rank else None,
            "rank_order": m.rank.sort_order if m.rank else 999, "is_supervisor": bool(m.rank and (m.rank.is_supervisor or m.rank.is_command)),
            "callsign": m.callsign, "status": m.status, "notes": m.notes, "joined_at": m.joined_at,
            "on_shift": m.user_id in (on_shift or set()), "unit": (units or {}).get(m.user_id)}


async def roster(s: AsyncSession, dept_id: int, *, include_removed: bool = False) -> list[dict[str, Any]]:
    stmt = (select(DepartmentMembership).options(selectinload(DepartmentMembership.user), selectinload(DepartmentMembership.rank))
            .where(DepartmentMembership.department_id == dept_id))
    if not include_removed:
        stmt = stmt.where(DepartmentMembership.status != "removed")
    members = (await s.execute(stmt)).scalars().all()
    on_shift = set((await s.execute(select(Shift.user_id).where(Shift.ended_at.is_(None)))).scalars())
    units = dict((await s.execute(select(UnitMembership.user_id, Unit.callsign).join(Unit, Unit.id == UnitMembership.unit_id)
                                  .where(UnitMembership.left_at.is_(None), Unit.is_archived.is_(False)))).all())
    rows = [member_dict(m, on_shift, units) for m in members]
    return sorted(rows, key=lambda r: (r["status"] != "active", r["rank_order"], (r["name"] or "").lower()))


async def _history(s: AsyncSession, actor: Actor, m: DepartmentMembership, action: str, old: Any, new: Any) -> None:
    s.add(DepartmentHistory(user_id=m.user_id, department_id=m.department_id, action=action,
                            old_value=None if old is None else str(old)[:120], new_value=None if new is None else str(new)[:120],
                            actor_id=actor.user_id))


async def add_member(s: AsyncSession, actor: Actor, dept_id: int, user_id: int, *, rank_id: int | None = None,
                     callsign: str = "") -> DepartmentMembership:
    if not actor.can_manage_department(dept_id):
        raise Forbidden("You cannot manage personnel for this department.")
    d = await get_department(s, dept_id)
    user = await s.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    if rank_id is not None:
        r = await s.get(Rank, rank_id)
        if r is None or r.department_id != d.id:
            raise ValidationFailed("Rank does not belong to this department.")
    elif d.ranks:
        rank_id = sorted([r for r in d.ranks if not r.is_archived], key=lambda r: -r.sort_order)[0].id
    callsign = (callsign or "").strip()[:24] or None
    if callsign:
        await _check_callsign_free(s, callsign)
    m = (await s.execute(select(DepartmentMembership).where(DepartmentMembership.user_id == user_id,
                                                            DepartmentMembership.department_id == dept_id))).scalar_one_or_none()
    if m and m.status != "removed":
        raise Conflict(f"{user.name} is already a member of {d.abbreviation}.")
    if m:
        m.status, m.rank_id, m.callsign, m.left_at, m.joined_at = "active", rank_id, callsign, None, utcnow()
    else:
        m = DepartmentMembership(user_id=user_id, department_id=dept_id, rank_id=rank_id, callsign=callsign, status="active")
        s.add(m)
    await s.flush()
    await _history(s, actor, m, "joined", None, d.abbreviation)
    await audit(s, actor, "department", "personnel.added", target_type="user", target_id=user_id, target_ref=user.name,
                department_id=dept_id, new={"rank_id": rank_id, "callsign": callsign})
    emit(s, "department.changed", {"id": dept_id}, origin=actor.source)
    return m


async def _check_callsign_free(s: AsyncSession, callsign: str, exclude_membership: int | None = None) -> None:
    stmt = select(DepartmentMembership.id).where(func.lower(DepartmentMembership.callsign) == callsign.lower(),
                                                 DepartmentMembership.status != "removed")
    if exclude_membership:
        stmt = stmt.where(DepartmentMembership.id != exclude_membership)
    if (await s.execute(stmt)).scalar():
        raise Conflict(f"Callsign {callsign} is already assigned to another member.")


async def update_member(s: AsyncSession, actor: Actor, membership_id: int, data: dict[str, Any]) -> DepartmentMembership:
    m = (await s.execute(select(DepartmentMembership).options(selectinload(DepartmentMembership.rank),
                                                              selectinload(DepartmentMembership.user))
                         .where(DepartmentMembership.id == membership_id))).scalar_one_or_none()
    if m is None:
        raise NotFound("Membership not found.")
    if not actor.can_manage_department(m.department_id):
        raise Forbidden("You cannot manage personnel for this department.")
    if "rank_id" in data and data["rank_id"] != m.rank_id:
        new_rank = await s.get(Rank, data["rank_id"]) if data["rank_id"] else None
        if data["rank_id"] and (new_rank is None or new_rank.department_id != m.department_id):
            raise ValidationFailed("Rank does not belong to this department.")
        old_rank = m.rank
        if new_rank and old_rank and actor.user_id == m.user_id and new_rank.sort_order < old_rank.sort_order and not actor.can("cad.department.manage"):
            raise Forbidden("You cannot promote yourself.")
        action = "rank"
        if old_rank and new_rank:
            action = "promoted" if new_rank.sort_order < old_rank.sort_order else "demoted"
        m.rank = new_rank
        await _history(s, actor, m, action, old_rank.name if old_rank else None, new_rank.name if new_rank else None)
        await audit(s, actor, "department", f"personnel.{action}", target_type="user", target_id=m.user_id,
                    target_ref=m.user.name if m.user else "", department_id=m.department_id,
                    old=old_rank.name if old_rank else None, new=new_rank.name if new_rank else None)
    if "callsign" in data and (data["callsign"] or None) != m.callsign:
        cs = (data["callsign"] or "").strip()[:24] or None
        if cs:
            await _check_callsign_free(s, cs, exclude_membership=m.id)
        await _history(s, actor, m, "callsign", m.callsign, cs)
        await audit(s, actor, "department", "personnel.callsign", target_type="user", target_id=m.user_id,
                    department_id=m.department_id, old=m.callsign, new=cs)
        m.callsign = cs
    if "status" in data and data["status"] != m.status:
        if data["status"] not in ("active", "leave", "inactive", "removed"):
            raise ValidationFailed("Invalid status.")
        await _history(s, actor, m, "status", m.status, data["status"])
        await audit(s, actor, "department", "personnel.status", target_type="user", target_id=m.user_id,
                    department_id=m.department_id, old=m.status, new=data["status"])
        m.status = data["status"]
        m.left_at = utcnow() if m.status == "removed" else None
    if "notes" in data:
        m.notes = (data["notes"] or "")[:2000]
    emit(s, "department.changed", {"id": m.department_id}, origin=actor.source)
    return m


async def personnel_profile(s: AsyncSession, actor: Actor, user_id: int) -> dict[str, Any]:
    actor.require("dept.view")
    user = await s.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    memberships = (await s.execute(select(DepartmentMembership).options(selectinload(DepartmentMembership.rank),
                                                                        selectinload(DepartmentMembership.department),
                                                                        selectinload(DepartmentMembership.user))
                                   .where(DepartmentMembership.user_id == user_id))).scalars().all()
    history = (await s.execute(select(DepartmentHistory, Department.abbreviation)
                               .join(Department, Department.id == DepartmentHistory.department_id)
                               .where(DepartmentHistory.user_id == user_id).order_by(DepartmentHistory.id.desc()).limit(100))).all()
    shifts = (await s.execute(select(Shift).where(Shift.user_id == user_id).order_by(Shift.started_at.desc()).limit(25))).scalars().all()
    from nexus.services.shifts import shift_dict

    show_notes = actor.user_id == user_id or any(actor.can_manage_department(m.department_id) for m in memberships)
    return {
        "user": {"id": user.id, "name": user.name, "discord_id": user.discord_id, "avatar_url": user.avatar_url,
                 "roblox_username": user.roblox_username, "roblox_id": user.roblox_id},
        "memberships": [{**member_dict(m), "department": m.department.abbreviation,
                         "notes": m.notes if show_notes else None} for m in memberships],
        "history": [{"department": abbr, "action": h.action, "old": h.old_value, "new": h.new_value, "created_at": h.created_at}
                    for h, abbr in history],
        "shifts": [shift_dict(sh) for sh in shifts],
    }


async def department_stats(s: AsyncSession, dept_id: int, days: int = 30) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    members = (await s.execute(select(func.count()).select_from(DepartmentMembership).where(
        DepartmentMembership.department_id == dept_id, DepartmentMembership.status == "active"))).scalar() or 0
    shifts = (await s.execute(select(Shift).where(Shift.department_id == dept_id, Shift.started_at >= since))).scalars().all()
    from nexus.services.shifts import duration_seconds

    hours = sum(duration_seconds(sh) for sh in shifts) / 3600
    on_shift = sum(1 for sh in shifts if sh.ended_at is None)
    incidents = (await s.execute(select(func.count()).select_from(Incident).where(Incident.department_id == dept_id,
                                                                                  Incident.created_at >= since))).scalar() or 0
    participation = (await s.execute(select(func.count(func.distinct(IncidentAssignment.incident_id)))
                                     .join(Unit, Unit.id == IncidentAssignment.unit_id)
                                     .where(Unit.department_id == dept_id, IncidentAssignment.assigned_at >= since))).scalar() or 0
    units = (await s.execute(select(func.count()).select_from(Unit).where(Unit.department_id == dept_id,
                                                                          Unit.is_archived.is_(False)))).scalar() or 0
    stops = (await s.execute(select(func.count()).select_from(TrafficStop).where(TrafficStop.department_id == dept_id,
                                                                                 TrafficStop.started_at >= since))).scalar() or 0
    reports = (await s.execute(select(func.count()).select_from(Report).where(Report.department_id == dept_id,
                                                                              Report.created_at >= since))).scalar() or 0
    active_people = len({sh.user_id for sh in shifts})
    return {"department_id": dept_id, "period_days": days, "active_members": members, "on_shift": on_shift,
            "shift_hours": round(hours, 1), "shifts": len(shifts), "members_with_shifts": active_people,
            "participation_pct": round(100 * active_people / members, 1) if members else None,
            "incidents_owned": incidents, "incidents_participated": participation, "units": units,
            "traffic_stops": stops, "reports": reports}
