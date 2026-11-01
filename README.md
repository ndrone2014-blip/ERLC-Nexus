# ERLC Nexus

**One platform. The entire ERLC operation. 100% free.**

ERLC Nexus is a free, self-hosted management platform for *Emergency Response: Liberty County* communities. It combines a Discord bot, a full Computer-Aided Dispatch (CAD) system, an officer Mobile Data Terminal (MDT), a records system and a professional web dashboard — all sharing one database, all running on your own computer.

- **No premium tier, no subscriptions, no ads, no locked features.** Every feature is available to everyone.
- **Official ERLC API only.** Live data comes from the official PRC API (`api.erlc.gg`). Nothing is faked; every piece of data is labelled with where it came from.
- **Runs on Windows** with three double-click scripts. Linux/macOS scripts are included too.

> Developed by Drone Hive Studios | Developer @ndrone40

---

## Contents

1. [What's included](#whats-included)
2. [Requirements](#requirements)
3. [Install on Windows](#install-on-windows)
4. [Configure Discord](#configure-discord)
5. [Configure the ERLC API](#configure-the-erlc-api)
6. [First login and setup](#first-login-and-setup)
7. [Everyday use](#everyday-use)
8. [Discord commands](#discord-commands)
9. [How it works](#how-it-works)
10. [Backups](#backups)
11. [Updating](#updating)
12. [Troubleshooting](#troubleshooting)
13. [Hosting elsewhere (optional)](#hosting-elsewhere-optional)
14. [Project layout](#project-layout)
15. [Development & tests](#development--tests)

Further documentation lives in [`docs/`](docs):
[API compatibility report](docs/API_COMPATIBILITY.md) ·
[Feature completion report](docs/FEATURES.md) ·
[Test report](docs/TEST_REPORT.md) ·
[Security](docs/SECURITY.md) ·
[Backups](docs/BACKUP.md) ·
[Deployment](docs/DEPLOYMENT.md) ·
[Discord commands](docs/COMMANDS.md)

---

## What's included

| Area | Highlights |
|---|---|
| **ERLC server** | Live server status, players (team, callsign, permission, wanted stars, **street & postal location**), staff, queue, spawned vehicles, join/kill/command logs, mod calls, bans, kick/ban/unban, in-game commands and announcements — all through the official API. |
| **CAD** | Incidents with numbered IDs (`NX-2026-000001`), configurable priorities/statuses/categories, full event timeline, dispatch queue with waiting timers and overdue alerts, unit management, drag-and-drop assignment, dispatcher notes, restricted notes, linked records. |
| **In-game 911** | 911 calls made in-game are imported from the official API into the Dispatch Center as *pending* calls. A dispatcher decides whether to create an incident — nothing is auto-dispatched. |
| **Live map** | The official ERLC map with incidents, units, traffic stops and live player positions. API positions and manually-entered positions look different and are labelled. Map editor + two-point calibration tool. |
| **MDT** | A separate, simpler officer interface: big status buttons, assigned calls, quick person/plate checks, BOLOs, traffic stops, reports, shift. |
| **Records** | Persons, vehicles, BOLOs (auto-expiry), warrants, cases, traffic stops — searchable, linkable, with full change history. All clearly marked as fictional roleplay records. |
| **Reports** | Templates with custom fields, drafts, supervisor review (approve / return with comments), immutable revision history, export and print. |
| **Departments** | Unlimited departments with custom ranks, callsign formats, unit types, colours, logos, rosters, personnel profiles and history. |
| **Shifts** | Clock in/out from Discord or the website, restart-safe, no duplicate shifts, supervisor approval and audited time adjustments (actual vs credited time kept separately). |
| **Analytics** | Server, CAD, department, dispatcher and activity reports with date ranges, CSV export and print views. |
| **Discord bot** | 74 commands in 12 groups + 2 context menus, interactive panels, modals, auto-refreshing live panels, channel notifications, dispatch-comms sync. |
| **Administration** | Role-based permissions (40+ granular permissions, Discord role mapping), customization of every list, searchable tamper-evident audit log, security page, backups, health page. |

## Requirements

- **Windows 10/11** (or Linux/macOS)
- **Python 3.12 or newer** — <https://www.python.org/downloads/> (tick **"Add python.exe to PATH"** while installing)
- A **Discord application** with a bot (free) — <https://discord.com/developers/applications>
- An **ERLC private server** with the **ERLC API server pack** for live server data

Everything else is installed automatically. No paid services are needed.

> **Important:** ERLC Nexus runs on *your* computer. When the computer is off, asleep or the ERLC Nexus window is closed, the website and bot are offline. See [Hosting elsewhere](#hosting-elsewhere-optional) if you want it online 24/7.

## Install on Windows

1. Download this repository (green **Code** button → **Download ZIP**) and extract it, e.g. to `C:\ERLC-Nexus`.
2. Double-click **`install.bat`**. It will:
   1. find Python, 2. check it's 3.12+, 3. create a virtual environment, 4. install dependencies,
   5. create the `data` folders, 6. create `config.env` (with a random `SECRET_KEY`) if it doesn't exist,
   7. create the database and run migrations, 8. download the official map images,
   9. check your configuration, 10. show the results.
   It never overwrites an existing `config.env`.
3. Open **`config.env`** in Notepad and fill it in (next two sections).
4. Double-click **`start.bat`**. Keep the window open. Open the website address it prints (default <http://localhost:8420>).
5. To stop, press **Ctrl+C** in that window or double-click **`stop.bat`**.

`start.bat web` starts only the website, `start.bat bot` only the bot.

## Configure Discord

In the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**:

1. **General Information** → copy the **Application ID** → `DISCORD_APPLICATION_ID`.
2. **Bot** → **Reset Token** → copy it → `DISCORD_BOT_TOKEN`. No privileged intents are needed.
3. **OAuth2** → copy the **Client Secret** → `DISCORD_CLIENT_SECRET`.
4. **OAuth2 → Redirects** → add `http://localhost:8420/auth/callback` (or your `PUBLIC_URL` + `/auth/callback`).
5. In Discord, enable *Settings → Advanced → Developer Mode*, right-click your server → **Copy Server ID** → `DISCORD_GUILD_ID`. (Commands then appear instantly, and member roles are read from this server.)
6. Right-click your own name → **Copy User ID** → `INITIAL_ADMIN_DISCORD_ID`. That account becomes **Owner**.
7. Start ERLC Nexus, open **System → Discord Integration** and click **Invite the bot to your server**.

## Configure the ERLC API

In-game on your private server open **Settings → ER:LC API** (requires the ERLC API server pack) and copy the **server key**. Either:

- paste it into `config.env` as `ERLC_SERVER_KEY`, **or**
- sign in to the website → **System → API Configuration** → paste → **Test & save** (the key is tested against the official API and stored encrypted).

ERLC Nexus makes one request per sync (default every 20 s) and follows every documented rate-limit rule. If the key is rejected it stops sending requests immediately to protect your key and IP. Full details: [docs/API_COMPATIBILITY.md](docs/API_COMPATIBILITY.md).

## First login and setup

1. Open the website and click **Sign in with Discord**. (Before Discord login is configured you can set `DEV_LOGIN=true` to sign in locally as `INITIAL_ADMIN_DISCORD_ID` — turn it off afterwards.)
2. **System → Permissions** — map your Discord roles to Nexus roles (Owner, Administrator, Command Staff, Supervisor, Dispatcher, Officer, Fire, DOT, Civilian, Viewer) or create your own. New users get **no access** until a role is assigned (least privilege).
3. **Departments** — six starter departments are created (Sheriff, Police, Fire, DOT, Communications, Civilian). Rename them, edit ranks and callsign formats, or create new ones.
4. **Map editor** (CAD → Live Map → Map editor) — starter locations are placed approximately and marked *unverified*; drag them into place. Use **Calibration** to line API positions up with the map image.
5. **System → Discord Integration** — choose channels for notifications (new incidents, BOLOs, shift events, in-game 911 calls, API problems…).
6. **System → Appearance & Customization** — community name, logo, colours, priorities, statuses, categories, unit statuses, report templates and more. Defaults are sensible, so this is optional.

## Everyday use

- **Dispatchers** use **CAD → Dispatch Center**: incoming in-game 911 calls on top, the priority queue in the middle, the unit board and dispatch comms on the right. Drag a unit onto an incident to assign it. Keyboard shortcuts (Alt+N new incident, Alt+S search…) are customizable.
- **Officers** use the **MDT** (`/#/mdt` or `/mdt panel` in Discord): set status with one click, see assigned calls, run plates and people, start traffic stops, write reports.
- **Civilians** can call 911 (`/cad 911` or the website) and manage their own characters and vehicles.
- **Supervisors** review reports, approve shifts and manage personnel in their department.
- **Everyone** can link their Roblox account in their profile — units then show their real in-game position on the map (from the official API) while the player is in the server.

## Discord commands

| Group | Subcommands |
|---|---|
| `/server` | panel · info · status · players · player · refresh · command · announcement |
| `/player` | panel · search · info · kick · ban · unban · history |
| `/cad` | panel · 911 · incident · incidents · close · reopen · assign · history |
| `/dispatch` | panel · create · assign · update · close · queue |
| `/unit` | panel · register · status · assign · remove · list · history |
| `/mdt` | panel · person · vehicle · bolo · traffic-stop · report |
| `/bolo` | create · search · update · close · list |
| `/record` | person · vehicle · search · update · history |
| `/report` | create · submit · view · search · review |
| `/department` | panel · info · roster · stats · ranks |
| `/shift` | start · end · status · history · stats |
| `/nexus` | help · status · dashboard · link-roblox · panel |
| Context menus | **Nexus profile** (on a member) · **Create CAD incident** (on a message) |

Commands are grouped (`/server info` rather than `/server-info`) to keep Discord's command list tidy. See [docs/COMMANDS.md](docs/COMMANDS.md) for what each one does and how it maps to the original specification.

## How it works

```
                 ┌────────────── shared SQLite / PostgreSQL database ──────────────┐
                 │  records · CAD · shifts · settings · audit log · event outbox    │
                 └───────────▲──────────────────────────────────────▲──────────────┘
                             │                                      │
   Browser ◄──HTTPS/WS──► Website process                    Discord bot process ◄──► Discord
                          (FastAPI, REST + WebSockets)        (discord.py)
                             │        ▲                             │
                             └── ERLC sync (one leader) ──► api.erlc.gg (official PRC API)
```

- The **website** and **bot** are separate processes that share the database and the same service layer. Either can run alone.
- Changes made anywhere are written to an **event outbox** in the database; the website pushes them to browsers over WebSockets and the bot posts them to Discord. That's how Discord and the website stay in sync.
- Only one process (the "sync leader", elected through the database) polls the ERLC API, so running both never doubles your API usage.
- The **launcher** (`start.bat` → `run.py`) validates configuration, applies staged restores, runs migrations, starts both components, restarts them if they crash, and shuts down cleanly.
- Records stored in Nexus stay available when the ERLC API or Discord is down.

## Backups

**System → Database → Create backup** makes a verified copy in `data/backups` (safe while running). **Restore** stages a backup; it's applied the next time you run `start.bat`, after saving your current database. Command line: `python scripts\backup.py create|list|restore <file>`. Records are never hard-deleted through the interface — they are archived. Details: [docs/BACKUP.md](docs/BACKUP.md).

## Updating

1. Run `stop.bat`. 2. Make a backup (copy the `data` folder). 3. Replace the program files with the new version (keep `config.env` and `data`). 4. Run `install.bat` again (it updates dependencies and the database schema; your config is untouched). 5. Run `start.bat`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Python 3.12 or newer was not found` | Install Python from python.org and tick *Add python.exe to PATH*. |
| Website says *Discord login isn't configured* | Fill `DISCORD_APPLICATION_ID` and `DISCORD_CLIENT_SECRET`, add the redirect URL in the Developer Portal, restart. |
| Signed in but see almost nothing | Your account has no role yet. The Owner assigns roles in **System → Permissions** (or maps your Discord role). |
| Slash commands don't appear | Set `DISCORD_GUILD_ID` for instant sync; global sync can take up to an hour. Make sure the bot was invited with the `applications.commands` scope (use the invite button). |
| *ERLC API rejected the server key* | The key was regenerated or mistyped. Paste the current key in **System → API Configuration**. |
| *Private server is offline* | The ERLC API reports the server as offline when it has no players; commands need at least one player in the server. |
| Map positions are offset | Use the **Calibration** tool in the map editor. |
| Something else | Check **System → System Health** and **System → Logging → Application logs**, or the files in `data/logs`. |

## Hosting elsewhere (optional)

You can run ERLC Nexus on any machine that runs Python (a spare PC, a VPS, etc.) using `install.sh` / `start.sh`. Third-party hosting, domains and certificates are **your choice and are not guaranteed to be free**. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for reverse-proxy, HTTPS and PostgreSQL notes.

## Project layout

```
nexus/            Python package (shared by website and bot)
  api/            FastAPI app, routes, WebSocket hub
  bot/            Discord bot, cogs (command groups), panels, notifier
  core/           permissions, audit chain, event outbox, settings, numbering
  db/             models, engine, Alembic migrations
  erlc/           official ERLC API client + background sync
  services/       business logic (CAD, records, reports, shifts, analytics…)
web/              website (no build step): index.html, css, js modules, vendored Leaflet
scripts/          installer steps, map image download, backup CLI
tests/            automated test suite (pytest)
docs/             reports and guides
run.py            launcher / supervisor
install.bat start.bat stop.bat   Windows scripts (install.sh start.sh stop.sh for Linux/macOS)
config.env.example               configuration template
```

## Development & tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest                                               # 103 tests
```

The website is plain ES modules — edit files in `web/` and refresh. The REST API is documented at `/api/docs` while the website is running.

## License

MIT — see [LICENSE](LICENSE). Leaflet (BSD-2-Clause) is bundled in `web/vendor/leaflet`. Map imagery is the official ERLC map provided by the Police Roleplay Community and is downloaded from `api.erlc.gg`, not redistributed. ERLC Nexus is an independent project and is not affiliated with or endorsed by Police Roleplay Community or Roblox.
