// ob-graph notes and artifacts: pure, no Herdr or gpui imports (test/test_ob_graph.py runs it under node).
//
// touchShape(touches, opts) turns the files the agents touched (the feed's `touches`: agent key -> [{path, op, at}],
// classified by kit/touches.js) into graph nodes and links. A note is kind "n" (key note:<path>), an artifact kind "a"
// (key art:<artifact id> for a herdr-artifact publication, else file:<path>). Each link is [agentNode, node, "touch", op]:
// the agent that touched it. A note touched by two agents is one node with two links (the shared-note look). Node keys
// come from the path or the artifact id, so they stay the same across refreshes. A remote agent's plain files are
// dropped (their paths are not this computer's); its herdr-artifact publications are kept.
//
// opts: { vault (the vault's full path, or null), home, notes (bool), artifacts (bool), resolve: a function agentKey ->
// the graph's node key for that agent (or null when it is not in the graph), or a plain { agentKey: nodeKey } map }.
// With notes on and no vault, notes are off.

import { classifyAll } from "./touches.js";

const OP_RANK = { read: 0, edit: 1, write: 2, create: 3, publish: 4 };

// The machine an agent key belongs to: a remote terminal address is "<machine>/<id>", a run or sub-agent key is
// "<machine or local>:<id>". null is this computer.
export function machineOfKey(key) {
  if (key.startsWith("term:")) {
    const addr = key.slice(5);
    const i = addr.indexOf("/");
    return i > 0 ? addr.slice(0, i) : null;
  }
  const parts = key.split(":");
  return parts.length >= 3 && parts[1] !== "local" ? parts[1] : null;
}

export function touchShape(touches, opts = {}) {
  const { vault = null, home = null, notes = false, artifacts = false, resolve = null } = opts;
  const wantNotes = Boolean(notes) && Boolean(vault);
  const lookup = typeof resolve === "function" ? resolve : (k) => resolve?.[k] ?? null;
  const nodes = new Map(), links = new Map();
  for (const [agent, rows] of Object.entries(touches ?? {})) {
    const from = lookup(agent);
    if (!from) continue;
    const machine = machineOfKey(agent);
    for (const c of classifyAll({ [agent]: rows }, { root: vault, home, machine })) {
      if (c.kind === "note" ? !wantNotes : !artifacts) continue;
      // A remote agent's plain file: its path is that machine's, not this one's (it would merge with a local file of the
      // same path and open here). Only its publications, keyed by artifact id, are shown.
      if (machine != null && !c.artifact) continue;
      const key = c.kind === "note" ? `note:${c.path}` : c.artifact ? `art:${c.artifact.id}` : `file:${c.path}`;
      if (!nodes.has(key)) nodes.set(key, { key, kind: c.kind === "note" ? "n" : "a", label: c.title, path: c.path, rel: c.rel ?? null, artifact: c.artifact ?? null });
      const lk = `${from}\u0001${key}`;
      const prev = links.get(lk);
      if (!prev || OP_RANK[c.op] > OP_RANK[prev[3]]) links.set(lk, [from, key, "touch", c.op]);
    }
  }
  return { nodes: [...nodes.values()], edges: [...links.values()] };
}
