import { api, ago, badge, btn, can, card, confirmDialog, deptOptions, disclaimer, empty, fmtTime, form, h, icon, kv, L, live, modal, mount, pageHead, prio, stat, state, statusPill, table, tabs, toast } from "../core.js";
import { barChart, donut } from "../charts.js";

// ---------------------------------------------------------------- shared helpers
export function incidentFields() {
  const cats = L.categories();
  return [
    { section: "Identification" },
    { name: "category", label: "Category", type: "select", required: true, options: cats.map((c) => [c.key, c.label]) },
    { name: "subtype", label: "Subtype", list: "nx-subtypes", placeholder: "e.g. Robbery" },
    { name: "priority", label: "Priority", type: "select", numeric: true, options: L.priorities().map((p) => [p.level, `P${p.level} — ${p.name}`]) },
    { name: "department_id", label: "Department", type: "select", options: deptOptions(), nullable: true, numeric: true },
    { section: "Caller" },
    { name: "caller_name", label: "Caller name" }, { name: "caller_identifier", label: "Caller identifier", hint: "Roblox name or callsign" },
    { name: "caller_contact", label: "Contact (if volunteered)" }, { name: "caller_description", label: "Caller description" },
    { name: "caller_notes", label: "Caller notes", type: "textarea", full: true, rows: 2 },
    { section: "Location" },
    { name: "location_id", label: "Location preset", type: "select", options: [["", "— None —"]], nullable: true, numeric: true },
    { name: "location_name", label: "Location name" }, { name: "street", label: "Street / road" }, { name: "intersection", label: "Intersection" },
    { name: "postal", label: "Postal" }, { name: "map_x", label: "Map X", type: "number", step: "any", nullable: true }, { name: "map_z", label: "Map Z", type: "number", step: "any", nullable: true },
    { name: "location_instructions", label: "Additional location instructions", full: true },
    { section: "Incident" },
    { name: "description", label: "Description", type: "textarea", full: true, required: true, rows: 3 },
    { name: "circumstances", label: "Reported circumstances", type: "textarea", full: true, rows: 2 },
    { name: "details", label: "Additional details", type: "textarea", full: true, rows: 2 },
  ];
}

export async function incidentDialog(values = {}, { title = "New incident", id = null } = {}) {
  const f = form(incidentFields(), { priority: 3, category: L.categories()[0]?.key, department_id: state.me.preferences?.default_department_id ?? "", ...values });
  const locs = await api("map/locations").catch(() => []);
  const sel = f.inputs.location_id;
  locs.forEach((l) => sel.appendChild(h("option", { value: l.id, selected: String(l.id) === String(values.location_id) }, `${l.name}${l.verified ? "" : " (unverified)"}`)));
  sel.addEventListener("change", () => { const l = locs.find((x) => String(x.id) === sel.value); if (l) { f.inputs.location_name.value = l.name; f.inputs.map_x.value = l.x; f.inputs.map_z.value = l.z; f.inputs.postal.value = l.postal || ""; f.inputs.street.value = l.street || ""; } });
  const dl = h("datalist", { id: "nx-subtypes" });
  const fillSub = () => { const c = L.categories().find((x) => x.key === f.inputs.category.value); dl.replaceChildren(...(c?.subtypes || []).map((s) => h("option", { value: s }))); };
  f.inputs.category.addEventListener("change", fillSub); fillSub();
  return modal(title, h("div", f.el, dl), { wide: true, submitLabel: id ? "Save changes" : "Create incident", onSubmit: async () => {
    const v = f.values();
    const r = id ? await api(`cad/incidents/${id}`, { method: "PATCH", body: v }) : await api("cad/incidents", { method: "POST", body: { ...v, source: values.source } });
    toast(`${r.number} ${id ? "updated" : "created"}`, "ok");
    return r;
  } });
}

export function incidentRow(i) {
  return [prio(i.priority, i.priority_color, i.priority_name), h("div", h("div", { style: { fontWeight: 600 } }, i.number), h("div", { class: "muted small" }, i.category_label, i.subtype ? ` · ${i.subtype}` : ""))];
}
const incidentColumns = [
  { label: "P", render: (i) => prio(i.priority, i.priority_color, i.priority_name) },
  { label: "Incident", render: (i) => h("div", h("div", { style: { fontWeight: 600 } }, i.number), h("div", { class: "muted small" }, i.category_label, i.subtype ? ` · ${i.subtype}` : "")) },
  { label: "Location", render: (i) => i.location || "—" },
  { label: "Status", render: (i) => statusPill(i.status_label, i.status_color) },
  { label: "Units", render: (i) => i.units.length ? i.units.map((u) => u.callsign).join(", ") : h("span", { class: "muted" }, "—") },
  { label: "Dept", render: (i) => i.department || "—" },
  { label: "Created", render: (i) => h("span", { title: fmtTime(i.created_at) }, ago(i.created_at)) },
];

