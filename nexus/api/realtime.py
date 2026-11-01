"""WebSocket hub: pushes outbox events to authenticated browser clients.

Events carry identifiers and short summaries only; clients re-fetch details
through the REST API, which enforces permissions. Each event kind is also gated
by a permission here so restricted information is never pushed to users who
should not see it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from nexus.core.context import Actor
from nexus.db.models import EventOutbox

log = logging.getLogger("nexus.realtime")

KIND_PERMS = [
    ("incident.", "cad.view"), ("unit.", "cad.view"), ("units.", "cad.view"), ("comms.", "cad.view"),
    ("traffic.", "cad.traffic.manage"), ("map.", "cad.view"), ("erlc.911", "cad.dispatch"),
    ("bolo.", "cad.records.search"), ("record.", "cad.records.search"), ("report.", "cad.reports.create"),
    ("shift.", "dept.view"), ("department.", "dept.view"), ("erlc.", "erlc.server.view"),
]
BROADCAST = ("config.changed", "permissions.changed")


def allowed(actor: Actor, ev: EventOutbox) -> bool:
    kind, payload = ev.kind, ev.payload or {}
    if kind in BROADCAST:
        return True
    if kind == "notification":
        aud = payload.get("audience", "all")
        if aud == "user":
            return payload.get("user_id") == actor.user_id
        if aud.startswith("perm:"):
            return actor.can(aud[5:])
        return True
    if kind == "comms.message" and payload.get("restricted") and not actor.can("cad.incident.restricted"):
        return False
    for prefix, perm in KIND_PERMS:
        if kind.startswith(prefix):
            return actor.can(perm)
    return False


@dataclass(eq=False)
class Client:
    ws: WebSocket
    actor: Actor
    user_id: int


class Hub:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self._lock = asyncio.Lock()
        self.refresh_actor = None  # set by app: async (user_id) -> Actor | None

    async def add(self, client: Client) -> None:
        async with self._lock:
            self.clients.add(client)

    async def remove(self, client: Client) -> None:
        async with self._lock:
            self.clients.discard(client)

    async def handle(self, ev: EventOutbox) -> None:
        if ev.kind == "permissions.changed" and self.refresh_actor:
            for c in list(self.clients):
                fresh = await self.refresh_actor(c.user_id)
                if fresh is None:
                    await c.ws.close(code=4401)
                    await self.remove(c)
                else:
                    c.actor = fresh
        if not self.clients:
            return
        message = json.dumps(jsonable_encoder({"id": ev.id, "kind": ev.kind, "payload": ev.payload,
                                               "origin": ev.origin, "at": ev.created_at}))
        dead = []
        for c in list(self.clients):
            if not allowed(c.actor, ev):
                continue
            try:
                await asyncio.wait_for(c.ws.send_text(message), timeout=5)
            except Exception:
                dead.append(c)
        for c in dead:
            await self.remove(c)

    @property
    def count(self) -> int:
        return len(self.clients)
