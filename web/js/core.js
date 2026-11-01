// ERLC Nexus web core: API client, safe DOM builder, UI primitives, realtime.
// All user/content strings are inserted with textContent — never innerHTML.

export const state = { me: null, boot: null, csrf: "", unread: 0, wsOk: false, serverStatus: null };
const listeners = new Map();

export function on(kind, fn) {
  if (!listeners.has(kind)) listeners.set(kind, new Set());
  listeners.get(kind).add(fn);
  return () => listeners.get(kind)?.delete(fn);
}
export function emit(kind, payload) {
  for (const k of [kind, "*"]) listeners.get(k)?.forEach((fn) => { try { fn(payload, kind); } catch (e) { console.error(e); } });
}

// ---------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(status, body) { super(body?.message || `Request failed (${status})`); this.status = status; this.body = body; }
}
export async function api(path, { method = "GET", body, query, raw = false, silent = false } = {}) {
  let url = path.startsWith("/") ? path : `/api/${path}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") qs.set(k, v);
    const s = qs.toString(); if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const headers = { Accept: "application/json" };
  if (method !== "GET") { headers["X-CSRF-Token"] = state.csrf; if (body !== undefined) headers["Content-Type"] = "application/json"; }
  const res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: "same-origin" });
  if (raw) return res;
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    if (res.status === 401 && state.me) { location.hash = "#/login"; location.reload(); }
    const err = new ApiError(res.status, data);
    if (!silent) toast(err.message, "bad", res.status === 403 ? "Not allowed" : "Error");
    throw err;
  }
  return data;
}
export const can = (perm) => {
  const p = state.me?.permissions || [];
  if (p.includes("*") || p.includes(perm)) return true;
  const parts = perm.split(".");
  for (let i = 1; i < parts.length; i++) if (p.includes(parts.slice(0, i).join(".") + ".*")) return true;
  return false;
};
export const canAny = (...perms) => perms.some(can);

// ---------------------------------------------------------------- DOM
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { children.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...children) { clear(el); append(el, children); return el; }

// ---------------------------------------------------------------- icons (stroke icons, original drawings)
const ICONS = {
  home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  bell: "M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 0 0 4 0",
  activity: "M3 12h4l3 8 4-16 3 8h4",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  users: "M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 20v-2a4 4 0 0 0-3-3.87M16 2.13a4 4 0 0 1 0 7.75",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  gavel: "M14 13l-7 7-3-3 7-7M13 4l7 7M10 7l7 7M16 3l5 5",
  terminal: "M4 17l6-5-6-5M12 19h8",
  sliders: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  radio: "M4.9 19.1a10 10 0 0 1 0-14.2M19.1 4.9a10 10 0 0 1 0 14.2M7.8 16.2a6 6 0 0 1 0-8.4M16.2 7.8a6 6 0 0 1 0 8.4M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  headset: "M3 14v-2a9 9 0 0 1 18 0v2M21 15a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2zM3 15a2 2 0 0 0 2 2h1v-6H5a2 2 0 0 0-2 2zM18 17v1a3 3 0 0 1-3 3h-3",
  map: "M9 3L3 6v15l6-3 6 3 6-3V3l-6 3-6-3zM9 3v15M15 6v15",
  phone: "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l4 2",
  car: "M5 17h14M6 17v2M18 17v2M3 13l2-6h14l2 6v4H3zM7 13h.01M17 13h.01",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h6",
  scale: "M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0zM19 7l-3 7a4 4 0 0 0 6 0zM8 21h8",
  building: "M3 21h18M5 21V5l7-3 7 3v16M9 9h1M14 9h1M9 13h1M14 13h1M10 21v-4h4v4",
  badge: "M12 2l3 3h4v4l3 3-3 3v4h-4l-3 3-3-3H5v-4l-3-3 3-3V5h4z",
  hash: "M4 9h16M4 15h16M10 3L8 21M16 3l-2 18",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  chart: "M3 3v18h18M7 15l4-4 3 3 5-6",
  pie: "M21.2 15.9A10 10 0 1 1 8 2.8M22 12A10 10 0 0 0 12 2v10z",
  layers: "M12 2l10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5",
  discord: "M8 12h.01M16 12h.01M7 17c-3 0-5-2-5-2 0-5 2-9 2-9a10 10 0 0 1 5-2l.5 1.5a14 14 0 0 1 5 0L15 4a10 10 0 0 1 5 2s2 4 2 9c0 0-2 2-5 2l-1-2",
  key: "M21 2l-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zM15.5 7.5l3 3L22 7l-3-3",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  palette: "M12 22a10 10 0 1 1 10-10c0 2.8-2.2 4-4 4h-2a2 2 0 0 0-1 3.7A2 2 0 0 1 12 22zM7.5 10.5h.01M10.5 7.5h.01M15.5 8.5h.01",
  database: "M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  heart: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z",
  plus: "M12 5v14M5 12h14",
  x: "M18 6L6 18M6 6l12 12",
  check: "M20 6L9 17l-5-5",
  refresh: "M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.8-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  menu: "M3 6h18M3 12h18M3 18h18",
  edit: "M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z",
  trash: "M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  printer: "M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z",
  link: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
  alert: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  pin: "M12 22s7-7.5 7-13a7 7 0 0 0-14 0c0 5.5 7 13 7 13zM12 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  grip: "M9 5h.01M9 12h.01M9 19h.01M15 5h.01M15 12h.01M15 19h.01",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  play: "M5 3l14 9-14 9z",
  stop: "M5 5h14v14H5z",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
};
export function icon(name, cls = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("class", ("ico " + cls).trim());
  const p = document.createElementNS(ns, "path"); p.setAttribute("d", ICONS[name] || ICONS.hash); svg.appendChild(p);
  return svg;
}

// ---------------------------------------------------------------- formatting
export function fmtTime(v, opts = {}) {
  if (!v) return "—";
  const d = new Date(v);
  if (opts.time) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (opts.date) return d.toLocaleDateString();
  return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
export function ago(v) {
  if (!v) return "—";
  const s = Math.round((Date.now() - new Date(v).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
export function duration(sec) {
  if (sec === null || sec === undefined) return "—";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}:${String(s).padStart(2, "0")}`;
}
export function timer(fromIso) {
  const el = h("span", { class: "mono", dataset: { since: fromIso || "" } }, duration((Date.now() - new Date(fromIso)) / 1000));
  return el;
}
setInterval(() => document.querySelectorAll("[data-since]").forEach((el) => {
  if (el.dataset.since) el.textContent = duration((Date.now() - new Date(el.dataset.since)) / 1000);
}), 1000);

