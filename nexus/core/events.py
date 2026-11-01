"""Transactional event outbox.

Services call :func:`emit` inside their database transaction. The website
process tails the outbox and pushes events to WebSocket clients; the Discord bot
tails it to post notifications. Because events live in the shared database, the
bot and website stay in sync even though they are separate processes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import Database, utcnow
from nexus.db.models import EventOutbox

log = logging.getLogger("nexus.events")


def emit(session: AsyncSession, kind: str, payload: dict[str, Any] | None = None, origin: str = "web") -> None:
    session.add(EventOutbox(kind=kind, payload=payload or {}, origin=origin))


class OutboxTailer:
    """Polls the outbox for new rows and dispatches them to a handler."""

    def __init__(self, db: Database, handler: Callable[[EventOutbox], Awaitable[None]], *, interval: float = 1.0,
                 name: str = "tailer") -> None:
        self.db = db
        self.handler = handler
        self.interval = interval
        self.name = name
        self.cursor: int | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _init_cursor(self) -> None:
        async with self.db.session() as s:
            self.cursor = (await s.execute(select(func.max(EventOutbox.id)))).scalar() or 0

    async def poll_once(self) -> int:
        if self.cursor is None:
            await self._init_cursor()
        async with self.db.session() as s:
            rows = (await s.execute(
                select(EventOutbox).where(EventOutbox.id > self.cursor).order_by(EventOutbox.id).limit(200)
            )).scalars().all()
        for row in rows:
            self.cursor = row.id
            try:
                await self.handler(row)
            except Exception:  # never let one bad event stop the stream
                log.exception("%s: handler failed for event %s", self.name, row.id)
        return len(rows)

    async def run(self) -> None:
        await self._init_cursor()
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception:
                log.exception("%s: outbox poll failed", self.name)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.run(), name=f"outbox-{self.name}")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)


async def prune_outbox(db: Database, keep_hours: int = 48) -> int:
    async with db.session() as s:
        res = await s.execute(delete(EventOutbox).where(EventOutbox.created_at < utcnow() - timedelta(hours=keep_hours)))
        await s.commit()
        return res.rowcount or 0
