// ob-recent's timeline entries: which agent transitions and which router visits become entries. Pure (no Herdr
// imports), so test/test_ob_recent.py runs it under node. Only main agents (terminal in a pane of a tab) record
// events; the rule is mainAgents in agents.js (the kit's copy of kit/agents.js).
import { mainAgents } from "./agents.js";

// Agent transitions since the last call. list: every agent (the map to keep covers all of them, so an agent that is
// placed later compares with what it was). placed: the terminal addresses in a pane. prev: Map address -> status from
// the last call, or null on the first call, which only seeds (no events for what was already so). Returns the
// changes to record ({ agent, status }: "blocked" = needs you, "done" = finished; main agents only) and the map to
// keep for the next call.
export function agentChanges(prev, list, placed) {
  const next = new Map((list ?? []).map((a) => [a.address, a.status]));
  if (!prev) return { changes: [], next };
  const changes = [];
  for (const a of mainAgents(list, placed)) {
    const was = prev.get(a.address);
    if (was === a.status) continue;
    if (a.status === "blocked" && was !== "blocked") changes.push({ agent: a, status: "blocked" });
    else if (was === "working" && (a.status === "idle" || a.status === "done")) changes.push({ agent: a, status: "done" });
  }
  return { changes, next };
}

// The router's visits to record. entries: ob.history's entries (chronological); histSeen: the newest entry already
// recorded (null: none); clearedAt: when the timeline was last cleared (0: never). Only entries newer than both are
// taken, so a clear is not undone by the router's older entries. Returns { take, histSeen }: the entries to record,
// and the newest entry seen (kept as the next histSeen, so later calls do not look at it again).
export function newVisits(entries, histSeen, clearedAt) {
  const seen = histSeen ?? 0;
  const floor = Math.max(seen, clearedAt ?? 0);
  const take = [];
  let top = seen;
  for (const e of entries ?? []) {
    if (!e || !e.at) continue;
    top = Math.max(top, e.at);
    if (e.at > floor) take.push(e);
  }
  return { take, histSeen: top };
}

// The timeline after adding `adds` (in order): the newest `max` visits, then the newest `max` agent events. The same
// as adding them one at a time, but filtered once, so a batch (the router's history) costs one pass and one save.
export function keepNewest(events, adds, max) {
  const all = [...(events ?? []), ...(adds ?? [])];
  return [...all.filter((e) => e.kind === "visit").slice(-max), ...all.filter((e) => e.kind !== "visit").slice(-max)];
}
