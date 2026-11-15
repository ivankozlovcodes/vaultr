// Pure agent helpers shared by the ob-* mods (copied into each mod by kit/sync.sh; kit.js re-exports them).
// No Herdr or gpui imports, so test/ can run them under node.
//
// A main agent is one whose terminal sits in a pane of a tab (what the person types into). A background agent is a
// terminal in no pane: an hc run --bg worker, a sub-agent, an agent in a tab with no pane. ob-agents lists main agents;
// ob-outline has the rest; ob-recent records agent events for main agents only.

// The terminal addresses that some pane shows. A mod pane has no terminal and places nothing.
export function placedTerminals(panes) {
  const out = new Set();
  for (const p of panes ?? []) if (p && p.terminal) out.add(p.terminal);
  return out;
}

// The agents (agents() order kept) whose terminal is placed.
export function mainAgents(agents, placed) {
  return (agents ?? []).filter((a) => placed.has(a.address));
}

// ---------------------------------------------------------------- activity (the Graph's halo and its "Active only" filter)
// One rule, so the halo and the filter cannot disagree, and the same answer as the Agents panel: a main agent is active when
// Herdr reports it working or blocked ("needs you"); every other status (idle, done, ok, failed, unknown) is not. A sub-agent
// or run is active when the feed says it is live (a local record too), and its feed is not paused (kit/feed_age.js).
// A node: { kind: "p" | "r" | "c" | "h", status, live, foreground, feedAt }. feedAt is the feed's `at` for a feed-sourced node.
// activeStatus mirrors kit/kit.js STATUS_MAP (test/test_ob_graph.py checks the two agree on every status).
import { feedPaused } from "./feed_age.js";

const ACTIVE_STATUS = {
  working: "working", running: "working", queued: "working", busy: "working", starting: "working", blocked: "blocked",
};
export function activeStatus(s) { return ACTIVE_STATUS[s] ?? null; }

const SUBAGENT_KINDS = new Set(["r", "c", "h"]);

// "working" | "blocked" | null (not active). now: epoch ms.
export function activityOf(n, now = Date.now()) {
  if (!n) return null;
  if (SUBAGENT_KINDS.has(n.kind)) {
    // `live` says the terminal or run exists; the status says whether it works, so done or idle is never active.
    const s = activeStatus(n.status);
    if (!n.live || s == null || feedPaused(n.feedAt, now)) return null;
    return s === "blocked" ? "blocked" : "working";
  }
  if (n.kind === "p" && n.foreground) return activeStatus(n.status);
  return null;
}
