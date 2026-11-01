"""System administration routes."""

from __future__ import annotations

import platform
import sys
import time
from collections import deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus import __version__
from nexus.api.deps import client_ip, current_actor, db_session, require, require_any
from nexus.core.audit import audit, verify_chain
from nexus.core.context import Actor, NotFound, ValidationFailed
from nexus.core.crypto import encrypt_secret
from nexus.core.defaults import SETTINGS_DEFAULTS
from nexus.core.permissions import PERMISSIONS
from nexus.core.settings_store import PRIVATE_KEYS, get_many, set_internal, set_setting
from nexus.db.base import utcnow
from nexus.db.migrate import current_revision
from nexus.db.models import ApiSyncRecord, AuditLog, AuthEvent, LeaderLease, User, WebSession
from nexus.erlc.client import ErlcClient, ErlcError
from nexus.erlc.sync import get_state
from nexus.services import activity, backup, users

router = APIRouter(prefix="/api")
STARTED = time.time()


# ---- settings -------------------------------------------------------------------------

@router.get("/admin/settings")
async def get_settings(actor: Actor = Depends(require("system.configure")), s: AsyncSession = Depends(db_session)):
    return await get_many(s)


@router.put("/admin/settings/{key}")
async def put_setting(key: str, body: dict = Body(...), actor: Actor = Depends(require("system.configure")),
                      s: AsyncSession = Depends(db_session)):
    if key in PRIVATE_KEYS:
        raise ValidationFailed("That setting is managed elsewhere.")
    await set_setting(s, actor, key, body.get("value"))
    await s.commit()
    return {"key": key, "value": body.get("value")}


@router.post("/admin/settings/{key}/reset")
async def reset_setting(key: str, actor: Actor = Depends(require("system.configure")), s: AsyncSession = Depends(db_session)):
    if key not in SETTINGS_DEFAULTS or key in PRIVATE_KEYS:
        raise ValidationFailed("Unknown setting.")
    await set_setting(s, actor, key, SETTINGS_DEFAULTS[key])
    await s.commit()
    return {"key": key, "value": SETTINGS_DEFAULTS[key]}


# ---- roles & users ---------------------------------------------------------------------------

@router.get("/admin/permissions")
async def permission_catalog(actor: Actor = Depends(require_any("system.permissions", "system.configure"))):
    return [{"key": k, "category": c, "description": d} for k, (c, d) in PERMISSIONS.items()]


@router.get("/admin/roles")
async def list_roles(actor: Actor = Depends(require_any("system.permissions", "system.configure")),
                     s: AsyncSession = Depends(db_session)):
    return [users.role_dict(r) for r in await users.list_roles(s)]


@router.post("/admin/roles")
async def create_role(body: dict = Body(...), actor: Actor = Depends(require("system.permissions")),
                      s: AsyncSession = Depends(db_session)):
    r = await users.save_role(s, actor, body)
    await s.commit()
    return users.role_dict(r)


@router.patch("/admin/roles/{role_id}")
async def update_role(role_id: int, body: dict = Body(...), actor: Actor = Depends(require("system.permissions")),
                      s: AsyncSession = Depends(db_session)):
    r = await users.save_role(s, actor, body, role_id)
    await s.commit()
    return users.role_dict(r)


@router.delete("/admin/roles/{role_id}")
async def delete_role(role_id: int, actor: Actor = Depends(require("system.permissions")), s: AsyncSession = Depends(db_session)):
    await users.delete_role(s, actor, role_id)
    await s.commit()
    return {"ok": True}


@router.get("/admin/users")
async def list_users(q: str = "", limit: int = 50, offset: int = 0,
                     actor: Actor = Depends(require_any("system.permissions", "dept.personnel.manage")),
                     s: AsyncSession = Depends(db_session)):
    out = []
    for u in await users.search_users(s, q, limit=min(limit, 200), offset=offset):
        roles = await users.effective_roles(s, u)
        out.append({**users.user_summary(u), "username": u.username, "is_active": u.is_active,
                    "last_login_at": u.last_login_at, "roles": [{"id": r.id, "name": r.name, "color": r.color} for r in roles]})
    return out


@router.get("/admin/users/{user_id}")
async def get_user(user_id: int, actor: Actor = Depends(require_any("system.permissions", "dept.personnel.manage")),
                   s: AsyncSession = Depends(db_session)):
    u = await s.get(User, user_id)
    if u is None:
        raise NotFound("User not found.")
    from nexus.db.models import DiscordAccount, UserRole

    direct = (await s.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))).scalars().all()
    acct = (await s.execute(select(DiscordAccount).where(DiscordAccount.user_id == user_id))).scalar_one_or_none()
    return {**await users.user_profile(s, u), "direct_role_ids": list(direct),
            "discord": None if acct is None else {"in_guild": acct.in_guild, "role_ids": acct.guild_role_ids,
                                                  "synced_at": acct.roles_synced_at, "source": acct.roles_source}}


