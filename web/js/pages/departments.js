import { api, badge, btn, can, card, confirmDialog, debounce, empty, fmtTime, form, h, icon, kv, L, live, modal, mount, pageHead, stat, state, table, toast } from "../core.js";

const KINDS = [["law", "Law enforcement"], ["fire", "Fire / rescue"], ["ems", "EMS"], ["dot", "Department of Transportation"], ["dispatch", "Dispatch / communications"], ["civilian", "Civilian"], ["other", "Other"]];
async function refreshBoot() { state.boot = await api("bootstrap"); }

async function deptDialog(values = {}, id = null) {
  const f = form([{ name: "name", label: "Name", required: true }, { name: "abbreviation", label: "Abbreviation", required: true, max: 12 },
    { name: "kind", label: "Type", type: "select", options: KINDS }, { name: "color", label: "Colour", type: "color" },
    { name: "callsign_format", label: "Callsign format", hint: "Placeholders: {abbr} {seq} {seq:02} {num} {type}" },
    { name: "unit_types", label: "Unit types", hint: "Comma separated, e.g. Engine, Rescue, Ladder" },
    { name: "logo_url", label: "Logo URL", full: true }, { name: "discord_role_id", label: "Discord role ID" }, { name: "notify_channel_id", label: "Department notification channel ID" },
    { name: "sort_order", label: "Sort order", type: "number" },
    { name: "description", label: "Description", type: "textarea", full: true },
    ...(id ? [] : [{ name: "ranks", label: "Ranks (most senior first)", hint: "Comma separated", full: true }])],
  { kind: "law", color: "#3b82f6", callsign_format: "{abbr}-{seq:02}", sort_order: 0, ...values, unit_types: (values.unit_types || []).join(", ") });
  return modal(id ? `Edit ${values.abbreviation}` : "New department", f.el, { wide: true, onSubmit: async () => {
    const v = f.values(); if (!id) v.ranks = (v.ranks || "").split(",").map((x) => x.trim()).filter(Boolean);
    const r = await api(id ? `departments/${id}` : "departments", { method: id ? "PATCH" : "POST", body: v }); await refreshBoot(); toast(`${r.abbreviation} saved`, "ok"); return r;
  } });
}

export async function overview(root) {
  const body = h("div", { class: "grid g3" });
  const load = async () => {
    const depts = await api("departments", { query: { include_archived: can("cad.department.manage") } });
    const full = await Promise.all(depts.map((d) => api(`departments/${d.id}`)));
    mount(body, full.map((d) => { const top = h("div", { style: { height: "4px", background: d.color, borderRadius: "8px 8px 0 0" } });
      return h("a", { class: "card", href: `#/departments/${d.id}`, style: { textDecoration: "none", color: "inherit", opacity: d.is_archived ? .5 : 1 } }, top,
        h("div", { class: "card-body stack" }, h("div", { class: "row" }, d.logo_url ? h("img", { src: d.logo_url, alt: "", class: "avatar", style: { borderRadius: "6px" } }) : h("span", { class: "avatar", style: { borderRadius: "6px", color: d.color } }, d.abbreviation.slice(0, 2)),
          h("div", h("div", { style: { fontWeight: 600 } }, d.name), h("div", { class: "small muted" }, d.abbreviation, " · ", KINDS.find((k) => k[0] === d.kind)?.[1] || d.kind, d.is_archived ? " · archived" : ""))),
          h("div", { class: "grid g3" }, stat("Members", d.stats.active_members), stat("On shift", d.stats.on_shift), stat("Units", d.stats.units)))); }));
  };
  mount(root, pageHead("Department Overview", "Every department, its personnel and activity.", [can("cad.department.manage") ? btn("New department", async () => { if (await deptDialog()) load(); }, { kind: "primary", sm: true, ico: "plus" }) : null]), body);
  await load();
}

