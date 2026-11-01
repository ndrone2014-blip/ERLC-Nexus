// Live ERLC map + map editor. Game coords (API LocationX/Z) → image pixels via admin calibration.
import { api, ago, badge, btn, can, card, confirmDialog, empty, form, h, icon, L, live, modal, mount, pageHead, state, table, toast } from "../core.js";
import { incidentDialog } from "./cad.js";

const TEAM_COLORS = { police: "#3b82f6", sheriff: "#b45309", fire: "#ef4444", dot: "#eab308", civilian: "#94a3b8", jail: "#a855f7" };

function makeMap(el, cfg) {
  const S = cfg.size;
  const map = window.L.map(el, { crs: window.L.CRS.Simple, minZoom: -3, maxZoom: 2, zoomSnap: 0.25, attributionControl: true, zoomControl: true });
  const bounds = [[0, 0], [S, S]];
  window.L.imageOverlay(cfg.image_url, bounds, { attribution: cfg.source_note }).addTo(map);
  map.fitBounds(bounds);
  map.setMaxBounds([[-S * 0.25, -S * 0.25], [S * 1.25, S * 1.25]]);
  const cal = cfg.calibration;
  const toLL = (x, z) => [S - (z * cal.scale + cal.offset_z), x * cal.scale + cal.offset_x];
  const toGame = (ll) => ({ x: (ll.lng - cal.offset_x) / cal.scale, z: (S - ll.lat - cal.offset_z) / cal.scale });
  const toPx = (ll) => ({ px: ll.lng, py: S - ll.lat });
  return { map, toLL, toGame, toPx };
}

function marker(color, cls = "") {
  const el = document.createElement("div");
  el.className = `nx-marker ${cls}`;
  if (cls.includes("hollow")) el.style.borderColor = color; else el.style.background = color;
  return window.L.divIcon({ html: el.outerHTML, className: "", iconSize: [18, 18], iconAnchor: [9, 9] });
}
function popup(...nodes) { const d = h("div", { class: "stack", style: { gap: "4px", minWidth: "180px" } }, nodes); return d; }

