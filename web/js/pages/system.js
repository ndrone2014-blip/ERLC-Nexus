import { api, ago, badge, btn, can, card, confirmDialog, debounce, empty, fmtTime, form, h, icon, kv, L, modal, mount, pageHead, stat, state, table, tabs, toast } from "../core.js";

async function setSetting(key, value) { await api(`admin/settings/${key}`, { method: "PUT", body: { value } }); }
async function refreshBoot() { state.boot = await api("bootstrap"); }

// ---------------------------------------------------------------- Discord
export async function discord(root) {
  const d = await api("admin/discord");
  const kinds = state.boot.notification_kinds;
  const extra = { "erlc.911": "In-game 911 calls", audit: "Audit log mirror" };
  const chanInputs = Object.keys(d.channels).map((k) => { const i = h("input", { value: d.channels[k] || "", placeholder: "Channel ID (empty = off)", dataset: { key: k } }); return h("label", { class: "field" }, kinds[k] || extra[k] || k, i); });
  const comms = h("input", { value: d.comms_channel || "", placeholder: "Channel ID" });
  const sync = h("input", { type: "checkbox", checked: d.sync_comms });
  const color = h("input", { type: "color", value: d.embeds.color || "#3b82f6" });
  const footer = h("input", { value: d.embeds.footer || "ERLC Nexus" });
  mount(root, pageHead("Discord Integration", "Bot status, invite link and where notifications are posted."),
    h("div", { class: "grid g2" },
      card("Bot", h("div", { class: "stack" }, kv([["Status", d.bot_online ? h("span", { class: "row" }, h("span", { class: "dot ok" }), "Online") : h("span", { class: "row" }, h("span", { class: "dot bad" }), "Offline / not started")],
        ["Last heartbeat", d.heartbeat_at ? ago(d.heartbeat_at) : "never"], ["Bot user", d.heartbeat?.user], ["Servers", d.heartbeat?.guilds], ["Latency", d.heartbeat?.latency_ms != null ? `${d.heartbeat.latency_ms} ms` : null],
        ["Guild ID", d.guild_id || h("span", { class: "muted" }, "not set — commands sync globally (slower)")], ["Application ID", d.application_id]]),
        d.invite_url ? h("a", { class: "btn primary", href: d.invite_url, target: "_blank", rel: "noopener" }, icon("discord"), "Invite the bot to your server") : h("div", { class: "notice warn" }, "Set DISCORD_APPLICATION_ID in config.env to get an invite link."))),
      card("Website login (OAuth2)", h("div", { class: "stack" }, kv([["Configured", d.oauth_configured ? "Yes" : "No"], ["Redirect URI", h("code", d.redirect_uri)]]),
        h("div", { class: "small muted" }, "Add this exact redirect URI in the Discord Developer Portal → OAuth2 → Redirects."))),
      card("Notification channels", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Right-click a channel in Discord (Developer Mode on) → Copy Channel ID. Department-specific channels are set on each department."),
        h("div", { class: "form-grid" }, chanInputs), btn("Save channels", async () => {
          const v = Object.fromEntries(chanInputs.map((l) => { const i = l.querySelector("input"); return [i.dataset.key, i.value.trim()]; }));
          await setSetting("discord.channels", v); toast("Channels saved", "ok");
        }, { kind: "primary", sm: true })), { cls: "span2" }),
      card("Dispatch communications sync", h("div", { class: "stack" }, h("label", { class: "check" }, sync, "Post website dispatch messages & announcements to Discord"), h("label", { class: "field" }, "Comms channel ID", comms),
        btn("Save", async () => { await setSetting("discord.sync_comms", sync.checked); await setSetting("discord.comms_channel", comms.value.trim()); toast("Saved", "ok"); }, { kind: "primary", sm: true }))),
      card("Embed style", h("div", { class: "stack" }, h("label", { class: "field" }, "Embed colour", color), h("label", { class: "field" }, "Footer text", footer),
        btn("Save", async () => { await setSetting("discord.embeds", { ...d.embeds, color: color.value, footer: footer.value }); toast("Saved", "ok"); }, { kind: "primary", sm: true })))));
}

