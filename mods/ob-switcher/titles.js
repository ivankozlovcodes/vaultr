// The session titles a tab holds, for the quick switcher's search: the titles of the agents and terminals in its
// panes (Claude Code's session title, a pi session's name, a terminal's title) and the session names the sub-agent
// feed knows for them. Pure functions (no Herdr or gpui imports, so test/ runs them under node).

// tabOf: Map terminal address -> tab id (the panes that show a terminal). agents: agents(). terminals: terminals().
// terms: the feed's terms, { [address]: { name } }. -> Map tab id -> [title, ...] (trimmed, no repeats).
export function sessionTitles(tabOf, { agents = [], terminals = [], terms = {} } = {}) {
  const out = new Map();
  const note = (address, title) => {
    const tab = tabOf.get(address);
    const text = typeof title === "string" ? title.trim() : "";
    if (tab == null || !text) return;
    const list = out.get(tab) ?? [];
    if (!list.includes(text)) list.push(text);
    out.set(tab, list);
  };
  for (const a of agents ?? []) note(a?.address, a?.title);
  for (const t of terminals ?? []) { note(t?.address, t?.title); note(t?.address, t?.name); }
  for (const [address, info] of Object.entries(terms ?? {})) note(address, info?.name);
  return out;
}

// The best-matching title for `query`, by `match(query, text) -> { score, hits } | null` (the switcher's fuzzy).
// -> { title, score, hits } or null.
export function bestTitle(query, titles, match) {
  let best = null;
  for (const title of titles ?? []) {
    const m = match(query, title);
    if (m && (!best || m.score > best.score)) best = { title, score: m.score, hits: m.hits };
  }
  return best;
}
