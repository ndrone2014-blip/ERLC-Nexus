// ERLC Nexus single-page app shell + router.
import { api, can, canAny, clear, connectRealtime, debounce, emit, h, icon, L, mount, on, state, toast, ago } from "./core.js";

const NAV = [
  ["GENERAL", [
    ["#/", "Overview", "home", null], ["#/notifications", "Notifications", "bell", null], ["#/activity", "Activity", "activity", ["cad.view", "dept.view", "audit.view"]],
  ]],
  ["ERLC SERVER", [
    ["#/server", "Server Overview", "server", ["erlc.server.view"]], ["#/server/players", "Live Players", "users", ["erlc.server.view"]],
    ["#/server/search", "Player Search", "search", ["erlc.server.view"]], ["#/server/moderation", "Server Moderation", "gavel", ["erlc.server.moderate", "erlc.logs.view"]],
    ["#/server/commands", "Server Commands", "terminal", ["erlc.server.command", "erlc.server.announce"]], ["#/server/config", "Server Configuration", "sliders", ["system.configure"]],
  ]],
  ["CAD", [
    ["#/cad", "CAD Overview", "radio", ["cad.view"]], ["#/cad/dispatch", "Dispatch Center", "headset", ["cad.view"]],
    ["#/cad/map", "Live Map", "map", ["cad.view"]], ["#/cad/calls", "Active Calls", "phone", ["cad.view"]],
    ["#/cad/history", "Incident History", "history", ["cad.view"]], ["#/cad/units", "Unit Management", "car", ["cad.view"]],
    ["#/cad/traffic", "Traffic Stops", "shield", ["cad.traffic.manage", "cad.dispatch"]], ["#/mdt", "Open MDT", "monitor", ["cad.view"]],
    ["#/cad/911", "Call 911", "phone", ["cad.911.create"]],
  ]],
  ["RECORDS", [
    ["#/records/persons", "Person Records", "user", ["cad.records.search", "civ.use"]], ["#/records/vehicles", "Vehicle Records", "car", ["cad.records.search", "civ.use"]],
    ["#/records/bolos", "BOLO Database", "eye", ["cad.records.search"]], ["#/records/warrants", "Warrant Records", "scale", ["cad.warrants.view"]],
    ["#/records/reports", "Incident Reports", "file", ["cad.reports.create"]], ["#/records/search", "Search Records", "search", ["cad.records.search", "cad.view"]],
  ]],
  ["DEPARTMENTS", [
    ["#/departments", "Department Overview", "building", ["dept.view"]], ["#/departments/personnel", "Personnel", "users", ["dept.view"]],
    ["#/departments/ranks", "Ranks", "badge", ["dept.view"]], ["#/departments/callsigns", "Callsigns", "hash", ["dept.view"]],
    ["#/departments/shifts", "Shift Management", "clock", ["shift.self", "shift.manage"]], ["#/departments/stats", "Department Statistics", "chart", ["dept.view"]],
  ]],
  ["ANALYTICS", [
    ["#/analytics/server", "Server Analytics", "chart", ["analytics.view"]], ["#/analytics/cad", "CAD Analytics", "pie", ["analytics.view"]],
    ["#/analytics/departments", "Department Analytics", "building", ["analytics.view"]], ["#/analytics/dispatchers", "Dispatcher Analytics", "headset", ["analytics.view"]],
    ["#/analytics/activity", "Activity Reports", "layers", ["analytics.view"]],
  ]],
  ["SYSTEM", [
    ["#/system/discord", "Discord Integration", "discord", ["system.configure"]], ["#/system/api", "API Configuration", "key", ["system.configure"]],
    ["#/system/permissions", "Permissions", "lock", ["system.permissions", "system.configure"]], ["#/system/logging", "Logging", "list", ["audit.view"]],
    ["#/system/appearance", "Appearance", "palette", ["system.configure"]], ["#/system/database", "Database", "database", ["system.database"]],
    ["#/system/health", "System Health", "heart", ["system.configure", "system.security"]], ["#/system/security", "Security", "shield", ["system.security"]],
  ]],
];