export async function detail(root, [id]) {
  const load = async () => {
    const d = await api(`departments/${id}`);
    const roster = await api(`departments/${id}/roster`);
    const manage = can("cad.department.manage") || (can("dept.personnel.manage") && state.me.department_ids.includes(d.id));
    mount(root, pageHead(d.name, `${d.abbreviation} · ${KINDS.find((k) => k[0] === d.kind)?.[1] || d.kind}`, [
      can("cad.department.manage") ? btn("Edit", async () => { if (await deptDialog(d, d.id)) load(); }, { sm: true, ico: "edit" }) : null,
      manage ? btn("Add member", async () => { if (await addMemberDialog(d)) load(); }, { sm: true, kind: "primary", ico: "plus" }) : null,
      can("cad.department.manage") ? btn(d.is_archived ? "Restore" : "Archive", async () => { if (d.is_archived || await confirmDialog("Archive department", `Archive ${d.abbreviation}? History is kept.`, "Archive")) { await api(`departments/${d.id}/archive`, { method: "POST", body: { archived: !d.is_archived } }); await refreshBoot(); load(); } }, { sm: true }) : null]),
      h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("Active members", d.stats.active_members, { tone: "accent" }), stat("On shift", d.stats.on_shift, { tone: "ok" }),
        stat("Shift hours (30d)", d.stats.shift_hours), stat("Incidents (30d)", d.stats.incidents_participated)),
      h("div", { class: "grid g2" },
        card(`Roster (${roster.length})`, rosterTable(roster, d, manage, load), { flush: true, cls: "span2" }),
        card("Configuration", kv([["Callsign format", h("code", d.callsign_format)], ["Unit types", d.unit_types.join(", ")], ["Discord role", d.discord_role_id], ["Notification channel", d.notify_channel_id], ["Description", d.description]])),
        card("Ranks", h("div", { class: "stack" }, d.ranks.map((r, i) => h("div", { class: "row" }, h("span", { class: "muted mono" }, String(i + 1).padStart(2, "0")), h("span", r.name), r.is_command ? badge("command", "#a855f7") : r.is_supervisor ? badge("supervisor", "#22c55e") : null)),
          h("a", { href: `#/departments/ranks?d=${d.id}`, class: "btn sm" }, "Manage ranks")))));
  };
  await load();
  return live(["department.", "shift."], load, 800);
}

function rosterTable(rows, d, manage, reload) {
  return table([
    { label: "Member", render: (m) => h("span", { class: "row" }, m.avatar_url ? h("img", { class: "avatar", src: m.avatar_url, alt: "" }) : h("span", { class: "avatar" }, (m.name || "?")[0]), h("a", { href: `#/departments/personnel/${m.user_id}`, onclick: (e) => e.stopPropagation() }, m.name)) },
    { label: "Rank", render: (m) => h("span", m.rank || "—", m.is_supervisor ? h("span", { class: "muted small" }, " · supervisor") : null) },
    { label: "Callsign", render: (m) => m.callsign ? h("code", m.callsign) : "—" },
    { label: "Status", render: (m) => badge(m.status, m.status === "active" ? "#22c55e" : m.status === "leave" ? "#f59e0b" : "#64748b") },
    { label: "Duty", render: (m) => m.on_shift ? h("span", { class: "row" }, h("span", { class: "dot ok" }), "On shift", m.unit ? ` · ${m.unit}` : "") : h("span", { class: "muted" }, "Off") },
    { label: "", render: (m) => manage ? btn("Manage", (e) => { e.stopPropagation(); memberDialog(m, d).then((r) => r && reload()); }, { sm: true }) : null },
  ], rows, { emptyText: "No members yet." });
}

