// registry.js: every command the hotkeys screen lists (SPEC 6.3). An entry:
//   { action (the exact keys.json string), title, group, home (the keys.json section it belongs to),
//     defaults (its chords in `home`), obsidian? (the Obsidian command with the same key), when? }
// Built from fixed tables plus the app's live commands() and keys() (rows for anything bound in
// keys.json that the tables don't name, so nothing in the file is ever hidden).

import { commands, keys, window as appWindow } from "herdr";
import { DEFAULT_SCOPE, scopeInfo } from "./keysfile.js";
import { chordForPlatform } from "./platform_keys.js";

export const LAYOUT_SCOPE = DEFAULT_SCOPE;
export const SESSIONS_SCOPE = "mod:ob-sessions";

// The Obsidian layout's own commands (SPEC 6.1 order), with the Obsidian command each key mirrors
// (the person's .obsidian/hotkeys.json overrides marked "yours").
const OB = [
  ["mod.open:ob-switcher", "Open quick switcher", ["ctrl-p"], "Quick switcher: Open quick switcher (yours: Ctrl+P)"],
  ["ob-tabs.switcher:commands", "Open command palette", ["ctrl-shift-p"], "Command palette: Open command palette (yours: Ctrl+Shift+P)"],
  ["layout.toggle:ob-left", "Toggle left sidebar", ["ctrl-b"], "Toggle left sidebar (yours: Ctrl+B)"],
  ["layout.toggle:ob-right", "Toggle right sidebar", ["ctrl-shift-b"], "Toggle right sidebar (yours: Ctrl+Shift+B)"],
  ["pane.split:right", "Split right", ["ctrl-\\"], "Split vertically (yours: Ctrl+\\)"],
  ["pane.split:down", "Split down", ["ctrl-shift-\\", "ctrl-|"], null],
  ["ob-tabs.open:ob-sessions@reveal", "Reveal active session", ["ctrl-shift-e"], "Files: Reveal current file in navigation (yours: Ctrl+Shift+E)"],
  ["ob-tabs.switcher:move", "Move tab to another space", ["ctrl-shift-m"], "Files: Move current file to another folder (yours: Ctrl+Shift+M)"],
  ["ob-tabs.copy-path", "Copy path", ["ctrl-shift-c", "ctrl-alt-c"], "Copy file path (yours: Ctrl+Shift+C)"],
  ["ob-tabs.daily", "Open today's daily note", ["ctrl-shift-d"], "Daily notes: Open today's daily note (yours: Ctrl+Shift+D)"],
  ["ob-tabs.open:ob-search", "Search all sessions", ["ctrl-shift-k", "ctrl-alt-f"], "Search: Search in all files (Ctrl+Shift+K)"],
  ["ob-tabs.open:ob-graph", "Open graph view", ["ctrl-shift-g"], "Graph view: Open graph view (Ctrl+G there; Ctrl+G stays with programs here)"],
  ["ob-tabs.toggle:ob-outline", "Toggle Outline", ["ctrl-shift-a"], null],
  ["ob-tabs.open:ob-outline", "Open outline", ["ctrl-alt-o"], "Outline: Show outline"],
  ["ob-tabs.open:ob-props", "Show properties", ["ctrl-alt-i"], "Properties: Show file properties"],
  ["ob-tabs.open:ob-agents", "Show agents", ["ctrl-alt-a"], null],
  ["ob-tabs.bookmark", "Bookmark current tab", ["ctrl-alt-b"], "Bookmarks: Bookmark..."],
  ["ob-tabs.back", "Navigate back", ["ctrl-alt-left"], "Navigate back (Ctrl+Alt+←)"],
  ["ob-tabs.forward", "Navigate forward", ["ctrl-alt-right"], "Navigate forward (Ctrl+Alt+→)"],
  ["ob-tabs.last", "Go to last tab", ["ctrl-9"], "Go to last tab (Ctrl+9)"],
  ["ob-tabs.settings:hotkeys", "Open hotkeys", ["ctrl-alt-k"], "Settings: Hotkeys"],
  ["ob-tabs.tab-list", "Show tab list", ["ctrl-alt-t"], null],
  ["ob-tabs.zen", "Toggle Zen mode", ["ctrl-shift-z", "ctrl-alt-z"], "Zen mode: Toggle"],
  ["ob-tabs.open:ob-bookmarks", "Show bookmarks", [], "Bookmarks: Show bookmarks"],
  ["ob-tabs.open:ob-recent", "Show recent", [], null],
  ["ob-tabs.open:ob-files", "Show files", [], "Files: Show file explorer"],
  ["ob-tabs.open:ob-changes", "Show changes", [], null],
  ["ob-tabs.open:ob-insights", "Show insights", [], null],
  ["ob-tabs.open:ob-notes", "Show notes", [], null],
  ["ob-tabs.copy-address", "Copy terminal address", [], null],
  ["ob-tabs.new", "New tab menu", [], null],
  ["ob-tabs.switcher:views", "Switch views", [], null],
  ["ob-sessions.collapse-all", "Collapse all sessions", [], "Files: Collapse all", "Sessions"],
  ["ob-sessions.expand-all", "Expand all sessions", [], "Files: Expand all", "Sessions"],
  ["ob-feed.refresh", "Rescan sub-agents", [], null],
  ["ob-graph.fit", "Fit graph", [], null, "Graph"],
];

