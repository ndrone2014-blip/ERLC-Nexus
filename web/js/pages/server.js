import { api, ago, btn, can, card, confirmDialog, debounce, empty, fmtTime, form, h, icon, kv, live, modal, mount, pageHead, stat, statusPill, table, tabs, toast } from "../core.js";
import { hbars } from "../charts.js";

const SOURCE = () => h("div", { class: "disclaimer" }, icon("check"), "Live data from the official ERLC API (api.erlc.gg)");

export async function overview(root) {
  const body = h("div");
  const load = async () => {
    const ov = await api("erlc/overview");
    const srv = ov.server;
    if (!srv) {
      mount(body, card(null, h("div", { class: "stack" }, h("div", { class: "notice " + (ov.api_error ? "bad" : "") },
        ov.api_error ? `ERLC API: ${ov.api_error.message}` : ov.configured ? "Waiting for the first sync…" : "No ERLC server key configured yet."),
        can("system.configure") ? h("a", { class: "btn", href: "#/system/api" }, icon("key"), "Configure the ERLC API") : null)));
      return;
    }
    const staff = srv.staff || {};
    mount(body,
      h("div", { class: "grid g4", style: { marginBottom: "14px" } },
        stat("Status", statusPill(ov.status === "online" ? "Online" : ov.status === "empty" ? "Empty" : ov.status, ov.status === "online" ? "#22c55e" : "#f59e0b"), { sub: `Last sync ${ago(ov.fetched_at)}${ov.stale ? " · stale" : ""}` }),
        stat("Players", `${srv.current_players}/${srv.max_players}`, { sub: `${srv.capacity_pct}% capacity`, tone: "accent" }),
        stat("Queue", srv.queue.length, { sub: "Players waiting to join" }),
        stat("Spawned vehicles", srv.vehicles.length, { sub: "Reported by the API" })),
      h("div", { class: "grid g2" },
        card("Server details", h("div", { class: "stack" }, kv([
          ["Name", srv.name], ["Join code", h("code", srv.join_key || "—")], ["Owner (Roblox ID)", srv.owner_id],
          ["Co-owners", srv.co_owner_ids.join(", ") || "—"], ["Account verification", srv.acc_verified_req], ["Team balance", srv.team_balance ? "On" : "Off"],
          ["Last successful sync", fmtTime(ov.last_successful_sync)]]), SOURCE())),
        card("Team distribution", hbars(Object.entries(srv.teams).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)) ),
        card("Server staff", Object.keys(staff).length ? h("div", { class: "grid g3" }, ["admins", "mods", "helpers"].map((k) => h("div",
          h("h4", { style: { marginBottom: "6px" } }, `${k} (${Object.keys(staff[k] || {}).length})`),
          h("div", { class: "stack small" }, Object.entries(staff[k] || {}).map(([id, name]) => h("span", { title: id }, name)))))) : empty("Staff list unavailable.")),
        card("Spawned vehicles", srv.vehicles.length ? table([
          { label: "Vehicle", key: "name" }, { label: "Owner", key: "owner" }, { label: "Plate", render: (v) => h("code", v.plate || "—") },
          { label: "Color", render: (v) => { const d = h("span", { class: "dot" }); d.style.background = v.color_hex ? `#${String(v.color_hex).replace("#", "")}` : "#64748b"; return h("span", { class: "row" }, d, v.color_name || "—"); } },
        ], srv.vehicles) : empty("No vehicles reported.", "car"), { flush: true })));
  };
  mount(root, pageHead("Server Overview", "Your private server, straight from the official ERLC API.", [
    btn("Refresh now", async (e) => { e.currentTarget.disabled = true; try { await api("erlc/refresh", { method: "POST" }); await load(); toast("Refreshed", "ok"); } finally { e.currentTarget.disabled = false; } }, { ico: "refresh", sm: true }),
  ]), body);
  await load();
  return live(["erlc.synced", "erlc.api_status"], load, 500);
}

