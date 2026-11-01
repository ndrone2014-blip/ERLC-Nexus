import { api, ago, btn, can, card, empty, h, icon, L, live, modal, mount, pageHead, prio, stat, state, statusPill, toast } from "../core.js";
import { lineChart } from "../charts.js";

const WIDGETS = {
  server: { title: "ERLC Server", perm: "erlc.server.view" },
  cad: { title: "CAD Status", perm: "cad.view" },
  units: { title: "Units", perm: "cad.view" },
  queue: { title: "Dispatch Queue", perm: "cad.view" },
  activity: { title: "Recent Activity", perm: null },
  players_chart: { title: "Player Count (24h)", perm: "analytics.view" },
  bolos: { title: "Active BOLOs", perm: "cad.records.search" },
  shifts: { title: "On Duty", perm: "dept.view" },
};

export default async function overview(root) {
  const prefs = state.me.preferences || {};
  const order = (prefs.dashboard_widgets?.length ? prefs.dashboard_widgets : L.settings("dashboard.widgets") || Object.keys(WIDGETS))
    .filter((w) => WIDGETS[w] && (!WIDGETS[w].perm || can(WIDGETS[w].perm)));
  const hidden = new Set(prefs.dashboard_hidden || []);
  const statsRow = h("div", { class: "grid g4", style: { marginBottom: "14px" } });
  const grid = h("div", { class: "grid g2" });
  mount(root, pageHead(`Welcome back, ${state.me.name}`, `${L.settings("community.name") || "Your community"} at a glance`, [
    btn("Customize", () => customize(order, hidden), { ico: "sliders", sm: true }),
    can("cad.911.create") ? h("a", { class: "btn sm", href: "#/cad/911" }, icon("phone"), "Call 911") : null,
    can("cad.incident.create") ? h("a", { class: "btn primary sm", href: "#/cad/dispatch?new=1" }, icon("plus"), "New incident") : null,
  ]), statsRow, grid);

  const els = {};
  for (const key of order) {
    if (hidden.has(key)) continue;
    els[key] = h("div", h("div", { class: "empty" }, "Loading…"));
    grid.appendChild(card(WIDGETS[key].title, els[key], { flush: ["activity", "queue", "bolos", "shifts", "units"].includes(key) }));
  }

  async function load() {
    const ov = await api("overview");
    const srv = ov.server?.server;
    mount(statsRow,
      stat("Players online", srv ? `${srv.current_players}/${srv.max_players}` : "—", { ico: "users", tone: "accent",
        sub: srv ? `${srv.capacity_pct}% capacity · ${ov.server.status}` : (ov.server ? (ov.server.configured ? "Waiting for sync" : "API not configured") : "No access") }),
      stat("Active incidents", ov.cad?.active ?? "—", { ico: "radio", tone: ov.cad?.emergency ? "bad" : "", sub: ov.cad ? `${ov.cad.emergency} emergency · ${ov.cad.awaiting_dispatch} awaiting dispatch` : "" }),
      stat("Units available", ov.units ? ov.units.available : "—", { ico: "car", tone: "ok", sub: ov.units ? `${ov.units.busy} busy · ${ov.units.unavailable} out of service` : "" }),
      stat("Personnel on shift", ov.on_shift, { ico: "clock", sub: `${ov.dispatchers_on_shift} dispatcher(s) · ${ov.bolos_active ?? 0} active BOLOs` + (ov.reports_unreviewed != null ? ` · ${ov.reports_unreviewed} reports to review` : "") }));
    if (els.server) mount(els.server, serverWidget(ov.server));
    if (els.cad) mount(els.cad, h("div", { class: "grid g2" },
      stat("Emergency calls", ov.cad.emergency, { tone: ov.cad.emergency ? "bad" : "" }), stat("Traffic stops", ov.traffic_active ?? 0),
      stat("Awaiting dispatch", ov.cad.awaiting_dispatch, { tone: ov.cad.awaiting_dispatch ? "warn" : "" }), stat("Active BOLOs", ov.bolos_active ?? "—"),
      stat("Reports to review", ov.reports_unreviewed ?? "—"), stat("Dispatchers on duty", ov.dispatchers_on_shift)));
    if (els.units) { const units = await api("cad/units"); mount(els.units, unitsWidget(units)); }
    if (els.queue) { const q = await api("cad/queue"); mount(els.queue, queueWidget(q)); }
    if (els.bolos) { const b = await api("records/bolos", { query: { status: "active" } }); mount(els.bolos, b.length ? h("div", { class: "list" }, b.slice(0, 8).map((x) =>
      h("a", { class: "list-item clickable", href: `#/records/bolo/${x.id}`, style: { color: "inherit", textDecoration: "none" } }, h("div", { class: "grow" },
        h("div", { class: "title" }, x.number, " ", h("span", { class: "muted small" }, x.category, x.plate ? ` · ${x.plate}` : "")), h("div", { class: "meta truncate" }, x.reason))))) : empty("No active BOLOs.", "eye")); }
    if (els.shifts) { const s = await api("shifts/on-duty"); mount(els.shifts, s.length ? h("div", { class: "list" }, s.map((x) =>
      h("div", { class: "list-item" }, h("span", { class: "dot ok" }), h("div", { class: "grow" }, h("div", { class: "title" }, x.user), h("div", { class: "meta" }, [x.department, x.callsign].filter(Boolean).join(" · "))),
        h("span", { class: "mono small", dataset: { since: x.started_at } }, "")))) : empty("Nobody is on shift.", "clock")); }
  }
  async function loadActivity() {
    if (!els.activity) return;
    const items = await api("activity", { query: { limit: 15 } });
    mount(els.activity, items.length ? h("div", { class: "list" }, items.map(activityItem)) : empty("No activity yet."));
  }
  async function loadChart() {
    if (!els.players_chart) return;
    const r = await api("analytics/server", { query: { days: 1 } });
    const pts = r.data.player_history.map((p) => ({ x: new Date(p.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), y: p.players }));
    mount(els.players_chart, lineChart(pts, { height: 180 }), h("div", { class: "small muted", style: { marginTop: "6px" } }, r.data.history_note));
  }
  await Promise.all([load(), loadActivity(), loadChart()]);
  const refreshMs = (prefs.refresh_seconds || L.settings("dashboard.refresh_seconds") || 15) * 1000;
  const iv = setInterval(load, Math.max(refreshMs, 5000) * 2);
  const off = [live(["incident.", "unit.", "erlc.synced", "shift.", "bolo."], load, 700), live(["incident.", "unit.", "shift.", "bolo.", "record.", "report.", "traffic."], loadActivity, 900)];
  return () => { clearInterval(iv); off.forEach((f) => f()); };
}

