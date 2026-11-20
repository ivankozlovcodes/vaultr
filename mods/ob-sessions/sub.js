// Sub-agents of one terminal as uniform items (pi runs, Claude agents, hc child terminals).
// Built on kit.subagentsOf (the only reader of the shared feed). Same file in ob-agents.

import { terminals } from "herdr";
import { subagentsOf, normStatus, isChildTerminalOf } from "./kit.js";

// A Claude Code sub-agent's state. Herdr's live records win; without one, the feed's `ended`
// decides, and an unfinished transcript counts as working only while it was written to lately
// (an agent whose session was killed never writes `ended`).
const FRESH = 180000;
export function claudeState(c, now = Date.now()) {
  if (c.state) return c.state === "working" || c.state === "blocked" ? c.state : "ok";
  if (c.live) return "working";
  if (c.ended) return "ok";
  if (c.updatedAt && now - c.updatedAt < FRESH) return "working";
  return "stopped";
}

const isLive = (s) => s === "working" || s === "blocked";

// -> [{ kind: "run"|"claude"|"child", key, label, detail, status, live, at, item }], live first, newest first.
export function subItems(address, all = null, now = Date.now()) {
  if (!address) return [];
  const sa = subagentsOf(address);
  const out = [];
  for (const r of sa.runs) {
    const chain = (r.steps ?? []).map((s) => s.agent).filter(Boolean);
    const label = chain.length > 3 ? `${r.mode ?? "workflow"} · ${chain.length} agents` : chain.join(" → ") || r.mode || r.short || "run";
    const models = [...new Set((r.steps ?? []).map((s) => s.model).filter(Boolean))].map((m) => String(m).replace(/^claude-/, ""));
    const status = r.live ? "working" : r.state ?? null;
    out.push({ kind: "run", key: `r:${r.key}`, id: r.key, label, detail: models.join(", "), status, live: Boolean(r.live), at: r.live ? r.startedAt : r.endedAt ?? r.lastUpdate ?? r.startedAt, item: r,
      text: [label, models.join(" "), ...(r.steps ?? []).map((s) => s.task ?? "")].join(" ") });
  }
  for (const c of sa.claude) {
    const status = claudeState(c, now);
    out.push({ kind: "claude", key: `c:${c.key}`, id: c.key, label: c.desc || c.type || c.id, detail: c.type ?? "", status, live: isLive(status), at: c.updatedAt ?? 0, item: c,
      text: [c.desc, c.type, c.model].filter(Boolean).join(" ") });
  }
  for (const t of all ?? terminals()) {
    if (!isChildTerminalOf(t, address)) continue;
    const status = t.status === "error" ? "blocked" : t.status === "done" ? "idle" : t.status ?? null;
    const label = t.name || t.template || t.program?.name || t.address;
    out.push({ kind: "child", key: `h:${t.address}`, id: t.address, label, detail: t.address, status, live: isLive(normStatus(status)), at: t.created_ms ?? 0, item: t, text: label });
  }
  out.sort((a, b) => (b.live - a.live) || ((b.at ?? 0) - (a.at ?? 0)));
  return out;
}

export function counts(items) {
  return { live: items.filter((i) => i.live).length, total: items.length };
}
