// ob-props usage: the token arithmetic and the words for the Usage section. Pure (no herdr imports), so the tests
// can run it in node. Input: turns from provider usage, in file order: { id, model, input, output, cacheRead, cacheWrite }.

// A model's context window, when it is one this file knows: the 3 family (…-3-opus-…, …-3-5-sonnet-…)
// and the 4 family (…-opus-4-…): 200k; 1M with a "[1m]" suffix on opus and sonnet 4. Any other model returns null,
// and its context shows the count only.
export function windowOf(model) {
  if (typeof model !== "string") return null;
  const base = model.replace(/\[1m\]$/, "");
  const four = /^[a-z]+-(opus|sonnet|haiku)-4(?![0-9])/.exec(base);
  if (!four && !/^[a-z]+-3-([0-9]-)?(opus|sonnet|haiku)(-|$)/.test(base)) return null;
  return four && four[1] !== "haiku" && base !== model ? 1000000 : 200000;
}

// Sums over the turns. context = the last turn's input + cache read + cache write (what it sent), not a sum.
// -> { input, output, cacheRead, cacheWrite, total, turns, model, context, window, share } or null with no turns.
export function summarize(turns) {
  if (!Array.isArray(turns) || turns.length === 0) return null;
  const sum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  for (const t of turns) {
    for (const k of Object.keys(sum)) sum[k] += Number(t[k]) || 0;
  }
  const last = turns[turns.length - 1];
  const model = last.model ?? null;
  const context = (Number(last.input) || 0) + (Number(last.cacheRead) || 0) + (Number(last.cacheWrite) || 0);
  const window = windowOf(model);
  return {
    ...sum,
    total: sum.input + sum.output + sum.cacheRead + sum.cacheWrite,
    turns: turns.length,
    model,
    context,
    window,
    share: window ? context / window : null,
  };
}

// 1234567 -> "1,234,567".
export function fmtCount(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// 0.5 -> "50%", 0.004 -> "0.4%".
export function fmtShare(x) {
  const pct = x * 100;
  return `${pct < 10 ? Number(pct.toFixed(1)) : Math.round(pct)}%`;
}

// The Usage rows, in the panel's order: [{ id, key, value }]. No summary -> no rows.
export function usageLines(s) {
  if (!s) return [];
  const ctx = s.window
    ? `${fmtCount(s.context)} · ${fmtShare(s.share)} of ${fmtCount(s.window)}`
    : fmtCount(s.context);
  return [
    { id: "input", key: "Input", value: fmtCount(s.input) },
    { id: "output", key: "Output", value: fmtCount(s.output) },
    { id: "cacheRead", key: "Cache read", value: fmtCount(s.cacheRead) },
    { id: "cacheWrite", key: "Cache write", value: fmtCount(s.cacheWrite) },
    { id: "total", key: "Total", value: fmtCount(s.total) },
    { id: "context", key: "Context", value: ctx },
    { id: "model", key: "Model", value: s.model ?? "—" },
    { id: "turns", key: "Turns", value: fmtCount(s.turns) },
  ];
}

// The subagents line, from the feed's per-agent output tokens (cheap: no extra read). Agents: [{ outTokens }].
export function subagentsLine(agents) {
  if (!Array.isArray(agents) || agents.length === 0) return null;
  const out = agents.reduce((n, a) => n + (Number(a.outTokens) || 0), 0);
  return `${agents.length} agent${agents.length === 1 ? "" : "s"} · ${fmtCount(out)} output tokens`;
}
