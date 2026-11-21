// Portions derived from the Herdr app (Apache-2.0) and modified for Vaultr; see NOTICE and LICENSE-herdr.
// Command mode of the quick switcher (a query starting with ">"): Vaultr's own commands and Herdr's app commands
// as one list, fuzzy-matched together. Pure functions, no Herdr or gpui imports, so test/test_ob_switcher.py runs
// them under node. The switcher passes its fuzzy matcher in as `match(query, text) -> { score, hits } | null`.
//
// Sources, both live: Vaultr's rows come from the switcher's own model; Herdr's from commands() (every app command
// and its arguments) and keys() (the key bindings, for the hints).

import { allowsRow, sinkDisabled } from "./modes.js";

export const PALETTE_ROUTE = "app.palette";
export const PALETTE_LABEL = "Herdr command palette…";

// Vaultr's own runnable commands in Command Palette order (pure metadata; icons resolve via kit/icons).
export const VAULTR_COMMANDS = [
  { route: "pane.split:right", label: "Split right", context: "Pane: Split right", words: "split vertical pane right", icon: "split-right" },
  { route: "pane.split:down", label: "Split down", context: "Pane: Split down", words: "split horizontal pane down", icon: "split-down" },
  { route: "layout.toggle:ob-left", label: "Toggle left sidebar", context: "Sidebar: Toggle left", words: "left sidebar toggle panel", icon: "panel-left" },
  { route: "layout.toggle:ob-right", label: "Toggle right sidebar", context: "Sidebar: Toggle right", words: "right sidebar toggle panel", icon: "panel-right" },
  { route: "ob-tabs.zen", label: "Toggle Zen mode", context: "Zen mode: Toggle", words: "zen mode toggle focus", icon: "minimize" },
  { route: "ob-tabs.open:ob-sessions@reveal", label: "Reveal active session", context: "Sessions: Reveal current tab", words: "reveal active session files", icon: "locate" },
  { route: "ob-tabs.switcher:move", label: "Move tab to another space", context: "Tabs: Reorder or move tab", words: "move tab space reorder", icon: "move" },
  { route: "ob-tabs.switcher:views", label: "Switch views", context: "Views: Open view switcher", words: "switch views panel", icon: "layers" },
  { route: "ob-tabs.copy-path", label: "Copy path", context: "Tab: Copy working directory", words: "copy path directory folder", icon: "copy" },
  { route: "ob-tabs.copy-address", label: "Copy terminal address", context: "Tab: Copy terminal address", words: "copy terminal address", icon: "terminal" },
  { route: "ob-tabs.daily", label: "Open today's daily note", context: "Daily notes: Open today", words: "daily note today journal", icon: "calendar" },
  { route: "ob-tabs.bookmark", label: "Bookmark current tab", context: "Bookmarks: Bookmark tab", words: "bookmark save tab", icon: "bookmark-plus" },
  { route: "ob-tabs.back", label: "Navigate back", context: "History: Back", words: "navigate back history", icon: "arrow-left" },
  { route: "ob-tabs.forward", label: "Navigate forward", context: "History: Forward", words: "navigate forward history", icon: "arrow-right" },
  { route: "ob-tabs.last", label: "Go to last tab", context: "Tabs: Last tab", words: "go last tab", icon: "tab" },
  { route: "ob-tabs.tab-list", label: "Show tab list", context: "Tabs: Open tab list", words: "show tab list", icon: "list" },
  { route: "ob-tabs.new", label: "New tab menu", context: "Tabs: New tab menu", words: "new tab menu", icon: "plus" },
  { route: "ob-tabs.toggle:ob-outline", label: "Toggle Outline", context: "Outline: Toggle panel", words: "toggle outline panel", icon: "list-tree" },
  { route: "ob-tabs.toggle:ob-quotas", label: "Toggle Quotas", context: "Quotas: Toggle panel", words: "toggle quotas panel", icon: "coins" },
  { route: "ob-tabs.settings:hotkeys", label: "Open hotkeys", context: "Settings: Hotkeys", words: "hotkeys keyboard shortcuts keybindings", icon: "keyboard" },
  { route: "mod.open:ob-settings", label: "Open settings", context: "Settings: Vaultr settings", words: "settings preferences options", icon: "settings" },
  { route: "ob-tabs.settings:feedback", label: "Open feedback settings", context: "Settings: Feedback folder", words: "feedback folder path settings", icon: "folder" },
  { route: "ob-tabs.feedback", label: "Submit feedback", context: "Feedback: Save note, screenshot and logs", words: "feedback bug report screenshot logs diagnostics", icon: "square-pen" },
  { route: "ob-sessions.collapse-all", label: "Collapse all sessions", context: "Sessions: Collapse folders", words: "collapse all sessions folders", icon: "collapse-all" },
  { route: "ob-sessions.expand-all", label: "Expand all sessions", context: "Sessions: Expand folders", words: "expand all sessions folders", icon: "expand-all" },
  { route: "ob-feed.refresh", label: "Rescan sub-agents", context: "Sub-agents: Rescan sessions", words: "rescan refresh subagents feed", icon: "refresh" },
  { route: "ob-graph.fit", label: "Fit graph", context: "Graph: Fit to view", words: "fit graph zoom reset", icon: "graph" },
];

