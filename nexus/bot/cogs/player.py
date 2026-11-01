"""/player — player lookup and moderation."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.services import erlc_ops


def player_embed(prof: dict) -> discord.Embed:
    live = prof.get("live") or {}
    rec = prof.get("recorded") or {}
    loc = live.get("location") or {}
    e = ui.embed(prof["name"], f"Roblox ID `{prof['roblox_id']}`", color=ui.GREEN if prof["online"] else ui.GREY, fields=[
        ("In server", "Yes" if prof["online"] else "No", True),
        ("Team", live.get("team") or rec.get("last_team") or "—", True),
        ("Callsign", live.get("callsign") or "—", True),
        ("Permission", live.get("permission") or "—", True),
        ("Wanted stars", live.get("wanted_stars", "—"), True),
        ("Banned", {True: "Yes", False: "No", None: "Unknown (refresh bans)"}[prof.get("banned")], True),
    ])
    if loc.get("street"):
        e.add_field(name="Location (API)", value=f"{loc.get('building') or ''} {loc['street']} · Postal {loc.get('postal') or '—'}".strip(), inline=False)
    if rec:
        e.add_field(name="Recorded by ERLC Nexus", value=f"First seen {ui.ts(rec['first_seen'], 'd')} · "
                    f"Last seen {ui.ts(rec['last_seen'])} · {rec['sessions']} session(s)", inline=False)
    hist = prof.get("history") or []
    if hist:
        e.add_field(name="Recent moderation", value="\n".join(
            f"{'✅' if h['success'] else '❌'} **{h['action']}** {ui.ts(h['created_at'])} — {h['reason'] or ''}"[:200]
            for h in hist[:5]), inline=False)
    return e


class ReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="Reason", required=False, max_length=200, style=discord.TextStyle.paragraph)

    def __init__(self, cog: "PlayerCog", action: str, player: str) -> None:
        super().__init__(title=f"{action.title()} {player}"[:45])
        self.cog, self.action, self.player = cog, action, player

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog._moderate(interaction, self.action, self.player, str(self.reason.value or ""))


class PlayerPanel(ui.OwnedView):
    def __init__(self, cog: "PlayerCog", owner_id: int, player: str) -> None:
        super().__init__(owner_id, timeout=300)
        self.cog, self.player = cog, player

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, emoji="👢")
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReasonModal(self.cog, "kick", self.player))

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReasonModal(self.cog, "ban", self.player))

    @discord.ui.button(label="History", style=discord.ButtonStyle.secondary, emoji="📜")
    async def history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog._history(interaction, self.player)


class PlayerCog(commands.GroupCog, group_name="player", group_description="ERLC player lookup and moderation"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    async def _moderate(self, interaction: discord.Interaction, action: str, player: str, reason: str) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        async with self.bot.ctx(interaction) as (s, actor):
            res = await erlc_ops.moderate(s, self.bot.rt.erlc, actor, action, player, reason)
        await interaction.followup.send(embed=ui.success_embed(
            f"**{res['player']}** {action}{'ned' if action == 'ban' else 'ed'}" + (f" — {reason}" if reason else "")
            + f"\nAPI: {res['result']}", "Moderation action"), ephemeral=True)

    async def _history(self, interaction: discord.Interaction, player: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            try:
                prof = await erlc_ops.find_player(s, player)
                rid, name = prof["roblox_id"], prof["name"]
            except Exception:
                rid, name = None, player
            hist = await erlc_ops.player_history(s, rid, name, limit=25)
        lines = [f"{'✅' if h['success'] else '❌'} **{h['action']}** {ui.ts(h['created_at'])} — {h['reason'] or '—'}" for h in hist]
        await ui.reply(interaction, embed=ui.embed(f"History for {name}", ui.chunk_lines(lines) or "No recorded actions.",
                                                   footer="Recorded by ERLC Nexus"))

    @app_commands.command(name="panel", description="Interactive player card with moderation buttons")
    @app_commands.describe(name="Roblox username or ID")
    async def panel(self, interaction: discord.Interaction, name: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            prof = await erlc_ops.find_player(s, name)
            can_mod = actor.can("erlc.server.moderate")
        view = PlayerPanel(self, interaction.user.id, prof["name"]) if can_mod else None
        await ui.reply(interaction, embed=player_embed(prof), view=view)

    @app_commands.command(name="search", description="Search players in the server by partial name or callsign")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            rows = await erlc_ops.players(s, q=query)
        from nexus.bot.cogs.server import players_embed

        await ui.reply(interaction, embed=players_embed(rows, f"Players matching '{query}'"))

    @app_commands.command(name="info", description="Player profile: live info plus history recorded by Nexus")
    async def info(self, interaction: discord.Interaction, name: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("erlc.server.view")
            prof = await erlc_ops.find_player(s, name)
        await ui.reply(interaction, embed=player_embed(prof))

    @app_commands.command(name="kick", description="Kick a player from the server")
    async def kick(self, interaction: discord.Interaction, name: str, reason: str | None = None) -> None:
        await self._moderate(interaction, "kick", name, reason or "")

    @app_commands.command(name="ban", description="Ban a player from the server")
    async def ban(self, interaction: discord.Interaction, name: str, reason: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("erlc.server.moderate")
        view = ui.ConfirmView(interaction.user.id, confirm_label=f"Ban {name}"[:80])
        await ui.reply(interaction, embed=ui.embed("Confirm ban", f"Ban **{name}**?" + (f"\nReason: {reason}" if reason else ""),
                                                   color=ui.RED), view=view)
        await view.wait()
        if view.value:
            await self._moderate(interaction, "ban", name, reason or "")

    @app_commands.command(name="unban", description="Unban a player")
    async def unban(self, interaction: discord.Interaction, name: str) -> None:
        await self._moderate(interaction, "unban", name, "")

    @app_commands.command(name="history", description="Moderation history recorded by ERLC Nexus")
    async def history(self, interaction: discord.Interaction, name: str) -> None:
        await self._history(interaction, name)


async def setup(bot) -> None:
    await bot.add_cog(PlayerCog(bot))