export async function players(root) {
  const q = h("input", { type: "search", placeholder: "Filter by name, ID or callsign" });
  const team = h("select", h("option", { value: "" }, "All teams"));
  const body = h("div");
  let rows = [];
  const render = () => {
    const ql = q.value.toLowerCase();
    const filtered = rows.filter((p) => (!team.value || p.team === team.value) && (!ql || p.name.toLowerCase().includes(ql) || p.id === ql || (p.callsign || "").toLowerCase().includes(ql)));
    mount(body, table([
      { label: "Player", render: (p) => h("div", h("div", { style: { fontWeight: 600 } }, p.name), h("div", { class: "muted small mono" }, p.id)) },
      { label: "Team", key: "team" }, { label: "Callsign", render: (p) => p.callsign ? h("code", p.callsign) : "—" },
      { label: "Permission", key: "permission" }, { label: "Wanted", render: (p) => p.wanted_stars ? "★".repeat(p.wanted_stars) : "—" },
      { label: "Location (API)", render: (p) => p.location?.street ? `${p.location.building || ""} ${p.location.street} · ${p.location.postal || ""}` : "—" },
    ], filtered, { onRow: (p) => { location.hash = `#/server/search?q=${encodeURIComponent(p.name)}`; }, emptyText: "No players match." }));
  };
  const load = async () => {
    rows = await api("erlc/players");
    const teams = [...new Set(rows.map((p) => p.team))].sort();
    const cur = team.value;
    mount(team, h("option", { value: "" }, `All teams (${rows.length})`), teams.map((t) => h("option", { value: t, selected: t === cur }, `${t} (${rows.filter((p) => p.team === t).length})`)));
    render();
  };
  q.addEventListener("input", render); team.addEventListener("change", render);
  mount(root, pageHead("Live Players", "Everyone in your server right now."), card(h("div", { class: "filters" }, q, team), body, { flush: true }), h("div", { style: { marginTop: "8px" } }, SOURCE()));
  await load();
  return live(["erlc.synced"], load, 500);
}

