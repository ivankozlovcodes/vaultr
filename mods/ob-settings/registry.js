// registry.js: every command the hotkeys screen lists. An entry:
//   { action (the exact keys.json string), title, group, home (the keys.json section it belongs to),
//     defaults (its chords in `home`), obsidian? (the Obsidian command with the same key), when?, missingArg? }
// Built from fixed tables plus the app's live commands() and keys() (rows for anything bound in
// keys.json that the tables don't name, so nothing in the file is ever hidden).

import { commands, keys, window as appWindow } from "herdr";
import {
  LAYOUT_SCOPE, SESSIONS_SCOPE, NAMED, HIDDEN, TERMINAL, SENDS, GROUPS,
  visibleText, titleFor, missingRequiredArg, buildRegistry,
  defaultsIn, chainOf, scopeTitle, scopeWhere, scopeShort,
} from "./registry_rules.js";

export {
  LAYOUT_SCOPE, SESSIONS_SCOPE, GROUPS,
  visibleText, titleFor, missingRequiredArg,
  defaultsIn, chainOf, scopeTitle, scopeWhere, scopeShort,
};

// The Obsidian layout's own commands, with the Obsidian command each key mirrors
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
  ["ob-tabs.open:ob-quotas", "Show quotas", [], null],
  ["ob-tabs.toggle:ob-quotas", "Toggle Quotas", [], null],
  ["ob-tabs.open:ob-props", "Show properties", ["ctrl-alt-i"], "Properties: Show file properties"],
  ["ob-tabs.open:ob-agents", "Show agents", ["ctrl-alt-a"], null],
  ["ob-tabs.bookmark", "Bookmark current tab", ["ctrl-alt-b"], "Bookmarks: Bookmark..."],
  ["ob-tabs.back", "Navigate back", ["ctrl-alt-left"], "Navigate back (Ctrl+Alt+←)"],
  ["ob-tabs.forward", "Navigate forward", ["ctrl-alt-right"], "Navigate forward (Ctrl+Alt+→)"],
  ["ob-tabs.last", "Go to last tab", ["ctrl-9"], "Go to last tab (Ctrl+9)"],
  ["ob-tabs.settings:hotkeys", "Open hotkeys", ["ctrl-alt-k"], "Settings: Hotkeys"],
  ["ob-tabs.settings:feedback", "Open feedback settings", [], null],
  ["ob-tabs.feedback", "Submit feedback", ["ctrl-alt-shift-f"], null],
  ["mod.open:ob-settings", "Open settings", ["ctrl-,"], "Settings: Open settings"],
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

function safeKeys() {
  try { return (keys() ?? []).filter((k) => k && typeof k.action === "string"); } catch { return []; }
}

function safeCommands() {
  try { return commands() ?? []; } catch { return []; }
}

export function registry() {
  let platform = "linux";
  try { platform = appWindow()?.platform ?? "linux"; } catch { platform = "linux"; }
  return buildRegistry({
    ob: OB, sessions: SESSIONS, named: NAMED, hidden: HIDDEN, terminal: TERMINAL,
    commands: safeCommands(), keys: safeKeys(), platform,
  });
}
