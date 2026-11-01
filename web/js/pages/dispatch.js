import { api, ago, badge, btn, can, card, deptOptions, empty, fmtTime, h, icon, kv, L, live, mount, prio, state, statusPill, toast } from "../core.js";
import { assignDialog, incidentDialog, registerUnitDialog, statusDialog, unitDialog } from "./cad.js";

export default async function dispatch(root, _params, query) {
  let selected = null;
  let dept = state.me.preferences?.default_department_id ? String(state.me.preferences.default_department_id) : "";
  let sort = "priority";
  const queueEl = h("div"), detailEl = h("div"), unitsEl = h("div"), callsEl = h("div"), commsEl = h("div", { class: "comms" });
  const commsInput = h("input", { placeholder: can("cad.comms.send") ? "Message all units…" : "Read only", disabled: !can("cad.comms.send") });
  const commsKind = h("select", { title: "Message type" }, h("option", { value: "message" }, "Message"), can("cad.comms.announce") ? h("option", { value: "announcement" }, "Announcement") : null);
  const deptSel = h("select", { onchange: (e) => { dept = e.target.value; loadQueue(); loadUnits(); } }, deptOptions("All departments").map(([v, l]) => h("option", { value: v, selected: String(v) === dept }, l)));
  const sortSel = h("select", { onchange: (e) => { sort = e.target.value; loadQueue(); } }, h("option", { value: "priority" }, "Priority"), h("option", { value: "age" }, "Age"));
  const searchIn = h("input", { type: "search", placeholder: "Filter queue…", oninput: () => loadQueue() });
  const sc = L.settings("dispatch.shortcuts") || {};

  const left = h("div", { class: "cad-col cad-left" },
    card("Dispatcher", h("div", { class: "stack" },
      h("div", { class: "row" }, state.me.avatar_url ? h("img", { class: "avatar", src: state.me.avatar_url, alt: "" }) : h("span", { class: "avatar" }, state.me.name[0]), h("div", h("div", { style: { fontWeight: 600 } }, state.me.name), h("div", { class: "small muted" }, state.me.roles.map((r) => r.name).join(", ")))),
      h("label", { class: "field" }, "Department", deptSel))),
    card("Tools", h("div", { class: "stack" },
      can("cad.incident.create") ? btn("New incident", newIncident, { kind: "primary", ico: "plus" }) : null,
      can("cad.unit.manage") ? btn("Register unit", async () => { if (await registerUnitDialog()) loadUnits(); }, { ico: "car" }) : null,
      h("a", { class: "btn", href: "#/cad/map" }, icon("map"), "Live map"), h("a", { class: "btn", href: "#/records/search" }, icon("search"), "Records search"),
      h("a", { class: "btn", href: "#/records/bolos" }, icon("eye"), "BOLOs"))),
    card("Shortcuts", h("div", { class: "stack small" }, Object.entries(sc).filter(([, k]) => k).map(([a, k]) => h("div", { class: "row between" }, h("span", { class: "muted" }, a.replace(/_/g, " ")), h("span", { class: "kbd" }, k))),
      h("a", { href: "#/profile", class: "small" }, "Customize shortcuts"))));

  const center = h("div", { class: "cad-col" },
    h("div", callsEl),
    card(h("h3", icon("radio"), "Dispatch queue"), queueEl, { flush: true, actions: [searchIn, sortSel] }),
    detailEl);
  const right = h("div", { class: "cad-col" },
    card(h("h3", icon("car"), "Unit board"), unitsEl, { flush: true }),
    card(h("h3", icon("headset"), "Dispatch communications"), h("div", commsEl, h("form", { class: "comms-form", onsubmit: async (e) => {
      e.preventDefault(); if (!commsInput.value.trim()) return;
      await api("cad/comms", { method: "POST", body: { body: commsInput.value, kind: commsKind.value, channel: commsKind.value === "announcement" ? "broadcast" : "dispatch", incident_id: selected } });
      commsInput.value = "";
    } }, commsKind, commsInput, h("button", { class: "btn primary sm", type: "submit", disabled: !can("cad.comms.send") }, "Send"))), { flush: true }));

  mount(root, h("div", { class: "page-head" }, h("div", h("h1", "Dispatch Center"), h("p", "Manage incidents, units and communications in real time.")),
    h("div", { class: "actions" }, h("span", { class: "chip" }, h("span", { class: "dot ok" }), "Live"))),
  h("div", { class: "cad-layout" }, left, center, right));

  async function newIncident() {
    const r = await incidentDialog();
    if (r) { selected = r.id; await loadQueue(); await loadDetail(); }
  }

  async function loadCalls() {
    const calls = await api("cad/erlc-calls");
    if (!calls.length) return mount(callsEl);
    mount(callsEl, card(h("h3", icon("phone"), `In-game emergency calls (${calls.length})`), h("div", h("div", { class: "stack" }, calls.map((c) => h("div", { class: "call-card" },
      h("div", { class: "row between" }, h("b", `#${c.call_number} · ${c.team || "Emergency"}`), h("span", { class: "small muted" }, ago(c.started_at))),
      h("div", c.description || "No description provided."), h("div", { class: "small muted" }, icon("pin"), " ", c.location || "Unknown location", " · caller ", c.caller || "unknown"),
      h("div", { class: "row" },
        can("cad.incident.create") ? btn("Create incident", async () => { const r = await api(`cad/erlc-calls/${c.id}/accept`, { method: "POST", body: {} }); toast(`${r.number} created from call #${c.call_number}`, "ok"); selected = r.id; loadAll(); }, { sm: true, kind: "primary" }) : null,
        can("cad.dispatch") ? btn("Dismiss", async () => { await api(`cad/erlc-calls/${c.id}/dismiss`, { method: "POST" }); loadCalls(); }, { sm: true }) : null)))),
      h("div", { class: "disclaimer", style: { marginTop: "8px" } }, icon("check"), "Reported by the official ERLC API. Nothing is dispatched until you create an incident."))));
  }

  async function loadQueue() {
    const items = await api("cad/queue", { query: { department_id: dept, sort, q: searchIn.value } });
    if (selected && !items.some((i) => i.id === selected)) { /* keep detail open even if closed */ }
    mount(queueEl, items.length ? items.map((i) => {
      const row = h("div", { class: `queue-item drop-target${i.id === selected ? " selected" : ""}${i.overdue ? " overdue" : ""}`, onclick: () => { selected = i.id; loadQueue(); loadDetail(); } },
        prio(i.priority, i.priority_color, i.priority_name),
        h("div", { class: "q-main" }, h("div", { class: "q-title" }, i.number, h("span", { class: "muted small" }, i.category_label, i.subtype ? ` · ${i.subtype}` : "")),
          h("div", { class: "q-sub truncate" }, i.location || "No location", " — ", i.description || ""),
          h("div", { class: "row wrap", style: { marginTop: "4px", gap: "4px" } }, statusPill(i.status_label, i.status_color), i.units.map((u) => badge(u.callsign)), !i.units.length ? badge("awaiting units", "#f59e0b") : null)),
        h("div", { class: "q-timer" }, h("div", { dataset: { since: i.created_at } }, ""), i.overdue ? h("div", { class: "small", style: { color: "var(--bad)" } }, "overdue") : null));
      // drag & drop unit → incident
      row.addEventListener("dragover", (e) => { e.preventDefault(); row.classList.add("drag-over"); });
      row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
      row.addEventListener("drop", async (e) => { e.preventDefault(); row.classList.remove("drag-over"); const uid = e.dataTransfer.getData("text/unit"); if (uid) { await api(`cad/incidents/${i.id}/assign`, { method: "POST", body: { unit: Number(uid) } }); toast("Unit assigned", "ok"); } });
      return row;
    }) : h("div", { class: "empty" }, icon("check"), h("div", "Queue is clear.")));
  }

  async function loadDetail() {
    if (!selected) return mount(detailEl, card(null, h("div", { class: "empty" }, "Select an incident to see details, timeline and quick actions.")));
    let d;
    try { d = await api(`cad/incidents/${selected}`, { silent: true }); } catch { selected = null; return loadDetail(); }
    const note = h("input", { placeholder: "Add dispatcher note… (Enter)", dataset: { noteInput: "1" }, style: { flex: 1 } });
    note.addEventListener("keydown", async (e) => { if (e.key === "Enter" && note.value.trim()) { await api(`cad/incidents/${d.id}/notes`, { method: "POST", body: { body: note.value } }); note.value = ""; } });
    const quickStatuses = L.incidentStatuses().filter((s) => ["en_route", "on_scene", "in_progress", "awaiting_units", "resolved"].includes(s.key));
    mount(detailEl, card(h("h3", prio(d.priority, d.priority_color, d.priority_name), h("a", { href: `#/cad/incident/${d.id}` }, d.number), statusPill(d.status_label, d.status_color)), h("div", { class: "stack" },
      h("div", { class: "row wrap" },
        can("cad.dispatch") || can("cad.unit.self") ? btn("Assign unit", async () => { if (await assignDialog(d)) loadDetail(); }, { sm: true, kind: "primary", ico: "car" }) : null,
        can("cad.incident.edit") ? quickStatuses.map((s) => btn(s.label, async () => { await api(`cad/incidents/${d.id}/status`, { method: "POST", body: { status: s.key } }); }, { sm: true })) : null,
        btn("Status…", async () => { if (await statusDialog(d)) loadDetail(); }, { sm: true }),
        can("cad.incident.edit") ? h("select", { class: "btn sm", style: { padding: "4px 6px" }, onchange: async (e) => { await api(`cad/incidents/${d.id}/priority`, { method: "POST", body: { priority: Number(e.target.value) } }); } },
          L.priorities().map((p) => h("option", { value: p.level, selected: p.level === d.priority }, `P${p.level} ${p.name}`))) : null,
        can("cad.incident.edit") ? btn("Edit", async () => { if (await incidentDialog(d, { title: `Edit ${d.number}`, id: d.id })) loadDetail(); }, { sm: true, ico: "edit" }) : null),
      h("div", { class: "grid g2" },
        kv([["Category", `${d.category_label}${d.subtype ? " · " + d.subtype : ""}`], ["Location", [d.location_name, d.street, d.intersection].filter(Boolean).join(" · ")], ["Postal", d.postal],
          ["Caller", [d.caller_name, d.caller_contact].filter(Boolean).join(" · ")], ["Department", d.department], ["Waiting", h("span", { dataset: { since: d.created_at } }, "")]]),
        h("div", { class: "stack" }, h("h4", "Assigned units"), d.units.length ? d.units.map((u) => h("div", { class: "unit-row", style: { padding: "4px 0", border: "none" } },
          h("span", { class: "cs" }, u.callsign), h("span", { class: "grow small muted" }, u.status.replace(/_/g, " ")), can("cad.dispatch") ? btn("Clear", async () => { await api(`cad/incidents/${d.id}/clear`, { method: "POST", body: { unit: u.id } }); }, { sm: true }) : null))
          : h("div", { class: "muted small" }, "No units assigned — drag a unit onto the incident in the queue."))),
      h("div", { style: { whiteSpace: "pre-wrap" } }, d.description),
      h("div", { class: "row" }, note, btn("Note", async () => { if (note.value.trim()) { await api(`cad/incidents/${d.id}/notes`, { method: "POST", body: { body: note.value } }); note.value = ""; } }, { sm: true })),
      h("h4", "Timeline"),
      h("ul", { class: "timeline" }, d.timeline.slice(-10).reverse().map((t) => h("li", h("div", h("b", t.user), " — ", t.message || t.event), h("div", { class: "when" }, fmtTime(t.created_at, { time: true }))))))));
  }

  async function loadUnits() {
    const units = await api("cad/units", { query: { department_id: dept } });
    const groups = { available: [], busy: [], unavailable: [] };
    units.forEach((u) => groups[u.status_group]?.push(u));
    const row = (u) => {
      const el = h("div", { class: "unit-row", draggable: can("cad.dispatch") ? "true" : null, title: can("cad.dispatch") ? "Drag onto an incident to assign" : "", onclick: () => unitDialog(u.id).then(() => loadUnits()) },
        h("span", { class: "cs" }, u.callsign), h("span", { class: "grow truncate small" }, u.members.map((m) => m.name).join(", ") || h("span", { class: "muted" }, u.unit_type)),
        u.current_incident_number ? badge(u.current_incident_number) : null, statusPill(u.status_label, u.status_color));
      el.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/unit", String(u.id)); el.classList.add("dragging"); });
      el.addEventListener("dragend", () => el.classList.remove("dragging"));
      return el;
    };
    mount(unitsEl, units.length ? [["available", "Available"], ["busy", "Assigned / busy"], ["unavailable", "Unavailable"]].map(([k, label]) => [
      h("div", { style: { padding: "8px 12px 4px" } }, h("h4", `${label} (${groups[k].length})`)), ...groups[k].map(row)]) : empty("No units registered.", "car"));
  }

  async function loadComms() {
    const msgs = await api("cad/comms", { query: { limit: 60 } });
    mount(commsEl, msgs.length ? msgs.slice().reverse().map((m) => h("div", { class: `msg ${m.kind}` },
      h("span", { class: "who" }, m.sender || "—"), m.kind === "announcement" ? badge("announcement", "#f59e0b") : null, " ", m.body,
      h("div", { class: "small muted" }, fmtTime(m.created_at, { time: true }), m.source === "discord" ? " · via Discord" : ""))) : h("div", { class: "empty" }, "No messages yet."));
    commsEl.scrollTop = commsEl.scrollHeight;
  }

  async function loadAll() { await Promise.all([loadCalls(), loadQueue(), loadDetail(), loadUnits(), loadComms()]); }
  await loadAll();
  if (query.new && can("cad.incident.create")) newIncident();
  const offs = [
    live(["incident.", "unit.assigned"], () => { loadQueue(); loadDetail(); }, 300),
    live(["unit."], loadUnits, 300),
    live(["erlc.911"], () => { loadCalls(); }, 200),
    live(["comms."], loadComms, 150),
  ];
  const iv = setInterval(loadQueue, 30000); // refresh overdue flags
  return () => { offs.forEach((f) => f()); clearInterval(iv); };
}
