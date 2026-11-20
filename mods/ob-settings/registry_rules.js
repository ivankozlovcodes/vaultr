// Portions derived from the Herdr app (Apache-2.0) and modified for Vaultr; see NOTICE and LICENSE-herdr.
// registry_rules.js: pure table and row-building helpers for Hotkeys (no herdr imports so
// test/test_ob_settings.py runs them under node).

import { DEFAULT_SCOPE, scopeInfo } from "./keysfile.js";
import { chordForPlatform } from "./platform_keys.js";

export const LAYOUT_SCOPE = DEFAULT_SCOPE;
export const SESSIONS_SCOPE = "mod:ob-sessions";

// The shipped palette's names (frame/palette/main.js NAMED), as runnable keys.json actions.
export const NAMED = [
  ["tab.new", {}, "New tab"],
  ["mod.open", { name: "picker" }, "Go to space or tab…"],
  ["tab.rename", {}, "Rename tab"],
  ["tab.close", {}, "Close tab"],
  ["tab.next", {}, "Next tab"],
  ["tab.prev", {}, "Previous tab"],
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ["tab.select", { index: n }, `Go to tab ${n}`]),
  ["pane.split", { direction: "right" }, "Split right"],
  ["pane.split", { direction: "down" }, "Split down"],
  ["pane.close", {}, "Close pane"],
  ["pane.zoom", {}, "Zoom pane"],
  ...["left", "right", "up", "down"].map((d) => ["pane.go", { direction: d }, `Focus pane ${d}`]),
  ...["left", "right", "up", "down"].map((d) => ["pane.swap", { direction: d }, `Swap pane ${d}`]),
  ["space.new", {}, "New space"],
  ["space.rename", {}, "Rename space"],
  ["space.close", {}, "Close space"],
  ["space.next", {}, "Next space"],
  ["space.prev", {}, "Previous space"],
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ["space.select", { index: n }, `Go to space ${n}`]),
  ["layout.switch", {}, "Next layout"],
  ["layout.reset", {}, "Reset layout"],
  ["layout.clone", { name: "vaultr" }, "Duplicate Vaultr layout"],
  ["terminal.open", {}, "New terminal"],
  ["terminal.copy", {}, "Copy"],
  ["terminal.paste", {}, "Paste"],
  ["agent.next", {}, "Next agent"],
  ["agent.prev", {}, "Previous agent"],
  ["window.minimize", {}, "Minimize window"],
  ["window.maximize", {}, "Maximize window"],
  ["window.close", {}, "Close window"],
  ["app.settings", {}, "Settings"],
  ["app.help", {}, "Keys"],
  ["app.welcome", {}, "Welcome"],
  ["app.whats_new", {}, "What's new"],
  ["app.reset", {}, "Reset to the default screen"],
  ["app.zoom_in", {}, "Zoom in"],
  ["app.zoom_out", {}, "Zoom out"],
  ["app.zoom_reset", {}, "Reset zoom"],
  ["app.quit", {}, "Quit Herdr"],
  ...["graphite", "ink", "moss", "atom-one-dark"].map((n) => ["app.theme", { name: n }, `Theme: ${n.replace(/-/g, " ")}`]),
];

// Commands that act on something you point at (not runnable without an argument).
export const HIDDEN = new Set([
  "space.move", "tab.move", "space.select", "tab.select", "pane.focus", "terminal.keep",
  "terminal.park", "terminal.kill", "terminal.show", "agent.focus", "layout.set", "layout.toggle",
  "layout.show", "layout.hide", "layout.resize", "layout.select", "mod.open", "overlay.close",
  "tab.settle", "tab.unsettle", "layout.clone", "mod.clone",
  "app.palette", "app.hide", "app.hide_others", "app.show_all", "app.theme", "app.settings",
]);

export const TERMINAL = [
  ["terminal.copy", "Copy"],
  ["terminal.paste", "Paste"],
  ["terminal.search", "Find in terminal"],
  ["terminal.paste_image", "Paste image"],
];

