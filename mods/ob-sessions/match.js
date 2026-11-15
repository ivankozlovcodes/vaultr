// The Sessions tree's filter, pure (no Herdr imports, so test/test_ob_sessions.py runs it under node): the kit's
// fuzzy() (./fuzzy.js, synced from kit/fuzzy.js), kept readable: letters in order, not spread over the whole label.
import { fuzzy } from "./fuzzy.js";

// fuzzy() matches every space-separated term anywhere, in any order, so the spread is checked per term: each term's
// own letters span at most 3 x its length + 2. -> fuzzy()'s { score, hits } or null.
export function matchQ(q, text) {
  const f = fuzzy(q, text);
  if (!f || !f.hits.length) return f;
  const tight = (t) => {
    const g = fuzzy(t, text);
    if (!g || !g.hits.length) return Boolean(g);
    return g.hits[g.hits.length - 1] - g.hits[0] + 1 <= t.length * 3 + 2;
  };
  return String(q).split(/\s+/).filter(Boolean).every(tight) ? f : null;
}
