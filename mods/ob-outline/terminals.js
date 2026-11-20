// ob-outline: which live terminals this panel lists as sub-agent terminals (TERMINALS). Pure: no Herdr or
// kit imports, so test/test_ob_outline.py runs it under node. The rule mirrors ob-agents' filter.js: a
// terminal some pane shows belongs to the Agents panel, not here. Every other live terminal is listed: a child
// a parent started, and a background one with no parent (an hc run --bg child, a sub-agent, an agent in a tab
// with no pane). Those without a parent show under "Unattached" in All.

// Parent terminal address of `t` (ignoring self-loops).
export function parentAddr(t) {
  return t?.parent && t.parent !== t.address ? t.parent : null;
}

// The terminal addresses that some pane shows. A mod pane has no terminal and places nothing.
export function placedTerminals(panes) {
  const out = new Set();
  for (const p of panes ?? []) if (p && p.terminal) out.add(p.terminal);
  return out;
}

// -> the live, unplaced terminals (terminals() order kept), each address once, with normalized `parent`.
export function listedTerminals(terminals, panes) {
  const placed = placedTerminals(panes);
  const seen = new Set();
  const out = [];
  for (const t of terminals ?? []) {
    if (!t || t.state !== "live" || placed.has(t.address) || seen.has(t.address)) continue;
    seen.add(t.address);
    const p = parentAddr(t);
    out.push(p != null ? (t.parent === p ? t : { ...t, parent: p }) : (t.parent != null ? { ...t, parent: null } : t));
  }
  return out;
}

// Map(address -> parent address) across all terminals (live or exited),
// so tree.js can roll nested items up through exited intermediate terminals.
export function parentMap(terminals) {
  const out = new Map();
  for (const t of terminals ?? []) {
    if (!t?.address) continue;
    const p = parentAddr(t);
    if (p) out.set(t.address, p);
  }
  return out;
}