// Pointer-only / internal commands and base forms replaced by parameterized entries.
const HIDDEN = new Set([
  "space.move", "tab.move", "space.select", "tab.select", "pane.focus", "pane.swap",
  "terminal.keep", "terminal.park", "terminal.kill", "terminal.show", "terminal.peek",
  "terminal.right_click", "terminal.pin", "agent.focus",
  "layout.set", "layout.toggle", "layout.show", "layout.hide", "layout.resize", "layout.select",
  "mod.open", "overlay.close", "tab.settle", "tab.unsettle",
  "app.palette", "app.hide", "app.hide_others", "app.show_all", "app.theme", "app.settings",
  "layout.clone", "mod.clone",
]);

const LAYOUT_TITLES = { main: "Herdr", terminals: "Terminals", win98: "Herdr 98", vaultr: "Vaultr" };

function layoutTitle(name) {
  return LAYOUT_TITLES[name] ?? (name.charAt(0).toUpperCase() + name.slice(1));
}

// Match string actions ("pane.split:right") and serialized object bindings (`{"command":"pane.split","args":{"direction":"right"}}`).
function actionMatches(keyAction, targetAction) {
  if (keyAction === targetAction) return true;
  if (typeof keyAction !== "string" || !keyAction.startsWith("{")) return false;
  let obj;
  try { obj = JSON.parse(keyAction); } catch { return false; }
  if (!obj || typeof obj.command !== "string") return false;
  const args = obj.args && typeof obj.args === "object" && !Array.isArray(obj.args) ? obj.args : {};
  const entries = Object.entries(args).filter(([, v]) => v !== undefined && v !== null);
  const colon = targetAction.indexOf(":");
  if (colon < 0) return obj.command === targetAction && entries.length === 0;
  const cmdName = targetAction.slice(0, colon);
  const argVal = targetAction.slice(colon + 1);
  return obj.command === cmdName && entries.length === 1 && String(entries[0][1]) === argVal;
}

// The query after ">", trimmed; null when the query is not in command mode.
export function commandQuery(query) {
  const q = String(query ?? "").trim();
  return q.startsWith(">") ? q.slice(1).trim() : null;
}

// The chord bound to an action, preferring the layout's section, then global, then any section.
// Within a tier, macOS prefers "cmd-" chords and non-macOS prefers non-"cmd-" chords.
export function chordFor(keys, action, layout = "vaultr", platform = "linux") {
  const hits = (keys ?? []).filter((k) => k && typeof k.keys === "string" && actionMatches(k.action, action));
  if (!hits.length) return null;
  const isCmd = (s) => /(?:^|[\s-])cmd-/.test(s);
  const pickFrom = (list) => {
    if (!list.length) return null;
    if (platform === "macos") return (list.find((k) => isCmd(k.keys)) ?? list[0]).keys;
    return (list.find((k) => !isCmd(k.keys)) ?? list[0]).keys;
  };
  return pickFrom(hits.filter((k) => k.section === `layout:${layout}`))
    ?? pickFrom(hits.filter((k) => k.section === "global"))
    ?? pickFrom(hits);
}

