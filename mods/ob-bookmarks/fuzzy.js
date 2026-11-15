// Fuzzy matching, one matcher for every mod, as pure functions (no Herdr or kit imports, so test/ runs it under node).
// kit/sync.sh copies it into each mod; kit.js re-exports fuzzy() and matchQuery(). The rules are the ones below.
//
// A query is space-separated terms. Every term must match the text, case-insensitively unless asked. How a term
// matches (transcript_search.py's prefilter follows the same rule; test/fixtures/ob-search/match-cases.json is the
// shared table both are tested against):
// - A strict term has a non-letter (such as - / . _ or a digit) or five letters or more. It matches as a contiguous
//   substring, or, when it has several word chunks ("hd-tr"), as chunks: each chunk's letters occur in order inside
//   one word, the first at the word's start, and each chunk starts at most twice the term's length after the one
//   before. Letters never scatter across unrelated words for a strict term.
// - A short term (letters only, under five) matches as a substring, or as letters in order inside one word, or as
//   letters in order in a tight window (the matched span at most twice the term's length).
// Score tiers, best first: a substring (100 and up; a word start or end adds), word chunks (60 to 90), a tight
// subsequence (under 30). Spans cover the matched letters only, never the separators between chunks.
// Ranking: score first, then recency (a number, larger is newer), then input order.

const LETTER = /\p{L}/u;
const WORD_CH = /[\p{L}\p{N}]/u;
const MAX_SUBSTRING_HITS = 50;

const isLetter = (c) => c !== undefined && LETTER.test(c);
const isWordCh = (c) => c !== undefined && WORD_CH.test(c);

// The words of `hay`: maximal runs of letters and digits, as { s, e } (e exclusive).
function wordsOf(hay) {
  const out = [];
  for (let i = 0; i < hay.length;) {
    if (!isWordCh(hay[i])) { i++; continue; }
    const s = i;
    while (i < hay.length && isWordCh(hay[i])) i++;
    out.push({ s, e: i });
  }
  return out;
}
const wordAt = (words, i) => words.find((w) => i >= w.s && i < w.e) ?? null;
// Strict: five letters or more, or any non-letter.
const isStrict = (t) => t.length >= 5 || [...t].some((c) => !isLetter(c));
// The word chunks of a term: "hd-tr" -> ["hd", "tr"].
const chunksOf = (t) => t.match(/[\p{L}\p{N}]+/gu) ?? [];

// The query's terms, lowercased (the default, case-insensitive form).
export function terms(q) {
  return splitTerms(q).map((t) => t.toLowerCase());
}

function splitTerms(q) {
  return String(q ?? "").split(/\s+/).filter(Boolean);
}

// Every start of `t` as a substring of `hay`, at most MAX_SUBSTRING_HITS.
function substringAt(t, hay) {
  const out = [];
  for (let p = hay.indexOf(t); p >= 0 && out.length < MAX_SUBSTRING_HITS; p = hay.indexOf(t, p + 1)) out.push(p);
  return out;
}

// Letters of `chunk` in order inside word `w`, the first at the word's start. Indexes, or null.
function chunkInWord(chunk, hay, w) {
  if (hay[w.s] !== chunk[0]) return null;
  const idx = [w.s];
  let at = w.s + 1;
  for (const ch of chunk.slice(1)) {
    let i = at;
    while (i < w.e && hay[i] !== ch) i++;
    if (i >= w.e) return null;
    idx.push(i);
    at = i + 1;
  }
  return idx;
}

// Word chunks of a strict term, in order, each in a word after the previous chunk, the gap at most 2 x term length.
// Returns { idxs } or null. Depth-first over the words, so a later word can still be used.
function chunkChain(chunks, hay, words, limit) {
  const step = (k, prevEnd) => {
    if (k === chunks.length) return { idxs: [] };
    for (const w of words) {
      if (prevEnd != null) {
        if (w.s <= prevEnd) continue;
        if (w.s - prevEnd - 1 > limit) break;
      }
      const idx = chunkInWord(chunks[k], hay, w);
      if (!idx) continue;
      const rest = step(k + 1, idx[idx.length - 1]);
      if (rest) return { idxs: [...idx, ...rest.idxs] };
    }
    return null;
  };
  return step(0, null);
}

// Score of matched letters at `idxs` (ascending) for the substring and chunk tiers.
function chunkScore(hay, idxs) {
  let gaps = 0;
  for (let k = 1; k < idxs.length; k++) gaps += Math.max(0, idxs[k] - idxs[k - 1] - 1);
  return Math.max(60, Math.min(90, 90 - gaps * 0.5));
}

