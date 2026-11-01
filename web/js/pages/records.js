import { api, badge, btn, can, canAny, card, debounce, deptOptions, disclaimer, empty, fmtTime, form, h, icon, kv, live, modal, mount, pageHead, table, tabs, toast } from "../core.js";
import { recordHref } from "./cad.js";

const REG = ["Valid", "Expired", "Suspended", "Unregistered", "Stolen"];
const INS = ["Valid", "Expired", "None"];
const editRecords = () => canAny("cad.records.edit", "civ.use");

function historyTable(rows) {
  return table([{ label: "Action", key: "action" }, { label: "Changes", render: (r) => Object.entries(r.changes || {}).slice(0, 5).map(([k, v]) => `${k}: ${v.old ?? "—"} → ${v.new ?? "—"}`).join("; ") || "—" },
    { label: "By", key: "user" }, { label: "When", render: (r) => fmtTime(r.created_at) }], rows, { emptyText: "No changes recorded." });
}
function flags(list) { return (list || []).length ? h("div", { class: "row wrap" }, list.map((f) => badge(f, "#ef4444"))) : "None"; }

// ---------------------------------------------------------------- persons
const personFields = [
  { name: "first_name", label: "First name", required: true }, { name: "last_name", label: "Last name" },
  { name: "date_of_birth", label: "Date of birth (roleplay)", placeholder: "YYYY-MM-DD" }, { name: "gender", label: "Gender" },
  { name: "aliases", label: "Aliases", hint: "Comma separated" }, { name: "license_status", label: "License status", type: "select", options: ["Valid", "Suspended", "Revoked", "Expired", "None"] },
  { name: "address", label: "Address" }, { name: "roblox_username", label: "Roblox username" },
  { name: "discord_id", label: "Discord ID", hint: "Optional — searchable only with permission" }, { name: "flags", label: "Flags", hint: "e.g. Armed, Gang affiliated — comma separated" },
  { name: "description", label: "Physical description", type: "textarea", full: true, rows: 2 }, { name: "notes", label: "Notes", type: "textarea", full: true },
];
export async function personDialog(values = {}, id = null) {
  const v = { ...values, aliases: (values.aliases || []).join(", "), flags: (values.flags || []).join(", ") };
  const f = form(personFields, { license_status: "Valid", ...v });
  return modal(id ? `Edit ${values.number}` : "New person record", h("div", { class: "stack" }, f.el, disclaimer()), { wide: true, onSubmit: async () => {
    const r = await api(id ? `records/persons/${id}` : "records/persons", { method: id ? "PATCH" : "POST", body: f.values() }); toast(`${r.number} saved`, "ok"); return r;
  } });
}

