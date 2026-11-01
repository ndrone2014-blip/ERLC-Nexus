"""Official PRC (ER:LC) API client — https://apidocs.erlc.gg

Implements the documented rules:
  * ``server-key`` header on every request, optional ``Authorization`` global key.
  * Rate-limit buckets learned from ``X-RateLimit-*`` headers; waits before
    sending when a bucket is exhausted.
  * On 429: honours ``Retry-After`` / ``retry_after`` for the whole bucket.
  * ``POST /v2/server/command`` is serialised with ≥5 s spacing (documented
    1 request / 5 s).
  * Only transient failures (network, 5xx, codes 1001/1002) are retried, with
    capped exponential back-off. 400/403/422 and 2xxx/3xxx/4xxx codes are never
    retried.
  * After 403 / codes 2000-2002/2004 the key is marked invalid and every call
    stops until the key is changed (avoids the documented invalid-request block
    and IP bans).
  * Responses are cached for ``cache_ttl`` seconds.
The server key is never logged or included in exceptions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from nexus.erlc.models import ServerSnapshot

log = logging.getLogger("nexus.erlc")

ALL_FLAGS = ("Players", "Staff", "JoinLogs", "Queue", "KillLogs", "CommandLogs", "ModCalls", "EmergencyCalls", "Vehicles")
COMMAND_SPACING = 5.0
MAX_COMMAND_LEN = 300

API_ERROR_MESSAGES = {
    0: "Unknown ERLC API error.",
    1001: "The ERLC API could not communicate with Roblox or the private server.",
    1002: "ERLC API internal error.",
    2000: "No server key was provided.",
    2001: "The server key is malformed.",
    2002: "The server key is invalid or expired. Update it in System > API Configuration.",
    2003: "The global API key is invalid.",
    2004: "This server key is banned from the ERLC API.",
    2005: "Unauthenticated requests for multiple servers are not allowed. A public application key is required.",
    3001: "The command is missing or invalid.",
    3002: "The private server is offline (no players in server).",
    4000: "You are not permitted to perform this action on this server.",
    4001: "Rate limited by the ERLC API. Nexus is waiting before retrying.",
    4002: "That command is restricted by the ERLC API.",
    4003: "That message is prohibited by the ERLC API.",
    9998: "That resource is restricted.",
    9999: "The in-game API module is outdated. Kick all players from the private server and try again.",
}

KEY_INVALID_CODES = {2000, 2001, 2002, 2004}
TRANSIENT_CODES = {1001, 1002}


class ErlcError(Exception):
    """User-safe ERLC API error. ``kind`` is one of:
    not_configured, auth, rate_limited, offline, forbidden, restricted, bad_request,
    transient, network, invalid_response, outdated_module.
    """

    def __init__(self, kind: str, message: str, *, http_status: int | None = None, api_code: int | None = None,
                 retry_after: float | None = None, command_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.http_status = http_status
        self.api_code = api_code
        self.retry_after = retry_after
        self.command_id = command_id

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "http_status": self.http_status,
                "api_code": self.api_code, "retry_after": self.retry_after}


@dataclass
class Bucket:
    name: str
    limit: int | None = None
    remaining: int | None = None
    reset_at: float = 0.0          # epoch seconds
    blocked_until: float = 0.0     # monotonic seconds (429 penalty)


@dataclass
class ClientStats:
    requests: int = 0
    failures: int = 0
    rate_limited: int = 0
    last_ok: float | None = None
    last_error: dict[str, Any] | None = None
    last_latency_ms: int | None = None
    key_invalid_reason: str | None = None
    buckets: dict[str, Bucket] = field(default_factory=dict)


class ErlcClient:
    def __init__(
        self,
        server_key: str | Callable[[], str | None],
        *,
        base_url: str = "https://api.erlc.gg",
        global_key: str = "",
        timeout: float = 10.0,
        cache_ttl: float = 15.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._key_source = server_key
        self.base_url = base_url.rstrip("/")
        self.global_key = global_key
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._http: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._route_bucket: dict[str, str] = {}
        self._command_lock = asyncio.Lock()
        self._last_command_at: float = -1e9
        self._invalid_key: str | None = None
        self.stats = ClientStats()

    # ---- key management --------------------------------------------------
    @property
    def server_key(self) -> str | None:
        key = self._key_source() if callable(self._key_source) else self._key_source
        return (key or "").strip() or None

    @property
    def configured(self) -> bool:
        return self.server_key is not None

    @property
    def key_invalid(self) -> bool:
        key = self.server_key
        return key is not None and self._invalid_key == key

    def reset_key_state(self) -> None:
        self._invalid_key = None
        self.stats.key_invalid_reason = None
        self._cache.clear()

    # ---- http ----------------------------------------------------------------
    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=self._transport,
                                           headers={"User-Agent": "ERLC-Nexus/1.0 (self-hosted)"})
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        key = self.server_key
        if key is None:
            raise ErlcError("not_configured", "No ERLC server key configured. Add it in System > API Configuration.")
        h = {"server-key": key, "Accept": "application/json"}
        if self.global_key:
            h["Authorization"] = self.global_key
        return h

    def _bucket(self, name: str) -> Bucket:
        b = self.stats.buckets.get(name)
        if b is None:
            b = self.stats.buckets[name] = Bucket(name=name)
        return b

    async def _wait_for_bucket(self, route_key: str) -> None:
        name = self._route_bucket.get(route_key)
        if not name:
            return
        b = self._bucket(name)
        now = self._clock()
        if b.blocked_until > now:
            wait = b.blocked_until - now
            if wait > 30:
                raise ErlcError("rate_limited", f"ERLC API rate limit active for {int(wait)}s.", retry_after=wait)
            await self._sleep(wait)
        if b.remaining is not None and b.remaining <= 0 and b.reset_at:
            wait = b.reset_at - time.time()
            if 0 < wait <= 30:
                await self._sleep(wait)

    def _record_headers(self, route_key: str, resp: httpx.Response) -> None:
        name = resp.headers.get("X-RateLimit-Bucket")
        if not name:
            return
        self._route_bucket[route_key] = name
        b = self._bucket(name)
        try:
            if "X-RateLimit-Limit" in resp.headers:
                b.limit = int(resp.headers["X-RateLimit-Limit"])
            if "X-RateLimit-Remaining" in resp.headers:
                b.remaining = int(resp.headers["X-RateLimit-Remaining"])
            if "X-RateLimit-Reset" in resp.headers:
                b.reset_at = float(resp.headers["X-RateLimit-Reset"])
        except ValueError:
            pass

    @staticmethod
    def _parse_body(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return None

    def _error_from_response(self, resp: httpx.Response, body: Any) -> ErlcError:
        status = resp.status_code
        code = body.get("code") if isinstance(body, dict) and isinstance(body.get("code"), int) else None
        command_id = body.get("commandId") if isinstance(body, dict) else None
        api_msg = ""
        if isinstance(body, dict):
            api_msg = str(body.get("message") or body.get("error") or "")[:200]
        if status == 429 or code == 4001:
            retry = resp.headers.get("Retry-After")
            retry_after = None
            try:
                retry_after = float(retry) if retry else float(body.get("retry_after")) if isinstance(body, dict) and body.get("retry_after") is not None else None
            except (TypeError, ValueError):
                retry_after = None
            return ErlcError("rate_limited", API_ERROR_MESSAGES[4001], http_status=status, api_code=code or 4001,
                             retry_after=retry_after or 5.0)
        if code in KEY_INVALID_CODES or (status == 403 and code is None):
            msg = API_ERROR_MESSAGES.get(code or 2002) if code else "The ERLC API rejected the server key (403). Check or regenerate it."
            return ErlcError("auth", msg, http_status=status, api_code=code)
        if code == 2003:
            return ErlcError("auth", API_ERROR_MESSAGES[2003], http_status=status, api_code=code)
        if code == 2005:
            return ErlcError("forbidden", API_ERROR_MESSAGES[2005], http_status=status, api_code=code)
        if status == 422 or code == 3002:
            return ErlcError("offline", API_ERROR_MESSAGES[3002], http_status=status, api_code=code or 3002,
                             command_id=command_id)
        if code == 9999:
            return ErlcError("outdated_module", API_ERROR_MESSAGES[9999], http_status=status, api_code=code)
        if code in (4000,):
            return ErlcError("forbidden", API_ERROR_MESSAGES[4000], http_status=status, api_code=code)
        if code in (4002, 4003, 9998):
            return ErlcError("restricted", API_ERROR_MESSAGES[code], http_status=status, api_code=code)
        if code == 3001 or status == 400:
            return ErlcError("bad_request", API_ERROR_MESSAGES.get(code, "") or api_msg or "Bad request.",
                             http_status=status, api_code=code)
        if status >= 500 or code in TRANSIENT_CODES:
            return ErlcError("transient", API_ERROR_MESSAGES.get(code or 1001, API_ERROR_MESSAGES[1001]),
                             http_status=status, api_code=code, command_id=command_id)
        if status == 404:
            return ErlcError("bad_request", "ERLC API endpoint not found.", http_status=status, api_code=code)
        return ErlcError("transient" if status >= 500 else "bad_request",
                         API_ERROR_MESSAGES.get(code or 0, API_ERROR_MESSAGES[0]), http_status=status, api_code=code)

    async def _request(self, method: str, path: str, route_key: str, *, params: dict | None = None,
                       json: dict | None = None, retries: int | None = None) -> Any:
        if self.key_invalid:
            raise ErlcError("auth", self.stats.key_invalid_reason or "Server key is marked invalid.")
        headers = self._headers()
        attempts = (self.max_retries if retries is None else retries) + 1
        delay = 1.0
        last_exc: ErlcError | None = None
        for attempt in range(attempts):
            await self._wait_for_bucket(route_key)
            client = await self._client()
            started = self._clock()
            self.stats.requests += 1
            try:
                resp = await client.request(method, path, params=params, json=json, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_exc = ErlcError("network", "Could not reach the ERLC API (network error or timeout).")
                log.warning("ERLC API %s %s network error: %s", method, path, type(exc).__name__)
            else:
                self.stats.last_latency_ms = int((self._clock() - started) * 1000)
                self._record_headers(route_key, resp)
                body = self._parse_body(resp)
                if 200 <= resp.status_code < 300:
                    self.stats.last_ok = time.time()
                    self.stats.last_error = None
                    return body
                err = self._error_from_response(resp, body)
                if err.kind == "rate_limited":
                    self.stats.rate_limited += 1
                    name = resp.headers.get("X-RateLimit-Bucket") or self._route_bucket.get(route_key) or route_key
                    self._route_bucket[route_key] = name
                    self._bucket(name).blocked_until = self._clock() + (err.retry_after or 5.0)
                if err.kind == "auth":
                    self._invalid_key = self.server_key
                    self.stats.key_invalid_reason = err.message
                    self._cache.clear()
                last_exc = err
                if err.kind != "transient":
                    break
            if attempt < attempts - 1:
                await self._sleep(delay)
                delay = min(delay * 2, 8.0)
        assert last_exc is not None
        self.stats.failures += 1
        self.stats.last_error = {**last_exc.to_dict(), "at": time.time()}
        log.warning("ERLC API %s %s failed: %s (http=%s code=%s)", method, path, last_exc.kind,
                    last_exc.http_status, last_exc.api_code)
        raise last_exc

    # ---- public API -------------------------------------------------------------
    async def get_server(self, flags: tuple[str, ...] = ALL_FLAGS, *, use_cache: bool = True) -> ServerSnapshot:
        flags = tuple(f for f in ALL_FLAGS if f in set(flags))  # validated, de-duplicated (duplicates → 400)
        cache_key = "server:" + ",".join(flags)
        now = self._clock()
        if use_cache and cache_key in self._cache and now - self._cache[cache_key][0] < self.cache_ttl:
            return self._cache[cache_key][1]
        body = await self._request("GET", "/v2/server", "GET /v2/server", params={f: "true" for f in flags})
        try:
            snap = ServerSnapshot.model_validate(body)
        except ValidationError as exc:
            raise ErlcError("invalid_response", "The ERLC API returned data in an unexpected format.") from exc
        self._cache[cache_key] = (now, snap)
        return snap

    async def get_bans(self, *, use_cache: bool = True) -> list[dict[str, str]]:
        """``GET /v1/server/bans``. The docs describe an object keyed by player id."""
        now = self._clock()
        if use_cache and "bans" in self._cache and now - self._cache["bans"][0] < self.cache_ttl:
            return self._cache["bans"][1]
        body = await self._request("GET", "/v1/server/bans", "GET /v1/server/bans")
        bans: list[dict[str, str]] = []
        if isinstance(body, dict):
            bans = [{"id": str(k), "name": str(v)} for k, v in body.items()]
        elif isinstance(body, list):
            for item in body:
                if isinstance(item, dict):
                    bans.extend({"id": str(k), "name": str(v)} for k, v in item.items())
        else:
            raise ErlcError("invalid_response", "The ERLC API returned ban data in an unexpected format.")
        self._cache["bans"] = (now, bans)
        return bans

    @staticmethod
    def validate_command(command: str, blocked: list[str] | None = None) -> str:
        cmd = (command or "").strip()
        if not cmd:
            raise ErlcError("bad_request", API_ERROR_MESSAGES[3001])
        if "\n" in cmd or "\r" in cmd:
            raise ErlcError("bad_request", "Commands must be a single line.")
        if not cmd.startswith(":"):
            raise ErlcError("bad_request", "ERLC commands must start with ':' (for example ':h Hello').")
        if len(cmd) > MAX_COMMAND_LEN:
            raise ErlcError("bad_request", f"Command is too long (max {MAX_COMMAND_LEN} characters).")
        head = cmd.split()[0].lower()
        for b in blocked or []:
            if head == b.lower().strip():
                raise ErlcError("restricted", f"The command '{head}' is blocked by this community's settings.")
        return cmd

    async def run_command(self, command: str, blocked: list[str] | None = None) -> str:
        cmd = self.validate_command(command, blocked)
        async with self._command_lock:
            wait = COMMAND_SPACING - (self._clock() - self._last_command_at)
            if wait > 0:
                await self._sleep(wait)
            try:
                body = await self._request("POST", "/v2/server/command", "POST /v2/server/command",
                                           json={"command": cmd}, retries=0)
            finally:
                self._last_command_at = self._clock()
        self._cache.clear()
        return str(body.get("message", "Success")) if isinstance(body, dict) else "Success"

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "key_invalid": self.key_invalid,
            "key_invalid_reason": self.stats.key_invalid_reason if self.key_invalid else None,
            "requests": self.stats.requests,
            "failures": self.stats.failures,
            "rate_limited": self.stats.rate_limited,
            "last_ok": self.stats.last_ok,
            "last_error": self.stats.last_error,
            "last_latency_ms": self.stats.last_latency_ms,
            "buckets": {k: {"limit": b.limit, "remaining": b.remaining, "reset_at": b.reset_at,
                            "blocked": b.blocked_until > self._clock()} for k, b in self.stats.buckets.items()},
            "base_url": self.base_url,
        }
