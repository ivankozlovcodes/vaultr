// Transcript search, the pure part (no Herdr or kit imports, so test/ runs it under node). The matcher is the kit copy
// (./fuzzy.js, synced from kit/fuzzy.js).
// The sessions to search come from the sub-agent feed (ob-feed's shared "ob.subagents", read with feed()):
// the live agent terminals (feed.terms: their session or transcript file), the Claude Code sub-agents
// (feed.claude) and the pi sub-agent steps (feed.runs[].steps). Only this computer is searched: a session
// whose machine is not this one is left out.

import { matchQuery, snippet as snippetOf } from "./fuzzy.js";

const base = (p) => String(p ?? "").replace(/\/+$/, "").split("/").pop();

// -> [{ id, path, kind: "main"|"subagent", label, parent (terminal address|null) }], deduplicated by path.
// opts.parents: a Set of terminal addresses; when given, only sessions whose parent is in it are kept.
export function sourcesFrom(feed, opts = {}) {
  if (!feed) return [];
  const out = [];
  const seen = new Set();
  const add = (path, kind, label, parent) => {
    if (typeof path !== "string" || !path || seen.has(path)) return;
    if (opts.parents && !opts.parents.has(parent)) return;
    seen.add(path);
    out.push({ id: `s${out.length}`, path, kind, label: String(label || "agent"), parent: parent ?? null });
  };
  for (const [addr, info] of Object.entries(feed.terms ?? {})) {
    if (!info || typeof info !== "object" || String(addr).includes("/")) continue;
    add(info.transcript || info.session, "main", info.name || base(info.cwd) || "agent", addr);
  }
  for (const c of feed.claude ?? []) {
    if (!c || c.machine) continue;
    add(c.transcript, "subagent", c.desc || c.type || "sub-agent", c.parent);
  }
  for (const r of feed.runs ?? []) {
    if (!r || r.machine) continue;
    for (const s of r.steps ?? []) {
      if (!s || typeof s !== "object") continue;
      add(s.session || s.transcript, "subagent", s.task || s.agent || "sub-agent", r.parent);
    }
  }
  return out;
}

// Hits per session, best first. `results` is what the scan helper returned per session:
// [{ id, path, msgs: [{ i, role, ts, text }] }]; a result with an error or no id is skipped.
// Each message is matched with the same rule as the terminals (matchQuery) and gets a snippet.
// opts: { caseSensitive, perGroup (hits shown per session), total (hits shown in all) }.
// -> [{ id, path, label, kind, parent, count, hits: [{ role, ts, i, text, score, snippet: {text, spans} }] }]
export function buildGroups(sources, results, query, opts = {}) {
  const perGroup = opts.perGroup ?? 5, total = opts.total ?? 200;
  const byId = new Map((sources ?? []).map((s) => [s.id, s]));
  const groups = [];
  for (const r of results ?? []) {
    const src = r && byId.get(r.id);
    if (!src || !Array.isArray(r.msgs)) continue;
    const hits = [];
    for (const msg of r.msgs) {
      const m = matchQuery(query, msg.text, { caseSensitive: opts.caseSensitive });
      if (!m) continue;
      hits.push({ role: msg.role, ts: msg.ts ?? null, i: msg.i, text: msg.text, score: m.score, snippet: snippetOf(msg.text, m.spans) });
    }
    if (!hits.length) continue;
    hits.sort((a, b) => (b.score - a.score) || (Number(b.ts) || 0) - (Number(a.ts) || 0) || (b.i - a.i));
    groups.push({ id: src.id, path: src.path, label: src.label, kind: src.kind, parent: src.parent, count: hits.length, best: hits[0].score, hits });
  }
  groups.sort((a, b) => b.best - a.best);
  let left = total;
  const out = [];
  for (const g of groups) {
    if (left <= 0) break;
    const shown = g.hits.slice(0, Math.min(perGroup, left));
    left -= shown.length;
    out.push({ ...g, hits: shown });
  }
  return out;
}

// The words at the right of the TRANSCRIPTS header for a scan state (main.js's this.tx). Regex is not run on
// transcripts (the helper and buildGroups match fuzzily only), so with regex on the section says so.
export function txStatus(tx) {
  const groups = tx?.groups ?? [];
  const n = groups.reduce((a, g) => a + (g.count ?? 0), 0);
  if (tx?.status === "searching") return "searching…";
  if (tx?.regex) return "fuzzy only: regex is on";
  if (tx?.error) return "couldn't search";
  if (tx?.none) return "no agent sessions on this computer";
  return n ? `${n} in ${groups.length} session${groups.length === 1 ? "" : "s"}` : "no matches";
}

// Runs fn(cx, job) for one job at a time. A job that arrives while one runs is not started: only the newest of them is
// kept and runs when the current one ends (with the first call's cx). exec cannot be cancelled, so this is what keeps
// several python3 scans from piling up while a person types with pauses.
export function latestOnly(fn) {
  let busy = false, next = null;
  return async (cx, job) => {
    if (busy) { next = { job }; return; }
    busy = true;
    try {
      for (let j = { job }; j; j = next) {
        next = null;
        try { await fn(cx, j.job); } catch (e) { console.log(`ob-search: transcript scan failed: ${e?.message ?? e}`); }
      }
    } finally { busy = false; next = null; }
  };
}