// ---------------------------------------------------------------- API configuration
export async function apiConfig(root) {
  const load = async () => {
    const c = await api("admin/erlc");
    const keyIn = h("input", { type: "password", placeholder: "Paste your ERLC server key", autocomplete: "off", style: { flex: 1 } });
    const result = h("div");
    mount(root, pageHead("API Configuration", "Connection to the official ERLC (PRC) API."),
      h("div", { class: "grid g4", style: { marginBottom: "14px" } },
        stat("Server key", c.key_configured ? (c.client.key_invalid ? "Invalid" : "Configured") : "Not set", { tone: c.key_configured && !c.client.key_invalid ? "ok" : "bad", sub: c.key_source ? `Source: ${c.key_source}` : "Add a key below" }),
        stat("Requests", c.client.requests, { sub: `${c.client.failures} failed · ${c.client.rate_limited} rate-limited` }),
        stat("Last success", c.client.last_ok ? ago(c.client.last_ok * 1000) : "never", { sub: c.client.last_latency_ms != null ? `${c.client.last_latency_ms} ms latency` : null }),
        stat("Sync leader", c.sync_leader ? c.sync_leader.holder : "none", { sub: `Every ${c.sync_interval}s · cache ${c.cache_ttl}s` })),
      c.client.key_invalid ? h("div", { class: "notice bad", style: { marginBottom: "14px" } }, c.client.key_invalid_reason, " Requests are paused to protect your server key from API blocks. Update the key to resume.") : null,
      c.api_error ? h("div", { class: "notice warn", style: { marginBottom: "14px" } }, `Last API error: ${c.api_error.message}`) : null,
      h("div", { class: "grid g2" },
        card("Server key", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Get it in-game: Settings → ER:LC API (requires the ERLC API server pack). The key is tested, then stored encrypted. It is never shown again or sent to browsers."),
          h("div", { class: "row" }, keyIn, btn("Test & save", async () => { const r = await api("admin/erlc/key", { method: "PUT", body: { key: keyIn.value } }); toast(`Connected to ${r.server_name}`, "ok"); load(); }, { kind: "primary" })),
          h("div", { class: "row" }, btn("Test connection", async () => { const r = await api("admin/erlc/test", { method: "POST" }); mount(result, h("div", { class: r.ok ? "notice ok" : "notice bad" }, r.ok ? `OK — ${r.server_name}, ${r.players}/${r.max} players, ${r.latency_ms} ms` : r.error.message)); }, { sm: true }),
            c.key_source === "dashboard (encrypted)" ? btn("Remove dashboard key", async () => { if (await confirmDialog("Remove key", "Stop using this key? (A key in config.env, if any, will be used instead.)")) { await api("admin/erlc/key", { method: "DELETE" }); load(); } }, { sm: true, kind: "danger" }) : null),
          result)),
        card("Settings (config.env)", h("div", { class: "stack" }, kv([["API base URL", h("code", c.base_url)], ["Sync interval", `${c.sync_interval}s (ERLC_SYNC_INTERVAL, min 10)`], ["Cache TTL", `${c.cache_ttl}s`],
          ["Global (public app) key", c.global_key_configured ? "Configured" : "Not used"], ["Event webhooks", c.webhook_enabled ? "Enabled (POST /api/erlc/webhook)" : "Disabled"]]),
          h("div", { class: "small muted" }, "These are set in config.env and need a restart to change."))),
        card("Rate-limit buckets (from API headers)", Object.keys(c.client.buckets).length ? table([{ label: "Bucket", render: (b) => h("code", b.name) }, { label: "Limit", render: (b) => b.limit ?? "—" }, { label: "Remaining", render: (b) => b.remaining ?? "—" },
          { label: "Resets", render: (b) => b.reset_at ? new Date(b.reset_at * 1000).toLocaleTimeString() : "—" }, { label: "", render: (b) => b.blocked ? badge("waiting", "#f59e0b") : badge("ok", "#22c55e") }],
          Object.entries(c.client.buckets).map(([name, b]) => ({ name, ...b }))) : empty("No requests yet."), { flush: true }),
        card("Recent sync cycles", table([{ label: "When", render: (r) => fmtTime(r.at, { time: true }) }, { label: "Result", render: (r) => r.ok ? badge("ok", "#22c55e") : badge("failed", "#ef4444") },
          { label: "ms", key: "ms", num: true }, { label: "Players", render: (r) => r.players ?? "—" }, { label: "Error", render: (r) => r.error || "" }], c.recent_syncs, { emptyText: "No syncs yet." }), { flush: true })),
      h("div", { class: "small muted", style: { marginTop: "12px" } }, "See docs/API_COMPATIBILITY.md for every endpoint ERLC Nexus uses and how rate limits are respected."));
  };
  await load();
}

