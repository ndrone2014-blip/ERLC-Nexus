"""/record — create and update person/vehicle records, central search."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from nexus.bot import ui
from nexus.bot.common import person_ac, vehicle_ac
from nexus.core.context import NotFound
from nexus.db.models import Person, Vehicle
from nexus.services import records, search as search_svc

DISCLAIMER = "Fictional ERLC roleplay record"


async def _person(s, ref: str) -> Person:
    p = (await s.execute(select(Person).where(Person.number == ref.upper().strip()))).scalar_one_or_none()
    if p is None:
        raise NotFound(f"Person {ref} not found.")
    return p


async def _vehicle(s, ref: str) -> Vehicle:
    v = (await s.execute(select(Vehicle).where(Vehicle.plate == records.norm_plate(ref), Vehicle.is_archived.is_(False)))).scalar_one_or_none()
    if v is None:
        raise NotFound(f"Vehicle {ref} not found.")
    return v


class PersonModal(discord.ui.Modal):
    first_name = discord.ui.TextInput(label="First name", max_length=60)
    last_name = discord.ui.TextInput(label="Last name", required=False, max_length=60)
    dob = discord.ui.TextInput(label="Date of birth (roleplay)", required=False, max_length=20, placeholder="e.g. 1995-04-12")
    aliases = discord.ui.TextInput(label="Aliases (comma separated)", required=False, max_length=200)
    notes = discord.ui.TextInput(label="Description / notes", required=False, max_length=1500, style=discord.TextStyle.paragraph)

    def __init__(self, bot, person_id: int | None = None, prefill: dict | None = None) -> None:
        super().__init__(title="Edit person record" if person_id else "New person record")
        self.bot, self.person_id = bot, person_id
        for field, key in ((self.first_name, "first_name"), (self.last_name, "last_name"), (self.dob, "date_of_birth"),
                           (self.notes, "notes")):
            if prefill and prefill.get(key):
                field.default = str(prefill[key])[:field.max_length]
        if prefill and prefill.get("aliases"):
            self.aliases.default = ", ".join(prefill["aliases"])[:200]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        data = {"first_name": str(self.first_name.value), "last_name": str(self.last_name.value or ""),
                "date_of_birth": str(self.dob.value or ""), "aliases": str(self.aliases.value or ""),
                "notes": str(self.notes.value or "")}
        async with self.bot.ctx(interaction) as (s, actor):
            if self.person_id:
                p = await records.update_person(s, actor, self.person_id, data)
            else:
                p = await records.create_person(s, actor, data)
            d = records.person_dict(p)
        await ui.reply(interaction, embed=ui.success_embed(f"`{d['number']}` **{d['name']}** saved.", "Person record"))


class RecordCog(commands.GroupCog, group_name="record", group_description="Person and vehicle records"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="person", description="Create a person record (opens a form)")
    async def person(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            if not (actor.can("cad.records.edit") or actor.can("civ.use")):
                actor.require("cad.records.edit")
        await interaction.response.send_modal(PersonModal(self.bot))

    @app_commands.command(name="vehicle", description="Register a vehicle record")
    @app_commands.autocomplete(owner=person_ac)
    @app_commands.choices(registration=[app_commands.Choice(name=x, value=x) for x in records.REG_STATUSES],
                          insurance=[app_commands.Choice(name=x, value=x) for x in records.INS_STATUSES])
    async def vehicle(self, interaction: discord.Interaction, plate: str, make: str, model: str, color: str,
                      owner: str | None = None, registration: app_commands.Choice[str] | None = None,
                      insurance: app_commands.Choice[str] | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            data = {"plate": plate, "make": make, "model": model, "color": color,
                    "registration_status": registration.value if registration else "Valid",
                    "insurance_status": insurance.value if insurance else "Valid"}
            if owner:
                data["owner_person_id"] = (await _person(s, owner)).id
            v = await records.create_vehicle(s, actor, data)
            d = records.vehicle_dict(v)
        await ui.reply(interaction, embed=ui.success_embed(
            f"`{d['plate']}` {d['color']} {d['make']} {d['model']} — owner {d['owner_name'] or '—'}", "Vehicle registered"))

    @app_commands.command(name="search", description="Search all records you can access")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            res = await search_svc.search(s, actor, query, limit=5)
        e = ui.embed(f"Search: {query}", f"{res['total']} result(s)", footer=DISCLAIMER)
        for scope, rows in res["results"].items():
            if rows:
                e.add_field(name=scope.title(), value=ui.chunk_lines([f"**{r['title']}** — {r['summary'][:90]}" for r in rows], 1000),
                            inline=False)
        await ui.reply(interaction, embed=e)

    @app_commands.command(name="update", description="Edit a person (form) or update a vehicle's status")
    @app_commands.autocomplete(person=person_ac, vehicle=vehicle_ac)
    @app_commands.choices(registration=[app_commands.Choice(name=x, value=x) for x in records.REG_STATUSES],
                          insurance=[app_commands.Choice(name=x, value=x) for x in records.INS_STATUSES])
    async def update(self, interaction: discord.Interaction, person: str | None = None, vehicle: str | None = None,
                     registration: app_commands.Choice[str] | None = None, insurance: app_commands.Choice[str] | None = None,
                     flags: str | None = None) -> None:
        if not (person or vehicle):
            await ui.reply(interaction, embed=ui.error_embed("Choose a person or a vehicle."))
            return
        async with self.bot.ctx(interaction) as (s, actor):
            if person:
                p = await _person(s, person)
                records._check_edit(actor, p.owner_user_id)
                prefill = records.person_dict(p)
                await interaction.response.send_modal(PersonModal(self.bot, p.id, prefill))
                return
            v = await _vehicle(s, vehicle)
            data = {}
            if registration:
                data["registration_status"] = registration.value
            if insurance:
                data["insurance_status"] = insurance.value
            if flags is not None:
                data["flags"] = flags
            v = await records.update_vehicle(s, actor, v.id, data)
            d = records.vehicle_dict(v)
        await ui.reply(interaction, embed=ui.success_embed(
            f"`{d['plate']}` — reg {d['registration_status']}, ins {d['insurance_status']}, flags {', '.join(d['flags']) or 'none'}"))

    @app_commands.command(name="history", description="Change history for a person or vehicle record")
    @app_commands.autocomplete(person=person_ac, vehicle=vehicle_ac)
    async def history(self, interaction: discord.Interaction, person: str | None = None, vehicle: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.records.search")
            if person:
                obj, rtype, label = await _person(s, person), "person", person
            elif vehicle:
                obj, rtype, label = await _vehicle(s, vehicle), "vehicle", vehicle
            else:
                await ui.reply(interaction, embed=ui.error_embed("Choose a person or a vehicle."))
                return
            rows = await records.revisions(s, rtype, obj.id)
        lines = [f"{ui.ts(r['created_at'], 'f')} **{r['action']}** by {r['user']}: "
                 + ", ".join(f"{k}: {v['old']} → {v['new']}" for k, v in list(r["changes"].items())[:4])[:300] for r in rows]
        await ui.reply(interaction, embed=ui.embed(f"History — {label}", ui.chunk_lines(lines) or "No history.", footer=DISCLAIMER))


async def setup(bot) -> None:
    await bot.add_cog(RecordCog(bot))
