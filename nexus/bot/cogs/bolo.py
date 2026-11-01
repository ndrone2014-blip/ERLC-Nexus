"""/bolo — Be On the Lookout management."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from nexus.bot import ui
from nexus.bot.panels import bolos_embed
from nexus.core.context import NotFound
from nexus.db.models import Bolo
from nexus.services import records


def bolo_embed(b: dict) -> discord.Embed:
    e = ui.embed(f"BOLO {b['number']} — {b['category'].title()}", b["reason"], color=ui.AMBER if b["is_active"] else ui.GREY, fields=[
        ("Status", b["status"].title(), True), ("Plate", b["plate"] or "—", True), ("Expires", ui.ts(b["expires_at"]), True),
        ("Subject", b["subject_description"] or "—", False), ("Vehicle", b["vehicle_description"] or "—", False),
        ("Last known location", b["last_known_location"] or "—", False)], footer="Fictional ERLC roleplay record")
    return e


class BoloModal(discord.ui.Modal):
    subject = discord.ui.TextInput(label="Subject description", required=False, max_length=400, style=discord.TextStyle.paragraph)
    vehicle = discord.ui.TextInput(label="Vehicle description", required=False, max_length=300)
    plate = discord.ui.TextInput(label="Plate", required=False, max_length=10)
    location = discord.ui.TextInput(label="Last known location", required=False, max_length=200)
    reason = discord.ui.TextInput(label="Reason", max_length=1000, style=discord.TextStyle.paragraph)

    def __init__(self, bot, category: str) -> None:
        super().__init__(title=f"New {category} BOLO")
        self.bot, self.category = bot, category

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            b = await records.create_bolo(s, actor, {
                "category": self.category, "subject_description": str(self.subject.value or ""),
                "vehicle_description": str(self.vehicle.value or ""), "plate": str(self.plate.value or ""),
                "last_known_location": str(self.location.value or ""), "reason": str(self.reason.value)})
            d = records.bolo_dict(b)
        await ui.reply(interaction, embed=bolo_embed(d), ephemeral=False)


async def _find(s, number: str) -> Bolo:
    b = (await s.execute(select(Bolo).where(Bolo.number == number.upper().strip()))).scalar_one_or_none()
    if b is None:
        raise NotFound(f"BOLO {number} not found.")
    return b


async def bolo_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with interaction.client.rt.db.session() as s:
        rows = (await s.execute(select(Bolo).where(Bolo.status.in_(("active", "updated")), Bolo.number.ilike(f"%{current}%"))
                                .order_by(Bolo.id.desc()).limit(25))).scalars()
        return [app_commands.Choice(name=f"{b.number} · {b.category} · {b.reason[:50]}"[:100], value=b.number) for b in rows]


class BoloCog(commands.GroupCog, group_name="bolo", group_description="BOLOs"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="create", description="Issue a BOLO (opens a form)")
    @app_commands.choices(category=[app_commands.Choice(name="Person", value="person"),
                                    app_commands.Choice(name="Vehicle", value="vehicle"),
                                    app_commands.Choice(name="General", value="general")])
    async def create(self, interaction: discord.Interaction, category: app_commands.Choice[str]) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("cad.bolo.manage")
        await interaction.response.send_modal(BoloModal(self.bot, category.value))

    @app_commands.command(name="search", description="Search BOLOs (all statuses)")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            rows = await records.list_bolos(s, actor, status="all", q=query, limit=15)
        lines = [f"`{b['number']}` {b['status']} · **{b['category']}** {b['plate'] or ''} — {b['reason'][:80]}" for b in rows]
        await ui.reply(interaction, embed=ui.embed(f"BOLOs matching '{query}'", ui.chunk_lines(lines) or "None."))

    @app_commands.command(name="update", description="Update a BOLO's location or details")
    @app_commands.autocomplete(number=bolo_ac)
    async def update(self, interaction: discord.Interaction, number: str, last_known_location: str | None = None,
                     details: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            b = await _find(s, number)
            data = {}
            if last_known_location:
                data["last_known_location"] = last_known_location
            if details:
                data["reason"] = f"{b.reason}\n[Update] {details}"
            b = await records.update_bolo(s, actor, b.id, data)
            d = records.bolo_dict(b)
        await ui.reply(interaction, embed=bolo_embed(d), ephemeral=False)

    @app_commands.command(name="close", description="Resolve or cancel a BOLO")
    @app_commands.autocomplete(number=bolo_ac)
    @app_commands.choices(outcome=[app_commands.Choice(name="Resolved", value="resolved"),
                                   app_commands.Choice(name="Cancelled", value="cancelled")])
    async def close(self, interaction: discord.Interaction, number: str, outcome: app_commands.Choice[str]) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            b = await _find(s, number)
            await records.update_bolo(s, actor, b.id, {"status": outcome.value})
        await ui.reply(interaction, embed=ui.success_embed(f"BOLO {number} {outcome.value}."))

    @app_commands.command(name="list", description="Active BOLOs")
    async def list_bolos(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            actor.require("cad.records.search")
            emb = await bolos_embed(s, await self.bot.embed_color())
        await ui.reply(interaction, embed=emb)


async def setup(bot) -> None:
    await bot.add_cog(BoloCog(bot))
