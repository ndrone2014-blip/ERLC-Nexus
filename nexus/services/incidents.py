"""CAD incident management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.core.audit import audit
from nexus.core.context import Actor, Conflict, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.numbering import next_number
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import (
    Department,
    ErlcEmergencyCall,
    Incident,
    IncidentAssignment,
    IncidentEvent,
    IncidentNote,
    Location,
    RecordLink,
    UnitEvent,
    UnitMembership,
    User,
)
from nexus.services import lookups, notifications, units as unit_svc

EDITABLE = [
    "category", "subtype", "caller_name", "caller_identifier", "caller_contact", "caller_description", "caller_notes",
    "location_name", "street", "intersection", "postal", "map_x", "map_z", "location_instructions", "location_id",
    "description", "circumstances", "details", "department_id", "supervisor_user_id",
]
CLOSED_STATUSES = ("resolved", "closed", "cancelled")
LINK_TYPES = ("person", "vehicle", "bolo", "warrant", "case", "traffic", "report", "incident")
MAX_LEN = {"description": 4000, "circumstances": 4000, "details": 4000, "caller_notes": 2000}


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k in EDITABLE:
        if k not in data:
            continue
        v = data[k]
        if isinstance(v, str):
            v = v.strip()[: MAX_LEN.get(k, 300)]
        if k in ("map_x", "map_z") and v not in (None, ""):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValidationFailed(f"{k} must be a number.")
        if k in ("map_x", "map_z", "department_id", "location_id", "supervisor_user_id") and v == "":
            v = None
        out[k] = v
    return out


def _event(s: AsyncSession, inc: Incident, actor: Actor, event: str, message: str = "", old: Any = None, new: Any = None,
           unit_id: int | None = None) -> None:
    s.add(IncidentEvent(incident_id=inc.id, event_type=event, message=message[:500], user_id=actor.user_id,
                        old_value=None if old is None else str(old)[:300], new_value=None if new is None else str(new)[:300],
                        unit_id=unit_id))


async def get(s: AsyncSession, ref: int | str) -> Incident:
    stmt = select(Incident).options(selectinload(Incident.department),
                                    selectinload(Incident.assignments).selectinload(IncidentAssignment.unit))
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        inc = (await s.execute(stmt.where(Incident.id == int(ref)))).scalar_one_or_none()
    else:
        inc = (await s.execute(stmt.where(func.upper(Incident.number) == str(ref).strip().upper()))).scalar_one_or_none()
    if inc is None:
        raise NotFound(f"Incident {ref} not found.")
    return inc


async def summary_dict(s: AsyncSession, inc: Incident, *, prios=None, statuses=None, cats=None) -> dict[str, Any]:
    prios = prios or await lookups.priorities(s)
    statuses = statuses or await lookups.incident_statuses(s)
    cats = cats or await lookups.categories(s)
    p = next((x for x in prios if x["level"] == inc.priority), None)
    st = next((x for x in statuses if x["key"] == inc.status), None)
    active = [a for a in inc.assignments if a.cleared_at is None]
    return {
        "id": inc.id, "number": inc.number, "category": inc.category,
        "category_label": lookups.label(cats, inc.category), "subtype": inc.subtype,
        "priority": inc.priority, "priority_name": p["name"] if p else str(inc.priority),
        "priority_color": p["color"] if p else "#64748b",
        "status": inc.status, "status_label": st["label"] if st else inc.status, "status_color": st["color"] if st else "#64748b",
        "is_open": bool(st and st.get("open")),
        "location": inc.location_name or inc.street or inc.intersection or "", "street": inc.street,
        "intersection": inc.intersection, "postal": inc.postal, "map_x": inc.map_x, "map_z": inc.map_z,
        "description": inc.description, "department_id": inc.department_id,
        "department": inc.department.abbreviation if inc.department else None,
        "caller_name": inc.caller_name, "source": inc.source, "source_ref": inc.source_ref,
        "units": [{"id": a.unit.id, "callsign": a.unit.callsign, "status": a.unit.status, "is_primary": a.is_primary}
                  for a in active if a.unit],
        "created_at": inc.created_at, "updated_at": inc.updated_at, "dispatched_at": inc.dispatched_at,
        "on_scene_at": inc.on_scene_at, "closed_at": inc.closed_at,
        "waiting_seconds": int(((inc.dispatched_at or utcnow()) - inc.created_at).total_seconds()),
    }


async def detail_dict(s: AsyncSession, actor: Actor, inc: Incident) -> dict[str, Any]:
    d = await summary_dict(s, inc)
    d.update({k: getattr(inc, k) for k in EDITABLE})
    d.update({"disposition": inc.disposition, "dispatcher_user_id": inc.dispatcher_user_id,
              "created_by_user_id": inc.created_by_user_id, "resolved_at": inc.resolved_at})
    names = {}
    uid_set = {inc.dispatcher_user_id, inc.supervisor_user_id, inc.created_by_user_id} - {None}
    events = (await s.execute(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)
                              .order_by(IncidentEvent.id))).scalars().all()
    notes_stmt = select(IncidentNote).where(IncidentNote.incident_id == inc.id).order_by(IncidentNote.id)
    if not actor.can("cad.incident.restricted"):
        notes_stmt = notes_stmt.where(IncidentNote.is_restricted.is_(False))
    notes = (await s.execute(notes_stmt)).scalars().all()
    uid_set |= {e.user_id for e in events if e.user_id} | {n.user_id for n in notes if n.user_id}
    if uid_set:
        names = dict((await s.execute(select(User.id, User.display_name).where(User.id.in_(uid_set)))).all())
    d["dispatcher"] = names.get(inc.dispatcher_user_id)
    d["supervisor"] = names.get(inc.supervisor_user_id)
    d["created_by"] = names.get(inc.created_by_user_id)
    d["timeline"] = [{"id": e.id, "event": e.event_type, "message": e.message, "old": e.old_value, "new": e.new_value,
                      "user": names.get(e.user_id, "System" if e.user_id is None else str(e.user_id)),
                      "created_at": e.created_at} for e in events]
    d["notes"] = [{"id": n.id, "body": n.body, "restricted": n.is_restricted, "user": names.get(n.user_id),
                   "created_at": n.created_at} for n in notes]
    d["assignment_history"] = [{"unit_id": a.unit_id, "callsign": a.unit.callsign if a.unit else None,
                                "assigned_at": a.assigned_at, "cleared_at": a.cleared_at, "is_primary": a.is_primary}
                               for a in inc.assignments]
    d["links"] = await linked_records(s, "incident", inc.id)
    return d


async def linked_records(s: AsyncSession, source_type: str, source_id: int) -> list[dict[str, Any]]:
    from nexus.services import records

    rows = (await s.execute(select(RecordLink).where(
        or_((RecordLink.source_type == source_type) & (RecordLink.source_id == source_id),
            (RecordLink.target_type == source_type) & (RecordLink.target_id == source_id))
    ))).scalars().all()
    out = []
    for r in rows:
        t, i = (r.target_type, r.target_id) if (r.source_type, r.source_id) == (source_type, source_id) else (r.source_type, r.source_id)
        label = await records.record_label(s, t, i)
        if label:
            out.append({"link_id": r.id, "type": t, "id": i, "label": label, "note": r.note})
    return out


async def create(s: AsyncSession, actor: Actor, data: dict[str, Any], *, source: str = "web",
                 source_ref: str | None = None) -> Incident:
    actor.require("cad.incident.create")
    fields = _clean(data)
    category = fields.get("category") or "other"
    await lookups.category(s, category)
    try:
        priority = int(data.get("priority") or 3)
    except (TypeError, ValueError):
        raise ValidationFailed("Priority must be a number.")
    pr = await lookups.priority(s, priority)
    status = data.get("status") or "new"
    st = await lookups.incident_status(s, status)
    if not st.get("open"):
        raise ValidationFailed("New incidents must start in an open status.")
    if not (fields.get("description") or fields.get("location_name") or fields.get("street")):
        raise ValidationFailed("Provide at least a description or a location.")
    if fields.get("department_id") and await s.get(Department, fields["department_id"]) is None:
        raise ValidationFailed("Department not found.")
    if fields.get("location_id"):
        loc = await s.get(Location, fields["location_id"])
        if loc is None:
            raise ValidationFailed("Location not found.")
        fields.setdefault("location_name", loc.name)
        if fields.get("map_x") is None:
            fields["map_x"], fields["map_z"] = loc.x, loc.z
        fields.setdefault("postal", loc.postal)
    prefix = await get_setting(s, "cad.incident_prefix") or "NX"
    inc = Incident(number=await next_number(s, "incident", prefix), priority=priority, status=status,
                   created_by_user_id=actor.user_id, source=source, source_ref=source_ref, **{**fields, "category": category})
    if actor.can("cad.dispatch") and source != "erlc_api":
        inc.dispatcher_user_id = actor.user_id
    s.add(inc)
    await s.flush()
    _event(s, inc, actor, "created", f"Incident created ({pr['name']}) via {source}", new=status)
    for link in data.get("links") or []:
        await link_record(s, actor, inc.id, link.get("type"), int(link.get("id")), _audit=False)
    await audit(s, actor, "cad", "incident.created", target_type="incident", target_id=inc.id, target_ref=inc.number,
                department_id=inc.department_id, new={"priority": priority, "category": category, "status": status,
                                                      "location": inc.location_name or inc.street})
    emit(s, "incident.created", {"id": inc.id, "number": inc.number, "priority": priority, "category": category,
                                 "location": inc.location_name or inc.street, "description": (inc.description or "")[:200],
                                 "department_id": inc.department_id}, origin=actor.source)
    if pr.get("notify"):
        await notifications.notify(s, "incident.created", f"{pr['name']}: {inc.number}",
                                   f"{lookups.label(await lookups.categories(s), category)} at "
                                   f"{inc.location_name or inc.street or 'unknown location'}",
                                   audience="perm:cad.view", department_id=inc.department_id,
                                   link=f"/#/cad/incident/{inc.id}", severity="danger" if priority == 1 else "warning")
    return inc


async def create_911(s: AsyncSession, actor: Actor, data: dict[str, Any], *, source: str = "web") -> Incident:
    """911 calls from civilians/anyone with cad.911.create. Created as Pending Dispatch."""
    actor.require("cad.911.create")
    desc = (data.get("description") or "").strip()
    loc = (data.get("location_name") or data.get("location") or "").strip()
    if not desc or not loc:
        raise ValidationFailed("A 911 call needs a location and a description of the emergency.")
    payload = {
        "category": data.get("category") or "other", "priority": int(data.get("priority") or 2), "status": "pending",
        "caller_name": (data.get("caller_name") or actor.name)[:100], "caller_identifier": actor.discord_id or "",
        "caller_contact": data.get("caller_contact") or "", "location_name": loc, "description": desc,
        "street": data.get("street") or "", "postal": data.get("postal") or "",
        "map_x": data.get("map_x"), "map_z": data.get("map_z"),
    }
    elevated = Actor(**{**actor.__dict__, "permissions": frozenset(actor.permissions | {"cad.incident.create"})})
    inc = await create(s, elevated, payload, source=source)
    _event(s, inc, actor, "note", "Received as a 911 call")
    await notifications.notify(s, "incident.created", f"911 call: {inc.number}", f"{desc[:200]} — {loc}",
                               audience="perm:cad.dispatch", link=f"/#/cad/incident/{inc.id}", severity="danger")
    return inc


async def update(s: AsyncSession, actor: Actor, inc_id: int, data: dict[str, Any]) -> Incident:
    actor.require("cad.incident.edit")
    inc = await get(s, inc_id)
    fields = _clean(data)
    if "category" in fields:
        await lookups.category(s, fields["category"])
    changes_old, changes_new = {}, {}
    for k, v in fields.items():
        if getattr(inc, k) != v:
            changes_old[k], changes_new[k] = getattr(inc, k), v
            setattr(inc, k, v)
    if "priority" in data and data["priority"] is not None and int(data["priority"]) != inc.priority:
        await change_priority(s, actor, inc, int(data["priority"]))
    if "status" in data and data["status"] and data["status"] != inc.status:
        await change_status(s, actor, inc.id, data["status"], disposition=data.get("disposition", ""))
    if changes_new:
        _event(s, inc, actor, "edited", "Updated " + ", ".join(sorted(changes_new)),
               old=", ".join(f"{k}={changes_old[k]}" for k in sorted(changes_old))[:300],
               new=", ".join(f"{k}={changes_new[k]}" for k in sorted(changes_new))[:300])
        await audit(s, actor, "cad", "incident.updated", target_type="incident", target_id=inc.id, target_ref=inc.number,
                    department_id=inc.department_id, old=changes_old, new=changes_new)
        emit(s, "incident.changed", {"id": inc.id, "number": inc.number}, origin=actor.source)
    return inc


async def change_priority(s: AsyncSession, actor: Actor, inc: Incident, level: int) -> None:
    actor.require("cad.incident.edit")
    pr = await lookups.priority(s, level)
    old = inc.priority
    if old == level:
        return
    inc.priority = level
    _event(s, inc, actor, "priority_changed", f"Priority → {pr['name']}", old, level)
    await audit(s, actor, "cad", "incident.priority", target_type="incident", target_id=inc.id, target_ref=inc.number,
                old=old, new=level)
    emit(s, "incident.changed", {"id": inc.id, "number": inc.number, "priority": level}, origin=actor.source)
    if pr.get("notify") and level < old:
        await notifications.notify(s, "incident.priority", f"{inc.number} upgraded to {pr['name']}", inc.description[:200],
                                   audience="perm:cad.view", link=f"/#/cad/incident/{inc.id}", severity="warning",
                                   dedupe_key=f"prio:{inc.id}")


async def change_status(s: AsyncSession, actor: Actor, inc_id: int, status: str, *, disposition: str = "") -> Incident:
    inc = await get(s, inc_id)
    st = await lookups.incident_status(s, status)
    old = inc.status
    if old == status:
        return inc
    old_st = next((x for x in await lookups.incident_statuses(s) if x["key"] == old), {"open": True})
    closing = not st.get("open")
    reopening = closing is False and not old_st.get("open")
    if closing or reopening:
        actor.require("cad.incident.close")
    elif not actor.can("cad.incident.edit"):
        # assigned units may advance status of their own incident
        mine = [u.id for u in await unit_svc.my_units(s, actor)]
        if not any(a.unit_id in mine and a.cleared_at is None for a in inc.assignments):
            raise Forbidden("You can only update incidents your unit is assigned to.")
    inc.status = status
    now = utcnow()
    if status == "dispatched":
        inc.dispatched_at = inc.dispatched_at or now
    if status == "on_scene":
        inc.on_scene_at = inc.on_scene_at or now
    if status == "resolved":
        inc.resolved_at = now
    if closing:
        inc.closed_at = now
        if disposition:
            inc.disposition = disposition.strip()[:200]
        for a in list(inc.assignments):
            if a.cleared_at is None and a.unit:
                unit = a.unit
                await unit_svc.clear_from_incident(s, actor, unit, reason=f"incident {st['label'].lower()}")
                if await unit_svc.auto_status_on_assign(s) and unit.status not in ("out_of_service", "on_break"):
                    unit.status = "available"
                    unit.status_changed_at = now
                    emit(s, "unit.status", {"id": unit.id, "callsign": unit.callsign, "status": "available"},
                         origin=actor.source)
    if reopening:
        inc.closed_at = None
        inc.resolved_at = None
    event = "reopened" if reopening else ("closed" if status == "closed" else "resolved" if status == "resolved"
                                          else "cancelled" if status == "cancelled" else "status_changed")
    _event(s, inc, actor, event, f"Status → {st['label']}" + (f" ({disposition})" if disposition else ""), old, status)
    await audit(s, actor, "cad", f"incident.{event}", target_type="incident", target_id=inc.id, target_ref=inc.number,
                department_id=inc.department_id, old=old, new=status, context={"disposition": disposition} if disposition else None)
    emit(s, "incident.changed", {"id": inc.id, "number": inc.number, "status": status}, origin=actor.source)
    if closing:
        emit(s, "incident.closed", {"id": inc.id, "number": inc.number, "status": status,
                                    "disposition": inc.disposition}, origin=actor.source)
    return inc


async def assign_unit(s: AsyncSession, actor: Actor, inc_id: int, unit_ref: int | str, *, primary: bool = False) -> Incident:
    inc = await get(s, inc_id)
    unit = await unit_svc.find_unit(s, unit_ref)
    if not actor.can("cad.dispatch"):
        if not (actor.can("cad.unit.self") and await unit_svc.is_member(s, unit.id, actor.user_id)):
            raise Forbidden("Only dispatchers can assign other units.")
    st = next((x for x in await lookups.incident_statuses(s) if x["key"] == inc.status), None)
    if st and not st.get("open"):
        raise ValidationFailed(f"{inc.number} is closed. Reopen it before assigning units.")
    if any(a.unit_id == unit.id and a.cleared_at is None for a in inc.assignments):
        raise Conflict(f"{unit.callsign} is already assigned to {inc.number}.")
    if unit.current_incident_id and unit.current_incident_id != inc.id:
        await unit_svc.clear_from_incident(s, actor, unit, reason=f"reassigned to {inc.number}")
    has_primary = any(a.is_primary and a.cleared_at is None for a in inc.assignments)
    a = IncidentAssignment(incident_id=inc.id, unit_id=unit.id, assigned_by=actor.user_id,
                           is_primary=primary or not has_primary)
    s.add(a)
    unit.current_incident_id = inc.id
    if actor.can("cad.dispatch"):
        unit.dispatcher_user_id = actor.user_id
        inc.dispatcher_user_id = inc.dispatcher_user_id or actor.user_id
    _event(s, inc, actor, "unit_assigned", f"{unit.callsign} assigned" + (" (primary)" if a.is_primary else ""),
           new=unit.callsign, unit_id=unit.id)
    s.add(UnitEvent(unit_id=unit.id, event_type="assigned", new_value=inc.number, incident_id=inc.id,
                    user_id=actor.user_id))
    if inc.status in ("new", "pending"):
        old = inc.status
        inc.status = "dispatched"
        inc.dispatched_at = inc.dispatched_at or utcnow()
        _event(s, inc, actor, "status_changed", "Status → Dispatched", old, "dispatched")
    if await unit_svc.auto_status_on_assign(s) and unit.status in ("available", "returning", "busy"):
        old_status = unit.status
        unit.status = "en_route"
        unit.status_changed_at = utcnow()
        emit(s, "unit.status", {"id": unit.id, "callsign": unit.callsign, "status": "en_route", "old": old_status},
             origin=actor.source)
    await s.flush()
    await audit(s, actor, "cad", "incident.unit_assigned", target_type="incident", target_id=inc.id, target_ref=inc.number,
                department_id=inc.department_id, new={"unit": unit.callsign})
    emit(s, "unit.assigned", {"incident_id": inc.id, "number": inc.number, "unit_id": unit.id, "callsign": unit.callsign,
                              "priority": inc.priority, "location": inc.location_name or inc.street,
                              "description": (inc.description or "")[:200]}, origin=actor.source)
    emit(s, "incident.changed", {"id": inc.id, "number": inc.number}, origin=actor.source)
    member_ids = (await s.execute(select(UnitMembership.user_id).where(UnitMembership.unit_id == unit.id,
                                                                       UnitMembership.left_at.is_(None)))).scalars().all()
    for uid in member_ids:
        if uid != actor.user_id:
            await notifications.notify(s, "unit.assigned", f"{unit.callsign} assigned to {inc.number}",
                                       f"{inc.location_name or inc.street}: {(inc.description or '')[:150]}",
                                       user_id=uid, link=f"/#/mdt/call/{inc.id}", severity="warning")
    return inc


async def clear_unit(s: AsyncSession, actor: Actor, inc_id: int, unit_ref: int | str) -> Incident:
    inc = await get(s, inc_id)
    unit = await unit_svc.find_unit(s, unit_ref)
    if not actor.can("cad.dispatch"):
        if not (actor.can("cad.unit.self") and await unit_svc.is_member(s, unit.id, actor.user_id)):
            raise Forbidden("Only dispatchers can clear other units.")
    if unit.current_incident_id != inc.id:
        active = [a for a in inc.assignments if a.unit_id == unit.id and a.cleared_at is None]
        if not active:
            raise NotFound(f"{unit.callsign} is not assigned to {inc.number}.")
        for a in active:
            a.cleared_at = utcnow()
        _event(s, inc, actor, "unit_removed", f"{unit.callsign} cleared", old=unit.callsign, unit_id=unit.id)
    else:
        await unit_svc.clear_from_incident(s, actor, unit)
    if await unit_svc.auto_status_on_assign(s) and unit.status not in ("out_of_service", "on_break", "available"):
        unit.status = "available"
        unit.status_changed_at = utcnow()
        emit(s, "unit.status", {"id": unit.id, "callsign": unit.callsign, "status": "available"}, origin=actor.source)
    await audit(s, actor, "cad", "incident.unit_cleared", target_type="incident", target_id=inc.id, target_ref=inc.number,
                old={"unit": unit.callsign})
    emit(s, "incident.changed", {"id": inc.id, "number": inc.number}, origin=actor.source)
    return inc


async def add_note(s: AsyncSession, actor: Actor, inc_id: int, body: str, *, restricted: bool = False) -> IncidentNote:
    inc = await get(s, inc_id)
    body = (body or "").strip()
    if not body:
        raise ValidationFailed("Note text is required.")
    if not (actor.can("cad.incident.edit") or actor.can("cad.dispatch")):
        mine = [u.id for u in await unit_svc.my_units(s, actor)]
        if not any(a.unit_id in mine and a.cleared_at is None for a in inc.assignments):
            raise Forbidden("Only dispatchers or assigned units can add notes.")
    if restricted:
        actor.require("cad.incident.restricted")
    note = IncidentNote(incident_id=inc.id, user_id=actor.user_id, body=body[:2000], is_restricted=restricted)
    s.add(note)
    _event(s, inc, actor, "note", ("[Restricted] " if restricted else "") + body[:400])
    await audit(s, actor, "cad", "incident.note", target_type="incident", target_id=inc.id, target_ref=inc.number,
                context={"restricted": restricted})
    emit(s, "incident.changed", {"id": inc.id, "number": inc.number, "note": True}, origin=actor.source)
    return note


async def link_record(s: AsyncSession, actor: Actor, inc_id: int, rtype: str | None, rid: int, *, note: str = "",
                      _audit: bool = True) -> RecordLink:
    from nexus.services import records

    if rtype not in LINK_TYPES:
        raise ValidationFailed("Unknown record type.")
    if not (actor.can("cad.incident.edit") or actor.can("cad.records.edit") or actor.can("cad.incident.create")):
        raise Forbidden("You cannot link records to incidents.")
    if not await records.record_label(s, rtype, rid):
        raise NotFound(f"{rtype} record {rid} not found.")
    inc = await s.get(Incident, inc_id)
    if inc is None:
        raise NotFound("Incident not found.")
    existing = (await s.execute(select(RecordLink).where(
        RecordLink.source_type == "incident", RecordLink.source_id == inc_id, RecordLink.target_type == rtype,
        RecordLink.target_id == rid))).scalar_one_or_none()
    if existing:
        return existing
    link = RecordLink(source_type="incident", source_id=inc_id, target_type=rtype, target_id=rid, note=note[:200],
                      created_by=actor.user_id)
    s.add(link)
    _event(s, inc, actor, "linked", f"Linked {rtype} {await records.record_label(s, rtype, rid)}")
    if _audit:
        await audit(s, actor, "cad", "incident.linked", target_type="incident", target_id=inc_id, target_ref=inc.number,
                    new={"type": rtype, "id": rid})
    return link


async def list_incidents(s: AsyncSession, actor: Actor, *, state: str = "open", department_id: int | None = None,
                         priority: int | None = None, category: str | None = None, q: str = "",
                         date_from: datetime | None = None, date_to: datetime | None = None, mine: bool = False,
                         sort: str = "priority", limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    actor.require("cad.view")
    open_keys = await lookups.open_status_keys(s)
    stmt = select(Incident).options(selectinload(Incident.department),
                                    selectinload(Incident.assignments).selectinload(IncidentAssignment.unit))
    stmt = stmt.where(Incident.is_archived.is_(False))
    if state == "open":
        stmt = stmt.where(Incident.status.in_(open_keys))
    elif state == "closed":
        stmt = stmt.where(Incident.status.not_in(open_keys))
    elif state not in ("all", ""):
        stmt = stmt.where(Incident.status == state)
    if department_id:
        stmt = stmt.where(Incident.department_id == department_id)
    if priority:
        stmt = stmt.where(Incident.priority == priority)
    if category:
        stmt = stmt.where(Incident.category == category)
    if date_from:
        stmt = stmt.where(Incident.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Incident.created_at <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Incident.number.ilike(like), Incident.description.ilike(like),
                              Incident.location_name.ilike(like), Incident.street.ilike(like),
                              Incident.caller_name.ilike(like), Incident.subtype.ilike(like)))
    if mine:
        my_ids = [u.id for u in await unit_svc.my_units(s, actor)] or [-1]
        stmt = stmt.join(IncidentAssignment, IncidentAssignment.incident_id == Incident.id).where(
            IncidentAssignment.unit_id.in_(my_ids), IncidentAssignment.cleared_at.is_(None))
    total = (await s.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar() or 0
    if sort == "age":
        stmt = stmt.order_by(Incident.created_at.asc())
    elif sort == "recent":
        stmt = stmt.order_by(Incident.created_at.desc())
    else:
        stmt = stmt.order_by(Incident.priority.asc(), Incident.created_at.asc())
    rows = (await s.execute(stmt.limit(min(limit, 200)).offset(offset))).scalars().unique().all()
    prios, statuses, cats = await lookups.priorities(s), await lookups.incident_statuses(s), await lookups.categories(s)
    return [await summary_dict(s, i, prios=prios, statuses=statuses, cats=cats) for i in rows], total


async def queue(s: AsyncSession, actor: Actor, *, department_id: int | None = None, sort: str = "priority",
                q: str = "") -> list[dict]:
    items, _ = await list_incidents(s, actor, state="open", department_id=department_id, sort=sort, q=q, limit=200)
    thresholds = await get_setting(s, "cad.queue_alert_seconds") or {}
    for it in items:
        limit = thresholds.get(str(it["priority"]))
        waiting = it["status"] in ("new", "pending") or not it["units"]
        it["overdue"] = bool(waiting and limit and it["waiting_seconds"] > int(limit))
        it["awaiting_dispatch"] = waiting
    return items


async def history(s: AsyncSession, inc_id: int) -> list[dict]:
    rows = (await s.execute(select(IncidentEvent, User.display_name).outerjoin(User, User.id == IncidentEvent.user_id)
                            .where(IncidentEvent.incident_id == inc_id).order_by(IncidentEvent.id))).all()
    return [{"event": e.event_type, "message": e.message, "old": e.old_value, "new": e.new_value,
             "user": name or "System", "created_at": e.created_at} for e, name in rows]


async def counts(s: AsyncSession) -> dict[str, int]:
    open_keys = await lookups.open_status_keys(s)
    rows = (await s.execute(select(Incident.priority, func.count()).where(Incident.status.in_(open_keys),
                                                                           Incident.is_archived.is_(False))
                            .group_by(Incident.priority))).all()
    by_prio = {int(p): n for p, n in rows}
    awaiting = (await s.execute(select(func.count()).select_from(Incident).where(Incident.status.in_(("new", "pending"))))).scalar()
    return {"active": sum(by_prio.values()), "emergency": by_prio.get(1, 0), "by_priority": by_prio,
            "awaiting_dispatch": awaiting or 0}


# ---- In-game 911 calls from the ERLC API ------------------------------------------


async def pending_erlc_calls(s: AsyncSession) -> list[dict]:
    rows = (await s.execute(select(ErlcEmergencyCall).where(ErlcEmergencyCall.status == "pending")
                            .order_by(ErlcEmergencyCall.started_at.desc()).limit(50))).scalars()
    return [{"id": c.id, "call_number": c.call_number, "team": c.team, "caller": c.caller_name or c.caller_roblox_id,
             "description": c.description, "location": c.position_descriptor, "x": c.x, "z": c.z,
             "started_at": c.started_at, "source": "official ERLC API"} for c in rows]


async def accept_erlc_call(s: AsyncSession, actor: Actor, call_id: int, extra: dict[str, Any] | None = None) -> Incident:
    actor.require("cad.incident.create")
    call = await s.get(ErlcEmergencyCall, call_id)
    if call is None:
        raise NotFound("Emergency call not found.")
    if call.status != "pending":
        raise Conflict("That call has already been handled.")
    extra = extra or {}
    team = (call.team or "").lower()
    default_cat = "fire" if "fire" in team else "medical" if "ems" in team or "medic" in team else "crime" if "police" in team or "sheriff" in team else "other"
    inc = await create(s, actor, {
        "category": extra.get("category") or default_cat, "priority": extra.get("priority") or 2,
        "status": "pending", "caller_name": call.caller_name or f"Roblox {call.caller_roblox_id}",
        "caller_identifier": call.caller_roblox_id, "location_name": call.position_descriptor or "In-game location",
        "map_x": call.x, "map_z": call.z, "description": call.description or f"In-game {call.team} call",
        "department_id": extra.get("department_id"),
    }, source="erlc_api", source_ref=f"call:{call.call_number}")
    _event(s, inc, actor, "note", f"Imported from official ERLC API emergency call #{call.call_number} ({call.team})")
    call.status = "accepted"
    call.incident_id = inc.id
    call.handled_by = actor.user_id
    emit(s, "erlc.911_handled", {"id": call.id, "incident_id": inc.id}, origin=actor.source)
    return inc


async def dismiss_erlc_call(s: AsyncSession, actor: Actor, call_id: int) -> None:
    actor.require("cad.dispatch")
    call = await s.get(ErlcEmergencyCall, call_id)
    if call is None:
        raise NotFound("Emergency call not found.")
    call.status = "dismissed"
    call.handled_by = actor.user_id
    await audit(s, actor, "cad", "erlc_call.dismissed", target_type="erlc_call", target_id=call.id,
                target_ref=f"#{call.call_number}")
    emit(s, "erlc.911_handled", {"id": call.id}, origin=actor.source)
