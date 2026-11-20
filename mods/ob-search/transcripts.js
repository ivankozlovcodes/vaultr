// Transcript search, pure UI helpers (no Herdr or kit imports, so test/ runs it under node).

// The words at the right of the TRANSCRIPTS header for a scan state (main.js's this.tx). Regex is not run on
// transcripts (provider search matches fuzzily only), so with regex on the section says so.
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
// several scans from piling up while a person types with pauses.
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
    } finally {
      busy = false;
    }
  };
}