// route pattern → [module, export]
const ROUTES = [
  [/^\/$/, "overview"], [/^\/notifications$/, "general", "notifications"], [/^\/activity$/, "general", "activity"], [/^\/profile$/, "general", "profile"],
  [/^\/server$/, "server", "overview"], [/^\/server\/players$/, "server", "players"], [/^\/server\/search$/, "server", "search"],
  [/^\/server\/moderation$/, "server", "moderation"], [/^\/server\/commands$/, "server", "commands"], [/^\/server\/config$/, "server", "config"],
  [/^\/cad$/, "cad", "overview"], [/^\/cad\/dispatch$/, "dispatch"], [/^\/cad\/map$/, "map", "liveMap"], [/^\/cad\/calls$/, "cad", "calls"],
  [/^\/cad\/history$/, "cad", "history"], [/^\/cad\/units$/, "cad", "units"], [/^\/cad\/traffic$/, "cad", "traffic"], [/^\/cad\/traffic\/(\d+)$/, "cad", "trafficDetail"],
  [/^\/cad\/incident\/(\d+)$/, "cad", "incident"], [/^\/cad\/911$/, "cad", "call911"], [/^\/cad\/map-editor$/, "map", "editor"],
  [/^\/records\/persons$/, "records", "persons"], [/^\/records\/person\/(\d+)$/, "records", "person"],
  [/^\/records\/vehicles$/, "records", "vehicles"], [/^\/records\/vehicle\/(\d+)$/, "records", "vehicle"],
  [/^\/records\/bolos$/, "records", "bolos"], [/^\/records\/bolo\/(\d+)$/, "records", "bolo"],
  [/^\/records\/warrants$/, "records", "warrants"], [/^\/records\/case\/(\d+)$/, "records", "caseDetail"],
  [/^\/records\/reports$/, "reports", "list"], [/^\/records\/report\/(\d+)$/, "reports", "detail"], [/^\/records\/report\/new$/, "reports", "create"],
  [/^\/records\/search$/, "records", "search"],
  [/^\/departments$/, "departments", "overview"], [/^\/departments\/(\d+)$/, "departments", "detail"], [/^\/departments\/personnel$/, "departments", "personnel"],
  [/^\/departments\/personnel\/(\d+)$/, "departments", "profile"], [/^\/departments\/ranks$/, "departments", "ranks"],
  [/^\/departments\/callsigns$/, "departments", "callsigns"], [/^\/departments\/shifts$/, "departments", "shifts"], [/^\/departments\/stats$/, "departments", "stats"],
  [/^\/analytics\/(server|cad|departments|dispatchers|activity)$/, "analytics", "page"],
  [/^\/system\/discord$/, "system", "discord"], [/^\/system\/api$/, "system", "apiConfig"], [/^\/system\/permissions$/, "system", "permissions"],
  [/^\/system\/logging$/, "system", "logging"], [/^\/system\/appearance$/, "system", "appearance"], [/^\/system\/database$/, "system", "database"],
  [/^\/system\/health$/, "system", "health"], [/^\/system\/security$/, "system", "security"],
  [/^\/mdt(?:\/([a-z-]+))?(?:\/(\d+))?$/, "mdt"],
];

let cleanup = null;
let shellEls = null;

async function boot() {
  try {
    const me = await api("me", { silent: true });
    state.me = me; state.csrf = me.csrf_token;
  } catch {
    return renderLogin();
  }
  state.boot = await api("bootstrap");
  applyTheme();
  connectRealtime();
  window.addEventListener("hashchange", route);
  on("permissions.changed", async () => { const me = await api("me", { silent: true }); state.me = me; state.csrf = me.csrf_token; renderNav(); });
  on("config.changed", debounce(async () => { state.boot = await api("bootstrap"); applyTheme(); }, 800));
  on("notification", (n) => {
    state.unread += 1; updateBell();
    if (n.severity === "danger" || n.severity === "warning") toast(n.body || "", n.severity === "danger" ? "bad" : "warn", n.title);
    if (state.me?.preferences?.sound_alerts && n.severity === "danger") beep();
  });
  setupShortcuts();
  const startPage = state.me.preferences?.default_page;
  if (startPage && startPage !== "#/" && (!location.hash || location.hash === "#/")) location.hash = startPage;
  route();
  refreshUnread();
}

function beep() {
  try { const ctx = new AudioContext(); const o = ctx.createOscillator(); o.frequency.value = 880; o.connect(ctx.destination); o.start(); setTimeout(() => { o.stop(); ctx.close(); }, 180); } catch { /* audio blocked */ }
}

