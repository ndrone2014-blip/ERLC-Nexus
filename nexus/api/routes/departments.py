"""Departments, ranks, personnel and shifts."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import current_actor, db_session, require, require_any
from nexus.core.context import Actor, Forbidden
from nexus.services import departments, shifts
from nexus.services.departments import dept_dict, rank_dict

router = APIRouter(prefix="/api")


@router.get("/departments")
async def list_departments(include_archived: bool = False, actor: Actor = Depends(current_actor),
                           s: AsyncSession = Depends(db_session)):
    return [dept_dict(d, ranks=True) for d in await departments.list_departments(
        s, include_archived=include_archived and actor.can("cad.department.manage"))]


@router.post("/departments")
async def create_department(body: dict = Body(...), actor: Actor = Depends(require("cad.department.manage")),
                            s: AsyncSession = Depends(db_session)):
    d = await departments.save_department(s, actor, body)
    await s.commit()
    return dept_dict(await departments.get_department(s, d.id), ranks=True)


@router.get("/departments/{ref}")
async def get_department(ref: str, actor: Actor = Depends(require("dept.view")), s: AsyncSession = Depends(db_session)):
    d = await departments.get_department(s, ref)
    return {**dept_dict(d, ranks=True), "stats": await departments.department_stats(s, d.id)}


@router.patch("/departments/{dept_id}")
async def update_department(dept_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.department.manage")),
                            s: AsyncSession = Depends(db_session)):
    await departments.save_department(s, actor, body, dept_id)
    await s.commit()
    return dept_dict(await departments.get_department(s, dept_id), ranks=True)


@router.post("/departments/{dept_id}/archive")
async def archive_department(dept_id: int, body: dict = Body(default_factory=dict),
                             actor: Actor = Depends(require("cad.department.manage")), s: AsyncSession = Depends(db_session)):
    await departments.archive_department(s, actor, dept_id, bool(body.get("archived", True)))
    await s.commit()
    return {"ok": True}


@router.get("/departments/{dept_id}/stats")
async def department_stats(dept_id: int, days: int = 30, actor: Actor = Depends(require_any("dept.stats.view", "dept.view")),
                           s: AsyncSession = Depends(db_session)):
    return await departments.department_stats(s, dept_id, days=max(1, min(days, 365)))


@router.post("/departments/{dept_id}/ranks")
async def create_rank(dept_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                      s: AsyncSession = Depends(db_session)):
    r = await departments.save_rank(s, actor, dept_id, body)
    await s.commit()
    return rank_dict(r)


@router.patch("/departments/{dept_id}/ranks/{rank_id}")
async def update_rank(dept_id: int, rank_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                      s: AsyncSession = Depends(db_session)):
    r = await departments.save_rank(s, actor, dept_id, body, rank_id)
    await s.commit()
    return rank_dict(r)


@router.delete("/departments/{dept_id}/ranks/{rank_id}")
async def delete_rank(dept_id: int, rank_id: int, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    await departments.delete_rank(s, actor, dept_id, rank_id)
    await s.commit()
    return {"ok": True}


@router.post("/departments/{dept_id}/ranks/reorder")
async def reorder_ranks(dept_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                        s: AsyncSession = Depends(db_session)):
    await departments.reorder_ranks(s, actor, dept_id, [int(x) for x in body.get("rank_ids", [])])
    await s.commit()
    return {"ok": True}


@router.get("/departments/{dept_id}/roster")
async def roster(dept_id: int, include_removed: bool = False, actor: Actor = Depends(require("dept.view")),
                 s: AsyncSession = Depends(db_session)):
    return await departments.roster(s, dept_id, include_removed=include_removed)


@router.post("/departments/{dept_id}/members")
async def add_member(dept_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                     s: AsyncSession = Depends(db_session)):
    m = await departments.add_member(s, actor, dept_id, int(body.get("user_id", 0)), rank_id=body.get("rank_id"),
                                     callsign=str(body.get("callsign", "")))
    await s.commit()
    return {"id": m.id}


@router.patch("/memberships/{membership_id}")
async def update_member(membership_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                        s: AsyncSession = Depends(db_session)):
    m = await departments.update_member(s, actor, membership_id, body)
    await s.commit()
    return {"id": m.id, "status": m.status, "rank_id": m.rank_id, "callsign": m.callsign}


@router.get("/personnel/{user_id}")
async def personnel(user_id: int, actor: Actor = Depends(require("dept.view")), s: AsyncSession = Depends(db_session)):
    return await departments.personnel_profile(s, actor, user_id)


# ---- shifts ---------------------------------------------------------------------------

@router.get("/shifts")
async def shift_history(user_id: int | None = None, department_id: int | None = None, status: str = "",
                        since: datetime | None = None, limit: int = 100, actor: Actor = Depends(current_actor),
                        s: AsyncSession = Depends(db_session)):
    if user_id != actor.user_id and not (actor.can("shift.manage") or actor.can("dept.view")):
        user_id = actor.user_id
    return await shifts.history(s, user_id=user_id, department_id=department_id, status=status, since=since, limit=limit)


@router.get("/shifts/me")
async def my_shift(actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await shifts.stats(s, actor.user_id)


@router.get("/shifts/on-duty")
async def on_duty(actor: Actor = Depends(require_any("dept.view", "cad.view")), s: AsyncSession = Depends(db_session)):
    return await shifts.on_duty(s)


@router.get("/shifts/stats/{user_id}")
async def shift_stats(user_id: int, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    if user_id != actor.user_id and not (actor.can("shift.manage") or actor.can("dept.stats.view")):
        raise Forbidden("You can only view your own shift statistics.")
    return await shifts.stats(s, user_id)


@router.post("/shifts/start")
async def start_shift(body: dict = Body(default_factory=dict), actor: Actor = Depends(require("shift.self")),
                      s: AsyncSession = Depends(db_session)):
    sh = await shifts.start(s, actor, department_id=body.get("department_id"), callsign=str(body.get("callsign", "")),
                            unit_id=body.get("unit_id"), notes=str(body.get("notes", "")))
    await s.commit()
    return shifts.shift_dict(sh)


@router.post("/shifts/end")
async def end_shift(body: dict = Body(default_factory=dict), actor: Actor = Depends(current_actor),
                    s: AsyncSession = Depends(db_session)):
    sh = await shifts.end(s, actor, user_id=body.get("user_id"), notes=str(body.get("notes", "")))
    await s.commit()
    return shifts.shift_dict(sh)


@router.post("/shifts/{shift_id}/adjust")
async def adjust_shift(shift_id: int, body: dict = Body(...), actor: Actor = Depends(require("shift.manage")),
                       s: AsyncSession = Depends(db_session)):
    minutes = body.get("credited_minutes")
    sh = await shifts.adjust(s, actor, shift_id, credited_minutes=None if minutes in (None, "") else int(minutes),
                             reason=str(body.get("reason", "")))
    await s.commit()
    return shifts.shift_dict(sh)


@router.post("/shifts/{shift_id}/approve")
async def approve_shift(shift_id: int, body: dict = Body(default_factory=dict), actor: Actor = Depends(require("shift.manage")),
                        s: AsyncSession = Depends(db_session)):
    sh = await shifts.approve(s, actor, shift_id, bool(body.get("approved", True)))
    await s.commit()
    return shifts.shift_dict(sh)
