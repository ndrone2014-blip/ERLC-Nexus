"""Shift / duty tracking.

* One active shift per user is enforced by a partial unique index.
* Active shifts live in the database, so a bot or website restart never loses
  them; on startup active shifts are marked ``recovered`` for transparency.
* Manual edits store ``adjusted_seconds`` separately from the real elapsed time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, Conflict, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import Department, DepartmentMembership, Shift, Unit, User
from nexus.services import notifications


def elapsed_seconds(sh: Shift, now: datetime | None = None) -> int:
    end = sh.ended_at or now or utcnow()
    return max(0, int((end - sh.started_at).total_seconds()))


def duration_seconds(sh: Shift, now: datetime | None = None) -> int:
    """Credited duration: manual adjustment if present, otherwise actual elapsed time."""
    return sh.adjusted_seconds if sh.adjusted_seconds is not None else elapsed_seconds(sh, now)


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h}h {rem // 60:02d}m"


def shift_dict(sh: Shift, names: dict[int, str] | None = None, depts: dict[int, str] | None = None) -> dict[str, Any]:
    names, depts = names or {}, depts or {}
    el = elapsed_seconds(sh)
    return {"id": sh.id, "user_id": sh.user_id, "user": names.get(sh.user_id), "department_id": sh.department_id,
            "department": depts.get(sh.department_id), "unit_id": sh.unit_id, "callsign": sh.callsign,
            "started_at": sh.started_at, "ended_at": sh.ended_at, "status": sh.status, "notes": sh.notes,
            "source": sh.source, "elapsed_seconds": el, "credited_seconds": duration_seconds(sh),
            "is_adjusted": sh.adjusted_seconds is not None, "adjust_reason": sh.adjust_reason,
            "adjusted_by": sh.adjusted_by, "approved_by": sh.approved_by, "approved_at": sh.approved_at,
            "recovered": sh.recovered, "active": sh.ended_at is None, "duration": fmt_duration(duration_seconds(sh))}


async def active_shift(s: AsyncSession, user_id: int) -> Shift | None:
    return (await s.execute(select(Shift).where(Shift.user_id == user_id, Shift.ended_at.is_(None)))).scalar_one_or_none()


async def start(s: AsyncSession, actor: Actor, *, department_id: int | None = None, callsign: str = "",
                unit_id: int | None = None, notes: str = "") -> Shift:
    actor.require("shift.self")
    if not actor.user_id:
        raise ValidationFailed("Shifts need a user.")
    if await active_shift(s, actor.user_id):
        raise Conflict("You are already on shift. End your current shift first.")
    memberships = (await s.execute(select(DepartmentMembership).where(
        DepartmentMembership.user_id == actor.user_id, DepartmentMembership.status == "active"))).scalars().all()
    if department_id is None:
        if len(memberships) == 1:
            department_id = memberships[0].department_id
        elif memberships:
            raise ValidationFailed("You belong to several departments — choose one to clock in.")
    if department_id is not None:
        if await s.get(Department, department_id) is None:
            raise ValidationFailed("Department not found.")
        m = next((m for m in memberships if m.department_id == department_id), None)
        if m is None and not actor.can("shift.manage"):
            raise Forbidden("You are not an active member of that department.")
        if not callsign and m and m.callsign:
            callsign = m.callsign
    if unit_id is not None:
        unit = await s.get(Unit, unit_id)
        if unit is None or unit.is_archived:
            raise ValidationFailed("Unit not found.")
        callsign = callsign or unit.callsign
    sh = Shift(user_id=actor.user_id, department_id=department_id, unit_id=unit_id, callsign=(callsign or "")[:24],
               notes=(notes or "")[:1000], source=actor.source, status="active", started_at=utcnow())
    s.add(sh)
    try:
        await s.flush()
    except IntegrityError:
        await s.rollback()
        raise Conflict("You are already on shift.")
    dept = await s.get(Department, department_id) if department_id else None
    await audit(s, actor, "department", "shift.started", target_type="shift", target_id=sh.id, target_ref=sh.callsign,
                department_id=department_id)
    emit(s, "shift.started", {"id": sh.id, "user_id": actor.user_id, "user": actor.name, "callsign": sh.callsign,
                              "department": dept.abbreviation if dept else None, "department_id": department_id},
         origin=actor.source)
    await notifications.notify(s, "shift.started", f"{actor.name} clocked in",
                               f"{dept.abbreviation if dept else 'No department'} {sh.callsign}".strip(),
                               audience="perm:shift.manage", department_id=department_id,
                               dedupe_key=f"shift:{actor.user_id}")
    return sh


async def end(s: AsyncSession, actor: Actor, *, user_id: int | None = None, notes: str = "") -> Shift:
    target = user_id or actor.user_id
    if target != actor.user_id:
        actor.require("shift.manage")
    else:
        actor.require("shift.self")
    sh = await active_shift(s, target)
    if sh is None:
        raise NotFound("No active shift found.")
    sh.ended_at = utcnow()
    require_approval = await get_setting(s, "shift.require_approval")
    sh.status = "ended" if require_approval else "approved"
    if notes:
        sh.notes = ((sh.notes + "\n") if sh.notes else "") + notes.strip()[:1000]
    # take the user's units out of service
    from nexus.db.models import UnitMembership

    unit_ids = (await s.execute(select(UnitMembership.unit_id).where(UnitMembership.user_id == target,
                                                                     UnitMembership.left_at.is_(None)))).scalars().all()
    for uid in unit_ids:
        unit = await s.get(Unit, uid)
        if unit and unit.status != "out_of_service":
            others_on = (await s.execute(select(func.count()).select_from(Shift).join(
                UnitMembership, (UnitMembership.user_id == Shift.user_id) & (UnitMembership.unit_id == uid)
                & UnitMembership.left_at.is_(None)).where(Shift.ended_at.is_(None), Shift.user_id != target))).scalar()
            if not others_on and not unit.current_incident_id:
                unit.status = "out_of_service"
                unit.status_changed_at = utcnow()
                emit(s, "unit.status", {"id": unit.id, "callsign": unit.callsign, "status": "out_of_service"},
                     origin=actor.source)
    user = await s.get(User, target)
    await audit(s, actor, "department", "shift.ended", target_type="shift", target_id=sh.id, target_ref=sh.callsign,
                department_id=sh.department_id, new={"duration_seconds": elapsed_seconds(sh)})
    emit(s, "shift.ended", {"id": sh.id, "user_id": target, "user": user.name if user else "", "callsign": sh.callsign,
                            "duration": fmt_duration(elapsed_seconds(sh)), "department_id": sh.department_id},
         origin=actor.source)
    await notifications.notify(s, "shift.ended", f"{user.name if user else 'Member'} clocked out",
                               f"Duration {fmt_duration(elapsed_seconds(sh))}", audience="perm:shift.manage",
                               department_id=sh.department_id, dedupe_key=f"shift:{target}")
    return sh


async def adjust(s: AsyncSession, actor: Actor, shift_id: int, *, credited_minutes: int | None, reason: str) -> Shift:
    actor.require("shift.manage")
    sh = await s.get(Shift, shift_id)
    if sh is None:
        raise NotFound("Shift not found.")
    if sh.department_id and not actor.can_manage_department(sh.department_id, "shift.manage") and not actor.can("system.configure"):
        raise Forbidden("You cannot edit shifts for this department.")
    if not (reason or "").strip():
        raise ValidationFailed("A reason is required when adjusting shift time.")
    if credited_minutes is not None and not 0 <= credited_minutes <= 24 * 60:
        raise ValidationFailed("Credited time must be between 0 and 24 hours.")
    old = sh.adjusted_seconds
    sh.adjusted_seconds = None if credited_minutes is None else credited_minutes * 60
    sh.adjusted_by = actor.user_id
    sh.adjust_reason = reason.strip()[:200]
    await audit(s, actor, "department", "shift.adjusted", target_type="shift", target_id=sh.id,
                department_id=sh.department_id, old={"credited_seconds": old, "elapsed": elapsed_seconds(sh)},
                new={"credited_seconds": sh.adjusted_seconds}, context={"reason": reason})
    return sh


async def approve(s: AsyncSession, actor: Actor, shift_id: int, approved: bool = True) -> Shift:
    actor.require("shift.manage")
    sh = await s.get(Shift, shift_id)
    if sh is None:
        raise NotFound("Shift not found.")
    if sh.ended_at is None:
        raise ValidationFailed("Active shifts cannot be approved yet.")
    if sh.user_id == actor.user_id and not actor.can("*"):
        raise Forbidden("You cannot approve your own shift.")
    sh.status = "approved" if approved else "rejected"
    sh.approved_by = actor.user_id
    sh.approved_at = utcnow()
    await audit(s, actor, "department", f"shift.{sh.status}", target_type="shift", target_id=sh.id,
                department_id=sh.department_id)
    return sh


async def history(s: AsyncSession, *, user_id: int | None = None, department_id: int | None = None,
                  status: str = "", since: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(Shift).order_by(Shift.started_at.desc())
    if user_id:
        stmt = stmt.where(Shift.user_id == user_id)
    if department_id:
        stmt = stmt.where(Shift.department_id == department_id)
    if status == "active":
        stmt = stmt.where(Shift.ended_at.is_(None))
    elif status:
        stmt = stmt.where(Shift.status == status)
    if since:
        stmt = stmt.where(Shift.started_at >= since)
    rows = (await s.execute(stmt.limit(min(limit, 500)))).scalars().all()
    uids = {r.user_id for r in rows}
    names = dict((await s.execute(select(User.id, User.display_name).where(User.id.in_(uids)))).all()) if uids else {}
    depts = dict((await s.execute(select(Department.id, Department.abbreviation))).all())
    return [shift_dict(r, names, depts) for r in rows]


async def stats(s: AsyncSession, user_id: int) -> dict[str, Any]:
    now = utcnow()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (await s.execute(select(Shift).where(Shift.user_id == user_id, Shift.status != "rejected"))).scalars().all()

    def total(since: datetime | None) -> int:
        return sum(duration_seconds(r, now) for r in rows if since is None or r.started_at >= since)

    edited = [r for r in rows if r.adjusted_seconds is not None]
    return {
        "week_seconds": total(week_start), "month_seconds": total(month_start), "all_time_seconds": total(None),
        "week": fmt_duration(total(week_start)), "month": fmt_duration(total(month_start)),
        "all_time": fmt_duration(total(None)), "shift_count": len(rows),
        "average": fmt_duration(total(None) // len(rows)) if rows else "0h 00m",
        "adjusted_shifts": len(edited),
        "adjustment_delta_seconds": sum(r.adjusted_seconds - elapsed_seconds(r, now) for r in edited),
        "active": shift_dict(next((r for r in rows if r.ended_at is None), None)) if any(r.ended_at is None for r in rows) else None,
    }


async def on_duty(s: AsyncSession) -> list[dict[str, Any]]:
    return await history(s, status="active", limit=500)


async def recover_active_shifts(s: AsyncSession) -> int:
    """Mark shifts that survived a restart. They keep running (time is not lost)."""
    res = await s.execute(update(Shift).where(Shift.ended_at.is_(None), Shift.recovered.is_(False)).values(recovered=True))
    return res.rowcount or 0