@router.post("/admin/users")
async def precreate_user(body: dict = Body(...), actor: Actor = Depends(require("system.permissions")),
                         s: AsyncSession = Depends(db_session)):
    """Add someone by Discord ID before their first login (so roles can be assigned ahead of time)."""
    did = str(body.get("discord_id", "")).strip()
    if not did.isdigit() or not 15 <= len(did) <= 21:
        raise ValidationFailed("Enter a valid Discord user ID.")
    u = await users.get_or_create_user(s, did, display_name=str(body.get("display_name", ""))[:100])
    await audit(s, actor, "system", "user.precreated", target_type="user", target_id=u.id, target_ref=did)
    await s.commit()
    return users.user_summary(u)


@router.put("/admin/users/{user_id}/roles")
async def set_roles(user_id: int, body: dict = Body(...), actor: Actor = Depends(require("system.permissions")),
                    s: AsyncSession = Depends(db_session)):
    await users.set_user_roles(s, actor, user_id, [int(x) for x in body.get("role_ids", [])])
    await s.commit()
    return {"ok": True}


@router.patch("/admin/users/{user_id}")
async def patch_user(user_id: int, body: dict = Body(...), actor: Actor = Depends(current_actor),
                     s: AsyncSession = Depends(db_session)):
    u = await users.update_user(s, actor, user_id, body)
    if body.get("is_active") is False:
        for ws in (await s.execute(select(WebSession).where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None)))).scalars():
            ws.revoked_at = utcnow()
    await s.commit()
    return users.user_summary(u)


# ---- audit & security --------------------------------------------------------------------------