// ---------------------------------------------------------------- Permissions
export async function permissions(root) {
  const body = h("div");
  const catalog = await api("admin/permissions");
  const byCat = {};
  catalog.forEach((p) => { (byCat[p.category] ||= []).push(p); });
  const roleDialog = async (role = null) => {
    const f = form([{ name: "name", label: "Name", required: true }, { name: "color", label: "Colour", type: "color" }, { name: "priority", label: "Priority", type: "number", hint: "Higher shows first" },
      { name: "description", label: "Description", full: true }, { name: "discord_role_ids", label: "Linked Discord role IDs", full: true, hint: "Comma separated. Members with any of these Discord roles get this role automatically (verified server-side)." }],
    role ? { ...role, discord_role_ids: role.discord_role_ids.join(", ") } : { color: "#5b8def", priority: 20 });
    const all = role?.permissions?.includes("*");
    const allBox = h("input", { type: "checkbox", checked: all, disabled: !can("*") });
    const boxes = catalog.map((p) => h("input", { type: "checkbox", value: p.key, checked: all || role?.permissions?.includes(p.key) }));
    const permGrid = h("div", { class: "grid g2" }, Object.entries(byCat).map(([cat, perms]) => h("div", { class: "card" }, h("div", { class: "card-head" }, h("h4", cat)),
      h("div", { class: "card-body stack" }, perms.map((p) => h("label", { class: "check", title: p.key }, boxes[catalog.indexOf(p)], h("span", p.description, h("span", { class: "muted small mono" }, ` ${p.key}`))))))));
    return modal(role ? `Edit role: ${role.name}` : "New role", h("div", { class: "stack" }, f.el, h("label", { class: "check" }, allBox, "Full platform access (*) — owners only"), permGrid), { wide: true, onSubmit: async () => {
      const v = f.values();
      v.discord_role_ids = v.discord_role_ids.split(",").map((x) => x.trim()).filter(Boolean);
      v.permissions = allBox.checked ? ["*"] : boxes.filter((b) => b.checked).map((b) => b.value);
      await api(role ? `admin/roles/${role.id}` : "admin/roles", { method: role ? "PATCH" : "POST", body: v }); toast("Role saved", "ok");
    } });
  };
  const show = async (tab) => {
    if (tab === "roles") {
      const roles = await api("admin/roles");
      mount(body, card(null, table([{ label: "Role", render: (r) => { const b = badge(r.name); b.style.color = r.color; return h("span", b, r.is_system ? h("span", { class: "muted small" }, " built-in") : null); } },
        { label: "Description", key: "description" }, { label: "Permissions", render: (r) => r.permissions.includes("*") ? "All" : String(r.permissions.length) },
        { label: "Discord roles", render: (r) => r.discord_role_ids.length ? r.discord_role_ids.join(", ") : "—" },
        { label: "", render: (r) => can("system.permissions") ? h("div", { class: "row" }, btn("Edit", (e) => { e.stopPropagation(); roleDialog(r).then((x) => x && show("roles")); }, { sm: true }),
          !r.is_system ? btn("Delete", async (e) => { e.stopPropagation(); if (await confirmDialog("Delete role", `Delete ${r.name}?`)) { await api(`admin/roles/${r.id}`, { method: "DELETE" }); show("roles"); } }, { sm: true, kind: "danger" }) : null) : null }], roles),
      { flush: true, actions: [can("system.permissions") ? btn("New role", () => roleDialog().then((x) => x && show("roles")), { sm: true, kind: "primary", ico: "plus" }) : null] }),
      h("div", { class: "notice", style: { marginTop: "12px" } }, "Permissions are always checked by the backend. Least-privilege defaults: new users get no access until a role is assigned here or mapped from a Discord role."));
    } else {
      const q = h("input", { type: "search", placeholder: "Search users" });
      const list = h("div");
      const roles = await api("admin/roles");
      const load = async () => {
        const users = await api("admin/users", { query: { q: q.value } });
        mount(list, table([{ label: "User", render: (u) => h("span", { class: "row" }, u.avatar_url ? h("img", { class: "avatar", src: u.avatar_url, alt: "" }) : h("span", { class: "avatar" }, (u.name || "?")[0]), h("div", h("div", u.name, u.is_active ? null : badge("disabled", "#ef4444")), h("div", { class: "small muted mono" }, u.discord_id))) },
          { label: "Roles", render: (u) => h("div", { class: "row wrap" }, u.roles.map((r) => { const b = badge(r.name); b.style.color = r.color; return b; })) },
          { label: "Last login", render: (u) => u.last_login_at ? ago(u.last_login_at) : "never" },
          { label: "", render: (u) => can("system.permissions") ? btn("Manage", async (e) => {
            e.stopPropagation();
            const detail = await api(`admin/users/${u.id}`);
            const boxes = roles.map((r) => h("label", { class: "check" }, h("input", { type: "checkbox", value: r.id, checked: detail.direct_role_ids.includes(r.id) }), r.name));
            const active = h("input", { type: "checkbox", checked: detail.is_active });
            const ok = await modal(`Manage ${u.name}`, h("div", { class: "stack" }, h("h4", "Directly assigned roles"), h("div", { class: "grid g2" }, boxes),
              h("div", { class: "small muted" }, detail.discord ? `Discord: ${detail.discord.in_guild ? "in server" : "not in server"}, ${detail.discord.role_ids.length} role(s), synced ${ago(detail.discord.synced_at)} via ${detail.discord.source}. Roles mapped from Discord roles apply automatically.` : "No Discord role data yet."),
              h("label", { class: "check" }, active, "Account active")), { onSubmit: async () => {
              await api(`admin/users/${u.id}/roles`, { method: "PUT", body: { role_ids: boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => Number(i.value)) } });
              if (active.checked !== detail.is_active) await api(`admin/users/${u.id}`, { method: "PATCH", body: { is_active: active.checked } });
            } });
            if (ok) { toast("User updated", "ok"); load(); }
          }, { sm: true }) : null }], users));
      };
      q.addEventListener("input", debounce(load, 250));
      mount(body, card(h("div", { class: "filters" }, q), list, { flush: true, actions: [can("system.permissions") ? btn("Add by Discord ID", async () => {
        const f = form([{ name: "discord_id", label: "Discord user ID", required: true }, { name: "display_name", label: "Display name" }]);
        if (await modal("Add user", h("div", { class: "stack" }, f.el, h("div", { class: "small muted" }, "Pre-create someone so you can assign roles and departments before their first login.")), { onSubmit: async () => api("admin/users", { method: "POST", body: f.values() }) })) load();
      }, { sm: true, ico: "plus" }) : null] }));
      load();
    }
  };
  mount(root, pageHead("Permissions", "Roles, granular permissions and Discord role mapping."), tabs([["roles", "Roles"], ["users", "Users"]], show), body);
  show("roles");
}