// ---------------------------------------------------------------- UI primitives
export function toast(message, kind = "info", title = "") {
  const root = document.getElementById("toasts");
  const el = h("div", { class: `toast ${kind}`, role: "status" }, title ? h("b", title) : null, message);
  root.appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 7000 : 4000);
}
export function badge(text, color, solid = false) {
  const el = h("span", { class: "badge" + (solid ? " solid" : "") }, text);
  if (color) { if (solid) el.style.background = color; else { el.style.color = color; el.style.background = color + "22"; el.style.borderColor = color + "44"; } }
  return el;
}
export function prio(level, color, name) {
  const el = h("span", { class: "prio", title: name || `Priority ${level}` }, `P${level}`);
  el.style.background = color || "#64748b";
  return el;
}
export function statusPill(label, color) {
  const d = h("span", { class: "dot" }); d.style.background = color || "#64748b";
  return h("span", { class: "status-pill" }, d, label);
}
export function btn(label, onclick, { kind = "", ico, sm = false, title, disabled = false, type = "button" } = {}) {
  return h("button", { class: `btn ${kind} ${sm ? "sm" : ""}`, type, onclick, title, disabled }, ico ? icon(ico) : null, label);
}
export function card(title, body, { actions, flush = false, cls = "" } = {}) {
  return h("section", { class: `card ${cls}` },
    title !== null ? h("div", { class: "card-head" }, typeof title === "string" ? h("h3", title) : title, actions ? h("div", { class: "row" }, actions) : null) : null,
    h("div", { class: "card-body" + (flush ? " flush" : "") }, body));
}
export function stat(label, value, { sub, tone = "", ico } = {}) {
  return h("div", { class: `stat ${tone}` }, h("span", { class: "label" }, ico ? icon(ico) : null, label), h("span", { class: "value" }, value ?? "—"),
    sub ? h("span", { class: "sub" }, sub) : null);
}
export function empty(text, ico = "list") { return h("div", { class: "empty" }, icon(ico), h("div", text)); }
export function pageHead(title, subtitle, actions = []) {
  return h("div", { class: "page-head" }, h("div", h("h1", title), subtitle ? h("p", subtitle) : null), h("div", { class: "actions" }, actions));
}
export function disclaimer() {
  return h("div", { class: "disclaimer" }, icon("alert"), state.boot?.settings?.["records.disclaimer"] || "All records are fictional ERLC roleplay data.");
}
export function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v]) => [h("dt", k), h("dd", v === null || v === undefined || v === "" ? "—" : v)]));
}