export async function statusDialog(inc) {
  const f = form([{ name: "status", label: "Status", type: "select", options: L.incidentStatuses().map((s) => [s.key, s.label]) },
    { name: "disposition", label: "Disposition (when closing)", full: true, placeholder: "e.g. Report taken, Arrest made, Unfounded" }], { status: inc.status, disposition: inc.disposition || "" });
  return modal(`Status — ${inc.number}`, f.el, { submitLabel: "Update status", onSubmit: async () => api(`cad/incidents/${inc.id}/status`, { method: "POST", body: f.values() }) });
}

export async function assignDialog(inc) {
  const units = await api("cad/units");
  const f = form([{ name: "unit", label: "Unit", type: "select", options: units.map((u) => [u.id, `${u.callsign} — ${u.status_label}${u.current_incident_number ? ` (on ${u.current_incident_number})` : ""}`]) },
    { name: "primary", label: "Primary unit", type: "checkbox" }]);
  return modal(`Assign unit — ${inc.number}`, units.length ? f.el : empty("No units registered."), { submitLabel: "Assign", onSubmit: async () => {
    const v = f.values(); return api(`cad/incidents/${inc.id}/assign`, { method: "POST", body: { unit: Number(v.unit), primary: v.primary } });
  } });
}

// ---------------------------------------------------------------- pages
export async function overview(root) {
  const body = h("div");
  const load = async () => {
    const [ov, q, units, calls] = await Promise.all([api("overview"), api("cad/queue"), api("cad/units"), api("cad/erlc-calls")]);
    const byCat = {}; q.forEach((i) => { byCat[i.category_label] = (byCat[i.category_label] || 0) + 1; });
    const byStatus = {}; units.forEach((u) => { byStatus[u.status_label] = byStatus[u.status_label] || { label: u.status_label, value: 0, color: u.status_color }; byStatus[u.status_label].value++; });
    mount(body,
      h("div", { class: "grid g4", style: { marginBottom: "14px" } },
        stat("Active incidents", ov.cad.active, { tone: "accent", ico: "radio" }), stat("Emergency (P1)", ov.cad.emergency, { tone: ov.cad.emergency ? "bad" : "", ico: "alert" }),
        stat("Awaiting dispatch", ov.cad.awaiting_dispatch, { tone: ov.cad.awaiting_dispatch ? "warn" : "", ico: "clock" }),
        stat("Units available", `${ov.units.available}/${ov.units.total}`, { tone: "ok", ico: "car" })),
      calls.length ? card(h("h3", icon("phone"), `In-game emergency calls (${calls.length})`), h("div", { class: "notice" }, "New 911 calls reported by the official ERLC API are waiting in the ", h("a", { href: "#/cad/dispatch" }, "Dispatch Center"), "."), { cls: "", }) : null,
      h("div", { class: "grid g2", style: { marginTop: "14px" } },
        card("Active incidents", table(incidentColumns, q, { onRow: (i) => { location.hash = `#/cad/incident/${i.id}`; }, emptyText: "No active incidents." }), { flush: true, cls: "span2",
          actions: [can("cad.incident.create") ? btn("New incident", async () => { const r = await incidentDialog(); if (r) location.hash = `#/cad/incident/${r.id}`; }, { sm: true, kind: "primary", ico: "plus" }) : null] }),
        card("Active incidents by category", barChart(Object.entries(byCat).map(([label, value]) => ({ label, value })))),
        card("Units by status", donut(Object.values(byStatus)))));
  };
  mount(root, pageHead("CAD Overview", "The current state of dispatch operations.", [h("a", { class: "btn sm", href: "#/cad/dispatch" }, icon("headset"), "Dispatch Center"), h("a", { class: "btn sm", href: "#/cad/map" }, icon("map"), "Live Map")]), body);
  await load();
  return live(["incident.", "unit.", "erlc.911"], load);
}

