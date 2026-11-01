"""/department — department info, roster, stats, ranks."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.common import department_ac, resolve_department
from nexus.bot.panels import department_embed
from nexus.core.context import NotFound
from nexus.services import departments


class DepartmentCog(commands.GroupCog, group_name="department", group_description="Departments and personnel"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    async def _dept(self, s, value: str) -> int:
        dept_id = await resolve_department(s, value)
        if dept_id is None:
            raise NotFound("Department not found.")
        return dept_id

    @app_commands.command(name="panel", description="Department card with roster and stats buttons")
    @app_commands.autocomplete(department=department_ac)
    async def panel(self, interaction: discord.Interaction, department: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            dept_id = await self._dept(s, department)
            emb = await department_embed(s, dept_id, await self.bot.embed_color())
        view = ui.OwnedView(interaction.user.id)
        cog = self

        async def show_roster(inter: discord.Interaction) -> None:
            await cog._send_roster(inter, dept_id)

        btn = discord.ui.Button(label="Roster", emoji="👥")
        btn.callback = show_roster
        view.add_item(btn)
        view.add_item(discord.ui.Button(label="Open in website", url=self.bot.website(f"departments/{dept_id}")))
        await ui.reply(interaction, embed=emb, view=view, ephemeral=False)

    @app_commands.command(name="info", description="Department information")
    @app_commands.autocomplete(department=department_ac)
    async def info(self, interaction: discord.Interaction, department: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            emb = await department_embed(s, await self._dept(s, department), await self.bot.embed_color())
        await ui.reply(interaction, embed=emb)

    async def _send_roster(self, interaction: discord.Interaction, dept_id: int) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            d = await departments.get_department(s, dept_id)
            rows = await departments.roster(s, dept_id)
        lines, current_rank = [], None
        for r in rows:
            if r["rank"] != current_rank:
                current_rank = r["rank"]
                lines.append(f"__**{current_rank or 'No rank'}**__")
            dot = "🟢" if r["on_shift"] else ("🟡" if r["status"] == "leave" else "⚪")
            lines.append(f"{dot} {r['name']} {('`' + r['callsign'] + '`') if r['callsign'] else ''}"
                         f"{' · ' + r['unit'] if r['unit'] else ''}{' (on leave)' if r['status'] == 'leave' else ''}")
        await ui.reply(interaction, embed=ui.embed(f"{d.abbreviation} roster ({len(rows)})", ui.chunk_lines(lines) or "No members yet.",
                                                   color=ui.hex_color(d.color)))

    @app_commands.command(name="roster", description="Department roster grouped by rank")
    @app_commands.autocomplete(department=department_ac)
    async def roster(self, interaction: discord.Interaction, department: str) -> None:
        async with self.bot.ctx(interaction) as (s, _):
            dept_id = await self._dept(s, department)
        await self._send_roster(interaction, dept_id)

    @app_commands.command(name="stats", description="Department statistics")
    @app_commands.autocomplete(department=department_ac)
    async def stats(self, interaction: discord.Interaction, department: str, days: app_commands.Range[int, 1, 365] = 30) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            dept_id = await self._dept(s, department)
            d = await departments.get_department(s, dept_id)
            st = await departments.department_stats(s, dept_id, days)
        await ui.reply(interaction, embed=ui.embed(f"{d.abbreviation} — last {days} days", "", color=ui.hex_color(d.color), fields=[
            ("Active members", st["active_members"], True), ("On shift now", st["on_shift"], True),
            ("Shift hours", st["shift_hours"], True), ("Shifts", st["shifts"], True),
            ("Participation", f"{st['participation_pct']}%" if st["participation_pct"] is not None else "—", True),
            ("Incidents participated", st["incidents_participated"], True), ("Traffic stops", st["traffic_stops"], True),
            ("Reports", st["reports"], True), ("Units", st["units"], True)],
            footer="Participation = members with ≥1 shift ÷ active members"))

    @app_commands.command(name="ranks", description="Rank structure")
    @app_commands.autocomplete(department=department_ac)
    async def ranks(self, interaction: discord.Interaction, department: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("dept.view")
            d = await departments.get_department(s, await self._dept(s, department))
        lines = [f"{i + 1}. **{r.name}**{' — Command' if r.is_command else ' — Supervisor' if r.is_supervisor else ''}"
                 for i, r in enumerate(sorted([r for r in d.ranks if not r.is_archived], key=lambda r: r.sort_order))]
        await ui.reply(interaction, embed=ui.embed(f"{d.abbreviation} ranks", "\n".join(lines) or "No ranks.", color=ui.hex_color(d.color)))


async def setup(bot) -> None:
    await bot.add_cog(DepartmentCog(bot))