export function applyTheme() {
  const pref = state.me?.preferences?.theme || state.boot?.settings?.["appearance.default_theme"] || "dark";
  const theme = pref === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : pref;
  document.documentElement.dataset.theme = theme;
  const accent = state.boot?.settings?.["appearance.accent"];
  if (accent && /^#[0-9a-f]{6}$/i.test(accent)) { document.documentElement.style.setProperty("--accent", accent); document.documentElement.style.setProperty("--accent-2", accent); }
  document.title = `${state.boot?.settings?.["community.name"] || "ERLC"} · Nexus`;
}

async function renderLogin() {
  const cfg = await api("auth/config", { silent: true }).catch(() => ({}));
  const err = new URLSearchParams(location.hash.split("?")[1] || "").get("error");
  const messages = { oauth_not_configured: "Discord login isn't configured yet. Add DISCORD_APPLICATION_ID and DISCORD_CLIENT_SECRET to config.env.",
    login_failed: "Login was cancelled or expired. Please try again.", discord_unavailable: "Couldn't reach Discord. Try again in a moment.",
    account_disabled: "Your ERLC Nexus account is disabled. Contact an administrator." };
  const logo = cfg.logo_url ? h("img", { src: cfg.logo_url, alt: "" }) : "NX";
  mount(document.getElementById("app"), h("div", { class: "login" }, h("div", { class: "login-card" },
    h("div", { class: "brand-mark", style: { width: "52px", height: "52px", margin: "0 auto", fontSize: "18px" } }, logo),
    h("h1", cfg.community_name || "ERLC Nexus"),
    h("p", "CAD, MDT, records and server management for your ERLC community."),
    err ? h("div", { class: "notice bad", style: { marginBottom: "14px", textAlign: "left" } }, messages[err] || "Login failed.") : null,
    h("a", { class: "btn primary", href: "/auth/login" }, icon("discord"), "Sign in with Discord"),
    cfg.dev_login ? h("button", { class: "btn", style: { marginTop: "8px", width: "100%", justifyContent: "center" }, onclick: async () => {
      const r = await fetch("/auth/dev-login", { method: "POST", credentials: "same-origin" });
      if (r.ok || r.redirected) { location.hash = "#/"; location.reload(); } else toast("Local login refused", "bad");
    } }, "Local administrator login (DEV_LOGIN)") : null,
    h("div", { class: "login-foot" }, "Free & self-hosted · ", h("span", { class: "muted" }, "Developed by Drone Hive Studios")))));
}

function renderShell() {
  const sidebar = h("aside", { class: "sidebar", id: "sidebar" });
  const view = h("main", { class: "content", id: "view" });
  const statusChip = h("span", { class: "chip hide-sm", title: "ERLC server status" }, h("span", { class: "dot" }), "Server");
  const wsChip = h("span", { class: "chip hide-sm", title: "Live updates" }, h("span", { class: "dot" }), "Live");
  const clock = h("span", { class: "clock" });
  const bellBtn = h("button", { class: "iconbtn", "aria-label": "Notifications", onclick: (e) => toggleNotifications(e) }, icon("bell"));
  const searchBox = h("input", { type: "search", placeholder: "Search incidents, people, plates, BOLOs…  (Alt+S)", id: "global-search", autocomplete: "off" });
  const searchWrap = h("div", { class: "search" }, icon("search"), searchBox);
  const deptSel = h("select", { title: "Department", style: { maxWidth: "170px" }, onchange: async (e) => {
    await api("me/preferences", { method: "PUT", body: { default_department_id: e.target.value ? Number(e.target.value) : null } });
    state.me.preferences.default_department_id = e.target.value ? Number(e.target.value) : null; emit("department.selected", e.target.value);
  } }, h("option", { value: "" }, "All departments"), L.departments().filter((d) => state.me.department_ids.includes(d.id) || can("cad.department.manage"))
    .map((d) => h("option", { value: d.id, selected: d.id === state.me.preferences?.default_department_id }, d.abbreviation)));
  const userBtn = h("a", { href: "#/profile", class: "row", title: "Your profile", style: { color: "var(--text)", textDecoration: "none" } },
    state.me.avatar_url ? h("img", { class: "avatar", src: state.me.avatar_url, alt: "" }) : h("span", { class: "avatar" }, (state.me.name || "?")[0]),
    h("span", { class: "small hide-sm" }, state.me.name));
  const topbar = h("header", { class: "topbar" },
    h("button", { class: "iconbtn menu-toggle", onclick: () => sidebar.classList.toggle("open"), "aria-label": "Menu" }, icon("menu")),
    searchWrap, h("div", { class: "spacer" }), statusChip, wsChip, clock, deptSel,
    h("div", { style: { position: "relative" }, id: "bell-wrap" }, bellBtn), userBtn,
    h("button", { class: "iconbtn", title: "Sign out", onclick: logout }, icon("logout")));
  mount(document.getElementById("app"), h("div", { class: "shell" }, sidebar, h("div", { class: "main" }, topbar, view)));
  shellEls = { sidebar, view, statusChip, wsChip, clock, bellBtn };
  setupGlobalSearch(searchWrap, searchBox);
  renderNav();
  setInterval(() => { clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }, 1000);
  on("ws.status", (ok) => { wsChip.querySelector(".dot").className = "dot " + (ok ? "ok" : "bad"); wsChip.lastChild.textContent = ok ? "Live" : "Reconnecting"; });
  const refreshStatus = debounce(async () => {
    if (!can("erlc.server.view")) { statusChip.style.display = "none"; return; }
    const ov = await api("erlc/overview", { silent: true }).catch(() => null);
    if (!ov) return;
    const map = { online: ["ok", `${ov.server?.current_players}/${ov.server?.max_players} online`], empty: ["warn", "Server empty"],
      api_error: ["bad", "API error"], not_configured: ["", "API not configured"], unknown: ["", "Waiting for sync"] };
    const [cls, text] = map[ov.status] || ["", ov.status];
    statusChip.querySelector(".dot").className = "dot " + cls; statusChip.lastChild.textContent = text;
  }, 300);
  refreshStatus(); on("erlc.synced", refreshStatus); on("erlc.api_status", refreshStatus);
}

function renderNav() {
  if (!shellEls) return;
  const current = location.hash || "#/";
  const community = state.boot?.settings?.["community.name"] || "ERLC Nexus";
  const logo = state.boot?.settings?.["community.logo_url"];
  mount(shellEls.sidebar,
    h("div", { class: "brand" }, h("div", { class: "brand-mark" }, logo ? h("img", { src: logo, alt: "" }) : "NX"),
      h("div", h("div", { class: "brand-name" }, community), h("div", { class: "brand-sub" }, "ERLC Nexus"))),
    NAV.map(([group, items]) => {
      const visible = items.filter(([, , , perms]) => !perms || canAny(...perms));
      if (!visible.length) return null;
      return h("nav", { class: "nav-group nav" }, h("h4", group), visible.map(([href, label, ico]) =>
        h("a", { href, class: (current === href || (href !== "#/" && current.startsWith(href + "/") && !visible.some(([o]) => o !== href && current.startsWith(o)))) ? "active" : "",
          onclick: () => shellEls.sidebar.classList.remove("open") }, icon(ico), label)));
    }));
}

async function refreshUnread() {
  const r = await api("notifications", { query: { unread: true }, silent: true }).catch(() => null);
  if (r) { state.unread = r.unread; updateBell(); }
}
function updateBell() {
  if (!shellEls) return;
  shellEls.bellBtn.querySelector(".badge-count")?.remove();
  if (state.unread > 0) shellEls.bellBtn.appendChild(h("span", { class: "badge-count" }, state.unread > 99 ? "99+" : state.unread));
}
async function toggleNotifications(e) {
  e.stopPropagation();
  const wrap = document.getElementById("bell-wrap");
  const existing = wrap.querySelector(".dropdown");
  if (existing) return existing.remove();
  const dd = h("div", { class: "dropdown" }, h("div", { class: "empty" }, "Loading…"));
  wrap.appendChild(dd);
  const r = await api("notifications");
  const close = (ev) => { if (!dd.contains(ev.target)) { dd.remove(); document.removeEventListener("click", close); } };
  setTimeout(() => document.addEventListener("click", close), 0);
  mount(dd, h("div", { class: "card-head" }, h("h3", "Notifications"), h("div", { class: "row" },
    h("button", { class: "btn xs", onclick: async () => { await api("notifications/read", { method: "POST", body: {} }); state.unread = 0; updateBell(); dd.remove(); } }, "Mark all read"),
    h("a", { class: "btn xs", href: "#/notifications", onclick: () => dd.remove() }, "View all"))),
    r.items.length ? h("div", { class: "list" }, r.items.slice(0, 20).map((n) => h("div", { class: "list-item clickable", style: { opacity: n.read ? .6 : 1 }, onclick: () => {
      api("notifications/read", { method: "POST", body: { ids: [n.id] }, silent: true }); if (n.link) location.hash = n.link.replace(/^\/?#/, "#"); dd.remove();
    } }, h("span", { class: "dot " + ({ danger: "bad", warning: "warn", success: "ok" }[n.severity] || "") }),
      h("div", { class: "grow" }, h("div", { class: "title" }, n.title, n.count > 1 ? ` (×${n.count})` : ""), n.body ? h("div", { class: "meta" }, n.body) : null, h("div", { class: "meta" }, ago(n.created_at)))))) : h("div", { class: "empty" }, "You're all caught up."));
}

function setupGlobalSearch(wrap, input) {
  let box = null;
  const close = () => { box?.remove(); box = null; };
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) return close();
    const r = await api("search", { query: { q, limit: 5 }, silent: true }).catch(() => null);
    if (!r) return;
    close();
    box = h("div", { class: "search-results" }, r.total ? Object.entries(r.results).filter(([, v]) => v.length).map(([scope, rows]) => [
      h("h4", scope), ...rows.map((row) => h("div", { class: "list-item clickable", onclick: () => { location.hash = row.link.replace(/^\/?#/, "#"); close(); input.value = ""; } },
        h("div", { class: "grow" }, h("div", { class: "title" }, row.title), h("div", { class: "meta truncate" }, row.summary))))]) : h("div", { class: "empty" }, "No results."),
      h("div", { class: "pager" }, h("a", { href: `#/records/search?q=${encodeURIComponent(q)}`, onclick: close }, "Advanced search →"), h("span", `${r.total} result(s)`)));
    wrap.appendChild(box);
  }, 250);
  input.addEventListener("input", run);
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); input.blur(); } if (e.key === "Enter") { location.hash = `#/records/search?q=${encodeURIComponent(input.value)}`; close(); } });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) close(); });
}

