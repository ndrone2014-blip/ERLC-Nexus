"""Records (MDT) routes: persons, vehicles, BOLOs, warrants, cases, reports, search."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import current_actor, db_session, require, require_any
from nexus.core.context import Actor, NotFound
from nexus.db.models import Bolo, Warrant
from nexus.services import records, reports, search as search_svc

router = APIRouter(prefix="/api")


# ---- persons ------------------------------------------------------------------------

@router.get("/records/persons")
async def persons(q: str = "", by: str = "any", include_archived: bool = False, limit: int = 25,
                  actor: Actor = Depends(require_any("cad.records.search", "civ.use")), s: AsyncSession = Depends(db_session)):
    res = await records.search_persons(s, actor, q, by=by, include_archived=include_archived, limit=min(limit, 100))
    await s.commit()
    return res


@router.post("/records/persons")
async def create_person(body: dict = Body(...), actor: Actor = Depends(require_any("cad.records.edit", "civ.use")),
                        s: AsyncSession = Depends(db_session)):
    p = await records.create_person(s, actor, body)
    await s.commit()
    return records.person_dict(p)


@router.get("/records/persons/{pid}")
async def person(pid: int, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await records.person_profile(s, actor, pid)


@router.patch("/records/persons/{pid}")
async def update_person(pid: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                        s: AsyncSession = Depends(db_session)):
    p = await records.update_person(s, actor, pid, body)
    await s.commit()
    return records.person_dict(p)


@router.post("/records/{rtype}/{rid}/archive")
async def archive(rtype: str, rid: int, body: dict = Body(default_factory=dict), actor: Actor = Depends(current_actor),
                  s: AsyncSession = Depends(db_session)):
    await records.set_archived(s, actor, rtype.rstrip("s"), rid, bool(body.get("archived", True)))
    await s.commit()
    return {"ok": True}


# ---- vehicles -----------------------------------------------------------------------

@router.get("/records/vehicles")
async def vehicles(q: str = "", color: str = "", registration: str = "", include_archived: bool = False, limit: int = 25,
                   actor: Actor = Depends(require_any("cad.records.search", "civ.use")), s: AsyncSession = Depends(db_session)):
    return await records.search_vehicles(s, actor, q, color=color, registration=registration,
                                         include_archived=include_archived, limit=min(limit, 100))


@router.post("/records/vehicles")
async def create_vehicle(body: dict = Body(...), actor: Actor = Depends(require_any("cad.records.edit", "civ.use")),
                         s: AsyncSession = Depends(db_session)):
    v = await records.create_vehicle(s, actor, body)
    await s.commit()
    return records.vehicle_dict(v)


@router.get("/records/vehicles/{vid}")
async def vehicle(vid: int, actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await records.vehicle_profile(s, actor, vid)


@router.patch("/records/vehicles/{vid}")
async def update_vehicle(vid: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                         s: AsyncSession = Depends(db_session)):
    v = await records.update_vehicle(s, actor, vid, body)
    await s.commit()
    return records.vehicle_dict(v)


@router.get("/records/plate/{plate}")
async def plate_check(plate: str, actor: Actor = Depends(require("cad.records.search")), s: AsyncSession = Depends(db_session)):
    res = await records.plate_check(s, actor, plate)
    await s.commit()
    return res


# ---- BOLOs --------------------------------------------------------------------------------

@router.get("/records/bolos")
async def bolos(status: str = "active", q: str = "", category: str = "", actor: Actor = Depends(require("cad.records.search")),
                s: AsyncSession = Depends(db_session)):
    return await records.list_bolos(s, actor, status=status, q=q, category=category)


@router.post("/records/bolos")
async def create_bolo(body: dict = Body(...), actor: Actor = Depends(require("cad.bolo.manage")),
                      s: AsyncSession = Depends(db_session)):
    b = await records.create_bolo(s, actor, body)
    await s.commit()
    return records.bolo_dict(b)


@router.get("/records/bolos/{bid}")
async def bolo(bid: int, actor: Actor = Depends(require("cad.records.search")), s: AsyncSession = Depends(db_session)):
    b = await s.get(Bolo, bid)
    if b is None:
        raise NotFound("BOLO not found.")
    from nexus.services.incidents import linked_records

    return {**records.bolo_dict(b), "history": await records.revisions(s, "bolo", bid),
            "links": await linked_records(s, "bolo", bid)}


@router.patch("/records/bolos/{bid}")
async def update_bolo(bid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.bolo.manage")),
                      s: AsyncSession = Depends(db_session)):
    b = await records.update_bolo(s, actor, bid, body)
    await s.commit()
    return records.bolo_dict(b)


# ---- warrants & cases ------------------------------------------------------------------------

@router.get("/records/warrants")
async def warrants(status: str = "active", q: str = "", actor: Actor = Depends(require("cad.warrants.view")),
                   s: AsyncSession = Depends(db_session)):
    return await records.list_warrants(s, actor, status=status, q=q)


@router.post("/records/warrants")
async def create_warrant(body: dict = Body(...), actor: Actor = Depends(require("cad.warrants.manage")),
                         s: AsyncSession = Depends(db_session)):
    w = await records.create_warrant(s, actor, body)
    await s.commit()
    return records.warrant_dict(w)


@router.get("/records/warrants/{wid}")
async def warrant(wid: int, actor: Actor = Depends(require("cad.warrants.view")), s: AsyncSession = Depends(db_session)):
    w = await s.get(Warrant, wid)
    if w is None:
        raise NotFound("Warrant not found.")
    return {**records.warrant_dict(w), "history": await records.revisions(s, "warrant", wid)}


@router.patch("/records/warrants/{wid}")
async def update_warrant(wid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.warrants.manage")),
                         s: AsyncSession = Depends(db_session)):
    w = await records.update_warrant(s, actor, wid, body)
    await s.commit()
    return records.warrant_dict(w)


@router.get("/records/cases")
async def cases(status: str = "", q: str = "", actor: Actor = Depends(require("cad.warrants.view")),
                s: AsyncSession = Depends(db_session)):
    return await records.list_cases(s, actor, status=status, q=q)


@router.post("/records/cases")
async def create_case(body: dict = Body(...), actor: Actor = Depends(require("cad.warrants.manage")),
                      s: AsyncSession = Depends(db_session)):
    c = await records.create_case(s, actor, body)
    await s.commit()
    return records.case_dict(c)


@router.get("/records/cases/{cid}")
async def case(cid: int, actor: Actor = Depends(require("cad.warrants.view")), s: AsyncSession = Depends(db_session)):
    return await records.case_detail(s, actor, cid)


@router.patch("/records/cases/{cid}")
async def update_case(cid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.warrants.manage")),
                      s: AsyncSession = Depends(db_session)):
    c = await records.update_case(s, actor, cid, body)
    await s.commit()
    return records.case_dict(c)


@router.post("/records/cases/{cid}/notes")
async def case_note(cid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.warrants.manage")),
                    s: AsyncSession = Depends(db_session)):
    await records.add_case_note(s, actor, cid, str(body.get("body", "")))
    await s.commit()
    return await records.case_detail(s, actor, cid)


@router.post("/records/link")
async def link(body: dict = Body(...), actor: Actor = Depends(require("cad.records.edit")), s: AsyncSession = Depends(db_session)):
    await records.link(s, actor, body["a_type"], int(body["a_id"]), body["b_type"], int(body["b_id"]), body.get("note", ""))
    await s.commit()
    return {"ok": True}


@router.get("/records/{rtype}/{rid}/history")
async def record_history(rtype: str, rid: int, actor: Actor = Depends(require("cad.records.search")),
                         s: AsyncSession = Depends(db_session)):
    return await records.revisions(s, rtype, rid)


# ---- central search ------------------------------------------------------------------------

@router.get("/search")
async def search(q: str, scopes: str = "", exact: bool = False, department_id: int | None = None, status: str = "",
                 date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 10,
                 actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    res = await search_svc.search(s, actor, q, scopes=[x for x in scopes.split(",") if x] or None, exact=exact,
                                  department_id=department_id, status=status, date_from=date_from, date_to=date_to,
                                  limit=min(limit, 50))
    await s.commit()
    return res


@router.get("/search/recent")
async def recent(actor: Actor = Depends(current_actor), s: AsyncSession = Depends(db_session)):
    return await search_svc.recent_searches(s, actor)


# ---- reports ------------------------------------------------------------------------------------

@router.get("/reports")
async def list_reports(q: str = "", status: str = "", mine: bool = False, department_id: int | None = None,
                       date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 50, offset: int = 0,
                       actor: Actor = Depends(require("cad.reports.create")), s: AsyncSession = Depends(db_session)):
    return await reports.search(s, actor, q=q, status=status, mine=mine, department_id=department_id,
                                date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/reports/export.csv", response_class=PlainTextResponse)
async def export_reports(q: str = "", status: str = "", department_id: int | None = None,
                         date_from: datetime | None = None, date_to: datetime | None = None,
                         actor: Actor = Depends(require("cad.reports.view_all")), s: AsyncSession = Depends(db_session)):
    rows = await reports.search(s, actor, q=q, status=status, department_id=department_id, date_from=date_from,
                                date_to=date_to, limit=200)
    return PlainTextResponse(reports.export_csv(rows), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="reports.csv"'})


@router.post("/reports")
async def create_report(body: dict = Body(...), actor: Actor = Depends(require("cad.reports.create")),
                        s: AsyncSession = Depends(db_session)):
    r = await reports.create(s, actor, body)
    await s.commit()
    return await reports.detail(s, actor, r.id)


@router.get("/reports/{rid}")
async def get_report(rid: str, actor: Actor = Depends(require("cad.reports.create")), s: AsyncSession = Depends(db_session)):
    r = await reports.get(s, actor, rid)
    return await reports.detail(s, actor, r.id)


@router.patch("/reports/{rid}")
async def update_report(rid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.reports.create")),
                        s: AsyncSession = Depends(db_session)):
    await reports.update(s, actor, rid, body)
    await s.commit()
    return await reports.detail(s, actor, rid)


@router.post("/reports/{rid}/submit")
async def submit_report(rid: int, actor: Actor = Depends(require("cad.reports.create")), s: AsyncSession = Depends(db_session)):
    await reports.submit(s, actor, rid)
    await s.commit()
    return await reports.detail(s, actor, rid)


@router.post("/reports/{rid}/review")
async def review_report(rid: int, body: dict = Body(...), actor: Actor = Depends(require("cad.reports.review")),
                        s: AsyncSession = Depends(db_session)):
    await reports.review(s, actor, rid, str(body.get("action", "")), str(body.get("comment", "")))
    await s.commit()
    return await reports.detail(s, actor, rid)


@router.get("/reports/{rid}/revisions/{revision}")
async def report_revision(rid: int, revision: int, actor: Actor = Depends(require("cad.reports.create")),
                          s: AsyncSession = Depends(db_session)):
    return await reports.revision_snapshot(s, actor, rid, revision)


@router.get("/reports/{rid}/export", response_class=PlainTextResponse)
async def export_report(rid: int, actor: Actor = Depends(require("cad.reports.create")), s: AsyncSession = Depends(db_session)):
    d = await reports.detail(s, actor, rid)
    return PlainTextResponse(reports.export_text(d), headers={"Content-Disposition": f'attachment; filename="{d["number"]}.txt"'})