// Herdr's runnable commands as rows: expands parameterized commands into runnable routes and hides
// pointer-only / internal / unparameterized required-arg commands (matching frame/palette).
export function herdrItems(herdr, keys, layout = "vaultr", opts = {}) {
  const { platform = "linux", layouts = [] } = opts ?? {};
  const out = [];
  out.push({
    key: `cmd:${PALETTE_ROUTE}`, kind: "command", source: "herdr-palette", route: PALETTE_ROUTE,
    label: PALETTE_LABEL, context: "Herdr's own palette: every command", words: "herdr command palette app palette",
    chord: chordFor(keys, PALETTE_ROUTE, layout, platform) ?? undefined,
  });
  const valid = (herdr ?? []).filter((c) => c && typeof c.name === "string");
  const known = new Set(valid.map((c) => c.name));
  const pushParam = (route, label, context, words) => {
    out.push({
      key: `cmd:${route}`, kind: "command", source: "herdr", route, label,
      context, words: `${route} ${words}`,
      chord: chordFor(keys, route, layout, platform) ?? undefined,
    });
  };
  if (known.has("pane.split")) {
    pushParam("pane.split:right", "Split right", "Split a pane right", "pane split right vertical");
    pushParam("pane.split:down", "Split down", "Split a pane down", "pane split down horizontal");
  }
  if (known.has("pane.go")) {
    for (const d of ["left", "right", "up", "down"]) {
      pushParam(`pane.go:${d}`, `Focus pane ${d}`, `Focus pane ${d}`, `pane go focus move ${d}`);
    }
  }
  if (known.has("pane.swap")) {
    for (const d of ["left", "right", "up", "down"]) {
      pushParam(`pane.swap:${d}`, `Swap pane ${d}`, `Swap pane ${d}`, `pane swap move ${d}`);
    }
  }
  if (known.has("tab.select")) {
    for (let i = 1; i <= 9; i++) {
      pushParam(`tab.select:${i}`, `Go to tab ${i}`, `Show tab ${i} in this space`, `tab select go switch ${i}`);
    }
  }
  if (known.has("space.select")) {
    for (let i = 1; i <= 9; i++) {
      pushParam(`space.select:${i}`, `Go to space ${i}`, `Show space ${i}`, `space select go switch ${i}`);
    }
  }
  if (known.has("layout.switch")) {
    for (const l of new Set((layouts ?? []).filter((x) => typeof x === "string" && x))) {
      pushParam(`layout.switch:${l}`, `Layout: ${layoutTitle(l)}`, `Switch layout to ${l}`, `layout switch look ${l}`);
    }
  }
  if (known.has("layout.clone") && layout) {
    pushParam(`layout.clone:${layout}`, `Duplicate ${layoutTitle(layout)} layout`, `Clone ${layout} layout`, `layout clone duplicate copy ${layout}`);
  }
  for (const c of valid) {
    if (c.name === PALETTE_ROUTE || HIDDEN.has(c.name)) continue;
    if (platform === "macos" && c.name.startsWith("window.")) continue;
    if ((c.args ?? []).some((a) => a && a.required)) continue;
    const about = String(c.about ?? "");
    out.push({
      key: `cmd:${c.name}`, kind: "command", source: "herdr", route: c.name, label: c.name,
      context: about.length > 100 ? `${about.slice(0, 99)}…` : about, words: `${c.name} ${about}`,
      chord: chordFor(keys, c.name, layout, platform) ?? undefined,
    });
  }
  return out;
}

// Vaultr's commands as rows: each carries its route (what runs) and the chord bound to it. Sidebar views are not
// commands (Views is its own mode), so their rows are left out.
export function vaultrItems(vaultr, keys, layout = "vaultr", opts = {}) {
  const { platform = "linux" } = opts ?? {};
  return (vaultr ?? []).filter((v) => v && typeof v.route === "string" && allowsRow("commands", v)).map((v) => ({
    ...v, key: `cmd:${v.route}`, kind: "command", source: "vaultr", chord: chordFor(keys, v.route, layout, platform) ?? undefined,
  }));
}

// The ranked list: [{ item, hits, score }]. Vaultr's rows first, then Herdr's; a route listed by both is kept once,
// as Vaultr's. With a query, rows are scored on their label, then on label + context + words (minus 4).
export function commandRows({ vaultr = [], herdr = [], keys = [], query = "", layout = "vaultr", platform = "linux", layouts = [], match = substring } = {}) {
  const seen = new Set();
  const all = [];
  for (const it of vaultrItems(vaultr, keys, layout, { platform })) { if (!seen.has(it.route)) { seen.add(it.route); all.push(it); } }
  for (const it of herdrItems(herdr, keys, layout, { platform, layouts })) { if (!seen.has(it.route)) { seen.add(it.route); all.push(it); } }
  const q = String(query ?? "").trim();
  if (!q) return sinkDisabled(all.map((item) => ({ item, hits: [], score: 1 })));
  const scored = [];
  for (const item of all) {
    const title = match(q, item.label);
    const more = title ? null : match(q, `${item.label} ${item.context ?? ""} ${item.words ?? ""}`);
    const best = title ?? (more && { score: more.score - 4, hits: [] });
    if (best) scored.push({ item, hits: best.hits ?? [], score: best.score });
  }
  scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  return sinkDisabled(scored);
}

// Stand-in matcher (case-insensitive substring) for callers without the switcher's fuzzy().
function substring(q, text) {
  const i = String(text ?? "").toLowerCase().indexOf(String(q).toLowerCase());
  return i < 0 ? null : { score: 10 - i / 100, hits: [] };
}
