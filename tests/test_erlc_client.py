"""Official ERLC API client: auth, parsing, rate limits, retries, error handling, secrecy."""

from __future__ import annotations

import logging

import httpx
import pytest

from nexus.erlc.client import COMMAND_SPACING, ErlcClient, ErlcError
from nexus.logging_setup import RedactingFilter, register_secret
from tests.conftest import SERVER_KEY, FakeErlc

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(s)
        self.t += s


def client(fake: FakeErlc, clock: Clock | None = None, **kw) -> ErlcClient:
    clock = clock or Clock()
    return ErlcClient(SERVER_KEY, transport=fake.transport, clock=clock.now, sleep=clock.sleep, **kw)


async def test_server_info_parsing_and_headers():
    fake = FakeErlc()
    c = client(fake)
    snap = await c.get_server()
    req = fake.requests[0]
    assert req.url.host == "api.erlc.gg" and req.url.path == "/v2/server"
    assert req.headers["server-key"] == SERVER_KEY
    assert "Authorization" not in req.headers  # no global key configured
    assert set(req.url.params) == {"Players", "Staff", "JoinLogs", "Queue", "KillLogs", "CommandLogs", "ModCalls",
                                   "EmergencyCalls", "Vehicles"}
    assert snap.name == "Test RP" and snap.current_players == 2
    bob = snap.players[0]
    assert (bob.name, bob.id, bob.team, bob.callsign) == ("Bob", "123", "Police", "1A-01")
    assert bob.location.street == "Main St" and bob.location.x == 10.5
    assert snap.players[1].location is None
    assert snap.team_counts() == {"Police": 1, "Civilian": 1}
    assert snap.emergency_calls[0].call_number == 4
    assert snap.vehicles[0].plate == "ABC123"
    assert snap.staff.mods == {"789": "Sam"}


async def test_flags_are_deduplicated_and_validated():
    fake = FakeErlc()
    c = client(fake)
    await c.get_server(flags=("Players", "Players", "Bogus"))
    assert list(fake.requests[0].url.params.keys()) == ["Players"]


async def test_global_key_sent_as_authorization():
    fake = FakeErlc()
    c = client(fake, global_key="GLOBAL")
    await c.get_server(flags=())
    assert fake.requests[0].headers["Authorization"] == "GLOBAL"


async def test_cache_avoids_repeat_requests():
    fake = FakeErlc()
    clock = Clock()
    c = client(fake, clock, cache_ttl=15)
    await c.get_server()
    await c.get_server()
    assert len(fake.requests) == 1
    clock.t += 16
    await c.get_server()
    assert len(fake.requests) == 2


async def test_invalid_key_marks_and_stops_all_requests():
    fake = FakeErlc()
    c = ErlcClient("wrong-key", transport=fake.transport)
    with pytest.raises(ErlcError) as e:
        await c.get_server(use_cache=False)
    assert e.value.kind == "auth" and e.value.api_code == 2002
    assert c.key_invalid
    n = len(fake.requests)
    for _ in range(3):
        with pytest.raises(ErlcError):
            await c.get_server(use_cache=False)
    assert len(fake.requests) == n, "must never keep retrying a rejected key"


async def test_403_without_body_is_auth_error():
    fake = FakeErlc()
    fake.responses.append(httpx.Response(403))
    c = client(fake)
    with pytest.raises(ErlcError) as e:
        await c.get_server()
    assert e.value.kind == "auth" and c.key_invalid
    assert len(fake.requests) == 1


async def test_key_change_resets_invalid_state():
    fake = FakeErlc()
    key = {"v": "wrong"}
    c = ErlcClient(lambda: key["v"], transport=fake.transport)
    with pytest.raises(ErlcError):
        await c.get_server()
    assert c.key_invalid
    key["v"] = SERVER_KEY
    assert not c.key_invalid
    assert (await c.get_server(use_cache=False)).name == "Test RP"


async def test_rate_limit_honours_retry_after_for_bucket():
    fake = FakeErlc()
    clock = Clock()
    fake.responses.append(httpx.Response(429, headers={"Retry-After": "7", "X-RateLimit-Bucket": "global"},
                                         json={"code": 4001, "retry_after": 7}))
    c = client(fake, clock, max_retries=0)
    with pytest.raises(ErlcError) as e:
        await c.get_server()
    assert e.value.kind == "rate_limited" and e.value.retry_after == 7
    assert c.stats.buckets["global"].blocked_until == pytest.approx(clock.t + 7)
    # next call waits out the bucket before sending
    snap = await c.get_server(use_cache=False)
    assert snap.name == "Test RP"
    assert any(s >= 6.9 for s in clock.slept)


