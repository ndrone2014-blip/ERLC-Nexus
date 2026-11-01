"""Reports (revisions & review), shifts (restart-safe, duplicate-proof), departments & ranks."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from nexus.core.context import Conflict, Forbidden, ValidationFailed
from nexus.db.models import DepartmentHistory, ReportRevision, Shift
from nexus.services import departments, reports, shifts

pytestmark = pytest.mark.anyio


# ---- reports -----------------------------------------------------------------------

async def test_report_review_cycle_keeps_all_revisions(rt, admin, make_user):
    author = await make_user("500000000000000001", ["officer"], "Author")
    sup = await make_user("500000000000000002", ["supervisor"], "Sup")
    async with rt.db.session() as s:
        r = await reports.create(s, author, {"title": "Traffic collision", "summary": "", "description": ""})
        await s.commit()
        with pytest.raises(ValidationFailed):
            await reports.submit(s, author, r.id)  # needs summary + description
        await reports.update(s, author, r.id, {"summary": "Two cars", "description": "Full narrative v1"})
        await reports.submit(s, author, r.id)
        await s.commit()
        with pytest.raises(ValidationFailed):
            await reports.update(s, author, r.id, {"description": "sneaky edit after submit"})
        with pytest.raises(ValidationFailed):
            await reports.review(s, sup, r.id, "return", "")  # return needs a comment
        await reports.review(s, sup, r.id, "return", "Add the plate numbers")
        await s.commit()
        await reports.update(s, author, r.id, {"description": "Full narrative v2 with plates"})
        await reports.submit(s, author, r.id)
        await reports.review(s, sup, r.id, "approve", "Good")
        await s.commit()
        assert r.status == "approved"
        revs = (await s.execute(select(ReportRevision).where(ReportRevision.report_id == r.id).order_by(ReportRevision.revision))).scalars().all()
        descriptions = [v.snapshot["description"] for v in revs]
        assert "Full narrative v1" in descriptions and "Full narrative v2 with plates" in descriptions
        assert len({v.revision for v in revs}) == len(revs) >= 6
        d = await reports.detail(s, sup, r.id)
        assert [c["action"] for c in d["comments"]] == ["return", "approve"]
        assert "Full narrative v2" in reports.export_text(d)


async def test_report_access_rules(rt, make_user):
    author = await make_user("500000000000000003", ["officer"], "A")
    other = await make_user("500000000000000004", ["officer"], "B")
    sup = await make_user("500000000000000005", ["supervisor"], "S")
    async with rt.db.session() as s:
        r = await reports.create(s, author, {"title": "Mine", "summary": "s", "description": "d"})
        await reports.submit(s, author, r.id)
        await s.commit()
        with pytest.raises(Forbidden):
            await reports.get(s, other, r.id)
        with pytest.raises(Forbidden):
            await reports.review(s, author, r.id, "approve")  # no review permission
        assert (await reports.search(s, other)) == []
        assert len(await reports.search(s, sup, status="awaiting_review")) == 1


async def test_cannot_review_own_report(rt, make_user):
    sup = await make_user("500000000000000006", ["supervisor"], "S2")
    async with rt.db.session() as s:
        r = await reports.create(s, sup, {"title": "Own", "summary": "s", "description": "d"})
        await reports.submit(s, sup, r.id)
        await s.commit()
        with pytest.raises(Forbidden):
            await reports.review(s, sup, r.id, "approve")


# ---- shifts --------------------------------------------------------------------------

async def test_shift_start_end_and_duplicate_prevention(rt, admin):
    async with rt.db.session() as s:
        sh = await shifts.start(s, admin, department_id=1, callsign="1A-01")
        await s.commit()
        with pytest.raises(Conflict):
            await shifts.start(s, admin, department_id=1)
    # database-level guarantee too
    async with rt.db.session() as s:
        s.add(Shift(user_id=admin.user_id, status="active"))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with rt.db.session() as s:
        ended = await shifts.end(s, admin, notes="quiet night")
        await s.commit()
        assert ended.id == sh.id and ended.ended_at and "quiet night" in ended.notes
        with pytest.raises(Exception):
            await shifts.end(s, admin)


async def test_shift_survives_restart(settings, fake_erlc):
    from nexus.runtime import Runtime

    rt1 = Runtime(settings, erlc_transport=fake_erlc.transport)
    await rt1.startup()
    from tests.conftest import make_actor

    a = await make_actor(rt1, "600000000000000001", ["officer"], "Night")
    async with rt1.db.session() as s:
        await shifts.start(s, a)
        await s.commit()
    await rt1.shutdown()
    rt2 = Runtime(settings, erlc_transport=fake_erlc.transport)  # "restart"
    await rt2.startup()
    async with rt2.db.session() as s:
        n = await shifts.recover_active_shifts(s)
        await s.commit()
        active = await shifts.active_shift(s, a.user_id)
        assert n == 1 and active is not None and active.recovered
    await rt2.shutdown()


async def test_shift_adjustment_tracks_actual_vs_edited(rt, admin, make_user):
    officer = await make_user("600000000000000002", ["officer"], "O")
    async with rt.db.session() as s:
        sh = await shifts.start(s, officer)
        await s.commit()
        await shifts.end(s, officer)
        await s.commit()
        with pytest.raises(Forbidden):
            await shifts.adjust(s, officer, sh.id, credited_minutes=600, reason="pls")
        with pytest.raises(ValidationFailed):
            await shifts.adjust(s, admin, sh.id, credited_minutes=60, reason="")
        await shifts.adjust(s, admin, sh.id, credited_minutes=90, reason="Forgot to clock in")
        await s.commit()
        d = shifts.shift_dict(sh)
        assert d["credited_seconds"] == 5400 and d["is_adjusted"] and d["elapsed_seconds"] < 60
        st = await shifts.stats(s, officer.user_id)
        assert st["adjusted_shifts"] == 1 and st["adjustment_delta_seconds"] > 5300


async def test_shift_approval(rt, admin, make_user):
    officer = await make_user("600000000000000003", ["officer"], "O2")
    from nexus.core.settings_store import set_setting

    async with rt.db.session() as s:
        await set_setting(s, admin, "shift.require_approval", True)
        sh = await shifts.start(s, officer)
        await s.commit()
        await shifts.end(s, officer)
        await s.commit()
        assert sh.status == "ended"
        await shifts.approve(s, admin, sh.id)
        await s.commit()
        assert sh.status == "approved" and sh.approved_by == admin.user_id


# ---- departments ------------------------------------------------------------------------

async def test_department_ranks_and_personnel(rt, admin, make_user):
    member = await make_user("700000000000000001", ["officer"], "Member")
    async with rt.db.session() as s:
        d = await departments.save_department(s, admin, {"name": "State Police", "abbreviation": "sp", "kind": "law",
                                                         "color": "#123456", "ranks": ["Colonel", "Trooper"]})
        await s.commit()
        assert d.abbreviation == "SP"
        with pytest.raises(Conflict):
            await departments.save_department(s, admin, {"name": "Other", "abbreviation": "SP"})
        d = await departments.get_department(s, d.id)
        colonel, trooper = d.ranks
        m = await departments.add_member(s, admin, d.id, member.user_id, rank_id=trooper.id, callsign="SP-01")
        await s.commit()
        await departments.update_member(s, admin, m.id, {"rank_id": colonel.id})
        await s.commit()
        hist = (await s.execute(select(DepartmentHistory.action).where(DepartmentHistory.user_id == member.user_id))).scalars().all()
        assert "joined" in hist and "promoted" in hist
        with pytest.raises(Conflict):
            await departments.delete_rank(s, admin, d.id, colonel.id)  # in use
        await departments.delete_rank(s, admin, d.id, trooper.id)
        await departments.reorder_ranks(s, admin, d.id, [colonel.id, trooper.id])
        await s.commit()
        roster = await departments.roster(s, d.id)
        assert roster[0]["rank"] == "Colonel" and roster[0]["callsign"] == "SP-01"
        other = await make_user("700000000000000002", ["officer"], "Other")
        with pytest.raises(Conflict):
            await departments.add_member(s, admin, d.id, other.user_id, callsign="sp-01")


async def test_supervisor_scope(rt, admin, make_user):
    sup = await make_user("700000000000000003", ["supervisor"], "Sup")
    target = await make_user("700000000000000004", ["officer"], "T")
    async with rt.db.session() as s:
        lcso = await departments.get_department(s, 1)
        await departments.add_member(s, admin, 1, sup.user_id, rank_id=lcso.ranks[1].id)  # supervisory rank
        await s.commit()
    from tests.conftest import make_actor

    sup = await make_actor(rt, "700000000000000003", [], "Sup")
    assert 1 in sup.supervisor_department_ids
    async with rt.db.session() as s:
        await departments.add_member(s, sup, 1, target.user_id)  # own department: allowed
        await s.commit()
        with pytest.raises(Forbidden):
            await departments.add_member(s, sup, 2, target.user_id)  # other department: denied
        count = (await s.execute(select(func.count()).select_from(DepartmentHistory))).scalar()
        assert count >= 2