const SESSIONS = [
  ["ob-sessions.rename", "Rename selected", ["f2"], "Files: Rename file (F2)"],
  ["ob-sessions.close", "Close selected", ["delete"], "Files: Delete file"],
  ["ob-sessions.open-right", "Open selected to the right", ["ctrl-enter"], "Open link in new tab (Ctrl+Enter)"],
];

// The shipped palette's names (frame/palette/main.js NAMED), as keys.json actions.
const NAMED = [
  ["tab.new", {}, "New tab"],
  ["mod.open", { name: "picker" }, "Go to space or tab…"],
  ["tab.rename", {}, "Rename tab"],
  ["tab.close", {}, "Close tab"],
  ["tab.next", {}, "Next tab"],
  ["tab.prev", {}, "Previous tab"],
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
  ["layout.switch", {}, "Next layout"],
  ["layout.reset", {}, "Reset layout"],
  ["layout.clone", {}, "Duplicate layout"],
  ["mod.clone", {}, "Duplicate mod"],
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
// The palette's list of commands that act on something you point at (not for a list).
const HIDDEN = new Set([
  "space.move", "tab.move", "space.select", "tab.select", "pane.focus", "terminal.keep",
  "terminal.park", "terminal.kill", "terminal.show", "agent.focus", "layout.set", "layout.toggle",
  "layout.show", "layout.hide", "layout.resize", "layout.select", "mod.open", "overlay.close",
  "tab.settle", "tab.unsettle",
  "app.palette", "app.hide", "app.hide_others", "app.show_all", "app.theme", "app.settings",
]);

const TERMINAL = [
  ["terminal.copy", "Copy"],
  ["terminal.paste", "Paste"],
  ["terminal.search", "Find in terminal"],
  ["terminal.paste_image", "Paste image"],
];

// Known send: texts, by what they do in a shell.
const SENDS = { "\u0017": "Delete word back", "\u001bb": "Word left", "\u001bf": "Word right", "\u0001": "Start of line", "\u0005": "End of line", "\u0015": "Delete to start of line", "\u000b": "Delete to end of line" };

// A name:value action -> keys.json string (first arg value), as the palette's keyOf does.
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

// The registry: [{ action, title, group, home, defaults, obsidian, when }], groups in order.
export const GROUPS = ["Vaultr layout", "Sessions panel", "Herdr", "In terminals", "Other"];

export function registry() {
  const out = [];
  // The tables are written with Ctrl; on macOS install.sh binds Cmd instead (platform_keys.js), so defaults follow.
  let platform = "linux";
  try { platform = appWindow()?.platform ?? "linux"; } catch { platform = "linux"; }
  const plat = (chords) => chords.map((c) => chordForPlatform(c, platform));
  const seen = new Set();
  const add = (e) => { if (seen.has(e.action)) return; seen.add(e.action); out.push(e); };
  for (const [action, title, defaults, obsidian, when] of OB) add({ action, title, group: "Vaultr layout", home: LAYOUT_SCOPE, defaults: plat(defaults), obsidian, when: when ?? null });
  for (const [action, title, defaults, obsidian] of SESSIONS) add({ action, title, group: "Sessions panel", home: SESSIONS_SCOPE, defaults: plat(defaults), obsidian, when: "Sessions" });
  const bound = safeKeys();
  // Terminal rows are reserved first so "Copy"/"Paste" land under In terminals, not Herdr.
  const termRows = [...TERMINAL.map(([action, title]) => ({ action, title }))];
  for (const k of bound) if (k.action === "terminal" || String(k.action).startsWith("send:")) termRows.push({ action: k.action, title: titleFor(k.action) });
  const termSet = new Set(termRows.map((r) => r.action));
  let cmds = [];
  try { cmds = commands() ?? []; } catch { cmds = []; }
  const known = new Set(cmds.map((c) => c.name));
  for (const [name, args, title] of NAMED) {
    const action = asAction(name, args);
    if (termSet.has(action) || (known.size && !known.has(name))) continue;
    add({ action, title, group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  for (const c of cmds) {
    if (HIDDEN.has(c.name) || termSet.has(c.name) || (c.args ?? []).some((a) => a.required)) continue;
    add({ action: c.name, title: titleFor(c.name), group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  // name:value forms the person's global keys use (space.select:1, layout.toggle:sidebar, ...).
  for (const k of bound) {
    if (k.section !== "global" || termSet.has(k.action)) continue;
    add({ action: k.action, title: titleFor(k.action), group: "Herdr", home: "global", defaults: null, obsidian: null, when: null });
  }
  for (const r of termRows) add({ ...r, group: "In terminals", home: "terminal", defaults: null, obsidian: null, when: null });
  // Anything else bound anywhere (mod:obsidian's keys, other layouts): shown so nothing hides.
  for (const k of bound) add({ action: k.action, title: titleFor(k.action), group: "Other", home: k.section, defaults: null, obsidian: null, when: null });
  return out;
}

function safeKeys() {
  try { return (keys() ?? []).filter((k) => k && typeof k.action === "string"); } catch { return []; }
}

// The chords a row should have in `scope` by default, or undefined when unknown there.
// Rows of this layout know theirs; any other row's default in the layout scope is "none extra".
export function defaultsIn(row, scope) {
  if (row.defaults && row.home === scope) return row.defaults;
  if (scope === LAYOUT_SCOPE || scope === SESSIONS_SCOPE) return [];
  return undefined;
}

// Sections that also apply while `scope`'s keys apply, most specific first (U1: mod:* placement is
// undocumented; we assume a panel's keys sit above the layout's).
export function chainOf(scope) {
  if (scope === "global") return [];
  if (scope === "terminal") return [LAYOUT_SCOPE, "global"];
  if (scope.startsWith("mod:ob-")) return [LAYOUT_SCOPE, "global"];
  return ["global"];
}

// Scope names for the menu and chips, and the sentence forms: see scopeInfo in keysfile.js.
export function scopeTitle(scope) {
  return scopeInfo(scope).title;
}
// "in the Vaultr layout", "in terminals": for sentences.
export function scopeWhere(scope) {
  return scopeInfo(scope).where;
}
export function scopeShort(scope) {
  if (scope === LAYOUT_SCOPE) return "layout";
  if (scope === "global") return "global";
  if (scope === "terminal") return "terminal";
  return scope.replace(/^(mod|layout):/, "");
}
