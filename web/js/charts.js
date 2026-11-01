// Minimal dependency-free SVG charts (line, bar, horizontal bar, donut).
import { h } from "./core.js";

const NS = "http://www.w3.org/2000/svg";
const PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6", "#eab308", "#f472b6", "#64748b"];
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  kids.flat().forEach((k) => k && el.appendChild(typeof k === "string" ? document.createTextNode(k) : k));
  return el;
}
const niceMax = (v) => { if (v <= 5) return 5; const p = 10 ** Math.floor(Math.log10(v)); return Math.ceil(v / p) * p; };

export function lineChart(points, { height = 200, color = "#3b82f6", label = (p) => p.x, fill = true, max: fixedMax } = {}) {
  if (!points.length) return h("div", { class: "empty" }, "No data collected for this period yet.");
  const W = 600, H = height, pl = 34, pr = 8, pt = 10, pb = 22;
  const max = fixedMax || niceMax(Math.max(...points.map((p) => p.y), 1));
  const x = (i) => pl + (points.length === 1 ? (W - pl - pr) / 2 : (i * (W - pl - pr)) / (points.length - 1));
  const y = (v) => pt + (H - pt - pb) * (1 - v / max);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", preserveAspectRatio: "none", role: "img" });
  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4;
    svg.append(s("line", { x1: pl, x2: W - pr, y1: y(v), y2: y(v), class: "grid-line" }), s("text", { x: pl - 6, y: y(v) + 3, "text-anchor": "end" }, String(Math.round(v))));
  }
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" ");
  if (fill) svg.append(s("path", { d: `${d} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`, fill: color, opacity: ".12" }));
  svg.append(s("path", { d, fill: "none", stroke: color, "stroke-width": "2", "vector-effect": "non-scaling-stroke" }));
  const step = Math.max(1, Math.ceil(points.length / 7));
  points.forEach((p, i) => {
    if (i % step === 0 || i === points.length - 1) svg.append(s("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, String(label(p))));
    const dot = s("circle", { cx: x(i), cy: y(p.y), r: points.length > 60 ? 0 : 2.5, fill: color });
    dot.append(s("title", {}, `${label(p)}: ${p.y}`));
    svg.append(dot);
  });
  return svg;
}

export function barChart(items, { height = 200, color = "#3b82f6" } = {}) {
  if (!items.length) return h("div", { class: "empty" }, "No data for this period.");
  const W = 600, H = height, pl = 30, pb = 24, pt = 8;
  const max = niceMax(Math.max(...items.map((i) => i.value), 1));
  const bw = (W - pl) / items.length;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4, yy = pt + (H - pt - pb) * (1 - v / max);
    svg.append(s("line", { x1: pl, x2: W, y1: yy, y2: yy, class: "grid-line" }), s("text", { x: pl - 5, y: yy + 3, "text-anchor": "end" }, String(Math.round(v))));
  }
  items.forEach((it, i) => {
    const bh = ((H - pt - pb) * it.value) / max;
    const r = s("rect", { x: pl + i * bw + bw * 0.15, y: H - pb - bh, width: bw * 0.7, height: Math.max(bh, 0), rx: 3, fill: it.color || color });
    r.append(s("title", {}, `${it.label}: ${it.value}`));
    svg.append(r, s("text", { x: pl + i * bw + bw / 2, y: H - 8, "text-anchor": "middle" }, String(it.label).slice(0, 10)));
  });
  return svg;
}

export function hbars(items, { color = "#3b82f6", unit = "" } = {}) {
  if (!items.length) return h("div", { class: "empty" }, "No data for this period.");
  const max = Math.max(...items.map((i) => i.value), 1);
  return h("div", { class: "stack" }, items.map((it, idx) => {
    const bar = h("span"); bar.style.width = `${(100 * it.value) / max}%`; bar.style.background = it.color || PALETTE[idx % PALETTE.length] || color;
    return h("div", h("div", { class: "row between small" }, h("span", it.label), h("span", { class: "mono" }, `${it.value}${unit}`)), h("div", { class: "meter" }, bar));
  }));
}

export function donut(items, { size = 160 } = {}) {
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!total) return h("div", { class: "empty" }, "No data.");
  const R = 60, C = 2 * Math.PI * R;
  const svg = s("svg", { viewBox: "0 0 160 160", width: size, height: size, class: "chart" });
  let off = 0;
  items.forEach((it, i) => {
    const len = (C * it.value) / total;
    const c = s("circle", { cx: 80, cy: 80, r: R, fill: "none", stroke: it.color || PALETTE[i % PALETTE.length], "stroke-width": 22,
      "stroke-dasharray": `${len} ${C - len}`, "stroke-dashoffset": -off, transform: "rotate(-90 80 80)" });
    c.append(s("title", {}, `${it.label}: ${it.value}`));
    svg.append(c); off += len;
  });
  svg.append(s("text", { x: 80, y: 86, "text-anchor": "middle", style: "font-size:20px;font-weight:700;fill:var(--text)" }, String(total)));
  const legend = h("div", { class: "legend" }, items.map((it, i) => { const sw = h("i"); sw.style.background = it.color || PALETTE[i % PALETTE.length]; return h("span", sw, `${it.label} (${it.value})`); }));
  return h("div", { class: "row wrap", style: { gap: "16px" } }, svg, legend);
}
export { PALETTE };
