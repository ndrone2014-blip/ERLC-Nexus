# ERLC Nexus — Feature completion report

Status key: ✅ complete · 🟡 partial (works, with the stated limitation) · ⬜ not implemented.
"Tested" refers to docs/TEST_REPORT.md.

## Platform & architecture (spec §2–3, §36–37)

| Requirement | Status | Notes |
|---|---|---|
| Bot, website, CAD/MDT sharing one backend & database | ✅ | Shared service layer + database; event outbox keeps them in sync. |
| Independent bot / website startup | ✅ | `start.bat web`, `start.bat bot`. |
| CAD records available without Discord | ✅ | Website works with the bot offline. |
| Browser never touches the database | ✅ | REST API only; permission checks server-side. |
| Automatic DB initialisation, Alembic migrations | ✅ | Run on install and every start; migration verified against models. |
| Structured logging, graceful shutdown, crash recovery | ✅ | JSON logs with redaction; launcher restarts crashed components (tested). |
| Async, non-blocking, caching, throttling, pagination | ✅ | |
| WebSocket reconnection | ✅ | Exponential back-off in the browser. |
| PostgreSQL compatibility | 🟡 | Built in, untested. |

## Official ERLC API (§4)

| Requirement | Status | Notes |
|---|---|---|
| Endpoint compatibility report | ✅ | docs/API_COMPATIBILITY.md |
| Server info, players, count, capacity, owner, identifiers, teams, permissions | ✅ | `GET /v2/server`. |
| Player locations (street, postal, coordinates) | ✅ | Official v2 `Location` field; shown on map labelled "API position". |
| In-game 911 calls → CAD | ✅ | Official `EmergencyCalls`; imported as pending, dispatcher decides. |
| Logs (join, kill, command, mod calls), queue, staff, vehicles | ✅ | Stored & deduplicated. |
| Commands, announcements, kick/ban/unban | ✅ | Via `POST /v2/server/command` (in-game admin commands; templates configurable). |
| Ban list | ✅ | `GET /v1/server/bans` (shape parsed defensively; docs are incomplete). |
| Player history | ✅ | Recorded by Nexus and labelled as such. |
| Auth, validation, timeouts, retries, rate limits, caching, structured errors, recovery | ✅ | Tested extensively. |
| Never retry requests that can't succeed | ✅ | Invalid keys stop all requests. |
| Never expose keys | ✅ | Tested across responses and logs. |
| Distinguish API / manual / calculated / unavailable data | ✅ | Source labels throughout (map, analytics notes, "Recorded by ERLC Nexus"). |
| Event webhooks | 🟡 | Signature verification complete; payload schema is undocumented so payloads are stored raw; polling stays the data source (as the docs advise). Off by default. |

## Website (§5–6)

| Requirement | Status | Notes |
|---|---|---|
| Visual identity (dark navy, charcoal, blue, restrained) | ✅ | Plus optional light theme and accent colour. |
| Every navigation item opens a working page | ✅ | 41 spec pages + extras (incident/record detail pages, map editor, profile, 911). All 56 routes browser-tested. |
| Overview: server stats, CAD stats, activity feed | ✅ | |
| Activity entries with user, time, record reference, department | ✅ | |
| Dashboard customisation (rearrange, hide, default page, theme, refresh) saved per user | ✅ | |

## CAD (§7–8)

| Requirement | Status | Notes |
|---|---|---|
| CAD workspace (left / centre / right panels, top bar) | ✅ | Dispatch Center. |
| Incident numbers `NX-YYYY-NNNNNN` | ✅ | Prefix configurable. |
| All incident fields (identification, caller, location, incident) | ✅ | |
| All 10 statuses, status changes recorded | ✅ | Statuses configurable. |
| Configurable priorities (name, description, colour, weight, notify) | ✅ | |
| Detailed incident timeline incl. previous/new values, kept after closure | ✅ | |
| Dispatch queue: sort, filter, search, assign, priority change, overdue alerts | ✅ | |
| No automatic dispatch | ✅ | |
| Units: all fields, multi-person, history, custom statuses, controls | ✅ | |
| Configurable callsign formats (not hardcoded) | ✅ | |
| Dispatcher console features & configurable/disable-able shortcuts | ✅ | |
| Dispatcher workload tracking (not used as a ranking) | ✅ | Listed alphabetically with a note. |

## Map (§9)

| Requirement | Status | Notes |
|---|---|---|
| Official ERLC map with incidents, units, traffic stops, players, locations | ✅ | Leaflet (bundled, BSD-2). |
| Zoom, pan, search, select, filter, details, create incident from location | ✅ | Right-click menu. |
| Custom markers / marker colours | ✅ | |
| Map editor: add, rename, move (drag), categorise, describe | ✅ | |
| Distinguish API vs manual unit positions | ✅ | Solid vs hollow markers + labels. |
| Manual locations, presets, unit-reported locations | ✅ | |
| Upload map assets / custom marker icons | 🟡 | Choose between the official map images; custom image upload and per-category icon images are not implemented (markers use category colours). |
| Coordinate accuracy | 🟡 | Scale isn't published by PRC → two-point calibration tool using live API positions. Starter locations are approximate and marked unverified. |