export async function search(root, _p, query) {
  const input = h("input", { type: "search", placeholder: "Roblox username or user ID", value: query.q || "", style: { minWidth: "300px" } });
  const body = h("div");
  const run = async () => {
    if (!input.value.trim()) return mount(body, empty("Search for a player by name or ID.", "search"));
    let prof;
    try { prof = await api("erlc/player", { query: { query: input.value.trim() }, silent: true }); }
    catch (e) { return mount(body, empty(e.message, "search")); }
    const live_ = prof.live || {};
    const rec = prof.recorded;
    const actions = can("erlc.server.moderate") ? h("div", { class: "row" },
      btn("Kick", () => moderateDialog("kick", prof.name), { sm: true }), btn("Ban", () => moderateDialog("ban", prof.name), { sm: true, kind: "danger" }),
      btn("Unban", () => moderateDialog("unban", prof.name), { sm: true }), btn("Add note", () => noteDialog(prof.name), { sm: true })) : null;
    mount(body, h("div", { class: "grid g2" },
      card(h("h3", prof.name, " ", prof.online ? h("span", { class: "badge", style: { color: "#22c55e" } }, "In server") : h("span", { class: "badge" }, "Not in server")), h("div", { class: "stack" }, kv([
        ["Roblox ID", h("code", prof.roblox_id)], ["Team", live_.team || rec?.last_team], ["Callsign", live_.callsign], ["Permission", live_.permission],
        ["Wanted stars", live_.wanted_stars], ["Location", live_.location?.street ? `${live_.location.building || ""} ${live_.location.street} · Postal ${live_.location.postal || "—"}` : null],
        ["Banned", prof.banned === null ? "Unknown — refresh the ban list" : prof.banned ? "Yes" : "No"]]), prof.online ? SOURCE() : null), { actions }),
      card("Recorded by ERLC Nexus", rec ? kv([["First seen", fmtTime(rec.first_seen)], ["Last seen", fmtTime(rec.last_seen)], ["Sessions", rec.sessions], ["Notes", rec.notes]])
        : empty("Nexus hasn't recorded this player yet.")),
      card("Moderation history", table([{ label: "Action", render: (r) => h("span", { class: "row" }, r.success ? icon("check") : icon("x"), r.action) },
        { label: "Reason", key: "reason" }, { label: "Result", key: "result" }, { label: "When", render: (r) => fmtTime(r.created_at) }], prof.history,
        { emptyText: "No recorded actions." }), { flush: true, cls: "span2" })));
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  mount(root, pageHead("Player Search", "Look up live players and the history ERLC Nexus has recorded for them."),
    card(h("div", { class: "filters" }, input, btn("Search", run, { kind: "primary", ico: "search" })), body));
  await run();
}

async function moderateDialog(action, player = "") {
  const f = form([{ name: "player", label: "Roblox username or ID", required: true }, ...(action !== "unban" ? [{ name: "reason", label: "Reason", type: "textarea", full: true, max: 200 }] : [])], { player });
  return modal(`${action[0].toUpperCase()}${action.slice(1)} player`, h("div", { class: "stack" }, f.el,
    h("div", { class: "small muted" }, "Sent as an in-game admin command through the official ERLC API and logged in the player's history.")), {
    submitLabel: action[0].toUpperCase() + action.slice(1), danger: action === "ban",
    onSubmit: async () => { const r = await api("erlc/moderate", { method: "POST", body: { action, ...f.values() } }); toast(`${r.player}: ${r.result}`, "ok", `Player ${action}`); },
  });
}
async function noteDialog(player) {
  const f = form([{ name: "note", label: "Note", type: "textarea", full: true, required: true }]);
  return modal(`Note on ${player}`, f.el, { onSubmit: async () => { await api("erlc/player-note", { method: "POST", body: { player, ...f.values() } }); toast("Note saved", "ok"); } });
}

export async function moderation(root) {
  const body = h("div");
  const show = async (tab) => {
    mount(body, h("div", { class: "empty" }, "Loading…"));
    if (tab === "actions") {
      const rows = await api("erlc/moderation");
      mount(body, card(null, table([{ label: "Player", render: (r) => h("div", r.username, h("div", { class: "muted small mono" }, r.roblox_id || "")) },
        { label: "Action", render: (r) => h("span", { class: "row" }, r.success ? icon("check") : icon("x"), r.action) }, { label: "Reason", key: "reason" },
        { label: "Result", key: "result" }, { label: "Source", key: "source" }, { label: "When", render: (r) => fmtTime(r.created_at) }], rows), { flush: true }));
    } else if (tab === "bans") {
      const r = await api("erlc/bans");
      mount(body, card(h("div", { class: "row" }, h("h3", "Server bans"), h("span", { class: "muted small" }, r.fetched_at ? `fetched ${ago(r.fetched_at)}` : "not fetched yet")),
        r.bans ? table([{ label: "Player", key: "name" }, { label: "Roblox ID", render: (b) => h("code", b.id) },
          { label: "", render: (b) => btn("Unban", () => moderateDialog("unban", b.name || b.id), { sm: true }) }], r.bans, { emptyText: "No bans." })
          : empty("Click refresh to load the ban list from the ERLC API."),
        { flush: true, actions: [btn("Refresh from API", async () => { await api("erlc/bans/refresh", { method: "POST" }); show("bans"); }, { sm: true, ico: "refresh" })] }),
        h("div", { style: { marginTop: "8px" } }, h("div", { class: "disclaimer" }, icon("check"), r.source)));
    } else {
      const kind = { joins: "join", kills: "kill", commands: "command", modcalls: "modcall" }[tab];
      const rows = await api("erlc/logs", { query: { kind, limit: 200 } });
      const cols = {
        join: [{ label: "Player", render: (r) => `${r.name} (${r.id})` }, { label: "Event", render: (r) => r.join ? "Joined" : "Left" }],
        kill: [{ label: "Killer", render: (r) => r.killer }, { label: "Killed", render: (r) => r.killed }],
        command: [{ label: "Player", render: (r) => r.name }, { label: "Command", render: (r) => h("code", r.command) }],
        modcall: [{ label: "Caller", render: (r) => r.caller }, { label: "Responded", render: (r) => r.moderator || h("span", { class: "badge", style: { color: "#f59e0b" } }, "Unanswered") }],
      }[kind];
      mount(body, card(null, table([...cols, { label: "Time", render: (r) => fmtTime(r.ts) }], rows, { emptyText: "No log entries collected yet." }), { flush: true }),
        h("div", { class: "small muted", style: { marginTop: "8px" } }, "Logs come from the official ERLC API and are stored by ERLC Nexus so history survives server restarts."));
    }
  };
  const items = [];
  if (can("erlc.server.moderate")) items.push(["actions", "Moderation actions"], ["bans", "Bans"]);
  if (can("erlc.logs.view")) items.push(["modcalls", "Mod calls"], ["joins", "Join logs"], ["kills", "Kill logs"], ["commands", "Command logs"]);
  mount(root, pageHead("Server Moderation", "Kick, ban and review what happened in your server.", can("erlc.server.moderate") ? [
    btn("Kick", () => moderateDialog("kick"), { sm: true }), btn("Ban", () => moderateDialog("ban"), { sm: true, kind: "danger" }), btn("Unban", () => moderateDialog("unban"), { sm: true })] : []),
    tabs(items, show), body);
  await show(items[0][0]);
}

export async function commands(root) {
  const hist = h("div");
  const loadHist = async () => {
    const r = await api("activity", { query: { limit: 100 } }).catch(() => []);
    const rows = r.filter((a) => a.action === "server.command" || a.action === "server.announcement");
    mount(hist, rows.length ? h("div", { class: "list" }, rows.slice(0, 20).map((a) => h("div", { class: "list-item" }, h("div", { class: "grow" }, h("div", { class: "title" }, a.description), h("div", { class: "meta" }, fmtTime(a.created_at)))))) : empty("No commands sent yet."));
  };
  const cmd = h("input", { placeholder: ":h Server restart in 5 minutes", style: { flex: 1 } });
  const ann = h("textarea", { maxlength: 250, rows: 3, placeholder: "Announcement text (max 250 characters)" });
  const style = h("select", h("option", { value: "hint" }, "Hint (top bar)"), h("option", { value: "message" }, "Message (full screen)"));
  const result = h("div");
  const send = async () => {
    const r = await api("erlc/command", { method: "POST", body: { command: cmd.value } });
    mount(result, h("div", { class: "notice ok" }, `${r.command} → ${r.result}`)); cmd.value = ""; loadHist();
  };
  cmd.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  const quick = [[":h ", "Hint"], [":m ", "Message"], [":kick ", "Kick"], [":ban ", "Ban"], [":unban ", "Unban"], [":pm ", "Private message"]];
  mount(root, pageHead("Server Commands", "Run in-game commands through the official API. The API allows one command every 5 seconds."),
    h("div", { class: "grid g2" },
      can("erlc.server.command") ? card("Run a command", h("div", { class: "stack" }, h("div", { class: "row" }, cmd, btn("Send", send, { kind: "primary", ico: "terminal" })),
        h("div", { class: "row wrap" }, quick.map(([p, l]) => btn(l, () => { cmd.value = p; cmd.focus(); }, { sm: true, kind: "ghost" }))), result,
        h("div", { class: "small muted" }, "Commands must start with ':'. Every command is audited. Blocked commands are configured in Server Configuration."))) : null,
      can("erlc.server.announce") ? card("Announcement", h("div", { class: "stack" }, ann, h("div", { class: "row" }, style,
        btn("Send announcement", async () => { const r = await api("erlc/announce", { method: "POST", body: { message: ann.value, style: style.value } }); toast(`Sent: ${r.command}`, "ok"); ann.value = ""; loadHist(); }, { kind: "primary" })))) : null,
      card("Recent commands", hist, { flush: true, cls: "span2" })));
  await loadHist();
}

export async function config(root) {
  const s = await api("admin/settings");
  const tpl = s["erlc.command_templates"];
  const f = form([
    { section: "Moderation command templates" },
    { name: "kick", label: "Kick", hint: "Placeholders: {player} {reason}" }, { name: "ban", label: "Ban" }, { name: "unban", label: "Unban" },
    { name: "hint", label: "Hint announcement", hint: "{message}" }, { name: "message", label: "Full message announcement" },
    { section: "Safety" },
    { name: "blocked", label: "Blocked commands", hint: "Comma separated, e.g. :pm, :shutdown", full: true },
    { section: "CAD integration" },
    { name: "import911", label: "Import in-game 911 calls from the API as pending CAD calls", type: "checkbox", full: true },
    { name: "apiLocations", label: "Update unit map positions from the API for members with a linked Roblox ID", type: "checkbox", full: true },
  ], { ...tpl, blocked: (s["erlc.blocked_commands"] || []).join(", "), import911: s["cad.import_erlc_911"], apiLocations: s["cad.api_unit_locations"] });
  mount(root, pageHead("Server Configuration", "How ERLC Nexus talks to your server."), card(null, h("div", { class: "stack" }, f.el, h("div", btn("Save", async () => {
    const v = f.values();
    await api("admin/settings/erlc.command_templates", { method: "PUT", body: { value: { kick: v.kick, ban: v.ban, unban: v.unban, hint: v.hint, message: v.message } } });
    await api("admin/settings/erlc.blocked_commands", { method: "PUT", body: { value: v.blocked.split(",").map((x) => x.trim()).filter(Boolean) } });
    await api("admin/settings/cad.import_erlc_911", { method: "PUT", body: { value: v.import911 } });
    await api("admin/settings/cad.api_unit_locations", { method: "PUT", body: { value: v.apiLocations } });
    toast("Server configuration saved", "ok");
  }, { kind: "primary" })))), h("div", { style: { marginTop: "12px" } }, h("a", { href: "#/system/api", class: "btn sm" }, icon("key"), "ERLC API key & sync settings")));
}