// Known send: texts, by what they do in a shell.
export const SENDS = {
  "\u0017": "Delete word back",
  "\u001bb": "Word left",
  "\u001bf": "Word right",
  "\u0001": "Start of line",
  "\u0005": "End of line",
  "\u0015": "Delete to start of line",
  "\u000b": "Delete to end of line",
};

const asAction = (name, args) => {
  const v = Object.values(args)[0];
  return v === undefined ? name : `${name}:${v}`;
};

// "\u0017" -> "^W"; "\u001bb" -> "Esc b"; printable kept.
export function visibleText(s) {
  return [...String(s)].map((ch) => {
    const c = ch.codePointAt(0);
    if (c === 27) return "Esc ";
    if (c < 32) return `^${String.fromCharCode(c + 64)}`;
    if (c === 127) return "^?";
    return ch;
  }).join("").trim();
}

// A title for any action string (rows for actions the tables don't name).
export function titleFor(action) {
  const a = String(action);
  if (a === "terminal") return "Send the key to the program";
  if (a.startsWith("send:")) {
    const text = a.slice(5);
    return SENDS[text] ? `${SENDS[text]} (types ${visibleText(text)})` : `Type ${visibleText(text)}`;
  }
  if (a.startsWith("{")) {
    try { const o = JSON.parse(a); return `${titleFor(o.command ?? "?")} · ${JSON.stringify(o.args ?? {})}`; } catch { return a; }
  }
  const i = a.indexOf(":");
  const name = i < 0 ? a : a.slice(0, i);
  const arg = i < 0 ? "" : a.slice(i + 1);
  if (name === "tab.select" && /^\d+$/.test(arg)) return `Go to tab ${arg}`;
  if (name === "space.select" && /^\d+$/.test(arg)) return `Go to space ${arg}`;
  if (name === "layout.switch" && arg) return `Layout: ${arg}`;
  if (name === "layout.clone" && arg) return `Duplicate ${arg} layout`;
  if (name === "layout.toggle" && arg) return `Toggle ${arg}`;
  if (name === "layout.show" && arg) return `Show ${arg}`;
  if (name === "layout.hide" && arg) return `Hide ${arg}`;
  if (name === "mod.open" && arg) return `Open ${arg}`;
  const dot = name.indexOf(".");
  if (dot > 0) {
    const noun = name.slice(0, dot);
    const verb = name.slice(dot + 1).replace(/[_-]/g, " ");
    const t = `${verb.charAt(0).toUpperCase()}${verb.slice(1)} ${noun}`;
    return arg ? `${t}: ${arg}` : t;
  }
  return arg ? `${name}: ${arg}` : name;
}

// Return the first missing required argument name when `action` names a known Herdr command without supplying all required args.
export function missingRequiredArg(action, cmds = []) {
  const a = String(action ?? "");
  if (!a || a === "terminal" || a.startsWith("send:")) return null;
  const byName = cmds instanceof Map ? cmds : new Map((cmds ?? []).filter((c) => c && c.name).map((c) => [c.name, c]));
  if (a.startsWith("{")) {
    let obj;
    try { obj = JSON.parse(a); } catch { return null; }
    const cmd = obj && typeof obj.command === "string" ? byName.get(obj.command) : null;
    if (!cmd) return null;
    const args = obj.args && typeof obj.args === "object" && !Array.isArray(obj.args) ? obj.args : {};
    for (const arg of cmd.args ?? []) {
      if (!arg?.required) continue;
      const v = args[arg.name];
      if (v === undefined || v === null || (typeof v === "string" && !v.trim())) return arg.name;
    }
    return null;
  }
  const colon = a.indexOf(":");
  const name = colon < 0 ? a : a.slice(0, colon);
  const val = colon < 0 ? "" : a.slice(colon + 1);
  const cmd = byName.get(name);
  if (!cmd) return null;
  const required = (cmd.args ?? []).filter((x) => x?.required).map((x) => x.name);
  if (!required.length) return null;
  if (colon < 0 || !val.trim()) return required[0];
  // Shorthand name:val fills at most one argument (numeric `index`, else the first declared arg).
  const filled = /^\d+$/.test(val) && (cmd.args ?? []).some((x) => x?.name === "index") ? "index" : cmd.args?.[0]?.name;
  return required.find((r) => r !== filled) ?? null;
}

