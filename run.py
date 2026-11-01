"""ERLC Nexus launcher.

    python run.py            start website + Discord bot (default)
    python run.py web        website only
    python run.py bot        Discord bot only
    python run.py stop       stop a running launcher
    python run.py check      validate configuration and database

The launcher validates configuration, applies a staged database restore, runs
migrations once, then starts each component as its own process. A component
that crashes is restarted with back-off. Ctrl+C or ``stop.bat`` shuts everything
down cleanly.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from nexus import __version__  # noqa: E402
from nexus.config import get_settings  # noqa: E402

IS_WINDOWS = os.name == "nt"
COMPONENTS = {"web": "nexus.api.app", "bot": "nexus.bot.core"}

C = {"ok": "\033[92m", "warn": "\033[93m", "bad": "\033[91m", "dim": "\033[2m", "b": "\033[1m", "end": "\033[0m"}
if IS_WINDOWS:
    os.system("")  # enable ANSI colours in Windows terminals


def say(msg: str, kind: str = "") -> None:
    prefix = {"ok": "[ OK ]", "warn": "[WARN]", "bad": "[FAIL]", "": "[    ]"}[kind]
    color = C.get(kind, "")
    print(f"{color}{prefix}{C['end']} {msg}", flush=True)


def paths():
    s = get_settings()
    data = s.data_path
    data.mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(exist_ok=True)
    return s, data / "nexus.pid", data / "stop.flag"


def check(component: str = "all") -> bool:
    s, _, _ = paths()
    print(f"\n{C['b']}ERLC Nexus {__version__}{C['end']} — configuration check\n")
    ok = True
    if not (ROOT / "config.env").exists():
        say("config.env is missing. Run install.bat first.", "bad")
        return False
    for problem in s.problems(component):
        blocking = "SECRET_KEY" in problem or (component in ("bot",) and "BOT_TOKEN" in problem)
        say(problem, "bad" if blocking else "warn")
        ok = ok and not blocking
    if s.dev_login:
        say("DEV_LOGIN is enabled: anyone using this computer can sign in as the initial administrator.", "warn")
    if s.web_host not in ("127.0.0.1", "localhost"):
        say(f"Website listens on {s.web_host} (reachable from your network). Use HTTPS + COOKIE_SECURE=true if exposed publicly.", "warn")
    try:
        from nexus.db.base import Database
        from nexus.db.migrate import upgrade_to_head

        async def _db():
            db = Database(s.db_url)
            try:
                await upgrade_to_head(db)
                return await db.ping()
            finally:
                await db.dispose()

        if asyncio.run(_db()):
            say(f"Database ready ({'SQLite' if s.is_sqlite else 'PostgreSQL'})", "ok")
        else:
            say("Database is not reachable.", "bad")
            ok = False
    except Exception as exc:
        say(f"Database error: {exc}", "bad")
        ok = False
    return ok


def apply_restore() -> None:
    s, _, _ = paths()
    if not s.is_sqlite:
        return
    from nexus.services.backup import apply_pending_restore

    try:
        msg = apply_pending_restore(s)
        if msg:
            say(msg, "ok")
    except Exception as exc:
        say(f"Staged restore could not be applied: {exc}", "bad")


def wait_for_web(url: str, timeout: float = 45) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


class Supervisor:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.procs: dict[str, subprocess.Popen] = {}
        self.restarts: dict[str, list[float]] = {n: [] for n in names}
        self.stopping = False

    def spawn(self, name: str) -> None:
        kwargs = {"cwd": str(ROOT)}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.procs[name] = subprocess.Popen([sys.executable, "-m", COMPONENTS[name]], env=env, **kwargs)
        say(f"Started {name} (pid {self.procs[name].pid})", "ok")

    def stop_all(self) -> None:
        self.stopping = True
        for name, p in self.procs.items():
            if p.poll() is None:
                say(f"Stopping {name}…")
                try:
                    if IS_WINDOWS:
                        p.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        p.send_signal(signal.SIGINT)
                except Exception:
                    pass
        deadline = time.time() + 15
        for name, p in self.procs.items():
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                say(f"{name} did not stop in time; terminating.", "warn")
                p.kill()
        say("All components stopped.", "ok")

    def run(self, stop_flag: Path) -> int:
        s = get_settings()
        if "web" in self.names:
            self.spawn("web")
            if wait_for_web(f"http://127.0.0.1:{s.web_port}"):
                say(f"Website: {C['b']}{s.base_url}{C['end']}", "ok")
            else:
                say("Website did not respond yet — check data/logs/web.log", "warn")
        if "bot" in self.names:
            self.spawn("bot")
        print(f"\n{C['dim']}ERLC Nexus is running. Keep this window open. Press Ctrl+C or run stop.bat to stop.{C['end']}")
        print(f"{C['dim']}It is only online while this computer is on and awake.{C['end']}\n")
        try:
            while not self.stopping:
                if stop_flag.exists():
                    stop_flag.unlink(missing_ok=True)
                    say("Stop requested.")
                    break
                for name, p in list(self.procs.items()):
                    code = p.poll()
                    if code is None:
                        continue
                    if code == 2:
                        say(f"{name} exited because of a configuration problem (see messages above / data/logs/{name}.log). Not restarting.", "bad")
                        self.procs.pop(name)
                        continue
                    recent = [t for t in self.restarts[name] if time.time() - t < 300]
                    self.restarts[name] = recent
                    if len(recent) >= 5:
                        say(f"{name} keeps crashing (5 times in 5 minutes). Giving up — check data/logs/{name}.log.", "bad")
                        self.procs.pop(name)
                        continue
                    delay = 2 ** len(recent)
                    say(f"{name} stopped unexpectedly (exit {code}). Restarting in {delay}s…", "warn")
                    time.sleep(delay)
                    self.restarts[name].append(time.time())
                    self.spawn(name)
                if not self.procs:
                    say("No components are running.", "bad")
                    return 1
                time.sleep(1)
        except KeyboardInterrupt:
            print()
        finally:
            self.stop_all()
        return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "all"
    s, pid_file, stop_flag = paths()
    if cmd == "stop":
        if not pid_file.exists():
            say("ERLC Nexus does not appear to be running.", "warn")
            return 0
        stop_flag.write_text("stop")
        say("Stop signal sent. Waiting for ERLC Nexus to shut down…")
        for _ in range(40):
            if not pid_file.exists():
                say("Stopped.", "ok")
                return 0
            time.sleep(0.5)
        say("ERLC Nexus did not confirm shutdown. Close its window if it is still open.", "warn")
        return 1
    if cmd == "check":
        return 0 if check() else 1
    if cmd not in ("all", "web", "bot"):
        print(__doc__)
        return 2
    names = ["web", "bot"] if cmd == "all" else [cmd]
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            alive = True
            if IS_WINDOWS:
                out = subprocess.run(["tasklist", "/FI", f"PID eq {old}"], capture_output=True, text=True).stdout
                alive = str(old) in out
            else:
                os.kill(old, 0)
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            alive = False
        if alive:
            say(f"ERLC Nexus already seems to be running (pid {old}). Run stop.bat first.", "bad")
            return 1
    apply_restore()
    if not check("all" if cmd == "all" else cmd):
        say("Fix the problems above and run start.bat again.", "bad")
        return 1
    if "bot" in names and not s.discord_bot_token:
        say("DISCORD_BOT_TOKEN is not set — starting the website only.", "warn")
        names.remove("bot")
    if not names:
        return 1
    stop_flag.unlink(missing_ok=True)
    pid_file.write_text(str(os.getpid()))
    try:
        return Supervisor(names).run(stop_flag)
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
