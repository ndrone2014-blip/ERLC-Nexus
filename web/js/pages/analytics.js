import { api, btn, card, deptOptions, duration, empty, h, icon, mount, pageHead, stat, table } from "../core.js";
import { barChart, donut, hbars, lineChart } from "../charts.js";

const TITLES = { server: "Server Analytics", cad: "CAD Analytics", departments: "Department Analytics", dispatchers: "Dispatcher Analytics", activity: "Activity Reports" };

export async function page(root, [kind]) {
  const preset = h("select", [["1", "Today (24h)"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["custom", "Custom range"]].map(([v, l]) => h("option", { value: v, selected: v === "7" }, l)));
  const from = h("input", { type: "date", style: { display: "none" } }), to = h("input", { type: "date", style: { display: "none" } });
  const dept = h("select", { style: { display: kind === "cad" ? "" : "none" } }, deptOptions("All departments").map(([v, l]) => h("option", { value: v }, l)));
  const body = h("div");
  const params = () => {
    const q = { department_id: dept.value };
    if (preset.value === "custom") { if (from.value) q.date_from = new Date(from.value).toISOString(); if (to.value) q.date_to = new Date(to.value + "T23:59:59").toISOString(); }
    else q.days = preset.value;
    return q;
  };
  const csv = h("a", { class: "btn sm", download: "" }, icon("download"), "Export CSV");
  const load = async () => {
    const q = params();
    csv.href = `/api/analytics/${kind}.csv?` + new URLSearchParams(Object.entries(q).filter(([, v]) => v)).toString();
    const r = await api(`analytics/${kind}`, { query: q });
    const d = r.data;
    const periodNote = h("div", { class: "small muted", style: { marginBottom: "12px" } }, `Period: ${new Date(r.period.from).toLocaleString()} → ${new Date(r.period.to).toLocaleString()}. Derived statistics are labelled and only calculated when the underlying data exists.`);
    if (kind === "server") {
      mount(body, periodNote, h("div", { class: "grid g4", style: { marginBottom: "14px" } },
        stat("Current players", d.current ? `${d.current.players}/${d.current.max}` : "—", { tone: "accent" }), stat("Peak players", d.peak_players ?? "—"),
        stat("Average players", d.average_players ?? "—", { sub: "derived from samples" }), stat("API availability", d.api_availability_pct != null ? `${d.api_availability_pct}%` : "—", { sub: `${d.sync_count} syncs · ${d.sync_failures} failed · avg ${d.avg_sync_ms ?? "—"} ms` })),
        h("div", { class: "grid g2" },
          card("Player count", h("div", lineChart(d.player_history.map((p) => ({ x: new Date(p.t).toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }), y: p.players }))), h("div", { class: "small muted" }, d.history_note)), { cls: "span2" }),
          card("Average team distribution", hbars(Object.entries(d.team_distribution_avg).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value))),
          card("Current teams", d.current ? donut(Object.entries(d.current.teams).map(([label, value]) => ({ label, value }))) : empty("No live data."))));
    } else if (kind === "cad") {
      mount(body, periodNote, h("div", { class: "grid g4", style: { marginBottom: "14px" } },
        stat("Total incidents", d.total, { tone: "accent" }), stat("Open / closed", `${d.open} / ${d.closed}`),
        stat("Avg time awaiting dispatch", duration(d.avg_awaiting_dispatch_seconds), { sub: d.notes.avg_awaiting_dispatch_seconds }),
        stat("Avg resolution time", duration(d.avg_resolution_seconds), { sub: d.notes.avg_resolution_seconds })),
        h("div", { class: "grid g2" },
          card("Incident creation trend", barChart(d.trend.map((t) => ({ label: t.day.slice(5), value: t.count }))), { cls: "span2" }),
          card("By category", hbars(Object.entries(d.by_category).map(([label, value]) => ({ label, value })))),
          card("By priority", donut(Object.entries(d.by_priority).map(([label, value]) => ({ label, value })))),
          card("By source", hbars(Object.entries(d.by_source).map(([label, value]) => ({ label: { web: "Website", discord: "Discord", erlc_api: "ERLC API 911", map: "Map" }[label] || label, value })))),
          card("Response", h("div", { class: "grid g2" }, stat("Avg response (dispatch → on scene)", duration(d.avg_response_seconds), { sub: d.notes.avg_response_seconds }), stat("Unit assignments", d.unit_assignments)))));
    } else if (kind === "departments") {
      mount(body, periodNote, h("div", { class: "grid g2" },
        card("Shift hours by department", barChart(d.map((x) => ({ label: x.department, value: x.shift_hours, color: x.color })))),
        card("Incident participation", barChart(d.map((x) => ({ label: x.department, value: x.incidents_participated, color: x.color })))),
        card("Department summary", table([{ label: "Department", key: "department" }, { label: "Members", key: "active_members", num: true }, { label: "Shift hours", key: "shift_hours", num: true },
          { label: "Shifts", key: "shifts", num: true }, { label: "Participation", render: (x) => x.participation_pct != null ? `${x.participation_pct}%` : "—", num: true },
          { label: "Incidents", key: "incidents_participated", num: true }, { label: "Units", key: "units", num: true }, { label: "Assignments / unit", render: (x) => x.assignments_per_unit ?? "—", num: true }], d), { flush: true, cls: "span2" })));
    } else if (kind === "dispatchers") {
      mount(body, periodNote, h("div", { class: "notice", style: { marginBottom: "14px" } }, "Listed alphabetically. Raw counts depend on shift length and call volume, so they are shown for workload awareness — not as a ranking."),
        card("Dispatcher workload", table([{ label: "Dispatcher", key: "name" }, { label: "Calls created", key: "calls_created", num: true }, { label: "Calls handled", key: "calls_handled", num: true },
          { label: "Calls closed", key: "calls_closed", num: true }, { label: "Active now", key: "active_workload", num: true }, { label: "Avg handling", render: (x) => duration(x.avg_handling_seconds), num: true },
          { label: "Shift hours", key: "shift_hours", num: true }], d, { emptyText: "No dispatch activity in this period." }), { flush: true }));
    } else {
      mount(body, periodNote, h("div", { class: "grid g2" },
        card("Events by category", donut(Object.entries(d.by_category).map(([label, value]) => ({ label, value })))),
        card("Most common actions", hbars(Object.entries(d.top_actions).map(([label, value]) => ({ label, value })))),
        card("Total", stat("Audited events", d.total_events))));
    }
  };
  preset.addEventListener("change", () => { const c = preset.value === "custom"; from.style.display = to.style.display = c ? "" : "none"; if (!c) load(); });
  [from, to, dept].forEach((x) => x.addEventListener("change", load));
  mount(root, pageHead(TITLES[kind], "Daily, weekly, monthly or custom reports.", [preset, from, to, dept, csv, btn("Print", () => window.print(), { sm: true, ico: "printer" })]), body);
  await load();
}
