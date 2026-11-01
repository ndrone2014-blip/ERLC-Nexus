"""/cad — incidents and 911 calls."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.common import any_incident_ac, open_incident_ac
from nexus.bot.panels import incidents_embed
from nexus.services import incidents, units as unit_svc


def incident_embed(d: dict, *, timeline: bool = False) -> discord.Embed:
    color = ui.hex_color(d.get("priority_color"), ui.BLUE)
    units_txt = ", ".join(f"`{u['callsign']}`{' ★' if u['is_primary'] else ''}" for u in d["units"]) or "Unassigned"
    e = ui.embed(f"{d['number']} — {d['category_label']}{(' / ' + d['subtype']) if d.get('subtype') else ''}",
                 d.get("description") or "", color=color, fields=[
                     ("Priority", f"P{d['priority']} {d['priority_name']}", True), ("Status", d["status_label"], True),
                     ("Department", d.get("department") or "—", True),
                     ("Location", " · ".join(x for x in [d.get("location"), d.get("street") if d.get("street") != d.get("location") else "",
                                                          f"Postal {d['postal']}" if d.get("postal") else ""] if x) or "—", False),
                     ("Units", units_txt, False), ("Caller", d.get("caller_name") or "—", True),
                     ("Created", ui.ts(d["created_at"]), True), ("Source", d.get("source"), True)])
    if d.get("disposition"):
        e.add_field(name="Disposition", value=d["disposition"], inline=False)
    if timeline and d.get("timeline"):
        lines = [f"{ui.ts(t['created_at'], 'T')} **{t['user']}** — {t['message'] or t['event']}" for t in d["timeline"][-12:]]
        e.add_field(name="Timeline (latest)", value=ui.chunk_lines(lines, 1000), inline=False)
    return e


class Call911Modal(discord.ui.Modal, title="Call 911"):
    location = discord.ui.TextInput(label="Where is the emergency?", max_length=160, placeholder="e.g. Bank on Main St")
    description = discord.ui.TextInput(label="What is happening?", style=discord.TextStyle.paragraph, max_length=1000)
    caller = discord.ui.TextInput(label="Caller name (roleplay)", required=False, max_length=100)
    contact = discord.ui.TextInput(label="Callback number (optional)", required=False, max_length=50)

    def __init__(self, bot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.create_911(s, actor, {
                "location_name": str(self.location.value), "description": str(self.description.value),
                "caller_name": str(self.caller.value or ""), "caller_contact": str(self.contact.value or "")}, source="discord")
            number = inc.number
        await ui.reply(interaction, embed=ui.success_embed(
            f"Your call **{number}** was sent to dispatch. Stay safe and stay on the line (in-game).", "911 call placed"))


class IncidentActions(ui.OwnedView):
    def __init__(self, cog: "CadCog", owner_id: int, incident_id: int, number: str) -> None:
        super().__init__(owner_id, timeout=600)
        self.cog, self.incident_id, self.number = cog, incident_id, number
        self.add_item(discord.ui.Button(label="Open in CAD", url=cog.bot.website(f"cad/incident/{incident_id}"),
                                        style=discord.ButtonStyle.link))

    async def _refresh(self, interaction: discord.Interaction) -> None:
        async with self.cog.bot.ctx(interaction) as (s, actor):
            d = await incidents.detail_dict(s, actor, await incidents.get(s, self.incident_id))
        await interaction.edit_original_response(embed=incident_embed(d, timeline=True), view=self)

    @discord.ui.button(label="Attach my unit", emoji="🚓", style=discord.ButtonStyle.primary)
    async def attach(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        async with self.cog.bot.ctx(interaction) as (s, actor):
            mine = await unit_svc.my_units(s, actor)
            if not mine:
                raise_msg = "You are not on a unit. Use /unit register first."
                await interaction.followup.send(embed=ui.error_embed(raise_msg), ephemeral=True)
                return
            await incidents.assign_unit(s, actor, self.incident_id, mine[0].id)
        await self._refresh(interaction)

    @discord.ui.button(label="On scene", emoji="📍", style=discord.ButtonStyle.secondary)
    async def on_scene(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        async with self.cog.bot.ctx(interaction) as (s, actor):
            mine = [u for u in await unit_svc.my_units(s, actor) if u.current_incident_id == self.incident_id]
            if not mine:
                await interaction.followup.send(embed=ui.error_embed("Your unit is not assigned to this incident."), ephemeral=True)
                return
            await unit_svc.set_status(s, actor, mine[0].id, "on_scene")
        await self._refresh(interaction)

    @discord.ui.button(label="Add note", emoji="📝", style=discord.ButtonStyle.secondary)
    async def note(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = self

        class NoteModal(discord.ui.Modal, title=f"Note on {self.number}"[:45]):
            body = discord.ui.TextInput(label="Note", style=discord.TextStyle.paragraph, max_length=1000)

            async def on_submit(self, inter: discord.Interaction) -> None:
                await inter.response.defer()
                async with view.cog.bot.ctx(inter) as (s, actor):
                    await incidents.add_note(s, actor, view.incident_id, str(self.body.value))
                await view._refresh(inter)

        await interaction.response.send_modal(NoteModal())

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._refresh(interaction)


class IncidentSelect(discord.ui.Select):
    def __init__(self, cog: "CadCog", items: list[dict]) -> None:
        options = [discord.SelectOption(label=f"{i['number']} · P{i['priority']} {i['category_label']}"[:100],
                                        description=(i["location"] or i["description"] or "")[:100], value=str(i["id"]))
                   for i in items[:25]]
        super().__init__(placeholder="Open an incident…", options=options or [discord.SelectOption(label="No incidents", value="0")],
                         disabled=not options)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.cog.bot.ctx(interaction) as (s, actor):
            d = await incidents.detail_dict(s, actor, await incidents.get(s, int(self.values[0])))
        await ui.reply(interaction, embed=incident_embed(d, timeline=True),
                       view=IncidentActions(self.cog, interaction.user.id, d["id"], d["number"]))


class CadCog(commands.GroupCog, group_name="cad", group_description="CAD incidents and 911 calls"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="panel", description="Active incidents with a picker to open details and actions")
    async def panel(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            items, _ = await incidents.list_incidents(s, actor, state="open", limit=25)
            emb = await incidents_embed(s, await self.bot.embed_color())
        view = ui.OwnedView(interaction.user.id, timeout=600)
        view.add_item(IncidentSelect(self, items))
        view.add_item(discord.ui.Button(label="Dispatch Center", url=self.bot.website("cad/dispatch"), style=discord.ButtonStyle.link))
        await ui.reply(interaction, embed=emb, view=view)

    @app_commands.command(name="911", description="Place a 911 call (opens a form)")
    async def call_911(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("cad.911.create")
        await interaction.response.send_modal(Call911Modal(self.bot))

    @app_commands.command(name="incident", description="View an incident with its timeline")
    @app_commands.autocomplete(number=any_incident_ac)
    async def incident(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            d = await incidents.detail_dict(s, actor, await incidents.get(s, number))
        await ui.reply(interaction, embed=incident_embed(d, timeline=True),
                       view=IncidentActions(self, interaction.user.id, d["id"], d["number"]))

    @app_commands.command(name="incidents", description="List incidents")
    @app_commands.choices(state=[app_commands.Choice(name="Open", value="open"), app_commands.Choice(name="Closed", value="closed"),
                                 app_commands.Choice(name="All", value="all")])
    async def list_incidents(self, interaction: discord.Interaction, state: app_commands.Choice[str] | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            items, total = await incidents.list_incidents(s, actor, state=state.value if state else "open",
                                                          sort="recent" if state and state.value != "open" else "priority", limit=20)
        lines = [f"**P{i['priority']}** `{i['number']}` {i['category_label']} — {i['location'] or '—'} · {i['status_label']} · "
                 f"{ui.ts(i['created_at'])}" for i in items]
        await ui.reply(interaction, embed=ui.embed(f"Incidents ({total})", ui.chunk_lines(lines) or "None."))

    @app_commands.command(name="close", description="Close an incident with a disposition")
    @app_commands.autocomplete(number=open_incident_ac)
    @app_commands.describe(disposition="Outcome, e.g. 'Report taken', 'Arrest made', 'Unfounded'")
    async def close(self, interaction: discord.Interaction, number: str, disposition: str,
                    cancel: bool = False) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.get(s, number)
            await incidents.change_status(s, actor, inc.id, "cancelled" if cancel else "closed", disposition=disposition)
        await ui.reply(interaction, embed=ui.success_embed(f"{number} {'cancelled' if cancel else 'closed'} — {disposition}"))

    @app_commands.command(name="reopen", description="Reopen a closed incident")
    @app_commands.autocomplete(number=any_incident_ac)
    async def reopen(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.get(s, number)
            await incidents.change_status(s, actor, inc.id, "pending")
        await ui.reply(interaction, embed=ui.success_embed(f"{number} reopened (Pending Dispatch)."))

    @app_commands.command(name="assign", description="Attach your own unit to an incident (dispatchers: use /dispatch assign)")
    @app_commands.autocomplete(number=open_incident_ac)
    async def assign(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            mine = await unit_svc.my_units(s, actor)
            if not mine:
                await ui.reply(interaction, embed=ui.error_embed("You are not on a unit. Use `/unit register` first."))
                return
            inc = await incidents.get(s, number)
            await incidents.assign_unit(s, actor, inc.id, mine[0].id)
            callsign = mine[0].callsign
        await ui.reply(interaction, embed=ui.success_embed(f"`{callsign}` attached to {number}."))

    @app_commands.command(name="history", description="Full event timeline for an incident")
    @app_commands.autocomplete(number=any_incident_ac)
    async def history(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            inc = await incidents.get(s, number)
            rows = await incidents.history(s, inc.id)
        lines = [f"{ui.ts(r['created_at'], 'f')} **{r['user']}** — {r['message'] or r['event']}" for r in rows]
        await ui.reply(interaction, embed=ui.embed(f"{number} timeline", ui.chunk_lines(lines) or "No events."))


async def setup(bot) -> None:
    await bot.add_cog(CadCog(bot))
