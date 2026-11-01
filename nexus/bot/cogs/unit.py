"""/unit — unit registration, status, members."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.bot.common import department_ac, resolve_department, unit_ac, unit_status_ac
from nexus.bot.panels import units_embed
from nexus.core.context import NotFound
from nexus.services import lookups, units as unit_svc
from nexus.services.users import get_or_create_user


def unit_embed(u: dict) -> discord.Embed:
    loc = u["location"]
    loc_txt = loc["text"] or ("—" if loc["x"] is None else f"{loc['x']:.0f}, {loc['z']:.0f}")
    if loc["source"] != "none":
        loc_txt += f" *({'API position' if loc['source'] == 'api' else loc['source']})*"
    e = ui.embed(f"{u['callsign']} — {u['unit_type']}", u.get("vehicle_description") or "",
                 color=ui.hex_color(u["status_color"]), fields=[
                     ("Status", u["status_label"], True), ("Department", u["department"] or "—", True),
                     ("Incident", u["current_incident_number"] or "—", True),
                     ("Members", ", ".join(m["name"] + (" ★" if m["is_primary"] else "") for m in u["members"]) or "—", False),
                     ("Location", loc_txt, False), ("Status since", ui.ts(u["status_changed_at"]), True)])
    return e


class StatusSelect(discord.ui.Select):
    def __init__(self, cog: "UnitCog", unit_id: int, statuses: list[dict], current: str) -> None:
        super().__init__(placeholder="Change status…", options=[
            discord.SelectOption(label=st["label"], value=st["key"], description=st.get("code") or None, default=st["key"] == current)
            for st in statuses[:25]])
        self.cog, self.unit_id = cog, unit_id

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.cog.bot.ctx(interaction) as (s, actor):
            await unit_svc.set_status(s, actor, self.unit_id, self.values[0])
            u = (await unit_svc.serialize_units(s, [await unit_svc.get_unit(s, self.unit_id)]))[0]
        await interaction.response.edit_message(embed=unit_embed(u), view=self.view)


class UnitCog(commands.GroupCog, group_name="unit", group_description="CAD units"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    async def _my_or_named(self, s, actor, unit: str | None):
        if unit:
            return await unit_svc.find_unit(s, unit)
        mine = await unit_svc.my_units(s, actor)
        if not mine:
            raise NotFound("You are not on a unit. Use /unit register or pass a callsign.")
        return mine[0]

    @app_commands.command(name="panel", description="Your unit with a quick status picker")
    @app_commands.autocomplete(unit=unit_ac)
    async def panel(self, interaction: discord.Interaction, unit: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            u_obj = await self._my_or_named(s, actor, unit)
            u = (await unit_svc.serialize_units(s, [u_obj]))[0]
            statuses = await lookups.unit_statuses(s)
        view = ui.OwnedView(interaction.user.id, timeout=900)
        view.add_item(StatusSelect(self, u["id"], statuses, u["status"]))
        await ui.reply(interaction, embed=unit_embed(u), view=view)

    @app_commands.command(name="register", description="Register a unit (callsign is suggested if left empty)")
    @app_commands.autocomplete(department=department_ac)
    @app_commands.describe(callsign="Leave empty to use the department's callsign format", unit_type="e.g. Patrol, Engine, Tow")
    async def register(self, interaction: discord.Interaction, department: str, callsign: str | None = None,
                       unit_type: str | None = None, vehicle: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            dept_id = await resolve_department(s, department)
            u = await unit_svc.register_unit(s, actor, {"department_id": dept_id, "callsign": callsign or "",
                                                        "unit_type": unit_type or "", "vehicle_description": vehicle or "",
                                                        "member_ids": [actor.user_id] if actor.user_id else []})
            await s.flush()
            data = (await unit_svc.serialize_units(s, [await unit_svc.get_unit(s, u.id)]))[0]
        await ui.reply(interaction, embed=unit_embed(data), ephemeral=False)

    @app_commands.command(name="status", description="Update unit status (your unit by default)")
    @app_commands.autocomplete(status=unit_status_ac, unit=unit_ac)
    async def status(self, interaction: discord.Interaction, status: str, unit: str | None = None,
                     note: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            u = await self._my_or_named(s, actor, unit)
            await unit_svc.set_status(s, actor, u.id, status, note=note or "")
            st = await lookups.unit_status(s, status)
            callsign = u.callsign
        await ui.reply(interaction, embed=ui.success_embed(f"`{callsign}` → **{st['label']}**"))

    @app_commands.command(name="assign", description="Add a member to a unit")
    @app_commands.autocomplete(unit=unit_ac)
    async def assign(self, interaction: discord.Interaction, unit: str, member: discord.Member, primary: bool = False) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            u = await unit_svc.find_unit(s, unit)
            target = await get_or_create_user(s, str(member.id), username=member.name, display_name=member.display_name)
            await s.flush()
            await unit_svc.add_member(s, actor, u.id, target.id, primary=primary)
        await ui.reply(interaction, embed=ui.success_embed(f"{member.mention} added to `{unit}`."))

    @app_commands.command(name="remove", description="Remove a member from a unit, or take the unit out of service permanently")
    @app_commands.autocomplete(unit=unit_ac)
    @app_commands.describe(member="Leave empty to remove the whole unit (requires unit management)")
    async def remove(self, interaction: discord.Interaction, unit: str, member: discord.Member | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            u = await unit_svc.find_unit(s, unit)
            if member is None:
                await unit_svc.archive_unit(s, actor, u.id)
                msg = f"Unit `{unit}` removed."
            else:
                target = await get_or_create_user(s, str(member.id), username=member.name)
                await s.flush()
                await unit_svc.remove_member(s, actor, u.id, target.id)
                msg = f"{member.mention} removed from `{unit}`."
        await ui.reply(interaction, embed=ui.success_embed(msg))

    @app_commands.command(name="list", description="List units by status")
    @app_commands.autocomplete(department=department_ac)
    async def list_units(self, interaction: discord.Interaction, department: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            if department:
                dept_id = await resolve_department(s, department)
                rows = await unit_svc.serialize_units(s, await unit_svc.list_units(s, department_id=dept_id))
                lines = [f"`{u['callsign']}` {u['unit_type']} — {u['status_label']}" for u in rows]
                emb = ui.embed(f"Units ({len(rows)})", ui.chunk_lines(lines) or "None.")
            else:
                emb = await units_embed(s, await self.bot.embed_color())
        await ui.reply(interaction, embed=emb)

    @app_commands.command(name="history", description="Recent history for a unit")
    @app_commands.autocomplete(unit=unit_ac)
    async def history(self, interaction: discord.Interaction, unit: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            u = await unit_svc.find_unit(s, unit)
            rows = await unit_svc.unit_history(s, u.id, limit=25)
        lines = [f"{ui.ts(r['created_at'], 'f')} **{r['event']}** {r['old'] or ''} → {r['new'] or ''}"
                 f"{' · ' + r['incident'] if r['incident'] else ''} ({r['user'] or 'System'})" for r in rows]
        await ui.reply(interaction, embed=ui.embed(f"{unit} history", ui.chunk_lines(lines) or "No history."))


async def setup(bot) -> None:
    await bot.add_cog(UnitCog(bot))
