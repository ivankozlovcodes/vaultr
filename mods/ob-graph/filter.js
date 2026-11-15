// ob-graph views: pure, no Herdr or gpui imports (test/test_ob_graph.py runs it under node).
//
// A graph is { nodes: [{key, kind, parent?, status?, live?, foreground?, feedAt?}], edges: [[a, b, kind]] }. kind: m
// (machine), s (space), p (pane), r (run), c (Claude agent), h (hc child). Edge kinds: contain, link, sibling (the
// invisible spring between the panes of one tab: Local counts it as a neighbour, Active only keeps it between kept nodes).
// foreground: a pane whose terminal is a main agent placed in a tab (kit mainAgents + placedTerminals). Active is one rule (kit/agents.js activityOf): a foreground
// pane by its agent's status (working, blocked), a subagent by its live flag and a fresh feed. live alone does not make a pane active.
// Notes and artifacts (kinds n and a, touch_shape.js) are kept by Active only when a kept agent touches them.
// main.js builds the whole model, finished subagents included; the views here decide what is shown.
//
// Local (localGraph): breadth-first from the focus over links both ways, to `depth` links. A pane's subagents are part of
// its hop: they cost no depth, so a tab's agent and all its subagents are one hop away. A machine is reached but never
// walked through, and the focus's parent chain up to its machine is always kept.
//
// What a view shows is shownGraph: Local anchors "Active only" on the focus, Global does not, so a pane gaining focus never
// reshuffles Global.
//
// Active only (filterGraph, one switch per view, see activeState): on keeps each active foreground agent pane, every active
// subagent that hangs (directly or through another kept subagent) off a kept agent, and the machines and spaces above them. An anchor (the focus) and its ancestors are always kept. Off keeps everything, finished subagents too.

import { activityOf } from "./agents.js";

const SUBAGENT = new Set(["r", "c", "h"]);
const TOUCHED = new Set(["n", "a"]);      // a note (n) or an artifact (a): see touch_shape.js

function adjacency(edges) {
  const adj = new Map();
  for (const [a, b] of edges) {
    (adj.get(a) ?? adj.set(a, []).get(a)).push(b);
    (adj.get(b) ?? adj.set(b, []).get(b)).push(a);
  }
  return adj;
}

// The nodes and edges among `keep`, in the graph's order.
function restrict(graph, keep) {
  return {
    nodes: graph.nodes.filter((n) => keep.has(n.key)),
    edges: graph.edges.filter(([a, b]) => keep.has(a) && keep.has(b)),
  };
}

// The subagents of each pane (they hang off a pane, or off a machine when orphaned).
function subagentsOf(graph) {
  const kids = new Map();
  for (const n of graph.nodes) {
    if (!SUBAGENT.has(n.kind) || !n.parent) continue;
    (kids.get(n.parent) ?? kids.set(n.parent, []).get(n.parent)).push(n.key);
  }
  return kids;
}

// Local view: the focus and everything within `depth` links of it. A pane's subagents come with the pane at no extra
// depth. A missing focus gives an empty graph.
export function localGraph(graph, focus, depth) {
  const byKey = new Map(graph.nodes.map((n) => [n.key, n]));
  if (!focus || !byKey.has(focus)) return { nodes: [], edges: [], focus: null };
  const adj = adjacency(graph.edges);
  const kids = subagentsOf(graph);
  const seen = new Set();
  const add = (k) => {
    seen.add(k);
    if (byKey.get(k)?.kind === "p") for (const s of kids.get(k) ?? []) seen.add(s);
  };
  add(focus);
  let front = [focus];
  for (let d = 0; d < depth && front.length; d++) {
    const next = [];
    for (const k of front) {
      // A machine is kept but not walked through: it would bring in every space it holds.
      for (const o of adj.get(k) ?? []) if (!seen.has(o)) { add(o); if (byKey.get(o)?.kind !== "m") next.push(o); }
    }
    front = next;
  }
  // The focus's parent chain up to its machine, always: the local graph says where it is.
  const up = new Set([focus]);
  for (let k = byKey.get(focus).parent; k && byKey.has(k) && !up.has(k); k = byKey.get(k).parent) { up.add(k); seen.add(k); }
  return { ...restrict(graph, seen), focus };
}

