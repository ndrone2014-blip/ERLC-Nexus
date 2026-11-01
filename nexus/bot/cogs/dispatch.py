"""/dispatch — dispatcher tools: queue, create, assign, update, clear."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.common import category_ac, department_ac, incident_status_ac, open_incident_ac, priority_ac, resolve_department, unit_ac
from nexus.bot.panels import units_embed
from nexus.services import incidents


def queue_embed(items: list[dict]) -> discord.Embed:
    lines = []
    for i in items:
        flag = "⏰ " if i.get("overdue") else ""
        units_txt = ", ".join(u["callsign"] for u in i["units"]) or "**awaiting units**"
        mins = i["waiting_seconds"] // 60
        lines.append(f"{flag}**P{i['priority']}** `{i['number']}` {i['category_label']} — {i['location'] or '—'}\n"
                     f"└ {i['status_label']} · {units_txt} · waiting {mins}m")
    return ui.embed(f"Dispatch queue ({len(items)})", ui.chunk_lines(lines) or "Queue is clear. 🎉",
                    color=ui.RED if any(i.get("overdue") for i in items) else ui.BLUE)


class DispatchCog(commands.GroupCog, group_name="dispatch", group_description="Dispatcher tools"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="panel", description="Dispatch overview: queue and unit board")
    async def panel(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            items = await incidents.queue(s, actor)
            ub = await units_embed(s, await self.bot.embed_color())
            calls = await incidents.pending_erlc_calls(s)
        embeds = [queue_embed(items), ub]
        if calls:
            embeds.append(ui.embed(f"In-game calls awaiting review ({len(calls)})", "\n".join(
                f"#{c['call_number']} {c['team']} — {c['description'][:80]} · {c['location']}" for c in calls[:10]),
                color=ui.RED, footer="Source: official ERLC API — accept in the Dispatch Center"))
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open Dispatch Center", url=self.bot.website("cad/dispatch")))
        if interaction.response.is_done():
            await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embeds=embeds, view=view, ephemeral=True)

    @app_commands.command(name="create", description="Create an incident")
    @app_commands.autocomplete(category=category_ac, priority=priority_ac, department=department_ac)
    async def create(self, interaction: discord.Interaction, category: str, priority: int, location: str, description: str,
                     department: str | None = None, caller: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            dept_id = await resolve_department(s, department) if department else None
            inc = await incidents.create(s, actor, {"category": category, "priority": priority, "location_name": location,
                                                    "description": description, "department_id": dept_id,
                                                    "caller_name": caller or ""}, source="discord")
            d = await incidents.summary_dict(s, await incidents.get(s, inc.id))
        from nexus.bot.cogs.cad import incident_embed

        await ui.reply(interaction, embed=incident_embed({**d, "disposition": ""}), ephemeral=False)

    @app_commands.command(name="assign", description="Assign a unit to an incident")
    @app_commands.autocomplete(incident=open_incident_ac, unit=unit_ac)
    async def assign(self, interaction: discord.Interaction, incident: str, unit: str, primary: bool = False) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.get(s, incident)
            await incidents.assign_unit(s, actor, inc.id, unit, primary=primary)
        await ui.reply(interaction, embed=ui.success_embed(f"`{unit}` assigned to {incident}."), ephemeral=False)

    @app_commands.command(name="update", description="Update an incident's status, priority or add a dispatcher note")
    @app_commands.autocomplete(incident=open_incident_ac, status=incident_status_ac, priority=priority_ac)
    async def update(self, interaction: discord.Interaction, incident: str, status: str | None = None,
                     priority: int | None = None, note: str | None = None) -> None:
        if not (status or priority or note):
            await ui.reply(interaction, embed=ui.error_embed("Provide a status, priority or note."))
            return
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.get(s, incident)
            if priority:
                await incidents.change_priority(s, actor, inc, priority)
            if status:
                await incidents.change_status(s, actor, inc.id, status)
            if note:
                await incidents.add_note(s, actor, inc.id, note)
        await ui.reply(interaction, embed=ui.success_embed(f"{incident} updated."))

    @app_commands.command(name="close", description="Clear a unit from an incident (closing incidents: /cad close)")
    @app_commands.autocomplete(incident=open_incident_ac, unit=unit_ac)
    async def close(self, interaction: discord.Interaction, incident: str, unit: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            inc = await incidents.get(s, incident)
            await incidents.clear_unit(s, actor, inc.id, unit)
        await ui.reply(interaction, embed=ui.success_embed(f"`{unit}` cleared from {incident}."))

    @app_commands.command(name="queue", description="Incidents waiting for dispatch, sorted by priority")
    @app_commands.choices(sort=[app_commands.Choice(name="Priority", value="priority"), app_commands.Choice(name="Oldest first", value="age")])
    async def queue(self, interaction: discord.Interaction, sort: app_commands.Choice[str] | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            items = await incidents.queue(s, actor, sort=sort.value if sort else "priority")
        await ui.reply(interaction, embed=queue_embed(items))


async def setup(bot) -> None:
    await bot.add_cog(DispatchCog(bot))