export async function calls(root) {
  const body = h("div");
  let sort = "priority", dept = "";
  const load = async () => {
    const items = await api("cad/queue", { query: { sort, department_id: dept } });
    mount(body, table([...incidentColumns, { label: "Waiting", render: (i) => i.awaiting_dispatch ? h("span", { class: "mono", style: { color: i.overdue ? "var(--bad)" : "" }, dataset: { since: i.created_at } }, "") : h("span", { class: "muted" }, "dispatched") }],
      items, { onRow: (i) => { location.hash = `#/cad/incident/${i.id}`; }, emptyText: "No active calls." }));
  };
  const sortSel = h("select", { onchange: (e) => { sort = e.target.value; load(); } }, h("option", { value: "priority" }, "Sort by priority"), h("option", { value: "age" }, "Oldest first"), h("option", { value: "recent" }, "Newest first"));
  const deptSel = h("select", { onchange: (e) => { dept = e.target.value; load(); } }, deptOptions("All departments").map(([v, l]) => h("option", { value: v }, l)));
  mount(root, pageHead("Active Calls", "Every open incident with live waiting timers.", [can("cad.incident.create") ? btn("New incident", async () => { if (await incidentDialog()) load(); }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, sortSel, deptSel), body, { flush: true }));
  await load();
  return live(["incident.", "unit.assigned"], load);
}

export async function history(root) {
  const body = h("div");
  const q = h("input", { type: "search", placeholder: "Number, location, caller, description" });
  const state_ = h("select", h("option", { value: "closed" }, "Closed"), h("option", { value: "all" }, "All"), h("option", { value: "open" }, "Open"));
  const cat = h("select", h("option", { value: "" }, "All categories"), L.categories().map((c) => h("option", { value: c.key }, c.label)));
  const dept = h("select", deptOptions("All departments").map(([v, l]) => h("option", { value: v }, l)));
  const from = h("input", { type: "date" }), to = h("input", { type: "date" });
  let offset = 0;
  const load = async () => {
    const r = await api("cad/incidents", { query: { state: state_.value, q: q.value, category: cat.value, department_id: dept.value, sort: "recent", limit: 50, offset,
      date_from: from.value ? new Date(from.value).toISOString() : "", date_to: to.value ? new Date(to.value + "T23:59:59").toISOString() : "" } });
    mount(body, table([...incidentColumns, { label: "Closed", render: (i) => i.closed_at ? fmtTime(i.closed_at) : "—" }], r.items, { onRow: (i) => { location.hash = `#/cad/incident/${i.id}`; } }),
      h("div", { class: "pager" }, h("span", `${r.total} incident(s)`), h("div", { class: "row" }, btn("Previous", () => { offset = Math.max(0, offset - 50); load(); }, { sm: true, disabled: offset === 0 }),
        btn("Next", () => { offset += 50; load(); }, { sm: true, disabled: offset + 50 >= r.total }))));
  };
  [q, state_, cat, dept, from, to].forEach((el) => el.addEventListener("change", () => { offset = 0; load(); }));
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { offset = 0; load(); } });
  mount(root, pageHead("Incident History", "Search every incident ever recorded. History is preserved after closure."),
    card(h("div", { class: "filters" }, q, state_, cat, dept, from, to), body, { flush: true }));
  await load();
}

