import { api, badge, btn, can, card, debounce, deptOptions, disclaimer, empty, fmtTime, form, h, icon, kv, L, live, modal, mount, pageHead, state, table, toast } from "../core.js";

const COLORS = { draft: "#64748b", submitted: "#3b82f6", under_review: "#0ea5e9", approved: "#22c55e", returned: "#f59e0b", archived: "#475569" };
const sBadge = (r) => badge(r.status_label, COLORS[r.status]);

export async function list(root) {
  const q = h("input", { type: "search", placeholder: "Number, title, summary, location" });
  const status = h("select", h("option", { value: "" }, "Any status"), can("cad.reports.review") ? h("option", { value: "awaiting_review" }, "Awaiting review") : null,
    Object.entries(COLORS).map(([k]) => h("option", { value: k }, k.replace("_", " "))));
  const mine = h("input", { type: "checkbox", checked: !can("cad.reports.view_all") });
  const dept = h("select", deptOptions("All departments").map(([v, l]) => h("option", { value: v }, l)));
  const body = h("div");
  const load = debounce(async () => {
    const rows = await api("reports", { query: { q: q.value, status: status.value, mine: mine.checked, department_id: dept.value } });
    mount(body, table([{ label: "Report", render: (r) => h("b", r.number) }, { label: "Title", key: "title" }, { label: "Author", render: (r) => r.author || "—" },
      { label: "Status", render: sBadge }, { label: "Rev", key: "revision", num: true }, { label: "Updated", render: (r) => fmtTime(r.updated_at) }],
      rows, { onRow: (r) => { location.hash = `#/records/report/${r.id}`; }, emptyText: "No reports found." }));
  }, 250);
  q.addEventListener("input", load); [status, mine, dept].forEach((x) => x.addEventListener("change", load));
  mount(root, pageHead("Incident Reports", "Write, submit and review reports. Every save is kept as a revision.", [
    can("cad.reports.view_all") ? h("a", { class: "btn sm", href: "/api/reports/export.csv", download: "" }, icon("download"), "Export CSV") : null,
    btn("New report", () => { location.hash = "#/records/report/new"; }, { kind: "primary", sm: true, ico: "plus" })]),
    card(h("div", { class: "filters" }, q, status, dept, h("label", { class: "check" }, mine, "Mine only")), body, { flush: true }));
  load();
  return live(["report."], load);
}

function reportFields(templateKey) {
  const templates = L.settings("reports.templates") || [];
  const tpl = templates.find((t) => t.key === templateKey) || templates[0];
  return [
    { name: "template_key", label: "Template", type: "select", options: templates.map((t) => [t.key, t.label]) },
    { name: "title", label: "Title", required: true },
    { name: "incident_id", label: "Incident number or ID", hint: "e.g. NX-2026-000012" },
    { name: "department_id", label: "Department", type: "select", options: deptOptions(), nullable: true, numeric: true },
    { name: "callsign", label: "Callsign" }, { name: "incident_type", label: "Incident type" },
    { name: "location", label: "Location" }, { name: "occurred_at", label: "Date & time", type: "datetime-local" },
    { name: "involved_personnel", label: "Involved personnel", full: true },
    { name: "summary", label: "Summary", type: "textarea", full: true, rows: 2, required: true },
    { name: "description", label: "Full description", type: "textarea", full: true, rows: 8, required: true },
    { name: "notes", label: "Additional notes", type: "textarea", full: true, rows: 2 },
    { name: "evidence", label: "Evidence references", type: "textarea", full: true, rows: 2, hint: "Links, screenshot names, clip timestamps" },
    ...(tpl?.fields?.length ? [{ section: `${tpl.label} fields` }, ...tpl.fields.map((f) => ({ name: `cf_${f.key}`, label: f.label, type: f.type === "textarea" ? "textarea" : f.type === "select" ? "select" : "text", options: f.options, full: f.type === "textarea" }))] : []),
  ];
}
function collect(f) {
  const v = f.values(); const custom = {};
  for (const k of Object.keys(v)) if (k.startsWith("cf_")) { custom[k.slice(3)] = v[k]; delete v[k]; }
  v.custom_fields = custom;
  v.occurred_at = v.occurred_at ? new Date(v.occurred_at).toISOString() : null;
  if (!v.incident_id) v.incident_id = null;
  return v;
}

export async function create(root, _p, query) {
  let tplKey = (L.settings("reports.templates") || [])[0]?.key || "incident";
  const wrap = h("div");
  let f;
  const render = (vals = {}) => {
    f = form(reportFields(tplKey), { template_key: tplKey, department_id: state.me.preferences?.default_department_id ?? "", ...vals });
    f.inputs.template_key.addEventListener("change", () => { const cur = collect(f); tplKey = f.inputs.template_key.value; render({ ...cur, template_key: tplKey }); });
    mount(wrap, f.el);
  };
  let prefill = {};
  if (query.incident) {
    const inc = await api(`cad/incidents/${query.incident}`).catch(() => null);
    if (inc) prefill = { incident_id: inc.number, title: `${inc.category_label} — ${inc.number}`, location: inc.location_name || inc.street, incident_type: inc.subtype || inc.category_label, department_id: inc.department_id ?? "" };
  }
  render(prefill);
  mount(root, pageHead("New report", "Saved as a draft first. Submit it for supervisor review when ready."),
    card(null, h("div", { class: "stack" }, wrap, disclaimer(), h("div", { class: "row" },
      btn("Save draft", async () => { const r = await api("reports", { method: "POST", body: collect(f) }); toast(`${r.number} saved as draft`, "ok"); location.hash = `#/records/report/${r.id}`; }, { kind: "primary" }),
      btn("Cancel", () => history.back())))));
}

