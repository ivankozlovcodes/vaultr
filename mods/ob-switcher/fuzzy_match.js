// Fzf-style fuzzy matcher for the quick switcher (pure JS, no Herdr or gpui imports).
// Every space-separated query term must match. Contiguous substring hits rank in Tier 1 (200+);
// otherwise optimal subsequence alignment (Tier 2, 10..180) matches across word boundaries,
// camelCase transitions, and short intra-word skips while rejecting mid-word jumps across spaces.
// Returns { score, hits } (sorted unique character indexes for highlight()) or null.

const isAlnum = (c) => (c >= "a" && c <= "z") || (c >= "0" && c <= "9");
const isUpper = (c) => c >= "A" && c <= "Z";
const isLower = (c) => c >= "a" && c <= "z";

function analyze(raw, hay) {
  const n = hay.length;
  const sep = new Uint8Array(n);
  const bnd = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    sep[i] = isAlnum(hay[i]) ? 0 : 1;
    bnd[i] = (i === 0 || sep[i - 1] || (isUpper(raw[i]) && isLower(raw[i - 1]))) ? 1 : 0;
  }
  return { sep, bnd };
}

function matchSubstring(term, hay, sep, bnd) {
  const m = term.length;
  const n = hay.length;
  let best = null;
  let from = 0;
  while (from <= n - m) {
    const p = hay.indexOf(term, from);
    if (p < 0) break;
    const endBnd = p + m === n || sep[p + m] || bnd[p + m];
    const score = 200 + (bnd[p] ? 30 : 0) + (endBnd ? 15 : 0) + (p === 0 ? 15 : 0) - p * 0.1;
    if (!best || score > best.score) {
      best = { score, hits: Array.from({ length: m }, (_, k) => p + k) };
    }
    from = p + 1;
  }
  return best;
}

function matchSubsequence(term, hay, sep, bnd) {
  const m = term.length;
  const n = Math.min(hay.length, 300);
  if (m > n) return null;
  // Quick existence check in order before DP.
  let qi = 0;
  for (let j = 0; j < n && qi < m; j++) if (hay[j] === term[qi]) qi++;
  if (qi < m) return null;

  const NEG = -1e9;
  const dp = Array.from({ length: m }, () => new Float64Array(n).fill(NEG));
  const back = Array.from({ length: m }, () => new Int32Array(n).fill(-1));

  for (let j = 0; j < n; j++) {
    if (hay[j] !== term[0]) continue;
    dp[0][j] = (bnd[j] ? 16 : 2) + (j === 0 ? 4 : 0) - j * 0.05;
  }

  for (let i = 1; i < m; i++) {
    const ch = term[i];
    const prevRow = dp[i - 1];
    let farBest = NEG;
    let farIdx = -1;
    for (let j = i; j < n; j++) {
      // Any prev <= j - 14 hits the capped boundary gap penalty (-18).
      const farCand = j - 14;
      if (farCand >= i - 1 && prevRow[farCand] > farBest) {
        farBest = prevRow[farCand];
        farIdx = farCand;
      }
      if (hay[j] !== ch) continue;

      let best = NEG;
      let bestP = -1;

      // 1. Consecutive character match.
      if (prevRow[j - 1] > NEG / 2) {
        const sc = prevRow[j - 1] + 14 + (bnd[j] ? 6 : 0);
        if (sc > best) { best = sc; bestP = j - 1; }
      }

      // 2. Jump to a word start / camelCase boundary from any earlier match.
      if (bnd[j]) {
        const lo = Math.max(i - 1, j - 13);
        for (let p = j - 2; p >= lo; p--) {
          if (prevRow[p] <= NEG / 2) continue;
          const sc = prevRow[p] + 12 - (j - p - 1) * 1.5;
          if (sc > best) { best = sc; bestP = p; }
        }
        if (farIdx >= 0) {
          const sc = farBest + 12 - 18;
          if (sc > best) { best = sc; bestP = farIdx; }
        }
      } else {
        // 3. Short intra-word skip (up to 3 skipped chars, never crossing a separator).
        const lo = Math.max(i - 1, j - 4);
        for (let p = j - 2; p >= lo; p--) {
          if (sep[p + 1]) break;
          if (prevRow[p] <= NEG / 2) continue;
          const sc = prevRow[p] + 1 - (j - p - 1) * 2.5;
          if (sc > best) { best = sc; bestP = p; }
        }
      }

      if (bestP >= 0) {
        dp[i][j] = best;
        back[i][j] = bestP;
      }
    }
  }

  let end = -1;
  let bestRaw = NEG;
  for (let j = m - 1; j < n; j++) {
    if (dp[m - 1][j] > bestRaw) { bestRaw = dp[m - 1][j]; end = j; }
  }
  if (end < 0) return null;

  const hits = new Array(m);
  let cur = end;
  for (let i = m - 1; i >= 0; i--) {
    hits[i] = cur;
    cur = back[i][cur];
  }
  const avg = bestRaw / m;
  const spanPenalty = Math.min(35, (hits[m - 1] - hits[0] + 1 - m) * 1.2);
  const score = Math.max(10, Math.min(180, 40 + avg * 8 - spanPenalty));
  return { score, hits };
}

export function switcherFuzzy(query, text) {
  const ts = String(query ?? "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!ts.length) return null;
  const raw = String(text ?? "");
  const hay = raw.toLowerCase();
  if (!hay) return null;
  const { sep, bnd } = analyze(raw, hay);

  let total = 0;
  const hits = [];
  for (const t of ts) {
    const hit = matchSubstring(t, hay, sep, bnd) ?? matchSubsequence(t, hay, sep, bnd);
    if (!hit) return null;
    total += hit.score;
    hits.push(...hit.hits);
  }
  return {
    score: total - hay.length * 0.01,
    hits: [...new Set(hits)].sort((a, b) => a - b),
  };
}
