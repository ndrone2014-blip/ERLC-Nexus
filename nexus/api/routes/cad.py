"""CAD routes: incidents, dispatch queue, 911, units, comms, traffic stops, map."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import current_actor, db_session, require, require_any
from nexus.core.context import Actor
from nexus.services import comms, incidents, maps, records, units

router = APIRouter(prefix="/api")


# ---- incidents ------------------------------------------------------------------

@router.get("/cad/incidents")
async def list_incidents(state: str = "open", department_id: int | None = None, priority: int | None = None,
                         category: str | None = None, q: str = "", date_from: datetime | None = None,
                         date_to: datetime | None = None, mine: bool = False, sort: str = "priority", limit: int = 50,
                         offset: int = 0, actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    items, total = await incidents.list_incidents(s, actor, state=state, department_id=department_id, priority=priority,
                                                  category=category, q=q, date_from=date_from, date_to=date_to, mine=mine,
                                                  sort=sort, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/cad/queue")
async def dispatch_queue(department_id: int | None = None, sort: str = "priority", q: str = "",
                         actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await incidents.queue(s, actor, department_id=department_id, sort=sort, q=q)


@router.post("/cad/incidents")
async def create_incident(body: dict = Body(...), actor: Actor = Depends(require("cad.incident.create")),
                          s: AsyncSession = Depends(db_session)):
    inc = await incidents.create(s, actor, body, source=body.get("source") if body.get("source") == "map" else "web")
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc.id))


@router.post("/cad/911")
async def call_911(body: dict = Body(...), actor: Actor = Depends(require("cad.911.create")), s: AsyncSession = Depends(db_session)):
    inc = await incidents.create_911(s, actor, body, source="web")
    await s.commit()
    return {"id": inc.id, "number": inc.number}


@router.get("/cad/incidents/{ref}")
async def get_incident(ref: str, actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await incidents.detail_dict(s, actor, await incidents.get(s, ref))


@router.patch("/cad/incidents/{inc_id}")
async def update_incident(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.incident.edit")),
                          s: AsyncSession = Depends(db_session)):
    await incidents.update(s, actor, inc_id, body)
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/status")
async def incident_status(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                          s: AsyncSession = Depends(db_session)):
    await incidents.change_status(s, actor, inc_id, str(body.get("status", "")), disposition=str(body.get("disposition", "")))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/priority")
async def incident_priority(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.incident.edit")),
                            s: AsyncSession = Depends(db_session)):
    await incidents.change_priority(s, actor, await incidents.get(s, inc_id), int(body.get("priority", 3)))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/assign")
async def assign(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                 s: AsyncSession = Depends(db_session)):
    await incidents.assign_unit(s, actor, inc_id, body.get("unit"), primary=bool(body.get("primary")))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/clear")
async def clear(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                s: AsyncSession = Depends(db_session)):
    await incidents.clear_unit(s, actor, inc_id, body.get("unit"))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/notes")
async def note(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
               s: AsyncSession = Depends(db_session)):
    await incidents.add_note(s, actor, inc_id, str(body.get("body", "")), restricted=bool(body.get("restricted")))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.post("/cad/incidents/{inc_id}/links")
async def link(inc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
               s: AsyncSession = Depends(db_session)):
    await incidents.link_record(s, actor, inc_id, body.get("type"), int(body.get("id", 0)), note=str(body.get("note", "")))
    await s.commit()
    return await incidents.detail_dict(s, actor, await incidents.get(s, inc_id))


@router.get("/cad/incidents/{inc_id}/history")
async def incident_history(inc_id: int, actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await incidents.history(s, inc_id)


# ---- in-game 911 calls (official API) -------------------------------------------

@router.get("/cad/erlc-calls")
async def erlc_calls(actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await incidents.pending_erlc_calls(s)


@router.post("/cad/erlc-calls/{call_id}/accept")
async def accept_call(call_id: int, body: dict = Body(default_factory=dict),
                      actor: Actor = Depends(require("cad.incident.create")), s: AsyncSession = Depends(db_session)):
    inc = await incidents.accept_erlc_call(s, actor, call_id, body)
    await s.commit()
    return {"id": inc.id, "number": inc.number}


@router.post("/cad/erlc-calls/{call_id}/dismiss")
async def dismiss_call(call_id: int, actor: Actor = Depends(require("cad.dispatch")), s: AsyncSession = Depends(db_session)):
    await incidents.dismiss_erlc_call(s, actor, call_id)
    await s.commit()
    return {"ok": True}


# ---- units ------------------------------------------------------------------------

@router.get("/cad/units")
async def list_units(department_id: int | None = None, status: str | None = None, group: str | None = None,
                     include_archived: bool = False, actor: Actor = Depends(require("cad.view")),
                     s: AsyncSession = Depends(db_session)):
    return await units.serialize_units(s, await units.list_units(s, department_id=department_id, status=status, group=group,
                                                                 include_archived=include_archived))


@router.get("/cad/my-units")
async def my_units(actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await units.serialize_units(s, await units.my_units(s, actor))


@router.get("/cad/callsign-suggest")
async def callsign_suggest(department_id: int, unit_type: str = "", num: str = "1",
                           actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return {"callsign": await units.suggest_callsign(s, department_id, unit_type, num)}


@router.post("/cad/units")
async def register_unit(body: dict = Body(...), actor: Actor = Depends(require_any("cad.unit.manage", "cad.unit.self")),
                        s: AsyncSession = Depends(db_session)):
    u = await units.register_unit(s, actor, body)
    await s.commit()
    return (await units.serialize_units(s, [await units.get_unit(s, u.id)]))[0]


@router.get("/cad/units/{unit_id}")
async def get_unit(unit_id: int, actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    u = (await units.serialize_units(s, [await units.get_unit(s, unit_id)]))[0]
    u["history"] = await units.unit_history(s, unit_id, limit=50)
    return u


@router.patch("/cad/units/{unit_id}")
async def update_unit(unit_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                      s: AsyncSession = Depends(db_session)):
    await units.update_unit(s, actor, unit_id, body)
    await s.commit()
    return (await units.serialize_units(s, [await units.get_unit(s, unit_id)]))[0]


@router.delete("/cad/units/{unit_id}")
async def remove_unit(unit_id: int, actor: Actor = Depends(require("cad.unit.manage")), s: AsyncSession = Depends(db_session)):
    await units.archive_unit(s, actor, unit_id)
    await s.commit()
    return {"ok": True}


@router.post("/cad/units/{unit_id}/status")
async def unit_status(unit_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                      s: AsyncSession = Depends(db_session)):
    await units.set_status(s, actor, unit_id, str(body.get("status", "")), note=str(body.get("note", "")))
    await s.commit()
    return (await units.serialize_units(s, [await units.get_unit(s, unit_id)]))[0]


@router.post("/cad/units/{unit_id}/location")
async def unit_location(unit_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                        s: AsyncSession = Depends(db_session)):
    x, z = body.get("x"), body.get("z")
    await units.set_location(s, actor, unit_id, text=str(body.get("text", "")), x=float(x) if x not in (None, "") else None,
                             z=float(z) if z not in (None, "") else None, location_id=body.get("location_id"))
    await s.commit()
    return (await units.serialize_units(s, [await units.get_unit(s, unit_id)]))[0]


@router.post("/cad/units/{unit_id}/members")
async def add_unit_member(unit_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.view")),
                          s: AsyncSession = Depends(db_session)):
    await units.add_member(s, actor, unit_id, int(body.get("user_id", 0)), primary=bool(body.get("primary")))
    await s.commit()
    return (await units.serialize_units(s, [await units.get_unit(s, unit_id)]))[0]


@router.delete("/cad/units/{unit_id}/members/{user_id}")
async def remove_unit_member(unit_id: int, user_id: int, actor: Actor = Depends(require("cad.view")),
                             s: AsyncSession = Depends(db_session)):
    await units.remove_member(s, actor, unit_id, user_id)
    await s.commit()
    return {"ok": True}


@router.get("/cad/units/{unit_id}/history")
async def unit_history(unit_id: int, actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await units.unit_history(s, unit_id)


# ---- communications -----------------------------------------------------------------

@router.get("/cad/comms")
async def comms_feed(channel: str = "", department_id: int | None = None, incident_id: int | None = None,
                     before_id: int | None = None, actor: Actor = Depends(require("cad.view")),
                     s: AsyncSession = Depends(db_session)):
    return await comms.feed(s, actor, channel=channel, department_id=department_id, incident_id=incident_id,
                            before_id=before_id)


@router.post("/cad/comms")
async def comms_send(body: dict = Body(...), actor: Actor = Depends(require("cad.comms.send")),
                     s: AsyncSession = Depends(db_session)):
    m = await comms.send(s, actor, body=str(body.get("body", "")), channel=str(body.get("channel", "dispatch")),
                         kind=str(body.get("kind", "message")), department_id=body.get("department_id"),
                         unit_id=body.get("unit_id"), incident_id=body.get("incident_id"),
                         restricted=bool(body.get("restricted")),
                         sender_label=f"{body['sender_label']} ({actor.name})" if body.get("sender_label") else "")
    await s.commit()
    return comms.msg_dict(m)


# ---- traffic stops --------------------------------------------------------------------

@router.get("/cad/traffic")
async def traffic_list(status: str = "", mine: bool = False, q: str = "",
                       actor: Actor = Depends(require_any("cad.traffic.manage", "cad.dispatch")),
                       s: AsyncSession = Depends(db_session)):
    return await records.list_traffic_stops(s, actor, status=status, mine=mine, q=q)


@router.post("/cad/traffic")
async def traffic_start(body: dict = Body(...), actor: Actor = Depends(require("cad.traffic.manage")),
                        s: AsyncSession = Depends(db_session)):
    t = await records.start_traffic_stop(s, actor, body)
    await s.commit()
    return records.traffic_dict(t)


@router.get("/cad/traffic/{tid}")
async def traffic_get(tid: int, actor: Actor = Depends(require_any("cad.traffic.manage", "cad.dispatch")),
                      s: AsyncSession = Depends(db_session)):
    from nexus.db.models import TrafficStop
    from nexus.core.context import NotFound

    t = await s.get(TrafficStop, tid)
    if t is None:
        raise NotFound("Traffic stop not found.")
    d = records.traffic_dict(t)
    d["history"] = await records.revisions(s, "traffic", tid)
    return d


@router.patch("/cad/traffic/{tid}")
async def traffic_update(tid: int, body: dict = Body(...),
                         actor: Actor = Depends(require_any("cad.traffic.manage", "cad.dispatch")),
                         s: AsyncSession = Depends(db_session)):
    t = await records.update_traffic_stop(s, actor, tid, body)
    await s.commit()
    return records.traffic_dict(t)


@router.post("/cad/traffic/{tid}/end")
async def traffic_end(tid: int, body: dict = Body(default_factory=dict),
                      actor: Actor = Depends(require_any("cad.traffic.manage", "cad.dispatch")),
                      s: AsyncSession = Depends(db_session)):
    t = await records.end_traffic_stop(s, actor, tid, outcome=str(body.get("outcome", "")),
                                       notes=str(body.get("notes", "")), cancel=bool(body.get("cancel")))
    await s.commit()
    return records.traffic_dict(t)


# ---- map --------------------------------------------------------------------------------

@router.get("/map/config")
async def map_config(actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await maps.map_config(s)


@router.get("/map/live")
async def map_live(actor: Actor = Depends(require("cad.view")), s: AsyncSession = Depends(db_session)):
    return await maps.live_layer(s, actor)


@router.get("/map/locations")
async def map_locations(q: str = "", category: str = "", include_archived: bool = False,
                        actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await maps.list_locations(s, q, category, include_archived and actor.can("cad.map.edit"))


@router.post("/map/locations")
async def create_location(body: dict = Body(...), actor: Actor = Depends(require("cad.map.edit")),
                          s: AsyncSession = Depends(db_session)):
    loc = await maps.save_location(s, actor, body)
    await s.commit()
    return maps.loc_dict(loc)


@router.patch("/map/locations/{loc_id}")
async def update_location(loc_id: int, body: dict = Body(...), actor: Actor = Depends(require("cad.map.edit")),
                          s: AsyncSession = Depends(db_session)):
    loc = await maps.save_location(s, actor, body, loc_id)
    await s.commit()
    return maps.loc_dict(loc)


@router.post("/map/calibration")
async def set_calibration(body: dict = Body(...), actor: Actor = Depends(require("cad.map.edit")),
                          s: AsyncSession = Depends(db_session)):
    actor.require("system.configure")
    if "points" in body:
        p1, p2 = body["points"]
        body = {**maps.calibrate_from_points(p1, p2), "verified": True}
    value = await maps.set_calibration(s, actor, scale=float(body["scale"]), offset_x=float(body["offset_x"]),
                                       offset_z=float(body["offset_z"]), verified=bool(body.get("verified", True)))
    await s.commit()
    return value
