"""CAD: incidents, timeline, statuses, priorities, units, assignments, queue, 911, permissions."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from nexus.core.context import Conflict, Forbidden, ValidationFailed
from nexus.db.models import IncidentEvent
from nexus.erlc.sync import SyncService
from nexus.services import incidents, units as unit_svc

pytestmark = pytest.mark.anyio


async def _new(rt, actor, **kw):
    async with rt.db.session() as s:
        inc = await incidents.create(s, actor, {"category": "crime", "priority": 2, "location_name": "Bank",
                                                "description": "Robbery", **kw})
        await s.commit()
        return inc.id, inc.number


async def test_numbering_and_creation(rt, admin):
    _, n1 = await _new(rt, admin)
    _, n2 = await _new(rt, admin)
    assert n1.startswith("NX-") and n1.endswith("000001") and n2.endswith("000002")


async def test_validation(rt, admin):
    async with rt.db.session() as s:
        with pytest.raises(ValidationFailed):
            await incidents.create(s, admin, {"category": "crime", "priority": 9, "description": "x"})
        with pytest.raises(ValidationFailed):
            await incidents.create(s, admin, {"category": "nope", "description": "x"})
        with pytest.raises(ValidationFailed):
            await incidents.create(s, admin, {"category": "crime"})  # no description or location


async def test_status_workflow_timeline_and_closure(rt, admin):
    iid, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        u = await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "1A-02", "status": "available"})
        await s.commit()
        await incidents.assign_unit(s, admin, iid, u.id)
        await s.commit()
        inc = await incidents.get(s, iid)
        assert inc.status == "dispatched" and inc.dispatched_at
        unit = await unit_svc.get_unit(s, u.id)
        assert unit.status == "en_route" and unit.current_incident_id == iid
        await unit_svc.set_status(s, admin, u.id, "on_scene")
        await s.commit()
        assert (await incidents.get(s, iid)).status == "on_scene"
        await incidents.change_priority(s, admin, await incidents.get(s, iid), 1)
        await incidents.change_status(s, admin, iid, "closed", disposition="Arrest made")
        await s.commit()
        inc = await incidents.get(s, iid)
        assert inc.status == "closed" and inc.closed_at and inc.disposition == "Arrest made"
        unit = await unit_svc.get_unit(s, u.id)
        assert unit.current_incident_id is None and unit.status == "available"
        events = [e.event_type for e in (await s.execute(select(IncidentEvent).where(IncidentEvent.incident_id == iid)
                                                         .order_by(IncidentEvent.id))).scalars()]
        for expected in ("created", "unit_assigned", "status_changed", "unit_status", "priority_changed", "unit_removed", "closed"):
            assert expected in events, expected
        # history is retained after closure and the incident can be reopened
        await incidents.change_status(s, admin, iid, "pending")
        await s.commit()
        assert (await incidents.get(s, iid)).closed_at is None
        assert "reopened" in [e["event"] for e in await incidents.history(s, iid)]


async def test_cannot_assign_to_closed_or_twice(rt, admin):
    iid, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        u = await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "1A-03", "status": "available"})
        await incidents.assign_unit(s, admin, iid, u.id)
        await s.commit()
        with pytest.raises(Conflict):
            await incidents.assign_unit(s, admin, iid, u.id)
        await incidents.change_status(s, admin, iid, "cancelled")
        await s.commit()
        with pytest.raises(ValidationFailed):
            await incidents.assign_unit(s, admin, iid, "1A-03")


async def test_reassignment_clears_previous_incident(rt, admin):
    a, _ = await _new(rt, admin)
    b, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        u = await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "1A-04", "status": "available"})
        await incidents.assign_unit(s, admin, a, u.id)
        await s.commit()
        await incidents.assign_unit(s, admin, b, u.id)
        await s.commit()
        inc_a = await incidents.get(s, a)
        assert all(x.cleared_at is not None for x in inc_a.assignments)
        assert (await unit_svc.get_unit(s, u.id)).current_incident_id == b


async def test_officer_permissions(rt, admin, make_user):
    officer = await make_user("200000000000000001", ["officer"], "Officer")
    iid, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        with pytest.raises(Forbidden):
            await incidents.create(s, officer, {"category": "crime", "description": "x"})
        with pytest.raises(Forbidden):
            await incidents.change_status(s, officer, iid, "closed")
        other = await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "1A-05", "status": "available"})
        await s.commit()
        with pytest.raises(Forbidden):
            await incidents.assign_unit(s, officer, iid, other.id)  # can't dispatch others
        with pytest.raises(Forbidden):
            await unit_svc.set_status(s, officer, other.id, "busy")  # not a member


async def test_officer_self_service_on_own_unit(rt, admin, make_user):
    officer = await make_user("200000000000000002", ["officer"], "Officer2")
    iid, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        from nexus.services import departments

        await departments.add_member(s, admin, 1, officer.user_id)
        await s.commit()
    officer = await make_user("200000000000000002", [], "Officer2")  # re-resolve with department membership
    async with rt.db.session() as s:
        u = await unit_svc.register_unit(s, officer, {"department_id": 1})  # self-register
        await s.commit()
        assert u.callsign and await unit_svc.is_member(s, u.id, officer.user_id)
        await incidents.assign_unit(s, officer, iid, u.id)  # attach own unit
        await unit_svc.set_status(s, officer, u.id, "on_scene")
        await incidents.add_note(s, officer, iid, "Arrived, suspect fled north")
        await s.commit()
        assert (await incidents.get(s, iid)).status == "on_scene"


async def test_callsign_uniqueness_and_format(rt, admin):
    async with rt.db.session() as s:
        await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "FIRE-01"})
        await s.commit()
        with pytest.raises(Conflict):
            await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "fire-01"})
        assert unit_svc.render_callsign("{abbr}-{seq:02}", abbr="LCSO", seq=3) == "LCSO-03"
        assert unit_svc.render_callsign("{num}A-{seq:02}", num=2, seq=1) == "2A-01"
        suggestion = await unit_svc.suggest_callsign(s, 1)
        assert suggestion and suggestion != "FIRE-01"


async def test_queue_overdue_flags(rt, admin):
    iid, _ = await _new(rt, admin, priority=1)
    async with rt.db.session() as s:
        from datetime import timedelta

        inc = await incidents.get(s, iid)
        inc.created_at = inc.created_at - timedelta(minutes=5)
        await s.commit()
        q = await incidents.queue(s, admin)
        item = next(i for i in q if i["id"] == iid)
        assert item["overdue"] and item["awaiting_dispatch"]


async def test_911_call_goes_to_pending(rt, make_user):
    civ = await make_user("300000000000000001", ["civilian"], "Civ")
    async with rt.db.session() as s:
        inc = await incidents.create_911(s, civ, {"location_name": "Gas station", "description": "Fire in the store"})
        await s.commit()
        assert inc.status == "pending" and inc.caller_name == "Civ"


async def test_accept_and_dismiss_erlc_calls(rt, admin):
    await SyncService(rt).run_cycle()
    async with rt.db.session() as s:
        calls = await incidents.pending_erlc_calls(s)
        assert calls[0]["source"] == "official ERLC API"
        inc = await incidents.accept_erlc_call(s, admin, calls[0]["id"])
        await s.commit()
        assert inc.source == "erlc_api" and inc.category == "crime" and inc.map_x == 1.0
        with pytest.raises(Conflict):
            await incidents.accept_erlc_call(s, admin, calls[0]["id"])
        assert await incidents.pending_erlc_calls(s) == []


async def test_restricted_notes_hidden(rt, admin, make_user):
    officer = await make_user("200000000000000003", ["officer"], "Officer3")
    iid, _ = await _new(rt, admin)
    async with rt.db.session() as s:
        await incidents.add_note(s, admin, iid, "public note")
        await incidents.add_note(s, admin, iid, "secret note", restricted=True)
        await s.commit()
        d = await incidents.detail_dict(s, officer, await incidents.get(s, iid))
        bodies = [n["body"] for n in d["notes"]]
        assert "public note" in bodies and "secret note" not in bodies
