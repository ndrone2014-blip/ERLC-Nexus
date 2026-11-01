"""/nexus — help, status, live panels, account linking and context menus."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus import __credits__, __version__
from nexus.bot import ui
from nexus.bot.panels import PANEL_KINDS, render_panel
from nexus.core.audit import audit
from nexus.db.models import DiscordPanel
from nexus.services import departments, incidents, shifts
from nexus.services.users import get_or_create_user, update_user

HELP = {
    "/server": "panel · info · status · players · player · refresh · command · announcement",
    "/player": "panel · search · info · kick · ban · unban · history",
    "/cad": "panel · 911 · incident · incidents · close · reopen · assign (self) · history",
    "/dispatch": "panel · create · assign · update · close (clear unit) · queue",
    "/unit": "panel · register · status · assign (member) · remove · list · history",
    "/mdt": "panel · person · vehicle · bolo · traffic-stop · report",
    "/bolo": "create · search · update · close · list",
    "/record": "person · vehicle · search · update · history",
    "/report": "create · submit · view · search · review",
    "/department": "panel · info · roster · stats · ranks",
    "/shift": "start · end · status · history · stats",
    "/nexus": "help · status · dashboard · link-roblox · panel",
}


class NexusCog(commands.GroupCog, group_name="nexus", group_description="ERLC Nexus utilities"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()
        self.profile_menu = app_commands.ContextMenu(name="Nexus profile", callback=self.profile_context)
        self.incident_menu = app_commands.ContextMenu(name="Create CAD incident", callback=self.incident_context)
        bot.tree.add_command(self.profile_menu)
        bot.tree.add_command(self.incident_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.profile_menu.name, type=self.profile_menu.type)
        self.bot.tree.remove_command(self.incident_menu.name, type=self.incident_menu.type)

    @app_commands.command(name="help", description="What ERLC Nexus can do")
    async def help(self, interaction: discord.Interaction) -> None:
        e = ui.embed("ERLC Nexus", "The free, all-in-one ERLC management platform: CAD, MDT, records and server management. "
                     "Everything is free — no premium tiers.", fields=[(k, v, False) for k, v in HELP.items()],
                     footer=__credits__)
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Open website", url=self.bot.website()))
        await ui.reply(interaction, embed=e, view=v)

    @app_commands.command(name="status", description="Bot, API and database status")
    async def status(self, interaction: discord.Interaction) -> None:
        client = self.bot.rt.erlc.status()
        db_ok = await self.bot.rt.db.ping()
        api = "Not configured" if not client["configured"] else ("Key invalid" if client["key_invalid"] else
                                                                ("Error: " + client["last_error"]["message"] if client["last_error"] else "OK"))
        await ui.reply(interaction, embed=ui.embed("ERLC Nexus status", "", fields=[
            ("Version", __version__, True), ("Discord latency", f"{round(self.bot.latency * 1000)} ms", True),
            ("Database", "OK" if db_ok else "Unavailable", True), ("ERLC API", api, False),
            ("Sync leader", "This bot" if self.bot.sync_service and self.bot.sync_service.is_leader else "Website / other", True)],
            footer=__credits__))

    @app_commands.command(name="dashboard", description="Link to the ERLC Nexus website")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Dashboard", url=self.bot.website()))
        v.add_item(discord.ui.Button(label="Dispatch Center", url=self.bot.website("cad/dispatch")))
        v.add_item(discord.ui.Button(label="MDT", url=self.bot.website("mdt")))
        await ui.reply(interaction, content="Open ERLC Nexus (sign in with Discord):", view=v)

    @app_commands.command(name="link-roblox", description="Link your Roblox account (enables automatic unit positions)")
    @app_commands.describe(username="Your Roblox username", user_id="Your numeric Roblox user ID")
    async def link_roblox(self, interaction: discord.Interaction, username: str, user_id: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            await update_user(s, actor, actor.user_id, {"roblox_username": username, "roblox_id": user_id})
        await ui.reply(interaction, embed=ui.success_embed(
            f"Linked to Roblox **{username}** (`{user_id}`). When you are in-game on a unit, its map position updates from the "
            "official ERLC API.", "Roblox linked"))

    @app_commands.command(name="panel", description="Post an auto-updating live panel in a channel")
    @app_commands.choices(kind=[app_commands.Choice(name=k.title(), value=k) for k in PANEL_KINDS])
    async def panel(self, interaction: discord.Interaction, kind: app_commands.Choice[str],
                    channel: discord.TextChannel | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("system.configure")
        target = channel or interaction.channel
        emb = await render_panel(self.bot, kind.value)
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Open ERLC Nexus", url=self.bot.website()))
        msg = await target.send(embed=emb, view=v)
        async with self.bot.ctx(interaction) as (s, actor):
            s.add(DiscordPanel(kind=kind.value, channel_id=str(target.id), message_id=str(msg.id), created_by=actor.user_id))
            await audit(s, actor, "system", "discord.panel_created", target_type="panel", target_ref=f"{kind.value}#{target.id}")
        await ui.reply(interaction, embed=ui.success_embed(f"Live **{kind.name}** panel posted in {target.mention}. "
                                                           "It refreshes automatically; delete the message to remove it."))

    # ---- context menus -----------------------------------------------------------------
    async def profile_context(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            user = await get_or_create_user(s, str(member.id), username=member.name, display_name=member.display_name)
            await s.flush()
            prof = await departments.personnel_profile(s, actor, user.id)
            st = await shifts.stats(s, user.id)
        mem = "\n".join(f"**{m['department']}** {m['rank'] or ''} {('`' + m['callsign'] + '`') if m['callsign'] else ''} ({m['status']})"
                        for m in prof["memberships"]) or "No departments"
        e = ui.embed(f"{prof['user']['name']}", "", fields=[
            ("Departments", mem, False), ("Roblox", prof["user"]["roblox_username"] or "Not linked", True),
            ("On duty", "Yes" if st.get("active") else "No", True), ("Hours this week", st["week"], True)])
        if member.display_avatar:
            e.set_thumbnail(url=member.display_avatar.url)
        await ui.reply(interaction, embed=e)

    async def incident_context(self, interaction: discord.Interaction, message: discord.Message) -> None:
        bot = self.bot

        class FromMessage(discord.ui.Modal, title="Create CAD incident"):
            location = discord.ui.TextInput(label="Location", max_length=160)
            description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=2000,
                                               default=(message.content or "")[:2000])
            priority = discord.ui.TextInput(label="Priority (1-4)", default="3", max_length=1)

            async def on_submit(self, inter: discord.Interaction) -> None:
                async with bot.ctx(inter) as (s, actor):
                    pr = int(self.priority.value) if str(self.priority.value).isdigit() else 3
                    inc = await incidents.create(s, actor, {"category": "other", "priority": pr,
                                                            "location_name": str(self.location.value),
                                                            "description": str(self.description.value),
                                                            "caller_name": message.author.display_name}, source="discord")
                    number = inc.number
                await ui.reply(inter, embed=ui.success_embed(f"Incident **{number}** created from {message.jump_url}."))

        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("cad.incident.create")
        await interaction.response.send_modal(FromMessage())


async def setup(bot) -> None:
    await bot.add_cog(NexusCog(bot))