// The registry: [{ action, title, group, home, defaults, obsidian, when, missingArg }], groups in order.
export const GROUPS = ["Vaultr layout", "Sessions panel", "Herdr", "In terminals", "Other"];

export function buildRegistry({ ob = [], sessions = [], named = NAMED, hidden = HIDDEN, terminal = TERMINAL, commands = [], keys = [], platform = "linux" } = {}) {
  const out = [];
  const cmds = (commands ?? []).filter((c) => c && typeof c.name === "string");
  const cmdMap = new Map(cmds.map((c) => [c.name, c]));
  const bound = (keys ?? []).filter((k) => k && typeof k.action === "string");
  const plat = (chords) => chords.map((c) => chordForPlatform(c, platform));
  const seen = new Set();
  const add = (e) => {
    if (seen.has(e.action)) return;
    seen.add(e.action);
    out.push({ ...e, missingArg: missingRequiredArg(e.action, cmdMap) });
  };
  for (const [action, title, defaults, obsidian, when] of ob) add({ action, title, group: "Vaultr layout", home: LAYOUT_SCOPE, defaults: plat(defaults), obsidian, when: when ?? null });
  for (const [action, title, defaults, obsidian] of sessions) add({ action, title, group: "Sessions panel", home: SESSIONS_SCOPE, defaults: plat(defaults), obsidian, when: "Sessions" });
  const termRows = [...terminal.map(([action, title]) => ({ action, title }))];
  for (const k of bound) if (k.action === "terminal" || String(k.action).startsWith("send:")) termRows.push({ action: k.action, title: titleFor(k.action) });
  const termSet = new Set(termRows.map((r) => r.action));
  for (const [name, args, title] of named) {
    const action = asAction(name, args);
    if (termSet.has(action) || (cmdMap.size && !cmdMap.has(name))) continue;
    add({ action, title, group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  for (const c of cmds) {
    if (hidden.has(c.name) || termSet.has(c.name) || (c.args ?? []).some((a) => a.required)) continue;
    add({ action: c.name, title: titleFor(c.name), group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  // Global bindings (including existing broken bare-arg keys so the user can see and remove them).
  for (const k of bound) {
    if (k.section !== "global" || termSet.has(k.action)) continue;
    add({ action: k.action, title: titleFor(k.action), group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  for (const r of termRows) add({ ...r, group: "In terminals", home: "terminal", defaults: null, obsidian: null, when: null });
  // Anything else bound anywhere (panel scopes, other layouts): shown so nothing hides.
  for (const k of bound) add({ action: k.action, title: titleFor(k.action), group: "Other", home: k.section, defaults: null, obsidian: null, when: null });
  return out;
}

export function defaultsIn(row, scope) {
  if (row.defaults && row.home === scope) return row.defaults;
  if (scope === LAYOUT_SCOPE || scope === SESSIONS_SCOPE) return [];
  return undefined;
}

export function chainOf(scope) {
  if (scope === "global") return [];
  if (scope === "terminal") return [LAYOUT_SCOPE, "global"];
  if (scope.startsWith("mod:ob-")) return [LAYOUT_SCOPE, "global"];
  return ["global"];
}

export function scopeTitle(scope) {
  return scopeInfo(scope).title;
}
export function scopeWhere(scope) {
  return scopeInfo(scope).where;
}
export function scopeShort(scope) {
  if (scope === LAYOUT_SCOPE) return "layout";
  if (scope === "global") return "global";
  if (scope === "terminal") return "terminal";
  return scope.replace(/^(mod|layout):/, "");
}