export function table(columns, rows, { onRow, emptyText = "Nothing here yet." } = {}) {
  if (!rows?.length) return empty(emptyText);
  return h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", h("tr", columns.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)))),
    h("tbody", rows.map((r) => h("tr", { class: onRow ? "clickable" : "", onclick: onRow ? () => onRow(r) : null },
      columns.map((c) => h("td", { class: c.num ? "num" : "" }, c.render ? c.render(r) : (r[c.key] ?? "—"))))))));
}

export function tabs(items, onChange, active) {
  const bar = h("div", { class: "tabs" });
  const render = (cur) => mount(bar, items.map(([key, label]) => h("button", { class: key === cur ? "active" : "", onclick: () => { render(key); onChange(key); } }, label)));
  render(active ?? items[0][0]);
  return bar;
}

// Modal returns a promise resolved with the submit value (or null on cancel).
export function modal(title, body, { submitLabel = "Save", onSubmit, wide = false, danger = false, footer } = {}) {
  return new Promise((resolve) => {
    const root = document.getElementById("modal-root");
    const close = (v) => { bd.remove(); document.removeEventListener("keydown", esc); resolve(v); };
    const esc = (e) => { if (e.key === "Escape") close(null); };
    const submit = h("button", { class: `btn ${danger ? "danger" : "primary"}`, type: "submit" }, submitLabel);
    const form = h("form", { class: `modal ${wide ? "wide" : ""}`, onsubmit: async (e) => {
      e.preventDefault();
      if (!onSubmit) return close(true);
      submit.disabled = true;
      try { const v = await onSubmit(form); if (v !== false) close(v ?? true); }
      catch (err) { if (!(err instanceof ApiError)) toast(err.message, "bad"); }
      finally { submit.disabled = false; }
    } },
      h("div", { class: "modal-head" }, h("h2", title), h("button", { class: "iconbtn", type: "button", onclick: () => close(null), "aria-label": "Close" }, icon("x"))),
      h("div", { class: "modal-body" }, body),
      footer === null ? null : h("div", { class: "modal-foot" }, footer || [h("button", { class: "btn ghost", type: "button", onclick: () => close(null) }, "Cancel"), onSubmit !== undefined || submitLabel ? submit : null]));
    const bd = h("div", { class: "modal-backdrop", onmousedown: (e) => { if (e.target === bd) close(null); } }, form);
    root.appendChild(bd);
    document.addEventListener("keydown", esc);
    setTimeout(() => form.querySelector("input:not([type=hidden]),select,textarea")?.focus(), 30);
  });
}
export async function confirmDialog(title, message, label = "Confirm", danger = true) {
  return !!(await modal(title, h("p", message), { submitLabel: label, danger, onSubmit: () => true }));
}

