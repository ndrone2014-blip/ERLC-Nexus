"""MDT records: persons, vehicles, BOLOs, warrants, cases, traffic stops.

Every record here is fictional ERLC roleplay data. Edits are tracked in
``record_revisions``; records are archived (soft-deleted), never erased.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.numbering import next_number
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import (
    Bolo,
    Case,
    CaseNote,
    Department,
    Incident,
    Person,
    RecordLink,
    RecordRevision,
    Report,
    TrafficStop,
    Unit,
    User,
    Vehicle,
    Warrant,
)
from nexus.services import notifications

PLATE_RE = re.compile(r"^[A-Z0-9 \-]{1,10}$")
DISCLAIMER = "Fictional ERLC roleplay record"


def norm_plate(p: str | None) -> str:
    return re.sub(r"\s+", "", (p or "").upper())


def _snap(obj: Any, fields: list[str]) -> dict[str, Any]:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o)))


async def _revision(s: AsyncSession, actor: Actor, rtype: str, rid: int, action: str, old: dict, new: dict) -> None:
    old, new = _json_safe(old), _json_safe(new)
    changes = {k: {"old": old.get(k), "new": new.get(k)} for k in new if old.get(k) != new.get(k)}
    if action != "updated" or changes:
        s.add(RecordRevision(record_type=rtype, record_id=rid, action=action, changes=changes, user_id=actor.user_id))


async def revisions(s: AsyncSession, rtype: str, rid: int) -> list[dict[str, Any]]:
    rows = (await s.execute(select(RecordRevision, User.display_name).outerjoin(User, User.id == RecordRevision.user_id)
                            .where(RecordRevision.record_type == rtype, RecordRevision.record_id == rid)
                            .order_by(RecordRevision.id.desc()))).all()
    return [{"action": r.action, "changes": r.changes, "user": n or "System", "created_at": r.created_at} for r, n in rows]


async def record_label(s: AsyncSession, rtype: str, rid: int) -> str | None:
    model = {"person": Person, "vehicle": Vehicle, "bolo": Bolo, "warrant": Warrant, "case": Case,
             "traffic": TrafficStop, "report": Report, "incident": Incident}.get(rtype)
    if model is None:
        return None
    obj = await s.get(model, rid)
    if obj is None:
        return None
    if rtype == "person":
        return f"{obj.number} {obj.full_name}"
    if rtype == "vehicle":
        return f"{obj.plate} {obj.color} {obj.make} {obj.model}".strip()
    if rtype == "case":
        return f"{obj.number} {obj.title}"
    return obj.number


def _check_edit(actor: Actor, owner_user_id: int | None = None) -> None:
    if actor.can("cad.records.edit"):
        return
    if actor.can("civ.use") and owner_user_id is not None and owner_user_id == actor.user_id:
        return
    raise Forbidden("You do not have permission to edit this record.")


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------

PERSON_FIELDS = ["first_name", "last_name", "aliases", "date_of_birth", "gender", "description", "address",
                 "license_status", "flags", "notes", "discord_id", "roblox_username"]


def person_dict(p: Person, *, full: bool = True) -> dict[str, Any]:
    d = {"id": p.id, "number": p.number, "name": p.full_name, "first_name": p.first_name, "last_name": p.last_name,
         "aliases": p.aliases or [], "date_of_birth": p.date_of_birth, "license_status": p.license_status,
         "flags": p.flags or [], "is_archived": p.is_archived, "is_civilian_character": p.is_civilian_character,
         "record_type": DISCLAIMER}
    if full:
        d.update({"gender": p.gender, "description": p.description, "address": p.address, "notes": p.notes,
                  "discord_id": p.discord_id, "roblox_username": p.roblox_username, "owner_user_id": p.owner_user_id,
                  "created_by": p.created_by, "created_at": p.created_at, "updated_at": p.updated_at})
    return d


def _person_values(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in PERSON_FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f in ("aliases", "flags"):
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            v = [str(x)[:40] for x in (v or [])][:20]
        elif isinstance(v, str):
            v = v.strip()[:2000 if f == "notes" else 400]
        out[f] = v
    return out


async def create_person(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Person:
    civilian = not actor.can("cad.records.edit")
    if civilian:
        actor.require("civ.use")
    vals = _person_values(data)
    if not vals.get("first_name"):
        raise ValidationFailed("First name is required.")
    if vals.get("discord_id") and not str(vals["discord_id"]).isdigit():
        raise ValidationFailed("Discord ID must be numeric.")
    p = Person(number=await next_number(s, "person"), created_by=actor.user_id,
               owner_user_id=actor.user_id if civilian or data.get("own_character") else None,
               is_civilian_character=civilian or bool(data.get("own_character")), **vals)
    s.add(p)
    await s.flush()
    await _revision(s, actor, "person", p.id, "created", {}, _snap(p, PERSON_FIELDS))
    await audit(s, actor, "mdt", "person.created", target_type="person", target_id=p.id, target_ref=p.number,
                new={"name": p.full_name})
    emit(s, "record.changed", {"type": "person", "id": p.id}, origin=actor.source)
    return p


async def update_person(s: AsyncSession, actor: Actor, pid: int, data: dict[str, Any]) -> Person:
    p = await s.get(Person, pid)
    if p is None:
        raise NotFound("Person record not found.")
    _check_edit(actor, p.owner_user_id)
    old = _snap(p, PERSON_FIELDS)
    for k, v in _person_values(data).items():
        setattr(p, k, v)
    if not p.first_name:
        raise ValidationFailed("First name is required.")
    new = _snap(p, PERSON_FIELDS)
    await _revision(s, actor, "person", p.id, "updated", old, new)
    if old != new:
        await audit(s, actor, "mdt", "person.updated", target_type="person", target_id=p.id, target_ref=p.number,
                    old={k: old[k] for k in new if old[k] != new[k]}, new={k: new[k] for k in new if old[k] != new[k]})
        emit(s, "record.changed", {"type": "person", "id": p.id}, origin=actor.source)
    return p


async def set_archived(s: AsyncSession, actor: Actor, rtype: str, rid: int, archived: bool) -> None:
    model = {"person": Person, "vehicle": Vehicle, "incident": Incident}.get(rtype)
    if model is None:
        raise ValidationFailed("That record type cannot be archived here.")
    obj = await s.get(model, rid)
    if obj is None:
        raise NotFound("Record not found.")
    owner = getattr(obj, "owner_user_id", None)
    if not actor.can("cad.records.archive") and not (actor.can("civ.use") and owner == actor.user_id):
        raise Forbidden("You cannot archive this record.")
    obj.is_archived = archived
    await _revision(s, actor, rtype, rid, "archived" if archived else "restored", {}, {})
    await audit(s, actor, "mdt", f"{rtype}.{'archived' if archived else 'restored'}", target_type=rtype, target_id=rid,
                target_ref=getattr(obj, "number", str(rid)))


async def person_profile(s: AsyncSession, actor: Actor, pid: int) -> dict[str, Any]:
    p = await s.get(Person, pid)
    if p is None or (p.is_archived and not actor.can("cad.records.archive")):
        raise NotFound("Person record not found.")
    if not actor.can("cad.records.search") and p.owner_user_id != actor.user_id:
        raise Forbidden("You cannot view this record.")
    d = person_dict(p)
    vehicles = (await s.execute(select(Vehicle).where(Vehicle.owner_person_id == p.id, Vehicle.is_archived.is_(False)))).scalars()
    d["vehicles"] = [vehicle_dict(v, full=False) for v in vehicles]
    stops = (await s.execute(select(TrafficStop).where(TrafficStop.driver_person_id == p.id)
                             .order_by(TrafficStop.started_at.desc()).limit(25))).scalars()
    d["traffic_stops"] = [traffic_dict(t) for t in stops]
    d["bolos"] = [bolo_dict(b) for b in (await s.execute(select(Bolo).where(Bolo.person_id == p.id)
                                                         .order_by(Bolo.id.desc()))).scalars()]
    if actor.can("cad.warrants.view"):
        d["warrants"] = [warrant_dict(w) for w in (await s.execute(select(Warrant).where(Warrant.person_id == p.id)
                                                                   .order_by(Warrant.id.desc()))).scalars()]
    from nexus.services.incidents import linked_records

    d["links"] = await linked_records(s, "person", p.id)
    d["history"] = await revisions(s, "person", p.id)
    return d


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

VEHICLE_FIELDS = ["plate", "make", "model", "color", "category", "year", "owner_person_id", "owner_name",
                  "registration_status", "insurance_status", "description", "flags", "notes"]
REG_STATUSES = ("Valid", "Expired", "Suspended", "Unregistered", "Stolen")
INS_STATUSES = ("Valid", "Expired", "None")


def vehicle_dict(v: Vehicle, *, full: bool = True) -> dict[str, Any]:
    d = {"id": v.id, "number": v.number, "plate": v.plate, "make": v.make, "model": v.model, "color": v.color,
         "category": v.category, "year": v.year, "registration_status": v.registration_status,
         "insurance_status": v.insurance_status, "owner_person_id": v.owner_person_id, "owner_name": v.owner_name,
         "flags": v.flags or [], "is_archived": v.is_archived, "record_type": DISCLAIMER}
    if full:
        d.update({"description": v.description, "notes": v.notes, "owner_user_id": v.owner_user_id,
                  "created_at": v.created_at, "updated_at": v.updated_at})
    return d


async def _vehicle_values(s: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in VEHICLE_FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f == "plate":
            v = norm_plate(v)
            if not PLATE_RE.match(v):
                raise ValidationFailed("License plates may only contain letters and numbers (max 10).")
        elif f == "flags":
            v = [x.strip() for x in v.split(",")] if isinstance(v, str) else list(v or [])
            v = [str(x)[:40] for x in v if x][:20]
        elif f == "owner_person_id":
            v = int(v) if v not in (None, "") else None
            if v is not None and await s.get(Person, v) is None:
                raise ValidationFailed("Owner person record not found.")
        elif f == "registration_status" and v not in REG_STATUSES:
            raise ValidationFailed(f"Registration status must be one of: {', '.join(REG_STATUSES)}.")
        elif f == "insurance_status" and v not in INS_STATUSES:
            raise ValidationFailed(f"Insurance status must be one of: {', '.join(INS_STATUSES)}.")
        elif isinstance(v, str):
            v = v.strip()[:2000 if f == "notes" else 300]
        out[f] = v
    return out


async def create_vehicle(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Vehicle:
    civilian = not actor.can("cad.records.edit")
    if civilian:
        actor.require("civ.use")
    vals = await _vehicle_values(s, data)
    if not vals.get("plate"):
        raise ValidationFailed("License plate is required.")
    if civilian and vals.get("owner_person_id"):
        owner = await s.get(Person, vals["owner_person_id"])
        if owner.owner_user_id != actor.user_id:
            raise Forbidden("Civilians can only register vehicles to their own characters.")
    dup = (await s.execute(select(Vehicle.id).where(Vehicle.plate == vals["plate"], Vehicle.is_archived.is_(False)))).scalar()
    if dup:
        raise ValidationFailed(f"A vehicle with plate {vals['plate']} already exists.")
    if vals.get("owner_person_id") and not vals.get("owner_name"):
        vals["owner_name"] = (await s.get(Person, vals["owner_person_id"])).full_name
    v = Vehicle(number=await next_number(s, "vehicle"), created_by=actor.user_id,
                owner_user_id=actor.user_id if civilian else None, **vals)
    s.add(v)
    await s.flush()
    await _revision(s, actor, "vehicle", v.id, "created", {}, _snap(v, VEHICLE_FIELDS))
    await audit(s, actor, "mdt", "vehicle.created", target_type="vehicle", target_id=v.id, target_ref=v.plate)
    emit(s, "record.changed", {"type": "vehicle", "id": v.id}, origin=actor.source)
    return v


async def update_vehicle(s: AsyncSession, actor: Actor, vid: int, data: dict[str, Any]) -> Vehicle:
    v = await s.get(Vehicle, vid)
    if v is None:
        raise NotFound("Vehicle record not found.")
    _check_edit(actor, v.owner_user_id)
    old = _snap(v, VEHICLE_FIELDS)
    vals = await _vehicle_values(s, data)
    if "plate" in vals and vals["plate"] != v.plate:
        dup = (await s.execute(select(Vehicle.id).where(Vehicle.plate == vals["plate"], Vehicle.id != v.id,
                                                        Vehicle.is_archived.is_(False)))).scalar()
        if dup:
            raise ValidationFailed(f"A vehicle with plate {vals['plate']} already exists.")
    for k, val in vals.items():
        setattr(v, k, val)
    new = _snap(v, VEHICLE_FIELDS)
    await _revision(s, actor, "vehicle", v.id, "updated", old, new)
    if old != new:
        await audit(s, actor, "mdt", "vehicle.updated", target_type="vehicle", target_id=v.id, target_ref=v.plate,
                    old={k: old[k] for k in new if old[k] != new[k]}, new={k: new[k] for k in new if old[k] != new[k]})
        emit(s, "record.changed", {"type": "vehicle", "id": v.id}, origin=actor.source)
    return v


async def vehicle_profile(s: AsyncSession, actor: Actor, vid: int) -> dict[str, Any]:
    v = await s.get(Vehicle, vid)
    if v is None or (v.is_archived and not actor.can("cad.records.archive")):
        raise NotFound("Vehicle record not found.")
    if not actor.can("cad.records.search") and v.owner_user_id != actor.user_id:
        raise Forbidden("You cannot view this record.")
    d = vehicle_dict(v)
    d["owner"] = person_dict(await s.get(Person, v.owner_person_id), full=False) if v.owner_person_id else None
    d["traffic_stops"] = [traffic_dict(t) for t in (await s.execute(
        select(TrafficStop).where(or_(TrafficStop.vehicle_id == v.id, TrafficStop.plate == v.plate))
        .order_by(TrafficStop.started_at.desc()).limit(25))).scalars()]
    d["bolos"] = [bolo_dict(b) for b in (await s.execute(
        select(Bolo).where(or_(Bolo.vehicle_id == v.id, Bolo.plate == v.plate)).order_by(Bolo.id.desc()))).scalars()]
    from nexus.services.incidents import linked_records

    d["links"] = await linked_records(s, "vehicle", v.id)
    d["history"] = await revisions(s, "vehicle", v.id)
    return d


async def plate_check(s: AsyncSession, actor: Actor, plate: str) -> dict[str, Any]:
    """Quick MDT plate check: vehicle record + active BOLOs + flags."""
    actor.require("cad.records.search")
    p = norm_plate(plate)
    if not p:
        raise ValidationFailed("Enter a plate.")
    v = (await s.execute(select(Vehicle).where(Vehicle.plate == p, Vehicle.is_archived.is_(False)))).scalar_one_or_none()
    bolos = (await s.execute(select(Bolo).where(Bolo.status.in_(("active", "updated")),
                                                or_(Bolo.plate == p, Bolo.vehicle_id == (v.id if v else -1))))).scalars().all()
    alerts = []
    if v and v.registration_status != "Valid":
        alerts.append(f"Registration: {v.registration_status}")
    if v and v.insurance_status != "Valid":
        alerts.append(f"Insurance: {v.insurance_status}")
    if v:
        alerts += [f"Flag: {f}" for f in v.flags or []]
    alerts += [f"Active BOLO {b.number}" for b in bolos]
    await audit(s, actor, "mdt", "record.plate_check", target_type="vehicle", target_ref=p, context={"found": bool(v)})
    return {"plate": p, "vehicle": vehicle_dict(v) if v else None, "bolos": [bolo_dict(b) for b in bolos],
            "alerts": alerts, "record_type": DISCLAIMER}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def search_persons(s: AsyncSession, actor: Actor, q: str, *, limit: int = 25, include_archived: bool = False,
                         by: str = "any") -> list[dict[str, Any]]:
    if not actor.can("cad.records.search"):
        if not actor.can("civ.use"):
            raise Forbidden("You cannot search person records.")
        stmt = select(Person).where(Person.owner_user_id == actor.user_id)
    else:
        stmt = select(Person)
    q = (q or "").strip()
    fields = (await get_setting(s, "records.searchable_fields")).get("person", [])
    if q:
        like = f"%{q}%"
        conds = []
        if by in ("any", "name") and "name" in fields:
            conds += [Person.first_name.ilike(like), Person.last_name.ilike(like),
                      (Person.first_name + " " + Person.last_name).ilike(like)]
        if by in ("any", "number") and "number" in fields:
            conds.append(Person.number.ilike(like))
        if by in ("any", "roblox") and "roblox" in fields:
            conds.append(Person.roblox_username.ilike(like))
        if by in ("any", "alias") and "alias" in fields:
            conds.append(cast(Person.aliases, String).ilike(like))
        if by in ("any", "vehicle") and "vehicle" in fields:
            owner_ids = select(Vehicle.owner_person_id).where(Vehicle.plate.ilike(f"%{norm_plate(q)}%"))
            conds.append(Person.id.in_(owner_ids))
        if by == "discord":
            actor.require("cad.records.discord_lookup")
            conds = [Person.discord_id == q]
        if not conds:
            return []
        stmt = stmt.where(or_(*conds))
    if not include_archived:
        stmt = stmt.where(Person.is_archived.is_(False))
    rows = (await s.execute(stmt.order_by(Person.last_name, Person.first_name).limit(limit))).scalars()
    return [person_dict(p, full=False) for p in rows]


async def search_vehicles(s: AsyncSession, actor: Actor, q: str = "", *, color: str = "", registration: str = "",
                          limit: int = 25, include_archived: bool = False) -> list[dict[str, Any]]:
    if not actor.can("cad.records.search"):
        if not actor.can("civ.use"):
            raise Forbidden("You cannot search vehicle records.")
        stmt = select(Vehicle).where(Vehicle.owner_user_id == actor.user_id)
    else:
        stmt = select(Vehicle)
    q = (q or "").strip()
    fields = (await get_setting(s, "records.searchable_fields")).get("vehicle", [])
    if q:
        like = f"%{q}%"
        conds = []
        if "plate" in fields:
            conds.append(Vehicle.plate.ilike(f"%{norm_plate(q)}%"))
        if "owner" in fields:
            conds.append(Vehicle.owner_name.ilike(like))
        if "make" in fields:
            conds.append(Vehicle.make.ilike(like))
        if "model" in fields:
            conds.append(Vehicle.model.ilike(like))
        stmt = stmt.where(or_(*conds)) if conds else stmt
    if color:
        stmt = stmt.where(Vehicle.color.ilike(f"%{color}%"))
    if registration:
        stmt = stmt.where(Vehicle.registration_status == registration)
    if not include_archived:
        stmt = stmt.where(Vehicle.is_archived.is_(False))
    rows = (await s.execute(stmt.order_by(Vehicle.plate).limit(limit))).scalars()
    return [vehicle_dict(v, full=False) for v in rows]


# ---------------------------------------------------------------------------
# BOLOs
# ---------------------------------------------------------------------------

BOLO_FIELDS = ["category", "subject_description", "vehicle_description", "plate", "person_id", "vehicle_id",
               "last_known_location", "reason", "department_id", "expires_at"]
BOLO_STATUSES = ("active", "updated", "resolved", "expired", "cancelled")


def bolo_dict(b: Bolo) -> dict[str, Any]:
    return {"id": b.id, "number": b.number, "category": b.category, "subject_description": b.subject_description,
            "vehicle_description": b.vehicle_description, "plate": b.plate, "person_id": b.person_id,
            "vehicle_id": b.vehicle_id, "last_known_location": b.last_known_location, "reason": b.reason,
            "department_id": b.department_id, "issued_by": b.issued_by, "status": b.status,
            "is_active": b.status in ("active", "updated"), "expires_at": b.expires_at, "created_at": b.created_at,
            "updated_at": b.updated_at, "closed_at": b.closed_at, "record_type": DISCLAIMER}


async def _bolo_values(s: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in BOLO_FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f == "category" and v not in ("person", "vehicle", "general"):
            raise ValidationFailed("BOLO category must be person, vehicle or general.")
        if f == "plate":
            v = norm_plate(v)
        if f in ("person_id", "vehicle_id", "department_id"):
            v = int(v) if v not in (None, "") else None
            model = {"person_id": Person, "vehicle_id": Vehicle, "department_id": Department}[f]
            if v is not None and await s.get(model, v) is None:
                raise ValidationFailed(f"{f.replace('_id', '').title()} not found.")
        if f == "expires_at" and isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None
        if isinstance(v, str):
            v = v.strip()[:2000 if f == "reason" else 400]
        out[f] = v
    return out


async def create_bolo(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Bolo:
    actor.require("cad.bolo.manage")
    vals = await _bolo_values(s, data)
    vals.setdefault("category", "general")
    if not (vals.get("subject_description") or vals.get("vehicle_description") or vals.get("plate")):
        raise ValidationFailed("Describe the subject or vehicle for the BOLO.")
    if not vals.get("reason"):
        raise ValidationFailed("A BOLO needs a reason.")
    if vals.get("vehicle_id") and not vals.get("plate"):
        vals["plate"] = (await s.get(Vehicle, vals["vehicle_id"])).plate
    if "expires_at" not in vals:
        hours = int(await get_setting(s, "bolo.default_expiry_hours") or 0)
        vals["expires_at"] = utcnow() + timedelta(hours=hours) if hours else None
    b = Bolo(number=await next_number(s, "bolo"), issued_by=actor.user_id, status="active", **vals)
    s.add(b)
    await s.flush()
    await _revision(s, actor, "bolo", b.id, "created", {}, _snap(b, BOLO_FIELDS))
    await audit(s, actor, "cad", "bolo.created", target_type="bolo", target_id=b.id, target_ref=b.number,
                department_id=b.department_id, new={"category": b.category, "reason": b.reason[:200]})
    emit(s, "bolo.created", {"id": b.id, "number": b.number, "category": b.category, "plate": b.plate,
                             "subject": b.subject_description[:200], "vehicle": b.vehicle_description[:200],
                             "reason": b.reason[:200], "location": b.last_known_location}, origin=actor.source)
    await notifications.notify(s, "bolo.created", f"New BOLO {b.number}",
                               (b.subject_description or b.vehicle_description or b.plate)[:200] + f" — {b.reason[:150]}",
                               audience="perm:cad.records.search", link=f"/#/records/bolo/{b.id}", severity="warning")
    return b


async def update_bolo(s: AsyncSession, actor: Actor, bid: int, data: dict[str, Any]) -> Bolo:
    actor.require("cad.bolo.manage")
    b = await s.get(Bolo, bid)
    if b is None:
        raise NotFound("BOLO not found.")
    old = _snap(b, BOLO_FIELDS + ["status"])
    for k, v in (await _bolo_values(s, data)).items():
        setattr(b, k, v)
    status = data.get("status")
    if status:
        if status not in BOLO_STATUSES:
            raise ValidationFailed("Invalid BOLO status.")
        b.status = status
        if status in ("resolved", "expired", "cancelled"):
            b.closed_at = utcnow()
        else:
            b.closed_at = None
    elif b.status == "active" and old != _snap(b, BOLO_FIELDS + ["status"]):
        b.status = "updated"
    new = _snap(b, BOLO_FIELDS + ["status"])
    await _revision(s, actor, "bolo", b.id, "updated", old, new)
    await audit(s, actor, "cad", "bolo.updated", target_type="bolo", target_id=b.id, target_ref=b.number,
                old={k: old[k] for k in new if old[k] != new[k]}, new={k: new[k] for k in new if old[k] != new[k]})
    emit(s, "bolo.changed", {"id": b.id, "number": b.number, "status": b.status}, origin=actor.source)
    return b


async def list_bolos(s: AsyncSession, actor: Actor, *, status: str = "active", q: str = "", category: str = "",
                     limit: int = 100) -> list[dict[str, Any]]:
    actor.require("cad.records.search")
    stmt = select(Bolo).order_by(Bolo.id.desc())
    if status == "active":
        stmt = stmt.where(Bolo.status.in_(("active", "updated")))
    elif status and status != "all":
        stmt = stmt.where(Bolo.status == status)
    if category:
        stmt = stmt.where(Bolo.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Bolo.number.ilike(like), Bolo.subject_description.ilike(like),
                              Bolo.vehicle_description.ilike(like), Bolo.plate.ilike(f"%{norm_plate(q)}%"),
                              Bolo.reason.ilike(like), Bolo.last_known_location.ilike(like)))
    return [bolo_dict(b) for b in (await s.execute(stmt.limit(limit))).scalars()]


async def expire_bolos(s: AsyncSession) -> list[Bolo]:
    """Expire overdue BOLOs and send expiry notifications. Called periodically."""
    from nexus.core.context import SYSTEM

    now = utcnow()
    due = (await s.execute(select(Bolo).where(Bolo.status.in_(("active", "updated")), Bolo.expires_at.is_not(None),
                                              Bolo.expires_at <= now))).scalars().all()
    for b in due:
        b.status = "expired"
        b.closed_at = now
        await _revision(s, SYSTEM, "bolo", b.id, "updated", {"status": "active"}, {"status": "expired"})
        emit(s, "bolo.expired", {"id": b.id, "number": b.number}, origin="system")
        await notifications.notify(s, "bolo.expired", f"BOLO {b.number} expired", b.reason[:200],
                                   audience="perm:cad.bolo.manage", link=f"/#/records/bolo/{b.id}")
    soon = (await s.execute(select(Bolo).where(Bolo.status.in_(("active", "updated")), Bolo.expiry_alerted.is_(False),
                                               Bolo.expires_at.is_not(None), Bolo.expires_at <= now + timedelta(hours=1)))).scalars().all()
    for b in soon:
        b.expiry_alerted = True
        await notifications.notify(s, "bolo.expired", f"BOLO {b.number} expires within an hour", b.reason[:200],
                                   audience="perm:cad.bolo.manage", link=f"/#/records/bolo/{b.id}",
                                   dedupe_key=f"bolo-soon:{b.id}")
    return due


# ---------------------------------------------------------------------------
# Cases & warrants
# ---------------------------------------------------------------------------

WARRANT_STATUSES = ("active", "served", "recalled", "expired")
CASE_STATUSES = ("open", "active", "closed", "archived")


def warrant_dict(w: Warrant) -> dict[str, Any]:
    return {"id": w.id, "number": w.number, "warrant_type": w.warrant_type, "case_id": w.case_id, "person_id": w.person_id,
            "vehicle_id": w.vehicle_id, "subject_name": w.subject_name, "charges": w.charges, "description": w.description,
            "department_id": w.department_id, "issued_by": w.issued_by, "status": w.status, "expires_at": w.expires_at,
            "created_at": w.created_at, "updated_at": w.updated_at, "record_type": DISCLAIMER}


def case_dict(c: Case) -> dict[str, Any]:
    return {"id": c.id, "number": c.number, "title": c.title, "summary": c.summary, "status": c.status,
            "department_id": c.department_id, "lead_user_id": c.lead_user_id, "created_by": c.created_by,
            "restricted": c.restricted, "created_at": c.created_at, "updated_at": c.updated_at, "closed_at": c.closed_at,
            "record_type": DISCLAIMER}


async def create_case(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Case:
    actor.require("cad.warrants.manage")
    title = (data.get("title") or "").strip()
    if not title:
        raise ValidationFailed("Case title is required.")
    c = Case(number=await next_number(s, "case"), title=title[:160], summary=(data.get("summary") or "")[:4000],
             department_id=data.get("department_id") or None, lead_user_id=data.get("lead_user_id") or actor.user_id,
             created_by=actor.user_id, restricted=bool(data.get("restricted")), status="open")
    s.add(c)
    await s.flush()
    await _revision(s, actor, "case", c.id, "created", {}, case_dict(c))
    await audit(s, actor, "mdt", "case.created", target_type="case", target_id=c.id, target_ref=c.number)
    return c


async def update_case(s: AsyncSession, actor: Actor, cid: int, data: dict[str, Any]) -> Case:
    actor.require("cad.warrants.manage")
    c = await s.get(Case, cid)
    if c is None:
        raise NotFound("Case not found.")
    old = {k: v for k, v in case_dict(c).items() if k in ("title", "summary", "status", "lead_user_id", "restricted")}
    for f in ("title", "summary", "lead_user_id", "restricted", "department_id"):
        if f in data:
            setattr(c, f, data[f])
    if "status" in data:
        if data["status"] not in CASE_STATUSES:
            raise ValidationFailed("Invalid case status.")
        c.status = data["status"]
        c.closed_at = utcnow() if c.status in ("closed", "archived") else None
    new = {k: v for k, v in case_dict(c).items() if k in old}
    await _revision(s, actor, "case", c.id, "updated", old, new)
    await audit(s, actor, "mdt", "case.updated", target_type="case", target_id=c.id, target_ref=c.number, old=old, new=new)
    return c


async def add_case_note(s: AsyncSession, actor: Actor, cid: int, body: str) -> CaseNote:
    actor.require("cad.warrants.manage")
    if await s.get(Case, cid) is None:
        raise NotFound("Case not found.")
    if not (body or "").strip():
        raise ValidationFailed("Note text is required.")
    n = CaseNote(case_id=cid, user_id=actor.user_id, body=body.strip()[:4000])
    s.add(n)
    await _revision(s, actor, "case", cid, "note", {}, {"note": body[:200]})
    return n


async def case_detail(s: AsyncSession, actor: Actor, cid: int) -> dict[str, Any]:
    actor.require("cad.warrants.view")
    c = await s.get(Case, cid)
    if c is None:
        raise NotFound("Case not found.")
    if c.restricted and not actor.can("cad.warrants.manage"):
        raise Forbidden("This case is restricted.")
    d = case_dict(c)
    notes = (await s.execute(select(CaseNote, User.display_name).outerjoin(User, User.id == CaseNote.user_id)
                             .where(CaseNote.case_id == cid).order_by(CaseNote.id))).all()
    d["notes"] = [{"id": n.id, "body": n.body, "user": name, "created_at": n.created_at} for n, name in notes]
    d["warrants"] = [warrant_dict(w) for w in (await s.execute(select(Warrant).where(Warrant.case_id == cid))).scalars()]
    from nexus.services.incidents import linked_records

    d["links"] = await linked_records(s, "case", cid)
    d["history"] = await revisions(s, "case", cid)
    return d


async def list_cases(s: AsyncSession, actor: Actor, *, status: str = "", q: str = "", limit: int = 100) -> list[dict]:
    actor.require("cad.warrants.view")
    stmt = select(Case).order_by(Case.id.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    if q:
        stmt = stmt.where(or_(Case.number.ilike(f"%{q}%"), Case.title.ilike(f"%{q}%")))
    if not actor.can("cad.warrants.manage"):
        stmt = stmt.where(Case.restricted.is_(False))
    return [case_dict(c) for c in (await s.execute(stmt.limit(limit))).scalars()]


async def create_warrant(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Warrant:
    actor.require("cad.warrants.manage")
    wtype = data.get("warrant_type", "arrest")
    if wtype not in ("arrest", "search", "bench"):
        raise ValidationFailed("Warrant type must be arrest, search or bench.")
    person_id = data.get("person_id") or None
    person = await s.get(Person, int(person_id)) if person_id else None
    if person_id and person is None:
        raise ValidationFailed("Person record not found.")
    subject = (data.get("subject_name") or (person.full_name if person else "")).strip()
    if not subject:
        raise ValidationFailed("A warrant needs a subject (person record or name).")
    if not (data.get("charges") or data.get("description")):
        raise ValidationFailed("Provide charges or a description.")
    exp = data.get("expires_at")
    w = Warrant(number=await next_number(s, "warrant"), warrant_type=wtype, case_id=data.get("case_id") or None,
                person_id=person.id if person else None, vehicle_id=data.get("vehicle_id") or None, subject_name=subject[:120],
                charges=(data.get("charges") or "")[:2000], description=(data.get("description") or "")[:4000],
                department_id=data.get("department_id") or None, issued_by=actor.user_id, status="active",
                expires_at=datetime.fromisoformat(exp.replace("Z", "+00:00")) if isinstance(exp, str) and exp else None)
    s.add(w)
    await s.flush()
    await _revision(s, actor, "warrant", w.id, "created", {}, warrant_dict(w))
    await audit(s, actor, "mdt", "warrant.created", target_type="warrant", target_id=w.id, target_ref=w.number,
                new={"subject": w.subject_name, "type": wtype})
    emit(s, "record.changed", {"type": "warrant", "id": w.id}, origin=actor.source)
    return w


async def update_warrant(s: AsyncSession, actor: Actor, wid: int, data: dict[str, Any]) -> Warrant:
    actor.require("cad.warrants.manage")
    w = await s.get(Warrant, wid)
    if w is None:
        raise NotFound("Warrant not found.")
    old = {k: getattr(w, k) for k in ("status", "charges", "description", "subject_name")}
    if "status" in data:
        if data["status"] not in WARRANT_STATUSES:
            raise ValidationFailed("Invalid warrant status.")
        w.status = data["status"]
    for f in ("charges", "description", "subject_name"):
        if f in data:
            setattr(w, f, (data[f] or "")[:4000])
    new = {k: getattr(w, k) for k in old}
    await _revision(s, actor, "warrant", w.id, "updated", old, new)
    await audit(s, actor, "mdt", "warrant.updated", target_type="warrant", target_id=w.id, target_ref=w.number, old=old, new=new)
    return w


async def list_warrants(s: AsyncSession, actor: Actor, *, status: str = "active", q: str = "", limit: int = 100) -> list[dict]:
    actor.require("cad.warrants.view")
    stmt = select(Warrant).order_by(Warrant.id.desc())
    if status and status != "all":
        stmt = stmt.where(Warrant.status == status)
    if q:
        stmt = stmt.where(or_(Warrant.number.ilike(f"%{q}%"), Warrant.subject_name.ilike(f"%{q}%"),
                              Warrant.charges.ilike(f"%{q}%")))
    return [warrant_dict(w) for w in (await s.execute(stmt.limit(limit))).scalars()]


# ---------------------------------------------------------------------------
# Traffic stops
# ---------------------------------------------------------------------------

TRAFFIC_FIELDS = ["driver_name", "driver_person_id", "vehicle_id", "plate", "vehicle_description", "location", "map_x",
                  "map_z", "reason", "passengers", "notes", "outcome", "incident_id"]
TRAFFIC_OUTCOMES = ("Verbal Warning", "Written Warning", "Citation", "Arrest", "No Action", "Other")


def traffic_dict(t: TrafficStop) -> dict[str, Any]:
    return {"id": t.id, "number": t.number, "officer_user_id": t.officer_user_id, "unit_id": t.unit_id,
            "callsign": t.callsign, "department_id": t.department_id, "driver_name": t.driver_name,
            "driver_person_id": t.driver_person_id, "vehicle_id": t.vehicle_id, "plate": t.plate,
            "vehicle_description": t.vehicle_description, "location": t.location, "map_x": t.map_x, "map_z": t.map_z,
            "reason": t.reason, "passengers": t.passengers, "notes": t.notes, "outcome": t.outcome, "status": t.status,
            "incident_id": t.incident_id, "started_at": t.started_at, "ended_at": t.ended_at, "record_type": DISCLAIMER}


async def _traffic_values(s: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in TRAFFIC_FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f == "plate":
            v = norm_plate(v)
        elif f in ("driver_person_id", "vehicle_id", "incident_id"):
            v = int(v) if v not in (None, "") else None
            model = {"driver_person_id": Person, "vehicle_id": Vehicle, "incident_id": Incident}[f]
            if v is not None and await s.get(model, v) is None:
                raise ValidationFailed(f"Linked {f.replace('_id', '').replace('_', ' ')} not found.")
        elif f in ("map_x", "map_z"):
            v = float(v) if v not in (None, "") else None
        elif f == "outcome" and v and v not in TRAFFIC_OUTCOMES:
            raise ValidationFailed(f"Outcome must be one of: {', '.join(TRAFFIC_OUTCOMES)}.")
        elif isinstance(v, str):
            v = v.strip()[:2000 if f == "notes" else 300]
        out[f] = v
    return out


async def start_traffic_stop(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> TrafficStop:
    actor.require("cad.traffic.manage")
    vals = await _traffic_values(s, data)
    if not (vals.get("plate") or vals.get("vehicle_id") or vals.get("vehicle_description")):
        raise ValidationFailed("Enter the plate or describe the vehicle.")
    if not vals.get("location"):
        raise ValidationFailed("Enter the stop location.")
    from nexus.services.units import my_units

    mine = await my_units(s, actor)
    unit: Unit | None = mine[0] if mine else None
    if vals.get("plate") and not vals.get("vehicle_id"):
        v = (await s.execute(select(Vehicle).where(Vehicle.plate == vals["plate"], Vehicle.is_archived.is_(False)))).scalar_one_or_none()
        if v:
            vals["vehicle_id"] = v.id
            vals.setdefault("vehicle_description", f"{v.color} {v.make} {v.model}".strip())
            if not vals.get("driver_person_id") and not vals.get("driver_name"):
                vals["driver_name"] = v.owner_name
                if v.owner_person_id:
                    vals["driver_person_id"] = v.owner_person_id
    t = TrafficStop(number=await next_number(s, "traffic"), officer_user_id=actor.user_id,
                    unit_id=unit.id if unit else None, callsign=data.get("callsign") or (unit.callsign if unit else ""),
                    department_id=unit.department_id if unit else (min(actor.department_ids) if actor.department_ids else None),
                    status="active", **vals)
    s.add(t)
    await s.flush()
    await audit(s, actor, "cad", "traffic.started", target_type="traffic", target_id=t.id, target_ref=t.number,
                new={"plate": t.plate, "location": t.location})
    emit(s, "traffic.changed", {"id": t.id, "number": t.number, "status": "active", "callsign": t.callsign,
                                "plate": t.plate, "location": t.location}, origin=actor.source)
    return t


async def _get_stop_for_edit(s: AsyncSession, actor: Actor, tid: int) -> TrafficStop:
    t = await s.get(TrafficStop, tid)
    if t is None:
        raise NotFound("Traffic stop not found.")
    if t.officer_user_id != actor.user_id and not (actor.can("cad.dispatch") or actor.can("cad.reports.review")):
        raise Forbidden("Only the officer who opened this stop (or a supervisor/dispatcher) can change it.")
    return t


async def update_traffic_stop(s: AsyncSession, actor: Actor, tid: int, data: dict[str, Any]) -> TrafficStop:
    if not actor.can("cad.dispatch"):
        actor.require("cad.traffic.manage")
    t = await _get_stop_for_edit(s, actor, tid)
    old = _snap(t, TRAFFIC_FIELDS)
    for k, v in (await _traffic_values(s, data)).items():
        setattr(t, k, v)
    new = _snap(t, TRAFFIC_FIELDS)
    await _revision(s, actor, "traffic", t.id, "updated", old, new)
    emit(s, "traffic.changed", {"id": t.id, "number": t.number, "status": t.status}, origin=actor.source)
    return t


async def end_traffic_stop(s: AsyncSession, actor: Actor, tid: int, *, outcome: str = "", notes: str = "",
                           cancel: bool = False) -> TrafficStop:
    t = await _get_stop_for_edit(s, actor, tid)
    if t.status != "active":
        raise ValidationFailed(f"Traffic stop {t.number} is already {t.status}.")
    if outcome and outcome not in TRAFFIC_OUTCOMES:
        raise ValidationFailed(f"Outcome must be one of: {', '.join(TRAFFIC_OUTCOMES)}.")
    if not cancel and not (outcome or t.outcome):
        raise ValidationFailed("Select an outcome to complete the stop.")
    t.status = "cancelled" if cancel else "completed"
    t.outcome = outcome or t.outcome
    if notes:
        t.notes = ((t.notes + "\n") if t.notes else "") + notes.strip()[:1000]
    t.ended_at = utcnow()
    await audit(s, actor, "cad", f"traffic.{t.status}", target_type="traffic", target_id=t.id, target_ref=t.number,
                new={"outcome": t.outcome})
    emit(s, "traffic.changed", {"id": t.id, "number": t.number, "status": t.status}, origin=actor.source)
    return t


async def list_traffic_stops(s: AsyncSession, actor: Actor, *, status: str = "", mine: bool = False, q: str = "",
                             limit: int = 100) -> list[dict]:
    if not (actor.can("cad.traffic.manage") or actor.can("cad.dispatch")):
        raise Forbidden("You cannot view traffic stops.")
    stmt = select(TrafficStop).order_by(TrafficStop.started_at.desc())
    if status:
        stmt = stmt.where(TrafficStop.status == status)
    if mine:
        stmt = stmt.where(TrafficStop.officer_user_id == actor.user_id)
    if q:
        stmt = stmt.where(or_(TrafficStop.number.ilike(f"%{q}%"), TrafficStop.plate.ilike(f"%{norm_plate(q)}%"),
                              TrafficStop.driver_name.ilike(f"%{q}%"), TrafficStop.location.ilike(f"%{q}%")))
    return [traffic_dict(t) for t in (await s.execute(stmt.limit(limit))).scalars()]


async def link(s: AsyncSession, actor: Actor, a_type: str, a_id: int, b_type: str, b_id: int, note: str = "") -> RecordLink:
    if not actor.can("cad.records.edit"):
        raise Forbidden("You cannot link records.")
    if not await record_label(s, a_type, a_id) or not await record_label(s, b_type, b_id):
        raise NotFound("Record not found.")
    existing = (await s.execute(select(RecordLink).where(
        RecordLink.source_type == a_type, RecordLink.source_id == a_id, RecordLink.target_type == b_type,
        RecordLink.target_id == b_id))).scalar_one_or_none()
    if existing:
        return existing
    r = RecordLink(source_type=a_type, source_id=a_id, target_type=b_type, target_id=b_id, note=note[:200],
                   created_by=actor.user_id)
    s.add(r)
    await audit(s, actor, "mdt", "record.linked", target_type=a_type, target_id=a_id, new={"type": b_type, "id": b_id})
    return r
