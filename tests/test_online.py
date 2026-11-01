"""start-online: Cloudflare Tunnel public link, proxy-aware visitor IPs, launcher wiring."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus import tunnel as tun
from nexus.api.deps import real_ip

FAKE = Path(__file__).parent / "fixtures" / "fake_cloudflared.py"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run as launcher  # noqa: E402


def _req(peer: str, **headers):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={k.lower().replace("_", "-"): v for k, v in headers.items()})


# --- address detection ------------------------------------------------------------

def test_quick_url_found_in_cloudflared_banner():
    line = "2026-11-01T22:08:31Z INF |  https://brave-lunar-octopus-ridge.trycloudflare.com          |"
    assert tun.find_quick_url(line) == "https://brave-lunar-octopus-ridge.trycloudflare.com"


@pytest.mark.parametrize("line", [
    'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp: no such host',
    "INF Requesting new quick Tunnel on trycloudflare.com...",
    "ERR error=\"https://brave-lunar-octopus-ridge.trycloudflare.com unreachable\"",
    "see https://www.trycloudflare.com for details",
])
def test_error_and_service_lines_are_not_mistaken_for_the_address(line):
    # Found in a real run: the API host in an error message was reported as the link.
    assert tun.find_quick_url(line) is None


def test_download_asset_names():
    assert tun.asset_name("Windows", "AMD64") == "cloudflared-windows-amd64.exe"
    assert tun.asset_name("Windows", "ARM64") == "cloudflared-windows-arm64.exe"
    assert tun.asset_name("Linux", "x86_64") == "cloudflared-linux-amd64"
    assert tun.asset_name("Linux", "aarch64") == "cloudflared-linux-arm64"
    assert tun.asset_name("Darwin", "arm64") is None  # Homebrew instead


# --- visitor IPs behind the tunnel ----------------------------------------------------

def test_forwarded_ip_only_trusted_from_this_computer():
    assert real_ip(_req("127.0.0.1", CF_Connecting_IP="203.0.113.7"), trust_proxy=True) == "203.0.113.7"
    assert real_ip(_req("127.0.0.1", X_Forwarded_For="198.51.100.2, 10.0.0.1"), trust_proxy=True) == "198.51.100.2"
    # A remote visitor can't spoof the header when the site is exposed directly.
    assert real_ip(_req("198.51.100.9", CF_Connecting_IP="127.0.0.1"), trust_proxy=True) == "198.51.100.9"
    # Without TRUST_PROXY the headers are ignored.
    assert real_ip(_req("127.0.0.1", CF_Connecting_IP="203.0.113.7"), trust_proxy=False) == "127.0.0.1"
    # Plain local requests stay local.
    assert real_ip(_req("127.0.0.1"), trust_proxy=True) == "127.0.0.1"


def test_tunnelled_visitor_cannot_use_local_login(settings, fake_erlc):
    """Through a tunnel every request comes from 127.0.0.1; dev-login must still refuse visitors."""
    from fastapi.testclient import TestClient

    from nexus.api.app import create_app
    from nexus.runtime import Runtime

    settings.trust_proxy = True
    app = create_app(Runtime(settings, erlc_transport=fake_erlc.transport), start_background=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        r = c.post("/auth/dev-login", headers={"CF-Connecting-IP": "203.0.113.7"})
        assert r.status_code == 403
        assert c.get("/api/auth/config", headers={"CF-Connecting-IP": "203.0.113.7"}).json()["dev_login"] is False


def test_rate_limit_is_per_visitor_behind_tunnel(settings, fake_erlc):
    from fastapi.testclient import TestClient

    from nexus.api.app import create_app
    from nexus.runtime import Runtime

    settings.trust_proxy = True
    app = create_app(Runtime(settings, erlc_transport=fake_erlc.transport), start_background=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        for _ in range(30):
            c.get("/auth/login", headers={"CF-Connecting-IP": "203.0.113.7"}, follow_redirects=False)
        assert c.get("/auth/login", headers={"CF-Connecting-IP": "203.0.113.7"}, follow_redirects=False).status_code == 429
        # A different visitor is not blocked by the first one.
        assert c.get("/auth/login", headers={"CF-Connecting-IP": "198.51.100.2"}, follow_redirects=False).status_code != 429


# --- launcher settings --------------------------------------------------------------

def test_online_env_quick_tunnel():
    env = launcher.online_env("https://a-b-c.trycloudflare.com/", fixed=False)
    assert env == {"PUBLIC_URL": "https://a-b-c.trycloudflare.com", "COOKIE_SECURE": "true", "TRUST_PROXY": "true",
                   "DEV_LOGIN": "false", "DISCORD_REDIRECT_URI": "https://a-b-c.trycloudflare.com/auth/callback"}


def test_online_env_fixed_tunnel_keeps_custom_redirect():
    env = launcher.online_env("https://cad.example.com", fixed=True, current_redirect="https://cad.example.com/auth/callback")
    assert "DISCORD_REDIRECT_URI" not in env and env["PUBLIC_URL"] == "https://cad.example.com"


def test_online_settings_flow_into_oauth_and_bot_links(monkeypatch, tmp_path):
    from nexus.config import load_settings

    for k, v in launcher.online_env("https://a-b-c.trycloudflare.com", fixed=False).items():
        monkeypatch.setenv(k, v)
    s = load_settings(tmp_path / "missing.env")
    assert s.base_url == "https://a-b-c.trycloudflare.com"
    assert s.oauth_redirect == "https://a-b-c.trycloudflare.com/auth/callback"
    assert s.cookie_secure and s.trust_proxy and not s.dev_login


def test_tunnel_token_is_masked():
    from nexus.config import Settings

    assert Settings(tunnel_token="eyJhIjoi-secret").safe_dict()["tunnel_token"] == "configured"


# --- the tunnel process (stand-in cloudflared) ---------------------------------------

@pytest.fixture
def fake_cf(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("stand-in uses a shebang script")
    exe = tmp_path / "cloudflared"
    exe.write_text(FAKE.read_text())
    exe.chmod(0o755)
    monkeypatch.setenv("FAKE_CF_PORT_FILE", str(tmp_path / "port"))
    return exe


def test_locate_prefers_configured_path(fake_cf, tmp_path):
    assert tun.locate(tmp_path / "tools", str(fake_cf), download=False) == fake_cf
    with pytest.raises(tun.TunnelError):
        tun.locate(tmp_path / "tools", str(tmp_path / "nope"), download=False)


def test_tunnel_reports_address_and_stops(fake_cf, tmp_path):
    t = tun.Tunnel(fake_cf, 8999, log_file=tmp_path / "tunnel.log")
    try:
        assert t.start(timeout=20) == "https://brave-lunar-octopus-ridge.trycloudflare.com"
        assert t.alive()
    finally:
        t.stop()
    assert not t.alive()
    assert "quick Tunnel has been created" in (tmp_path / "tunnel.log").read_text()


def test_tunnel_failure_is_explained(fake_cf, monkeypatch):
    monkeypatch.setenv("FAKE_CF_MODE", "fail")
    with pytest.raises(tun.TunnelError) as exc:
        tun.Tunnel(fake_cf, 8999).start(timeout=20)
    assert "no such host" in str(exc.value)


def test_fixed_tunnel_token_not_on_command_line_or_in_logs(fake_cf, tmp_path):
    t = tun.Tunnel(fake_cf, 8999, token="SECRET-TOKEN-123")
    assert "SECRET-TOKEN-123" not in " ".join(t.command())
    t.lines.append("x")
    # Output lines are scrubbed of the token before they are stored or logged.
    t2 = tun.Tunnel(Path(sys.executable), 0, token="SECRET-TOKEN-123", log_file=tmp_path / "t.log")
    t2.proc = subprocess.Popen([sys.executable, "-c", "print('token SECRET-TOKEN-123 Registered tunnel connection')"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    t2._read()
    assert "SECRET-TOKEN-123" not in (tmp_path / "t.log").read_text()
    assert t2._ready.is_set()


def test_launcher_online_end_to_end(fake_cf, tmp_path):
    """run.py online: tunnel → website at the public address, visitor IPs, clean stop."""
    port = 18000 + os.getpid() % 1000
    root = tmp_path / "app"
    root.mkdir()
    (root / "config.env").write_text(
        f"SECRET_KEY={'k' * 48}\nWEB_PORT={port}\nDISCORD_APPLICATION_ID=1\nDISCORD_CLIENT_SECRET=x\n"
        f"DEV_LOGIN=true\nINITIAL_ADMIN_DISCORD_ID=5\nCLOUDFLARED_PATH={fake_cf}\nDATA_DIR={root / 'data'}\n")
    import shutil

    for item in ("nexus", "web", "run.py", "alembic.ini"):
        src = ROOT / item
        (shutil.copytree if src.is_dir() else shutil.copy)(src, root / item)
    env = {k: v for k, v in os.environ.items() if k not in
           ("PUBLIC_URL", "DEV_LOGIN", "TRUST_PROXY", "COOKIE_SECURE", "DISCORD_REDIRECT_URI", "DATA_DIR")}
    proc = subprocess.Popen([sys.executable, str(root / "run.py"), "online"], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        port_file = Path(os.environ["FAKE_CF_PORT_FILE"])
        deadline = time.time() + 60
        edge = None
        while time.time() < deadline:
            if port_file.exists() and port_file.read_text():
                edge = int(port_file.read_text())
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{edge}/api/auth/config", timeout=2) as r:
                        if r.status == 200:
                            break
                except Exception:
                    pass
            time.sleep(0.5)
        else:
            proc.kill()
            pytest.fail("website never answered through the tunnel:\n" + proc.communicate()[0][-3000:])
        req = urllib.request.Request(f"http://127.0.0.1:{edge}/auth/login")
        opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                                                  {"redirect_request": lambda *a, **k: None}))
        try:
            opener.open(req, timeout=5)
        except urllib.error.HTTPError as e:
            loc = e.headers["location"]
            assert "redirect_uri=https%3A%2F%2Fbrave-lunar-octopus-ridge.trycloudflare.com%2Fauth%2Fcallback" in loc
            assert "Secure" in e.headers["set-cookie"]
        assert (root / "data" / "public_url.txt").read_text().strip() == "https://brave-lunar-octopus-ridge.trycloudflare.com"
    finally:
        subprocess.run([sys.executable, str(root / "run.py"), "stop"], cwd=root, env=env, capture_output=True, timeout=60)
        out, _ = proc.communicate(timeout=60)
    assert "DEV_LOGIN is turned OFF while online" in out
    assert "Your ERLC Nexus website is ONLINE" in out
    assert "Public link closed." in out
    assert not (root / "data" / "public_url.txt").exists()