const SHORTCUT_ACTIONS = {
  new_incident: () => { location.hash = "#/cad/dispatch?new=1"; },
  search: () => document.getElementById("global-search")?.focus(),
  unit_board: () => { location.hash = "#/cad/units"; },
  active_calls: () => { location.hash = "#/cad/calls"; },
  dashboard: () => { location.hash = "#/"; },
  focus_note: () => document.querySelector("[data-note-input]")?.focus(),
};
function setupShortcuts() {
  document.addEventListener("keydown", (e) => {
    const prefs = state.me?.preferences || {};
    if (prefs.shortcuts_enabled === false) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) && !e.altKey) return;
    const combo = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.key.length === 1 ? e.key.toUpperCase() : e.key].filter(Boolean).join("+");
    const map = { ...(state.boot?.settings?.["dispatch.shortcuts"] || {}), ...(prefs.shortcuts || {}) };
    for (const [action, keys] of Object.entries(map)) {
      if (keys && keys.toUpperCase() === combo.toUpperCase() && SHORTCUT_ACTIONS[action]) { e.preventDefault(); SHORTCUT_ACTIONS[action](); return; }
    }
  });
}

async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => null);
  location.href = "/";
}

async function route() {
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  if (path === "/login") { location.hash = "#/"; return; }
  if (typeof cleanup === "function") { try { cleanup(); } catch { /* ignore */ } }
  cleanup = null;
  const isMdt = path.startsWith("/mdt");
  if (isMdt) { shellEls = null; } else if (!shellEls) { renderShell(); }
  if (!isMdt) renderNav();
  const root = isMdt ? document.getElementById("app") : shellEls.view;
  for (const [re, mod, fn] of ROUTES) {
    const m = path.match(re);
    if (!m) continue;
    clear(root);
    if (!isMdt) root.appendChild(h("div", { class: "empty" }, "Loading…"));
    try {
      const module = await import(`./pages/${mod}.js`);
      const page = fn ? module[fn] : module.default;
      clear(root);
      cleanup = await page(root, m.slice(1), query);
      window.scrollTo(0, 0);
    } catch (err) {
      console.error(err);
      mount(root, h("div", { class: "notice bad" }, err.status === 403 ? "You don't have permission to view this page." : `Could not load this page: ${err.message}`));
    }
    return;
  }
  mount(root, h("div", { class: "empty" }, "Page not found. ", h("a", { href: "#/" }, "Go to overview")));
}

boot();