// Letters in order inside one word, or inside a window of at most twice the term's length. The greedy match from
// each start is the tightest for that start. Returns { score, idxs } or null.
function tightSubsequence(t, hay, words) {
  let best = null;
  for (let s = 0; s < hay.length; s++) {
    if (hay[s] !== t[0]) continue;
    const idxs = [s];
    let at = s + 1;
    let ok = true;
    for (const ch of t.slice(1)) {
      const i = hay.indexOf(ch, at);
      if (i < 0) { ok = false; break; }
      idxs.push(i);
      at = i + 1;
    }
    if (!ok) continue;
    const span = idxs[idxs.length - 1] - s + 1;
    const w = wordAt(words, s);
    const inOneWord = Boolean(w) && idxs.every((i) => i < w.e);
    if (!inOneWord && span > 2 * t.length) continue;
    const wordStart = !w || w.s === s ? 5 : 0;
    const score = Math.max(1, 20 + wordStart - (span - t.length) * 0.5);
    if (!best || score > best.score) best = { score, idxs };
  }
  return best;
}

// One term against one text (lowercased already, or the same case as the query). Returns { score, idxs } or null.
function matchTerm(t, hay) {
  if (!t) return null;
  const words = wordsOf(hay);
  let best = null;
  for (const p of substringAt(t, hay)) {
    const wordStart = !wordAt(words, p) || wordAt(words, p).s === p ? 20 : 0;
    const w = wordAt(words, p + t.length - 1);
    const wordEnd = w && w.e === p + t.length ? 10 : 0;
    const score = 100 + wordStart + wordEnd;
    if (!best || score > best.score) {
      best = { score, idxs: Array.from({ length: t.length }, (_, k) => p + k) };
    }
  }
  if (best) return best;
  if (isStrict(t)) {
    const chunks = chunksOf(t);
    if (chunks.length < 2) return null;
    const chain = chunkChain(chunks, hay, words, 2 * t.length);
    return chain ? { score: chunkScore(hay, chain.idxs), idxs: chain.idxs } : null;
  }
  return tightSubsequence(t, hay, words);
}

// Matched letter indexes as [start, end) ranges, merged.
function toSpans(idxs) {
  const sorted = [...new Set(idxs)].sort((a, b) => a - b);
  const out = [];
  for (const i of sorted) {
    const last = out[out.length - 1];
    if (last && last[1] === i) last[1] = i + 1;
    else out.push([i, i + 1]);
  }
  return out;
}

// All terms of `q` must match `text`. Returns { score, spans } or null. An empty query matches nothing.
export function matchQuery(q, text, opts = {}) {
  const cs = Boolean(opts.caseSensitive);
  const ts = splitTerms(q).map((t) => (cs ? t : t.toLowerCase()));
  if (!ts.length) return null;
  const hay = cs ? String(text ?? "") : String(text ?? "").toLowerCase();
  let score = 0;
  const idxs = [];
  for (const t of ts) {
    const m = matchTerm(t, hay);
    if (!m) return null;
    score += m.score;
    idxs.push(...m.idxs);
  }
  return { score: score - hay.length * 0.01, spans: toSpans(idxs) };
}

// The items that match, best first: score, then recency (opts.time(item), larger is newer), then input order.
// opts: { text(item), time(item), caseSensitive }. Returns [{ item, score, spans }].
export function rankItems(items, q, opts) {
  const out = [];
  (items ?? []).forEach((item, index) => {
    const m = matchQuery(q, opts.text(item), { caseSensitive: opts.caseSensitive });
    if (m) out.push({ item, score: m.score, spans: m.spans, index, time: Number(opts.time?.(item)) || 0 });
  });
  out.sort((a, b) => (b.score - a.score) || (b.time - a.time) || (a.index - b.index));
  return out.map(({ item, score, spans }) => ({ item, score, spans }));
}

// A window of `width` characters around the first span, with "…" where it was cut. Spans move with it.
// -> { text, spans }
export function snippet(text, spans, width = 60) {
  const s = String(text ?? "");
  if (s.length <= width) return { text: s, spans: spans ?? [] };
  const first = spans?.[0] ?? [0, 1];
  const span = Math.max(1, first[1] - first[0]);
  let from = Math.max(0, first[0] - Math.floor((width - span) / 2));
  let to = Math.min(s.length, from + width);
  from = Math.max(0, to - width);
  const lead = from > 0 ? "…" : "";
  const tail = to < s.length ? "…" : "";
  const off = from - lead.length;
  const shifted = (spans ?? [])
    .filter(([a, b]) => a >= from && b <= to)
    .map(([a, b]) => [a - off, b - off]);
  return { text: lead + s.slice(from, to) + tail, spans: shifted };
}

// The shape every mod's callers use (kit.js re-exports it): { score, hits } or null, where hits are the matched
// letter indexes in `text` (highlight() takes them). An empty query matches with score 0 and no hits.
export function fuzzy(q, text) {
  if (!splitTerms(q).length) return { score: 0, hits: [] };
  const m = matchQuery(q, text);
  if (!m) return null;
  return { score: m.score, hits: m.spans.flatMap(([a, b]) => Array.from({ length: b - a }, (_, k) => a + k)) };
}
