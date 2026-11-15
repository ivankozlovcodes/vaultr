// ob-outline: which live terminals this panel lists as sub-agent terminals (TERMINALS). Pure: no Herdr or
// kit imports, so test/test_ob_subagents.py runs it under node. The rule mirrors ob-agents' filter.js: a
// terminal some pane shows belongs to the Agents panel, not here. Every other live terminal is listed: a child
// a parent started, and a background one with no parent (an hc run --bg worker, a sub-agent, an agent in a tab
// with no pane). Those without a parent show under "Unattached" in All.

// The terminal addresses that some pane shows. A mod pane has no terminal and places nothing.
export function placedTerminals(panes) {
  const out = new Set();
  for (const p of panes ?? []) if (p && p.terminal) out.add(p.terminal);
  return out;
}

// -> the live, unplaced terminals (terminals() order kept), each address once.
export function listedTerminals(terminals, panes) {
  const placed = placedTerminals(panes);
  const seen = new Set();
  const out = [];
  for (const t of terminals ?? []) {
    if (!t || t.state !== "live" || placed.has(t.address) || seen.has(t.address)) continue;
    seen.add(t.address);
    out.push(t);
  }
  return out;
}
