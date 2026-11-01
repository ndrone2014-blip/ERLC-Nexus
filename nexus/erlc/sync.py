"""Background ERLC API synchronisation.

Only one process polls at a time (database leader lease), so running the
website and bot together never doubles the request rate. Each cycle makes one
``GET /v2/server`` call with all documented flags and then:

* caches the snapshot in ``erlc_state`` for the bot and website,
* records join/kill/command/mod-call logs (deduplicated),
* tracks players seen by Nexus (labelled "recorded by ERLC Nexus"),
* samples player counts for analytics (every 60 s),
* imports in-game emergency calls as *pending* CAD calls (never auto-dispatched),
* optionally updates unit positions for personnel with a linked Roblox ID,
* emits server/API status change events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import SYSTEM
from nexus.core.events import emit
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import (
    ApiSyncRecord,
    ErlcEmergencyCall,
    ErlcPlayer,
    ErlcState,
    LeaderLease,
    PlayerCountSample,
    ServerLogEntry,
    Unit,
    UnitMembership,
    User,
)
from nexus.erlc.client import ErlcError
from nexus.erlc.models import ServerSnapshot, split_player, ts_to_dt
from nexus.services import notifications

log = logging.getLogger("nexus.erlc.sync")

LEASE_NAME = "erlc-sync"
SAMPLE_EVERY = 60.0


async def acquire_lease(session: AsyncSession, holder: str, ttl: float) -> bool:
    now = utcnow()
    lease = await session.get(LeaderLease, LEASE_NAME, with_for_update=True)
    if lease is None:
        session.add(LeaderLease(name=LEASE_NAME, holder=holder, expires_at=now + timedelta(seconds=ttl)))
        await session.commit()
        return True
    if lease.holder == holder or lease.expires_at < now:
        lease.holder = holder
        lease.expires_at = now + timedelta(seconds=ttl)
        await session.commit()
        return True
    await session.rollback()
    return False


async def release_lease(session: AsyncSession, holder: str) -> None:
    await session.execute(delete(LeaderLease).where(LeaderLease.name == LEASE_NAME, LeaderLease.holder == holder))
    await session.commit()


async def set_state(session: AsyncSession, key: str, data: Any) -> None:
    row = await session.get(ErlcState, key)
    if row is None:
        session.add(ErlcState(key=key, data=data, fetched_at=utcnow()))
    else:
        row.data = data
        row.fetched_at = utcnow()


async def get_state(session: AsyncSession, key: str) -> tuple[Any, Any]:
    row = await session.get(ErlcState, key)
    return (row.data, row.fetched_at) if row else (None, None)


def _dedupe(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


class SyncService:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_sample = 0.0
        self._last_status: dict[str, Any] = {"api_ok": None, "server_online": None}
        self.is_leader = False

    @property
    def interval(self) -> int:
        return self.rt.settings.erlc_sync_interval

    async def run_cycle(self) -> dict[str, Any]:
        """One sync cycle. Returns a summary (also used by tests and /server refresh)."""
        rt = self.rt
        await rt.refresh_server_key()
        started = time.monotonic()
        record = ApiSyncRecord(started_at=utcnow())
        summary: dict[str, Any] = {"ok": False}
        snap: ServerSnapshot | None = None
        error: ErlcError | None = None
        if not rt.erlc.configured:
            error = ErlcError("not_configured", "No ERLC server key configured.")
        else:
            try:
                snap = await rt.erlc.get_server(use_cache=False)
            except ErlcError as exc:
                error = exc
        record.duration_ms = int((time.monotonic() - started) * 1000)
        async with rt.db.session() as s:
            if snap is not None:
                record.ok = True
                record.players = snap.current_players
                b = rt.erlc.stats.buckets.get("global")
                record.rate_remaining = b.remaining if b else None
                summary = await self._apply(s, snap)
                summary["ok"] = True
            else:
                assert error is not None
                record.error = error.message[:300]
                record.http_status = error.http_status
                record.error_code = error.api_code
                summary = {"ok": False, "error": error.to_dict()}
                await set_state(s, "api_error", {**error.to_dict(), "at": utcnow().isoformat()})
            s.add(record)
            await self._status_transitions(s, snap, error)
            await s.commit()
        return summary

    async def _apply(self, s: AsyncSession, snap: ServerSnapshot) -> dict[str, Any]:
        now = utcnow()
        public = snap.to_public()
        await set_state(s, "server", public)
        await set_state(s, "api_error", None)

        new_logs = await self._store_logs(s, snap)
        await self._track_players(s, snap, now)
        calls = await self._import_emergency_calls(s, snap)
        if await get_setting(s, "cad.api_unit_locations"):
            await self._update_unit_locations(s, snap, now)

        mono = time.monotonic()
        if mono - self._last_sample >= SAMPLE_EVERY:
            self._last_sample = mono
            s.add(PlayerCountSample(ts=now, players=snap.current_players, max_players=snap.max_players,
                                    queue=len(snap.queue or []), teams=snap.team_counts()))
        emit(s, "erlc.synced", {"players": snap.current_players, "max": snap.max_players}, origin="system")
        return {"players": snap.current_players, "new_logs": new_logs, "new_calls": calls}

    async def _store_logs(self, s: AsyncSession, snap: ServerSnapshot) -> int:
        entries: list[tuple[str, int, dict]] = []
        for j in snap.join_logs or []:
            name, pid = split_player(j.player)
            entries.append(("join", j.timestamp, {"join": j.join, "name": name, "id": pid}))
        for k in snap.kill_logs or []:
            kn, kid = split_player(k.killer)
            vn, vid = split_player(k.killed)
            entries.append(("kill", k.timestamp, {"killer": kn, "killer_id": kid, "killed": vn, "killed_id": vid}))
        for c in snap.command_logs or []:
            name, pid = split_player(c.player)
            entries.append(("command", c.timestamp, {"name": name, "id": pid, "command": c.command}))
        for m in snap.mod_calls or []:
            cn, cid = split_player(m.caller)
            mn, mid = split_player(m.moderator)
            entries.append(("modcall", m.timestamp, {"caller": cn, "caller_id": cid, "moderator": mn or None,
                                                     "moderator_id": mid or None}))
        if not entries:
            return 0
        keys = {_dedupe(kind, ts, data): (kind, ts, data) for kind, ts, data in entries}
        existing = set((await s.execute(select(ServerLogEntry.dedupe).where(ServerLogEntry.dedupe.in_(list(keys))))).scalars())
        added = 0
        for key, (kind, ts, data) in keys.items():
            if key in existing:
                continue
            s.add(ServerLogEntry(kind=kind, ts=ts_to_dt(ts) or utcnow(), data=data, dedupe=key))
            added += 1
            if kind == "modcall" and not data.get("moderator"):
                await notifications.notify(
                    s, "erlc.modcall", f"Mod call from {data['caller']}",
                    "A player requested a moderator in-game.", audience="perm:erlc.server.moderate",
                    link="/#/server/moderation", dedupe_key=f"modcall:{key}", severity="warning")
        return added

    async def _track_players(self, s: AsyncSession, snap: ServerSnapshot, now) -> None:
        online = {p.id: p for p in snap.players or [] if p.id}
        known = {p.roblox_id: p for p in (await s.execute(
            select(ErlcPlayer).where((ErlcPlayer.is_online.is_(True)) | (ErlcPlayer.roblox_id.in_(list(online))))
        )).scalars()}
        for pid, p in online.items():
            row = known.get(pid)
            if row is None:
                row = ErlcPlayer(roblox_id=pid, username=p.name, first_seen=now, last_seen=now, sessions=1, is_online=True)
                s.add(row)
            else:
                if not row.is_online:
                    row.sessions += 1
                row.is_online = True
                row.last_seen = now
                row.username = p.name or row.username
            row.last_team = p.team or ""
            row.last_callsign = p.callsign or ""
        if snap.players is not None:
            for pid, row in known.items():
                if pid not in online and row.is_online:
                    row.is_online = False

    async def _import_emergency_calls(self, s: AsyncSession, snap: ServerSnapshot) -> int:
        if not snap.emergency_calls or not await get_setting(s, "cad.import_erlc_911"):
            return 0
        names = {p.id: p.name for p in snap.players or []}
        added = 0
        for call in snap.emergency_calls:
            key = call.dedupe_key
            if (await s.execute(select(ErlcEmergencyCall.id).where(ErlcEmergencyCall.dedupe == key))).scalar():
                continue
            x = call.position[0] if len(call.position) == 2 else None
            z = call.position[1] if len(call.position) == 2 else None
            row = ErlcEmergencyCall(
                dedupe=key, call_number=call.call_number, team=call.team, caller_roblox_id=str(call.caller),
                caller_name=names.get(str(call.caller), ""), players=list(call.players), x=x, z=z,
                position_descriptor=call.position_descriptor[:200], description=call.description,
                started_at=ts_to_dt(call.started_at) or utcnow(), status="pending",
            )
            s.add(row)
            await s.flush()
            added += 1
            emit(s, "erlc.911", {"id": row.id, "call_number": call.call_number, "team": call.team,
                                 "description": call.description[:200], "location": call.position_descriptor},
                 origin="system")
            await notifications.notify(
                s, "erlc.911", f"In-game {call.team or 'emergency'} call #{call.call_number}",
                (call.description or "No description")[:300] + (f" — {call.position_descriptor}" if call.position_descriptor else ""),
                audience="perm:cad.dispatch", link="/#/cad/dispatch", dedupe_key=f"911:{key}", severity="danger")
        return added

    async def _update_unit_locations(self, s: AsyncSession, snap: ServerSnapshot, now) -> None:
        by_roblox = {p.id: p for p in snap.players or [] if p.id and p.location and p.location.x is not None}
        if not by_roblox:
            return
        rows = (await s.execute(
            select(Unit, User.roblox_id)
            .join(UnitMembership, (UnitMembership.unit_id == Unit.id) & (UnitMembership.left_at.is_(None)))
            .join(User, User.id == UnitMembership.user_id)
            .where(Unit.is_archived.is_(False), User.roblox_id.is_not(None), Unit.status != "out_of_service")
            .order_by(UnitMembership.is_primary.desc())
        )).all()
        done: set[int] = set()
        for unit, rid in rows:
            if unit.id in done or rid not in by_roblox:
                continue
            p = by_roblox[rid]
            loc = p.location
            unit.location_x, unit.location_z = loc.x, loc.z
            unit.location_text = " ".join(x for x in [loc.building or "", loc.street or "",
                                                      f"(Postal {loc.postal})" if loc.postal else ""] if x).strip()
            unit.location_source = "api"
            unit.location_updated_at = now
            done.add(unit.id)
        if done:
            emit(s, "units.locations", {"unit_ids": sorted(done)}, origin="system")

    async def _status_transitions(self, s: AsyncSession, snap: ServerSnapshot | None, error: ErlcError | None) -> None:
        api_ok = snap is not None
        server_online = bool(snap and snap.current_players > 0) if snap else None
        prev = self._last_status
        if prev["api_ok"] is not None and prev["api_ok"] != api_ok:
            if api_ok:
                await notifications.notify(s, "erlc.api", "ERLC API connection restored", "Live data is updating again.",
                                           audience="perm:system.configure", dedupe_key="erlc.api", severity="success")
            else:
                await notifications.notify(s, "erlc.api", "ERLC API connection problem",
                                           error.message if error else "Unknown error",
                                           audience="perm:system.configure", dedupe_key="erlc.api", severity="danger")
                await audit(s, SYSTEM, "system", "erlc.api_failure", target_type="erlc", context=error.to_dict() if error else None)
            emit(s, "erlc.api_status", {"ok": api_ok}, origin="system")
        elif prev["api_ok"] is None and not api_ok and error and error.kind in ("auth", "outdated_module"):
            await notifications.notify(s, "erlc.api", "ERLC API configuration problem", error.message,
                                       audience="perm:system.configure", dedupe_key="erlc.api", severity="danger")
        if server_online is not None and prev["server_online"] is not None and prev["server_online"] != server_online:
            title = "ERLC server is now active" if server_online else "ERLC server is now empty"
            await notifications.notify(s, "erlc.status", title, f"{snap.current_players}/{snap.max_players} players.",
                                       dedupe_key="erlc.status", severity="info")
            emit(s, "erlc.server_status", {"online": server_online}, origin="system")
        self._last_status = {"api_ok": api_ok, "server_online": server_online if server_online is not None else prev["server_online"]}

    async def _housekeeping(self) -> None:
        cutoff = utcnow() - timedelta(days=7)
        async with self.rt.db.session() as s:
            await s.execute(delete(ApiSyncRecord).where(ApiSyncRecord.started_at < cutoff))
            await s.execute(update(ErlcEmergencyCall).where(
                ErlcEmergencyCall.status == "pending", ErlcEmergencyCall.started_at < utcnow() - timedelta(hours=6)
            ).values(status="expired"))
            await s.commit()

    async def run(self) -> None:
        holder = self.rt.instance_id
        lease_ttl = max(self.interval * 3, 45)
        cycles = 0
        while not self._stop.is_set():
            try:
                async with self.rt.db.session() as s:
                    self.is_leader = await acquire_lease(s, holder, lease_ttl)
                if self.is_leader:
                    await self.run_cycle()
                    cycles += 1
                    if cycles % 100 == 1:
                        await self._housekeeping()
            except Exception:
                log.exception("ERLC sync cycle failed")
            wait = self.interval
            err = self.rt.erlc.stats.last_error
            if err and err.get("kind") == "rate_limited" and err.get("retry_after"):
                wait = max(wait, float(err["retry_after"]))
            if self.rt.erlc.key_invalid:
                wait = max(wait, 120)  # stop hammering with a bad key; resumes when key changes
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        if self.is_leader:
            async with self.rt.db.session() as s:
                await release_lease(s, holder)

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.run(), name="erlc-sync")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