async function addMemberDialog(d) {
  const pick = h("input", { placeholder: "Search users by name…", list: "nx-user-pick" });
  const dl = h("datalist", { id: "nx-user-pick" });
  pick.addEventListener("input", debounce(async () => { if (pick.value.length < 2) return; const us = await api("users", { query: { q: pick.value }, silent: true }).catch(() => []); dl.replaceChildren(...us.map((u) => h("option", { value: `${u.name} #${u.id}` }))); }, 200));
  const f = form([{ name: "rank_id", label: "Rank", type: "select", options: d.ranks.map((r) => [r.id, r.name]), numeric: true }, { name: "callsign", label: "Callsign" }]);
  return modal(`Add member to ${d.abbreviation}`, h("div", { class: "stack" }, h("label", { class: "field" }, "User", pick, dl, h("span", { class: "hint" }, "People appear here after signing in once or using the bot. Admins can also pre-add a Discord ID in System → Permissions.")), f.el), {
    submitLabel: "Add member", onSubmit: async () => {
      const uid = Number((pick.value.match(/#(\d+)$/) || [])[1]);
      if (!uid) { toast("Pick a user from the suggestions", "warn"); return false; }
      return api(`departments/${d.id}/members`, { method: "POST", body: { user_id: uid, ...f.values() } });
    } });
}

async function memberDialog(m, d) {
  const f = form([{ name: "rank_id", label: "Rank", type: "select", options: d.ranks.map((r) => [r.id, r.name]), numeric: true },
    { name: "callsign", label: "Callsign" }, { name: "status", label: "Status", type: "select", options: [["active", "Active"], ["leave", "On leave"], ["inactive", "Inactive"], ["removed", "Removed"]] },
    { name: "notes", label: "Personnel notes", type: "textarea", full: true }], m);
  return modal(`${m.name} — ${d.abbreviation}`, f.el, { onSubmit: async () => { await api(`memberships/${m.id}`, { method: "PATCH", body: f.values() }); toast("Member updated", "ok"); } });
}

export async function personnel(root) {
  const q = h("input", { type: "search", placeholder: "Filter by name or callsign" });
  const deptSel = h("select", h("option", { value: "" }, "All departments"), L.departments().map((d) => h("option", { value: d.id }, d.abbreviation)));
  const body = h("div");
  let all = [];
  const render = () => {
    const ql = q.value.toLowerCase();
    const rows = all.filter((m) => (!deptSel.value || String(m.department_id) === deptSel.value) && (!ql || (m.name || "").toLowerCase().includes(ql) || (m.callsign || "").toLowerCase().includes(ql)));
    mount(body, table([{ label: "Member", render: (m) => m.name }, { label: "Department", render: (m) => L.dept(m.department_id)?.abbreviation || "—" }, { label: "Rank", render: (m) => m.rank || "—" },
      { label: "Callsign", render: (m) => m.callsign ? h("code", m.callsign) : "—" }, { label: "Status", key: "status" }, { label: "Duty", render: (m) => m.on_shift ? "On shift" : "Off" }],
      rows, { onRow: (m) => { location.hash = `#/departments/personnel/${m.user_id}`; }, emptyText: "No personnel." }));
  };
  const load = async () => { all = (await Promise.all(L.departments().map((d) => api(`departments/${d.id}/roster`)))).flat(); render(); };
  q.addEventListener("input", render); deptSel.addEventListener("change", render);
  mount(root, pageHead("Personnel", "Everyone across all departments."), card(h("div", { class: "filters" }, q, deptSel), body, { flush: true }));
  await load();
}

export async function profile(root, [id]) {
  const p = await api(`personnel/${id}`);
  const st = await api(`shifts/stats/${id}`).catch(() => null);
  mount(root, pageHead(p.user.name, `Discord ${p.user.discord_id}${p.user.roblox_username ? " · Roblox " + p.user.roblox_username : ""}`),
    st ? h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("This week", st.week), stat("This month", st.month), stat("All time", st.all_time), stat("Shifts", st.shift_count, { sub: st.adjusted_shifts ? `${st.adjusted_shifts} adjusted by supervisors` : null })) : null,
    h("div", { class: "grid g2" },
      card("Departments", table([{ label: "Department", key: "department" }, { label: "Rank", render: (m) => m.rank || "—" }, { label: "Callsign", render: (m) => m.callsign || "—" }, { label: "Status", key: "status" }, { label: "Joined", render: (m) => fmtTime(m.joined_at, { date: true }) }], p.memberships), { flush: true }),
      card("Personnel notes", h("div", { class: "stack" }, p.memberships.filter((m) => m.notes).map((m) => h("div", h("b", m.department), h("div", { style: { whiteSpace: "pre-wrap" } }, m.notes))).concat([]).length ? p.memberships.filter((m) => m.notes).map((m) => h("div", h("b", m.department), h("div", { style: { whiteSpace: "pre-wrap" } }, m.notes))) : h("span", { class: "muted" }, "No notes (or not visible to you)."))),
      card("Department history", table([{ label: "Department", key: "department" }, { label: "Action", key: "action" }, { label: "Change", render: (x) => `${x.old ?? "—"} → ${x.new ?? "—"}` }, { label: "When", render: (x) => fmtTime(x.created_at) }], p.history, { emptyText: "No history." }), { flush: true }),
      card("Recent shifts", table([{ label: "Started", render: (s) => fmtTime(s.started_at) }, { label: "Department", render: (s) => s.department || "—" }, { label: "Callsign", key: "callsign" }, { label: "Credited", key: "duration" }, { label: "Status", key: "status" }], p.shifts, { emptyText: "No shifts." }), { flush: true })));
}

export async function ranks(root, _p, query) {
  const deptSel = h("select", L.departments().map((d) => h("option", { value: d.id, selected: String(d.id) === query.d }, `${d.abbreviation} — ${d.name}`)));
  const body = h("div");
  const load = async () => {
    const d = await api(`departments/${deptSel.value}`);
    const canManage = can("cad.department.manage") || can("dept.ranks.manage");
    const order = d.ranks.map((r) => r.id);
    const rankDialog = (r = null) => {
      const f = form([{ name: "name", label: "Name", required: true }, { name: "abbreviation", label: "Abbreviation" }, { name: "is_supervisor", label: "Supervisory rank", type: "checkbox" },
        { name: "is_command", label: "Command rank", type: "checkbox" }, ...(can("system.permissions") ? [{ name: "permissions", label: "Extra permissions", hint: "Comma separated keys, e.g. cad.reports.review", full: true }] : [])],
      r ? { ...r, permissions: (r.permissions || []).join(", ") } : {});
      return modal(r ? `Edit ${r.name}` : "New rank", f.el, { onSubmit: async () => {
        const v = f.values(); if (typeof v.permissions === "string") v.permissions = v.permissions.split(",").map((x) => x.trim()).filter(Boolean);
        await api(r ? `departments/${d.id}/ranks/${r.id}` : `departments/${d.id}/ranks`, { method: r ? "PATCH" : "POST", body: v }); toast("Rank saved", "ok"); load();
      } });
    };
    mount(body, card(`${d.abbreviation} rank structure`, h("div", { class: "stack" },
      h("div", { class: "small muted" }, "Most senior first. Supervisory and command ranks can review reports and manage shifts for their department."),
      d.ranks.map((r, i) => h("div", { class: "sortable-item" }, h("span", { class: "muted mono" }, String(i + 1).padStart(2, "0")), h("span", { style: { flex: 1 } }, r.name, r.abbreviation ? h("span", { class: "muted" }, ` (${r.abbreviation})`) : null),
        r.is_command ? badge("command", "#a855f7") : r.is_supervisor ? badge("supervisor", "#22c55e") : null, r.permissions?.length ? badge(`+${r.permissions.length} perms`) : null,
        canManage ? [btn("↑", async () => { if (!i) return; [order[i - 1], order[i]] = [order[i], order[i - 1]]; await api(`departments/${d.id}/ranks/reorder`, { method: "POST", body: { rank_ids: order } }); load(); }, { sm: true, disabled: i === 0 }),
          btn("↓", async () => { if (i === order.length - 1) return; [order[i + 1], order[i]] = [order[i], order[i + 1]]; await api(`departments/${d.id}/ranks/reorder`, { method: "POST", body: { rank_ids: order } }); load(); }, { sm: true, disabled: i === order.length - 1 }),
          btn("Edit", () => rankDialog(r), { sm: true }), btn("Delete", async () => { if (await confirmDialog("Delete rank", `Delete ${r.name}? Members must be moved off it first.`, "Delete")) { await api(`departments/${d.id}/ranks/${r.id}`, { method: "DELETE" }); load(); } }, { sm: true, kind: "danger" })] : null)),
      canManage ? btn("Add rank", () => rankDialog(), { sm: true, kind: "primary", ico: "plus" }) : null)));
  };
  deptSel.addEventListener("change", load);
  mount(root, pageHead("Ranks", "Create, rename, reorder and configure ranks for each department.", [deptSel]), body);
  await load();
}

export async function callsigns(root) {
  const body = h("div");
  const load = async () => {
    const depts = L.departments();
    const rosters = await Promise.all(depts.map((d) => api(`departments/${d.id}/roster`)));
    const units = await api("cad/units");
    mount(body, h("div", { class: "grid g2" },
      card("Callsign formats", table([{ label: "Department", render: (d) => d.abbreviation }, { label: "Format", render: (d) => h("code", d.callsign_format) },
        { label: "Next suggestion", render: (d) => { const s = h("span", { class: "muted" }, "…"); api("cad/callsign-suggest", { query: { department_id: d.id }, silent: true }).then((r) => { s.textContent = r.callsign; s.className = "mono"; }).catch(() => { s.textContent = "—"; }); return s; } },
        { label: "", render: (d) => can("cad.department.manage") ? btn("Edit format", async () => {
          const f = form([{ name: "callsign_format", label: "Format", hint: "Placeholders: {abbr} {seq} {seq:02} {num} {type}. Examples: 1A-{seq:02}, FIRE-{seq:02}, {abbr}-{num}{seq:02}" }], d);
          if (await modal(`${d.abbreviation} callsign format`, f.el, { onSubmit: async () => { await api(`departments/${d.id}`, { method: "PATCH", body: f.values() }); await refreshBoot(); } })) load();
        }, { sm: true }) : null }], depts), { flush: true }),
      card("Assigned personnel callsigns", table([{ label: "Callsign", render: (m) => h("code", m.callsign) }, { label: "Member", key: "name" }, { label: "Department", render: (m) => L.dept(m.department_id)?.abbreviation }, { label: "Rank", key: "rank" }],
        rosters.flat().filter((m) => m.callsign).sort((a, b) => a.callsign.localeCompare(b.callsign)), { emptyText: "No callsigns assigned." }), { flush: true }),
      card("Active unit callsigns", table([{ label: "Callsign", render: (u) => h("code", u.callsign) }, { label: "Department", key: "department" }, { label: "Type", key: "unit_type" }, { label: "Status", key: "status_label" }], units, { emptyText: "No units." }), { flush: true, cls: "span2" })));
  };
  mount(root, pageHead("Callsigns", "Configurable callsign formats per department — nothing is hardcoded."), body);
  await load();
}

export async function shifts(root) {
  const body = h("div");
  const load = async () => {
    const me = await api("shifts/me");
    const my = await api("shifts", { query: { user_id: state.me.id, limit: 20 } });
    const deptSel = h("select", h("option", { value: "" }, "Auto"), L.departments().filter((d) => state.me.department_ids.includes(d.id)).map((d) => h("option", { value: d.id }, d.abbreviation)));
    const cs = h("input", { placeholder: "Callsign (optional)", style: { width: "150px" } });
    const units = await api("cad/my-units").catch(() => []);
    const unitSel = h("select", h("option", { value: "" }, "No unit"), units.map((u) => h("option", { value: u.id }, u.callsign)));
    const notes = h("input", { placeholder: "Shift notes (optional)" });
    const active = me.active;
    const sections = [
      h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("Status", active ? h("span", { style: { color: "var(--ok)" } }, "On duty") : "Off duty", { sub: active ? h("span", { dataset: { since: active.started_at } }, "") : null, tone: active ? "ok" : "" }),
        stat("This week", me.week), stat("This month", me.month), stat("All time", me.all_time, { sub: `${me.shift_count} shifts · avg ${me.average}` })),
      card("Clock in / out", active ? h("div", { class: "stack" }, h("div", `On duty since ${fmtTime(active.started_at)}${active.callsign ? " as " + active.callsign : ""}${active.department ? " · " + active.department : ""}${active.recovered ? " (survived a restart)" : ""}`),
        h("div", { class: "row" }, notes, btn("Clock out", async () => { await api("shifts/end", { method: "POST", body: { notes: notes.value } }); toast("Clocked out", "ok"); load(); }, { kind: "danger", ico: "stop" })))
        : can("shift.self") ? h("div", { class: "row wrap" }, deptSel, cs, unitSel, notes, btn("Clock in", async () => {
          await api("shifts/start", { method: "POST", body: { department_id: deptSel.value ? Number(deptSel.value) : null, callsign: cs.value, unit_id: unitSel.value ? Number(unitSel.value) : null, notes: notes.value } });
          toast("Clocked in", "ok"); load(); }, { kind: "primary", ico: "play" })) : empty("You don't have permission to clock in.")),
      h("div", { style: { height: "14px" } }),
      card("My shifts", shiftTable(my, false, load), { flush: true })];
    if (can("shift.manage")) {
      const onDuty = await api("shifts/on-duty");
      const pending = await api("shifts", { query: { status: "ended", limit: 100 } });
      const recent = await api("shifts", { query: { limit: 100 } });
      sections.push(h("div", { style: { height: "14px" } }),
        card(`On duty now (${onDuty.length})`, shiftTable(onDuty, true, load), { flush: true }), h("div", { style: { height: "14px" } }),
        card(`Awaiting approval (${pending.length})`, shiftTable(pending, true, load), { flush: true }), h("div", { style: { height: "14px" } }),
        card("All recent shifts", shiftTable(recent, true, load), { flush: true }));
    }
    mount(body, sections);
  };
  mount(root, pageHead("Shift Management", "Clock in and out. Active shifts are stored safely and survive restarts."), body);
  await load();
  return live(["shift."], load, 600);
}

function shiftTable(rows, manage, reload) {
  return table([
    ...(manage ? [{ label: "Member", render: (s) => s.user }] : []),
    { label: "Started", render: (s) => fmtTime(s.started_at) }, { label: "Department", render: (s) => s.department || "—" }, { label: "Callsign", render: (s) => s.callsign || "—" },
    { label: "Actual", render: (s) => s.active ? h("span", { class: "mono", dataset: { since: s.started_at } }, "") : `${Math.floor(s.elapsed_seconds / 3600)}h ${String(Math.floor((s.elapsed_seconds % 3600) / 60)).padStart(2, "0")}m` },
    { label: "Credited", render: (s) => h("span", s.duration, s.is_adjusted ? h("span", { title: s.adjust_reason, style: { color: "var(--warn)" } }, " ✎") : null) },
    { label: "Status", render: (s) => badge(s.status, { active: "#22c55e", approved: "#3b82f6", ended: "#f59e0b", rejected: "#ef4444" }[s.status]) },
    { label: "Notes", render: (s) => h("span", { class: "small muted" }, s.notes || "") },
    ...(manage ? [{ label: "", render: (s) => h("div", { class: "row" },
      s.active ? btn("End", async () => { await api("shifts/end", { method: "POST", body: { user_id: s.user_id } }); reload(); }, { sm: true }) : null,
      !s.active && s.status === "ended" ? btn("Approve", async () => { await api(`shifts/${s.id}/approve`, { method: "POST", body: { approved: true } }); reload(); }, { sm: true, kind: "primary" }) : null,
      !s.active && s.status === "ended" ? btn("Reject", async () => { await api(`shifts/${s.id}/approve`, { method: "POST", body: { approved: false } }); reload(); }, { sm: true }) : null,
      !s.active ? btn("Adjust", async () => {
        const f = form([{ name: "credited_minutes", label: "Credited minutes", type: "number", nullable: true, hint: `Actual elapsed: ${Math.round(s.elapsed_seconds / 60)} min. Leave empty to remove the adjustment.` }, { name: "reason", label: "Reason (required, audited)", required: true, full: true }],
          { credited_minutes: s.is_adjusted ? Math.round(s.credited_seconds / 60) : "" });
        if (await modal("Adjust shift time", f.el, { onSubmit: async () => api(`shifts/${s.id}/adjust`, { method: "POST", body: f.values() }) })) reload();
      }, { sm: true }) : null) }] : []),
  ], rows, { emptyText: "No shifts." });
}

export async function stats(root) {
  const deptSel = h("select", L.departments().map((d) => h("option", { value: d.id }, d.abbreviation)));
  const days = h("select", [7, 30, 90, 365].map((n) => h("option", { value: n, selected: n === 30 }, `Last ${n} days`)));
  const body = h("div");
  const load = async () => {
    const s = await api(`departments/${deptSel.value}/stats`, { query: { days: days.value } });
    mount(body, h("div", { class: "grid g4" }, stat("Active members", s.active_members, { tone: "accent" }), stat("On shift now", s.on_shift, { tone: "ok" }), stat("Shift hours", s.shift_hours),
      stat("Shifts", s.shifts), stat("Participation", s.participation_pct != null ? `${s.participation_pct}%` : "—", { sub: "members with ≥1 shift ÷ active members" }),
      stat("Incidents participated", s.incidents_participated), stat("Traffic stops", s.traffic_stops), stat("Reports", s.reports)),
      h("div", { class: "small muted", style: { marginTop: "10px" } }, "Statistics are calculated only from data recorded in ERLC Nexus. For trends, see Analytics → Department Analytics."));
  };
  deptSel.onchange = load; days.onchange = load;
  mount(root, pageHead("Department Statistics", "Activity and participation per department.", [deptSel, days]), body);
  await load();
}

