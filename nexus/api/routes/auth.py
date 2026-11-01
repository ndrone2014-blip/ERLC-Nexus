"""Discord OAuth2 login (passwordless), logout and session info."""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import SESSION_COOKIE, client_ip, current_actor, current_session, db_session
from nexus.core.audit import audit
from nexus.core.context import Actor, Forbidden
from nexus.core.crypto import hash_token, new_token, sign, unsign
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import AuthEvent, WebSession
from nexus.services.users import get_or_create_user, resolve_actor, update_discord_roles, user_profile

log = logging.getLogger("nexus.auth")
router = APIRouter()

DISCORD_API = "https://discord.com/api/v10"
STATE_COOKIE = "nx_oauth_state"


def _cookie_args(request: Request) -> dict:
    rt = request.app.state.runtime
    return {"httponly": True, "samesite": "lax", "secure": rt.settings.cookie_secure, "path": "/"}


async def _start_session(request: Request, s: AsyncSession, user, *, method: str) -> JSONResponse | RedirectResponse:
    rt = request.app.state.runtime
    token = new_token()
    ws = WebSession(token_hash=hash_token(token), user_id=user.id, csrf_token=new_token(24), ip=client_ip(request),
                    user_agent=(request.headers.get("user-agent") or "")[:300],
                    expires_at=utcnow() + timedelta(hours=rt.settings.session_hours))
    s.add(ws)
    user.last_login_at = utcnow()
    s.add(AuthEvent(kind="login", user_id=user.id, discord_id=user.discord_id, ip=client_ip(request), detail=method))
    actor = await resolve_actor(s, user, ip=client_ip(request))
    await audit(s, actor, "system", "auth.login", target_type="user", target_id=user.id, target_ref=user.name,
                context={"method": method})
    await s.commit()
    resp = RedirectResponse("/#/", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, max_age=rt.settings.session_hours * 3600, **_cookie_args(request))
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@router.get("/auth/login")
async def login(request: Request):
    rt = request.app.state.runtime
    if not rt.settings.oauth_configured:
        return RedirectResponse("/#/login?error=oauth_not_configured", status_code=303)
    state = new_token(16)
    scopes = "identify guilds.members.read" if rt.settings.discord_guild_id else "identify"
    params = {"client_id": rt.settings.discord_application_id, "redirect_uri": rt.settings.oauth_redirect,
              "response_type": "code", "scope": scopes, "state": state, "prompt": "none"}
    resp = RedirectResponse(f"https://discord.com/oauth2/authorize?{urlencode(params)}", status_code=303)
    resp.set_cookie(STATE_COOKIE, sign(rt.settings.secret_key, state), max_age=600, **_cookie_args(request))
    return resp


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "",
                   s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    expected = unsign(rt.settings.secret_key, request.cookies.get(STATE_COOKIE, ""))
    if error or not code or not expected or expected != state:
        s.add(AuthEvent(kind="failed", ip=client_ip(request), detail=f"OAuth state/code invalid ({error or 'state'})"[:300]))
        await s.commit()
        return RedirectResponse("/#/login?error=login_failed", status_code=303)
    transport = getattr(request.app.state, "discord_transport", None)
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as http:
            tok = await http.post(f"{DISCORD_API}/oauth2/token", data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": rt.settings.oauth_redirect,
                "client_id": rt.settings.discord_application_id, "client_secret": rt.settings.discord_client_secret,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if tok.status_code != 200:
                raise RuntimeError(f"token exchange failed ({tok.status_code})")
            access = tok.json()["access_token"]
            auth = {"Authorization": f"Bearer {access}"}
            me = (await http.get(f"{DISCORD_API}/users/@me", headers=auth)).json()
            roles, in_guild = [], False
            if rt.settings.discord_guild_id:
                mr = await http.get(f"{DISCORD_API}/users/@me/guilds/{rt.settings.discord_guild_id}/member", headers=auth)
                if mr.status_code == 200:
                    roles, in_guild = mr.json().get("roles", []), True
    except Exception as exc:  # network / Discord errors
        log.warning("Discord OAuth failed: %s", exc)
        s.add(AuthEvent(kind="failed", ip=client_ip(request), detail="Discord OAuth exchange failed"))
        await s.commit()
        return RedirectResponse("/#/login?error=discord_unavailable", status_code=303)
    avatar = f"https://cdn.discordapp.com/avatars/{me['id']}/{me['avatar']}.png?size=64" if me.get("avatar") else ""
    user = await get_or_create_user(s, me["id"], username=me.get("username", ""),
                                    display_name=me.get("global_name") or me.get("username", ""), avatar_url=avatar)
    if not user.is_active:
        s.add(AuthEvent(kind="denied", user_id=user.id, discord_id=user.discord_id, ip=client_ip(request), detail="disabled account"))
        await s.commit()
        return RedirectResponse("/#/login?error=account_disabled", status_code=303)
    await update_discord_roles(s, user, roles, in_guild=in_guild, source="oauth", username=me.get("username", ""),
                               global_name=me.get("global_name"))
    return await _start_session(request, s, user, method="discord")


@router.post("/auth/dev-login")
async def dev_login(request: Request, s: AsyncSession = Depends(db_session)):
    """Local-only login for trying Nexus before Discord OAuth is configured.

    Requires DEV_LOGIN=true in config.env AND a request from this computer.
    Signs in as INITIAL_ADMIN_DISCORD_ID.
    """
    rt = request.app.state.runtime
    ip = client_ip(request)
    origin = request.headers.get("origin")
    same_origin = origin is None or urlparse(origin).netloc == request.headers.get("host", "")
    if (not rt.settings.dev_login or ip not in ("127.0.0.1", "::1", "testclient") or not rt.settings.initial_admin_discord_id
            or not same_origin):
        s.add(AuthEvent(kind="denied", ip=ip, detail="dev-login refused"))
        await s.commit()
        raise Forbidden("Local login is disabled.")
    user = await get_or_create_user(s, rt.settings.initial_admin_discord_id)
    return await _start_session(request, s, user, method="dev-login")


@router.post("/auth/logout")
async def logout(request: Request, ws: WebSession = Depends(current_session), s: AsyncSession = Depends(db_session)):
    ws = await s.merge(ws)
    ws.revoked_at = utcnow()
    s.add(AuthEvent(kind="logout", user_id=ws.user_id, ip=client_ip(request)))
    await s.commit()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/api/auth/config")
async def auth_config(request: Request, s: AsyncSession = Depends(db_session)):
    rt = request.app.state.runtime
    return {"oauth_configured": rt.settings.oauth_configured,
            "dev_login": rt.settings.dev_login and client_ip(request) in ("127.0.0.1", "::1", "testclient"),
            "community_name": await get_setting(s, "community.name"),
            "logo_url": await get_setting(s, "community.logo_url"),
            "accent": await get_setting(s, "appearance.accent")}


@router.get("/api/me")
async def me(request: Request, ws: WebSession = Depends(current_session), actor: Actor = Depends(current_actor),
             s: AsyncSession = Depends(db_session)):
    from nexus.db.models import User

    user = await s.get(User, ws.user_id)
    prof = await user_profile(s, user, actor)
    return {**prof, "csrf_token": ws.csrf_token, "session_expires_at": ws.expires_at}