## MDT, records, BOLOs, traffic, warrants, reports (§10–16)

| Requirement | Status | Notes |
|---|---|---|
| Separate MDT interface with all listed sections | ✅ | 10 sections incl. unit-to-dispatch messaging. |
| MDT respects permissions; no admin controls | ✅ | |
| Person records & search (name, alias, number, vehicle, Discord ID with permission) | ✅ | Searchable fields configurable. |
| Vehicle records & search (full/partial plate, owner, make, model, colour, registration) | ✅ | |
| BOLOs: types, fields, statuses, search, notifications, history, editing, expiry alerts | ✅ | |
| Traffic stops: fields, statuses, officer & dispatcher actions | ✅ | |
| Warrants & cases with audit history and access restrictions | ✅ | |
| Fictional-record labelling | ✅ | Configurable disclaimer on every record page and bot embed. |
| Reports: all fields, statuses, drafts, review, comments, revisions, search, export | ✅ | |
| Report export format | 🟡 | Plain-text download and browser print view (PDF via "Print → Save as PDF"); no native PDF generator. |
| Report templates | ✅ | Editable, with custom fields. |

## Departments & operations (§17–23)

| Requirement | Status | Notes |
|---|---|---|
| Fire, law enforcement, DOT, civilian operations | ✅ | Department types with their own unit types, incident categories and report templates. |
| Department management (name, abbreviation, logo, colour, ranks, roster, supervisors, callsigns, units, stats) | ✅ | Logos are URLs (no file upload). |
| Personnel profiles with shift & department history | ✅ | |
| Rank management (create, rename, delete, reorder, permissions, supervisory) | ✅ | |
| Shifts: clock in/out, department/callsign/unit, notes, approval, history, weekly/monthly hours | ✅ | |
| No duplicate shifts, restart-safe, actual vs edited time, audit trail | ✅ | Tested. |
| Dispatch communications feed with Discord sync | 🟡 | Website → Discord mirroring works; messages typed in a Discord channel are not imported into the website feed. |

## Discord bot (§24–25)

| Requirement | Status | Notes |
|---|---|---|
| All listed command areas | ✅ | 74 commands (12 groups + 2 context menus); see docs/COMMANDS.md for the mapping. |
| Descriptions, permissions, validation, useful responses, error handling, audit | ✅ | |
| No duplicate commands | ✅ | Overlapping spec names were given distinct purposes (documented). |
| Buttons, selects, modals, embeds, context menus, interactive panels | ✅ | Plus auto-refreshing live panels. |
| Expiry handling; others can't use your buttons | ✅ | Tested. |

## Logging, analytics, search, notifications, customisation, permissions (§26–31)

| Requirement | Status | Notes |
|---|---|---|
| Logging categories and fields; searchable audit log; protected against modification | ✅ | Hash-chained, integrity check in the UI. |
| Server / CAD / department / dispatch analytics; daily/weekly/monthly/custom; CSV; print | ✅ | Derived values labelled. |
| Central search with filters, date ranges, history | ✅ | |
| Notification engine (website + Discord, channels, preferences, department scoping, anti-spam) | ✅ | |
| Customisation of every listed item with sensible defaults | ✅ | Marker icons see Map row. |
| Default roles, custom roles, granular permissions, backend enforcement, least privilege | ✅ | |

## Data, security, free software, installation (§32–35)

| Requirement | Status | Notes |
|---|---|---|
| All required entities, foreign keys, indexes, transactions, migrations | ✅ | 49 tables. |
| Backup & restore, documented | ✅ | Tested. |
| Soft deletion / archival | ✅ | |
| Security list (OAuth, sessions, CSRF, validation, escaping, SQLi, rate limits, key storage, expiry, admin security page) | ✅ | docs/SECURITY.md |
| 100% free, no paid dependencies, local Windows hosting | ✅ | MIT licence; all dependencies open source. |
| install.bat / start.bat / stop.bat / config.env.example / requirements.txt / README.md | ✅ | Batch files not executed on Windows during development (see test report). |
| Installer never overwrites configuration | ✅ | Tested. |

## Extras beyond the specification

* Live player positions and automatic unit positions from the official API (for members with a linked Roblox account).
* Map calibration tool using real players as reference points.
* Drag-and-drop unit assignment.
* Auto-refreshing Discord live panels (`/nexus panel`).
* "Create CAD incident" from any Discord message.
* Plate checks that combine registration, flags and active BOLOs in one alert.
* Tamper-evident (hash-chained) audit log.
* Launcher with automatic crash recovery and staged, verified restores.
* **`start-online.bat`: one-click public `https://` link** for the self-hosted website via free
  Cloudflare Tunnel (auto-download, Discord redirect copied to the clipboard, reconnects, optional
  permanent address). Real-tunnel connection untested — see TEST_REPORT.md.
* Proxy-aware visitor IPs (`TRUST_PROXY`) for rate limits, login records and the audit log.
* Linux/macOS scripts and a deployment guide.
