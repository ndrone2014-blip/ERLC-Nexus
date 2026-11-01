"""Shared Discord UI helpers: embeds, owner-locked views, error formatting."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import discord

from nexus.core.context import NexusError
from nexus.erlc.client import ErlcError

log = logging.getLogger("nexus.bot.ui")

BLUE = 0x3B82F6
GREEN = 0x22C55E
RED = 0xEF4444
AMBER = 0xF59E0B
GREY = 0x64748B
FOOTER = "ERLC Nexus"


def hex_color(value: str | None, default: int = BLUE) -> int:
    try:
        return int((value or "").lstrip("#"), 16)
    except ValueError:
        return default


def embed(title: str, description: str = "", *, color: int = BLUE, fields: list[tuple[str, Any, bool]] | None = None,
          footer: str | None = None, url: str | None = None, timestamp: bool = True) -> discord.Embed:
    e = discord.Embed(title=title[:256], description=(description or "")[:4000], color=color, url=url)
    for name, value, inline in fields or []:
        text = str(value) if value not in (None, "") else "—"
        e.add_field(name=str(name)[:256], value=text[:1024], inline=inline)
    e.set_footer(text=footer or FOOTER)
    if timestamp:
        e.timestamp = discord.utils.utcnow()
    return e


def ts(dt: datetime | None, style: str = "R") -> str:
    return discord.utils.format_dt(dt, style) if dt else "—"


def error_embed(message: str, title: str = "Can't do that") -> discord.Embed:
    return embed(title, message, color=RED, timestamp=False)


def success_embed(message: str, title: str = "Done") -> discord.Embed:
    return embed(title, message, color=GREEN, timestamp=False)


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, NexusError):
        return exc.message
    if isinstance(exc, ErlcError):
        return f"ERLC API: {exc.message}"
    if isinstance(exc, discord.Forbidden):
        return "I'm missing Discord permissions in this channel (Send Messages / Embed Links)."
    return "Something went wrong. The error has been logged for the administrators."


async def reply(interaction: discord.Interaction, *, embed: discord.Embed | None = None, content: str | None = None,
                view: discord.ui.View | None = None, ephemeral: bool = True) -> None:
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}
    if embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        msg = await interaction.followup.send(wait=True, **kwargs)
    else:
        await interaction.response.send_message(**kwargs)
        msg = await interaction.original_response()
    if isinstance(view, OwnedView):
        view.message = msg


class OwnedView(discord.ui.View):
    """A view only its creator can use. Components are disabled when it expires."""

    def __init__(self, owner_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: discord.Message | discord.InteractionMessage | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error_embed("These buttons belong to someone else. Run the command yourself."), ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)) and not getattr(child, "url", None):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        if not isinstance(error, (NexusError, ErlcError)):
            log.exception("View error", exc_info=error)
        await reply(interaction, embed=error_embed(friendly_error(error)))


class ConfirmView(OwnedView):
    def __init__(self, owner_id: int, *, confirm_label: str = "Confirm", danger: bool = True) -> None:
        super().__init__(owner_id, timeout=60)
        self.value: bool | None = None
        self.confirm.label = confirm_label
        self.confirm.style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = False
        await interaction.response.defer()
        self.stop()


def chunk_lines(lines: list[str], limit: int = 3800) -> str:
    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > limit:
            out.append(f"…and {len(lines) - len(out)} more")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)