// ---------------------------------------------------------------- Logging
export async function logging(root) {
  const body = h("div");
  const show = async (tab) => {
    if (tab === "audit") {
      const cat = h("select", h("option", { value: "" }, "All categories"), ["erlc", "cad", "mdt", "department", "system"].map((c) => h("option", { value: c }, c.toUpperCase())));
      const q = h("input", { type: "search", placeholder: "User, record, action" });
      const from = h("input", { type: "date" }), to = h("input", { type: "date" });
      const list = h("div"), verify = h("span");
      let offset = 0;
      const load = async () => {
        const r = await api("admin/audit", { query: { category: cat.value, q: q.value, limit: 100, offset, date_from: from.value ? new Date(from.value).toISOString() : "", date_to: to.value ? new Date(to.value + "T23:59:59").toISOString() : "" } });
        mount(list, table([{ label: "When", render: (a) => fmtTime(a.created_at) }, { label: "Category", render: (a) => badge(a.category) }, { label: "Event", render: (a) => h("code", a.action) },
          { label: "User", key: "user" }, { label: "Record", render: (a) => a.link ? h("a", { href: a.link, onclick: (e) => e.stopPropagation() }, a.reference || a.target_id) : (a.reference || a.target_id || "—") },
          { label: "Source", key: "source" }], r.items, { onRow: (a) => modal(`${a.action}`, h("div", { class: "stack" }, kv([["When", fmtTime(a.created_at)], ["User", a.user], ["Category", a.category], ["Record", `${a.target_type} ${a.target_id || ""} ${a.reference}`], ["Department", a.department], ["Source", a.source], ["IP", a.ip], ["Hash", h("code", { style: { fontSize: "10px" } }, a.hash)]]),
            h("h4", "Previous value"), h("pre", { class: "mono", style: { whiteSpace: "pre-wrap" } }, JSON.stringify(a.old, null, 2) ?? "—"), h("h4", "New value"), h("pre", { class: "mono", style: { whiteSpace: "pre-wrap" } }, JSON.stringify(a.new, null, 2) ?? "—"),
            a.context ? [h("h4", "Context"), h("pre", { class: "mono", style: { whiteSpace: "pre-wrap" } }, JSON.stringify(a.context, null, 2))] : null), { submitLabel: "Close" }) }),
          h("div", { class: "pager" }, h("span", `${r.total} event(s)`), h("div", { class: "row" }, btn("Previous", () => { offset = Math.max(0, offset - 100); load(); }, { sm: true, disabled: !offset }), btn("Next", () => { offset += 100; load(); }, { sm: true, disabled: offset + 100 >= r.total }))));
      };
      [cat, from, to].forEach((x) => x.addEventListener("change", () => { offset = 0; load(); })); q.addEventListener("input", debounce(() => { offset = 0; load(); }, 300));
      mount(body, card(h("div", { class: "filters" }, cat, q, from, to), list, { flush: true, actions: [verify, btn("Verify integrity", async () => {
        const r = await api("admin/audit/verify");
        mount(verify, r.ok ? badge(`✓ ${r.checked} entries intact`, "#22c55e") : badge(`✗ chain broken at #${r.broken_at}: ${r.reason}`, "#ef4444"));
      }, { sm: true, ico: "shield" })] }), h("div", { class: "small muted", style: { marginTop: "8px" } }, "Audit entries are append-only and hash-chained; there is no way to edit or delete them from the interface. 'Verify integrity' detects tampering."));
      load();
    } else {
      const comp = h("select", h("option", { value: "web" }, "Website"), h("option", { value: "bot" }, "Discord bot"), h("option", { value: "launcher" }, "Launcher"));
      const level = h("select", h("option", { value: "" }, "All levels"), ["ERROR", "WARNING", "INFO"].map((l) => h("option", { value: l }, l)));
      const list = h("div");
      const load = async () => {
        const r = await api("admin/logs", { query: { component: comp.value, level: level.value, lines: 400 } });
        mount(list, r.lines.length ? h("div", { style: { maxHeight: "65vh", overflow: "auto", fontFamily: "var(--mono)", fontSize: "12px" } }, r.lines.slice().reverse().map((l) =>
          h("div", { style: { padding: "3px 12px", borderBottom: "1px solid var(--line)", color: l.level === "ERROR" ? "#fca5a5" : l.level === "WARNING" ? "#fcd34d" : "" } }, `${l.ts || ""} ${l.level || ""} ${l.logger || ""}: ${l.msg}`, l.exc ? h("pre", { style: { whiteSpace: "pre-wrap", margin: "4px 0" } }, l.exc) : null)))
          : empty(`No log lines in ${r.path}.`));
      };
      comp.onchange = load; level.onchange = load;
      mount(body, card(h("div", { class: "filters" }, comp, level, btn("Refresh", load, { sm: true, ico: "refresh" })), list, { flush: true }), h("div", { class: "small muted", style: { marginTop: "8px" } }, "Application logs are stored in data/logs with secrets automatically redacted."));
      if (can("system.configure")) load(); else mount(list, empty("Application logs need system configuration permission."));
    }
  };
  mount(root, pageHead("Logging", "Searchable audit trail and application diagnostics."), tabs([["audit", "Audit log"], ["app", "Application logs"]], show), body);
  show("audit");
}

