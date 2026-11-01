"""CAD unit management."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.core.audit import audit
from nexus.core.context import Actor, Conflict, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import (
    Department,
    DepartmentMembership,
    Incident,
    IncidentAssignment,
    IncidentEvent,
    Location,
    Unit,
    UnitEvent,
    UnitMembership,
    User,
)
from nexus.services import lookups, notifications

CALLSIGN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-_/]{0,23}$")


def render_callsign(fmt: str, *, abbr: str = "", seq: int = 1, num: int | str = 1, unit_type: str = "") -> str:
    """Render a department callsign format. Placeholders: {abbr} {seq} {seq:02} {num} {type}."""
    out = fmt
    out = re.sub(r"\{seq:0(\d)\}", lambda m: str(seq).zfill(int(m.group(1))), out)
    out = re.sub(r"\{num:0(\d)\}", lambda m: str(num).zfill(int(m.group(1))), out)
    return (out.replace("{seq}", str(seq)).replace("{num}", str(num)).replace("{abbr}", abbr)
            .replace("{type}", (unit_type or "UNIT").upper()[:8]))


async def suggest_callsign(s: AsyncSession, department_id: int, unit_type: str = "", num: int | str = 1) -> str:
    dept = await s.get(Department, department_id)
    if dept is None:
        raise NotFound("Department not found.")
    taken = set((await s.execute(select(Unit.callsign).where(Unit.is_archived.is_(False)))).scalars())
    taken |= set(c for c in (await s.execute(select(DepartmentMembership.callsign))).scalars() if c)
    for seq in range(1, 1000):
        cs = render_callsign(dept.callsign_format, abbr=dept.abbreviation, seq=seq, num=num, unit_type=unit_type)
        if cs not in taken:
            return cs
    raise Conflict("No free callsign available for this format.")


def unit_dict(u: Unit, statuses: list[dict] | None = None, incident_number: str | None = None) -> dict[str, Any]:
    st = next((x for x in statuses or [] if x["key"] == u.status), None)
    return {
        "id": u.id, "callsign": u.callsign, "department_id": u.department_id,
        "department": u.department.abbreviation if u.department else None,
        "department_color": u.department.color if u.department else None,
        "unit_type": u.unit_type, "vehicle_description": u.vehicle_description,
        "status": u.status, "status_label": st["label"] if st else u.status, "status_color": st["color"] if st else "#64748b",
        "status_group": st["group"] if st else "unavailable",
        "current_incident_id": u.current_incident_id, "current_incident_number": incident_number,
        "location": {"text": u.location_text, "x": u.location_x, "z": u.location_z, "source": u.location_source,
                     "updated_at": u.location_updated_at},
        "dispatcher_user_id": u.dispatcher_user_id, "notes": u.notes, "is_archived": u.is_archived,
        "status_changed_at": u.status_changed_at, "created_at": u.created_at,
        "members": [{"user_id": m.user_id, "name": m.user.name if m.user else str(m.user_id), "is_primary": m.is_primary,
                     "roblox_linked": bool(m.user and m.user.roblox_id)} for m in (u.members or [])],
    }


def _unit_query():
    return select(Unit).options(selectinload(Unit.department), selectinload(Unit.members).selectinload(UnitMembership.user))


async def get_unit(s: AsyncSession, unit_id: int) -> Unit:
    u = (await s.execute(_unit_query().where(Unit.id == unit_id))).scalar_one_or_none()
    if u is None:
        raise NotFound("Unit not found.")
    return u


async def find_unit(s: AsyncSession, ref: str | int) -> Unit:
    if isinstance(ref, int) or str(ref).isdigit():
        try:
            return await get_unit(s, int(ref))
        except NotFound:
            pass
    u = (await s.execute(_unit_query().where(func.lower(Unit.callsign) == str(ref).lower().strip(),
                                             Unit.is_archived.is_(False)))).scalar_one_or_none()
    if u is None:
        raise NotFound(f"No active unit with callsign '{ref}'.")
    return u


async def serialize_units(s: AsyncSession, units: list[Unit]) -> list[dict[str, Any]]:
    statuses = await lookups.unit_statuses(s)
    inc_ids = [u.current_incident_id for u in units if u.current_incident_id]
    numbers = dict((await s.execute(select(Incident.id, Incident.number).where(Incident.id.in_(inc_ids)))).all()) if inc_ids else {}
    return [unit_dict(u, statuses, numbers.get(u.current_incident_id)) for u in units]


async def list_units(s: AsyncSession, *, department_id: int | None = None, status: str | None = None,
                     group: str | None = None, include_archived: bool = False) -> list[Unit]:
    stmt = _unit_query().order_by(Unit.department_id, Unit.callsign)
    if not include_archived:
        stmt = stmt.where(Unit.is_archived.is_(False))
    if department_id:
        stmt = stmt.where(Unit.department_id == department_id)
    if status:
        stmt = stmt.where(Unit.status == status)
    units = list((await s.execute(stmt)).scalars())
    if group:
        statuses = {x["key"]: x["group"] for x in await lookups.unit_statuses(s)}
        units = [u for u in units if statuses.get(u.status) == group]
    return units


async def _log(s: AsyncSession, unit: Unit, actor: Actor, event: str, old: Any = None, new: Any = None,
               incident_id: int | None = None) -> None:
    s.add(UnitEvent(unit_id=unit.id, event_type=event, old_value=None if old is None else str(old)[:160],
                    new_value=None if new is None else str(new)[:160], incident_id=incident_id, user_id=actor.user_id))


async def is_member(s: AsyncSession, unit_id: int, user_id: int | None) -> bool:
    if not user_id:
        return False
    return bool((await s.execute(select(UnitMembership.id).where(
        UnitMembership.unit_id == unit_id, UnitMembership.user_id == user_id, UnitMembership.left_at.is_(None)
    ))).scalar())


async def _require_unit_control(s: AsyncSession, actor: Actor, unit: Unit) -> None:
    if actor.can("cad.unit.manage") or actor.can("cad.dispatch"):
        return
    if actor.can("cad.unit.self") and await is_member(s, unit.id, actor.user_id):
        return
    raise Forbidden("You can only update units you belong to.")


async def register_unit(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Unit:
    dept_id = data.get("department_id")
    dept = await s.get(Department, dept_id) if dept_id else None
    if dept is None or dept.is_archived:
        raise ValidationFailed("Choose a valid department.")
    self_register = not actor.can("cad.unit.manage")
    if self_register:
        actor.require("cad.unit.self")
        if dept.id not in actor.department_ids:
            raise Forbidden("You can only register units in your own department.")
    callsign = (data.get("callsign") or "").strip()
    unit_type = (data.get("unit_type") or (dept.unit_types[0] if dept.unit_types else "General")).strip()
    if not callsign:
        callsign = await suggest_callsign(s, dept.id, unit_type)
    if not CALLSIGN_RE.match(callsign):
        raise ValidationFailed("Callsigns may contain letters, numbers, spaces, '-', '_' or '/' (max 24 chars).")
    dup = (await s.execute(select(Unit.id).where(func.lower(Unit.callsign) == callsign.lower(),
                                                 Unit.is_archived.is_(False)))).scalar()
    if dup:
        raise Conflict(f"An active unit with callsign {callsign} already exists.")
    unit = Unit(callsign=callsign, department_id=dept.id, unit_type=unit_type[:32],
                vehicle_description=(data.get("vehicle_description") or "")[:160], notes=data.get("notes") or "",
                status=data.get("status") or ("available" if self_register else "out_of_service"))
    await lookups.unit_status(s, unit.status)
    s.add(unit)
    await s.flush()
    member_ids = list(dict.fromkeys(int(x) for x in data.get("member_ids") or []))
    if self_register and actor.user_id and actor.user_id not in member_ids:
        member_ids.insert(0, actor.user_id)
    for i, uid in enumerate(member_ids):
        if await s.get(User, uid) is None:
            raise ValidationFailed(f"User {uid} does not exist.")
        await _leave_other_units(s, uid, actor)
        s.add(UnitMembership(unit_id=unit.id, user_id=uid, is_primary=i == 0))
    await _log(s, unit, actor, "registered", new=callsign)
    await audit(s, actor, "cad", "unit.registered", target_type="unit", target_id=unit.id, target_ref=callsign,
                department_id=dept.id, new={"callsign": callsign, "type": unit_type, "members": member_ids})
    emit(s, "unit.changed", {"id": unit.id, "callsign": callsign}, origin=actor.source)
    return unit


async def _leave_other_units(s: AsyncSession, user_id: int, actor: Actor) -> None:
    rows = (await s.execute(select(UnitMembership).where(UnitMembership.user_id == user_id,
                                                         UnitMembership.left_at.is_(None)))).scalars().all()
    for m in rows:
        m.left_at = utcnow()
        unit = await s.get(Unit, m.unit_id)
        if unit:
            await _log(s, unit, actor, "member_left", old=user_id)


async def update_unit(s: AsyncSession, actor: Actor, unit_id: int, data: dict[str, Any]) -> Unit:
    unit = await get_unit(s, unit_id)
    if not actor.can("cad.unit.manage"):
        await _require_unit_control(s, actor, unit)
        data = {k: v for k, v in data.items() if k in ("vehicle_description", "notes")}
    before = {"callsign": unit.callsign, "unit_type": unit.unit_type, "vehicle_description": unit.vehicle_description,
              "notes": unit.notes, "department_id": unit.department_id}
    if "callsign" in data and data["callsign"] and data["callsign"] != unit.callsign:
        cs = data["callsign"].strip()
        if not CALLSIGN_RE.match(cs):
            raise ValidationFailed("Invalid callsign.")
        dup = (await s.execute(select(Unit.id).where(func.lower(Unit.callsign) == cs.lower(), Unit.id != unit.id,
                                                     Unit.is_archived.is_(False)))).scalar()
        if dup:
            raise Conflict(f"Callsign {cs} is already in use.")
        await _log(s, unit, actor, "callsign_changed", unit.callsign, cs)
        unit.callsign = cs
    if "department_id" in data and data["department_id"] != unit.department_id:
        if await s.get(Department, data["department_id"]) is None:
            raise ValidationFailed("Department not found.")
        unit.department_id = data["department_id"]
    for f in ("unit_type", "vehicle_description", "notes"):
        if f in data and data[f] is not None:
            setattr(unit, f, str(data[f]))
    after = {"callsign": unit.callsign, "unit_type": unit.unit_type, "vehicle_description": unit.vehicle_description,
             "notes": unit.notes, "department_id": unit.department_id}
    if before != after:
        await _log(s, unit, actor, "edited")
        await audit(s, actor, "cad", "unit.updated", target_type="unit", target_id=unit.id, target_ref=unit.callsign,
                    department_id=unit.department_id, old=before, new=after)
        emit(s, "unit.changed", {"id": unit.id}, origin=actor.source)
    return unit


async def archive_unit(s: AsyncSession, actor: Actor, unit_id: int) -> Unit:
    actor.require("cad.unit.manage")
    unit = await get_unit(s, unit_id)
    if unit.current_incident_id:
        await clear_from_incident(s, actor, unit, reason="unit removed")
    for m in unit.members:
        m.left_at = utcnow()
    unit.is_archived = True
    unit.status = "out_of_service"
    await _log(s, unit, actor, "removed")
    await audit(s, actor, "cad", "unit.removed", target_type="unit", target_id=unit.id, target_ref=unit.callsign,
                department_id=unit.department_id)
    emit(s, "unit.changed", {"id": unit.id, "archived": True}, origin=actor.source)
    return unit


async def add_member(s: AsyncSession, actor: Actor, unit_id: int, user_id: int, primary: bool = False) -> None:
    unit = await get_unit(s, unit_id)
    if not (actor.can("cad.unit.manage") or actor.can("cad.dispatch")):
        await _require_unit_control(s, actor, unit)
    if await s.get(User, user_id) is None:
        raise NotFound("User not found.")
    if await is_member(s, unit.id, user_id):
        raise Conflict("That person is already assigned to this unit.")
    await _leave_other_units(s, user_id, actor)
    if primary:
        for m in unit.members:
            m.is_primary = False
    s.add(UnitMembership(unit_id=unit.id, user_id=user_id, is_primary=primary or not unit.members))
    await _log(s, unit, actor, "member_added", new=user_id)
    await audit(s, actor, "cad", "unit.member_added", target_type="unit", target_id=unit.id, target_ref=unit.callsign,
                new={"user_id": user_id})
    emit(s, "unit.changed", {"id": unit.id}, origin=actor.source)


async def remove_member(s: AsyncSession, actor: Actor, unit_id: int, user_id: int) -> None:
    unit = await get_unit(s, unit_id)
    if actor.user_id != user_id and not (actor.can("cad.unit.manage") or actor.can("cad.dispatch")):
        raise Forbidden("You cannot remove other members from this unit.")
    m = (await s.execute(select(UnitMembership).where(UnitMembership.unit_id == unit.id, UnitMembership.user_id == user_id,
                                                      UnitMembership.left_at.is_(None)))).scalar_one_or_none()
    if m is None:
        raise NotFound("That person is not on this unit.")
    m.left_at = utcnow()
    await _log(s, unit, actor, "member_removed", old=user_id)
    await audit(s, actor, "cad", "unit.member_removed", target_type="unit", target_id=unit.id, target_ref=unit.callsign,
                old={"user_id": user_id})
    emit(s, "unit.changed", {"id": unit.id}, origin=actor.source)


async def clear_from_incident(s: AsyncSession, actor: Actor, unit: Unit, *, reason: str = "") -> None:
    if not unit.current_incident_id:
        return
    inc_id = unit.current_incident_id
    asg = (await s.execute(select(IncidentAssignment).where(IncidentAssignment.incident_id == inc_id,
                                                            IncidentAssignment.unit_id == unit.id,
                                                            IncidentAssignment.cleared_at.is_(None)))).scalars().all()
    for a in asg:
        a.cleared_at = utcnow()
    s.add(IncidentEvent(incident_id=inc_id, event_type="unit_removed", message=f"{unit.callsign} cleared" +
                        (f" ({reason})" if reason else ""), old_value=unit.callsign, user_id=actor.user_id, unit_id=unit.id))
    await _log(s, unit, actor, "cleared", incident_id=inc_id)
    unit.current_incident_id = None
    emit(s, "incident.changed", {"id": inc_id}, origin=actor.source)


async def set_status(s: AsyncSession, actor: Actor, unit_id: int, status: str, *, note: str = "") -> Unit:
    unit = await get_unit(s, unit_id)
    await _require_unit_control(s, actor, unit)
    st = await lookups.unit_status(s, status)
    old = unit.status
    if old == status:
        return unit
    unit.status = status
    unit.status_changed_at = utcnow()
    await _log(s, unit, actor, "status", old, status, incident_id=unit.current_incident_id)
    if unit.current_incident_id:
        inc = await s.get(Incident, unit.current_incident_id)
        if inc:
            s.add(IncidentEvent(incident_id=inc.id, event_type="unit_status", message=f"{unit.callsign} → {st['label']}",
                                old_value=old, new_value=status, user_id=actor.user_id, unit_id=unit.id))
            if status == "on_scene":
                inc.on_scene_at = inc.on_scene_at or utcnow()
                if inc.status in ("new", "pending", "dispatched", "en_route"):
                    s.add(IncidentEvent(incident_id=inc.id, event_type="status_changed", old_value=inc.status,
                                        new_value="on_scene", message="Status → On Scene (unit arrived)", user_id=actor.user_id))
                    inc.status = "on_scene"
            elif status == "en_route" and inc.status in ("new", "pending", "dispatched"):
                s.add(IncidentEvent(incident_id=inc.id, event_type="status_changed", old_value=inc.status,
                                    new_value="en_route", message="Status → Units En Route", user_id=actor.user_id))
                inc.status = "en_route"
            if st["group"] in ("available", "unavailable"):
                await clear_from_incident(s, actor, unit, reason=f"status {st['label']}")
            emit(s, "incident.changed", {"id": inc.id}, origin=actor.source)
    await audit(s, actor, "cad", "unit.status", target_type="unit", target_id=unit.id, target_ref=unit.callsign,
                department_id=unit.department_id, old=old, new=status, context={"note": note} if note else None)
    emit(s, "unit.status", {"id": unit.id, "callsign": unit.callsign, "status": status, "label": st["label"],
                            "old": old, "department_id": unit.department_id}, origin=actor.source)
    await notifications.notify(s, "unit.status", f"{unit.callsign} is {st['label']}", note,
                               audience="perm:cad.dispatch", department_id=None, link="/#/cad/units",
                               dedupe_key=f"unit.status:{unit.id}")
    return unit


async def set_location(s: AsyncSession, actor: Actor, unit_id: int, *, text: str = "", x: float | None = None,
                       z: float | None = None, location_id: int | None = None) -> Unit:
    unit = await get_unit(s, unit_id)
    await _require_unit_control(s, actor, unit)
    source = "manual"
    if location_id:
        loc = await s.get(Location, location_id)
        if loc is None or loc.is_archived:
            raise NotFound("Location preset not found.")
        text, x, z, source = text or loc.name, loc.x, loc.z, "preset"
    if not text and x is None:
        raise ValidationFailed("Provide a location description, map position or preset.")
    old = unit.location_text
    unit.location_text = (text or "")[:160]
    unit.location_x, unit.location_z = x, z
    unit.location_source = source
    unit.location_updated_at = utcnow()
    await _log(s, unit, actor, "location", old, unit.location_text)
    emit(s, "unit.changed", {"id": unit.id, "location": True}, origin=actor.source)
    return unit


async def my_units(s: AsyncSession, actor: Actor) -> list[Unit]:
    if not actor.user_id:
        return []
    return list((await s.execute(
        _unit_query().join(UnitMembership, UnitMembership.unit_id == Unit.id)
        .where(UnitMembership.user_id == actor.user_id, UnitMembership.left_at.is_(None), Unit.is_archived.is_(False))
    )).scalars().unique())


async def unit_history(s: AsyncSession, unit_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await s.execute(
        select(UnitEvent, User.display_name, Incident.number)
        .outerjoin(User, User.id == UnitEvent.user_id).outerjoin(Incident, Incident.id == UnitEvent.incident_id)
        .where(UnitEvent.unit_id == unit_id).order_by(UnitEvent.id.desc()).limit(limit)
    )).all()
    return [{"id": e.id, "event": e.event_type, "old": e.old_value, "new": e.new_value, "incident": num,
             "user": name, "created_at": e.created_at} for e, name, num in rows]


async def unit_counts(s: AsyncSession) -> dict[str, int]:
    groups = {x["key"]: x["group"] for x in await lookups.unit_statuses(s)}
    rows = (await s.execute(select(Unit.status, func.count()).where(Unit.is_archived.is_(False)).group_by(Unit.status))).all()
    out = {"available": 0, "busy": 0, "unavailable": 0, "total": 0}
    for status, n in rows:
        out[groups.get(status, "unavailable")] += n
        out["total"] += n
    return out


async def auto_status_on_assign(s: AsyncSession) -> bool:
    return bool(await get_setting(s, "cad.auto_status_on_assign"))
