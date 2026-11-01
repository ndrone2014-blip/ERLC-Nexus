"""/shift — clock in/out and shift statistics."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.common import department_ac, resolve_department
from nexus.services import shifts
from nexus.services.users import get_or_create_user


class ShiftCog(commands.GroupCog, group_name="shift", group_description="Duty shifts"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="start", description="Clock in")
    @app_commands.autocomplete(department=department_ac)
    async def start(self, interaction: discord.Interaction, department: str | None = None, callsign: str | None = None,
                    notes: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            dept_id = await resolve_department(s, department) if department else None
            sh = await shifts.start(s, actor, department_id=dept_id, callsign=callsign or "", notes=notes or "")
            d = shifts.shift_dict(sh)
        await ui.reply(interaction, embed=ui.success_embed(
            f"You're on duty{(' as `' + d['callsign'] + '`') if d['callsign'] else ''}. Clocked in {ui.ts(d['started_at'], 't')}.",
            "Shift started"))

    @app_commands.command(name="end", description="Clock out")
    async def end(self, interaction: discord.Interaction, notes: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            sh = await shifts.end(s, actor, notes=notes or "")
            d = shifts.shift_dict(sh)
        await ui.reply(interaction, embed=ui.success_embed(f"Shift ended after **{d['duration']}**.", "Shift ended"))

    @app_commands.command(name="status", description="Your current shift and who is on duty")
    async def status(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            st = await shifts.stats(s, actor.user_id)
            on = await shifts.on_duty(s) if actor.can("dept.view") else []
        active = st.get("active")
        e = ui.embed("Shift status", "", color=ui.GREEN if active else ui.GREY, fields=[
            ("You", f"On duty since {ui.ts(active['started_at'])} ({active['duration']})" if active else "Off duty", False),
            ("This week", st["week"], True), ("This month", st["month"], True)])
        if on:
            e.add_field(name=f"On duty ({len(on)})", value=ui.chunk_lines(
                [f"{r['user']} {r['department'] or ''} {r['callsign'] or ''} · {r['duration']}" for r in on], 1000), inline=False)
        await ui.reply(interaction, embed=e)

    @app_commands.command(name="history", description="Recent shifts (yours, or a member's if you supervise)")
    async def history(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            uid = actor.user_id
            if member and member.id != interaction.user.id:
                actor.require("shift.manage")
                uid = (await get_or_create_user(s, str(member.id), username=member.name)).id
            rows = await shifts.history(s, user_id=uid, limit=15)
        lines = [f"{ui.ts(r['started_at'], 'd')} {r['department'] or ''} {r['callsign'] or ''} — **{r['duration']}**"
                 f"{' ✏️' if r['is_adjusted'] else ''}{' (active)' if r['active'] else ''} · {r['status']}" for r in rows]
        await ui.reply(interaction, embed=ui.embed(f"Shift history{' — ' + member.display_name if member else ''}",
                                                   ui.chunk_lines(lines) or "No shifts.", footer="✏️ = time adjusted by a supervisor"))

    @app_commands.command(name="stats", description="Weekly, monthly and all-time hours")
    async def stats(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            uid = actor.user_id
            if member and member.id != interaction.user.id:
                actor.require("shift.manage")
                uid = (await get_or_create_user(s, str(member.id), username=member.name)).id
            st = await shifts.stats(s, uid)
        adj = st["adjustment_delta_seconds"]
        await ui.reply(interaction, embed=ui.embed(f"Shift stats{' — ' + member.display_name if member else ''}", "", fields=[
            ("This week", st["week"], True), ("This month", st["month"], True), ("All time", st["all_time"], True),
            ("Shifts", st["shift_count"], True), ("Average", st["average"], True),
            ("Manual adjustments", f"{st['adjusted_shifts']} shift(s), {adj // 60:+d} min vs actual" if st["adjusted_shifts"] else "None", True)]))


async def setup(bot) -> None:
    await bot.add_cog(ShiftCog(bot))
