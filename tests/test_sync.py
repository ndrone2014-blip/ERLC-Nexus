"""Background ERLC sync: caching, logs, players, 911 import, unit positions, leader lease."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select

from nexus.db.models import ApiSyncRecord, ErlcEmergencyCall, ErlcPlayer, Incident, Notification, ServerLogEntry
from nexus.erlc.sync import SyncService, acquire_lease, get_state
from nexus.services import units as unit_svc

pytestmark = pytest.mark.anyio


async def test_cycle_stores_snapshot_logs_players_and_calls(rt):
    sync = SyncService(rt)
    summary = await sync.run_cycle()
    assert summary["ok"] and summary["players"] == 2 and summary["new_calls"] == 1
    async with rt.db.session() as s:
        server, fetched = await get_state(s, "server")
        assert server["name"] == "Test RP" and fetched is not None
        assert "server-key" not in str(server).lower()
        kinds = dict((await s.execute(select(ServerLogEntry.kind, func.count()).group_by(ServerLogEntry.kind))).all())
        assert kinds == {"join": 1, "kill": 1, "command": 1, "modcall": 1}
        players = {p.username: p for p in (await s.execute(select(ErlcPlayer))).scalars()}
        assert players["Bob"].is_online and players["Bob"].sessions == 1
        call = (await s.execute(select(ErlcEmergencyCall))).scalar_one()
        assert call.status == "pending" and call.caller_name == "Amy" and call.x == 1.0
        # in-game calls are never auto-dispatched into incidents
        assert (await s.execute(select(func.count()).select_from(Incident))).scalar() == 0
        assert (await s.execute(select(func.count()).select_from(ApiSyncRecord))).scalar() == 1


async def test_second_cycle_deduplicates(rt):
    sync = SyncService(rt)
    await sync.run_cycle()
    rt.erlc._cache.clear()
    second = await sync.run_cycle()
    assert second["new_logs"] == 0 and second["new_calls"] == 0


async def test_player_leaving_is_tracked(rt, fake_erlc):
    sync = SyncService(rt)
    await sync.run_cycle()
    fake_erlc.payload["Players"] = fake_erlc.payload["Players"][:1]
    await sync.run_cycle()
    async with rt.db.session() as s:
        amy = (await s.execute(select(ErlcPlayer).where(ErlcPlayer.username == "Amy"))).scalar_one()
        assert not amy.is_online


async def test_unit_location_from_api_for_linked_roblox_member(rt, admin):
    from nexus.db.models import User

    async with rt.db.session() as s:
        user = await s.get(User, admin.user_id)
        user.roblox_id = "123"
        u = await unit_svc.register_unit(s, admin, {"department_id": 1, "callsign": "1A-01", "member_ids": [admin.user_id],
                                                    "status": "available"})
        await s.commit()
        uid = u.id
    await SyncService(rt).run_cycle()
    async with rt.db.session() as s:
        unit = await unit_svc.get_unit(s, uid)
        assert unit.location_source == "api" and unit.location_x == 10.5 and "Main St" in unit.location_text


async def test_failure_records_error_and_notifies_admins(rt, fake_erlc):
    sync = SyncService(rt)
    await sync.run_cycle()
    rt.erlc._cache.clear()
    fake_erlc.responses.append(httpx.Response(500, json={"error": "x", "code": 1001}))
    fake_erlc.responses.append(httpx.Response(500, json={"error": "x", "code": 1001}))
    fake_erlc.responses.append(httpx.Response(500, json={"error": "x", "code": 1001}))
    res = await sync.run_cycle()
    assert not res["ok"]
    async with rt.db.session() as s:
        err, _ = await get_state(s, "api_error")
        assert err["kind"] == "transient"
        n = (await s.execute(select(Notification).where(Notification.kind == "erlc.api"))).scalars().all()
        assert n and "problem" in n[-1].title.lower()


async def test_not_configured_makes_no_requests(rt, fake_erlc):
    rt.settings.erlc_server_key = ""
    res = await SyncService(rt).run_cycle()
    assert not res["ok"] and res["error"]["kind"] == "not_configured"
    assert fake_erlc.requests == []


async def test_leader_lease_is_exclusive(rt):
    async with rt.db.session() as s:
        assert await acquire_lease(s, "a", 60)
    async with rt.db.session() as s:
        assert not await acquire_lease(s, "b", 60)
    async with rt.db.session() as s:
        assert await acquire_lease(s, "a", 60)  # renewal by holder