// ---------------------------------------------------------------- Appearance & customization
function listEditor(key, columns, rows, { addRow = {}, minRows = 1 } = {}) {
  const wrap = h("div");
  const data = rows.map((r) => ({ ...r }));
  const render = () => mount(wrap, h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", h("tr", columns.map((c) => h("th", c.label)), h("th", ""))),
    h("tbody", data.map((r, i) => h("tr", columns.map((c) => {
      let input;
      const val = c.get ? c.get(r) : r[c.key];
      if (c.type === "checkbox") input = h("input", { type: "checkbox", checked: !!val, onchange: (e) => { r[c.key] = e.target.checked; } });
      else if (c.type === "select") input = h("select", { onchange: (e) => { r[c.key] = e.target.value; } }, c.options.map((o) => h("option", { value: o, selected: o === val }, o)));
      else input = h("input", { type: c.type || "text", value: val ?? "", style: { width: c.width || "100%" }, oninput: (e) => { const v = e.target.value; if (c.set) c.set(r, v); else r[c.key] = c.type === "number" ? Number(v) : v; } });
      return h("td", input);
    }), h("td", h("div", { class: "row" }, btn("↑", () => { if (i) { [data[i - 1], data[i]] = [data[i], data[i - 1]]; render(); } }, { sm: true }),
      btn("✕", () => { if (data.length > minRows) { data.splice(i, 1); render(); } }, { sm: true })))))))),
  h("div", { class: "row", style: { padding: "10px" } }, btn("Add row", () => { data.push(JSON.parse(JSON.stringify(addRow))); render(); }, { sm: true, ico: "plus" }),
    btn("Save", async () => { await setSetting(key, data); await refreshBoot(); toast("Saved", "ok"); }, { sm: true, kind: "primary" }),
    btn("Reset to defaults", async () => { if (await confirmDialog("Reset", "Restore the default values for this list?", "Reset")) { await api(`admin/settings/${key}/reset`, { method: "POST" }); await refreshBoot(); toast("Reset", "ok"); location.reload(); } }, { sm: true, kind: "ghost" })));
  render();
  return wrap;
}

