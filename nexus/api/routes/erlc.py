"""ERLC server routes (official PRC API)."""

from __future__ import annotations

import base64
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import db_session, require
from nexus.core.audit import audit
from nexus.core.context import SYSTEM, Actor, NexusError
from nexus.erlc.sync import get_state
from nexus.services import erlc_ops

router = APIRouter(prefix="/api/erlc")

# Official ER:LC event-webhook public key (apidocs.erlc.gg/event-webhooks), base64 SPKI DER.
ERLC_WEBHOOK_PUBLIC_KEY = "MCowBQYDK2VwAyEAjSICb9pp0kHizGQtdG8ySWsDChfGqi+gyFCttigBNOA="


class TooFast(NexusError):
    status = 429
    code = "rate_limited"


@router.get("/overview")
async def overview(request: Request, actor: Actor = Depends(require("erlc.server.view")), s: AsyncSession = Depends(db_session)):
    return await erlc_ops.server_overview(s, request.app.state.runtime.erlc)


@router.get("/players")
async def players(q: str = "", team: str = "", actor: Actor = Depends(require("erlc.server.view")),
                  s: AsyncSession = Depends(db_session)):
    return await erlc_ops.players(s, q, team)


@router.get("/player")
async def player(query: str, actor: Actor = Depends(require("erlc.server.view")), s: AsyncSession = Depends(db_session)):
    return await erlc_ops.find_player(s, query)


@router.get("/player/history")
async def player_history(roblox_id: str = "", name: str = "", actor: Actor = Depends(require("erlc.server.view")),
                         s: AsyncSession = Depends(db_session)):
    return await erlc_ops.player_history(s, roblox_id or None, name)


@router.post("/refresh")
async def refresh(request: Request, actor: Actor = Depends(require("erlc.server.view")), s: AsyncSession = Depends(db_session)):
    app = request.app
    last = getattr(app.state, "last_manual_refresh", 0.0)
    if time.monotonic() - last < 10:
        raise TooFast("Live data was refreshed moments ago. Try again in a few seconds.")
    app.state.last_manual_refresh = time.monotonic()
    sync = getattr(app.state, "sync", None)
    summary = await sync.run_cycle() if sync is not None else {"ok": False, "error": {"message": "Sync not running"}}
    return {"summary": summary, "overview": await erlc_ops.server_overview(s, app.state.runtime.erlc)}


@router.post("/command")
async def command(request: Request, body: dict = Body(...), actor: Actor = Depends(require("erlc.server.command")),
                  s: AsyncSession = Depends(db_session)):
    res = await erlc_ops.run_command(s, request.app.state.runtime.erlc, actor, str(body.get("command", "")))
    await s.commit()
    return res


@router.post("/announce")
async def announce(request: Request, body: dict = Body(...), actor: Actor = Depends(require("erlc.server.announce")),
                   s: AsyncSession = Depends(db_session)):
    res = await erlc_ops.announce(s, request.app.state.runtime.erlc, actor, str(body.get("message", "")),
                                  str(body.get("style", "hint")))
    await s.commit()
    return res


@router.post("/moderate")
async def moderate(request: Request, body: dict = Body(...), actor: Actor = Depends(require("erlc.server.moderate")),
                   s: AsyncSession = Depends(db_session)):
    res = await erlc_ops.moderate(s, request.app.state.runtime.erlc, actor, str(body.get("action", "")),
                                  str(body.get("player", "")), str(body.get("reason", "")))
    await s.commit()
    return res


@router.post("/player-note")
async def player_note(body: dict = Body(...), actor: Actor = Depends(require("erlc.server.moderate")),
                      s: AsyncSession = Depends(db_session)):
    entry = await erlc_ops.add_player_note(s, actor, str(body.get("player", "")), str(body.get("note", "")))
    await s.commit()
    return {"id": entry.id}


@router.get("/bans")
async def bans(actor: Actor = Depends(require("erlc.server.moderate")), s: AsyncSession = Depends(db_session)):
    data, fetched = await get_state(s, "bans")
    return {"bans": data, "fetched_at": fetched, "source": "official ERLC API (GET /v1/server/bans)"}


@router.post("/bans/refresh")
async def refresh_bans(request: Request, actor: Actor = Depends(require("erlc.server.moderate")),
                       s: AsyncSession = Depends(db_session)):
    bans_list = await erlc_ops.refresh_bans(s, request.app.state.runtime.erlc, actor)
    await s.commit()
    return {"bans": bans_list}


@router.get("/logs")
async def logs(kind: str | None = None, q: str = "", limit: int = 100, actor: Actor = Depends(require("erlc.logs.view")),
               s: AsyncSession = Depends(db_session)):
    return await erlc_ops.server_logs(s, kind, q, limit)


@router.get("/moderation")
async def moderation(actor: Actor = Depends(require("erlc.server.moderate")), s: AsyncSession = Depends(db_session)):
    return await erlc_ops.moderation_actions(s)


@router.get("/status")
async def client_status(request: Request, actor: Actor = Depends(require("erlc.server.view"))):
    return request.app.state.runtime.erlc.status()


def verify_webhook_signature(raw: bytes, timestamp: str, signature_hex: str,
                             public_key_b64: str = ERLC_WEBHOOK_PUBLIC_KEY) -> bool:
    try:
        key = load_der_public_key(base64.b64decode(public_key_b64))
        key.verify(bytes.fromhex(signature_hex), timestamp.encode() + raw)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


@router.post("/webhook")
async def webhook(request: Request, s: AsyncSession = Depends(db_session)):
    """Optional ER:LC event webhook receiver (Ed25519-verified). Disabled unless ERLC_WEBHOOK_ENABLED=true."""
    if not request.app.state.runtime.settings.erlc_webhook_enabled:
        return JSONResponse({"error": "disabled"}, status_code=404)
    ts = request.headers.get("X-Signature-Timestamp", "")
    sig = request.headers.get("X-Signature-Ed25519", "")
    raw = await request.body()  # raw bytes, never re-serialised
    if not ts or not sig or not verify_webhook_signature(raw, ts, sig):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        payload = (await request.json()) if raw else None
    except ValueError:
        payload = None
    await audit(s, SYSTEM, "erlc", "webhook.received", target_type="erlc",
                context={"payload": payload if isinstance(payload, (dict, list)) else None, "size": len(raw)})
    await s.commit()
    return {"ok": True}
