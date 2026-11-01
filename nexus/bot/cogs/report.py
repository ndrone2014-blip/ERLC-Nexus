"""/report — incident reports."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from nexus.bot import ui
from nexus.bot.common import any_incident_ac
from nexus.db.models import Report
from nexus.services import reports


def report_embed(d: dict) -> discord.Embed:
    color = {"approved": ui.GREEN, "returned": ui.AMBER, "submitted": ui.BLUE, "under_review": ui.BLUE}.get(d["status"], ui.GREY)
    e = ui.embed(f"{d['number']} — {d['title']}", d.get("summary") or "", color=color, fields=[
        ("Status", d["status_label"], True), ("Revision", d["revision"], True), ("Author", d.get("author") or "—", True),
        ("Incident", d.get("incident_number") or "—", True), ("Location", d.get("location") or "—", True),
        ("Reviewer", d.get("reviewer") or "—", True)], footer="Fictional ERLC roleplay record")
    if d.get("description"):
        e.add_field(name="Description", value=d["description"][:1000], inline=False)
    if d.get("comments"):
        e.add_field(name="Review comments", value="\n".join(f"**{c['user']}** ({c['action']}): {c['body'][:150]}"
                                                           for c in d["comments"][-3:]), inline=False)
    return e


class ReportModal(discord.ui.Modal, title="New incident report"):
    title_in = discord.ui.TextInput(label="Title", max_length=160)
    location = discord.ui.TextInput(label="Location", required=False, max_length=200)
    summary = discord.ui.TextInput(label="Summary", max_length=600, style=discord.TextStyle.paragraph)
    description = discord.ui.TextInput(label="Full description", max_length=4000, style=discord.TextStyle.paragraph)
    personnel = discord.ui.TextInput(label="Involved personnel", required=False, max_length=400)

    def __init__(self, bot, incident: str | None) -> None:
        super().__init__()
        self.bot, self.incident = bot, incident

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            r = await reports.create(s, actor, {"title": str(self.title_in.value), "location": str(self.location.value or ""),
                                                "summary": str(self.summary.value), "description": str(self.description.value),
                                                "involved_personnel": str(self.personnel.value or ""),
                                                "incident_id": self.incident or None})
            d = await reports.detail(s, actor, r.id)
        await ui.reply(interaction, embed=report_embed(d), content="Draft saved. Submit it with `/report submit` when ready.")


async def my_report_ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with interaction.client.rt.db.session() as s:
        from nexus.db.models import User

        uid = (await s.execute(select(User.id).where(User.discord_id == str(interaction.user.id)))).scalar()
        rows = (await s.execute(select(Report).where(Report.number.ilike(f"%{current}%"))
                                .where((Report.author_user_id == uid) | Report.status.in_(("submitted", "under_review")))
                                .order_by(Report.id.desc()).limit(25))).scalars()
        return [app_commands.Choice(name=f"{r.number} · {r.status} · {r.title[:50]}"[:100], value=r.number) for r in rows]


class ReportCog(commands.GroupCog, group_name="report", group_description="Incident reports"):
    def __init__(self, bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="create", description="Write an incident report (opens a form)")
    @app_commands.autocomplete(incident=any_incident_ac)
    async def create(self, interaction: discord.Interaction, incident: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (_, actor):
            actor.require("cad.reports.create")
        await interaction.response.send_modal(ReportModal(self.bot, incident))

    @app_commands.command(name="submit", description="Submit your draft for supervisor review")
    @app_commands.autocomplete(number=my_report_ac)
    async def submit(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            r = await reports.get(s, actor, number)
            await reports.submit(s, actor, r.id)
        await ui.reply(interaction, embed=ui.success_embed(f"{number} submitted for review."))

    @app_commands.command(name="view", description="View a report")
    @app_commands.autocomplete(number=my_report_ac)
    async def view(self, interaction: discord.Interaction, number: str) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            r = await reports.get(s, actor, number)
            d = await reports.detail(s, actor, r.id)
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Open / edit in website", url=self.bot.website(f"records/report/{d['id']}")))
        await ui.reply(interaction, embed=report_embed(d), view=v)

    @app_commands.command(name="search", description="Search reports")
    @app_commands.choices(status=[app_commands.Choice(name=v, value=k) for k, v in reports.STATUS_LABELS.items()]
                          + [app_commands.Choice(name="Awaiting review", value="awaiting_review")])
    async def search(self, interaction: discord.Interaction, query: str = "", status: app_commands.Choice[str] | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            rows = await reports.search(s, actor, q=query, status=status.value if status else "", limit=20)
        lines = [f"`{r['number']}` {r['title'][:60]} — **{r['status_label']}** · {r['author'] or '—'}" for r in rows]
        await ui.reply(interaction, embed=ui.embed("Reports", ui.chunk_lines(lines) or "No reports found."))

    @app_commands.command(name="review", description="Approve, return or comment on a submitted report")
    @app_commands.autocomplete(number=my_report_ac)
    @app_commands.choices(action=[app_commands.Choice(name="Start review", value="start"),
                                  app_commands.Choice(name="Approve", value="approve"),
                                  app_commands.Choice(name="Return for changes", value="return"),
                                  app_commands.Choice(name="Comment", value="comment"),
                                  app_commands.Choice(name="Archive", value="archive")])
    async def review(self, interaction: discord.Interaction, number: str, action: app_commands.Choice[str],
                     comment: str | None = None) -> None:
        async with self.bot.ctx(interaction) as (s, actor):
            r = await reports.get(s, actor, number)
            r = await reports.review(s, actor, r.id, action.value, comment or "")
            label = reports.STATUS_LABELS[r.status]
        await ui.reply(interaction, embed=ui.success_embed(f"{number}: {action.name} → **{label}**"))


async def setup(bot) -> None:
    await bot.add_cog(ReportCog(bot))