export async function appearance(root) {
  const s = await api("admin/settings");
  const body = h("div");
  const show = (tab) => {
    if (tab === "branding") {
      const f = form([{ name: "community.name", label: "Community name", required: true }, { name: "community.logo_url", label: "Logo URL", hint: "Square image URL (https)" },
        { name: "appearance.accent", label: "Accent colour", type: "color" }, { name: "appearance.default_theme", label: "Default theme", type: "select", options: [["dark", "Dark"], ["light", "Light"], ["system", "Match system"]] },
        { name: "map.style", label: "Map image", type: "select", options: [["fall_postals", "Fall — with postals"], ["fall_blank", "Fall — blank"], ["snow_postals", "Winter — with postals"], ["snow_blank", "Winter — blank"]] },
        { name: "dashboard.refresh_seconds", label: "Default dashboard refresh (s)", type: "number" },
        { name: "records.disclaimer", label: "Records disclaimer", full: true }], s);
      mount(body, card(null, h("div", { class: "stack" }, f.el, btn("Save", async () => {
        const v = f.values(); for (const [k, val] of Object.entries(v)) if (JSON.stringify(val) !== JSON.stringify(s[k])) await setSetting(k, val);
        await refreshBoot(); toast("Saved — refresh to see everything update", "ok");
      }, { kind: "primary" }))));
    } else if (tab === "cad") {
      mount(body, h("div", { class: "stack" },
        card("Incident priorities", listEditor("cad.priorities", [{ label: "Level", key: "level", type: "number", width: "60px" }, { label: "Name", key: "name" }, { label: "Description", key: "description" },
          { label: "Colour", key: "color", type: "color" }, { label: "Sort weight", key: "weight", type: "number", width: "80px" }, { label: "Notify", key: "notify", type: "checkbox" }], s["cad.priorities"], { addRow: { level: 5, name: "", description: "", color: "#64748b", weight: 10, notify: false } }), { flush: true }),
        card("Incident statuses", listEditor("cad.incident_statuses", [{ label: "Key", key: "key" }, { label: "Label", key: "label" }, { label: "Colour", key: "color", type: "color" }, { label: "Open", key: "open", type: "checkbox" }], s["cad.incident_statuses"], { addRow: { key: "", label: "", color: "#64748b", open: true } }), { flush: true }),
        card("Incident categories", listEditor("cad.incident_categories", [{ label: "Key", key: "key" }, { label: "Label", key: "label" },
          { label: "Subtypes (comma separated)", get: (r) => (r.subtypes || []).join(", "), set: (r, v) => { r.subtypes = v.split(",").map((x) => x.trim()).filter(Boolean); } },
          { label: "Department types", get: (r) => (r.dept_kinds || []).join(", "), set: (r, v) => { r.dept_kinds = v.split(",").map((x) => x.trim()).filter(Boolean); } }], s["cad.incident_categories"], { addRow: { key: "", label: "", subtypes: [], dept_kinds: [] } }), { flush: true }),
        card("Unit statuses", listEditor("cad.unit_statuses", [{ label: "Key", key: "key" }, { label: "Label", key: "label" }, { label: "Code", key: "code", width: "80px" }, { label: "Colour", key: "color", type: "color" },
          { label: "Group", key: "group", type: "select", options: ["available", "busy", "unavailable"] }], s["cad.unit_statuses"], { addRow: { key: "", label: "", code: "", color: "#64748b", group: "busy" } }), { flush: true }),
        card("Other CAD settings", (() => {
          const f = form([{ name: "cad.incident_prefix", label: "Incident number prefix", hint: "NX → NX-2026-000001" }, { name: "cad.auto_status_on_assign", label: "Automatically set unit En Route on assignment / Available on close", type: "checkbox", full: true },
            ...Object.entries(s["cad.queue_alert_seconds"]).map(([p, v]) => ({ name: `q${p}`, label: `Alert when P${p} waits longer than (seconds)`, type: "number", value: v }))], s);
          return h("div", { class: "stack" }, f.el, btn("Save", async () => {
            const v = f.values(); await setSetting("cad.incident_prefix", v["cad.incident_prefix"]); await setSetting("cad.auto_status_on_assign", v["cad.auto_status_on_assign"]);
            await setSetting("cad.queue_alert_seconds", Object.fromEntries(Object.keys(s["cad.queue_alert_seconds"]).map((p) => [p, Number(v[`q${p}`])]))); await refreshBoot(); toast("Saved", "ok");
          }, { kind: "primary", sm: true }));
        })()),
        card("Map location categories", listEditor("map.location_categories", [{ label: "Key", key: "key" }, { label: "Label", key: "label" }, { label: "Colour", key: "color", type: "color" }, { label: "Icon", key: "icon" }], s["map.location_categories"], { addRow: { key: "", label: "", color: "#a855f7", icon: "pin" } }), { flush: true }),
        card("Map marker colours", (() => {
          const mc = s["map.marker_colors"];
          const f = form(Object.keys(mc).map((k) => ({ name: k, label: k, type: "color" })), mc);
          return h("div", { class: "stack" }, f.el, btn("Save", async () => { await setSetting("map.marker_colors", f.values()); toast("Saved", "ok"); }, { kind: "primary", sm: true }));
        })())));
    } else if (tab === "records") {
      const sf = s["records.searchable_fields"];
      const personBoxes = ["name", "alias", "number", "vehicle", "roblox"].map((k) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: sf.person.includes(k) }), k));
      const vehBoxes = ["plate", "owner", "make", "model", "color"].map((k) => h("label", { class: "check" }, h("input", { type: "checkbox", value: k, checked: sf.vehicle.includes(k) }), k));
      const tpl = s["reports.templates"];
      const tplArea = h("textarea", { rows: 14, class: "mono", style: { width: "100%" } }, JSON.stringify(tpl, null, 2));
      const misc = form([{ name: "bolo.default_expiry_hours", label: "Default BOLO expiry (hours, 0 = never)", type: "number" }, { name: "shift.require_approval", label: "Shifts require supervisor approval", type: "checkbox" },
        { name: "shift.max_hours_flag", label: "Flag shifts longer than (hours)", type: "number" }, { name: "notifications.throttle_seconds", label: "Group duplicate notifications within (seconds)", type: "number" }], s);
      mount(body, h("div", { class: "grid g2" },
        card("Searchable fields", h("div", { class: "stack" }, h("h4", "Person search"), h("div", { class: "row wrap" }, personBoxes), h("h4", "Vehicle search"), h("div", { class: "row wrap" }, vehBoxes),
          btn("Save", async () => { const pick = (bs) => bs.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value); await setSetting("records.searchable_fields", { person: pick(personBoxes), vehicle: pick(vehBoxes) }); toast("Saved", "ok"); }, { kind: "primary", sm: true }))),
        card("Records, shifts & notifications", h("div", { class: "stack" }, misc.el, btn("Save", async () => { for (const [k, v] of Object.entries(misc.values())) await setSetting(k, v); toast("Saved", "ok"); }, { kind: "primary", sm: true }))),
        card("Report templates (JSON)", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Each template: key, label and fields [{key, label, type: text|textarea|select, options}]. Custom fields appear on the report form."), tplArea,
          btn("Save templates", async () => { let v; try { v = JSON.parse(tplArea.value); } catch { return toast("Invalid JSON", "bad"); } await setSetting("reports.templates", v); await refreshBoot(); toast("Templates saved", "ok"); }, { kind: "primary", sm: true })), { cls: "span2" })));
    } else {
      const widgets = ["server", "cad", "units", "queue", "activity", "players_chart", "bolos", "shifts"];
      const cur = s["dashboard.widgets"];
      const boxes = widgets.map((w) => h("label", { class: "check" }, h("input", { type: "checkbox", value: w, checked: cur.includes(w) }), w.replace("_", " ")));
      const sc = form(Object.keys(s["dispatch.shortcuts"]).map((k) => ({ name: k, label: k.replace(/_/g, " ") })), s["dispatch.shortcuts"]);
      mount(body, h("div", { class: "grid g2" },
        card("Default dashboard widgets", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Users can still personalise their own dashboard."), h("div", { class: "grid g2" }, boxes),
          btn("Save", async () => { await setSetting("dashboard.widgets", boxes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value)); toast("Saved", "ok"); }, { kind: "primary", sm: true }))),
        card("Default keyboard shortcuts", h("div", { class: "stack" }, sc.el, btn("Save", async () => { await setSetting("dispatch.shortcuts", sc.values()); await refreshBoot(); toast("Saved", "ok"); }, { kind: "primary", sm: true })))));
    }
  };
  mount(root, pageHead("Appearance & Customization", "Branding plus every configurable list in ERLC Nexus. Sensible defaults are pre-filled."),
    tabs([["branding", "Branding"], ["cad", "CAD & map"], ["records", "Records & reports"], ["dashboard", "Dashboard & shortcuts"]], show), body);
  show("branding");
}

