"""Public HTTPS link for a self-hosted ERLC Nexus via Cloudflare Tunnel.

Used by ``start-online.bat`` (``run.py online``). Cloudflare Tunnel is free and opens
an outbound connection from this computer to Cloudflare, so no router or firewall
changes are needed and the website keeps listening on 127.0.0.1 only.

Two modes:

* **Quick tunnel** (default, no account): a random ``https://….trycloudflare.com``
  address that changes every time it starts.
* **Fixed tunnel**: set ``TUNNEL_TOKEN`` (from the Cloudflare dashboard) and
  ``PUBLIC_URL`` (the hostname you attached to that tunnel) for a permanent address.

``cloudflared`` is Cloudflare's official open-source client (Apache-2.0). If it isn't
installed, it is downloaded once from Cloudflare's GitHub releases into ``data/tools``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

QUICK_URL_RE = re.compile(r"https://([a-z0-9][a-z0-9-]*)\.trycloudflare\.com(?![\w/.-])")
# Cloudflare's own service hosts also appear in log/error lines; they are never a tunnel address.
NOT_A_TUNNEL = {"api", "www"}
RELEASE_BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"


class TunnelError(RuntimeError):
    """A tunnel problem with a user-readable message."""


def find_quick_url(text: str) -> str | None:
    """The tunnel address from a cloudflared output line, ignoring errors and service URLs."""
    low = text.lower()
    if "failed" in low or " err " in f" {low} " or "error" in low:
        return None
    for m in QUICK_URL_RE.finditer(text):
        if m.group(1) not in NOT_A_TUNNEL:
            return m.group(0)
    return None


def asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """Release file name for this OS / CPU, or None if it must be installed manually."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arm = machine in ("arm64", "aarch64")
    if system == "windows":
        return "cloudflared-windows-arm64.exe" if arm else (
            "cloudflared-windows-amd64.exe" if machine in ("amd64", "x86_64", "") else "cloudflared-windows-386.exe")
    if system == "linux":
        if arm:
            return "cloudflared-linux-arm64"
        if machine.startswith("arm"):
            return "cloudflared-linux-arm"
        return "cloudflared-linux-amd64"
    return None  # macOS ships as an archive: `brew install cloudflared`


def _works(path: Path | str) -> bool:
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and "cloudflared" in (out.stdout + out.stderr).lower()


def locate(tools_dir: Path, configured: str = "", download: bool = True, log=print) -> Path:
    """Find cloudflared: CLOUDFLARED_PATH → data/tools → PATH → download."""
    if configured:
        p = Path(configured)
        if not _works(p):
            raise TunnelError(f"CLOUDFLARED_PATH={configured} is not a working cloudflared program.")
        return p
    exe = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local = tools_dir / exe
    if local.exists() and _works(local):
        return local
    on_path = shutil.which("cloudflared")
    if on_path and _works(on_path):
        return Path(on_path)
    if not download:
        raise TunnelError("cloudflared is not installed.")
    name = asset_name()
    if not name:
        raise TunnelError("Install cloudflared first (macOS: `brew install cloudflared`), then run this again.")
    tools_dir.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".part")
    log("Downloading Cloudflare Tunnel (cloudflared) from GitHub — one time only…")
    try:
        req = urllib.request.Request(RELEASE_BASE + name, headers={"User-Agent": "ERLC-Nexus"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise TunnelError(f"Could not download cloudflared ({exc}). Check your internet connection, "
                          "or download it from github.com/cloudflare/cloudflared/releases and set CLOUDFLARED_PATH.") from exc
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise TunnelError("The cloudflared download looks incomplete. Try again.")
    tmp.replace(local)
    if os.name != "nt":
        local.chmod(local.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if not _works(local):
        local.unlink(missing_ok=True)
        raise TunnelError("The downloaded cloudflared program does not run on this computer.")
    return local


class Tunnel:
    """A running cloudflared process."""

    def __init__(self, exe: Path, port: int, token: str = "", log_file: Path | None = None) -> None:
        self.exe = exe
        self.port = port
        self.token = token
        self.log_file = log_file
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.lines: deque[str] = deque(maxlen=60)
        self._ready = threading.Event()

    @property
    def fixed(self) -> bool:
        return bool(self.token)

    def command(self) -> list[str]:
        base = [str(self.exe), "tunnel", "--no-autoupdate"]
        if self.token:
            # The token is passed through the environment, not the command line, so it
            # doesn't show up in process listings.
            return base + ["run"]
        return base + ["--url", f"http://127.0.0.1:{self.port}"]

    def start(self, timeout: float = 45) -> str | None:
        env = dict(os.environ)
        if self.token:
            env["TUNNEL_TOKEN"] = self.token
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                     env=env, **kwargs)
        threading.Thread(target=self._read, daemon=True).start()
        end = time.time() + timeout
        while time.time() < end:
            if self._ready.wait(0.25):
                return self.url
            if self.proc.poll() is not None:
                break
        if self.proc.poll() is not None:
            raise TunnelError("Cloudflare Tunnel stopped while starting:\n  " + "\n  ".join(list(self.lines)[-8:]))
        if not self.fixed:
            self.stop()
            raise TunnelError("Cloudflare Tunnel didn't report a public address in time. "
                              "Check your internet connection and try again.")
        return None

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        fh = open(self.log_file, "a", encoding="utf-8") if self.log_file else None
        try:
            for line in self.proc.stdout:
                line = line.rstrip()
                if self.token:
                    line = line.replace(self.token, "***")
                self.lines.append(line)
                if fh:
                    fh.write(line + "\n")
                    fh.flush()
                if not self._ready.is_set():
                    if not self.fixed:
                        url = find_quick_url(line)
                        if url:
                            self.url = url
                            self._ready.set()
                    elif "registered tunnel connection" in line.lower():
                        self._ready.set()
        finally:
            if fh:
                fh.close()

    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def copy_to_clipboard(text: str) -> bool:
    """Best effort; Windows only (uses the built-in `clip` command)."""
    if os.name != "nt":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True, timeout=5)
        return True
    except Exception:
        return False
