// Portions derived from the Herdr app (Apache-2.0) and modified for Vaultr; see NOTICE and LICENSE-herdr.
// Command mode of the quick switcher (a query starting with ">"): Vaultr's own commands and Herdr's app commands
// as one list, fuzzy-matched together. Pure functions, no Herdr or gpui imports, so test/test_ob_switcher.py runs
// them under node. The switcher passes its fuzzy matcher in as `match(query, text) -> { score, hits } | null`.
//
// Sources, both live: Vaultr's rows come from the switcher's own model; Herdr's from commands() (every app command
// and its arguments) and keys() (the key bindings, for the hints).

import { allowsRow, sinkDisabled } from "./modes.js";

export const PALETTE_ROUTE = "app.palette";
export const PALETTE_LABEL = "Herdr command palette…";

// The query after ">", trimmed; null when the query is not in command mode.
export function commandQuery(query) {
  const q = String(query ?? "").trim();
  return q.startsWith(">") ? q.slice(1).trim() : null;
}

// The chord bound to an action, preferring the layout's section, then global, then any section.
export function chordFor(keys, action, layout = "vaultr") {
  const hits = (keys ?? []).filter((k) => k && k.action === action && typeof k.keys === "string");
  if (!hits.length) return null;
  const pick = hits.find((k) => k.section === `layout:${layout}`) ?? hits.find((k) => k.section === "global") ?? hits[0];
  return pick.keys;
}

// Herdr's commands as rows. The palette entry replaces Herdr's own app.palette row, and a command that needs
// arguments is listed but disabled (the hint names them): the switcher runs a command by name only.
export function herdrItems(herdr, keys, layout = "vaultr") {
  const out = [];
  out.push({
    key: `cmd:${PALETTE_ROUTE}`, kind: "command", source: "herdr-palette", route: PALETTE_ROUTE,
    label: PALETTE_LABEL, context: "Herdr's own palette: every command", words: "herdr command palette app palette",
  });
  for (const c of herdr ?? []) {
    if (!c || typeof c.name !== "string" || c.name === PALETTE_ROUTE) continue;
    const required = (c.args ?? []).filter((a) => a && a.required).map((a) => a.name);
    const about = String(c.about ?? "");
    out.push({
      key: `cmd:${c.name}`, kind: "command", source: "herdr", route: c.name, label: c.name,
      context: about.length > 100 ? `${about.slice(0, 99)}…` : about, words: `${c.name} ${about}`,
      chord: chordFor(keys, c.name, layout) ?? undefined,
      disabled: required.length > 0, hint: required.length ? `needs: ${required.join(", ")}` : undefined,
    });
  }
  return out;
}

// Vaultr's commands as rows: each carries its route (what runs) and the chord bound to it. Sidebar views are not
// commands (Views is its own mode), so their rows are left out.
export function vaultrItems(vaultr, keys, layout = "vaultr") {
  return (vaultr ?? []).filter((v) => v && typeof v.route === "string" && allowsRow("commands", v)).map((v) => ({
    ...v, key: `cmd:${v.route}`, kind: "command", source: "vaultr", chord: chordFor(keys, v.route, layout) ?? undefined,
  }));
}

// The ranked list: [{ item, hits, score }]. Vaultr's rows first, then Herdr's; a route listed by both is kept once,
// as Vaultr's. With a query, rows are scored on their label, then on label + context + words (minus 4). Rows that
// need arguments come after every runnable row.
export function commandRows({ vaultr = [], herdr = [], keys = [], query = "", layout = "vaultr", match = substring } = {}) {
  const seen = new Set();
  const all = [];
  for (const it of vaultrItems(vaultr, keys, layout)) { if (!seen.has(it.route)) { seen.add(it.route); all.push(it); } }
  for (const it of herdrItems(herdr, keys, layout)) { if (!seen.has(it.route)) { seen.add(it.route); all.push(it); } }
  const q = String(query ?? "").trim();
  if (!q) return sinkDisabled(all.map((item) => ({ item, hits: [], score: 1 })));
  const scored = [];
  for (const item of all) {
    const title = match(q, item.label);
    const more = title ? null : match(q, `${item.label} ${item.context ?? ""} ${item.words ?? ""}`);
    const best = title ?? (more && { score: more.score - 4, hits: [] });
    if (best) scored.push({ item, hits: best.hits ?? [], score: best.score });
  }
  scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
  return sinkDisabled(scored);
}

// Stand-in matcher (case-insensitive substring) for callers without the switcher's fuzzy().
function substring(q, text) {
  const i = String(text ?? "").toLowerCase().indexOf(String(q).toLowerCase());
  return i < 0 ? null : { score: 10 - i / 100, hits: [] };
}
