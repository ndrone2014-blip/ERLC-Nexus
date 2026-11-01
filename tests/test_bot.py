"""Discord bot: command registration, payload validity, permissions, interactions, notifier."""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest
from discord import app_commands
from sqlalchemy import select

from nexus.bot import ui
from nexus.bot.core import COGS, NexusBot
from nexus.db.models import Incident, Role

pytestmark = pytest.mark.anyio

EXPECTED = {
    "server": {"panel", "info", "status", "players", "player", "refresh", "command", "announcement"},
    "player": {"panel", "search", "info", "ban", "kick", "unban", "history"},
    "cad": {"panel", "911", "incident", "incidents", "close", "reopen", "assign", "history"},
    "unit": {"panel", "register", "status", "assign", "remove", "list", "history"},
    "dispatch": {"panel", "create", "assign", "update", "close", "queue"},
    "mdt": {"panel", "person", "vehicle", "bolo", "traffic-stop", "report"},
    "department": {"panel", "info", "roster", "stats", "ranks"},
    "shift": {"start", "end", "status", "history", "stats"},
    "bolo": {"create", "search", "update", "close", "list"},
    "record": {"person", "vehicle", "search", "update", "history"},
    "report": {"create", "submit", "view", "search", "review"},
    "nexus": {"help", "status", "dashboard", "link-roblox", "panel"},
}


@pytest.fixture
async def bot(rt):
    b = NexusBot(rt, run_sync=False)
    for ext in COGS:
        await b.load_extension(ext)
    b._connection.user = SimpleNamespace(id=1, name="Nexus")  # minimal identity, no gateway login
    yield b


async def test_all_command_groups_register(bot):
    groups = {c.name: {s.name for s in c.commands} for c in bot.tree.get_commands() if isinstance(c, app_commands.Group)}
    assert groups == EXPECTED
    menus = {c.name for c in bot.tree.get_commands(type=discord.AppCommandType.user)} | \
            {c.name for c in bot.tree.get_commands(type=discord.AppCommandType.message)}
    assert menus == {"Nexus profile", "Create CAD incident"}
    total = sum(len(v) for v in groups.values())
    assert total == 72  # + 2 context menus = 74 commands


async def test_command_payloads_are_valid_for_discord(bot):
    payload = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
    assert len(payload) <= 100
    for group in payload:
        for sub in group.get("options", []):
            assert 1 <= len(sub["description"]) <= 100, sub["name"]
            seen_optional = False
            for opt in sub.get("options", []):
                if not opt.get("required", False):
                    seen_optional = True
                assert not (seen_optional and opt.get("required")), f"{group['name']} {sub['name']}: required after optional"


class FakeResponse:
    def __init__(self):
        self.sent = []
        self._done = False
        self.modal = None

    def is_done(self):
        return self._done

    async def send_message(self, **kw):
        self.sent.append(kw)
        self._done = True

    async def defer(self, **kw):
        self._done = True

    async def send_modal(self, modal):
        self.modal = modal
        self._done = True

    async def edit_message(self, **kw):
        self.sent.append(kw)
        self._done = True


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, **kw):
        self.sent.append(kw)
        return SimpleNamespace(id=1)


def fake_interaction(bot, user_id=100000000000000001, roles=()):
    guild = SimpleNamespace(id=999)
    user = SimpleNamespace(id=user_id, name="tester", display_name="Tester", roles=[SimpleNamespace(id=r) for r in roles],
                           guild=guild, display_avatar=None)
    resp, follow = FakeResponse(), FakeFollowup()
    inter = SimpleNamespace(user=user, client=bot, response=resp, followup=follow, guild=guild, channel=None, data={})

    async def original_response():
        return SimpleNamespace(id=2, edit=lambda **k: None)

    inter.original_response = original_response
    return inter


def make_member(monkeypatch):
    monkeypatch.setattr(discord, "Member", SimpleNamespace)  # treat our fake user as a guild member


async def test_ctx_resolves_permissions_from_discord_roles(bot, rt, admin, monkeypatch):
    make_member(monkeypatch)
    async with rt.db.session() as s:
        disp = (await s.execute(select(Role).where(Role.key == "dispatcher"))).scalar_one()
        disp.discord_role_ids = ["4242"]
        await s.commit()
    inter = fake_interaction(bot, 920000000000000001, roles=[4242])
    async with bot.ctx(inter) as (_, actor):
        assert actor.can("cad.dispatch") and not actor.can("system.configure")
    inter2 = fake_interaction(bot, 920000000000000002, roles=[])
    async with bot.ctx(inter2) as (_, actor):
        assert not actor.can("cad.view")


