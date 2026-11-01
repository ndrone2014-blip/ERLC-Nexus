"""Map locations, calibration and the live map layer.

Coordinates are stored in ERLC game units (the same space as the official API
``LocationX``/``LocationZ``). The website converts them to image pixels with
the admin-editable calibration: ``px = x * scale + offset_x``,
``py = z * scale + offset_z`` (``+Z`` is down, per the official docs).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.settings_store import get_setting, set_setting
from nexus.db.models import Bolo, Incident, Location, TrafficStop
from nexus.erlc.sync import get_state
from nexus.services import lookups, units as unit_svc

MAP_STYLES = {
    "fall_postals": "https://api.erlc.gg/maps/fall_postals.png",
    "fall_blank": "https://api.erlc.gg/maps/fall_blank.png",
    "snow_postals": "https://api.erlc.gg/maps/snow_postals.png",
    "snow_blank": "https://api.erlc.gg/maps/snow_blank.png",
}
MAP_SIZE = 5355


def loc_dict(l: Location) -> dict[str, Any]:
    return {"id": l.id, "name": l.name, "category": l.category, "description": l.description, "street": l.street,
            "postal": l.postal, "x": l.x, "z": l.z, "icon": l.icon, "color": l.color, "is_preset": l.is_preset,
            "verified": l.verified, "is_archived": l.is_archived}


async def list_locations(s: AsyncSession, q: str = "", category: str = "", include_archived: bool = False) -> list[dict]:
    stmt = select(Location).order_by(Location.category, Location.name)
    if not include_archived:
        stmt = stmt.where(Location.is_archived.is_(False))
    if category:
        stmt = stmt.where(Location.category == category)
    if q:
        stmt = stmt.where(or_(Location.name.ilike(f"%{q}%"), Location.street.ilike(f"%{q}%"), Location.postal == q))
    return [loc_dict(l) for l in (await s.execute(stmt)).scalars()]


async def save_location(s: AsyncSession, actor: Actor, data: dict[str, Any], loc_id: int | None = None) -> Location:
    actor.require("cad.map.edit")
    cats = {c["key"] for c in await get_setting(s, "map.location_categories")}
    vals: dict[str, Any] = {}
    for f in ("name", "category", "description", "street", "postal", "x", "z", "icon", "color"):
        if f in data:
            v = data[f]
            if f in ("x", "z"):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise ValidationFailed("Coordinates must be numbers.")
                if abs(v) > 100000:
                    raise ValidationFailed("Coordinate out of range.")
            elif f == "category" and v not in cats:
                raise ValidationFailed("Unknown location category.")
            elif isinstance(v, str):
                v = v.strip()[:400]
            vals[f] = v
    if loc_id is None:
        if not vals.get("name"):
            raise ValidationFailed("Location name is required.")
        loc = Location(created_by=actor.user_id, is_preset=True, verified=True, **{"category": "custom", "x": 0, "z": 0, **vals})
        s.add(loc)
        await s.flush()
        await audit(s, actor, "cad", "map.location_created", target_type="location", target_id=loc.id, target_ref=loc.name,
                    new=vals)
    else:
        loc = await s.get(Location, loc_id)
        if loc is None:
            raise NotFound("Location not found.")
        before = loc_dict(loc)
        for k, v in vals.items():
            setattr(loc, k, v)
        if "x" in vals or "z" in vals or data.get("verified"):
            loc.verified = True
        if "is_archived" in data:
            loc.is_archived = bool(data["is_archived"])
        await audit(s, actor, "cad", "map.location_updated", target_type="location", target_id=loc.id, target_ref=loc.name,
                    old={k: before[k] for k in vals}, new=vals)
    emit(s, "map.changed", {"location_id": loc.id}, origin=actor.source)
    return loc


async def set_calibration(s: AsyncSession, actor: Actor, *, scale: float, offset_x: float, offset_z: float,
                          verified: bool = True) -> dict[str, Any]:
    if not (0.001 <= scale <= 100):
        raise ValidationFailed("Scale must be between 0.001 and 100.")
    value = {"scale": scale, "offset_x": offset_x, "offset_z": offset_z, "verified": verified}
    await set_setting(s, actor, "map.calibration", value)
    return value


def calibrate_from_points(p1: dict, p2: dict) -> dict[str, float]:
    """Two reference points (game x/z + image px/py) → uniform scale + offsets."""
    dx_game = p2["x"] - p1["x"]
    dz_game = p2["z"] - p1["z"]
    dist_game = (dx_game ** 2 + dz_game ** 2) ** 0.5
    dist_px = ((p2["px"] - p1["px"]) ** 2 + (p2["py"] - p1["py"]) ** 2) ** 0.5
    if dist_game < 1 or dist_px < 1:
        raise ValidationFailed("Pick two reference points that are far apart.")
    scale = dist_px / dist_game
    return {"scale": round(scale, 6), "offset_x": round(p1["px"] - p1["x"] * scale, 3),
            "offset_z": round(p1["py"] - p1["z"] * scale, 3)}


async def map_config(s: AsyncSession) -> dict[str, Any]:
    style = await get_setting(s, "map.style")
    return {"size": MAP_SIZE, "style": style, "styles": list(MAP_STYLES), "image_url": f"/map-image/{style}.png",
            "calibration": await get_setting(s, "map.calibration"),
            "categories": await get_setting(s, "map.location_categories"),
            "marker_colors": await get_setting(s, "map.marker_colors"),
            "source_note": "Map imagery © Police Roleplay Community (official ERLC map image)."}


async def live_layer(s: AsyncSession, actor: Actor) -> dict[str, Any]:
    """Everything drawn on the live map, each item labelled with its data source."""
    actor.require("cad.view")
    open_keys = await lookups.open_status_keys(s)
    incidents = (await s.execute(select(Incident).where(Incident.status.in_(open_keys), Incident.map_x.is_not(None),
                                                        Incident.is_archived.is_(False)))).scalars().all()
    prios = {p["level"]: p for p in await lookups.priorities(s)}
    units = await unit_svc.list_units(s)
    unit_rows = [u for u in await unit_svc.serialize_units(s, units) if u["location"]["x"] is not None]
    stops = (await s.execute(select(TrafficStop).where(TrafficStop.status == "active", TrafficStop.map_x.is_not(None)))).scalars().all()
    server, fetched = await get_state(s, "server")
    players = []
    if actor.can("erlc.server.view") and server:
        for p in server.get("players", []):
            loc = p.get("location") or {}
            if loc.get("x") is not None:
                players.append({"name": p["name"], "team": p["team"], "callsign": p.get("callsign"),
                                "x": loc["x"], "z": loc["z"], "street": loc.get("street"), "postal": loc.get("postal"),
                                "source": "api"})
    bolos = (await s.execute(select(Bolo).where(Bolo.status.in_(("active", "updated"))))).scalars().all()
    return {
        "incidents": [{"id": i.id, "number": i.number, "priority": i.priority,
                       "color": prios.get(i.priority, {}).get("color", "#ef4444"),
                       "category": i.category, "location": i.location_name or i.street, "description": i.description[:160],
                       "status": i.status, "x": i.map_x, "z": i.map_z,
                       "source": "api" if i.source == "erlc_api" else "manual"} for i in incidents],
        "units": [{"id": u["id"], "callsign": u["callsign"], "status": u["status_label"], "color": u["status_color"],
                   "department": u["department"], "x": u["location"]["x"], "z": u["location"]["z"],
                   "text": u["location"]["text"], "source": u["location"]["source"],
                   "updated_at": u["location"]["updated_at"]} for u in unit_rows],
        "traffic_stops": [{"id": t.id, "number": t.number, "callsign": t.callsign, "plate": t.plate, "location": t.location,
                           "x": t.map_x, "z": t.map_z, "source": "manual"} for t in stops],
        "players": players,
        "players_fetched_at": fetched,
        "bolo_locations": [{"id": b.id, "number": b.number, "text": b.last_known_location} for b in bolos if b.last_known_location],
    }