export async function incident(root, [id]) {
  const head = h("div"), main = h("div", { class: "cad-col" }), side = h("div", { class: "cad-col" });
  mount(root, head, h("div", { class: "grid", style: { gridTemplateColumns: "minmax(0,1fr) 340px", alignItems: "start" } }, main, side));
  const load = async () => {
    const d = await api(`cad/incidents/${id}`);
    const editable = can("cad.incident.edit");
    mount(head, pageHead(h("span", { class: "row" }, prio(d.priority, d.priority_color, d.priority_name), d.number, statusPill(d.status_label, d.status_color)),
      `${d.category_label}${d.subtype ? " · " + d.subtype : ""} · created ${fmtTime(d.created_at)} via ${d.source}${d.source === "erlc_api" ? " (official ERLC API call)" : ""}`, [
        editable ? btn("Edit", async () => { if (await incidentDialog(d, { title: `Edit ${d.number}`, id: d.id })) load(); }, { sm: true, ico: "edit" }) : null,
        btn("Status", async () => { if (await statusDialog(d)) load(); }, { sm: true }),
        can("cad.dispatch") || can("cad.unit.self") ? btn("Assign unit", async () => { if (await assignDialog(d)) load(); }, { sm: true, kind: "primary", ico: "car" }) : null,
        can("cad.reports.create") ? h("a", { class: "btn sm", href: `#/records/report/new?incident=${d.id}` }, icon("file"), "Write report") : null,
        btn("Print", () => window.print(), { sm: true, ico: "printer" })]));
    const noteInput = h("textarea", { rows: 2, placeholder: "Add a dispatcher note…  (Alt+M)", dataset: { noteInput: "1" } });
    const restricted = h("input", { type: "checkbox" });
    mount(main,
      card("Incident", h("div", { class: "grid g2" },
        kv([["Location", d.location_name], ["Street", d.street], ["Intersection", d.intersection], ["Postal", d.postal],
          ["Map position", d.map_x != null ? `${Math.round(d.map_x)}, ${Math.round(d.map_z)}` : null], ["Instructions", d.location_instructions]]),
        kv([["Department", d.department], ["Dispatcher", d.dispatcher], ["Supervisor", d.supervisor], ["Created by", d.created_by],
          ["Dispatched", fmtTime(d.dispatched_at)], ["On scene", fmtTime(d.on_scene_at)], ["Closed", fmtTime(d.closed_at)], ["Disposition", d.disposition]]),
        h("div", { class: "span2 stack" }, h("h4", "Description"), h("div", { style: { whiteSpace: "pre-wrap" } }, d.description || "—"),
          d.circumstances ? [h("h4", "Reported circumstances"), h("div", { style: { whiteSpace: "pre-wrap" } }, d.circumstances)] : null,
          d.details ? [h("h4", "Additional details"), h("div", { style: { whiteSpace: "pre-wrap" } }, d.details)] : null))),
      card("Caller", kv([["Name", d.caller_name], ["Identifier", d.caller_identifier], ["Contact", d.caller_contact], ["Description", d.caller_description], ["Notes", d.caller_notes]])),
      card(`Timeline (${d.timeline.length})`, h("ul", { class: "timeline" }, d.timeline.slice().reverse().map((t) => h("li",
        h("div", h("b", t.user), " — ", t.message || t.event, (t.old || t.new) && ["status_changed", "priority_changed"].includes(t.event) ? h("span", { class: "muted" }, ` (${t.old ?? "—"} → ${t.new ?? "—"})`) : null),
        h("div", { class: "when" }, fmtTime(t.created_at)))))));
    mount(side,
      card(`Units (${d.units.length})`, d.units.length ? h("div", { class: "list" }, d.units.map((u) => h("div", { class: "unit-row" },
        h("span", { class: "cs" }, u.callsign), h("span", { class: "grow muted small" }, u.status.replace(/_/g, " "), u.is_primary ? " · primary" : ""),
        can("cad.dispatch") ? btn("Clear", async () => { await api(`cad/incidents/${d.id}/clear`, { method: "POST", body: { unit: u.id } }); load(); }, { sm: true }) : null))) : empty("No units assigned.", "car"), { flush: true }),
      card(`Notes (${d.notes.length})`, h("div", { class: "stack" },
        d.notes.length ? h("div", { class: "list" }, d.notes.map((n) => h("div", { class: "list-item" }, h("div", { class: "grow" },
          h("div", { class: "meta" }, n.user || "—", " · ", fmtTime(n.created_at), n.restricted ? " · restricted" : ""), h("div", { style: { whiteSpace: "pre-wrap" } }, n.body))))) : null,
        noteInput, h("div", { class: "row between" }, can("cad.incident.restricted") ? h("label", { class: "check" }, restricted, "Restricted") : h("span"),
          btn("Add note", async () => { if (!noteInput.value.trim()) return; await api(`cad/incidents/${d.id}/notes`, { method: "POST", body: { body: noteInput.value, restricted: restricted.checked } }); load(); }, { sm: true, kind: "primary" })))),
      card("Related records", h("div", { class: "stack" },
        d.links.length ? h("div", { class: "list" }, d.links.map((l) => h("a", { class: "list-item clickable", href: recordHref(l.type, l.id), style: { color: "inherit" } }, badge(l.type), h("span", { class: "grow" }, l.label)))) : h("div", { class: "muted small" }, "No linked records."),
        can("cad.incident.edit") || can("cad.records.edit") ? btn("Link record", async () => { if (await linkDialog(d.id)) load(); }, { sm: true, ico: "link" }) : null)),
      card("Assignment history", table([{ label: "Unit", key: "callsign" }, { label: "Assigned", render: (a) => fmtTime(a.assigned_at, { time: true }) },
        { label: "Cleared", render: (a) => a.cleared_at ? fmtTime(a.cleared_at, { time: true }) : "active" }], d.assignment_history, { emptyText: "None." }), { flush: true }));
  };
  await load();
  return live(["incident.changed", "unit."], (ev) => { if (!ev.payload?.id || String(ev.payload.id) === String(id) || ev.kind.startsWith("unit.")) load(); }, 500);
}

