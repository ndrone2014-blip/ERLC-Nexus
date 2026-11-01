"""ERLC server management built on the official API client."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import ApiSyncRecord, ErlcPlayer, PlayerAction, ServerLogEntry
from nexus.erlc.client import ErlcClient, ErlcError
from nexus.erlc.sync import get_state

_SAFE_ARG = re.compile(r"^[A-Za-z0-9_]{2,40}$")


async def server_overview(session: AsyncSession, erlc: ErlcClient) -> dict[str, Any]:
    data, fetched = await get_state(session, "server")
    err, _ = await get_state(session, "api_error")
    last_ok = (await session.execute(
        select(ApiSyncRecord.started_at).where(ApiSyncRecord.ok.is_(True)).order_by(ApiSyncRecord.id.desc()).limit(1)
    )).scalar()
    stale = fetched is None or (utcnow() - fetched) > timedelta(minutes=3)
    if data is None:
        status = "not_configured" if not erlc.configured else "unknown"
    elif err:
        status = "api_error"
    elif data.get("current_players", 0) > 0:
        status = "online"
    else:
        status = "empty"
    return {
        "configured": erlc.configured,
        "key_invalid": erlc.key_invalid,
        "status": status,
        "stale": stale,
        "data_source": "official ERLC API" if data else None,
        "fetched_at": fetched,
        "last_successful_sync": last_ok,
        "api_error": err,
        "server": data,
    }


async def players(session: AsyncSession, q: str = "", team: str = "") -> list[dict[str, Any]]:
    data, _ = await get_state(session, "server")
    rows = (data or {}).get("players", [])
    if q:
        ql = q.lower()
        rows = [p for p in rows if ql in p["name"].lower() or ql == p["id"] or ql in (p.get("callsign") or "").lower()]
    if team:
        rows = [p for p in rows if p["team"].lower() == team.lower()]
    return sorted(rows, key=lambda p: (p["team"], p["name"].lower()))


async def find_player(session: AsyncSession, query: str) -> dict[str, Any]:
    """Look up a player by exact/partial name or Roblox ID, live first then recorded."""
    query = (query or "").strip()
    if not query:
        raise ValidationFailed("Enter a player name or Roblox ID.")
    live = await players(session)
    match = next((p for p in live if p["id"] == query or p["name"].lower() == query.lower()), None)
    if match is None:
        partial = [p for p in live if query.lower() in p["name"].lower()]
        match = partial[0] if len(partial) == 1 else None
    rec = None
    if match:
        rec = (await session.execute(select(ErlcPlayer).where(ErlcPlayer.roblox_id == match["id"]))).scalar_one_or_none()
    else:
        rec = (await session.execute(
            select(ErlcPlayer).where(or_(ErlcPlayer.roblox_id == query, func.lower(ErlcPlayer.username) == query.lower()))
        )).scalar_one_or_none()
        if rec is None:
            cands = (await session.execute(
                select(ErlcPlayer).where(ErlcPlayer.username.ilike(f"%{query}%")).limit(2)
            )).scalars().all()
            rec = cands[0] if len(cands) == 1 else None
    if match is None and rec is None:
        raise NotFound(f"No player matching '{query}' is in the server or in Nexus records.")
    rid = (match or {}).get("id") or rec.roblox_id
    name = (match or {}).get("name") or rec.username
    history = await player_history(session, rid, name, limit=10)
    bans_state, _ = await get_state(session, "bans")
    return {
        "name": name,
        "roblox_id": rid,
        "online": match is not None,
        "live": match,
        "recorded": None if rec is None else {
            "first_seen": rec.first_seen, "last_seen": rec.last_seen, "sessions": rec.sessions,
            "last_team": rec.last_team, "notes": rec.notes, "source": "Recorded by ERLC Nexus",
        },
        "banned": bool(bans_state and any(b["id"] == rid for b in bans_state)) if bans_state is not None else None,
        "history": history,
    }


async def player_history(session: AsyncSession, roblox_id: str | None, name: str = "", limit: int = 50) -> list[dict]:
    cond = []
    if roblox_id:
        cond.append(PlayerAction.roblox_id == roblox_id)
    if name:
        cond.append(func.lower(PlayerAction.username) == name.lower())
    if not cond:
        return []
    rows = (await session.execute(
        select(PlayerAction).where(or_(*cond)).order_by(PlayerAction.id.desc()).limit(limit)
    )).scalars()
    return [{"id": r.id, "action": r.action, "reason": r.reason, "success": r.success, "result": r.result,
             "user_id": r.user_id, "source": r.source, "created_at": r.created_at} for r in rows]


def _render(template: str, **kw: str) -> str:
    out = template
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return re.sub(r"\s+", " ", out).strip()


async def run_command(session: AsyncSession, erlc: ErlcClient, actor: Actor, command: str) -> dict[str, Any]:
    actor.require("erlc.server.command")
    blocked = await get_setting(session, "erlc.blocked_commands") or []
    try:
        result = await erlc.run_command(command, blocked)
        ok = True
    except ErlcError as exc:
        result, ok = exc.message, False
        await audit(session, actor, "erlc", "server.command_failed", target_type="erlc", target_ref=command[:60],
                    context={"command": command, "error": exc.to_dict()})
        await session.commit()
        raise
    await audit(session, actor, "erlc", "server.command", target_type="erlc", target_ref=command[:60],
                new={"command": command, "result": result})
    emit(session, "erlc.command", {"command": command, "by": actor.name}, origin=actor.source)
    return {"ok": ok, "result": result, "command": command}


async def announce(session: AsyncSession, erlc: ErlcClient, actor: Actor, message: str, style: str = "hint") -> dict:
    actor.require("erlc.server.announce")
    message = " ".join((message or "").split())
    if not message:
        raise ValidationFailed("Announcement text is required.")
    if len(message) > 250:
        raise ValidationFailed("Announcements are limited to 250 characters.")
    templates = await get_setting(session, "erlc.command_templates")
    tpl = templates.get("message" if style == "message" else "hint", ":h {message}")
    cmd = _render(tpl, message=message)
    blocked = await get_setting(session, "erlc.blocked_commands") or []
    try:
        result = await erlc.run_command(cmd, blocked)
    except ErlcError as exc:
        await audit(session, actor, "erlc", "server.announcement_failed", target_type="erlc",
                    context={"message": message, "error": exc.to_dict()})
        await session.commit()
        raise
    await audit(session, actor, "erlc", "server.announcement", target_type="erlc", new={"message": message, "style": style})
    return {"ok": True, "result": result, "command": cmd}


async def moderate(session: AsyncSession, erlc: ErlcClient, actor: Actor, action: str, player: str,
                   reason: str = "", roblox_id: str | None = None) -> dict[str, Any]:
    """Kick / ban / unban a player via the documented in-game admin commands."""
    actor.require("erlc.server.moderate")
    if action not in ("kick", "ban", "unban"):
        raise ValidationFailed("Unknown moderation action.")
    player = (player or "").strip()
    if not _SAFE_ARG.match(player):
        raise ValidationFailed("Enter a valid Roblox username or user ID (letters, numbers and underscores).")
    reason = " ".join((reason or "").split())[:200]
    templates = await get_setting(session, "erlc.command_templates")
    cmd = _render(templates.get(action, f":{action} {{player}}"), player=player, reason=reason)
    blocked = await get_setting(session, "erlc.blocked_commands") or []
    if roblox_id is None:
        rec = (await session.execute(select(ErlcPlayer).where(
            or_(func.lower(ErlcPlayer.username) == player.lower(), ErlcPlayer.roblox_id == player)
        ))).scalar_one_or_none()
        roblox_id = rec.roblox_id if rec else (player if player.isdigit() else None)
    entry = PlayerAction(roblox_id=roblox_id, username=player, action=action, reason=reason, command=cmd,
                         user_id=actor.user_id, source=actor.source)
    try:
        entry.result = (await erlc.run_command(cmd, blocked))[:120]
        entry.success = True
    except ErlcError as exc:
        entry.result = exc.message[:120]
        entry.success = False
        session.add(entry)
        await audit(session, actor, "erlc", f"player.{action}_failed", target_type="player",
                    target_id=roblox_id or player, target_ref=player, context={"reason": reason, "error": exc.to_dict()})
        await session.commit()
        raise
    session.add(entry)
    await audit(session, actor, "erlc", f"player.{action}", target_type="player", target_id=roblox_id or player,
                target_ref=player, new={"reason": reason, "command": cmd})
    emit(session, "erlc.moderation", {"action": action, "player": player, "by": actor.name}, origin=actor.source)
    return {"ok": True, "action": action, "player": player, "result": entry.result}


async def add_player_note(session: AsyncSession, actor: Actor, player: str, note: str) -> PlayerAction:
    actor.require("erlc.server.moderate")
    note = (note or "").strip()
    if not note:
        raise ValidationFailed("Note text is required.")
    rec = (await session.execute(select(ErlcPlayer).where(
        or_(func.lower(ErlcPlayer.username) == player.lower(), ErlcPlayer.roblox_id == player)
    ))).scalar_one_or_none()
    entry = PlayerAction(roblox_id=rec.roblox_id if rec else None, username=rec.username if rec else player,
                         action="note", reason=note[:300], success=True, user_id=actor.user_id, source=actor.source)
    session.add(entry)
    await audit(session, actor, "erlc", "player.note", target_type="player", target_ref=player, new={"note": note})
    return entry


async def refresh_bans(session: AsyncSession, erlc: ErlcClient, actor: Actor) -> list[dict[str, str]]:
    actor.require("erlc.server.moderate")
    from nexus.erlc.sync import set_state

    bans = await erlc.get_bans(use_cache=False)
    await set_state(session, "bans", bans)
    return bans


async def server_logs(session: AsyncSession, kind: str | None = None, q: str = "", limit: int = 100,
                      before: datetime | None = None) -> list[dict[str, Any]]:
    stmt = select(ServerLogEntry).order_by(ServerLogEntry.ts.desc()).limit(min(limit, 500))
    if kind:
        stmt = stmt.where(ServerLogEntry.kind == kind)
    if before:
        stmt = stmt.where(ServerLogEntry.ts < before)
    rows = (await session.execute(stmt)).scalars().all()
    out = [{"id": r.id, "kind": r.kind, "ts": r.ts, **r.data} for r in rows]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in " ".join(str(v) for v in o.values()).lower()]
    return out


async def moderation_actions(session: AsyncSession, limit: int = 100) -> list[dict[str, Any]]:
    rows = (await session.execute(select(PlayerAction).order_by(PlayerAction.id.desc()).limit(limit))).scalars()
    return [{"id": r.id, "username": r.username, "roblox_id": r.roblox_id, "action": r.action, "reason": r.reason,
             "success": r.success, "result": r.result, "user_id": r.user_id, "source": r.source,
             "created_at": r.created_at} for r in rows]
