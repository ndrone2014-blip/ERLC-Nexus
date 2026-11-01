"""Posts Nexus events to configured Discord channels and refreshes live panels."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from sqlalchemy import select

from nexus.bot import ui
from nexus.core.settings_store import get_setting
from nexus.db.models import Department, DiscordPanel, EventOutbox

log = logging.getLogger("nexus.bot.notifier")

# event kind -> settings channel key. Notification events are already grouped/throttled.
DIRECT = {
    "incident.created": "incident.created", "incident.closed": "incident.closed", "unit.assigned": "unit.assigned",
    "bolo.created": "bolo.created", "bolo.expired": "bolo.expired", "report.submitted": "report.submitted",
    "shift.started": "shift.started", "shift.ended": "shift.ended", "erlc.911": "erlc.911",
}
VIA_NOTIFICATION = {"incident.priority", "unit.status", "erlc.api", "erlc.status", "erlc.modcall"}
PANEL_REFRESH_KINDS = ("incident.", "unit.", "bolo.", "erlc.synced", "shift.")


class Notifier:
    def __init__(self, bot) -> None:
        self.bot = bot
        self._last_sent: dict[str, float] = {}
        self._panel_dirty: set[str] = set()
        self._panel_task = asyncio.create_task(self._panel_loop(), name="panel-refresh")

    async def stop(self) -> None:
        self._panel_task.cancel()

    async def _channel(self, channel_id: str | None) -> discord.abc.Messageable | None:
        if not channel_id:
            return None
        try:
            cid = int(channel_id)
        except ValueError:
            return None
        ch = self.bot.get_channel(cid)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(cid)
            except discord.HTTPException:
                return None
        return ch

    def _throttled(self, key: str, seconds: float = 5.0) -> bool:
        now = time.monotonic()
        if now - self._last_sent.get(key, 0) < seconds:
            return True
        self._last_sent[key] = now
        return False

    async def handle(self, ev: EventOutbox) -> None:
        kind, p = ev.kind, ev.payload or {}
        if any(kind.startswith(k) for k in PANEL_REFRESH_KINDS):
            self._panel_dirty.add(kind.split(".")[0])
        async with self.bot.rt.db.session() as s:
            channels: dict[str, str] = await get_setting(s, "discord.channels")
            embeds_cfg = await get_setting(s, "discord.embeds")
            color = ui.hex_color(embeds_cfg.get("color"))
            if kind == "comms.message":
                if ev.origin == "discord" or not await get_setting(s, "discord.sync_comms"):
                    return
                if p.get("restricted"):
                    return
                ch = await self._channel(await get_setting(s, "discord.comms_channel"))
                if ch:
                    label = "📢 Announcement" if p.get("kind") == "announcement" else "📻 Dispatch"
                    await self._send(ch, ui.embed(f"{label} — {p.get('sender')}", p.get("body", ""), color=color))
                return
            if kind == "notification":
                nkind = p.get("kind", "")
                if nkind not in VIA_NOTIFICATION:
                    return
                target = channels.get(nkind)
                sev = {"danger": ui.RED, "warning": ui.AMBER, "success": ui.GREEN}.get(p.get("severity"), color)
                emb = ui.embed(p.get("title", "Notification"), p.get("body", ""), color=sev)
            else:
                key = DIRECT.get(kind)
                if key is None:
                    return
                target = channels.get(key)
                emb = self._event_embed(kind, p, color)
                dept_id = p.get("department_id")
                if dept_id and kind in ("incident.created", "bolo.created", "shift.started", "shift.ended", "report.submitted"):
                    dept = await s.get(Department, dept_id)
                    if dept and dept.notify_channel_id and dept.notify_channel_id != target:
                        dch = await self._channel(dept.notify_channel_id)
                        if dch and emb:
                            await self._send(dch, emb)
            if not target or emb is None:
                return
            ch = await self._channel(target)
            if ch is None:
                return
            if self._throttled(f"{kind}:{p.get('id')}:{p.get('kind')}", 2.0):
                return
            await self._send(ch, emb)

    async def _send(self, ch, emb: discord.Embed) -> None:
        try:
            await ch.send(embed=emb)
        except discord.HTTPException as exc:
            log.warning("Could not post to channel %s: %s", getattr(ch, "id", "?"), exc)

    def _event_embed(self, kind: str, p: dict[str, Any], color: int) -> discord.Embed | None:
        site = self.bot.website
        if kind == "incident.created":
            return ui.embed(f"🚨 New incident {p.get('number')}", p.get("description") or "",
                            color=ui.RED if p.get("priority") == 1 else color,
                            fields=[("Priority", f"P{p.get('priority')}", True), ("Category", p.get("category"), True),
                                    ("Location", p.get("location"), True)], url=site(f"cad/incident/{p.get('id')}"))
        if kind == "incident.closed":
            return ui.embed(f"✅ {p.get('number')} {p.get('status')}", p.get("disposition") or "", color=ui.GREY)
        if kind == "unit.assigned":
            return ui.embed(f"📟 {p.get('callsign')} assigned to {p.get('number')}", p.get("description") or "",
                            color=color, fields=[("Location", p.get("location"), True), ("Priority", f"P{p.get('priority')}", True)])
        if kind == "bolo.created":
            return ui.embed(f"👁️ BOLO {p.get('number')}", p.get("reason") or "", color=ui.AMBER,
                            fields=[("Category", p.get("category"), True), ("Plate", p.get("plate") or "—", True),
                                    ("Subject", p.get("subject") or "—", False), ("Vehicle", p.get("vehicle") or "—", False),
                                    ("Last known location", p.get("location") or "—", False)])
        if kind == "bolo.expired":
            return ui.embed(f"⌛ BOLO {p.get('number')} expired", color=ui.GREY)
        if kind == "report.submitted":
            return ui.embed(f"📝 Report {p.get('number')} awaiting review", f"{p.get('title')} — {p.get('author')}", color=color,
                            url=site(f"records/report/{p.get('id')}"))
        if kind == "shift.started":
            return ui.embed(f"🟢 {p.get('user')} clocked in", f"{p.get('department') or ''} {p.get('callsign') or ''}".strip(),
                            color=ui.GREEN, timestamp=True)
        if kind == "shift.ended":
            return ui.embed(f"🔴 {p.get('user')} clocked out", f"Duration {p.get('duration')}", color=ui.GREY)
        if kind == "erlc.911":
            return ui.embed(f"☎️ In-game {p.get('team') or ''} call #{p.get('call_number')}", p.get("description") or "",
                            color=ui.RED, fields=[("Location", p.get("location") or "—", False)],
                            footer="Source: official ERLC API · accept it in the Dispatch Center")
        return None

    # ---- live panels ---------------------------------------------------------------------
    async def _panel_loop(self) -> None:
        from nexus.bot.panels import render_panel

        await self.bot.wait_until_ready()
        tick = 0
        while True:
            await asyncio.sleep(15)
            tick += 1
            if not self._panel_dirty and tick % 4:
                continue  # refresh at least once a minute
            self._panel_dirty.clear()
            try:
                async with self.bot.rt.db.session() as s:
                    panels = (await s.execute(select(DiscordPanel))).scalars().all()
                for panel in panels:
                    try:
                        ch = await self._channel(panel.channel_id)
                        if ch is None:
                            continue
                        msg = await ch.fetch_message(int(panel.message_id))
                        emb = await render_panel(self.bot, panel.kind)
                        await msg.edit(embed=emb)
                    except discord.NotFound:
                        async with self.bot.rt.db.session() as s:
                            row = await s.get(DiscordPanel, panel.id)
                            if row:
                                await s.delete(row)
                                await s.commit()
                    except discord.HTTPException as exc:
                        log.debug("panel refresh failed: %s", exc)
            except Exception:
                log.exception("panel refresh loop error")
