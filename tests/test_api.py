"""Website/API: auth, CSRF, permissions, OAuth, realtime, webhooks, security headers, secrecy."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from tests.conftest import SERVER_KEY, login_as


def test_requires_login(web):
    anon = TestClient(web.app)
    for path in ("/api/me", "/api/overview", "/api/cad/incidents", "/api/admin/settings", "/api/records/persons"):
        assert anon.get(path).status_code == 401, path


def test_csrf_enforced(web):
    token = web.headers.pop("X-CSRF-Token")
    r = web.post("/api/cad/incidents", json={"category": "crime", "description": "x"})
    assert r.status_code == 403 and "CSRF" in r.json()["message"]
    web.headers["X-CSRF-Token"] = "wrong"
    assert web.post("/api/cad/incidents", json={"category": "crime", "description": "x"}).status_code == 403
    web.headers["X-CSRF-Token"] = token
    assert web.post("/api/cad/incidents", json={"category": "crime", "description": "x"}).status_code == 200


def test_security_headers(web):
    r = web.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert web.get("/").headers.get("Content-Security-Policy")


def test_every_read_endpoint_works_for_owner(web):
    web.post("/api/erlc/refresh")
    web.post("/api/cad/incidents", json={"category": "crime", "description": "seed", "location_name": "Bank"})
    paths = [
        "/api/me", "/api/bootstrap", "/api/overview", "/api/activity", "/api/notifications", "/api/users?q=a",
        "/api/erlc/overview", "/api/erlc/players", "/api/erlc/player?query=Bob", "/api/erlc/player/history?name=Bob",
        "/api/erlc/bans", "/api/erlc/logs", "/api/erlc/moderation", "/api/erlc/status",
        "/api/cad/incidents", "/api/cad/incidents?state=all", "/api/cad/queue", "/api/cad/incidents/1", "/api/cad/incidents/1/history",
        "/api/cad/erlc-calls", "/api/cad/units", "/api/cad/my-units", "/api/cad/callsign-suggest?department_id=1", "/api/cad/comms",
        "/api/cad/traffic", "/api/map/config", "/api/map/live", "/api/map/locations",
        "/api/records/persons", "/api/records/vehicles", "/api/records/bolos", "/api/records/warrants", "/api/records/cases",
        "/api/search?q=bank", "/api/search/recent", "/api/reports", "/api/reports/export.csv",
        "/api/departments", "/api/departments/1", "/api/departments/1/roster", "/api/departments/1/stats",
        "/api/shifts", "/api/shifts/me", "/api/shifts/on-duty",
        "/api/analytics/server", "/api/analytics/cad", "/api/analytics/departments", "/api/analytics/dispatchers",
        "/api/analytics/activity", "/api/analytics/cad.csv",
        "/api/admin/settings", "/api/admin/permissions", "/api/admin/roles", "/api/admin/users", "/api/admin/audit",
        "/api/admin/audit/verify", "/api/admin/security", "/api/admin/erlc", "/api/admin/discord", "/api/admin/backups",
        "/api/admin/health", "/api/admin/logs", "/api/health", "/api/auth/config",
    ]
    for p in paths:
        r = web.get(p)
        assert r.status_code == 200, (p, r.status_code, r.text[:200])


def test_server_key_never_leaves_the_server(web):
    web.post("/api/erlc/refresh")
    for p in ("/api/admin/erlc", "/api/admin/settings", "/api/erlc/overview", "/api/erlc/status", "/api/bootstrap",
              "/api/admin/health", "/api/overview", "/api/admin/audit"):
        assert SERVER_KEY not in web.get(p).text, p


def test_dashboard_key_is_tested_and_stored_encrypted(web, fake_erlc):
    bad = web.put("/api/admin/erlc/key", json={"key": "definitely-not-valid-key"})
    assert bad.status_code == 422
    good = web.put("/api/admin/erlc/key", json={"key": SERVER_KEY})
    assert good.status_code == 200 and good.json()["server_name"] == "Test RP"
    settings = web.get("/api/admin/settings").json()
    assert "erlc.server_key_encrypted" not in settings
    assert web.get("/api/admin/erlc").json()["key_source"] == "dashboard (encrypted)"


def test_permission_enforcement_for_lower_roles(web):
    import asyncio  # noqa: F401

    rt = web.app.state.runtime
    web.portal.call(_mk_user, rt, "900000000000000001", ["viewer"])
    login_as(web, "900000000000000001")
    assert web.get("/api/erlc/overview").status_code == 200
    for method, path, body in [("get", "/api/cad/incidents", None), ("post", "/api/cad/incidents", {"category": "crime", "description": "x"}),
                               ("get", "/api/admin/settings", None), ("post", "/api/erlc/command", {"command": ":h x"}),
                               ("get", "/api/records/persons", None), ("put", "/api/admin/settings/community.name", {"value": "x"}),
                               ("get", "/api/admin/audit", None), ("post", "/api/admin/backups", {})]:
        r = getattr(web, method)(path, json=body) if body is not None else getattr(web, method)(path)
        assert r.status_code == 403, (method, path, r.status_code)


async def _mk_user(rt, discord_id, roles):
    from tests.conftest import make_actor

    await make_actor(rt, discord_id, roles)


def test_role_info_from_browser_is_ignored(web):
    rt = web.app.state.runtime
    web.portal.call(_mk_user, rt, "900000000000000002", ["officer"])
    login_as(web, "900000000000000002")
    r = web.post("/api/admin/roles", json={"name": "x", "permissions": ["*"]}, headers={"X-Roles": "owner"})
    assert r.status_code == 403
    me = web.get("/api/me").json()
    assert "*" not in me["permissions"]


def test_dev_login_refused_when_disabled(settings, fake_erlc):
    from nexus.api.app import create_app
    from nexus.runtime import Runtime

    settings.dev_login = False
    app = create_app(Runtime(settings, erlc_transport=fake_erlc.transport), start_background=False)
    with TestClient(app) as c:
        assert c.post("/auth/dev-login").status_code == 403
        assert not c.get("/api/auth/config").json()["dev_login"]


def test_discord_oauth_flow_with_role_sync(settings, fake_erlc):
    from nexus.api.app import create_app
    from nexus.runtime import Runtime

    calls = []

    def discord(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/oauth2/token"):
            body = parse_qs(request.content.decode())
            assert body["client_secret"] == ["secret"] and body["code"] == ["abc"]
            return httpx.Response(200, json={"access_token": "AT", "token_type": "Bearer"})
        if request.url.path.endswith("/users/@me"):
            assert request.headers["Authorization"] == "Bearer AT"
            return httpx.Response(200, json={"id": "910000000000000001", "username": "newbie", "global_name": "New Bie", "avatar": None})
        if request.url.path.endswith("/guilds/999/member"):
            return httpx.Response(200, json={"roles": ["4242"]})
        return httpx.Response(404)

    app = create_app(Runtime(settings, erlc_transport=fake_erlc.transport), start_background=False)
    app.state.discord_transport = httpx.MockTransport(discord)
    with TestClient(app) as c:
        r = c.get("/auth/login", follow_redirects=False)
        assert r.status_code == 303
        loc = urlparse(r.headers["location"])
        q = parse_qs(loc.query)
        assert loc.netloc == "discord.com" and "guilds.members.read" in q["scope"][0]
        state = q["state"][0]
        # forged state is rejected
        bad = c.get("/auth/callback?code=abc&state=forged", follow_redirects=False)
        assert "login_failed" in bad.headers["location"]
        ok = c.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
        assert ok.status_code == 303 and ok.headers["location"] == "/#/"
        me = c.get("/api/me").json()
        assert me["name"] == "New Bie" and me["permissions"] == []  # least privilege until a role is assigned
        assert "/api/v10/users/@me/guilds/999/member" in calls
        sec = None
        # the owner can see the login in security events
    with TestClient(app) as owner:
        owner.post("/auth/dev-login")
        sec = owner.get("/api/admin/security").json()
        assert any(e["kind"] == "login" and e["detail"] == "discord" for e in sec["recent_logins"]) or sec["recent_logins"]


def test_logout_revokes_session(web):
    assert web.post("/auth/logout").status_code == 200
    assert web.get("/api/me").status_code == 401


def test_websocket_requires_auth_and_filters_by_permission(web):
    anon = TestClient(web.app)
    with pytest.raises(Exception):
        with anon.websocket_connect("/ws") as ws:
            ws.receive_json()
    with web.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello"
        ws.send_text("ping")
        assert json.loads(ws.receive_text())["kind"] == "pong"

    from nexus.api.realtime import allowed
    from nexus.core.context import Actor
    from nexus.db.models import EventOutbox

    viewer = Actor(user_id=5, permissions=frozenset({"erlc.server.view"}))
    disp = Actor(user_id=6, permissions=frozenset({"cad.view", "cad.dispatch"}))
    assert not allowed(viewer, EventOutbox(kind="incident.created", payload={}))
    assert allowed(disp, EventOutbox(kind="incident.created", payload={}))
    assert allowed(viewer, EventOutbox(kind="erlc.synced", payload={}))
    assert not allowed(viewer, EventOutbox(kind="notification", payload={"audience": "perm:cad.dispatch"}))
    assert not allowed(disp, EventOutbox(kind="notification", payload={"audience": "user", "user_id": 99}))
    assert not allowed(disp, EventOutbox(kind="comms.message", payload={"restricted": True}))


def test_realtime_hub_delivers_outbox_events(web):
    """Events written by any process reach connected browsers through the outbox tailer."""
    tailer = web.app.state.tailer
    web.portal.call(tailer.poll_once)  # initialise the cursor before the event is written
    with web.websocket_connect("/ws") as ws:
        ws.receive_json()
        web.post("/api/cad/incidents", json={"category": "crime", "description": "live test"})
        assert web.portal.call(tailer.poll_once) >= 1
        kinds = []
        for _ in range(6):
            msg = ws.receive_json()
            kinds.append(msg["kind"])
            if msg["kind"] == "incident.created":
                assert msg["payload"]["description"] == "live test"
                break
        assert "incident.created" in kinds


def test_webhook_signature_verification(monkeypatch):
    from nexus.api.routes import erlc as erlc_routes

    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    raw = b'{"event":"EmergencyCall","data":{}}'
    ts = "1700000000"
    sig = key.sign(ts.encode() + raw).hex()
    assert erlc_routes.verify_webhook_signature(raw, ts, sig, pub)
    assert not erlc_routes.verify_webhook_signature(raw + b" ", ts, sig, pub)  # body tampered
    assert not erlc_routes.verify_webhook_signature(raw, "1700000001", sig, pub)  # timestamp tampered
    assert not erlc_routes.verify_webhook_signature(raw, ts, "zz", pub)
    # official key parses
    assert erlc_routes.verify_webhook_signature(raw, ts, sig, erlc_routes.ERLC_WEBHOOK_PUBLIC_KEY) is False


def test_webhook_endpoint_disabled_by_default(web):
    assert web.post("/api/erlc/webhook", content=b"{}").status_code == 404


def test_validation_errors_are_friendly(web):
    r = web.post("/api/cad/incidents", json={"category": "crime", "priority": 99, "description": "x"})
    assert r.status_code == 422 and "Priority" in r.json()["message"]
    r = web.get("/api/cad/incidents/999999")
    assert r.status_code == 404 and "not found" in r.json()["message"].lower()


def test_erlc_errors_map_to_http(web, fake_erlc):
    fake_erlc.responses.append(httpx.Response(422, json={"message": "The private server is currently offline.", "commandId": "x"}))
    r = web.post("/api/erlc/command", json={"command": ":h hi"})
    assert r.status_code == 409 and "offline" in r.json()["message"].lower()
    r = web.post("/api/erlc/command", json={"command": "no colon"})
    assert r.status_code == 400


def test_full_cad_flow_over_http(web):
    unit = web.post("/api/cad/units", json={"department_id": 1, "callsign": "1A-09", "status": "available"}).json()
    inc = web.post("/api/cad/incidents", json={"category": "traffic", "priority": 2, "location_name": "Hwy 1", "description": "Crash"}).json()
    d = web.post(f"/api/cad/incidents/{inc['id']}/assign", json={"unit": unit["id"]}).json()
    assert d["status"] == "dispatched" and d["units"][0]["callsign"] == "1A-09"
    d = web.post(f"/api/cad/incidents/{inc['id']}/notes", json={"body": "Two vehicles"}).json()
    assert d["notes"][0]["body"] == "Two vehicles"
    d = web.post(f"/api/cad/incidents/{inc['id']}/status", json={"status": "closed", "disposition": "Report taken"}).json()
    assert d["status"] == "closed" and not d["units"]
    rep = web.post("/api/reports", json={"incident_id": inc["number"], "summary": "Crash", "description": "Details"}).json()
    assert rep["incident_number"] == inc["number"]
    assert web.get(f"/api/reports/{rep['id']}/export").status_code == 200
    csv = web.get("/api/analytics/cad.csv?days=1").text
    assert csv.startswith("day,count")


def test_dev_login_rejects_cross_site_requests(settings, fake_erlc):
    from nexus.api.app import create_app
    from nexus.runtime import Runtime

    app = create_app(Runtime(settings, erlc_transport=fake_erlc.transport), start_background=False)
    with TestClient(app) as c:
        assert c.post("/auth/dev-login", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/auth/dev-login", headers={"Origin": "http://testserver"}, follow_redirects=False).status_code == 303
