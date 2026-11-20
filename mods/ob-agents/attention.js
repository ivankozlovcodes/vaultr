// attention.js: pure rules for who needs you, and for dismissing a "Needs you" entry.
// MASTER COPY: kit/attention.js. sync.sh copies it into mods/ob-*/attention.js.
// Pure ES module: no herdr or gpui imports so tests can run it in node.
//
// An agent that is blocked or ended with an error needs you. The person can dismiss that: for attention (the Agents
// sections and counts, the Agents tab badge, the status bar counts, the Sessions marks and pill) the agent then counts
// as idle. Panels that show the terminal's own status (pane header, Properties, Outline) do not use this.
//
// Dismissals: { [terminal address]: stamp }. A stamp names one status report: the status word, the time of the
// terminal's last status change (status_ms) and its turn counter. When any of them moves on, the stamp no longer
// matches, the dismissal ends by itself and the agent is flagged again.

// Mirrors kit/kit.js STATUS_MAP (test/test_attention.py checks the two agree). Unknown words are idle, null stays null.
const WORDS = {
  working: "working", running: "working", queued: "working", busy: "working", starting: "working",
  blocked: "blocked", error: "failed", failed: "failed", lost: "failed",
  done: "done", complete: "ok", completed: "ok", success: "ok", ok: "ok",
  idle: "idle", stopped: "stopped", cancelled: "stopped", canceled: "stopped",
};
export function attentionWord(s) { return s == null ? null : WORDS[s] ?? "idle"; }

// The Agents panel's sections: 4 Needs you, 3 Done, 2 Working, 1 Idle; 0 for ok, stopped and no status.
const RANK = { blocked: 4, failed: 4, done: 3, working: 2, idle: 1 };
export function attentionRank(s) { return RANK[attentionWord(s)] ?? 0; }
export function isNeedsYou(s) { return attentionRank(s) === 4; }

// Counts by section; failed counts with blocked as "needs you". ok, stopped and no status are not counted.
export function attentionCounts(statuses) {
  const out = { blocked: 0, done: 0, working: 0, idle: 0 };
  for (const s of statuses ?? []) {
    const w = attentionWord(s);
    const k = w === "failed" ? "blocked" : w;
    if (k in out) out[k] += 1;
  }
  return out;
}

// The stamp of a terminal's current report. term: a terminals() entry (status_ms, turn), or nothing. The status goes
// in as its word ("error" and "failed" are one), so panels that read the raw word a little differently still agree.
export function dismissStamp(status, term) {
  return `${attentionWord(status) ?? ""}@${term?.status_ms ?? ""}#${term?.turn ?? ""}`;
}

export function normDismissed(raw) {
  const out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [k, v] of Object.entries(raw)) if (k && typeof v === "string") out[k] = v;
  return out;
}

// Whether this report of this agent is dismissed. Only a needs-you status can be.
export function isDismissed(dis, address, status, term) {
  if (!address || !isNeedsYou(status) || !dis || typeof dis !== "object") return false;
  const v = dis[address];
  return typeof v === "string" && v === dismissStamp(status, term);
}

// The status to use for attention: idle when this report is dismissed, else the status unchanged.
export function attentionStatus(dis, address, status, term) {
  return isDismissed(dis, address, status, term) ? "idle" : status;
}

// Dismiss (stamp) or restore (stamp null) one agent; returns a new map.
export function patchDismissed(raw, address, stamp) {
  const out = normDismissed(raw);
  if (!address) return out;
  if (stamp) out[String(address)] = String(stamp);
  else delete out[String(address)];
  return out;
}

// Keeps only the dismissals whose terminal still exists and still has the dismissed report.
// current: Map or object, address -> its stamp now. Only removes, so a smaller result means something was dropped.
export function pruneDismissed(raw, current) {
  const norm = normDismissed(raw);
  const now = current instanceof Map ? current : new Map(Object.entries(current ?? {}));
  const out = {};
  for (const [k, v] of Object.entries(norm)) if (now.get(k) === v) out[k] = v;
  return out;
}