// Declarative form fields → {el, values()}.
export function form(fields, values = {}) {
  const inputs = {};
  const grid = h("div", { class: "form-grid" });
  for (const f of fields) {
    if (f.section) { grid.appendChild(h("div", { class: "form-section" }, f.section)); continue; }
    const v = values[f.name] ?? f.value ?? "";
    let input;
    if (f.type === "select") {
      input = h("select", { name: f.name, required: f.required }, (f.options || []).map((o) => {
        const [val, label] = Array.isArray(o) ? o : [o, o];
        return h("option", { value: val, selected: String(val) === String(v) }, label);
      }));
    } else if (f.type === "textarea") input = h("textarea", { name: f.name, rows: f.rows || 4, required: f.required, placeholder: f.placeholder || "", maxlength: f.max }, String(v ?? ""));
    else if (f.type === "checkbox") input = h("input", { type: "checkbox", name: f.name, checked: !!v });
    else input = h("input", { type: f.type || "text", name: f.name, value: v ?? "", required: f.required, placeholder: f.placeholder || "", maxlength: f.max, min: f.min, max: f.maxv, step: f.step, list: f.list });
    inputs[f.name] = input;
    const wrap = f.type === "checkbox"
      ? h("label", { class: "check " + (f.full ? "full" : "") }, input, f.label)
      : h("label", { class: "field " + (f.full ? "full" : "") }, f.label + (f.required ? " *" : ""), input, f.hint ? h("span", { class: "hint" }, f.hint) : null);
    grid.appendChild(wrap);
  }
  return {
    el: grid, inputs,
    values() {
      const out = {};
      for (const f of fields) {
        if (!f.name) continue;
        const i = inputs[f.name];
        let val = f.type === "checkbox" ? i.checked : i.value;
        if ((f.type === "number" || f.numeric) && val !== "") val = Number(val);
        if (f.nullable && val === "") val = null;
        out[f.name] = val;
      }
      return out;
    },
  };
}

// Debounce helper
export function debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// Lookups from bootstrap
export const L = {
  settings: (k) => state.boot?.settings?.[k],
  priorities: () => state.boot?.settings?.["cad.priorities"] || [],
  prio: (lv) => (state.boot?.settings?.["cad.priorities"] || []).find((p) => p.level === lv),
  incidentStatuses: () => state.boot?.settings?.["cad.incident_statuses"] || [],
  unitStatuses: () => state.boot?.settings?.["cad.unit_statuses"] || [],
  categories: () => state.boot?.settings?.["cad.incident_categories"] || [],
  departments: () => state.boot?.departments || [],
  dept: (id) => (state.boot?.departments || []).find((d) => d.id === id),
};
export const deptOptions = (blank = "— None —") => [["", blank], ...L.departments().map((d) => [d.id, `${d.abbreviation} — ${d.name}`])];

// ---------------------------------------------------------------- realtime
let ws, wsTimer, wsBackoff = 1000;
export function connectRealtime() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { state.wsOk = true; wsBackoff = 1000; emit("ws.status", true); };
  ws.onmessage = (e) => { try { const ev = JSON.parse(e.data); emit(ev.kind, ev.payload); emit("event", ev); } catch { /* ignore */ } };
  ws.onclose = (e) => {
    state.wsOk = false; emit("ws.status", false);
    if (e.code === 4401) return;
    clearTimeout(wsTimer); wsTimer = setTimeout(connectRealtime, wsBackoff); wsBackoff = Math.min(wsBackoff * 2, 30000);
  };
  setInterval(() => { if (ws?.readyState === 1) ws.send("ping"); }, 25000);
}
// Re-run fn when any event with a matching prefix arrives (debounced). Returns unsubscribe.
export function live(prefixes, fn, ms = 400) {
  const run = debounce(fn, ms);
  return on("event", (ev) => { if (prefixes.some((p) => ev.kind.startsWith(p))) run(ev); });
}
