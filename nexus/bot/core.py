"""The ERLC Nexus Discord bot.

The bot is a client of the shared service layer and database; it does not
contain the backend. Permissions are resolved from the member's Discord roles
(delivered by Discord's gateway, so they are trustworthy) mapped to Nexus roles,
plus roles assigned in the website.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy.ext.asyncio import AsyncSession

from nexus import __version__
from nexus.bot import ui
from nexus.core.context import Actor, NexusError
from nexus.core.events import OutboxTailer
from nexus.core.settings_store import get_setting, invalidate_cache
from nexus.erlc.client import ErlcError
from nexus.erlc.sync import SyncService, set_state
from nexus.runtime import Runtime
from nexus.services import shifts
from nexus.services.users import actor_for_discord

log = logging.getLogger("nexus.bot")

COGS = [
    "nexus.bot.cogs.server", "nexus.bot.cogs.player", "nexus.bot.cogs.cad", "nexus.bot.cogs.unit",
    "nexus.bot.cogs.dispatch", "nexus.bot.cogs.mdt", "nexus.bot.cogs.department", "nexus.bot.cogs.shift",
    "nexus.bot.cogs.bolo", "nexus.bot.cogs.record", "nexus.bot.cogs.report", "nexus.bot.cogs.nexus",
]


class NexusTree(app_commands.CommandTree):
    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Slow down — try again in {error.retry_after:.0f}s."
        elif isinstance(error, app_commands.TransformerError):
            msg = f"Invalid value: {error.value}"
        elif isinstance(original, (NexusError, ErlcError, discord.Forbidden)):
            msg = ui.friendly_error(original)
        else:
            log.exception("Command error in /%s", interaction.command.qualified_name if interaction.command else "?",
                          exc_info=original)
            msg = ui.friendly_error(original)
        try:
            await ui.reply(interaction, embed=ui.error_embed(msg))
        except discord.HTTPException:
            pass


class NexusBot(commands.Bot):
    def __init__(self, runtime: Runtime, *, run_sync: bool = True) -> None:
        intents = discord.Intents.default()
        intents.members = False  # role IDs arrive with each interaction; no privileged intent needed
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, tree_cls=NexusTree,
                         help_command=None, activity=discord.Activity(type=discord.ActivityType.watching, name="Liberty County"))
        self.rt = runtime
        self.run_sync = run_sync
        self.sync_service: SyncService | None = None
        self.tailer: OutboxTailer | None = None
        self.notifier = None

    # ---- context ---------------------------------------------------------------------
    @asynccontextmanager
    async def ctx(self, interaction: discord.Interaction) -> AsyncIterator[tuple[AsyncSession, Actor]]:
        """Database session + actor for the interaction user, committed on success."""
        user = interaction.user
        role_ids = [str(r.id) for r in getattr(user, "roles", [])] if isinstance(user, discord.Member) else None
        in_guild = isinstance(user, discord.Member) and (
            not self.rt.settings.discord_guild_id or str(user.guild.id) == self.rt.settings.discord_guild_id)
        async with self.rt.db.session() as s:
            _, actor = await actor_for_discord(
                s, str(user.id), name=getattr(user, "display_name", user.name), role_ids=role_ids if in_guild else None,
                avatar_url=str(user.display_avatar.url) if user.display_avatar else "", in_guild=in_guild)
            yield s, actor
            await s.commit()

    def website(self, path: str = "") -> str:
        return f"{self.rt.settings.base_url}/#/{path.lstrip('/')}"

    async def embed_color(self) -> int:
        async with self.rt.db.session() as s:
            cfg = await get_setting(s, "discord.embeds")
        return ui.hex_color(cfg.get("color"))

    # ---- lifecycle --------------------------------------------------------------------
    async def setup_hook(self) -> None:
        await self.rt.startup()
        async with self.rt.db.session() as s:
            await shifts.recover_active_shifts(s)
            await s.commit()
        for ext in COGS:
            await self.load_extension(ext)
        await self.sync_commands()
        from nexus.bot.notifier import Notifier

        self.notifier = Notifier(self)

        async def on_event(ev):
            if ev.kind == "config.changed":
                invalidate_cache()
                if ev.payload.get("key") == "erlc.server_key_encrypted":
                    await self.rt.refresh_server_key()
            await self.notifier.handle(ev)

        self.tailer = OutboxTailer(self.rt.db, on_event, interval=1.5, name="bot")
        self.tailer.start()
        if self.run_sync:
            self.sync_service = SyncService(self.rt)
            self.sync_service.start()
        self.heartbeat.start()

    async def sync_commands(self) -> None:
        gid = self.rt.settings.discord_guild_id
        try:
            if gid:
                guild = discord.Object(id=int(gid))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d command groups to guild %s", len(synced), gid)
            else:
                synced = await self.tree.sync()
                log.info("Synced %d global command groups (may take up to an hour to appear)", len(synced))
        except discord.HTTPException as exc:
            log.error("Command sync failed: %s", exc)

    @tasks.loop(seconds=30)
    async def heartbeat(self) -> None:
        async with self.rt.db.session() as s:
            await set_state(s, "bot_heartbeat", {
                "user": str(self.user) if self.user else None, "guilds": len(self.guilds),
                "latency_ms": round(self.latency * 1000) if self.latency == self.latency else None,
                "version": __version__, "sync_leader": bool(self.sync_service and self.sync_service.is_leader),
            })
            await s.commit()

    @heartbeat.before_loop
    async def _before_heartbeat(self) -> None:
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s) in %d server(s)", self.user, self.user.id if self.user else "?", len(self.guilds))
        gid = self.rt.settings.discord_guild_id
        if gid and not self.get_guild(int(gid)):
            log.warning("The bot is not in DISCORD_GUILD_ID=%s. Invite it with the URL on System > Discord Integration.", gid)

    async def close(self) -> None:
        log.info("Shutting down bot…")
        self.heartbeat.cancel()
        if self.tailer:
            await self.tailer.stop()
        if self.sync_service:
            await self.sync_service.stop()
        if self.notifier:
            await self.notifier.stop()
        await super().close()
        await self.rt.shutdown()


def run() -> None:  # pragma: no cover - process entry
    from nexus.config import get_settings
    from nexus.logging_setup import setup_logging

    settings = get_settings()
    setup_logging("bot", settings.data_path / "logs", settings.log_level)
    if not settings.discord_bot_token:
        log.error("DISCORD_BOT_TOKEN is not set in config.env — the bot cannot start.")
        raise SystemExit(2)
    bot = NexusBot(Runtime(settings, component="bot"))
    if hasattr(signal, "SIGBREAK"):  # Windows: the launcher sends CTRL_BREAK for a clean shutdown
        def _break(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, _break)
    try:
        bot.run(settings.discord_bot_token, log_handler=None)
    except discord.LoginFailure:
        log.error("Discord rejected the bot token. Check DISCORD_BOT_TOKEN in config.env.")
        raise SystemExit(2)
    except discord.PrivilegedIntentsRequired:
        log.error("Privileged intents are not enabled for this bot in the Discord Developer Portal.")
        raise SystemExit(2)


if __name__ == "__main__":  # pragma: no cover
    run()