async def test_long_rate_limit_is_not_waited_inline():
    fake = FakeErlc()
    fake.responses.append(httpx.Response(429, headers={"Retry-After": "120", "X-RateLimit-Bucket": "global"}, json={}))
    c = client(fake, max_retries=0)
    with pytest.raises(ErlcError):
        await c.get_server()
    n = len(fake.requests)
    with pytest.raises(ErlcError) as e:
        await c.get_server(use_cache=False)
    assert e.value.kind == "rate_limited" and len(fake.requests) == n


async def test_transient_errors_retry_with_backoff():
    fake = FakeErlc()
    clock = Clock()
    fake.responses += [httpx.Response(500, json={"error": "roblox", "code": 1001}),
                       httpx.Response(500, json={"error": "roblox", "code": 1001})]
    c = client(fake, clock, max_retries=2)
    snap = await c.get_server()
    assert snap.name == "Test RP" and len(fake.requests) == 3
    assert clock.slept[:2] == [1.0, 2.0]


async def test_bad_request_is_never_retried():
    fake = FakeErlc()
    fake.responses.append(httpx.Response(400, json={"code": 2001, "message": "malformed"}))
    c = client(fake, max_retries=3)
    with pytest.raises(ErlcError):
        await c.get_server()
    assert len(fake.requests) == 1


async def test_network_error_and_timeout():
    def boom(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    clock = Clock()
    c = ErlcClient(SERVER_KEY, transport=httpx.MockTransport(boom), clock=clock.now, sleep=clock.sleep, max_retries=1)
    with pytest.raises(ErlcError) as e:
        await c.get_server()
    assert e.value.kind == "network"
    assert c.stats.failures == 1


async def test_invalid_response_shape():
    fake = FakeErlc()
    fake.responses.append(httpx.Response(200, json={"unexpected": True}))
    c = client(fake)
    with pytest.raises(ErlcError) as e:
        await c.get_server()
    assert e.value.kind == "invalid_response"


async def test_documented_error_codes_map_to_kinds():
    cases = {422: ("offline", None), 9999: ("outdated_module", 400), 4002: ("restricted", 400), 4000: ("forbidden", 400),
             2005: ("forbidden", 403), 3001: ("bad_request", 400)}
    for code, (kind, status) in cases.items():
        fake = FakeErlc()
        if code == 422:
            fake.responses.append(httpx.Response(422, json={"message": "offline", "commandId": "x"}))
        else:
            fake.responses.append(httpx.Response(status, json={"code": code, "message": "m"}))
        c = client(fake, max_retries=0)
        with pytest.raises(ErlcError) as e:
            await c.get_server()
        assert e.value.kind == kind, code


async def test_commands_are_validated_and_spaced():
    fake = FakeErlc()
    clock = Clock()
    c = client(fake, clock)
    await c.run_command(":h one")
    await c.run_command(":h two")
    assert fake.commands == [":h one", ":h two"]
    assert any(s >= COMMAND_SPACING - 0.01 for s in clock.slept), "second command must wait for the 5s command bucket"
    for bad in ["", "h no colon", ":h line\nbreak", ":" + "x" * 400]:
        with pytest.raises(ErlcError):
            ErlcClient.validate_command(bad)
    with pytest.raises(ErlcError) as e:
        ErlcClient.validate_command(":pm someone hi", blocked=[":pm"])
    assert e.value.kind == "restricted"


async def test_bans_parsing():
    fake = FakeErlc()
    c = client(fake)
    assert await c.get_bans() == [{"id": "555", "name": "Griefer"}]
    assert fake.requests[-1].url.path == "/v1/server/bans"


async def test_not_configured():
    c = ErlcClient("", transport=FakeErlc().transport)
    assert not c.configured
    with pytest.raises(ErlcError) as e:
        await c.get_server()
    assert e.value.kind == "not_configured"


async def test_status_never_contains_key():
    fake = FakeErlc()
    c = client(fake)
    await c.get_server()
    assert SERVER_KEY not in repr(c.status())


def test_logs_redact_secrets():
    register_secret(SERVER_KEY)
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "sending server-key: %s and token=abc123def", (SERVER_KEY,), None)
    RedactingFilter().filter(rec)
    assert SERVER_KEY not in rec.getMessage()
    assert "abc123def" not in rec.getMessage()