export async function liveMap(root) {
  const cfg = await api("map/config");
  const mapEl = h("div", { id: "map" });
  const layersState = { incidents: true, units: true, traffic: true, players: can("erlc.server.view"), locations: true };
  const search = h("input", { type: "search", placeholder: "Search locations…" });
  const results = h("div", { class: "stack small" });
  const updated = h("div", { class: "small muted" });
  const toggles = Object.keys(layersState).map((k) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: layersState[k], onchange: (e) => { layersState[k] = e.target.checked; render(); } }), k[0].toUpperCase() + k.slice(1)));
  const panel = h("div", { class: "map-panel" }, h("h3", "Layers"), toggles, h("div", { class: "hr" }), search, results, updated,
    can("cad.map.edit") ? h("a", { class: "btn sm", href: "#/cad/map-editor" }, icon("edit"), "Map editor") : null);
  const legend = h("div", { class: "map-legend" },
    h("div", { class: "row" }, h("span", { class: "nx-marker small", style: { background: "#ef4444" } }), "Incident (priority colour)"),
    h("div", { class: "row" }, h("span", { class: "nx-marker small square", style: { background: "#22c55e" } }), "Unit — API position"),
    h("div", { class: "row" }, h("span", { class: "nx-marker small square hollow", style: { borderColor: "#22c55e" } }), "Unit — manual / preset"),
    h("div", { class: "row" }, h("span", { class: "nx-marker small diamond", style: { background: "#f59e0b" } }), "Traffic stop"),
    h("div", { class: "row" }, h("span", { class: "nx-marker small", style: { background: "#94a3b8" } }), "Player (official API)"),
    cfg.calibration.verified ? null : h("div", { style: { color: "var(--warn)" } }, "⚠ Map calibration not verified"));
  mount(root, pageHead("Live Map", "Incidents, units, traffic stops and players on the official ERLC map.", [
    can("cad.incident.create") ? h("span", { class: "small muted" }, "Right-click the map to create an incident or place a unit") : null]),
    h("div", { class: "map-wrap" }, mapEl, panel, legend));
  const { map, toLL, toGame } = makeMap(mapEl, cfg);
  const group = window.L.layerGroup().addTo(map);
  let data = null, locations = [];

  map.on("contextmenu", async (e) => {
    const g = toGame(e.latlng);
    const items = h("div", { class: "stack", style: { gap: "6px" } }, h("div", { class: "small muted" }, `Game position ≈ ${Math.round(g.x)}, ${Math.round(g.z)}`),
      can("cad.incident.create") ? btn("Create incident here", async () => { map.closePopup(); const r = await incidentDialog({ map_x: g.x.toFixed(1), map_z: g.z.toFixed(1), source: "map" }); if (r) location.hash = `#/cad/incident/${r.id}`; }, { sm: true, kind: "primary" }) : null,
      btn("Place a unit here (manual)", async () => {
        map.closePopup();
        const units = await api("cad/my-units").then((m) => (can("cad.dispatch") || can("cad.unit.manage") ? api("cad/units") : m));
        const f = form([{ name: "unit", label: "Unit", type: "select", options: units.map((u) => [u.id, u.callsign]) }, { name: "text", label: "Location description", placeholder: "e.g. Main St & 2nd" }]);
        await modal("Set unit location", units.length ? f.el : empty("No units available."), { onSubmit: async () => { const v = f.values(); await api(`cad/units/${v.unit}/location`, { method: "POST", body: { text: v.text || "Map position", x: g.x, z: g.z } }); toast("Unit location set (manual)", "ok"); } });
      }, { sm: true }));
    window.L.popup().setLatLng(e.latlng).setContent(items).openOn(map);
  });

  function render() {
    group.clearLayers();
    if (!data) return;
    if (layersState.locations) locations.forEach((l) => {
      const cat = (cfg.categories || []).find((c) => c.key === l.category);
      window.L.marker(toLL(l.x, l.z), { icon: marker(l.color || cat?.color || "#a855f7", "small" + (l.verified ? "" : " unverified")), title: l.name })
        .bindPopup(popup(h("b", l.name), h("span", { class: "small muted" }, cat?.label || l.category), l.description ? h("span", { class: "small" }, l.description) : null, l.verified ? null : h("span", { class: "small", style: { color: "var(--warn)" } }, "Position not yet verified"))).addTo(group);
    });
    if (layersState.players) data.players.forEach((p) => {
      const color = TEAM_COLORS[(p.team || "").toLowerCase()] || "#94a3b8";
      window.L.circleMarker(toLL(p.x, p.z), { radius: 5, color: "#fff", weight: 1, fillColor: color, fillOpacity: 1 })
        .bindPopup(popup(h("b", p.name), h("span", { class: "small" }, `${p.team}${p.callsign ? " · " + p.callsign : ""}`), h("span", { class: "small muted" }, `${p.street || ""} ${p.postal ? "· Postal " + p.postal : ""}`), h("span", { class: "small muted" }, "Position from the official ERLC API"))).addTo(group);
    });
    if (layersState.traffic) data.traffic_stops.forEach((t) => window.L.marker(toLL(t.x, t.z), { icon: marker("#f59e0b", "diamond") })
      .bindPopup(popup(h("b", `Traffic stop ${t.number}`), h("span", { class: "small" }, `${t.callsign} · ${t.plate || ""}`), h("span", { class: "small muted" }, t.location), h("a", { href: `#/cad/traffic/${t.id}` }, "Open stop"))).addTo(group));
    if (layersState.units) data.units.forEach((u) => {
      const m = window.L.marker(toLL(u.x, u.z), { icon: marker(u.color, "square" + (u.source === "api" ? "" : " hollow")) })
        .bindPopup(popup(h("b", u.callsign), h("span", { class: "small" }, `${u.department || ""} · ${u.status}`), h("span", { class: "small muted" }, u.text || ""),
          h("span", { class: "small muted" }, u.source === "api" ? `API position · ${ago(u.updated_at)}` : `Manual location · ${ago(u.updated_at)}`))).addTo(group);
      m.bindTooltip(u.callsign, { permanent: true, direction: "right", offset: [10, 0], className: "nx-label" });
    });
    if (layersState.incidents) data.incidents.forEach((i) => window.L.marker(toLL(i.x, i.z), { icon: marker(i.color), zIndexOffset: 1000 })
      .bindPopup(popup(h("b", `P${i.priority} ${i.number}`), h("span", { class: "small" }, i.location || i.category), h("span", { class: "small muted" }, i.description),
        h("span", { class: "small muted" }, i.source === "api" ? "Location from an official ERLC API call" : "Manually entered location"), h("a", { href: `#/cad/incident/${i.id}` }, "Open incident"))).addTo(group));
  }
  async function load() {
    [data, locations] = await Promise.all([api("map/live"), api("map/locations")]);
    updated.textContent = data.players_fetched_at ? `Players updated ${ago(data.players_fetched_at)}` : "No live player positions yet";
    render();
  }
  search.addEventListener("input", () => {
    const q = search.value.toLowerCase();
    mount(results, q.length < 2 ? [] : locations.filter((l) => l.name.toLowerCase().includes(q) || (l.postal || "") === q).slice(0, 8).map((l) =>
      h("a", { href: "javascript:void 0", onclick: () => { map.setView(toLL(l.x, l.z), 1); } }, l.name)));
  });
  await load();
  setTimeout(() => map.invalidateSize(), 50);
  const off = live(["incident.", "unit.", "units.", "traffic.", "erlc.synced", "map."], load, 800);
  return () => { off(); map.remove(); };
}

