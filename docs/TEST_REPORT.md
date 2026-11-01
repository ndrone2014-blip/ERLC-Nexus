# ERLC Nexus — Test report

Version 1.0.0 · run on 2026-11-01 · Python 3.13 (Linux build environment)

This report only claims what was actually executed. Anything not tested is listed under
**Not tested** — please read that section before relying on those parts.

## Summary

| Suite | Result |
|---|---|
| Automated tests (`pytest`) | **103 passed, 0 failed** |
| Static analysis (`ruff`, pyflakes rules + syntax) | **0 issues** |
| Browser check — every website route loaded in headless Chrome | **56/56 routes rendered with no JavaScript errors** |
| Browser workflow — dispatcher flow driven through the real UI | **Passed** |
| Installer steps 5–10 (`scripts/setup.py`) on a clean copy | **Passed** (idempotent; existing `config.env` preserved) |
| Launcher (`run.py`): start → health → stop | **Passed** (graceful shutdown) |
| Launcher crash recovery (website process killed) | **Passed** (restarted automatically) |

Run the suite yourself: `.venv\Scripts\python.exe -m pytest` (needs `requirements-dev.txt`).

## Automated tests by area

| File | Tests | What is covered |
|---|---|---|
| `test_erlc_client.py` | 19 | `server-key` / `Authorization` headers, all 9 documented flags (deduplicated), parsing of every documented response field incl. `Location` and `EmergencyCalls`, caching, **403 → key marked invalid and no further requests**, key change resets state, **429 honours `Retry-After` per bucket**, long blocks aren't waited inline, transient 5xx/1001 retries with back-off, 400 never retried, network timeouts, malformed responses, mapping of documented error codes (2005, 3001, 3002/422, 4000, 4002, 9999), command validation and **5-second command spacing**, bans parsing, missing key, status never contains the key, log redaction. |
| `test_sync.py` | 7 | Snapshot caching, join/kill/command/mod-call log storage and deduplication, player online/offline tracking, **in-game 911 calls imported as pending (no automatic incidents)**, unit position from API for linked Roblox members, failure recording + admin notification, no requests without a key, exclusive sync leader lease. |
| `test_cad.py` | 12 | Incident numbering, validation, full status workflow and **timeline events**, closure clears units, reopen keeps history, double/closed assignment rejected, reassignment clears previous incident, **officer permission limits**, officer self-service on own unit, callsign formats and uniqueness, overdue queue flags, 911 → Pending Dispatch, accept/dismiss API calls, restricted notes hidden. |
| `test_records.py` | 11 | Person/vehicle CRUD with revisions, plate normalisation and duplicates, soft archive, plate-check alerts (registration, flags, BOLO), BOLO lifecycle and **automatic expiry**, warrants & restricted cases, traffic-stop lifecycle and ownership, **civilian ownership scoping**, permission-aware central search + history, Discord-ID lookup permission, record links. |
| `test_reports_shifts_departments.py` | 9 | Report draft → submit → return (comment required) → edit → resubmit → approve with **every revision preserved**, report access rules, no self-review; shifts: duplicate prevention in code **and** at the database level, **active shift survives a restart**, adjustments keep actual vs credited time (reason required), approval; departments: ranks create/delete/reorder, promotion history, callsign uniqueness, **supervisor scope limited to own department**. |
| `test_platform.py` | 10 | Permission wildcards, least-privilege default roles, config parsing and secret masking, **Discord role → Nexus role mapping** (and ignored for other guilds), Owner protections, settings validation, **audit hash chain detects tampering**, notification grouping/audiences/read state, **backup → stage → apply restore** (incl. path traversal rejection), **migration creates exactly the model schema**. |
| `test_api.py` | 19 | Login required, **CSRF enforced**, security headers, every read endpoint returns 200 for an owner (68 endpoints), **ERLC key never appears in any response**, dashboard key is tested and stored encrypted, **403 for lower roles across admin/CAD/records/commands**, role headers from the browser ignored, dev-login disabled / cross-site refused, **Discord OAuth flow** (state check, token exchange, guild roles, least privilege), logout revokes session, WebSocket auth + per-permission event filtering, outbox → WebSocket delivery, **Ed25519 webhook verification**, webhook disabled by default, friendly validation errors, ERLC errors mapped to HTTP codes, full CAD → report → CSV flow over HTTP. |
| `test_bot.py` | 11 | All 12 command groups + 2 context menus register with the expected subcommands, payloads valid for Discord (description lengths, option order, ≤100 commands), Discord roles → permissions in the bot, `/cad 911` modal creates a pending incident, permission-denied message, `/shift start` and `/shift end`, owner-locked views reject other users, views disable on timeout, user-safe error messages, notifier embeds for every event type, live panels render. |
| `test_web.py` | 5 | Index and assets served, every router entry points at an existing page export, every navigation item from the specification exists, no `innerHTML` usage, only local scripts. |

## Browser checks (headless Chrome, live server, ERLC API mocked with documented payloads)

* All 56 routes (Overview through System Health, plus the 10 MDT sections) loaded and
  rendered with **zero JavaScript exceptions or console errors**. The only network error
  was the official map image, which the build sandbox could not download; on a normal PC
  the installer downloads it (or the browser loads it from `api.erlc.gg`).
* Workflow driven through the actual UI: register a unit via the modal → accept the in-game
  911 call in the Dispatch Center → assign the unit → send a dispatch message → add a note
  on the incident page → create a person record → open the live map (12 markers drawn).
  All steps succeeded and updated live over the WebSocket.

## Bugs found and fixed during testing

* WebSocket clients couldn't be tracked (unhashable record) → live updates failed to connect.
* Local login didn't reload the app after signing in (fragment-only navigation).
* Case/warrant revision history failed to save timestamps (JSON serialisation).
* Traffic stops didn't fill the driver from a vehicle's owner name.
* A promotion didn't refresh the member's cached rank.
* The default Supervisor role was missing department-scoped personnel management.
* Icon sizing and widget styling issues found in screenshots.

## Not tested (be aware)

| Area | Status |
|---|---|
| `install.bat`, `start.bat`, `stop.bat` on Windows | **Not executed** — the build environment is Linux. The Python steps they call were tested (installer, launcher start/stop/restart). Windows-specific pieces (Python detection via `py`, `CTRL_BREAK` shutdown signal) are untested. Please report any issue. |
| Live Discord gateway | Not tested with a real bot token. Commands, payloads, permission resolution and several callbacks were tested with simulated interactions. |
| Live ERLC API | Not tested with a real server key. All behaviour was tested against responses shaped exactly like the official documentation (apidocs.erlc.gg). |
| Discord OAuth against discord.com | Tested with a mocked Discord API (full flow), not the real service. |
| PostgreSQL | Supported by the data layer but not tested; SQLite was used for all tests. |
| Map coordinate accuracy | The official docs don't publish the map scale; positions depend on the in-app calibration. |
| Load / performance | No load testing. Queries are indexed and paginated; one API request per sync interval. |
| Accessibility audit, mobile devices | Responsive layout checked only at desktop size in headless Chrome. |
