"""/server — ERLC server information, commands and announcements."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.panels import server_embed
from nexus.services import erlc_ops


class ServerPanel(ui.OwnedView):
    def __init__(self, bot, owner_id: int) -> None:
        super().__init__(owner_id, timeout=600)
        self.bot = bot
        self.add_item(discord.ui.Button(label="Open dashboard", url=bot.website("server"), style=discord.ButtonStyle.link))

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            ov = await erlc_ops.server_overview(s, self.bot.rt.erlc)
        await interaction.response.edit_message(embed=server_embed(ov, await self.bot.embed_color(), self.bot.website("server")), view=self)

    @discord.ui.button(label="Players", emoji="👥", style=discord.ButtonStyle.secondary)
    async def players(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            rows = await erlc_ops.players(s)
        await ui.reply(interaction, embed=players_embed(rows))


def players_embed(rows: list[dict], title: str = "Players in server") -> discord.Embed:
    by_team: dict[str, list[str]] = {}
    for p in rows:
        cs = f" `{p['callsign']}`" if p.get("callsign") else ""
        loc = p.get("location") or {}
        street = f" · {loc.get('street')}" if loc.get("street") else ""
        by_team.setdefault(p["team"] or "Unknown", []).append(f"{p['name']}{cs}{street}")
    e = ui.embed(f"{title} ({len(rows)})", "" if rows else "Nobody matches.")
    for team, names in sorted(by_team.items()):
        e.add_field(name=f"{team} ({len(names)})", value=ui.chunk_lines(names, 1000), inline=False)
    e.set_footer(text="Live data from the official ERLC API")
    return e


class ServerCog(commands.GroupCog, group_name="server", group_description="ERLC server information and management"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    async def _overview(self, interaction: discord.Interaction):
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            return await erlc_ops.server_overview(s, self.bot.rt.erlc)

    @app_commands.command(name="panel", description="Interactive server panel with refresh and player list")
    async def panel(self, interaction: discord.Interaction) -> None:
        ov = await self._overview(interaction)
        await ui.reply(interaction, embed=server_embed(ov, await self.bot.embed_color(), self.bot.website("server")),
                       view=ServerPanel(self.bot, interaction.user.id), ephemeral=False)

    @app_commands.command(name="info", description="Server name, owner, capacity, join code and settings")
    async def info(self, interaction: discord.Interaction) -> None:
        ov = await self._overview(interaction)
        srv = ov.get("server") or {}
        e = server_embed(ov, await self.bot.embed_color())
        if srv:
            co = ", ".join(str(x) for x in srv.get("co_owner_ids") or []) or "—"
            e.add_field(name="Owner (Roblox ID)", value=str(srv.get("owner_id")), inline=True)
            e.add_field(name="Co-owners", value=co, inline=True)
        await ui.reply(interaction, embed=e, ephemeral=False)

    @app_commands.command(name="status", description="Quick server and API connection status")
    async def status(self, interaction: discord.Interaction) -> None:
        ov = await self._overview(interaction)
        srv = ov.get("server") or {}
        client = self.bot.rt.erlc.status()
        api = "🔴 Key invalid" if client["key_invalid"] else ("🟢 Connected" if not ov.get("api_error") and srv else "🟡 Waiting/err")
        players = f"{srv.get('current_players', '—')}/{srv.get('max_players', '—')}" if srv else "—"
        await ui.reply(interaction, embed=ui.embed("Server status", "", fields=[
            ("Server", srv.get("name", "—"), True), ("Players", players, True), ("API", api, True),
            ("Last sync", ui.ts(ov.get("fetched_at")), True),
            ("Last error", (ov.get("api_error") or {}).get("message", "None"), False)]))

    @app_commands.command(name="players", description="List players in the server")
    @app_commands.describe(team="Only show one team (e.g. Police, Sheriff, Fire, DOT, Civilian)")
    async def players(self, interaction: discord.Interaction, team: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            rows = await erlc_ops.players(s, team=team or "")
        await ui.reply(interaction, embed=players_embed(rows), ephemeral=False)

    @app_commands.command(name="player", description="Look up a player who is currently in the server")
    @app_commands.describe(name="Roblox username, partial name or user ID")
    async def player(self, interaction: discord.Interaction, name: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            prof = await erlc_ops.find_player(s, name)
        from nexus.bot.cogs.player import player_embed

        await ui.reply(interaction, embed=player_embed(prof))

    @app_commands.command(name="refresh", description="Fetch fresh data from the ERLC API now")
    @app_commands.checks.cooldown(1, 15)
    async def refresh(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("erlc.server.view")
        await interaction.response.defer(ephemeral=True)
        sync = self.bot.sync_service
        if sync is None:
            from nexus.erlc.sync import SyncService

            sync = SyncService(self.bot.rt)
        summary = await sync.run_cycle()
        ov = await self._overview(interaction)
        msg = "Refreshed." if summary.get("ok") else f"Refresh failed: {summary.get('error', {}).get('message')}"
        await interaction.followup.send(content=msg, embed=server_embed(ov, await self.bot.embed_color()), ephemeral=True)

    @app_commands.command(name="command", description="Run an in-game command (e.g. :h Hello) through the official API")
    @app_commands.describe(command="The command, starting with ':'")
    async def command(self, interaction: discord.Interaction, command: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.bot.ctx(interaction) as (s, actor):
            res = await erlc_ops.run_command(s, self.bot.rt.erlc, actor, command)
        await interaction.followup.send(embed=ui.success_embed(f"`{res['command']}` → {res['result']}", "Command sent"), ephemeral=True)

    @app_commands.command(name="announcement", description="Send an in-game announcement")
    @app_commands.describe(message="Announcement text (max 250 characters)", style="Hint bar or full-screen message")
    @app_commands.choices(style=[app_commands.Choice(name="Hint (top bar)", value="hint"),
                                 app_commands.Choice(name="Message (full screen)", value="message")])
    async def announcement(self, interaction: discord.Interaction, message: app_commands.Range[str, 1, 250],
                           style: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.bot.ctx(interaction) as (s, actor):
            res = await erlc_ops.announce(s, self.bot.rt.erlc, actor, message, style.value if style else "hint")
        await interaction.followup.send(embed=ui.success_embed(f"Sent: `{res['command']}`", "Announcement sent"), ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(ServerCog(bot))
