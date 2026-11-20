// ob-outline: pure decisions behind the panel's actions (Transcript, Attach, Escape, Move to main window).
// No Herdr or kit imports, so test/test_ob_subagents.py runs them under node.

// A row key is a run key ("<machine>:<id>"), a Claude agent key ("<machine>:<id>" from the feed, or
// "<parent>#<id>" from a live record) or a pi step key ("<run key>#<step index>"). A Claude key may contain "#",
// so a key that is a known row is taken whole before the step suffix is read.
// -> { key, step: number | null } or null when nothing matches.
export function resolveKey(key, { runs = [], claude = [] } = {}) {
  if (runs.includes(key) || claude.includes(key)) return { key, step: null };
  const m = /^(.*)#(\d+)$/.exec(String(key ?? ""));
  if (m && runs.includes(m[1])) return { key: m[1], step: Number(m[2]) };
  return null;
}

// What Transcript does for a row that has (or may have) a transcript file.
// item: { path } for a pi step, or { transcript, desc, type, live } for a Claude agent.
// -> { open: true, path, title } or { open: false, notice }
export function transcriptPlan(item) {
  const path = item?.path ?? item?.transcript ?? null;
  if (path) return { open: true, path, title: item.title ?? `${item.desc || item.type || "agent"} · transcript` };
  return { open: false, notice: "No transcript is recorded for this agent yet" };
}

// Attach on a row. kind "terminal": an hc child terminal; "claude": a Claude Code agent (no terminal of its own).
// -> { show, enabled, tip }
export function attachPlan(row) {
  if (row?.kind === "claude") {
    return { show: true, enabled: false, tip: "No terminal: this agent runs inside its parent; open its transcript" };
  }
  if (row?.kind === "terminal") {
    if (row.state !== "live") return { show: false, enabled: false, tip: "" };
    return { show: true, enabled: true, tip: "Attach: the live terminal in a popup, typeable" };
  }
  return { show: false, enabled: false, tip: "" };
}

// What attach() does with the terminal record it found for `address` (terminals(), maybe none yet). A terminal just
// started (Open session) can be missing or not live for a moment: with a timer (canWait) it is looked for again,
// ATTACH_TRIES times ATTACH_WAIT ms apart, then attach gives up with the reason. -> { do: "open"|"retry"|"fail", why? }
export const ATTACH_TRIES = 4, ATTACH_WAIT = 250;
export function attachStep(address, term, tries, canWait) {
  if (term?.state === "live") return { do: "open" };
  if (canWait && tries < ATTACH_TRIES) return { do: "retry" };
  return { do: "fail", why: term ? `Terminal ${address} is ${term.state ?? "not live"}` : `No live terminal ${address}` };
}

// Escape in a popup: a transcript or log closes; an attached terminal keeps Escape (agents use it)
// only once the terminal itself has focus. On initial open, the attach header/container has focus so Escape detaches.
export function escapeOwner(view, terminalFocused = false) {
  return view === "attach" && terminalFocused ? "terminal" : "close";
}

// Detach. In an attach popup it closes the popup; for a terminal that has a pane (after "Move to main window")
// it is Herdr's terminal.park: the pane (or its tab, when it was the only pane) goes away and the program keeps
// running in the background, where the Outline lists it. Close pane would end the program.
export const DETACH_ICON = "win-min";
export const DETACH_POPUP_TIP = "Detach: close popup and leave terminal running in background";
// -> the menu item that parks a placed terminal, or null for a pane without one (a mod pane).
export function detachItem(terminal) {
  return terminal ? { label: "Detach to background", icon: DETACH_ICON, command: "terminal.park", args: { terminal } } : null;
}

// Move to main window: beside the focused pane when there is one, else a new tab. The popup closes after.
export function moveTarget(hasPane, props) {
  const args = { mod: "ob-outline", props };
  return hasPane ? { verb: "pane.split", args: { direction: "right", ...args } } : { verb: "tab.new", args };
}