export async function detail(root, [id]) {
  const load = async () => {
    const r = await api(`reports/${id}`);
    const editing = r.can_edit;
    let f = null;
    const content = editing ? (() => { f = form(reportFields(r.template_key), { ...r, incident_id: r.incident_number || "", occurred_at: r.occurred_at ? new Date(r.occurred_at).toISOString().slice(0, 16) : "",
      ...Object.fromEntries(Object.entries(r.custom_fields || {}).map(([k, v]) => [`cf_${k}`, v])) }); return f.el; })()
      : h("div", { class: "stack" }, kv([["Template", r.template_key], ["Incident", r.incident_number ? h("a", { href: `#/cad/incident/${r.incident_id}` }, r.incident_number) : null], ["Callsign", r.callsign],
        ["Incident type", r.incident_type], ["Location", r.location], ["Occurred", fmtTime(r.occurred_at)], ["Involved personnel", r.involved_personnel],
        ...Object.entries(r.custom_fields || {}).map(([k, v]) => [k, v])]),
        h("h4", "Summary"), h("div", { style: { whiteSpace: "pre-wrap" } }, r.summary || "—"), h("h4", "Full description"), h("div", { style: { whiteSpace: "pre-wrap" } }, r.description || "—"),
        r.notes ? [h("h4", "Notes"), h("div", { style: { whiteSpace: "pre-wrap" } }, r.notes)] : null, r.evidence ? [h("h4", "Evidence"), h("div", { style: { whiteSpace: "pre-wrap" } }, r.evidence)] : null);
    const comment = h("textarea", { rows: 3, placeholder: "Reviewer comment (required to return a report)" });
    const review = (action) => async () => { await api(`reports/${r.id}/review`, { method: "POST", body: { action, comment: comment.value } }); toast("Review saved", "ok"); load(); };
    mount(root, pageHead(`${r.number} — ${r.title}`, `By ${r.author || "—"} · revision ${r.revision}`, [sBadge(r),
      editing ? btn("Save changes", async () => { await api(`reports/${r.id}`, { method: "PATCH", body: collect(f) }); toast("Saved as a new revision", "ok"); load(); }, { sm: true }) : null,
      editing ? btn("Submit for review", async () => { if (f) await api(`reports/${r.id}`, { method: "PATCH", body: collect(f) }); await api(`reports/${r.id}/submit`, { method: "POST" }); toast("Submitted", "ok"); load(); }, { sm: true, kind: "primary" }) : null,
      h("a", { class: "btn sm", href: `/api/reports/${r.id}/export`, download: "" }, icon("download"), "Export"), btn("Print", () => window.print(), { sm: true, ico: "printer" })]),
      r.status === "returned" ? h("div", { class: "notice warn", style: { marginBottom: "14px" } }, "This report was returned for changes. See the reviewer comments, edit, and resubmit.") : null,
      h("div", { class: "grid", style: { gridTemplateColumns: "minmax(0,1fr) 340px", alignItems: "start" } },
        h("div", { class: "cad-col" }, card("Report", content), disclaimer()),
        h("div", { class: "cad-col" },
          r.can_review ? card("Supervisor review", h("div", { class: "stack" }, comment, h("div", { class: "row wrap" },
            r.status === "submitted" ? btn("Start review", review("start"), { sm: true }) : null,
            ["submitted", "under_review"].includes(r.status) ? btn("Approve", review("approve"), { sm: true, kind: "primary" }) : null,
            ["submitted", "under_review"].includes(r.status) ? btn("Return for changes", review("return"), { sm: true, kind: "danger" }) : null,
            btn("Comment", review("comment"), { sm: true }), r.status !== "archived" ? btn("Archive", review("archive"), { sm: true }) : null))) : null,
          card(`Comments (${r.comments.length})`, r.comments.length ? h("div", { class: "list" }, r.comments.map((c) => h("div", { class: "list-item" }, h("div", { class: "grow" },
            h("div", { class: "meta" }, c.user, " · ", c.action, " · ", fmtTime(c.created_at)), c.body ? h("div", { style: { whiteSpace: "pre-wrap" } }, c.body) : null)))) : empty("No comments."), { flush: true }),
          card(`Revisions (${r.revisions.length})`, table([{ label: "Rev", key: "revision" }, { label: "Status", key: "status" }, { label: "Reason", key: "reason" }, { label: "When", render: (v) => fmtTime(v.created_at) }],
            r.revisions, { onRow: async (v) => { const snap = await api(`reports/${r.id}/revisions/${v.revision}`);
              modal(`Revision ${v.revision}`, h("div", { class: "stack" }, kv(Object.entries(snap.snapshot).filter(([, x]) => x && typeof x !== "object").map(([k, x]) => [k, h("span", { style: { whiteSpace: "pre-wrap" } }, String(x))]))), { submitLabel: "Close" }); } }), { flush: true }))));
  };
  await load();
  return live(["report.changed"], (ev) => { if (String(ev.payload?.id) === String(id)) load(); });
}