export function activityItem(a) {
  return h("div", { class: "list-item" + (a.link ? " clickable" : ""), onclick: a.link ? () => { location.hash = a.link.replace(/^\/?#/, "#"); } : null },
    h("span", { class: "badge" }, a.category),
    h("div", { class: "grow" }, h("div", { class: "title truncate" }, a.description),
      h("div", { class: "meta" }, [a.department, a.reference, a.source !== "web" ? `via ${a.source}` : null].filter(Boolean).join(" · "))),
    h("span", { class: "meta", title: new Date(a.created_at).toLocaleString() }, ago(a.created_at)));
}

function serverWidget(ov) {
  if (!ov) return empty("No access.");
  const srv = ov.server;
  if (!srv) return h("div", { class: "stack" }, h("div", { class: "notice " + (ov.api_error ? "bad" : "") },
    ov.api_error ? ov.api_error.message : ov.configured ? "Waiting for the first sync from the ERLC API…" : "Add your ERLC server key in System → API Configuration to see live data."),
    can("system.configure") ? h("a", { class: "btn sm", href: "#/system/api" }, "API configuration") : null);
  const pct = srv.capacity_pct;
  const bar = h("span"); bar.style.width = `${pct}%`; if (pct > 90) bar.style.background = "var(--warn)";
  const teams = Object.entries(srv.teams || {}).sort((a, b) => b[1] - a[1]);
  return h("div", { class: "stack" },
    h("div", { class: "row between" }, h("h2", srv.name), statusPill(ov.status === "online" ? "Online" : ov.status, ov.status === "online" ? "#22c55e" : "#f59e0b")),
    h("div", { class: "row between small" }, h("span", `${srv.current_players} / ${srv.max_players} players`), h("span", { class: "muted" }, `${pct}%`)),
    h("div", { class: "meter" }, bar),
    h("div", { class: "row wrap" }, teams.map(([t, n]) => h("span", { class: "chip" }, `${t}: ${n}`))),
    h("div", { class: "small muted" }, `Join code ${srv.join_key || "—"} · Queue ${srv.queue?.length || 0} · Last sync ${ago(ov.fetched_at)}`, ov.stale ? " · ⚠ stale" : ""),
    h("div", { class: "disclaimer" }, icon("check"), "Live data from the official ERLC API"));
}

function unitsWidget(units) {
  if (!units.length) return empty("No units registered.", "car");
  return h("div", { class: "list" }, units.slice(0, 10).map((u) => h("div", { class: "unit-row" },
    h("span", { class: "cs" }, u.callsign), h("span", { class: "grow muted small truncate" }, u.department, " · ", u.unit_type),
    u.current_incident_number ? h("span", { class: "badge" }, u.current_incident_number) : null, statusPill(u.status_label, u.status_color))));
}

function queueWidget(items) {
  if (!items.length) return empty("Queue is clear.", "check");
  return h("div", { class: "list" }, items.slice(0, 8).map((i) => h("a", { class: "queue-item" + (i.overdue ? " overdue" : ""), href: `#/cad/incident/${i.id}`, style: { color: "inherit", textDecoration: "none" } },
    prio(i.priority, i.priority_color, i.priority_name),
    h("div", { class: "q-main" }, h("div", { class: "q-title" }, i.number, h("span", { class: "muted small" }, i.category_label)), h("div", { class: "q-sub truncate" }, i.location || i.description)),
    h("div", { class: "q-timer" }, h("div", { dataset: { since: i.created_at } }, ""), h("div", { class: "small muted" }, i.units.length ? i.units.map((u) => u.callsign).join(", ") : "unassigned")))));
}

async function customize(order, hidden) {
  const items = [...new Set([...order, ...Object.keys(WIDGETS)])].filter((k) => !WIDGETS[k].perm || can(WIDGETS[k].perm));
  const list = h("div");
  const render = () => {
    list.replaceChildren(...items.map((k, idx) => h("div", { class: "sortable-item" },
      h("input", { type: "checkbox", checked: !hidden.has(k), onchange: (e) => (e.target.checked ? hidden.delete(k) : hidden.add(k)) }),
      h("span", { style: { flex: 1 } }, WIDGETS[k].title),
      h("button", { class: "btn xs", type: "button", disabled: idx === 0, onclick: () => { [items[idx - 1], items[idx]] = [items[idx], items[idx - 1]]; render(); } }, "↑"),
      h("button", { class: "btn xs", type: "button", disabled: idx === items.length - 1, onclick: () => { [items[idx + 1], items[idx]] = [items[idx], items[idx + 1]]; render(); } }, "↓"))));
  };
  render();
  const ok = await modal("Customize dashboard", h("div", h("p", { class: "muted small" }, "Choose and order the widgets on your overview. Saved to your account."), list), {
    submitLabel: "Save layout",
    onSubmit: async () => {
      await api("me/preferences", { method: "PUT", body: { dashboard_widgets: items, dashboard_hidden: [...hidden] } });
      state.me.preferences = { ...state.me.preferences, dashboard_widgets: items, dashboard_hidden: [...hidden] };
    },
  });
  if (ok) { toast("Dashboard layout saved", "ok"); location.hash = "#/"; window.dispatchEvent(new HashChangeEvent("hashchange")); }
}
