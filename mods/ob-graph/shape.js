// ob-graph tab shape: pure, no Herdr or gpui imports (test/test_ob_graph.py runs it under node).
//
// A tab has no node of its own. Its panes are nodes (key p:<pane>), each labelled by the caller (kit paneLabel), and the
// panes of one tab are joined in a chain by sibling links. A sibling link is a spring the simulation pulls with and
// nothing draws, so a tab reads as a small cluster (like a folder in Obsidian's graph). A pane keeps its key whatever its
// tab holds, so adding or closing a pane does not move the pane that stays.
//
// paneShape(tabId, panes): panes = [{ pane, label }] in order. Returns { nodes: [{ key, kind: "p", label, pane }],
// edges: [[a, b, "sibling"]] }. Two panes with the same label get a number each ("Claude Code 1", "Claude Code 2").

export function paneLabels(labels) {
  const base = labels.map((l) => (typeof l === "string" && l.trim() ? l.trim() : "Terminal"));
  const count = new Map();
  for (const b of base) count.set(b, (count.get(b) ?? 0) + 1);
  return base.map((b, i) => (count.get(b) > 1 ? `${b} ${i + 1}` : b));
}

export function paneShape(tabId, panes) {
  const list = panes ?? [];
  const labels = paneLabels(list.map((p) => p.label));
  const nodes = list.map((p, i) => ({ key: `p:${p.pane}`, kind: "p", label: labels[i], pane: p.pane }));
  const edges = [];
  for (let i = 1; i < list.length; i++) edges.push([`p:${list[i - 1].pane}`, `p:${list[i].pane}`, "sibling"]);
  return { tab: tabId ?? null, nodes, edges };
}

// placeSubs(subs, paneOf): where each sub-agent hangs. subs = [{ key, parentAddr, machine, ... }], paneOf = Map(terminal
// address -> pane key). The parent is the pane of parentAddr, else the hc child at that address (h:<address>, itself
// in subs, in any order: nested hc children), else the machine (m:<machine or local>). Returns the subs in order, each
// with parent and edge ("link" to a session, "contain" to a machine). A cycle of hc children falls back to the machine.
export function placeSubs(subs, paneOf) {
  const list = subs ?? [];
  const keys = new Set(list.map((s) => s.key));
  const at = new Map();                                    // key -> parent key, or null for the machine
  let pending = list;
  for (let grew = true; grew && pending.length;) {
    grew = false;
    const next = [];
    for (const s of pending) {
      const pane = s.parentAddr ? paneOf.get(s.parentAddr) : null;
      const hk = s.parentAddr ? `h:${s.parentAddr}` : null;
      const viaHc = hk && hk !== s.key && keys.has(hk);
      if (pane) at.set(s.key, pane);
      else if (viaHc && at.has(hk)) at.set(s.key, hk);
      else if (viaHc) { next.push(s); continue; }
      else at.set(s.key, null);
      grew = true;
    }
    pending = next;
  }
  return list.map((s) => {
    const p = at.get(s.key) ?? null;
    return { ...s, parent: p ?? `m:${s.machine ?? "local"}`, edge: p ? "link" : "contain" };
  });
}
