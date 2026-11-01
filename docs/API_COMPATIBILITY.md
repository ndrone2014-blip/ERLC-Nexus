# ERLC Nexus — Official PRC API Compatibility Report

Source of truth: the official ER:LC Private Server API documentation at
<https://apidocs.erlc.gg> (reviewed 2026-11-01). Nothing in ERLC Nexus uses an
endpoint, field, or capability that is not listed below.

> **Domain migration.** PRC moved the API from `api.policeroleplay.community`
> to **`https://api.erlc.gg`** with no further grace period. ERLC Nexus uses the
> new domain by default (`ERLC_API_BASE_URL`).

## Authentication

| Header | Required | Purpose |
|---|---|---|
| `server-key` | Yes, every request | Private server key (in-game Settings → ER:LC API, or `erlc.link/sk`). Requires the ERLC API server pack. |
| `Authorization` | No | Global key for *public applications* serving many servers. Self-hosted single-community installs do not need it. |

ERLC Nexus stores the server key in `config.env` or, if set from the dashboard,
encrypted at rest (Fernet, key derived from `SECRET_KEY`). It is never returned
by any API route, logged, or rendered in the browser.

## Endpoints

| # | Endpoint | Method | Params / Body | Response (used fields) | Errors | Used by Nexus for |
|---|---|---|---|---|---|---|
| 1 | `/v2/server` | GET | Optional boolean query flags: `Players`, `Staff`, `JoinLogs`, `Queue`, `KillLogs`, `CommandLogs`, `ModCalls`, `EmergencyCalls`, `Vehicles`. Duplicate flags → 400. | Always: `Name`, `OwnerId`, `CoOwnerIds[]`, `CurrentPlayers`, `MaxPlayers`, `JoinKey`, `AccVerifiedReq`, `TeamBalance`. Flagged: see below. | 400 `{code,message}` (e.g. 2001), 403, 500 `{error,code}` (e.g. 1001) | **Primary sync call.** One request per sync cycle fetches everything below. |
| 2 | `/v2/server/command` | POST | JSON `{"command": "<string>"}` | 200 `{"message":"Success"}` | 400 (missing command), 403, 422 server offline/no players (`commandId`), 500 Roblox error (`commandId`) | `/server command`, announcements (`:h`, `:m`), kick/ban/unban, website Server Commands page. |
| 3 | `/v1/server/bans` | GET | — | Ban data (documented as object keyed by player id → name) | 403 | Ban list on Server Moderation page. Parsed defensively because the docs do not fully specify the shape. |
| 4 | `/v1/server` and other `/v1/server/*` reads | GET | — | Same data as v2 split per route | 403 | **Not used.** v2 `/v2/server` supersedes them in a single request (fewer requests = kinder to rate limits). |

### `/v2/server` flagged fields

| Flag | Field | Shape | Nexus feature |
|---|---|---|---|
| `Players` | `Players[]` | `Player` ("Name:Id"), `Team`, `Callsign` (nullable), `Permission`, `WantedStars`, `Location{LocationX, LocationZ, PostalCode, StreetName, BuildingNumber}` | Live Players, Player Search, team distribution, **live map positions**, unit auto-location (opt-in, matched by linked Roblox ID). |
| `Staff` | `Staff{Admins, Mods, Helpers}` | maps of Roblox id → username | Server Overview staff list. |
| `JoinLogs` | `JoinLogs[]` | `Join` (bool), `Timestamp`, `Player` | Activity feed, player history. |
| `Queue` | `Queue[]` | Roblox ids | Queue size on Server Overview. |
| `KillLogs` | `KillLogs[]` | `Killed`, `Killer`, `Timestamp` | Server log viewer. |
| `CommandLogs` | `CommandLogs[]` | `Player`, `Command`, `Timestamp` | Server log viewer, moderation audit. |
| `ModCalls` | `ModCalls[]` | `Caller`, `Moderator` (nullable), `Timestamp` | Server Moderation page, Discord notification. |
| `EmergencyCalls` | `EmergencyCalls[]` | `Team`, `Caller` (Roblox id), `Players[]`, `Position[2]`, `StartedAt`, `CallNumber`, `Description`, `PositionDescriptor` | **In-game 911 calls → CAD.** Imported as *pending* CAD calls labelled "Source: ERLC API". Dispatchers decide whether to create an incident (never auto-dispatched). |
| `Vehicles` | `Vehicles[]` | `Name`, `Owner`, `Plate`, `Texture`, `ColorHex`, `ColorName` | Live spawned-vehicle list; plate cross-check against BOLOs and vehicle records. |

## Location data

* `0,0` is the map centre; `+X` = right, `+Z` = **down** (official doc
  "Interpreting API Location Data").
