"""Embed renderers shared by commands and auto-refreshing live panels."""

from __future__ import annotations

from typing import Any

import discord

from nexus.bot import ui
from nexus.core.context import SYSTEM
from nexus.services import departments, erlc_ops, incidents, records, shifts, units

PANEL_KINDS = ("server", "incidents", "units", "bolos", "shifts")


def server_embed(ov: dict[str, Any], color: int, website: str = "") -> discord.Embed:
    srv = ov.get("server")
    status_text = {"online": "🟢 Online", "empty": "🟡 Empty", "api_error": "🔴 API error",
                   "not_configured": "⚪ Not configured", "unknown": "⚪ Waiting for first sync"}.get(ov["status"], ov["status"])
    if not srv:
        desc = "No live data yet." if ov["configured"] else "Add your ERLC server key in **System → API Configuration**."
        if ov.get("api_error"):
            desc = f"⚠️ {ov['api_error'].get('message')}"
        return ui.embed("ERLC Server", desc, color=ui.GREY, fields=[("Status", status_text, True)])
    teams = srv.get("teams") or {}
    team_txt = "\n".join(f"**{t}** — {n}" for t, n in sorted(teams.items(), key=lambda x: -x[1])) or "—"
    staff = srv.get("staff") or {}
    staff_n = sum(len(staff.get(k, {})) for k in ("admins", "mods", "helpers")) if staff else None
    e = ui.embed(srv["name"], "", color=color, url=website or None, fields=[
        ("Status", status_text, True),
        ("Players", f"{srv['current_players']}/{srv['max_players']} ({srv['capacity_pct']}%)", True),
        ("Queue", len(srv.get("queue") or []), True),
        ("Join code", f"`{srv['join_key']}`" if srv.get("join_key") else "—", True),
        ("Verification", srv.get("acc_verified_req") or "—", True),
        ("Team balance", "On" if srv.get("team_balance") else "Off", True),
        ("Teams", team_txt, False),
    ])
    if staff_n is not None:
        e.add_field(name="Server staff", value=str(staff_n), inline=True)
    e.add_field(name="Last sync", value=ui.ts(ov.get("fetched_at")), inline=True)
    if ov.get("stale"):
        e.add_field(name="⚠️ Data may be stale", value="The last successful sync was over 3 minutes ago.", inline=False)
    e.set_footer(text="Live data from the official ERLC API · ERLC Nexus")
    return e


async def incidents_embed(s, color: int) -> discord.Embed:
    items, total = await incidents.list_incidents(s, SYSTEM, state="open", limit=15)
    lines = []
    for i in items:
        units_txt = ", ".join(u["callsign"] for u in i["units"]) or "*unassigned*"
        lines.append(f"**P{i['priority']}** `{i['number']}` {i['category_label']} — {i['location'] or 'no location'}"
                     f"\n└ {i['status_label']} · {units_txt} · {ui.ts(i['created_at'])}")
    return ui.embed(f"Active incidents ({total})", ui.chunk_lines(lines) or "No active incidents.", color=color)


async def units_embed(s, color: int) -> discord.Embed:
    rows = await units.serialize_units(s, await units.list_units(s))
    groups: dict[str, list[str]] = {"available": [], "busy": [], "unavailable": []}
    for u in rows:
        inc = f" → `{u['current_incident_number']}`" if u["current_incident_number"] else ""
        groups[u["status_group"]].append(f"`{u['callsign']}` {u['department'] or ''} — {u['status_label']}{inc}")
    e = ui.embed(f"Units ({len(rows)})", "", color=color)
    for key, title in (("available", "🟢 Available"), ("busy", "🟠 Busy"), ("unavailable", "⚫ Unavailable")):
        e.add_field(name=f"{title} ({len(groups[key])})", value=ui.chunk_lines(groups[key], 1000) or "—", inline=False)
    return e


async def bolos_embed(s, color: int) -> discord.Embed:
    rows = await records.list_bolos(s, SYSTEM, status="active", limit=15)
    lines = [f"`{b['number']}` **{b['category']}** {b['plate'] or ''} — {(b['subject_description'] or b['vehicle_description'] or '')[:60]}"
             f"\n└ {b['reason'][:80]} · {ui.ts(b['created_at'])}" for b in rows]
    return ui.embed(f"Active BOLOs ({len(rows)})", ui.chunk_lines(lines) or "No active BOLOs.", color=ui.AMBER)


async def shifts_embed(s, color: int) -> discord.Embed:
    rows = await shifts.on_duty(s)
    lines = [f"**{r['user']}** {r['department'] or ''} {r['callsign'] or ''} — on duty {ui.ts(r['started_at'])}" for r in rows]
    return ui.embed(f"On duty ({len(rows)})", ui.chunk_lines(lines) or "Nobody is on shift.", color=color)


async def render_panel(bot, kind: str) -> discord.Embed:
    color = await bot.embed_color()
    async with bot.rt.db.session() as s:
        if kind == "server":
            return server_embed(await erlc_ops.server_overview(s, bot.rt.erlc), color, bot.website("server"))
        if kind == "incidents":
            return await incidents_embed(s, color)
        if kind == "units":
            return await units_embed(s, color)
        if kind == "bolos":
            return await bolos_embed(s, color)
        if kind == "shifts":
            return await shifts_embed(s, color)
    return ui.error_embed("Unknown panel.")


async def department_embed(s, dept_id: int, color: int) -> discord.Embed:
    d = await departments.get_department(s, dept_id)
    st = await departments.department_stats(s, d.id)
    e = ui.embed(f"{d.name} ({d.abbreviation})", d.description or "", color=ui.hex_color(d.color, color), fields=[
        ("Type", d.kind.upper(), True), ("Active members", st["active_members"], True), ("On shift", st["on_shift"], True),
        ("Units", st["units"], True), ("Shift hours (30d)", st["shift_hours"], True),
        ("Incidents (30d)", st["incidents_participated"], True),
        ("Ranks", " › ".join(r.name for r in d.ranks if not r.is_archived) or "—", False),
        ("Callsign format", f"`{d.callsign_format}`", True),
    ])
    if d.logo_url and d.logo_url.startswith("http"):
        e.set_thumbnail(url=d.logo_url)
    return e
