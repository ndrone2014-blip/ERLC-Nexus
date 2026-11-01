"""Autocomplete providers and small helpers shared by cogs."""

from __future__ import annotations

from discord import app_commands
import discord
from sqlalchemy import func, select

from nexus.db.models import Department, Incident, Person, Unit, Vehicle
from nexus.services import lookups


def _bot(interaction: discord.Interaction):
    return interaction.client


async def department_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        rows = (await s.execute(select(Department).where(Department.is_archived.is_(False)).order_by(Department.sort_order))).scalars()
        cur = current.lower()
        return [app_commands.Choice(name=f"{d.abbreviation} — {d.name}"[:100], value=str(d.id)) for d in rows
                if cur in d.name.lower() or cur in d.abbreviation.lower()][:25]


async def unit_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        rows = (await s.execute(select(Unit).where(Unit.is_archived.is_(False), Unit.callsign.ilike(f"%{current}%"))
                                .order_by(Unit.callsign).limit(25))).scalars()
        return [app_commands.Choice(name=f"{u.callsign} ({u.unit_type}, {u.status.replace('_', ' ')})"[:100], value=u.callsign)
                for u in rows]


async def open_incident_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        open_keys = await lookups.open_status_keys(s)
        rows = (await s.execute(select(Incident).where(Incident.status.in_(open_keys), Incident.number.ilike(f"%{current}%"))
                                .order_by(Incident.priority, Incident.created_at.desc()).limit(25))).scalars()
        return [app_commands.Choice(name=f"{i.number} · P{i.priority} {i.category} · {i.location_name or i.street}"[:100],
                                    value=i.number) for i in rows]


async def any_incident_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        rows = (await s.execute(select(Incident).where(Incident.number.ilike(f"%{current}%"))
                                .order_by(Incident.id.desc()).limit(25))).scalars()
        return [app_commands.Choice(name=f"{i.number} · {i.status} · {i.location_name or i.street}"[:100], value=i.number)
                for i in rows]


async def category_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        cats = await lookups.categories(s)
    return [app_commands.Choice(name=c["label"], value=c["key"]) for c in cats if current.lower() in c["label"].lower()][:25]


async def unit_status_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        sts = await lookups.unit_statuses(s)
    return [app_commands.Choice(name=f"{st['label']} ({st.get('code', '')})".strip(" ()"), value=st["key"])
            for st in sts if current.lower() in st["label"].lower()][:25]


async def incident_status_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        sts = await lookups.incident_statuses(s)
    return [app_commands.Choice(name=st["label"], value=st["key"]) for st in sts if current.lower() in st["label"].lower()][:25]


async def person_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        like = f"%{current}%"
        rows = (await s.execute(select(Person).where(Person.is_archived.is_(False), (Person.first_name + " " + Person.last_name).ilike(like) | Person.number.ilike(like))
                                .limit(25))).scalars()
        return [app_commands.Choice(name=f"{p.number} {p.full_name}"[:100], value=p.number) for p in rows]


async def vehicle_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with _bot(interaction).rt.db.session() as s:
        rows = (await s.execute(select(Vehicle).where(Vehicle.is_archived.is_(False), Vehicle.plate.ilike(f"%{current.upper()}%"))
                                .limit(25))).scalars()
        return [app_commands.Choice(name=f"{v.plate} — {v.color} {v.make} {v.model}"[:100], value=v.plate) for v in rows]


async def resolve_department(s, value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    d = (await s.execute(select(Department).where(func.upper(Department.abbreviation) == value.upper()))).scalar_one_or_none()
    return d.id if d else None


async def priority_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Priorities are configurable, so they come from settings rather than fixed choices."""
    async with _bot(interaction).rt.db.session() as s:
        prios = await lookups.priorities(s)
    return [app_commands.Choice(name=f"P{p['level']} — {p['name']}", value=int(p["level"])) for p in prios
            if current.lower() in f"p{p['level']} {p['name']}".lower()][:25]
