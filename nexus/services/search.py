"""Central permission-aware search across all record types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, ValidationFailed
from nexus.db.models import (
    Bolo,
    Department,
    Incident,
    Person,
    Report,
    SearchHistory,
    TrafficStop,
    Unit,
    User,
    Vehicle,
)
from nexus.services.records import norm_plate

SCOPES = {
    "incidents": "cad.view", "people": "cad.records.search", "vehicles": "cad.records.search",
    "bolos": "cad.records.search", "traffic": "cad.traffic.manage", "reports": "cad.reports.create",
    "units": "cad.view", "personnel": "dept.view", "departments": "dept.view",
}


async def search(s: AsyncSession, actor: Actor, q: str, *, scopes: list[str] | None = None, exact: bool = False,
                 department_id: int | None = None, status: str = "", date_from: datetime | None = None,
                 date_to: datetime | None = None, limit: int = 10, save_history: bool = True) -> dict[str, Any]:
    q = (q or "").strip()
    if len(q) < 2:
        raise ValidationFailed("Search for at least 2 characters.")
    allowed = [sc for sc in (scopes or list(SCOPES)) if sc in SCOPES and actor.can(SCOPES[sc])]
    like = q if exact else f"%{q}%"

    def m(col):
        return col.ilike(like) if not exact else col.ilike(q)

    def dates(stmt, col):
        if date_from:
            stmt = stmt.where(col >= date_from)
        if date_to:
            stmt = stmt.where(col <= date_to)
        return stmt

    results: dict[str, list[dict[str, Any]]] = {}
    if "incidents" in allowed:
        stmt = select(Incident).where(or_(m(Incident.number), m(Incident.description), m(Incident.location_name),
                                          m(Incident.street), m(Incident.caller_name)), Incident.is_archived.is_(False))
        if department_id:
            stmt = stmt.where(Incident.department_id == department_id)
        if status:
            stmt = stmt.where(Incident.status == status)
        stmt = dates(stmt, Incident.created_at)
        results["incidents"] = [{"id": i.id, "title": i.number, "summary": f"P{i.priority} · {i.category} · "
                                 f"{i.location_name or i.street} — {(i.description or '')[:80]}", "status": i.status,
                                 "link": f"/#/cad/incident/{i.id}", "date": i.created_at}
                                for i in (await s.execute(stmt.order_by(Incident.id.desc()).limit(limit))).scalars()]
    if "people" in allowed:
        stmt = select(Person).where(or_(m(Person.first_name), m(Person.last_name), m(Person.number),
                                        m(Person.first_name + " " + Person.last_name), m(Person.roblox_username)),
                                    Person.is_archived.is_(False))
        results["people"] = [{"id": p.id, "title": p.full_name, "summary": f"{p.number} · DOB {p.date_of_birth or '—'} · "
                              f"License {p.license_status}" + (f" · Flags: {', '.join(p.flags)}" if p.flags else ""),
                              "link": f"/#/records/person/{p.id}", "date": p.updated_at}
                             for p in (await s.execute(stmt.limit(limit))).scalars()]
    if "vehicles" in allowed:
        plate_like = norm_plate(q) if exact else f"%{norm_plate(q)}%"
        stmt = select(Vehicle).where(or_(Vehicle.plate.ilike(plate_like), m(Vehicle.make), m(Vehicle.model),
                                         m(Vehicle.owner_name), m(Vehicle.number)), Vehicle.is_archived.is_(False))
        results["vehicles"] = [{"id": v.id, "title": v.plate, "summary": f"{v.color} {v.make} {v.model} · Owner "
                                f"{v.owner_name or '—'} · Reg {v.registration_status}", "link": f"/#/records/vehicle/{v.id}",
                                "date": v.updated_at} for v in (await s.execute(stmt.limit(limit))).scalars()]
    if "bolos" in allowed:
        stmt = select(Bolo).where(or_(m(Bolo.number), m(Bolo.subject_description), m(Bolo.vehicle_description),
                                      m(Bolo.reason), Bolo.plate.ilike(f"%{norm_plate(q)}%")))
        if status:
            stmt = stmt.where(Bolo.status == status)
        stmt = dates(stmt, Bolo.created_at)
        results["bolos"] = [{"id": b.id, "title": b.number, "summary": f"{b.category} · {b.status} · {b.reason[:90]}",
                             "status": b.status, "link": f"/#/records/bolo/{b.id}", "date": b.created_at}
                            for b in (await s.execute(stmt.order_by(Bolo.id.desc()).limit(limit))).scalars()]
    if "traffic" in allowed:
        stmt = select(TrafficStop).where(or_(m(TrafficStop.number), TrafficStop.plate.ilike(f"%{norm_plate(q)}%"),
                                             m(TrafficStop.driver_name), m(TrafficStop.location)))
        stmt = dates(stmt, TrafficStop.started_at)
        results["traffic"] = [{"id": t.id, "title": t.number, "summary": f"{t.plate} · {t.driver_name or '—'} · "
                               f"{t.location} · {t.outcome or t.status}", "status": t.status,
                               "link": f"/#/cad/traffic/{t.id}", "date": t.started_at}
                              for t in (await s.execute(stmt.order_by(TrafficStop.id.desc()).limit(limit))).scalars()]
    if "reports" in allowed:
        stmt = select(Report).where(or_(m(Report.number), m(Report.title), m(Report.summary), m(Report.location)))
        if not (actor.can("cad.reports.view_all") or actor.can("cad.reports.review")):
            stmt = stmt.where(Report.author_user_id == actor.user_id)
        if department_id:
            stmt = stmt.where(Report.department_id == department_id)
        stmt = dates(stmt, Report.created_at)
        results["reports"] = [{"id": r.id, "title": r.number, "summary": f"{r.title} · {r.status}", "status": r.status,
                               "link": f"/#/records/report/{r.id}", "date": r.created_at}
                              for r in (await s.execute(stmt.order_by(Report.id.desc()).limit(limit))).scalars()]
    if "units" in allowed:
        stmt = select(Unit).where(or_(m(Unit.callsign), m(Unit.vehicle_description)), Unit.is_archived.is_(False))
        if department_id:
            stmt = stmt.where(Unit.department_id == department_id)
        results["units"] = [{"id": u.id, "title": u.callsign, "summary": f"{u.unit_type} · {u.status}",
                             "link": "/#/cad/units", "date": u.updated_at} for u in (await s.execute(stmt.limit(limit))).scalars()]
    if "personnel" in allowed:
        stmt = select(User).where(or_(m(User.display_name), m(User.username), m(User.roblox_username)))
        results["personnel"] = [{"id": u.id, "title": u.name, "summary": f"Discord {u.username or u.discord_id}",
                                 "link": f"/#/departments/personnel/{u.id}", "date": u.last_login_at}
                                for u in (await s.execute(stmt.limit(limit))).scalars()]
    if "departments" in allowed:
        stmt = select(Department).where(or_(m(Department.name), m(Department.abbreviation)))
        results["departments"] = [{"id": d.id, "title": d.abbreviation, "summary": d.name, "link": f"/#/departments/{d.id}",
                                   "date": None} for d in (await s.execute(stmt.limit(limit))).scalars()]
    total = sum(len(v) for v in results.values())
    if save_history and actor.user_id:
        s.add(SearchHistory(user_id=actor.user_id, query=q[:120], scopes=allowed, result_count=total))
    if any(k in results for k in ("people", "vehicles")):
        await audit(s, actor, "mdt", "record.search", target_type="search", target_ref=q[:60],
                    context={"scopes": allowed, "results": total})
    return {"query": q, "scopes": allowed, "total": total, "results": results}


async def recent_searches(s: AsyncSession, actor: Actor, limit: int = 10) -> list[dict[str, Any]]:
    if not actor.user_id:
        return []
    rows = (await s.execute(select(SearchHistory).where(SearchHistory.user_id == actor.user_id)
                            .order_by(SearchHistory.id.desc()).limit(limit * 3))).scalars()
    seen, out = set(), []
    for r in rows:
        if r.query.lower() in seen:
            continue
        seen.add(r.query.lower())
        out.append({"query": r.query, "results": r.result_count, "created_at": r.created_at})
        if len(out) >= limit:
            break
    return out
