# Discord command reference

All commands check permissions on the server. Responses that contain records are only
visible to you (ephemeral) unless noted. Interactive buttons only work for the person who
ran the command and expire after a few minutes.

The specification listed commands as flat names (`/server-info`, `/cad-911`, …). ERLC Nexus
groups them (`/server info`, `/cad 911`) as the spec asked for "logical slash-command
groups"; the table shows the mapping. The bare names (`/server`, `/cad`, `/mdt` …) became
each group's interactive **panel** subcommand.

| Spec name | Command | What it does | Permission |
|---|---|---|---|
| /server | `/server panel` | Live server card with Refresh and Players buttons (public) | erlc.server.view |
| /server-info | `/server info` | Name, owner, capacity, join code, verification, teams | erlc.server.view |
| /server-status | `/server status` | Server + API connection status, last sync, last error | erlc.server.view |
| /server-players | `/server players [team]` | Players grouped by team with callsign and street | erlc.server.view |
| /server-player | `/server player <name>` | Live lookup of a player in the server | erlc.server.view |
| /server-refresh | `/server refresh` | Fetch fresh data from the API now (15 s cooldown) | erlc.server.view |
| /server-command | `/server command <command>` | Run an in-game command (e.g. `:h Hello`) | erlc.server.command |
| /server-announcement | `/server announcement <message> [style]` | In-game hint or full-screen message | erlc.server.announce |
| /player | `/player panel <name>` | Player card with Kick / Ban / History buttons | erlc.server.view (+moderate for buttons) |
| /player-search | `/player search <query>` | Partial name / callsign search in the server | erlc.server.view |
| /player-info | `/player info <name>` | Live info + history recorded by Nexus | erlc.server.view |
| /player-ban | `/player ban <name> [reason]` | Ban (with confirmation) | erlc.server.moderate |
| /player-kick | `/player kick <name> [reason]` | Kick | erlc.server.moderate |
| /player-unban | `/player unban <name>` | Unban | erlc.server.moderate |
| /player-history | `/player history <name>` | Moderation history recorded by Nexus | erlc.server.view |
| /cad | `/cad panel` | Active incidents with a picker → incident card with actions | cad.view |
| /cad-911 | `/cad 911` | Opens a 911 form → Pending Dispatch call | cad.911.create |
| /cad-incident | `/cad incident <number>` | Incident card + timeline + Attach / On scene / Note buttons | cad.view |
| /cad-incidents | `/cad incidents [state]` | List open / closed / all incidents | cad.view |
| /cad-close | `/cad close <number> <disposition> [cancel]` | Close or cancel with disposition | cad.incident.close |
| /cad-reopen | `/cad reopen <number>` | Reopen to Pending Dispatch | cad.incident.close |
| /cad-assign | `/cad assign <number>` | **Attach your own unit** (self-assign) | cad.unit.self |
| /cad-history | `/cad history <number>` | Full event timeline | cad.view |
| /unit | `/unit panel [unit]` | Your unit with a status picker | cad.view |
| /unit-register | `/unit register <department> [callsign] [type] [vehicle]` | Register a unit (callsign suggested from the department format) | cad.unit.manage or cad.unit.self (own dept) |
| /unit-status | `/unit status <status> [unit] [note]` | Update status (statuses are configurable) | cad.unit.self / cad.dispatch |
| /unit-assign | `/unit assign <unit> <member> [primary]` | **Add a member** to a unit | cad.unit.manage / cad.dispatch |
| /unit-remove | `/unit remove <unit> [member]` | Remove a member, or remove the unit | cad.unit.manage |
| /unit-list | `/unit list [department]` | Unit board grouped by availability | cad.view |
| /unit-history | `/unit history <unit>` | Status, assignment and member history | cad.view |
| /dispatch | `/dispatch panel` | Queue + unit board + pending in-game calls | cad.view |
| /dispatch-create | `/dispatch create <category> <priority> <location> <description> [department] [caller]` | Create an incident (public) | cad.incident.create |
| /dispatch-assign | `/dispatch assign <incident> <unit> [primary]` | Assign any unit | cad.dispatch |
| /dispatch-update | `/dispatch update <incident> [status] [priority] [note]` | Status / priority / dispatcher note | cad.incident.edit |
| /dispatch-close | `/dispatch close <incident> <unit>` | **Clear a unit** from an incident (closing incidents is `/cad close`, so the two don't duplicate) | cad.dispatch |
| /dispatch-queue | `/dispatch queue [sort]` | Waiting incidents with timers and overdue flags | cad.view |
| /mdt | `/mdt panel` | Your unit, status, assigned calls, active stops, hours | cad.view |
| /mdt-person | `/mdt person <query>` | Person lookup with warrants / BOLO alerts | cad.records.search |
| /mdt-vehicle | `/mdt vehicle <plate or query>` | Plate check with registration / insurance / BOLO alerts | cad.records.search |
| /mdt-bolo | `/mdt bolo <query>` | Check a name/plate/description against active BOLOs | cad.records.search |
| /mdt-traffic-stop | `/mdt traffic-stop <location> [plate] [vehicle] [reason] [driver]` | Start a stop; complete it with the outcome picker | cad.traffic.manage |
| /mdt-report | `/mdt report` | Your reports and their review status | cad.reports.create |
| /department | `/department panel <department>` | Department card with roster button (public) | dept.view |
| /department-info | `/department info <department>` | Details and statistics | dept.view |
| /department-roster | `/department roster <department>` | Roster grouped by rank with duty status | dept.view |
| /department-stats | `/department stats <department> [days]` | Hours, participation, incidents, stops, reports | dept.view |
| /department-ranks | `/department ranks <department>` | Rank structure | dept.view |
| /shift-start | `/shift start [department] [callsign] [notes]` | Clock in | shift.self |
| /shift-end | `/shift end [notes]` | Clock out | shift.self |
| /shift-status | `/shift status` | Your shift + who's on duty | shift.self |
| /shift-history | `/shift history [member]` | Recent shifts (others need shift.manage) | shift.self |
| /shift-stats | `/shift stats [member]` | Weekly / monthly / all-time hours, adjustments | shift.self |
| /bolo-create | `/bolo create <category>` | Opens a BOLO form (public result) | cad.bolo.manage |
| /bolo-search | `/bolo search <query>` | Search all BOLOs | cad.records.search |
| /bolo-update | `/bolo update <number> [location] [details]` | Update location / add details | cad.bolo.manage |
| /bolo-close | `/bolo close <number> <resolved/cancelled>` | Close a BOLO | cad.bolo.manage |
| /bolo-list | `/bolo list` | Active BOLOs | cad.records.search |
| /record-person | `/record person` | New person record (form) | cad.records.edit / civ.use |
| /record-vehicle | `/record vehicle <plate> <make> <model> <color> [owner] [registration] [insurance]` | Register a vehicle | cad.records.edit / civ.use |
| /record-search | `/record search <query>` | Central search across everything you can access | per record type |
| /record-update | `/record update [person] [vehicle] [registration] [insurance] [flags]` | Edit a person (form) or vehicle status | cad.records.edit |
| /record-history | `/record history [person] [vehicle]` | Field-level change history | cad.records.search |
| /report-create | `/report create [incident]` | Write a report (form) — saved as draft | cad.reports.create |
| /report-submit | `/report submit <number>` | Submit for review | author |
| /report-view | `/report view <number>` | View report + comments | author / reviewers |
| /report-search | `/report search [query] [status]` | Search reports | cad.reports.create |
| /report-review | `/report review <number> <action> [comment]` | Start / approve / return / comment / archive | cad.reports.review |
| — | `/nexus help` | Command overview | everyone |
| — | `/nexus status` | Bot, API and database status | everyone |
| — | `/nexus dashboard` | Links to the website, Dispatch Center and MDT | everyone |
| — | `/nexus link-roblox <username> <user_id>` | Link Roblox account (enables API unit positions) | everyone |
| — | `/nexus panel <kind> [channel]` | Post an auto-refreshing live panel (server, incidents, units, bolos, shifts) | system.configure |
| — | **Nexus profile** (user context menu) | Department memberships, duty status and hours | dept.view |
| — | **Create CAD incident** (message context menu) | Turn a Discord message into an incident | cad.incident.create |

## Notifications posted by the bot

Configure channels in **System → Discord Integration**: new incidents, closures, unit
assignments, unit status changes (throttled), priority upgrades, new / expired BOLOs,
reports awaiting review, shift start / end, in-game 911 calls, server status changes,
ERLC API problems and in-game mod calls. Departments can also have their own channel.
Website dispatch messages and announcements can be mirrored to a comms channel.
