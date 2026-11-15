// The quick switcher's modes, as pure functions (no Herdr or gpui imports; test/test_ob_switcher.py runs them under
// node). One mode system: Everything ("go"), Views ("views") and Commands ("commands").
//
// - Tab cycles Everything -> Views -> Commands -> Everything (Shift+Tab backwards). Move is its own entry point.
// - Typing ">" as the first character, in any mode, enters Commands; deleting it returns to the mode you came from.
// - The header names the current mode, the footer says where Tab goes next, and the placeholder says what to type.

export const MODES = ["go", "views", "commands"];
export const LABEL = { go: "Everything", views: "Views", commands: "Commands", move: "Move" };
export const PLACEHOLDER = {
  go: "Go to a tab, space or view…",
  views: "Find a view…",
  commands: "Run a command…",
  move: "Find a space or a position…",
};

// The mode after `mode` when Tab (step 1) or Shift+Tab (step -1) is pressed.
export function nextMode(mode, step = 1) {
  const i = MODES.indexOf(mode);
  if (i < 0) return MODES[0];
  return MODES[(((i + step) % MODES.length) + MODES.length) % MODES.length];
}

// True when the query starts with ">" (leading spaces ignored): the query is a command query.
export function isCommandQuery(query) {
  return String(query ?? "").trimStart().startsWith(">");
}

// The query without the ">" prefix, trimmed; the text as typed when there is no prefix.
export function bodyOf(query) {
  const s = String(query ?? "");
  return isCommandQuery(s) ? s.trimStart().slice(1).trim() : s;
}

// The mode the switcher is in after its query changed. `base` is the mode a ">" came from (Everything or Views).
// Returns { mode, base }.
export function modeForQuery(mode, base, query) {
  if (isCommandQuery(query)) return { mode: "commands", base: mode === "commands" ? base : mode };
  if (mode === "commands") { const back = base ?? "go"; return { mode: back, base: back }; }
  return { mode, base: mode };
}

// The text the input shows in `mode`: Commands gets a ">" prefix, the other modes lose it.
export function queryForMode(mode, query) {
  const body = bodyOf(query);
  if (mode !== "commands") return body;
  return body ? `> ${body}` : ">";
}

export function headerLabel(mode) { return LABEL[mode] ?? LABEL.go; }
export function placeholder(mode) { return PLACEHOLDER[mode] ?? PLACEHOLDER.go; }
// The footer hint after the tab key: where Tab goes next.
export function tabHint(mode) { return `→ ${LABEL[nextMode(mode)]}`; }

// Whether a row of the ranked list belongs to a mode. Commands has no sidebar-view rows (Views is its own mode).
export function allowsRow(mode, item) {
  const kind = item?.kind;
  if (mode === "views") return kind === "view";
  if (mode === "commands") return kind !== "view";
  return true;
}

// Rows that need arguments (disabled) go after every runnable row; the order inside each group is kept.
export function sinkDisabled(rows) {
  return [...rows.filter((r) => !r.item?.disabled), ...rows.filter((r) => r.item?.disabled)];
}