// ---------------------------------------------------------------- Database
export async function database(root) {
  const load = async () => {
    const r = await api("admin/backups");
    mount(root, pageHead("Database", "Backups, restore and schema version.", [r.supported ? btn("Create backup", async () => { const b = await api("admin/backups", { method: "POST", body: { label: "manual" } }); toast(`Backup ${b.name} created and verified`, "ok"); load(); }, { kind: "primary", sm: true, ico: "database" }) : null]),
      h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("Engine", r.supported ? "SQLite" : "PostgreSQL"), stat("Schema revision", r.schema_revision || "—"), stat("Backups", r.backups.length),
        stat("Restore pending", r.restore_pending ? "Yes" : "No", { tone: r.restore_pending ? "warn" : "", sub: r.restore_pending ? "Applied on next start" : null })),
      r.restore_pending ? h("div", { class: "notice warn", style: { marginBottom: "14px" } }, "A restore is staged. Run stop.bat and then start.bat to apply it. The current database will be saved as a safety backup first.") : null,
      !r.supported ? h("div", { class: "notice" }, "You are using PostgreSQL. Use pg_dump / pg_restore — see docs/BACKUP.md.") : card("Backups", table([
        { label: "File", render: (b) => h("code", b.name) }, { label: "Size", render: (b) => `${(b.size / 1024).toFixed(0)} KB`, num: true }, { label: "Created", render: (b) => fmtTime(b.created_at) },
        { label: "", render: (b) => h("div", { class: "row" }, h("a", { class: "btn sm", href: `/api/admin/backups/${encodeURIComponent(b.name)}/download`, download: "" }, icon("download"), "Download"),
          btn("Restore", async () => { if (await confirmDialog("Stage restore", `Restore ${b.name}? It will be applied the next time ERLC Nexus starts. Your current database is backed up first.`, "Stage restore")) { const x = await api(`admin/backups/${encodeURIComponent(b.name)}/restore`, { method: "POST" }); toast(x.message, "ok"); load(); } }, { sm: true, kind: "danger" })) }],
      r.backups, { emptyText: "No backups yet." }), { flush: true }),
      h("div", { class: "small muted", style: { marginTop: "10px" } }, "Backups use SQLite's online backup API, so they're safe while everything is running. Records are never hard-deleted through the interface — they are archived."));
  };
  await load();
}