export function recordHref(type, id) {
  return { person: `#/records/person/${id}`, vehicle: `#/records/vehicle/${id}`, bolo: `#/records/bolo/${id}`, case: `#/records/case/${id}`,
    report: `#/records/report/${id}`, traffic: `#/cad/traffic/${id}`, incident: `#/cad/incident/${id}`, warrant: `#/records/warrants` }[type] || "#/";
}

async function linkDialog(incidentId) {
  const type = h("select", ["person", "vehicle", "bolo", "warrant", "case", "traffic", "report", "incident"].map((t) => h("option", { value: t }, t)));
  const q = h("input", { type: "search", placeholder: "Search…" });
  const results = h("div", { class: "list", style: { maxHeight: "260px", overflowY: "auto", marginTop: "8px" } });
  let chosen = null;
  const run = async () => {
    if (q.value.trim().length < 2) return;
    const scopes = { person: "people", vehicle: "vehicles", bolo: "bolos", traffic: "traffic", report: "reports", incident: "incidents" }[type.value];
    let rows = [];
    if (scopes) { const r = await api("search", { query: { q: q.value, scopes, limit: 10 }, silent: true }).catch(() => null); rows = r?.results?.[scopes] || []; }
    else if (type.value === "warrant") rows = (await api("records/warrants", { query: { q: q.value, status: "all" } })).map((w) => ({ id: w.id, title: w.number, summary: w.subject_name }));
    else if (type.value === "case") rows = (await api("records/cases", { query: { q: q.value } })).map((c) => ({ id: c.id, title: c.number, summary: c.title }));
    mount(results, rows.length ? rows.map((r) => h("div", { class: "list-item clickable", onclick: (e) => { chosen = r.id; results.querySelectorAll(".list-item").forEach((x) => (x.style.background = "")); e.currentTarget.style.background = "var(--accent-soft)"; } },
      h("div", { class: "grow" }, h("div", { class: "title" }, r.title), h("div", { class: "meta" }, r.summary)))) : empty("No matches."));
  };
  q.addEventListener("input", () => setTimeout(run, 250)); type.addEventListener("change", run);
  return modal("Link a record", h("div", h("div", { class: "row" }, type, q), results), { submitLabel: "Link", onSubmit: async () => {
    if (!chosen) { toast("Choose a record first", "warn"); return false; }
    return api(`cad/incidents/${incidentId}/links`, { method: "POST", body: { type: type.value, id: chosen } });
  } });
}