export async function editor(root) {
  if (!can("cad.map.edit")) return mount(root, h("div", { class: "notice bad" }, "You need map editing permission."));
  const cfg = await api("map/config");
  const mapEl = h("div", { class: "map" });
  const listEl = h("div");
  const calEl = h("div");
  mount(root, pageHead("Map Editor", "Place locations by dragging markers. Right-click the map to add a location.", [h("a", { class: "btn sm", href: "#/cad/map" }, icon("map"), "Back to live map")]),
    h("div", { class: "grid", style: { gridTemplateColumns: "minmax(0,1fr) 360px", alignItems: "start" } },
      h("div", { class: "map-wrap" }, mapEl), h("div", { class: "cad-col" }, card("Calibration", calEl), card("Locations", listEl, { flush: true }))));
  const { map, toLL, toGame, toPx } = makeMap(mapEl, cfg);
  const group = window.L.layerGroup().addTo(map);
  let locs = [];
  const cats = cfg.categories || [];

  const locDialog = (values = {}, id = null) => {
    const f = form([{ name: "name", label: "Name", required: true }, { name: "category", label: "Category", type: "select", options: cats.map((c) => [c.key, c.label]) },
      { name: "street", label: "Street" }, { name: "postal", label: "Postal" }, { name: "x", label: "Game X", type: "number", step: "any" }, { name: "z", label: "Game Z", type: "number", step: "any" },
      { name: "color", label: "Marker colour (optional)", type: "color" }, { name: "description", label: "Description", type: "textarea", full: true }], { category: "custom", color: "#a855f7", ...values });
    return modal(id ? "Edit location" : "New location", f.el, { onSubmit: async () => { const v = f.values(); await api(id ? `map/locations/${id}` : "map/locations", { method: id ? "PATCH" : "POST", body: v }); toast("Location saved", "ok"); load(); } });
  };
  map.on("contextmenu", (e) => { const g = toGame(e.latlng); locDialog({ x: g.x.toFixed(1), z: g.z.toFixed(1) }); });

  async function load() {
    locs = await api("map/locations", { query: { include_archived: true } });
    group.clearLayers();
    locs.filter((l) => !l.is_archived).forEach((l) => {
      const cat = cats.find((c) => c.key === l.category);
      const m = window.L.marker(toLL(l.x, l.z), { draggable: true, icon: marker(l.color || cat?.color || "#a855f7", l.verified ? "" : "unverified"), title: l.name }).addTo(group);
      m.bindTooltip(l.name, { direction: "top", className: "nx-label" });
      m.on("dragend", async () => { const g = toGame(m.getLatLng()); await api(`map/locations/${l.id}`, { method: "PATCH", body: { x: Number(g.x.toFixed(1)), z: Number(g.z.toFixed(1)) } }); toast(`${l.name} moved`, "ok"); load(); });
    });
    mount(listEl, table([{ label: "Name", render: (l) => h("span", l.name, l.verified ? "" : h("span", { class: "small", style: { color: "var(--warn)" } }, " · unverified")) },
      { label: "Category", key: "category" },
      { label: "", render: (l) => h("div", { class: "row" }, btn("Edit", (e) => { e.stopPropagation(); locDialog(l, l.id); }, { sm: true }),
        btn(l.is_archived ? "Restore" : "Archive", async (e) => { e.stopPropagation(); await api(`map/locations/${l.id}`, { method: "PATCH", body: { is_archived: !l.is_archived } }); load(); }, { sm: true })) }],
    locs, { onRow: (l) => map.setView(toLL(l.x, l.z), 1) }), h("div", { style: { padding: "10px" } }, btn("Add location", () => locDialog(), { sm: true, ico: "plus" })));
  }

  // Two-point calibration using live player positions from the official API.
  const cal = cfg.calibration;
  const points = [];
  let picking = null;
  const status = h("div", { class: "small muted" });
  async function startPick(idx) {
    const live_ = await api("map/live");
    if (!live_.players.length) return toast("No live player positions available. Have someone stand at a landmark in-game, wait for a sync, then try again.", "warn");
    const f = form([{ name: "player", label: "Reference player (from the official API)", type: "select", options: live_.players.map((p, i) => [i, `${p.name} — ${p.street || "?"} (${Math.round(p.x)}, ${Math.round(p.z)})`]) }]);
    const ok = await modal(`Reference point ${idx + 1}`, h("div", { class: "stack" }, f.el, h("div", { class: "small muted" }, "After choosing, click the exact spot where that player is standing on the map image.")), { submitLabel: "Choose & click map" });
    if (!ok) return;
    const p = live_.players[Number(f.values().player)];
    picking = { idx, x: p.x, z: p.z };
    status.textContent = `Click where ${p.name} is on the map…`;
  }
  map.on("click", (e) => {
    if (!picking) return;
    const px = toPx(e.latlng);
    points[picking.idx] = { x: picking.x, z: picking.z, px: px.px, py: px.py };
    status.textContent = `Point ${picking.idx + 1} set.`;
    picking = null;
    renderCal();
  });
  const manual = form([{ name: "scale", label: "Scale (px per game unit)", type: "number", step: "any" }, { name: "offset_x", label: "Offset X (px)", type: "number", step: "any" }, { name: "offset_z", label: "Offset Z (px)", type: "number", step: "any" }], cal);
  function renderCal() {
    mount(calEl, h("div", { class: "stack" },
      h("div", { class: cal.verified ? "notice ok" : "notice warn" }, cal.verified ? "Calibration verified." : "Not verified yet. Positions from the API may be offset until you calibrate."),
      h("div", { class: "small muted" }, "The official docs don't publish the map scale, so calibrate with two reference points: real player positions from the API matched to spots on the map image."),
      h("div", { class: "row" }, btn(points[0] ? "Point 1 ✓" : "Set point 1", () => startPick(0), { sm: true }), btn(points[1] ? "Point 2 ✓" : "Set point 2", () => startPick(1), { sm: true }),
        btn("Apply", async () => { if (!points[0] || !points[1]) return toast("Set both points first", "warn"); await api("map/calibration", { method: "POST", body: { points } }); toast("Calibration saved — reloading", "ok"); setTimeout(() => location.reload(), 600); }, { sm: true, kind: "primary", disabled: !(points[0] && points[1]) })),
      status, h("details", h("summary", { class: "small" }, "Manual values"), manual.el,
        btn("Save manual calibration", async () => { await api("map/calibration", { method: "POST", body: { ...manual.values(), verified: true } }); toast("Saved — reloading", "ok"); setTimeout(() => location.reload(), 600); }, { sm: true }))));
  }
  renderCal();
  await load();
  setTimeout(() => map.invalidateSize(), 50);
  return () => map.remove();
}

