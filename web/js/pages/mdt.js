// Officer Mobile Data Terminal — deliberately separate from the dispatcher console.
import { api, ago, badge, btn, can, card, disclaimer, empty, fmtTime, h, icon, kv, L, live, mount, prio, state, statusPill, table, toast } from "../core.js";
import { plateResult, boloDialog } from "./records.js";
import { registerUnitDialog, trafficDialog } from "./cad.js";

const NAV = [["", "Dashboard", "home"], ["unit", "My Unit", "car"], ["calls", "Active Calls", "phone"], ["person", "Person Search", "user"], ["vehicle", "Vehicle Search", "car"],
  ["bolos", "BOLOs", "eye"], ["traffic", "Traffic Stops", "shield"], ["reports", "Incident Reports", "file"], ["shift", "Shift", "clock"], ["history", "Activity History", "history"]];

export default async function mdt(root, [section = "", id]) {
  if (!can("cad.view")) return mount(root, h("div", { class: "content" }, h("div", { class: "notice bad" }, "The MDT requires CAD access.")));
  const main = h("main", { class: "mdt-main" });
  const idCard = h("div", { class: "mdt-id" });
  const side = h("nav", { class: "mdt-side" }, idCard,
    NAV.filter(([k]) => !(k === "traffic" && !can("cad.traffic.manage")) && !(["person", "vehicle", "bolos"].includes(k) && !can("cad.records.search")) && !(k === "reports" && !can("cad.reports.create")))
      .map(([k, label, ico]) => h("a", { href: `#/mdt${k ? "/" + k : ""}`, class: (section === k || (section === "call" && k === "calls")) ? "active" : "" }, icon(ico), label)),
    h("div", { style: { flex: 1 } }), h("a", { href: "#/" }, icon("logout"), "Exit MDT"));
  mount(root, h("div", { class: "mdt" }, side, main));

  let myUnit = null, shift = null, commsOff = null;
  const loadId = async () => {
    const [units, st] = await Promise.all([api("cad/my-units"), api("shifts/me")]);
    myUnit = units[0] || null; shift = st;
    mount(idCard, h("div", { class: "small muted" }, state.me.name), h("div", { class: "cs" }, myUnit?.callsign || "NO UNIT"),
      h("div", { class: "small" }, myUnit ? `${myUnit.department} · ${myUnit.unit_type}` : "Register a unit to go on duty"),
      myUnit ? h("div", { style: { marginTop: "6px" } }, statusPill(myUnit.status_label, myUnit.status_color)) : null,
      h("div", { class: "small muted", style: { marginTop: "4px" } }, st.active ? h("span", "On shift ", h("span", { dataset: { since: st.active.started_at } }, "")) : "Off shift"));
  };
  await loadId();

  const pages = { "": dashboard, unit: unitPage, calls: callsPage, call: callDetail, person: personPage, vehicle: vehiclePage, bolos: bolosPage, traffic: trafficPage, reports: reportsPage, shift: shiftPage, history: historyPage };
  const render = async () => { await (pages[section] || dashboard)(); };

  function statusButtons() {
    if (!myUnit) return h("div", { class: "notice" }, "You're not on a unit. ", can("cad.unit.self") || can("cad.unit.manage") ? btn("Register unit", async () => { if (await registerUnitDialog()) { await loadId(); render(); } }, { sm: true, kind: "primary" }) : null);
    return h("div", { class: "mdt-status" }, L.unitStatuses().map((s) => {
      const b = h("button", { class: s.key === myUnit.status ? "active" : "", onclick: async () => { await api(`cad/units/${myUnit.id}/status`, { method: "POST", body: { status: s.key } }); toast(`${myUnit.callsign} → ${s.label}`, "ok"); await loadId(); render(); } },
        s.label, h("small", s.code || ""));
      b.style.color = s.color; return b;
    }));
  }

  async function dashboard() {
    const calls = await api("cad/incidents", { query: { mine: true, state: "open" } });
    const bolos = can("cad.records.search") ? await api("records/bolos", { query: { status: "active" } }) : [];
    const plate = h("input", { placeholder: "Quick plate check", style: { flex: 1 } });
    const person = h("input", { placeholder: "Quick person search", style: { flex: 1 } });
    mount(main, h("div", { class: "page-head" }, h("div", h("h1", "MDT"), h("p", `${state.me.name}${myUnit ? " · " + myUnit.callsign : ""}`)),
      h("div", { class: "actions" }, can("cad.traffic.manage") ? btn("Start traffic stop", async () => { const t = await trafficDialog(); if (t) { location.hash = "#/mdt/traffic"; } }, { kind: "primary", ico: "shield" }) : null)),
      calls.items.length ? h("div", { class: "alert-banner", style: { marginBottom: "14px" } }, icon("alert"), `${calls.items.length} assigned call(s)`) : null,
      card("Unit status", statusButtons()), h("div", { style: { height: "14px" } }),
      h("div", { class: "grid g2" },
        card("Assigned calls", calls.items.length ? h("div", { class: "list" }, calls.items.map(callItem)) : empty("No assigned calls.", "phone"), { flush: true }),
        card("Quick checks", h("div", { class: "stack" },
          can("cad.records.search") ? h("form", { class: "row", onsubmit: async (e) => { e.preventDefault(); plateResult(await api(`records/plate/${encodeURIComponent(plate.value)}`)); } }, plate, h("button", { class: "btn" }, "Run")) : null,
          can("cad.records.search") ? h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); location.hash = `#/mdt/person?q=${encodeURIComponent(person.value)}`; section = "person"; personPage(person.value); } }, person, h("button", { class: "btn" }, "Search")) : null,
          disclaimer())),
        card(`Active BOLOs (${bolos.length})`, bolos.length ? h("div", { class: "list" }, bolos.slice(0, 6).map((b) => h("div", { class: "list-item" }, badge(b.category, "#f59e0b"), h("div", { class: "grow" }, h("div", { class: "title" }, b.number, b.plate ? ` · ${b.plate}` : ""), h("div", { class: "meta" }, b.reason))))) : empty("No active BOLOs.", "eye"), { flush: true }),
        card("Shift", h("div", { class: "stack" }, shift.active ? h("div", "On duty since ", fmtTime(shift.active.started_at)) : h("div", { class: "muted" }, "Off duty"), kv([["This week", shift.week], ["This month", shift.month]]), h("a", { class: "btn sm", href: "#/mdt/shift" }, "Shift details"))),
        card("Dispatch communications", commsBox(), { flush: true, cls: "span2" })));
  }
  function commsBox() {
    const feed = h("div", { class: "comms", style: { maxHeight: "220px" } });
    const input = h("input", { placeholder: can("cad.comms.send") ? `Message dispatch${myUnit ? " as " + myUnit.callsign : ""}…` : "Read only", disabled: !can("cad.comms.send") });
    const load = async () => {
      const msgs = await api("cad/comms", { query: { limit: 25 } });
      mount(feed, msgs.length ? msgs.slice().reverse().map((m) => h("div", { class: `msg ${m.kind}` }, h("span", { class: "who" }, m.sender), m.body,
        h("div", { class: "small muted" }, fmtTime(m.created_at, { time: true })))) : h("div", { class: "empty" }, "No messages yet."));
      feed.scrollTop = feed.scrollHeight;
    };
    load();
    commsOff?.();
    commsOff = live(["comms."], load, 200);
    return h("div", feed, h("form", { class: "comms-form", onsubmit: async (e) => {
      e.preventDefault(); if (!input.value.trim()) return;
      await api("cad/comms", { method: "POST", body: { body: input.value, channel: myUnit ? "unit" : "dispatch", unit_id: myUnit?.id || null, sender_label: myUnit?.callsign } });
      input.value = "";
    } }, input, h("button", { class: "btn primary sm", type: "submit", disabled: !can("cad.comms.send") }, "Send")));
  }
  function callItem(c) {
    return h("a", { class: "list-item clickable", href: `#/mdt/call/${c.id}`, style: { color: "inherit", textDecoration: "none" } }, prio(c.priority, c.priority_color, c.priority_name),
      h("div", { class: "grow" }, h("div", { class: "title" }, c.number, " · ", c.category_label), h("div", { class: "meta" }, c.location || "—", " — ", c.description)), statusPill(c.status_label, c.status_color));
  }

  async function unitPage() {
    const locText = h("input", { placeholder: "Where are you? (e.g. Main St & 2nd)", style: { flex: 1 } });
    const preset = h("select", h("option", { value: "" }, "— Location preset —"));
    (await api("map/locations").catch(() => [])).forEach((l) => preset.appendChild(h("option", { value: l.id }, l.name)));
    mount(main, h("div", { class: "page-head" }, h("h1", "My Unit")),
      card("Status", statusButtons()), h("div", { style: { height: "14px" } }),
      myUnit ? h("div", { class: "grid g2" },
        card("Unit", kv([["Callsign", myUnit.callsign], ["Department", myUnit.department], ["Type", myUnit.unit_type], ["Vehicle", myUnit.vehicle_description], ["Members", myUnit.members.map((m) => m.name).join(", ")],
          ["Current incident", myUnit.current_incident_number ? h("a", { href: `#/mdt/call/${myUnit.current_incident_id}` }, myUnit.current_incident_number) : null]])),
        card("Location", h("div", { class: "stack" }, h("div", myUnit.location.text || "No location reported", myUnit.location.source !== "none" ? h("span", { class: "muted small" }, ` · ${myUnit.location.source === "api" ? "official API position" : myUnit.location.source} · ${ago(myUnit.location.updated_at)}`) : null),
          h("div", { class: "row" }, locText, preset), btn("Report location", async () => { await api(`cad/units/${myUnit.id}/location`, { method: "POST", body: { text: locText.value, location_id: preset.value ? Number(preset.value) : null } }); toast("Location reported", "ok"); await loadId(); unitPage(); }, { kind: "primary", sm: true }),
          h("div", { class: "small muted" }, state.me.roblox_id ? "Your Roblox account is linked, so your position updates automatically from the official ERLC API while you're in-game." : h("span", "Link your Roblox account in ", h("a", { href: "#/profile" }, "your profile"), " for automatic map positions."))))) : null);
  }

  async function callsPage() {
    const [mine, all] = await Promise.all([api("cad/incidents", { query: { mine: true, state: "open" } }), api("cad/queue")]);
    mount(main, h("div", { class: "page-head" }, h("h1", "Active Calls")),
      card(`Assigned to me (${mine.items.length})`, mine.items.length ? h("div", { class: "list" }, mine.items.map(callItem)) : empty("No assigned calls."), { flush: true }), h("div", { style: { height: "14px" } }),
      card(`All active calls (${all.length})`, all.length ? h("div", { class: "list" }, all.map(callItem)) : empty("No active calls."), { flush: true }));
  }

  async function callDetail() {
    const d = await api(`cad/incidents/${id}`);
    const mineOn = myUnit && d.units.some((u) => u.id === myUnit.id);
    const note = h("input", { placeholder: "Add note to this call", style: { flex: 1 } });
    mount(main, h("div", { class: "page-head" }, h("div", h("h1", { class: "row" }, prio(d.priority, d.priority_color, d.priority_name), d.number), h("p", `${d.category_label}${d.subtype ? " · " + d.subtype : ""}`)),
      h("div", { class: "actions" }, statusPill(d.status_label, d.status_color))),
      h("div", { class: "row wrap", style: { marginBottom: "14px" } },
        myUnit && !mineOn && d.is_open ? btn("Attach my unit", async () => { await api(`cad/incidents/${d.id}/assign`, { method: "POST", body: { unit: myUnit.id } }); await loadId(); callDetail(); }, { kind: "primary" }) : null,
        mineOn ? btn("En route", async () => { await api(`cad/units/${myUnit.id}/status`, { method: "POST", body: { status: "en_route" } }); await loadId(); callDetail(); }) : null,
        mineOn ? btn("On scene", async () => { await api(`cad/units/${myUnit.id}/status`, { method: "POST", body: { status: "on_scene" } }); await loadId(); callDetail(); }) : null,
        mineOn ? btn("Clear from call", async () => { await api(`cad/incidents/${d.id}/clear`, { method: "POST", body: { unit: myUnit.id } }); await loadId(); location.hash = "#/mdt/calls"; }) : null,
        can("cad.reports.create") ? h("a", { class: "btn", href: `#/records/report/new?incident=${d.id}` }, icon("file"), "Write report") : null),
      h("div", { class: "grid g2" },
        card("Call", h("div", { class: "stack" }, kv([["Location", [d.location_name, d.street, d.intersection].filter(Boolean).join(" · ")], ["Postal", d.postal], ["Instructions", d.location_instructions],
          ["Caller", [d.caller_name, d.caller_contact].filter(Boolean).join(" · ")], ["Units", d.units.map((u) => u.callsign).join(", ")], ["Created", fmtTime(d.created_at)]]),
          h("h4", "Description"), h("div", { style: { whiteSpace: "pre-wrap" } }, d.description))),
        card("Updates", h("div", { class: "stack" }, h("ul", { class: "timeline" }, d.timeline.slice(-12).reverse().map((t) => h("li", h("div", h("b", t.user), " — ", t.message || t.event), h("div", { class: "when" }, fmtTime(t.created_at, { time: true }))))),
          mineOn || can("cad.incident.edit") ? h("form", { class: "row", onsubmit: async (e) => { e.preventDefault(); if (!note.value.trim()) return; await api(`cad/incidents/${d.id}/notes`, { method: "POST", body: { body: note.value } }); callDetail(); } }, note, h("button", { class: "btn" }, "Add")) : null))));
  }

  async function personPage(prefill) {
    const q = h("input", { placeholder: "Name, alias or record number", value: typeof prefill === "string" ? prefill : (new URLSearchParams(location.hash.split("?")[1] || "").get("q") || ""), style: { flex: 1 } });
    const results = h("div");
    const run = async () => {
      if (!q.value.trim()) return mount(results);
      const rows = await api("records/persons", { query: { q: q.value } });
      mount(results, table([{ label: "Record", key: "number" }, { label: "Name", key: "name" }, { label: "DOB", key: "date_of_birth" }, { label: "License", key: "license_status" },
        { label: "Flags", render: (p) => p.flags.length ? h("div", { class: "row wrap" }, p.flags.map((f) => badge(f, "#ef4444"))) : "—" }], rows, { onRow: (p) => { location.hash = `#/records/person/${p.id}`; }, emptyText: "No matching records." }));
    };
    mount(main, h("div", { class: "page-head" }, h("h1", "Person Search")), card(null, h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); run(); } }, q, h("button", { class: "btn primary" }, "Search"))), h("div", { style: { height: "14px" } }), card(null, results, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
    run();
  }

  async function vehiclePage() {
    const q = h("input", { placeholder: "Plate (full or partial), owner, make or model", style: { flex: 1 } });
    const results = h("div");
    const run = async () => {
      if (!q.value.trim()) return;
      const exact = await api(`records/plate/${encodeURIComponent(q.value)}`, { silent: true }).catch(() => null);
      const rows = await api("records/vehicles", { query: { q: q.value } });
      mount(results, exact?.alerts?.length ? h("div", { class: "alert-banner", style: { margin: "10px" } }, icon("alert"), exact.alerts.join(" · ")) : null,
        table([{ label: "Plate", render: (v) => h("code", v.plate) }, { label: "Vehicle", render: (v) => `${v.color} ${v.make} ${v.model}` }, { label: "Owner", key: "owner_name" }, { label: "Reg", key: "registration_status" }, { label: "Ins", key: "insurance_status" }],
          rows, { onRow: (v) => { location.hash = `#/records/vehicle/${v.id}`; }, emptyText: "No matching vehicles." }));
    };
    mount(main, h("div", { class: "page-head" }, h("h1", "Vehicle Search")), card(null, h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); run(); } }, q, h("button", { class: "btn primary" }, "Run"))), h("div", { style: { height: "14px" } }), card(null, results, { flush: true }), h("div", { style: { marginTop: "8px" } }, disclaimer()));
  }

  async function bolosPage() {
    const rows = await api("records/bolos", { query: { status: "active" } });
    mount(main, h("div", { class: "page-head" }, h("h1", "BOLOs"), can("cad.bolo.manage") ? btn("Issue BOLO", async () => { if (await boloDialog()) bolosPage(); }, { kind: "primary" }) : null),
      card(null, rows.length ? h("div", { class: "list" }, rows.map((b) => h("a", { class: "list-item clickable", href: `#/records/bolo/${b.id}`, style: { color: "inherit", textDecoration: "none" } }, badge(b.category, "#f59e0b"),
        h("div", { class: "grow" }, h("div", { class: "title" }, b.number, b.plate ? ` · ${b.plate}` : ""), h("div", { class: "meta" }, b.subject_description || b.vehicle_description), h("div", { class: "meta" }, b.reason)), h("span", { class: "meta" }, ago(b.created_at))))) : empty("No active BOLOs.", "eye"), { flush: true }));
  }

  async function trafficPage() {
    const rows = await api("cad/traffic", { query: { mine: true } });
    mount(main, h("div", { class: "page-head" }, h("h1", "Traffic Stops"), btn("Start traffic stop", async () => { if (await trafficDialog()) trafficPage(); }, { kind: "primary" })),
      card(null, table([{ label: "Stop", key: "number" }, { label: "Plate", render: (t) => h("code", t.plate || "—") }, { label: "Location", key: "location" }, { label: "Status", render: (t) => badge(t.status, t.status === "active" ? "#f59e0b" : "#22c55e") },
        { label: "Outcome", key: "outcome" }, { label: "Started", render: (t) => fmtTime(t.started_at) }], rows, { onRow: (t) => { location.hash = `#/cad/traffic/${t.id}`; }, emptyText: "You haven't made any traffic stops." }), { flush: true }));
  }

  async function reportsPage() {
    const rows = await api("reports", { query: { mine: true } });
    mount(main, h("div", { class: "page-head" }, h("h1", "Incident Reports"), h("a", { class: "btn primary", href: "#/records/report/new" }, icon("plus"), "New report")),
      card(null, table([{ label: "Report", key: "number" }, { label: "Title", key: "title" }, { label: "Status", render: (r) => badge(r.status_label) }, { label: "Updated", render: (r) => fmtTime(r.updated_at) }], rows,
        { onRow: (r) => { location.hash = `#/records/report/${r.id}`; }, emptyText: "No reports yet." }), { flush: true }));
  }

  async function shiftPage() {
    const st = await api("shifts/me");
    const hist = await api("shifts", { query: { user_id: state.me.id, limit: 15 } });
    mount(main, h("div", { class: "page-head" }, h("h1", "Shift")),
      card(null, h("div", { class: "row wrap" }, st.active ? [h("span", "On duty since ", fmtTime(st.active.started_at), " · ", h("span", { class: "mono", dataset: { since: st.active.started_at } }, "")),
        btn("Clock out", async () => { await api("shifts/end", { method: "POST", body: {} }); await loadId(); shiftPage(); }, { kind: "danger" })]
        : can("shift.self") ? btn("Clock in", async () => { await api("shifts/start", { method: "POST", body: { unit_id: myUnit?.id || null } }); await loadId(); shiftPage(); }, { kind: "primary" }) : h("span", { class: "muted" }, "You can't clock in."))),
      h("div", { style: { height: "14px" } }),
      card(null, kv([["This week", st.week], ["This month", st.month], ["All time", st.all_time], ["Shifts", st.shift_count]])), h("div", { style: { height: "14px" } }),
      card("Recent shifts", table([{ label: "Started", render: (s) => fmtTime(s.started_at) }, { label: "Callsign", key: "callsign" }, { label: "Credited", key: "duration" }, { label: "Status", key: "status" }], hist), { flush: true }));
  }

  async function historyPage() {
    const [stops, reports, incidents] = await Promise.all([can("cad.traffic.manage") ? api("cad/traffic", { query: { mine: true } }) : [], can("cad.reports.create") ? api("reports", { query: { mine: true } }) : [],
      myUnit ? api(`cad/units/${myUnit.id}/history`) : []]);
    mount(main, h("div", { class: "page-head" }, h("h1", "Activity History")),
      h("div", { class: "grid g2" },
        card("My unit history", table([{ label: "Event", key: "event" }, { label: "Change", render: (e) => `${e.old ?? ""} → ${e.new ?? ""}` }, { label: "Incident", render: (e) => e.incident || "—" }, { label: "When", render: (e) => fmtTime(e.created_at) }], incidents.slice(0, 25), { emptyText: "No unit history." }), { flush: true }),
        card("My traffic stops", table([{ label: "Stop", key: "number" }, { label: "Outcome", key: "outcome" }, { label: "When", render: (t) => fmtTime(t.started_at) }], stops.slice(0, 15), { emptyText: "None." }), { flush: true }),
        card("My reports", table([{ label: "Report", key: "number" }, { label: "Status", key: "status_label" }, { label: "When", render: (r) => fmtTime(r.updated_at) }], reports.slice(0, 15), { emptyText: "None." }), { flush: true })));
  }

  await render();
  const off = live(["unit.", "incident.", "shift.", "bolo."], async () => { await loadId(); if (["unit", "calls", "call"].includes(section) || (section === "" && !main.contains(document.activeElement))) render(); }, 700);
  return () => { off(); commsOff?.(); };
}
