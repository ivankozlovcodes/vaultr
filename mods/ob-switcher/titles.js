// The session titles a tab holds, for the quick switcher's search: the titles of the agents and terminals in its
// panes (agent session titles, terminal titles) and the session names the provider facade knows for them.
// Pure functions (no Herdr or gpui imports, so test/ runs them under node).

import { cleanTitle } from "./names.js";

// tabOf: Map terminal address -> tab id (the panes that show a terminal). agents: agents(). terminals: terminals().
// sessions: provider.sessions() rows [{ address, title }]. panes: panes() (optional, for manual pane names).
// -> Map tab id -> [title, ...] (trimmed, no repeats).
export function sessionTitles(tabOf, { agents = [], terminals = [], sessions = [], panes = [] } = {}) {
  const out = new Map();
  const noteTab = (tab, title) => {
    const text = cleanTitle(title);
    if (tab == null || !text) return;
    const list = out.get(tab) ?? [];
    if (!list.includes(text)) list.push(text);
    out.set(tab, list);
  };
  const note = (address, title) => noteTab(tabOf.get(address), title);
  for (const p of panes ?? []) noteTab(p?.tab, p?.name);
  for (const a of agents ?? []) note(a?.address, a?.title);
  for (const t of terminals ?? []) { note(t?.address, t?.title); note(t?.address, t?.name); }
  for (const s of sessions ?? []) note(s?.address, s?.title ?? s?.name);
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
