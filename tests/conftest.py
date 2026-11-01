"""Shared fixtures: isolated database per test, mocked official ERLC API, signed-in clients."""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nexus.config import load_settings
from nexus.core.context import Actor
from nexus.core.settings_store import invalidate_cache
from nexus.runtime import Runtime

SERVER_KEY = "test-server-key-0123456789"
ADMIN_ID = "100000000000000001"

# Response shaped exactly like the documented GET /v2/server payload (apidocs.erlc.gg).
SERVER_PAYLOAD: dict[str, Any] = {
    "Name": "Test RP", "OwnerId": 1, "CoOwnerIds": [2], "CurrentPlayers": 2, "MaxPlayers": 40, "JoinKey": "TEST",
    "AccVerifiedReq": "Disabled", "TeamBalance": True,
    "Players": [
        {"Player": "Bob:123", "Team": "Police", "Callsign": "1A-01", "Permission": "Normal", "WantedStars": 0,
         "Location": {"LocationX": 10.5, "LocationZ": -4.0, "PostalCode": "201", "StreetName": "Main St", "BuildingNumber": "5"}},
        {"Player": "Amy:456", "Team": "Civilian", "Callsign": None, "Permission": "Normal", "WantedStars": 2},
    ],
    "Staff": {"Admins": {"1": "Owner"}, "Mods": {"789": "Sam"}, "Helpers": {}},
    "JoinLogs": [{"Join": True, "Timestamp": 1700000000, "Player": "Bob:123"}],
    "Queue": [999],
    "KillLogs": [{"Killed": "Amy:456", "Killer": "Bob:123", "Timestamp": 1700000100}],
    "CommandLogs": [{"Player": "Bob:123", "Command": ":h hi", "Timestamp": 1700000200}],
    "ModCalls": [{"Caller": "Amy:456", "Moderator": None, "Timestamp": 1700000300}],
    "EmergencyCalls": [{"Team": "Police", "Caller": 456, "Players": [], "Position": [1.0, 2.0], "StartedAt": 1900000000,
                        "CallNumber": 4, "Description": "Robbery at the bank", "PositionDescriptor": "Main St"}],
    "Vehicles": [{"Name": "Falcon Stallion", "Owner": "Amy", "Plate": "ABC123", "Texture": None, "ColorHex": "ff0000", "ColorName": "Red"}],
}


class FakeErlc:
    """Programmable stand-in for api.erlc.gg used through httpx.MockTransport."""

    def __init__(self) -> None:
        self.payload = copy.deepcopy(SERVER_PAYLOAD)
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []  # queued overrides
        self.commands: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        if request.headers.get("server-key") != SERVER_KEY:
            return httpx.Response(403, json={"code": 2002, "message": "Invalid server key"})
        if request.url.path == "/v2/server":
            flags = set(request.url.params.keys())
            body = {k: v for k, v in self.payload.items() if k not in
                    ("Players", "Staff", "JoinLogs", "Queue", "KillLogs", "CommandLogs", "ModCalls", "EmergencyCalls", "Vehicles") or k in flags}
            return httpx.Response(200, json=body, headers={"X-RateLimit-Bucket": "global", "X-RateLimit-Limit": "35",
                                                          "X-RateLimit-Remaining": "34", "X-RateLimit-Reset": "0"})
        if request.url.path == "/v2/server/command":
            import json

            self.commands.append(json.loads(request.content)["command"])
            return httpx.Response(200, json={"message": "Success"}, headers={"X-RateLimit-Bucket": "command"})
        if request.url.path == "/v1/server/bans":
            return httpx.Response(200, json={"555": "Griefer"})
        return httpx.Response(404, json={"message": "not found"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def fake_erlc() -> FakeErlc:
    return FakeErlc()


@pytest.fixture
def settings(tmp_path):
    invalidate_cache()
    return load_settings(env_file=tmp_path / "none.env", overrides=dict(
        data_dir=str(tmp_path / "data"), secret_key="s" * 48, dev_login=True, initial_admin_discord_id=ADMIN_ID,
        erlc_server_key=SERVER_KEY, discord_application_id="1234", discord_client_secret="secret", discord_guild_id="999"))


@pytest.fixture
async def rt(settings, fake_erlc):
    runtime = Runtime(settings, erlc_transport=fake_erlc.transport)
    # instant sleeps so rate-limit/back-off tests don't wait
    async def _no_sleep(_s):
        return None
    runtime.erlc._sleep = _no_sleep
    await runtime.startup()
    yield runtime
    await runtime.shutdown()
    invalidate_cache()


@pytest.fixture
async def admin(rt) -> Actor:
    from sqlalchemy import select

    from nexus.db.models import User
    from nexus.services.users import resolve_actor

    async with rt.db.session() as s:
        user = (await s.execute(select(User).where(User.discord_id == ADMIN_ID))).scalar_one()
        return await resolve_actor(s, user)


async def make_actor(rt, discord_id: str, role_keys: list[str], name: str = "Tester") -> Actor:
    """Create a user with the given built-in roles and return its resolved Actor."""
    from sqlalchemy import select

    from nexus.db.models import Role, UserRole
    from nexus.services.users import get_or_create_user, resolve_actor

    async with rt.db.session() as s:
        user = await get_or_create_user(s, discord_id, username=name, display_name=name)
        for key in role_keys:
            role = (await s.execute(select(Role).where(Role.key == key))).scalar_one()
            s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()
        return await resolve_actor(s, user)


@pytest.fixture
def make_user(rt):
    async def _make(discord_id: str, roles: list[str], name: str = "Tester") -> Actor:
        return await make_actor(rt, discord_id, roles, name)
    return _make


@pytest.fixture
def web(settings, fake_erlc):
    """A started website app with a signed-in owner (via DEV_LOGIN) and CSRF header helper."""
    from nexus.api.app import create_app

    runtime = Runtime(settings, erlc_transport=fake_erlc.transport)

    async def _no_sleep(_s):
        return None

    runtime.erlc._sleep = _no_sleep
    app = create_app(runtime, start_background=False)
    with TestClient(app) as client:
        from nexus.erlc.sync import SyncService

        app.state.sync = SyncService(runtime)
        r = client.post("/auth/dev-login", follow_redirects=False)
        assert r.status_code == 303
        me = client.get("/api/me").json()
        client.headers["X-CSRF-Token"] = me["csrf_token"]
        client.app_runtime = runtime
        yield client
    invalidate_cache()


def login_as(client: TestClient, discord_id: str) -> None:
    """Swap the test client's session to another user (creates a session directly)."""
    from datetime import timedelta

    from sqlalchemy import select

    from nexus.core.crypto import hash_token, new_token
    from nexus.db.base import utcnow
    from nexus.db.models import User, WebSession

    rt = client.app.state.runtime
    token, csrf = new_token(), new_token(12)

    async def _mk():
        async with rt.db.session() as s:
            user = (await s.execute(select(User).where(User.discord_id == discord_id))).scalar_one()
            s.add(WebSession(token_hash=hash_token(token), user_id=user.id, csrf_token=csrf, expires_at=utcnow() + timedelta(hours=1)))
            await s.commit()

    client.portal.call(_mk)
    client.cookies.set("nx_session", token)
    client.headers["X-CSRF-Token"] = csrf