* Official map images are 5355×5355 px (`https://api.erlc.gg/maps/fall_postals.png`
  etc.). The docs do **not** publish the game-unit span of the image, so Nexus
  ships a configurable **map calibration** (scale + offset, editable in the
  Map Editor with a two-point calibration tool) rather than inventing a
  conversion constant. Until calibrated, the default assumes the origin at the
  image centre with 1 game unit = 1 px, and the map shows a "calibration
  unverified" badge.
* API-sourced positions are drawn with a solid marker and labelled
  "API position"; manually entered unit locations use a hollow marker labelled
  "Manual". Unit positions are only derived from the API when an administrator
  links a personnel profile to a Roblox ID **and** that player is in the server.

## Rate limits (official)

| Bucket | Rule |
|---|---|
| `global` | Per application (authenticated) per second; limit varies. |
| `unauthenticated-global` / `unauthenticated-server` | Lower limits per IP and per server key at the same time. |
| `command` | `POST /command`: **1 request / 5 s** (subject to change). |
| `invalid-requests-server` / `invalid-requests` | Repeated 400/401/403/404 → temporary block (429, code 4001). |

Headers: `X-RateLimit-Bucket`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset` (epoch). 429 responses include `Retry-After` and a JSON
`retry_after`.

**How Nexus complies** (`nexus/erlc/client.py`):

* Tracks every bucket from response headers and waits *before* sending when a
  bucket is exhausted.
* On 429, honours `Retry-After` for the whole bucket and never retries early.
* Serialises commands per server key with a 5 s minimum spacing.
* Retries only transient failures (network errors, 500/code 1001) with
  exponential back-off and a cap; **never** retries 400/403/422 or code 2xxx/4xxx.
* After a 403 or codes 2002/2004 the key is marked *invalid* and all calls stop
  until an administrator updates it (protects against the invalid-request block
  and permanent IP bans described in the docs).
* Responses are cached (default 15 s TTL) and only one process (the sync
  "leader", elected through a database lease) polls the API, so running the bot
  and website together never doubles the request rate.
* No IP rotation, no proxies.

## Error codes handled

| Code | Meaning | Nexus behaviour |
|---|---|---|
| 0 | Unknown | Logged, surfaced as "Unknown ERLC API error". |
| 1001 | Roblox communication failure | Transient → retry with back-off. |
| 1002 | Internal error | Transient → retry with back-off. |
| 2000–2002 | Missing / malformed / invalid key | Key marked invalid, sync paused, admin alerted. |
| 2003 | Invalid global key | Global key marked invalid. |
| 2004 | Server key banned | Key marked invalid, sync stopped. |
| 2005 | Multi-server unauthenticated | Explained to admin (use a public application key). |
| 3001 | Missing command | Validation error shown to user (also pre-validated). |
| 3002 | Server offline (no players) | "Server is empty/offline" shown; not retried. |
| 4000 | Not permitted | Shown to user, not retried. |
| 4001 | Rate limited / blocked | Bucket paused for `Retry-After`. |
| 4002 | Command restricted | Shown to user. |
| 4003 | Prohibited message | Shown to user. |
| 9998 | Resource restricted | Shown to user. |
| 9999 | In-game module outdated | Admin alert with the documented fix (kick all players and retry). |

## Event webhooks (optional)

The game can POST Ed25519-signed events (`;` chat commands and emergency calls)
to an HTTPS URL. Nexus exposes `POST /api/erlc/webhook`, which verifies
`X-Signature-Ed25519` over `X-Signature-Timestamp + raw body` with the official
public key and rejects everything else. Because the payload schema is not
published, verified payloads are stored raw in the audit log and emergency calls
are **still sourced from polling `EmergencyCalls`** (the docs state webhooks do
not replace polling). A locally hosted install is usually not reachable from the
internet, so this is disabled by default.

## Things the API does **not** provide (and how Nexus handles them)

| Not provided | Nexus approach |
|---|---|
| Kick/ban/unban endpoints | Sent as in-game admin commands (`:kick`, `:ban`, `:unban`) through `/v2/server/command`; command templates are configurable. |
| Player history across sessions | Built by Nexus from its own join-log and moderation records (labelled "Recorded by ERLC Nexus"). |
| Historical player counts | Collected by Nexus at each sync (labelled "collected since install"). |
| Map coordinate scale | Admin calibration (see above). |
| Event webhook payload schema | Stored raw; polling remains the data source. |
| Person/vehicle registration records | Manually entered fictional roleplay records. |

## Acceptable Use notes honoured

* Keys kept out of repositories and client code; rotate from the dashboard.
* `:pm` is not used for routine notifications.
* Stop using a server key immediately when removed (sync disabled + key cleared
  from System → API Configuration).
