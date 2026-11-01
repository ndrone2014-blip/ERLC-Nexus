"""FastAPI dependencies: database session, authentication, permission checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.context import Actor, Forbidden, NexusError
from nexus.core.crypto import hash_token
from nexus.db.base import utcnow
from nexus.db.models import AuthEvent, User, WebSession
from nexus.services.users import resolve_actor

SESSION_COOKIE = "nx_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Unauthorized(NexusError):
    status = 401
    code = "unauthorized"


def runtime(request: Request):
    return request.app.state.runtime


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.runtime.db.session() as s:
        yield s


LOOPBACK = ("127.0.0.1", "::1")


def real_ip(request: Request, trust_proxy: bool) -> str:
    """The visitor's IP address.

    Behind start-online / a local reverse proxy every request arrives from 127.0.0.1, so
    with TRUST_PROXY the forwarded address is used instead. Forwarded headers are only
    believed when the direct peer is this computer, so remote visitors can't spoof them.
    """
    peer = request.client.host if request.client else ""
    if trust_proxy and peer in LOOPBACK:
        fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        fwd = fwd.strip()
        if fwd:
            return fwd[:64]
    return peer


def client_ip(request: Request) -> str:
    rt = getattr(request.app.state, "runtime", None)
    return real_ip(request, bool(rt and rt.settings.trust_proxy))


async def load_session(s: AsyncSession, token: str | None) -> WebSession | None:
    if not token:
        return None
    ws = (await s.execute(select(WebSession).where(WebSession.token_hash == hash_token(token)))).scalar_one_or_none()
    if ws is None or ws.revoked_at is not None:
        return None
    if ws.expires_at < utcnow():
        return None
    return ws


async def current_session(request: Request, s: AsyncSession = Depends(db_session)) -> WebSession:
    token = request.cookies.get(SESSION_COOKIE)
    ws = await load_session(s, token)
    if ws is None:
        if token:
            s.add(AuthEvent(kind="expired", ip=client_ip(request), detail="Expired or invalid session"))
            await s.commit()
        raise Unauthorized("Please sign in.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or sent != ws.csrf_token:
            s.add(AuthEvent(kind="csrf_failed", user_id=ws.user_id, ip=client_ip(request), detail=request.url.path[:200]))
            await s.commit()
            raise Forbidden("Security check failed (CSRF). Refresh the page and try again.")
    now = utcnow()
    if now - ws.last_seen_at > timedelta(minutes=5):
        ws.last_seen_at = now
        await s.commit()
    return ws


async def current_actor(request: Request, ws: WebSession = Depends(current_session),
                        s: AsyncSession = Depends(db_session)) -> Actor:
    user = await s.get(User, ws.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Your account is disabled.")
    actor = await resolve_actor(s, user, source="web", ip=client_ip(request))
    request.state.actor = actor
    return actor


def require(*perms: str):
    """Dependency factory: actor must hold ALL listed permissions."""

    async def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        for p in perms:
            actor.require(p)
        return actor

    return _dep


def require_any(*perms: str):
    async def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        if not any(actor.can(p) for p in perms):
            raise Forbidden("You do not have permission to do that.")
        return actor

    return _dep