export async function units(root) {
  const body = h("div");
  const deptSel = h("select", deptOptions("All departments").map(([v, l]) => h("option", { value: v }, l)));
  const groupSel = h("select", h("option", { value: "" }, "All statuses"), h("option", { value: "available" }, "Available"), h("option", { value: "busy" }, "Busy"), h("option", { value: "unavailable" }, "Unavailable"));
  const load = async () => {
    const rows = await api("cad/units", { query: { department_id: deptSel.value, group: groupSel.value } });
    mount(body, table([
      { label: "Callsign", render: (u) => h("span", { class: "mono", style: { fontWeight: 700 } }, u.callsign) },
      { label: "Department", render: (u) => u.department || "—" }, { label: "Type", key: "unit_type" },
      { label: "Status", render: (u) => statusPill(u.status_label, u.status_color) },
      { label: "Incident", render: (u) => u.current_incident_number ? h("a", { href: `#/cad/incident/${u.current_incident_id}`, onclick: (e) => e.stopPropagation() }, u.current_incident_number) : "—" },
      { label: "Personnel", render: (u) => u.members.map((m) => m.name).join(", ") || "—" },
      { label: "Location", render: (u) => u.location.text ? h("span", u.location.text, " ", badge(u.location.source === "api" ? "API" : u.location.source)) : "—" },
      { label: "Since", render: (u) => ago(u.status_changed_at) },
    ], rows, { onRow: (u) => unitDialog(u.id).then(load), emptyText: "No units. Register one to get started." }));
  };
  deptSel.onchange = load; groupSel.onchange = load;
  mount(root, pageHead("Unit Management", "Register units, manage personnel, statuses and locations.", [
    canAnyUnit() ? btn("Register unit", async () => { if (await registerUnitDialog()) load(); }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, deptSel, groupSel), body, { flush: true }));
  await load();
  return live(["unit."], load);
}
const canAnyUnit = () => can("cad.unit.manage") || can("cad.unit.self");

export async function registerUnitDialog() {
  const depts = L.departments().filter((d) => can("cad.unit.manage") || state.me.department_ids.includes(d.id));
  const f = form([
    { name: "department_id", label: "Department", type: "select", required: true, numeric: true, options: depts.map((d) => [d.id, d.abbreviation + " — " + d.name]) },
    { name: "unit_type", label: "Unit type", list: "nx-unit-types" },
    { name: "callsign", label: "Callsign", hint: "Leave empty to use the department's callsign format" },
    { name: "vehicle_description", label: "Vehicle" }, { name: "notes", label: "Notes", type: "textarea", full: true, rows: 2 },
  ], { department_id: state.me.preferences?.default_department_id || depts[0]?.id });
  const dl = h("datalist", { id: "nx-unit-types" });
  const fill = async () => {
    const d = L.dept(Number(f.inputs.department_id.value));
    dl.replaceChildren(...(d?.unit_types || []).map((t) => h("option", { value: t })));
    if (d) { const s = await api("cad/callsign-suggest", { query: { department_id: d.id, unit_type: f.inputs.unit_type.value }, silent: true }).catch(() => null); if (s) f.inputs.callsign.placeholder = `Suggested: ${s.callsign}`; }
  };
  f.inputs.department_id.addEventListener("change", fill); f.inputs.unit_type.addEventListener("change", fill); fill();
  return modal("Register unit", h("div", f.el, dl), { submitLabel: "Register", onSubmit: async () => { const r = await api("cad/units", { method: "POST", body: f.values() }); toast(`${r.callsign} registered`, "ok"); return r; } });
}

export async function unitDialog(unitId) {
  const u = await api(`cad/units/${unitId}`);
  const manage = can("cad.unit.manage");
  const statusSel = h("select", L.unitStatuses().map((s) => h("option", { value: s.key, selected: s.key === u.status }, `${s.label}${s.code ? " (" + s.code + ")" : ""}`)));
  const locText = h("input", { value: u.location.text || "", placeholder: "Location description" });
  const locPreset = h("select", h("option", { value: "" }, "— Preset —"));
  (await api("map/locations").catch(() => [])).forEach((l) => locPreset.appendChild(h("option", { value: l.id }, l.name)));
  const edit = form([{ name: "callsign", label: "Callsign" }, { name: "unit_type", label: "Type" }, { name: "vehicle_description", label: "Vehicle" }, { name: "notes", label: "Notes", type: "textarea", full: true, rows: 2 }], u);
  const memberPick = h("input", { placeholder: "Add member by name…", list: "nx-users" });
  const dl = h("datalist", { id: "nx-users" });
  memberPick.addEventListener("input", async () => { if (memberPick.value.length < 2) return; const us = await api("users", { query: { q: memberPick.value }, silent: true }).catch(() => []); dl.replaceChildren(...us.map((x) => h("option", { value: `${x.name} #${x.id}` }))); });
  const body = h("div", { class: "stack" },
    h("div", { class: "row wrap" }, statusPill(u.status_label, u.status_color), u.current_incident_number ? badge(`On ${u.current_incident_number}`) : null, badge(u.department || "—")),
    h("div", { class: "row" }, statusSel, btn("Set status", async () => { await api(`cad/units/${u.id}/status`, { method: "POST", body: { status: statusSel.value } }); toast("Status updated", "ok"); }, { sm: true, kind: "primary" })),
    h("div", { class: "row" }, locText, locPreset, btn("Set location", async () => {
      await api(`cad/units/${u.id}/location`, { method: "POST", body: { text: locText.value, location_id: locPreset.value ? Number(locPreset.value) : null } }); toast("Location updated (manual)", "ok");
    }, { sm: true })),
    h("div", { class: "small muted" }, u.location.source === "api" ? `Position from the official ERLC API ${ago(u.location.updated_at)} (linked Roblox account).` : "Manual locations are labelled as manual on the map."),
    h("h4", "Personnel"),
    h("div", { class: "list" }, u.members.map((m) => h("div", { class: "unit-row" }, h("span", { class: "grow" }, m.name, m.is_primary ? " ★" : "", m.roblox_linked ? "" : h("span", { class: "muted small" }, " · no Roblox link")),
      btn("Remove", async () => { await api(`cad/units/${u.id}/members/${m.user_id}`, { method: "DELETE" }); toast("Removed", "ok"); }, { sm: true })))),
    h("div", { class: "row" }, memberPick, dl, btn("Add", async () => { const id = Number((memberPick.value.match(/#(\d+)$/) || [])[1]); if (!id) return toast("Pick a user from the list", "warn"); await api(`cad/units/${u.id}/members`, { method: "POST", body: { user_id: id } }); toast("Member added", "ok"); }, { sm: true })),
    h("h4", "Details"), edit.el,
    h("h4", "History"), table([{ label: "Event", key: "event" }, { label: "Change", render: (e) => `${e.old ?? ""} → ${e.new ?? ""}` }, { label: "Incident", render: (e) => e.incident || "—" },
      { label: "By", render: (e) => e.user || "System" }, { label: "When", render: (e) => fmtTime(e.created_at) }], u.history.slice(0, 15), { emptyText: "No history." }));
  return modal(`Unit ${u.callsign}`, body, { wide: true, submitLabel: "Save details", footer: [
    manage ? btn("Remove unit", async () => { if (await confirmDialog("Remove unit", `Take ${u.callsign} out of service permanently? History is kept.`, "Remove")) { await api(`cad/units/${u.id}`, { method: "DELETE" }); toast("Unit removed", "ok"); document.querySelector(".modal-backdrop")?.remove(); } }, { kind: "danger" }) : null,
    h("span", { style: { flex: 1 } }), btn("Save details", async () => { await api(`cad/units/${u.id}`, { method: "PATCH", body: edit.values() }); toast("Saved", "ok"); document.querySelector(".modal-backdrop")?.remove(); }, { kind: "primary" })] });
}

export async function traffic(root) {
  const body = h("div");
  const status = h("select", h("option", { value: "active" }, "Active"), h("option", { value: "" }, "All"), h("option", { value: "completed" }, "Completed"), h("option", { value: "cancelled" }, "Cancelled"));
  const mine = h("input", { type: "checkbox" });
  const q = h("input", { type: "search", placeholder: "Plate, driver, location" });
  const load = async () => {
    const rows = await api("cad/traffic", { query: { status: status.value, mine: mine.checked, q: q.value } });
    mount(body, table([{ label: "Stop", render: (t) => h("b", t.number) }, { label: "Callsign", key: "callsign" }, { label: "Plate", render: (t) => h("code", t.plate || "—") },
      { label: "Driver", key: "driver_name" }, { label: "Location", key: "location" }, { label: "Reason", key: "reason" },
      { label: "Status", render: (t) => badge(t.status, t.status === "active" ? "#f59e0b" : t.status === "completed" ? "#22c55e" : "#64748b") },
      { label: "Outcome", key: "outcome" }, { label: "Duration", render: (t) => t.status === "active" ? h("span", { class: "mono", dataset: { since: t.started_at } }, "") : t.ended_at ? `${Math.round((new Date(t.ended_at) - new Date(t.started_at)) / 60000)} min` : "—" }],
      rows, { onRow: (t) => { location.hash = `#/cad/traffic/${t.id}`; }, emptyText: "No traffic stops." }));
  };
  [status, mine, q].forEach((x) => x.addEventListener("change", load));
  mount(root, pageHead("Traffic Stops", "Active and historical traffic stops.", [can("cad.traffic.manage") ? btn("Start traffic stop", async () => { const r = await trafficDialog(); if (r) location.hash = `#/cad/traffic/${r.id}`; }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, status, q, h("label", { class: "check" }, mine, "Mine only")), body, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  await load();
  return live(["traffic."], load);
}

export async function trafficDialog(values = {}) {
  const f = form([{ name: "plate", label: "Plate" }, { name: "vehicle_description", label: "Vehicle description" }, { name: "driver_name", label: "Driver" },
    { name: "location", label: "Location", required: true }, { name: "reason", label: "Reason for stop", full: true }, { name: "passengers", label: "Passengers", full: true },
    { name: "map_x", label: "Map X", type: "number", step: "any", nullable: true }, { name: "map_z", label: "Map Z", type: "number", step: "any", nullable: true }], values);
  const check = h("div");
  f.inputs.plate.addEventListener("change", async () => {
    if (!f.inputs.plate.value) return mount(check);
    const r = await api(`records/plate/${encodeURIComponent(f.inputs.plate.value)}`, { silent: true }).catch(() => null);
    if (!r) return;
    if (r.vehicle && !f.inputs.vehicle_description.value) f.inputs.vehicle_description.value = `${r.vehicle.color} ${r.vehicle.make} ${r.vehicle.model}`.trim();
    if (r.vehicle && !f.inputs.driver_name.value) f.inputs.driver_name.value = r.vehicle.owner_name || "";
    mount(check, r.alerts.length ? h("div", { class: "alert-banner" }, icon("alert"), r.alerts.join(" · ")) : h("div", { class: "notice ok" }, r.vehicle ? "No alerts on this plate." : "No vehicle record for this plate."));
  });
  return modal("Start traffic stop", h("div", { class: "stack" }, f.el, check), { submitLabel: "Start stop", onSubmit: async () => api("cad/traffic", { method: "POST", body: f.values() }) });
}

export async function trafficDetail(root, [id]) {
  const load = async () => {
    const t = await api(`cad/traffic/${id}`);
    const f = form([{ name: "driver_name", label: "Driver" }, { name: "plate", label: "Plate" }, { name: "vehicle_description", label: "Vehicle" }, { name: "location", label: "Location" },
      { name: "reason", label: "Reason", full: true }, { name: "passengers", label: "Passengers", full: true }, { name: "notes", label: "Notes", type: "textarea", full: true }], t);
    const outcome = h("select", ["Verbal Warning", "Written Warning", "Citation", "Arrest", "No Action", "Other"].map((o) => h("option", { value: o, selected: o === t.outcome }, o)));
    const active = t.status === "active";
    mount(root, pageHead(`Traffic stop ${t.number}`, `${t.callsign || "—"} · started ${fmtTime(t.started_at)}`, [badge(t.status, active ? "#f59e0b" : "#22c55e")]),
      h("div", { class: "grid g2" },
        card("Details", h("div", { class: "stack" }, f.el, btn("Save", async () => { await api(`cad/traffic/${t.id}`, { method: "PATCH", body: f.values() }); toast("Saved", "ok"); load(); }, { kind: "primary", sm: true }))),
        h("div", { class: "cad-col" },
          card("Complete stop", active ? h("div", { class: "stack" }, h("label", { class: "field" }, "Outcome", outcome),
            h("div", { class: "row" }, btn("Complete", async () => { await api(`cad/traffic/${t.id}/end`, { method: "POST", body: { outcome: outcome.value } }); toast("Stop completed", "ok"); load(); }, { kind: "primary" }),
              btn("Cancel stop", async () => { await api(`cad/traffic/${t.id}/end`, { method: "POST", body: { cancel: true } }); load(); }, { kind: "danger" })))
            : kv([["Outcome", t.outcome], ["Ended", fmtTime(t.ended_at)], ["Duration", t.ended_at ? `${Math.round((new Date(t.ended_at) - new Date(t.started_at)) / 60000)} min` : "—"]])),
          card("Linked records", kv([["Vehicle record", t.vehicle_id ? h("a", { href: `#/records/vehicle/${t.vehicle_id}` }, "Open vehicle") : "None"],
            ["Driver record", t.driver_person_id ? h("a", { href: `#/records/person/${t.driver_person_id}` }, "Open person") : "None"],
            ["Incident", t.incident_id ? h("a", { href: `#/cad/incident/${t.incident_id}` }, "Open incident") : "None"]])),
          card("Change history", table([{ label: "Changes", render: (r) => Object.keys(r.changes).join(", ") }, { label: "By", key: "user" }, { label: "When", render: (r) => fmtTime(r.created_at) }], t.history, { emptyText: "No edits." }), { flush: true }),
          disclaimer())));
  };
  await load();
}

export async function call911(root) {
  const f = form([{ name: "location_name", label: "Where is the emergency?", required: true, full: true }, { name: "description", label: "What is happening?", type: "textarea", required: true, full: true },
    { name: "caller_name", label: "Your name (roleplay)", value: state.me.name }, { name: "caller_contact", label: "Callback number (optional)" },
    { name: "category", label: "Type", type: "select", options: L.categories().map((c) => [c.key, c.label]) }]);
  mount(root, pageHead("Call 911", "Your call goes straight to the dispatch queue."), card(null, h("div", { class: "stack" }, f.el,
    h("div", btn("Place call", async (e) => { e.currentTarget.disabled = true; try { const r = await api("cad/911", { method: "POST", body: f.values() }); toast(`Call ${r.number} received by dispatch`, "ok", "911"); mount(root, pageHead("Call placed", ""), card(null, h("div", { class: "notice ok" }, `Your call ${r.number} is in the dispatch queue. Stay safe.`))); } finally { e.currentTarget.disabled = false; } }, { kind: "primary", ico: "phone" })))));
}

