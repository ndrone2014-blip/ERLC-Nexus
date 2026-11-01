"""Overview dashboard, activity feed, notifications, bootstrap lookups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import current_actor, db_session, require_any
from nexus.core.context import Actor
from nexus.core.permissions import PERMISSIONS
from nexus.core.settings_store import get_many
from nexus.db.models import Bolo, Department, Report, Shift, TrafficStop
from nexus.services import activity, departments, erlc_ops, incidents, maps, notifications, units, users
from nexus.services.departments import dept_dict

router = APIRouter(prefix="/api")

PUBLIC_SETTINGS = [
    "community.name", "community.logo_url", "appearance.accent", "appearance.default_theme", "cad.priorities",
    "cad.incident_statuses", "cad.incident_categories", "cad.unit_statuses", "cad.unit_types", "cad.queue_alert_seconds",
    "map.location_categories", "map.marker_colors", "reports.templates", "records.disclaimer", "dashboard.widgets",
    "dashboard.refresh_seconds", "dispatch.shortcuts", "bolo.default_expiry_hours",
]


@router.get("/bootstrap")
async def bootstrap(request: Request, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    settings = await get_many(s, PUBLIC_SETTINGS)
    depts = [dept_dict(d, ranks=True) for d in await departments.list_departments(s)]
    return {"settings": settings, "departments": depts, "map": await maps.map_config(s),
            "permissions_catalog": {k: {"category": c, "description": d} for k, (c, d) in PERMISSIONS.items()},
            "notification_kinds": notifications.KINDS, "erlc_configured": rt.erlc.configured,
            "version": request.app.version}


@router.get("/overview")
async def overview(request: Request, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    out: dict[str, Any] = {"server": None, "cad": None, "units": None}
    if actor.can("erlc.server.view"):
        out["server"] = await erlc_ops.server_overview(s, rt.erlc)
    if actor.can("cad.view"):
        out["cad"] = await incidents.counts(s)
        out["units"] = await units.unit_counts(s)
        out["traffic_active"] = (await s.execute(select(func.count()).select_from(TrafficStop).where(
            TrafficStop.status == "active"))).scalar()
    if actor.can("cad.records.search"):
        out["bolos_active"] = (await s.execute(select(func.count()).select_from(Bolo).where(
            Bolo.status.in_(("active", "updated"))))).scalar()
    if actor.can("cad.reports.review"):
        out["reports_unreviewed"] = (await s.execute(select(func.count()).select_from(Report).where(
            Report.status.in_(("submitted", "under_review"))))).scalar()
    on_duty = (await s.execute(select(Shift).where(Shift.ended_at.is_(None)))).scalars().all()
    dispatch_ids = set((await s.execute(select(Department.id).where(Department.kind == "dispatch"))).scalars())
    out["on_shift"] = len(on_duty)
    out["dispatchers_on_shift"] = sum(1 for sh in on_duty if sh.department_id in dispatch_ids)
    out["sync"] = {"leader": getattr(request.app.state, "sync", None) and request.app.state.sync.is_leader,
                   "client": rt.erlc.status()}
    return out


@router.get("/activity")
async def activity_feed(before_id: int | None = None, limit: int = 40, actor: Actor = Depends(current_actor),
                        s: AsyncSession = Depends(db_session)):
    if not (actor.can("cad.view") or actor.can("dept.view") or actor.can("audit.view")):
        return []
    return await activity.feed(s, limit=limit, before_id=before_id)


@router.get("/notifications")
async def list_notifications(unread: bool = False, before_id: int | None = None, actor: Actor = Depends(current_actor),
                             s: AsyncSession = Depends(db_session)):
    items = await notifications.list_for(s, actor, unread_only=unread, before_id=before_id)
    unread_count = len(await notifications.list_for(s, actor, unread_only=True, limit=100))
    return {"items": items, "unread": unread_count}


@router.post("/notifications/read")
async def read_notifications(body: dict = Body(default_factory=dict), actor: Actor = Depends(current_actor),
                             s: AsyncSession = Depends(db_session)):
    n = await notifications.mark_read(s, actor, body.get("ids"))
    await s.commit()
    return {"marked": n}


@router.put("/me/preferences")
async def save_preferences(body: dict = Body(...), actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    allowed = {"dashboard_widgets", "dashboard_hidden", "default_page", "theme", "refresh_seconds", "shortcuts",
               "shortcuts_enabled", "muted_notifications", "cad_layout", "sound_alerts", "default_department_id"}
    prefs = {k: v for k, v in body.items() if k in allowed}
    user = await users.update_user(s, actor, actor.user_id, {"preferences": prefs})
    await s.commit()
    return user.preferences


@router.patch("/me")
async def update_me(body: dict = Body(...), actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    data = {k: v for k, v in body.items() if k in ("display_name", "roblox_username", "roblox_id")}
    user = await users.update_user(s, actor, actor.user_id, data)
    await s.commit()
    return users.user_summary(user)


@router.get("/users")
async def user_picker(q: str = "", limit: int = 25,
                      actor: Actor = Depends(require_any("dept.view", "cad.dispatch", "system.permissions")),
                      s: AsyncSession = Depends(db_session)):
    return [users.user_summary(u) for u in await users.search_users(s, q, limit=min(limit, 100))]