// "Active only": pure. The anchor (the focus) and its ancestors always stay, so a focus that is not an active agent still
// anchors its view.
export function activeOnly(graph, anchor = null, now = Date.now()) {
  const byKey = new Map(graph.nodes.map((n) => [n.key, n]));
  const keep = new Set();
  for (const n of graph.nodes) if (n.kind === "p" && n.foreground && activityOf(n, now)) keep.add(n.key);
  if (anchor && byKey.has(anchor)) keep.add(anchor);
  // Live subagents attached to a kept node, then to those, until nothing more attaches.
  for (let grew = true; grew;) {
    grew = false;
    for (const n of graph.nodes) {
      if (SUBAGENT.has(n.kind) && activityOf(n, now) && !keep.has(n.key) && keep.has(n.parent)) { keep.add(n.key); grew = true; }
    }
  }
  // Notes and artifacts: kept when a kept agent touches them (their links to other agents go with the restriction).
  const adj = adjacency(graph.edges);
  for (const n of graph.nodes) {
    if (TOUCHED.has(n.kind) && (adj.get(n.key) ?? []).some((o) => keep.has(o))) keep.add(n.key);
  }
  // The machine and space of every kept node (and of the anchor).
  for (const k of [...keep]) {
    for (let p = byKey.get(k)?.parent; p && byKey.has(p) && !keep.has(p); p = byKey.get(p).parent) keep.add(p);
  }
  return restrict(graph, keep);
}

// The filter as the toolbar sees it: off returns the graph unchanged (finished subagents included).
export function filterGraph(graph, on, anchor = null, now = Date.now()) {
  return on ? activeOnly(graph, anchor, now) : graph;
}

// What a view shows: Local is the focus's neighbourhood (localGraph), Global is everything; then "Active only" over it.
// Only Local is built around the focus, so only Local anchors the filter on it. In Global the filter shows what is active,
// whichever pane has focus: clicking something that opens a pane moves focus and must not reshuffle the graph or tint a
// different node. `focus` of the result is the node to draw in the accent colour: Local's focus when it is drawn, else null
// (Global has none).
export function shownGraph(lists, { mode, focus = null, depth = 1, active = true, now = Date.now() }) {
  const local = mode === "local";
  const base = local ? localGraph(lists, focus, depth) : lists;
  const shown = filterGraph(base, active, local ? focus : null, now);
  const drawn = local && focus && shown.nodes.some((n) => n.key === focus) ? focus : null;
  return { nodes: shown.nodes, edges: shown.edges, focus: drawn };
}

// The words of the empty graph. In Global, Active only with nothing active is the one case where the filter, not the
// absence of machines and agents, is what leaves the view empty: say so, and what to do.
export function emptyCopy(mode, active) {
  if (mode === "local") return { title: "No session focused", body: "The local graph follows the focused session. Switch to Global to see every machine." };
  if (active) return { title: "Nothing is active", body: "Active only is on and no agent is working. Switch it off to see every machine, space and agent." };
  return { title: "Nothing to draw", body: "Machines, spaces, panes and agents appear here." };
}

// The Active only state per view: { local: bool, global: bool }, on by default. A view with no saved value takes the old
// "show finished sub-agents" setting (legacy.finished === true means the finished ones were visible, so Active only is off).
export function activeState(saved, legacy) {
  const out = {};
  for (const view of ["local", "global"]) {
    if (saved && typeof saved[view] === "boolean") out[view] = saved[view];
    else out[view] = legacy?.finished === true ? false : true;
  }
  return out;
}

export function activeOf(state, view) {
  return state?.[view] !== false;
}

// A copy of the state with one view's switch set; the other view is untouched.
export function setActive(state, view, on) {
  return { ...state, [view]: Boolean(on) };
}

// The Notes and Artifacts switches: { local: { notes, artifacts }, global: { ... } }, both off by default. A saved value
// that is not a boolean is off. Kept per view, like Active only.
export const TOUCH_SWITCHES = ["notes", "artifacts"];
export function touchState(saved) {
  const out = {};
  for (const view of ["local", "global"]) {
    out[view] = {};
    for (const w of TOUCH_SWITCHES) out[view][w] = saved?.[view]?.[w] === true;
  }
  return out;
}

export function touchOn(state, view, which) {
  return state?.[view]?.[which] === true;
}

// A copy of the state with one view's switch set; the other switches are untouched.
export function setTouch(state, view, which, on) {
  const base = touchState(state);
  base[view][which] = Boolean(on);
  return base;
}
