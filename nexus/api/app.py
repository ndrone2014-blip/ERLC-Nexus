"""FastAPI application factory for the ERLC Nexus website and API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from nexus import __version__
from nexus.api.deps import SESSION_COOKIE, client_ip, load_session
from nexus.api.realtime import Client, Hub
from nexus.config import ROOT_DIR
from nexus.core.context import NexusError
from nexus.core.events import OutboxTailer, prune_outbox
from nexus.core.settings_store import invalidate_cache
from nexus.db.models import User
from nexus.erlc.client import ErlcError
from nexus.erlc.sync import SyncService
from nexus.runtime import Runtime
from nexus.services import maps, records, shifts
from nexus.services.users import resolve_actor

log = logging.getLogger("nexus.web")
WEB_DIR = ROOT_DIR / "web"

ERLC_STATUS = {"not_configured": 503, "auth": 502, "rate_limited": 429, "offline": 409, "forbidden": 403,
               "restricted": 403, "bad_request": 400, "transient": 502, "network": 504, "invalid_response": 502,
               "outdated_module": 502}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https://cdn.discordapp.com "
       "https://api.erlc.gg; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self' "
       "https://discord.com")


class RateLimiter:
    """Simple sliding-window limiter per client IP and bucket."""

    def __init__(self) -> None:
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def allow(self, ip: str, bucket: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self.hits[(ip, bucket)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


async def periodic(app: FastAPI) -> None:
    rt: Runtime = app.state.runtime
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        try:
            async with rt.db.session() as s:
                await records.expire_bolos(s)
                await s.commit()
            if tick % 30 == 0:
                await prune_outbox(rt.db)
        except Exception:
            log.exception("periodic task failed")


def create_app(runtime: Runtime | None = None, *, start_background: bool = True, run_migrations: bool = True) -> FastAPI:
    rt = runtime or Runtime(component="web")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await rt.startup(run_migrations=run_migrations)
        async with rt.db.session() as s:
            recovered = await shifts.recover_active_shifts(s)
            await s.commit()
        if recovered:
            log.info("Recovered %s active shift(s) after restart", recovered)
        hub: Hub = app.state.hub

        async def refresh_actor(user_id: int):
            async with rt.db.session() as s:
                user = await s.get(User, user_id)
                return await resolve_actor(s, user) if user and user.is_active else None

        hub.refresh_actor = refresh_actor

        async def on_event(ev):
            if ev.kind == "config.changed":
                invalidate_cache()
                if ev.payload.get("key") == "erlc.server_key_encrypted":
                    await rt.refresh_server_key()
            await hub.handle(ev)

        tasks = []
        tailer = OutboxTailer(rt.db, on_event, interval=1.0, name="web")
        app.state.tailer = tailer
        if start_background:
            tailer.start()
            app.state.sync = SyncService(rt)
            app.state.sync.start()
            tasks.append(asyncio.create_task(periodic(app), name="periodic"))
        log.info("ERLC Nexus website ready on %s", rt.settings.base_url)
        try:
            yield
        finally:
            log.info("Shutting down website…")
            for t in tasks:
                t.cancel()
            await tailer.stop()
            if getattr(app.state, "sync", None):
                await app.state.sync.stop()
            await rt.shutdown()

    app = FastAPI(title="ERLC Nexus", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.runtime = rt
    app.state.hub = Hub()
    app.state.sync = None
    limiter = RateLimiter()

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        ip = client_ip(request) or "?"
        if path.startswith("/auth/") and not limiter.allow(ip, "auth", 30):
            return JSONResponse({"error": "rate_limited", "message": "Too many login attempts. Wait a minute."}, status_code=429)
        if path.startswith("/api/") and not limiter.allow(ip, "api", 600):
            return JSONResponse({"error": "rate_limited", "message": "Too many requests. Slow down."}, status_code=429)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = CSP
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NexusError)
    async def nexus_error(request: Request, exc: NexusError):
        return JSONResponse({"error": exc.code, "message": exc.message, "details": exc.details}, status_code=exc.status)

    @app.exception_handler(ErlcError)
    async def erlc_error(request: Request, exc: ErlcError):
        return JSONResponse({"error": f"erlc_{exc.kind}", "message": exc.message, "retry_after": exc.retry_after},
                            status_code=ERLC_STATUS.get(exc.kind, 502))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()]
        return JSONResponse({"error": "validation", "message": "Some fields are missing or invalid: " + ", ".join(fields),
                             "details": {"fields": fields}}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "server_error", "message": "Something went wrong. The error has been logged."},
                            status_code=500)

    from nexus.api.routes import admin, analytics, auth, cad, dashboard, departments, erlc, records as records_routes

    for module in (auth, dashboard, erlc, cad, records_routes, departments, analytics, admin):
        app.include_router(module.router)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        async with rt.db.session() as s:
            session = await load_session(s, ws.cookies.get(SESSION_COOKIE))
            user = await s.get(User, session.user_id) if session else None
            actor = await resolve_actor(s, user) if user and user.is_active else None
        if actor is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        client = Client(ws=ws, actor=actor, user_id=user.id)
        await app.state.hub.add(client)
        try:
            await ws.send_json({"kind": "hello", "payload": {"user": user.name}})
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text('{"kind":"pong"}')
        except WebSocketDisconnect:
            pass
        except Exception:
            log.debug("websocket closed", exc_info=True)
        finally:
            await app.state.hub.remove(client)

    @app.get("/map-image/{style}.png", include_in_schema=False)
    async def map_image(style: str):
        if style not in maps.MAP_STYLES:
            return JSONResponse({"error": "not_found"}, status_code=404)
        local = rt.settings.data_path / "maps" / f"{style}.png"
        if local.exists():
            return FileResponse(local, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        return RedirectResponse(maps.MAP_STYLES[style], status_code=307)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="web")
    return app


def run(host: str | None = None, port: int | None = None) -> None:  # pragma: no cover - process entry
    import uvicorn

    from nexus.config import get_settings
    from nexus.logging_setup import setup_logging

    settings = get_settings()
    setup_logging("web", settings.data_path / "logs", settings.log_level)
    app = create_app(Runtime(settings, component="web"))
    uvicorn.run(app, host=host or settings.web_host, port=port or settings.web_port, log_level="warning",
                proxy_headers=False, ws_ping_interval=20, ws_ping_timeout=20)


if __name__ == "__main__":  # pragma: no cover
    run()