@router.get("/admin/audit")
async def audit_logs(category: str = "", action: str = "", user_id: int | None = None, q: str = "",
                     date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 100, offset: int = 0,
                     actor: Actor = Depends(require("audit.view")), s: AsyncSession = Depends(db_session)):
    items, total = await activity.audit_search(s, category=category, action=action, user_id=user_id, q=q,
                                               date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/admin/audit/verify")
async def audit_verify(actor: Actor = Depends(require("audit.view")), s: AsyncSession = Depends(db_session)):
    return await verify_chain(s)


@router.get("/admin/security")
async def security(actor: Actor = Depends(require("system.security")), s: AsyncSession = Depends(db_session)):
    names = dict((await s.execute(select(User.id, User.display_name))).all())

    def ev(rows):
        return [{"id": e.id, "kind": e.kind, "user": names.get(e.user_id), "discord_id": e.discord_id, "ip": e.ip,
                 "detail": e.detail, "created_at": e.created_at} for e in rows]

    logins = (await s.execute(select(AuthEvent).where(AuthEvent.kind == "login").order_by(AuthEvent.id.desc()).limit(25))).scalars()
    failed = (await s.execute(select(AuthEvent).where(AuthEvent.kind.in_(("failed", "denied", "csrf_failed")))
                              .order_by(AuthEvent.id.desc()).limit(25))).scalars()
    sessions = (await s.execute(select(WebSession).where(WebSession.revoked_at.is_(None), WebSession.expires_at > utcnow())
                                .order_by(WebSession.last_seen_at.desc()).limit(100))).scalars()
    perm_changes = (await s.execute(select(AuditLog).where(AuditLog.action.in_(
        ("user.roles_changed", "role.created", "role.updated", "role.deleted"))).order_by(AuditLog.id.desc()).limit(25))).scalars()
    sec_events = (await s.execute(select(AuthEvent).where(AuthEvent.kind.in_(("expired", "csrf_failed", "denied")))
                                  .order_by(AuthEvent.id.desc()).limit(25))).scalars()
    since = utcnow() - timedelta(hours=24)
    failed_24h = (await s.execute(select(func.count()).select_from(AuthEvent).where(
        AuthEvent.kind.in_(("failed", "denied", "csrf_failed")), AuthEvent.created_at > since))).scalar()
    return {
        "recent_logins": ev(logins), "failed_attempts": ev(failed), "failed_24h": failed_24h,
        "active_sessions": [{"id": w.id, "user": names.get(w.user_id), "user_id": w.user_id, "ip": w.ip,
                             "user_agent": w.user_agent, "created_at": w.created_at, "last_seen_at": w.last_seen_at,
                             "expires_at": w.expires_at} for w in sessions],
        "permission_changes": [activity.entry_dict(a, full=True) for a in perm_changes],
        "security_events": ev(sec_events),
    }


@router.post("/admin/sessions/{session_id}/revoke")
async def revoke_session(session_id: int, request: Request, actor: Actor = Depends(require("system.security")),
                         s: AsyncSession = Depends(db_session)):
    ws = await s.get(WebSession, session_id)
    if ws is None:
        raise NotFound("Session not found.")
    ws.revoked_at = utcnow()
    s.add(AuthEvent(kind="revoked", user_id=ws.user_id, ip=client_ip(request), detail=f"revoked by {actor.name}"))
    await audit(s, actor, "system", "security.session_revoked", target_type="session", target_id=session_id)
    await s.commit()
    return {"ok": True}


# ---- ERLC API configuration --------------------------------------------------------------------

@router.get("/admin/erlc")
async def erlc_config(request: Request, actor: Actor = Depends(require("system.configure")), s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    records = (await s.execute(select(ApiSyncRecord).order_by(ApiSyncRecord.id.desc()).limit(30))).scalars().all()
    lease = await s.get(LeaderLease, "erlc-sync")
    err, _ = await get_state(s, "api_error")
    return {
        "key_configured": rt.erlc.configured,
        "key_source": "dashboard (encrypted)" if rt._db_key else ("config.env" if rt.settings.erlc_server_key else None),
        "global_key_configured": bool(rt.settings.erlc_global_key),
        "base_url": rt.settings.erlc_api_base_url, "sync_interval": rt.settings.erlc_sync_interval,
        "cache_ttl": rt.settings.erlc_cache_ttl, "webhook_enabled": rt.settings.erlc_webhook_enabled,
        "client": rt.erlc.status(), "api_error": err,
        "sync_leader": None if lease is None else {"holder": lease.holder.split("-")[0], "expires_at": lease.expires_at},
        "recent_syncs": [{"at": r.started_at, "ok": r.ok, "ms": r.duration_ms, "http": r.http_status, "code": r.error_code,
                          "error": r.error, "players": r.players} for r in records],
    }


@router.put("/admin/erlc/key")
async def set_erlc_key(request: Request, body: dict = Body(...), actor: Actor = Depends(require("system.configure")),
                       s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    key = str(body.get("key", "")).strip()
    if len(key) < 10 or len(key) > 200 or any(c.isspace() for c in key):
        raise ValidationFailed("That does not look like a valid ERLC server key.")
    if body.get("test", True):
        tester = ErlcClient(key, base_url=rt.settings.erlc_api_base_url, global_key=rt.settings.erlc_global_key,
                            timeout=rt.settings.erlc_request_timeout, max_retries=0,
                            transport=getattr(rt.erlc, "_transport", None))
        try:
            snap = await tester.get_server(flags=())
        except ErlcError as exc:
            raise ValidationFailed(f"The ERLC API rejected this key: {exc.message}")
        finally:
            await tester.close()
        server_name = snap.name
    else:
        server_name = None
    await set_internal(s, "erlc.server_key_encrypted", encrypt_secret(rt.settings.secret_key, key))
    await audit(s, actor, "system", "erlc.key_updated", target_type="erlc", new={"server": server_name})
    await s.commit()
    await rt.refresh_server_key()
    return {"ok": True, "server_name": server_name}


@router.delete("/admin/erlc/key")
async def clear_erlc_key(request: Request, actor: Actor = Depends(require("system.configure")),
                         s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    await set_internal(s, "erlc.server_key_encrypted", "")
    await audit(s, actor, "system", "erlc.key_removed", target_type="erlc")
    await s.commit()
    await rt.refresh_server_key()
    return {"ok": True, "still_configured_via_env": bool(rt.settings.erlc_server_key)}


@router.post("/admin/erlc/test")
async def test_erlc(request: Request, actor: Actor = Depends(require("system.configure"))):
    rt = request.app.state.runtime
    rt.erlc.reset_key_state()
    try:
        snap = await rt.erlc.get_server(flags=(), use_cache=False)
        return {"ok": True, "server_name": snap.name, "players": snap.current_players, "max": snap.max_players,
                "latency_ms": rt.erlc.stats.last_latency_ms}
    except ErlcError as exc:
        return {"ok": False, "error": exc.to_dict()}


# ---- Discord ---------------------------------------------------------------------------------------

@router.get("/admin/discord")
async def discord_status(request: Request, actor: Actor = Depends(require("system.configure")),
                         s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    hb, at = await get_state(s, "bot_heartbeat")
    online = bool(at and utcnow() - at < timedelta(seconds=90))
    app_id = rt.settings.discord_application_id
    # View Channels | Send Messages | Embed Links | Read Message History | Use Application Commands
    perms = (1 << 10) | (1 << 11) | (1 << 14) | (1 << 16) | (1 << 31)
    return {
        "bot_online": online, "heartbeat": hb, "heartbeat_at": at, "guild_id": rt.settings.discord_guild_id or None,
        "application_id": app_id or None, "oauth_configured": rt.settings.oauth_configured,
        "redirect_uri": rt.settings.oauth_redirect,
        "invite_url": f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={perms}" if app_id else None,
        "channels": (await get_many(s, ["discord.channels"]))["discord.channels"],
        "embeds": (await get_many(s, ["discord.embeds"]))["discord.embeds"],
        "sync_comms": (await get_many(s, ["discord.sync_comms"]))["discord.sync_comms"],
        "comms_channel": (await get_many(s, ["discord.comms_channel"]))["discord.comms_channel"],
    }


# ---- backups ------------------------------------------------------------------------------------------

@router.get("/admin/backups")
async def list_backups(request: Request, actor: Actor = Depends(require("system.database")),
                       s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    pending = backup.pending_restore_path(rt.settings).exists() if rt.settings.is_sqlite else False
    return {"backups": backup.list_backups(rt.settings) if rt.settings.is_sqlite else [], "restore_pending": pending,
            "supported": rt.settings.is_sqlite, "schema_revision": await current_revision(rt.db)}


@router.post("/admin/backups")
async def create_backup(request: Request, body: dict = Body(default_factory=dict),
                        actor: Actor = Depends(require("system.database")), s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    info = await backup.create_backup(rt.settings, str(body.get("label", "manual")))
    await audit(s, actor, "system", "database.backup", target_type="backup", target_ref=info["name"])
    await s.commit()
    return info


@router.get("/admin/backups/{name}/download")
async def download_backup(name: str, request: Request, actor: Actor = Depends(require("system.database")),
                          s: AsyncSession = Depends(db_session)):
    path = backup.backup_path(request.app.state.runtime.settings, name)
    await audit(s, actor, "system", "database.backup_downloaded", target_type="backup", target_ref=name)
    await s.commit()
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/admin/backups/{name}/restore")
async def restore_backup(name: str, request: Request, actor: Actor = Depends(require("system.database")),
                         s: AsyncSession = Depends(db_session)):
    info = await backup.stage_restore(request.app.state.runtime.settings, name)
    await audit(s, actor, "system", "database.restore_staged", target_type="backup", target_ref=name)
    await s.commit()
    return info


# ---- health & logs -------------------------------------------------------------------------------------

@router.get("/health")
async def health(request: Request):
    rt = request.app.state.runtime
    return {"status": "ok" if await rt.db.ping() else "degraded", "version": __version__}


@router.get("/admin/health")
async def admin_health(request: Request, actor: Actor = Depends(require_any("system.configure", "system.security")),
                       s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    hb, at = await get_state(s, "bot_heartbeat")
    last_sync = (await s.execute(select(ApiSyncRecord).order_by(ApiSyncRecord.id.desc()).limit(1))).scalar_one_or_none()
    hub = request.app.state.hub
    return {
        "version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
        "uptime_seconds": int(time.time() - STARTED),
        "database": {"ok": await rt.db.ping(), "engine": "SQLite" if rt.settings.is_sqlite else "PostgreSQL",
                     "revision": await current_revision(rt.db)},
        "erlc_api": {"configured": rt.erlc.configured, "key_invalid": rt.erlc.key_invalid,
                     "last_sync_ok": last_sync.ok if last_sync else None,
                     "last_sync_at": last_sync.started_at if last_sync else None,
                     "is_leader": bool(getattr(request.app.state, "sync", None) and request.app.state.sync.is_leader)},
        "discord_bot": {"online": bool(at and utcnow() - at < timedelta(seconds=90)), "heartbeat_at": at,
                        "latency_ms": (hb or {}).get("latency_ms"), "guilds": (hb or {}).get("guilds")},
        "websocket_clients": hub.count,
        "config_problems": rt.settings.problems("web"),
    }


@router.get("/admin/logs")
async def read_logs(request: Request, component: str = "web", lines: int = 200, level: str = "",
                    actor: Actor = Depends(require("system.configure"))):
    rt = request.app.state.runtime
    if component not in ("web", "bot", "launcher"):
        raise ValidationFailed("Unknown component.")
    path = rt.settings.data_path / "logs" / f"{component}.log"
    if not path.exists():
        return {"lines": [], "path": f"data/logs/{component}.log"}
    with path.open(encoding="utf-8", errors="replace") as fh:
        tail = deque(fh, maxlen=max(10, min(lines, 2000)))
    out = []
    import json

    for raw in tail:
        try:
            rec = json.loads(raw)
        except ValueError:
            rec = {"msg": raw.rstrip()}
        if level and rec.get("level") != level.upper():
            continue
        out.append(rec)
    return {"lines": out, "path": f"data/logs/{component}.log"}