// ---------------------------------------------------------------- Health
export async function health(root) {
  const load = async () => {
    const hh = await api("admin/health");
    const ok = (v) => h("span", { class: "row" }, h("span", { class: "dot " + (v ? "ok" : "bad") }), v ? "OK" : "Problem");
    mount(root, pageHead("System Health", `ERLC Nexus ${hh.version} · Python ${hh.python}`, [btn("Refresh", load, { sm: true, ico: "refresh" })]),
      h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("Database", ok(hh.database.ok), { sub: `${hh.database.engine} · rev ${hh.database.revision}` }),
        stat("ERLC API", hh.erlc_api.configured ? ok(!hh.erlc_api.key_invalid && hh.erlc_api.last_sync_ok !== false) : "Not configured", { sub: hh.erlc_api.last_sync_at ? `last sync ${ago(hh.erlc_api.last_sync_at)}` : "" }),
        stat("Discord bot", ok(hh.discord_bot.online), { sub: hh.discord_bot.heartbeat_at ? `heartbeat ${ago(hh.discord_bot.heartbeat_at)}` : "no heartbeat" }),
        stat("Live connections", hh.websocket_clients, { sub: `uptime ${Math.floor(hh.uptime_seconds / 3600)}h ${Math.floor((hh.uptime_seconds % 3600) / 60)}m` })),
      card("Configuration checks", hh.config_problems.length ? h("div", { class: "stack" }, hh.config_problems.map((p) => h("div", { class: "notice warn" }, p))) : h("div", { class: "notice ok" }, "No configuration problems detected.")),
      h("div", { style: { height: "14px" } }),
      card("Details", kv([["Platform", hh.platform], ["Sync leader in this process", hh.erlc_api.is_leader ? "Yes" : "No (another process polls the API)"], ["Bot latency", hh.discord_bot.latency_ms != null ? `${hh.discord_bot.latency_ms} ms` : "—"], ["Bot servers", hh.discord_bot.guilds ?? "—"]])),
      h("div", { class: "notice", style: { marginTop: "14px" } }, "ERLC Nexus runs on your own computer. When the host computer is off or asleep, the website and bot are offline."));
  };
  await load();
}

// ---------------------------------------------------------------- Security
export async function security(root) {
  const load = async () => {
    const s = await api("admin/security");
    const ev = (rows) => table([{ label: "When", render: (e) => fmtTime(e.created_at) }, { label: "Event", key: "kind" }, { label: "User", render: (e) => e.user || e.discord_id || "—" }, { label: "IP", key: "ip" }, { label: "Detail", key: "detail" }], rows, { emptyText: "None." });
    mount(root, pageHead("Security", "Logins, sessions, failed attempts and permission changes.", [btn("Refresh", load, { sm: true, ico: "refresh" })]),
      h("div", { class: "grid g4", style: { marginBottom: "14px" } }, stat("Active sessions", s.active_sessions.length), stat("Failed attempts (24h)", s.failed_24h, { tone: s.failed_24h ? "warn" : "" }),
        stat("Recent logins", s.recent_logins.length), stat("Permission changes", s.permission_changes.length)),
      h("div", { class: "grid g2" },
        card("Active sessions", table([{ label: "User", key: "user" }, { label: "IP", key: "ip" }, { label: "Last seen", render: (w) => ago(w.last_seen_at) }, { label: "Expires", render: (w) => fmtTime(w.expires_at) },
          { label: "", render: (w) => btn("Revoke", async () => { if (await confirmDialog("Revoke session", `Sign ${w.user} out of this session?`, "Revoke")) { await api(`admin/sessions/${w.id}/revoke`, { method: "POST" }); load(); } }, { sm: true, kind: "danger" }) }], s.active_sessions), { flush: true, cls: "span2" }),
        card("Recent logins", ev(s.recent_logins), { flush: true }), card("Failed authentication attempts", ev(s.failed_attempts), { flush: true }),
        card("Permission changes", table([{ label: "When", render: (a) => fmtTime(a.created_at) }, { label: "By", key: "user" }, { label: "Event", key: "action" }, { label: "Target", key: "reference" }], s.permission_changes, { emptyText: "None." }), { flush: true }),
        card("Security events", ev(s.security_events), { flush: true })));
  };
  await load();
}