export async function persons(root) {
  const q = h("input", { type: "search", placeholder: "Name, alias, record number, plate, Roblox name" });
  const by = h("select", ["any", "name", "alias", "number", "vehicle", "roblox"].map((x) => h("option", { value: x }, `Search by ${x}`)), can("cad.records.discord_lookup") ? h("option", { value: "discord" }, "Search by Discord ID") : null);
  const arch = h("input", { type: "checkbox" });
  const body = h("div");
  const load = debounce(async () => {
    const rows = await api("records/persons", { query: { q: q.value, by: by.value, include_archived: arch.checked, limit: 100 } });
    mount(body, table([{ label: "Record", render: (p) => h("b", p.number) }, { label: "Name", render: (p) => h("span", p.name, p.is_archived ? badge("archived") : null, p.is_civilian_character ? badge("civilian") : null) },
      { label: "DOB", key: "date_of_birth" }, { label: "License", key: "license_status" }, { label: "Aliases", render: (p) => p.aliases.join(", ") || "—" }, { label: "Flags", render: (p) => flags(p.flags) }],
      rows, { onRow: (p) => { location.hash = `#/records/person/${p.id}`; }, emptyText: q.value ? "No matching records." : "No person records yet." }));
  }, 250);
  [q, by, arch].forEach((x) => x.addEventListener(x === q ? "input" : "change", load));
  mount(root, pageHead("Person Records", "Searchable roleplay identities.", [editRecords() ? btn("New person", async () => { const r = await personDialog(); if (r) location.hash = `#/records/person/${r.id}`; }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, q, by, can("cad.records.archive") ? h("label", { class: "check" }, arch, "Include archived") : null), body, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  load();
  return live(["record.changed"], load);
}

export async function person(root, [id]) {
  const load = async () => {
    const p = await api(`records/persons/${id}`);
    const activeW = (p.warrants || []).filter((w) => w.status === "active");
    const activeB = (p.bolos || []).filter((b) => b.is_active);
    mount(root, pageHead(`${p.name}`, `${p.number} · ${p.record_type}`, [
      editRecords() ? btn("Edit", async () => { if (await personDialog(p, p.id)) load(); }, { sm: true, ico: "edit" }) : null,
      can("cad.records.edit") ? btn("Register vehicle", async () => { if (await vehicleDialog({ owner_person_id: p.id })) load(); }, { sm: true, ico: "car" }) : null,
      can("cad.warrants.manage") ? btn("Issue warrant", async () => { if (await warrantDialog({ person_id: p.id })) load(); }, { sm: true, ico: "scale" }) : null,
      can("cad.records.archive") ? btn(p.is_archived ? "Restore" : "Archive", async () => { await api(`records/persons/${p.id}/archive`, { method: "POST", body: { archived: !p.is_archived } }); load(); }, { sm: true }) : null,
      btn("Print", () => window.print(), { sm: true, ico: "printer" })]),
      activeW.length || activeB.length ? h("div", { class: "alert-banner", style: { marginBottom: "14px" } }, icon("alert"), [activeW.length ? `${activeW.length} active warrant(s)` : null, activeB.length ? `${activeB.length} active BOLO(s)` : null].filter(Boolean).join(" · ")) : null,
      h("div", { class: "grid g2" },
        card("Identity", kv([["Name", p.name], ["Aliases", p.aliases.join(", ")], ["Date of birth", p.date_of_birth], ["Gender", p.gender], ["License", p.license_status], ["Address", p.address],
          ["Flags", flags(p.flags)], ["Roblox", p.roblox_username], can("cad.records.discord_lookup") ? ["Discord ID", p.discord_id] : null, ["Description", p.description],
          ["Created", fmtTime(p.created_at)], ["Updated", fmtTime(p.updated_at)]])),
        card("Notes", h("div", { style: { whiteSpace: "pre-wrap" } }, p.notes || h("span", { class: "muted" }, "No notes."))),
        card(`Vehicles (${p.vehicles.length})`, table([{ label: "Plate", render: (v) => h("code", v.plate) }, { label: "Vehicle", render: (v) => `${v.color} ${v.make} ${v.model}` }, { label: "Registration", key: "registration_status" }], p.vehicles, { onRow: (v) => { location.hash = `#/records/vehicle/${v.id}`; }, emptyText: "No vehicles." }), { flush: true }),
        card(`Warrants (${(p.warrants || []).length})`, p.warrants ? table([{ label: "Number", key: "number" }, { label: "Type", key: "warrant_type" }, { label: "Charges", key: "charges" }, { label: "Status", render: (w) => badge(w.status, w.status === "active" ? "#ef4444" : "#64748b") }], p.warrants, { emptyText: "No warrants." }) : empty("Requires warrant access."), { flush: true }),
        card(`BOLOs (${p.bolos.length})`, table([{ label: "Number", key: "number" }, { label: "Reason", key: "reason" }, { label: "Status", key: "status" }], p.bolos, { onRow: (b) => { location.hash = `#/records/bolo/${b.id}`; }, emptyText: "No BOLOs." }), { flush: true }),
        card(`Traffic stops (${p.traffic_stops.length})`, table([{ label: "Stop", key: "number" }, { label: "Location", key: "location" }, { label: "Outcome", key: "outcome" }, { label: "Date", render: (t) => fmtTime(t.started_at) }], p.traffic_stops, { onRow: (t) => { location.hash = `#/cad/traffic/${t.id}`; }, emptyText: "None." }), { flush: true }),
        card("Related incidents & records", p.links.length ? h("div", { class: "list" }, p.links.map((l) => h("a", { class: "list-item clickable", href: recordHref(l.type, l.id), style: { color: "inherit" } }, badge(l.type), h("span", l.label)))) : empty("No linked records.")),
        card("Record history", historyTable(p.history), { flush: true })), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  };
  await load();
}

// ---------------------------------------------------------------- vehicles
export async function vehicleDialog(values = {}, id = null) {
  const f = form([{ name: "plate", label: "Plate", required: true, max: 10 }, { name: "make", label: "Make" }, { name: "model", label: "Model" }, { name: "color", label: "Color" },
    { name: "year", label: "Year" }, { name: "category", label: "Category", type: "select", options: ["Sedan", "SUV", "Truck", "Coupe", "Motorcycle", "Van", "Emergency", "Commercial", "Other"] },
    { name: "owner_person_id", label: "Owner person record ID", type: "number", nullable: true, hint: "Use the number from the person profile URL" }, { name: "owner_name", label: "Owner name (if no record)" },
    { name: "registration_status", label: "Registration", type: "select", options: REG }, { name: "insurance_status", label: "Insurance", type: "select", options: INS },
    { name: "flags", label: "Flags", hint: "Comma separated, e.g. Stolen" }, { name: "description", label: "Description", full: true }, { name: "notes", label: "Notes", type: "textarea", full: true }],
  { registration_status: "Valid", insurance_status: "Valid", category: "Sedan", ...values, flags: (values.flags || []).join?.(", ") ?? values.flags });
  return modal(id ? `Edit ${values.plate}` : "New vehicle record", h("div", { class: "stack" }, f.el, disclaimer()), { wide: true, onSubmit: async () => {
    const r = await api(id ? `records/vehicles/${id}` : "records/vehicles", { method: id ? "PATCH" : "POST", body: f.values() }); toast(`${r.plate} saved`, "ok"); return r;
  } });
}

export async function vehicles(root) {
  const q = h("input", { type: "search", placeholder: "Full or partial plate, owner, make, model" });
  const color = h("input", { placeholder: "Color", style: { width: "110px" } });
  const reg = h("select", h("option", { value: "" }, "Any registration"), REG.map((r) => h("option", { value: r }, r)));
  const body = h("div");
  const load = debounce(async () => {
    const rows = await api("records/vehicles", { query: { q: q.value, color: color.value, registration: reg.value, limit: 100 } });
    mount(body, table([{ label: "Plate", render: (v) => h("code", { style: { fontWeight: 700 } }, v.plate) }, { label: "Vehicle", render: (v) => `${v.year} ${v.color} ${v.make} ${v.model}`.trim() },
      { label: "Owner", render: (v) => v.owner_name || "—" }, { label: "Registration", render: (v) => badge(v.registration_status, v.registration_status === "Valid" ? "#22c55e" : "#ef4444") },
      { label: "Insurance", key: "insurance_status" }, { label: "Flags", render: (v) => flags(v.flags) }], rows, { onRow: (v) => { location.hash = `#/records/vehicle/${v.id}`; } }));
  }, 250);
  [q, color].forEach((x) => x.addEventListener("input", load)); reg.addEventListener("change", load);
  const plate = h("input", { placeholder: "Run plate…", style: { width: "140px" } });
  mount(root, pageHead("Vehicle Records", "Registered roleplay vehicles.", [
    h("form", { class: "row", onsubmit: async (e) => { e.preventDefault(); const r = await api(`records/plate/${encodeURIComponent(plate.value)}`); plateResult(r); } }, plate, h("button", { class: "btn sm" }, "Check")),
    editRecords() ? btn("New vehicle", async () => { const r = await vehicleDialog(); if (r) location.hash = `#/records/vehicle/${r.id}`; }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, q, color, reg), body, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  load();
  return live(["record.changed"], load);
}

export function plateResult(r) {
  return modal(`Plate ${r.plate}`, h("div", { class: "stack" },
    r.alerts.length ? h("div", { class: "alert-banner" }, icon("alert"), r.alerts.join(" · ")) : h("div", { class: "notice ok" }, r.vehicle ? "No alerts." : "No vehicle record found."),
    r.vehicle ? kv([["Vehicle", `${r.vehicle.year} ${r.vehicle.color} ${r.vehicle.make} ${r.vehicle.model}`], ["Owner", r.vehicle.owner_name], ["Registration", r.vehicle.registration_status], ["Insurance", r.vehicle.insurance_status]]) : null,
    r.vehicle ? h("a", { href: `#/records/vehicle/${r.vehicle.id}`, onclick: () => document.querySelector(".modal-backdrop")?.remove() }, "Open vehicle record") : null, disclaimer()), { submitLabel: "Close" });
}

export async function vehicle(root, [id]) {
  const load = async () => {
    const v = await api(`records/vehicles/${id}`);
    const activeB = v.bolos.filter((b) => b.is_active);
    mount(root, pageHead(`${v.plate}`, `${v.number} · ${v.year} ${v.color} ${v.make} ${v.model}`, [
      editRecords() ? btn("Edit", async () => { if (await vehicleDialog(v, v.id)) load(); }, { sm: true, ico: "edit" }) : null,
      can("cad.bolo.manage") ? btn("Issue BOLO", async () => { if (await boloDialog({ category: "vehicle", vehicle_id: v.id, plate: v.plate, vehicle_description: `${v.color} ${v.make} ${v.model}` })) load(); }, { sm: true, ico: "eye" }) : null,
      can("cad.records.archive") ? btn(v.is_archived ? "Restore" : "Archive", async () => { await api(`records/vehicles/${v.id}/archive`, { method: "POST", body: { archived: !v.is_archived } }); load(); }, { sm: true }) : null]),
      activeB.length || v.registration_status !== "Valid" ? h("div", { class: "alert-banner", style: { marginBottom: "14px" } }, icon("alert"), [activeB.length ? `${activeB.length} active BOLO(s)` : null, v.registration_status !== "Valid" ? `Registration ${v.registration_status}` : null].filter(Boolean).join(" · ")) : null,
      h("div", { class: "grid g2" },
        card("Vehicle", kv([["Plate", h("code", v.plate)], ["Make / model", `${v.make} ${v.model}`], ["Color", v.color], ["Year", v.year], ["Category", v.category], ["Registration", v.registration_status],
          ["Insurance", v.insurance_status], ["Flags", flags(v.flags)], ["Description", v.description], ["Notes", v.notes]])),
        card("Registered owner", v.owner ? h("div", { class: "stack" }, kv([["Name", v.owner.name], ["Record", v.owner.number], ["License", v.owner.license_status], ["Flags", flags(v.owner.flags)]]),
          h("a", { href: `#/records/person/${v.owner.id}`, class: "btn sm" }, "Open person record")) : kv([["Owner", v.owner_name || "Unknown"]])),
        card(`Traffic stops (${v.traffic_stops.length})`, table([{ label: "Stop", key: "number" }, { label: "Officer", key: "callsign" }, { label: "Outcome", key: "outcome" }, { label: "Date", render: (t) => fmtTime(t.started_at) }], v.traffic_stops, { onRow: (t) => { location.hash = `#/cad/traffic/${t.id}`; }, emptyText: "No stops." }), { flush: true }),
        card(`BOLOs (${v.bolos.length})`, table([{ label: "Number", key: "number" }, { label: "Reason", key: "reason" }, { label: "Status", key: "status" }], v.bolos, { onRow: (b) => { location.hash = `#/records/bolo/${b.id}`; }, emptyText: "No BOLOs." }), { flush: true }),
        card("Related records", v.links.length ? h("div", { class: "list" }, v.links.map((l) => h("a", { class: "list-item clickable", href: recordHref(l.type, l.id), style: { color: "inherit" } }, badge(l.type), h("span", l.label)))) : empty("No linked records.")),
        card("Record history", historyTable(v.history), { flush: true })), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  };
  await load();
}

// ---------------------------------------------------------------- BOLOs
export async function boloDialog(values = {}, id = null) {
  const f = form([{ name: "category", label: "Category", type: "select", options: [["person", "Person"], ["vehicle", "Vehicle"], ["general", "General"]] },
    { name: "department_id", label: "Department", type: "select", options: deptOptions(), nullable: true, numeric: true },
    { name: "subject_description", label: "Subject description", type: "textarea", full: true, rows: 2 }, { name: "vehicle_description", label: "Vehicle description", full: true },
    { name: "plate", label: "Plate" }, { name: "last_known_location", label: "Last known location" },
    { name: "reason", label: "Reason", type: "textarea", full: true, required: true },
    { name: "expires_at", label: "Expires", type: "datetime-local", hint: "Leave empty for the default expiry" },
    ...(id ? [{ name: "status", label: "Status", type: "select", options: ["active", "updated", "resolved", "expired", "cancelled"] }] : [])],
  { category: "general", ...values, expires_at: values.expires_at ? new Date(values.expires_at).toISOString().slice(0, 16) : "" });
  return modal(id ? `Edit ${values.number}` : "Issue BOLO", h("div", { class: "stack" }, f.el, disclaimer()), { wide: true, onSubmit: async () => {
    const v = f.values(); v.expires_at = v.expires_at ? new Date(v.expires_at).toISOString() : (id ? null : undefined);
    if (v.expires_at === undefined) delete v.expires_at;
    const r = await api(id ? `records/bolos/${id}` : "records/bolos", { method: id ? "PATCH" : "POST", body: v }); toast(`${r.number} saved`, "ok"); return r;
  } });
}

export async function bolos(root) {
  const status = h("select", ["active", "all", "resolved", "expired", "cancelled"].map((s) => h("option", { value: s }, s[0].toUpperCase() + s.slice(1))));
  const cat = h("select", h("option", { value: "" }, "All categories"), ["person", "vehicle", "general"].map((s) => h("option", { value: s }, s)));
  const q = h("input", { type: "search", placeholder: "Search BOLOs" });
  const body = h("div");
  const load = debounce(async () => {
    const rows = await api("records/bolos", { query: { status: status.value, category: cat.value, q: q.value } });
    mount(body, table([{ label: "BOLO", render: (b) => h("b", b.number) }, { label: "Category", key: "category" }, { label: "Subject / vehicle", render: (b) => b.subject_description || b.vehicle_description || "—" },
      { label: "Plate", render: (b) => b.plate ? h("code", b.plate) : "—" }, { label: "Reason", render: (b) => h("span", { class: "truncate", style: { maxWidth: "280px", display: "inline-block" } }, b.reason) },
      { label: "Status", render: (b) => badge(b.status, b.is_active ? "#f59e0b" : "#64748b") }, { label: "Expires", render: (b) => fmtTime(b.expires_at) }],
      rows, { onRow: (b) => { location.hash = `#/records/bolo/${b.id}`; }, emptyText: "No BOLOs." }));
  }, 250);
  [status, cat].forEach((x) => x.addEventListener("change", load)); q.addEventListener("input", load);
  mount(root, pageHead("BOLO Database", "Be On the Lookout alerts. Expired BOLOs close automatically and alert their issuers.", [
    can("cad.bolo.manage") ? btn("Issue BOLO", async () => { if (await boloDialog()) load(); }, { kind: "primary", sm: true, ico: "plus" }) : null]),
    card(h("div", { class: "filters" }, status, cat, q), body, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  load();
  return live(["bolo."], load);
}

export async function bolo(root, [id]) {
  const load = async () => {
    const b = await api(`records/bolos/${id}`);
    mount(root, pageHead(`BOLO ${b.number}`, `${b.category} · issued ${fmtTime(b.created_at)}`, [
      can("cad.bolo.manage") ? btn("Edit", async () => { if (await boloDialog(b, b.id)) load(); }, { sm: true, ico: "edit" }) : null,
      can("cad.bolo.manage") && b.is_active ? btn("Resolve", async () => { await api(`records/bolos/${b.id}`, { method: "PATCH", body: { status: "resolved" } }); load(); }, { sm: true, kind: "primary" }) : null,
      can("cad.bolo.manage") && b.is_active ? btn("Cancel", async () => { await api(`records/bolos/${b.id}`, { method: "PATCH", body: { status: "cancelled" } }); load(); }, { sm: true }) : null]),
      h("div", { class: "grid g2" },
        card("Details", kv([["Status", badge(b.status, b.is_active ? "#f59e0b" : "#64748b")], ["Subject", b.subject_description], ["Vehicle", b.vehicle_description], ["Plate", b.plate],
          ["Last known location", b.last_known_location], ["Reason", h("span", { style: { whiteSpace: "pre-wrap" } }, b.reason)], ["Expires", fmtTime(b.expires_at)], ["Closed", fmtTime(b.closed_at)],
          ["Person record", b.person_id ? h("a", { href: `#/records/person/${b.person_id}` }, "Open") : null], ["Vehicle record", b.vehicle_id ? h("a", { href: `#/records/vehicle/${b.vehicle_id}` }, "Open") : null]])),
        card("History", historyTable(b.history), { flush: true })), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  };
  await load();
}

// ---------------------------------------------------------------- warrants & cases
export async function warrantDialog(values = {}) {
  const f = form([{ name: "warrant_type", label: "Type", type: "select", options: [["arrest", "Arrest"], ["search", "Search"], ["bench", "Bench"]] },
    { name: "person_id", label: "Person record ID", type: "number", nullable: true }, { name: "subject_name", label: "Subject name (if no record)" },
    { name: "case_id", label: "Case ID", type: "number", nullable: true }, { name: "department_id", label: "Department", type: "select", options: deptOptions(), nullable: true, numeric: true },
    { name: "expires_at", label: "Expires", type: "datetime-local" }, { name: "charges", label: "Charges", type: "textarea", full: true }, { name: "description", label: "Description", type: "textarea", full: true }], values);
  return modal("Issue warrant", h("div", { class: "stack" }, f.el, disclaimer(), h("div", { class: "small muted" }, "Roleplay record only — never a real legal document.")), { wide: true, onSubmit: async () => {
    const v = f.values(); v.expires_at = v.expires_at ? new Date(v.expires_at).toISOString() : "";
    const r = await api("records/warrants", { method: "POST", body: v }); toast(`${r.number} issued`, "ok"); return r;
  } });
}

export async function warrants(root) {
  const body = h("div");
  const show = async (tab) => {
    if (tab === "warrants") {
      const status = h("select", ["active", "all", "served", "recalled", "expired"].map((s) => h("option", { value: s }, s)));
      const q = h("input", { type: "search", placeholder: "Search warrants" });
      const list = h("div");
      const load = async () => {
        const rows = await api("records/warrants", { query: { status: status.value, q: q.value } });
        mount(list, table([{ label: "Number", render: (w) => h("b", w.number) }, { label: "Type", key: "warrant_type" }, { label: "Subject", render: (w) => w.person_id ? h("a", { href: `#/records/person/${w.person_id}`, onclick: (e) => e.stopPropagation() }, w.subject_name) : w.subject_name },
          { label: "Charges", key: "charges" }, { label: "Status", render: (w) => badge(w.status, w.status === "active" ? "#ef4444" : "#64748b") }, { label: "Issued", render: (w) => fmtTime(w.created_at) },
          { label: "", render: (w) => can("cad.warrants.manage") && w.status === "active" ? h("div", { class: "row" },
            btn("Served", async (e) => { e.stopPropagation(); await api(`records/warrants/${w.id}`, { method: "PATCH", body: { status: "served" } }); load(); }, { sm: true }),
            btn("Recall", async (e) => { e.stopPropagation(); await api(`records/warrants/${w.id}`, { method: "PATCH", body: { status: "recalled" } }); load(); }, { sm: true })) : null }], rows, { emptyText: "No warrants." }));
      };
      status.onchange = load; q.oninput = debounce(load, 250);
      mount(body, card(h("div", { class: "filters" }, status, q), list, { flush: true, actions: [can("cad.warrants.manage") ? btn("Issue warrant", async () => { if (await warrantDialog()) load(); }, { sm: true, kind: "primary", ico: "plus" }) : null] }));
      load();
    } else {
      const list = h("div");
      const load = async () => {
        const rows = await api("records/cases");
        mount(list, table([{ label: "Case", render: (c) => h("b", c.number) }, { label: "Title", key: "title" }, { label: "Status", render: (c) => badge(c.status) }, { label: "Restricted", render: (c) => c.restricted ? "Yes" : "No" }, { label: "Opened", render: (c) => fmtTime(c.created_at) }],
          rows, { onRow: (c) => { location.hash = `#/records/case/${c.id}`; }, emptyText: "No cases." }));
      };
      mount(body, card(null, list, { flush: true, actions: [can("cad.warrants.manage") ? btn("Open case", async () => {
        const f = form([{ name: "title", label: "Title", required: true, full: true }, { name: "summary", label: "Summary", type: "textarea", full: true }, { name: "department_id", label: "Department", type: "select", options: deptOptions(), nullable: true, numeric: true }, { name: "restricted", label: "Restricted (case managers only)", type: "checkbox" }]);
        const r = await modal("Open case", f.el, { onSubmit: async () => api("records/cases", { method: "POST", body: f.values() }) }); if (r) location.hash = `#/records/case/${r.id}`;
      }, { sm: true, kind: "primary", ico: "plus" }) : null] }));
      load();
    }
  };
  mount(root, pageHead("Warrant Records", "Roleplay warrants and case files with full audit history."), tabs([["warrants", "Warrants"], ["cases", "Cases"]], show), body, h("div", { style: { marginTop: "8px" } }, disclaimer()));
  show("warrants");
}

export async function caseDetail(root, [id]) {
  const load = async () => {
    const c = await api(`records/cases/${id}`);
    const note = h("textarea", { rows: 2, placeholder: "Add case note…" });
    mount(root, pageHead(`${c.number} — ${c.title}`, `${c.status}${c.restricted ? " · restricted" : ""}`, [
      can("cad.warrants.manage") ? h("select", { class: "btn sm", onchange: async (e) => { await api(`records/cases/${c.id}`, { method: "PATCH", body: { status: e.target.value } }); load(); } },
        ["open", "active", "closed", "archived"].map((s) => h("option", { value: s, selected: s === c.status }, s))) : null,
      can("cad.warrants.manage") ? btn("Issue warrant", async () => { if (await warrantDialog({ case_id: c.id })) load(); }, { sm: true }) : null]),
      h("div", { class: "grid g2" },
        card("Summary", h("div", { style: { whiteSpace: "pre-wrap" } }, c.summary || "—")),
        card(`Warrants (${c.warrants.length})`, table([{ label: "Number", key: "number" }, { label: "Subject", key: "subject_name" }, { label: "Status", key: "status" }], c.warrants, { emptyText: "None." }), { flush: true }),
        card(`Case notes (${c.notes.length})`, h("div", { class: "stack" }, h("div", { class: "list" }, c.notes.map((n) => h("div", { class: "list-item" }, h("div", { class: "grow" }, h("div", { class: "meta" }, n.user, " · ", fmtTime(n.created_at)), h("div", { style: { whiteSpace: "pre-wrap" } }, n.body))))),
          can("cad.warrants.manage") ? [note, btn("Add note", async () => { await api(`records/cases/${c.id}/notes`, { method: "POST", body: { body: note.value } }); load(); }, { sm: true, kind: "primary" })] : null)),
        card("Audit history", historyTable(c.history), { flush: true })), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  };
  await load();
}

// ---------------------------------------------------------------- search
export async function search(root, _p, query) {
  const scopes = ["incidents", "people", "vehicles", "bolos", "traffic", "reports", "units", "personnel", "departments"];
  const q = h("input", { type: "search", placeholder: "Search everything…", value: query.q || "", style: { minWidth: "320px", flex: 1 } });
  const exact = h("input", { type: "checkbox" });
  const scopeBoxes = scopes.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: true, value: s }), s));
  const dept = h("select", deptOptions("Any department").map(([v, l]) => h("option", { value: v }, l)));
  const status = h("input", { placeholder: "Status (optional)", style: { width: "150px" } });
  const from = h("input", { type: "date" }), to = h("input", { type: "date" });
  const body = h("div"), recent = h("div");
  const run = async () => {
    if (q.value.trim().length < 2) return mount(body, empty("Enter at least 2 characters.", "search"));
    const sel = scopeBoxes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value).join(",");
    const r = await api("search", { query: { q: q.value, scopes: sel, exact: exact.checked, department_id: dept.value, status: status.value, limit: 25,
      date_from: from.value ? new Date(from.value).toISOString() : "", date_to: to.value ? new Date(to.value + "T23:59:59").toISOString() : "" } });
    mount(body, r.total ? h("div", { class: "grid g2" }, Object.entries(r.results).filter(([, v]) => v.length).map(([k, rows]) => card(`${k} (${rows.length})`,
      h("div", { class: "list" }, rows.map((row) => h("a", { class: "list-item clickable", href: row.link.replace(/^\/?#/, "#"), style: { color: "inherit", textDecoration: "none" } },
        h("div", { class: "grow" }, h("div", { class: "title" }, row.title, row.status ? h("span", { class: "muted small" }, ` · ${row.status}`) : null), h("div", { class: "meta" }, row.summary)),
        row.date ? h("span", { class: "meta" }, fmtTime(row.date, { date: true })) : null))), { flush: true }))) : empty(`No results for “${q.value}”.`, "search"));
    loadRecent();
  };
  const loadRecent = async () => { const r = await api("search/recent"); mount(recent, r.length ? h("div", { class: "row wrap" }, r.map((x) => btn(x.query, () => { q.value = x.query; run(); }, { sm: true, kind: "ghost" }))) : h("span", { class: "muted small" }, "No recent searches.")); };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  mount(root, pageHead("Search Records", "One search across every record type you have permission to see."),
    card(null, h("div", { class: "stack" }, h("div", { class: "row" }, q, btn("Search", run, { kind: "primary", ico: "search" })),
      h("div", { class: "row wrap" }, scopeBoxes), h("div", { class: "filters" }, h("label", { class: "check" }, exact, "Exact match"), dept, status, h("span", { class: "small muted" }, "From"), from, h("span", { class: "small muted" }, "to"), to),
      h("div", { class: "row small" }, h("span", { class: "muted" }, "Recent:"), recent))), h("div", { style: { marginTop: "14px" } }, body));
  loadRecent();
  if (query.q) run();
}
