// Pure follow rule for the right-hand panels (Properties, Outline). Copied into each ob-* mod by kit/sync.sh;
// kit.js re-exports it. No Herdr or gpui imports, so test/ can run it under node.
//
// The panel shows its pinned terminal while that terminal is live. Otherwise it shows the last focused main-window
// pane that holds a terminal (wantAgent false: Properties) or an agent (wantAgent true: Outline). Focus on anything
// else (a side panel, a dialog, a pane without a terminal, or a shell when wantAgent) keeps the previous target.
//
// Arguments:
//   pinned    the pinned terminal's address, or null (ob.inspect)
//   focused   { pane, terminal, agent } from focused() with `agent` set by the caller (the terminal is in agents()),
//             or null when no main-window pane has focus
//   last      the address this panel followed last, or null (the mod keeps it in shared state)
//   terminals terminals() entries: { address, state }; only state "live" counts
//   wantAgent true for Outline (ob-outline)
// Returns { terminal, last }: the address to show (null for the empty state) and the `last` to keep.
export function followTarget({ pinned = null, focused = null, last = null, terminals = [], wantAgent = false } = {}) {
  const live = new Set();
  for (const t of terminals ?? []) if (t && t.state === "live") live.add(t.address);
  const main = focused && focused.pane && focused.terminal && (!wantAgent || focused.agent) ? focused.terminal : null;
  const next = main ?? last ?? null;
  if (pinned && live.has(pinned)) return { terminal: pinned, last: next };
  if (next && live.has(next)) return { terminal: next, last: next };
  return { terminal: null, last: null };
}
