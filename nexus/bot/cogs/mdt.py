"""/mdt — officer Mobile Data Terminal lookups and traffic stops."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from nexus.bot import ui
from nexus.services import incidents, records, reports, shifts, units as unit_svc

DISCLAIMER = "Fictional ERLC roleplay record"


def person_embed(p: dict) -> discord.Embed:
    flags = ", ".join(p.get("flags") or []) or "None"
    e = ui.embed(f"{p['name']} ({p['number']})", p.get("description") or "", color=ui.RED if p.get("flags") else ui.BLUE, fields=[
        ("DOB", p.get("date_of_birth") or "—", True), ("License", p.get("license_status"), True), ("Flags", flags, True),
        ("Aliases", ", ".join(p.get("aliases") or []) or "—", False)], footer=DISCLAIMER)
    if p.get("vehicles"):
        e.add_field(name="Vehicles", value="\n".join(f"`{v['plate']}` {v['color']} {v['make']} {v['model']} ({v['registration_status']})"
                                                    for v in p["vehicles"][:8]), inline=False)
    active_w = [w for w in p.get("warrants", []) if w["status"] == "active"]
    if active_w:
        e.add_field(name="⚠️ Active warrants", value="\n".join(f"`{w['number']}` {w['warrant_type']} — {w['charges'][:80]}"
                                                            for w in active_w[:5]), inline=False)
    active_b = [b for b in p.get("bolos", []) if b["is_active"]]
    if active_b:
        e.add_field(name="⚠️ Active BOLOs", value="\n".join(f"`{b['number']}` {b['reason'][:80]}" for b in active_b[:5]), inline=False)
    if p.get("traffic_stops"):
        e.add_field(name="Recent traffic stops", value="\n".join(f"`{t['number']}` {t['outcome'] or t['status']} · {ui.ts(t['started_at'], 'd')}"
                                                               for t in p["traffic_stops"][:5]), inline=False)
    return e


def plate_embed(res: dict) -> discord.Embed:
    v = res.get("vehicle")
    alerts = res.get("alerts") or []
    color = ui.RED if alerts else (ui.GREEN if v else ui.GREY)
    if not v:
        e = ui.embed(f"Plate {res['plate']}", "No vehicle record found.", color=color, footer=DISCLAIMER)
    else:
        e = ui.embed(f"Plate {v['plate']}", f"{v['year']} {v['color']} {v['make']} {v['model']}".strip(), color=color, fields=[
            ("Owner", v["owner_name"] or "—", True), ("Registration", v["registration_status"], True),
            ("Insurance", v["insurance_status"], True), ("Category", v["category"], True)], footer=DISCLAIMER)
    if alerts:
        e.add_field(name="⚠️ Alerts", value="\n".join(alerts), inline=False)
    return e


class EndStopView(ui.OwnedView):
    def __init__(self, bot, owner_id: int, stop_id: int) -> None:
        super().__init__(owner_id, timeout=3600)
        self.bot, self.stop_id = bot, stop_id
        select = discord.ui.Select(placeholder="Complete stop with outcome…", options=[
            discord.SelectOption(label=o, value=o) for o in records.TRAFFIC_OUTCOMES])
        select.callback = self._complete
        self.add_item(select)

    async def _complete(self, interaction: discord.Interaction) -> None:
        outcome = interaction.data["values"][0]
        async with self.bot.ctx(interaction) as (s, actor):
            t = await records.end_traffic_stop(s, actor, self.stop_id, outcome=outcome)
            number = t.number
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=ui.success_embed(f"Traffic stop **{number}** completed — {outcome}."), view=self)

    @discord.ui.button(label="Cancel stop", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            t = await records.end_traffic_stop(s, actor, self.stop_id, cancel=True)
        await interaction.response.edit_message(embed=ui.success_embed(f"Traffic stop {t.number} cancelled."), view=None)


class MdtCog(commands.GroupCog, group_name="mdt", group_description="Mobile Data Terminal"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="panel", description="Your MDT: unit, status, assigned calls and shift")
    async def panel(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.view")
            my = await unit_svc.serialize_units(s, await unit_svc.my_units(s, actor))
            calls, _ = await incidents.list_incidents(s, actor, state="open", mine=True, limit=10)
            st = await shifts.stats(s, actor.user_id)
            stops = await records.list_traffic_stops(s, actor, status="active", mine=True) if actor.can("cad.traffic.manage") else []
        u = my[0] if my else None
        e = ui.embed(f"MDT — {actor.name}", "", fields=[
            ("Unit", f"`{u['callsign']}` {u['department'] or ''}" if u else "Not on a unit", True),
            ("Status", u["status_label"] if u else "—", True),
            ("Shift", f"On duty {ui.ts(st['active']['started_at'])}" if st.get("active") else "Off duty", True),
            ("Assigned calls", "\n".join(f"**P{c['priority']}** `{c['number']}` {c['category_label']} — {c['location']}" for c in calls) or "None", False),
            ("Active traffic stops", "\n".join(f"`{t['number']}` {t['plate']} · {t['location']}" for t in stops) or "None", False),
            ("Hours this week", st["week"], True)])
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open web MDT", url=self.bot.website("mdt")))
        await ui.reply(interaction, embed=e, view=view)

    @app_commands.command(name="person", description="Search person records")
    async def person(self, interaction: discord.Interaction, query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            rows = await records.search_persons(s, actor, query, limit=10)
            prof = await records.person_profile(s, actor, rows[0]["id"]) if len(rows) == 1 else None
        if prof:
            await ui.reply(interaction, embed=person_embed(prof))
        else:
            lines = [f"`{p['number']}` **{p['name']}** · DOB {p['date_of_birth'] or '—'} · {p['license_status']}" for p in rows]
            await ui.reply(interaction, embed=ui.embed(f"People matching '{query}'", ui.chunk_lines(lines) or "No records found.",
                                                       footer=DISCLAIMER))

    @app_commands.command(name="vehicle", description="Run a plate (or search make/model/owner)")
    async def vehicle(self, interaction: discord.Interaction, plate_or_query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            res = await records.plate_check(s, actor, plate_or_query)
            if res["vehicle"] is None:
                rows = await records.search_vehicles(s, actor, plate_or_query, limit=10)
            else:
                rows = []
        if res["vehicle"] or not rows:
            await ui.reply(interaction, embed=plate_embed(res))
        else:
            lines = [f"`{v['plate']}` {v['color']} {v['make']} {v['model']} · {v['owner_name'] or '—'} · {v['registration_status']}" for v in rows]
            await ui.reply(interaction, embed=ui.embed(f"Vehicles matching '{plate_or_query}'", ui.chunk_lines(lines), footer=DISCLAIMER))

    @app_commands.command(name="bolo", description="Check a name, plate or description against active BOLOs")
    async def bolo(self, interaction: discord.Interaction, query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            rows = await records.list_bolos(s, actor, status="active", q=query)
        lines = [f"⚠️ `{b['number']}` **{b['category']}** {b['plate'] or ''} — {b['reason'][:100]}" for b in rows]
        await ui.reply(interaction, embed=ui.embed(f"BOLO check: {query}", ui.chunk_lines(lines) or "✅ No active BOLO matches.",
                                                   color=ui.RED if rows else ui.GREEN))

    @app_commands.command(name="traffic-stop", description="Start a traffic stop (complete it with the outcome picker)")
    async def traffic_stop(self, interaction: discord.Interaction, location: str, plate: str | None = None,
                           vehicle: str | None = None, reason: str | None = None, driver: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            t = await records.start_traffic_stop(s, actor, {"location": location, "plate": plate or "",
                                                            "vehicle_description": vehicle or "", "reason": reason or "",
                                                            "driver_name": driver or ""})
            check = await records.plate_check(s, actor, t.plate) if t.plate else None
            data = records.traffic_dict(t)
        e = ui.embed(f"🚔 Traffic stop {data['number']}", data["reason"] or "", fields=[
            ("Location", data["location"], True), ("Plate", data["plate"] or "—", True), ("Vehicle", data["vehicle_description"] or "—", True),
            ("Driver", data["driver_name"] or "—", True), ("Callsign", data["callsign"] or "—", True)], footer=DISCLAIMER)
        if check and check["alerts"]:
            e.color = ui.RED
            e.add_field(name="⚠️ Plate alerts", value="\n".join(check["alerts"]), inline=False)
        await ui.reply(interaction, embed=e, view=EndStopView(self.bot, interaction.user.id, data["id"]))

    @app_commands.command(name="report", description="Your incident reports and their review status")
    async def report(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            rows = await reports.search(s, actor, mine=True, limit=15)
        lines = [f"`{r['number']}` {r['title'][:60]} — **{r['status_label']}** · {ui.ts(r['updated_at'])}" for r in rows]
        await ui.reply(interaction, embed=ui.embed("My reports", ui.chunk_lines(lines) or "No reports yet. Use /report create."))


async def setup(bot) -> None:
    await bot.add_cog(MdtCog(bot))
