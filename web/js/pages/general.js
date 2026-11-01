import { api, ago, btn, card, empty, form, h, L, live, mount, pageHead, state, toast } from "../core.js";
import { activityItem } from "./overview.js";
import { applyTheme } from "../app.js";

export async function notifications(root) {
  const listEl = h("div");
  let unreadOnly = false;
  const load = async () => {
    const r = await api("notifications", { query: { unread: unreadOnly } });
    mount(listEl, r.items.length ? h("div", { class: "list" }, r.items.map((n) => h("div", { class: "list-item" + (n.link ? " clickable" : ""), style: { opacity: n.read ? .65 : 1 },
      onclick: () => { api("notifications/read", { method: "POST", body: { ids: [n.id] }, silent: true }); if (n.link) location.hash = n.link.replace(/^\/?#/, "#"); } },
      h("span", { class: "dot " + ({ danger: "bad", warning: "warn", success: "ok" }[n.severity] || "") }),
      h("div", { class: "grow" }, h("div", { class: "title" }, n.title, n.count > 1 ? h("span", { class: "muted" }, ` ×${n.count}`) : null),
        n.body ? h("div", { class: "meta" }, n.body) : null),
      h("span", { class: "badge" }, (state.boot.notification_kinds[n.kind] || n.kind)), h("span", { class: "meta" }, ago(n.created_at))))) : empty("No notifications.", "bell"));
  };
  mount(root, pageHead("Notifications", "Alerts for your role and departments. Change which types you receive in your profile.", [
    btn("Unread only", (e) => { unreadOnly = !unreadOnly; e.currentTarget.classList.toggle("primary", unreadOnly); load(); }, { sm: true }),
    btn("Mark all read", async () => { await api("notifications/read", { method: "POST", body: {} }); state.unread = 0; load(); }, { sm: true, ico: "check" }),
  ]), card(null, listEl, { flush: true }));
  await load();
  return live(["notification"], load);
}

export async function activity(root) {
  const listEl = h("div");
  let items = [];
  const load = async (more = false) => {
    const before = more && items.length ? items[items.length - 1].id : undefined;
    const r = await api("activity", { query: { limit: 50, before_id: before } });
    items = more ? items.concat(r) : r;
    mount(listEl, items.length ? h("div", { class: "list" }, items.map(activityItem)) : empty("No activity recorded yet."),
      r.length === 50 ? h("div", { class: "pager" }, btn("Load more", () => load(true), { sm: true }), h("span", `${items.length} shown`)) : null);
  };
  mount(root, pageHead("Activity", "A live feed of CAD, records, department and server actions across ERLC Nexus."), card(null, listEl, { flush: true }));
  await load();
  return live(["incident.", "unit.", "bolo.", "shift.", "record.", "report.", "traffic.", "erlc.moderation", "erlc.command"], () => load(false), 1000);
}

export async function profile(root) {
  const me = await api("me");
  const p = me.preferences || {};
  const kinds = state.boot.notification_kinds;
  const muted = new Set(p.muted_notifications || []);
  const account = form([
    { name: "display_name", label: "Display name", required: true, max: 100 },
    { name: "roblox_username", label: "Roblox username", hint: "Used to match you with live ERLC data." },
    { name: "roblox_id", label: "Roblox user ID", hint: "Numeric ID. Enables automatic unit map positions from the official API while you are in-game." },
  ], me);
  const prefs = form([
    { name: "theme", label: "Theme", type: "select", options: [["dark", "Dark"], ["light", "Light"], ["system", "Match system"]] },
    { name: "default_page", label: "Default page after login", type: "select", options: [["#/", "Overview"], ["#/cad/dispatch", "Dispatch Center"], ["#/mdt", "MDT"], ["#/cad/map", "Live Map"]] },
    { name: "refresh_seconds", label: "Dashboard refresh (seconds)", type: "number", min: 5, maxv: 300 },
    { name: "default_department_id", label: "Default department", type: "select", options: [["", "— None —"], ...L.departments().filter((d) => me.department_ids.includes(d.id)).map((d) => [d.id, d.abbreviation])], nullable: true, numeric: true },
    { name: "sound_alerts", label: "Play a sound for emergency alerts", type: "checkbox" },
    { name: "shortcuts_enabled", label: "Enable keyboard shortcuts", type: "checkbox" },
  ], { theme: "dark", default_page: "#/", refresh_seconds: 15, shortcuts_enabled: true, ...p });
  const shortcutDefaults = L.settings("dispatch.shortcuts") || {};
  const shortcutInputs = Object.entries(shortcutDefaults).map(([action, keys]) => {
    const i = h("input", { value: (p.shortcuts || {})[action] ?? keys, placeholder: "disabled", dataset: { action } });
    return h("label", { class: "field" }, action.replace(/_/g, " "), i);
  });
  const mutedBoxes = Object.entries(kinds).map(([k, label]) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: !muted.has(k), dataset: { kind: k } }), label));
  mount(root, pageHead("Your profile", `Signed in with Discord as ${me.username || me.name}`),
    h("div", { class: "grid g2" },
      card("Account", h("div", { class: "stack" }, account.el, h("div", btn("Save account", async () => {
        await api("me", { method: "PATCH", body: account.values() }); toast("Account saved", "ok");
      }, { kind: "primary", sm: true })))),
      card("Roles & permissions", h("div", { class: "stack" },
        h("div", { class: "row wrap" }, me.roles.length ? me.roles.map((r) => { const b = h("span", { class: "badge" }, r.name); b.style.color = r.color; return b; }) : h("span", { class: "muted" }, "No roles yet — ask an administrator.")),
        h("div", { class: "small muted" }, `${me.effective_permissions.length} permission(s) granted. Roles can also come from your Discord server roles.`))),
      card("Preferences", h("div", { class: "stack" }, prefs.el, h("div", btn("Save preferences", async () => {
        const v = prefs.values();
        const saved = await api("me/preferences", { method: "PUT", body: v });
        state.me.preferences = saved; applyTheme(); toast("Preferences saved", "ok");
      }, { kind: "primary", sm: true })))),
      card("Keyboard shortcuts", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Format like Alt+N or Ctrl+Shift+K. Leave empty to disable a shortcut."),
        h("div", { class: "form-grid" }, shortcutInputs), h("div", btn("Save shortcuts", async () => {
          const sc = Object.fromEntries(shortcutInputs.map((l) => { const i = l.querySelector("input"); return [i.dataset.action, i.value.trim()]; }));
          state.me.preferences = await api("me/preferences", { method: "PUT", body: { shortcuts: sc } }); toast("Shortcuts saved", "ok");
        }, { kind: "primary", sm: true })))),
      card("Notification types", h("div", { class: "stack" }, h("div", { class: "small muted" }, "Unchecked types are hidden from your notifications."),
        h("div", { class: "grid g2" }, mutedBoxes), h("div", btn("Save notification settings", async () => {
          const m = mutedBoxes.map((l) => l.querySelector("input")).filter((i) => !i.checked).map((i) => i.dataset.kind);
          state.me.preferences = await api("me/preferences", { method: "PUT", body: { muted_notifications: m } }); toast("Notification settings saved", "ok");
        }, { kind: "primary", sm: true }))), { cls: "span2" })));
}