async def test_911_modal_creates_incident(bot, rt, monkeypatch):
    make_member(monkeypatch)
    from nexus.bot.cogs.cad import Call911Modal

    async with rt.db.session() as s:
        civ = (await s.execute(select(Role).where(Role.key == "civilian"))).scalar_one()
        civ.discord_role_ids = ["11"]
        await s.commit()
    modal = Call911Modal(bot)
    modal.location._value = "Bank on Main"
    modal.description._value = "Robbery in progress"
    modal.caller._value = "Jane"
    modal.contact._value = ""
    inter = fake_interaction(bot, 930000000000000001, roles=[11])
    await modal.on_submit(inter)
    async with rt.db.session() as s:
        inc = (await s.execute(select(Incident))).scalar_one()
        assert inc.status == "pending" and inc.source == "discord" and inc.caller_name == "Jane"
    assert "911 call placed" in inter.response.sent[0]["embed"].title


async def test_command_permission_denied_message(bot, monkeypatch):
    make_member(monkeypatch)
    cog = bot.get_cog("ServerCog")
    inter = fake_interaction(bot, 940000000000000001, roles=[])
    with pytest.raises(Exception) as e:
        await cog.command.callback(cog, inter, ":h hi")
    assert "permission" in ui.friendly_error(e.value).lower()


async def test_shift_commands(bot, rt, admin, monkeypatch):
    make_member(monkeypatch)
    cog = bot.get_cog("ShiftCog")
    inter = fake_interaction(bot)  # the initial admin (Owner)
    await cog.start.callback(cog, inter, None, "1A-01", None)
    assert "Shift started" in inter.response.sent[0]["embed"].title
    inter = fake_interaction(bot)
    await cog.end.callback(cog, inter, "done")
    assert "Shift ended" in inter.response.sent[0]["embed"].title


async def test_owned_view_blocks_other_users(bot):
    view = ui.OwnedView(owner_id=1)
    other = fake_interaction(bot, user_id=2)
    assert await view.interaction_check(other) is False
    assert "someone else" in other.response.sent[0]["embed"].description
    assert await view.interaction_check(fake_interaction(bot, user_id=1)) is True


async def test_owned_view_disables_on_timeout():
    view = ui.OwnedView(owner_id=1)
    btn = discord.ui.Button(label="x")
    view.add_item(btn)
    edits = []

    class Msg:
        async def edit(self, **kw):
            edits.append(kw)

    view.message = Msg()
    await view.on_timeout()
    assert btn.disabled and edits


async def test_error_messages_are_user_safe():
    from nexus.core.context import NotFound
    from nexus.erlc.client import ErlcError

    assert ui.friendly_error(NotFound("Incident X not found.")) == "Incident X not found."
    assert ui.friendly_error(ErlcError("offline", "Server offline")).startswith("ERLC API")
    assert "logged" in ui.friendly_error(RuntimeError("secret internal stack"))


async def test_notifier_builds_embeds_for_every_direct_event(bot):
    from nexus.bot.notifier import DIRECT, Notifier

    n = Notifier.__new__(Notifier)
    n.bot = bot
    sample = {"id": 1, "number": "NX-1", "priority": 1, "category": "crime", "location": "Bank", "description": "d",
              "callsign": "1A-01", "plate": "ABC", "reason": "r", "title": "t", "author": "a", "user": "u", "duration": "1h",
              "team": "Police", "call_number": 4, "status": "closed", "disposition": "done"}
    for kind in DIRECT:
        emb = n._event_embed(kind, sample, 0x3B82F6)
        assert isinstance(emb, discord.Embed) and emb.title, kind


async def test_panels_render(bot, rt):
    from nexus.bot.panels import PANEL_KINDS, render_panel
    from nexus.erlc.sync import SyncService

    await SyncService(rt).run_cycle()
    for kind in PANEL_KINDS:
        emb = await render_panel(bot, kind)
        assert isinstance(emb, discord.Embed) and emb.title
