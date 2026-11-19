// ob-graph simulation: Quartz v4's graph model (jackyzha0/quartz, MIT, commit d25a6eab: components/Graph.tsx and
// components/scripts/graph.inline.ts) on the vendored d3-force 3.0.0 (vendor/, ISC). Pure: no Herdr or kit imports,
// so test/test_ob_graph.py runs it under node with every timer removed (Herdr has none; the mod ticks the simulation).
//
// A graph is { nodes: [{key, kind, parent?}], edges: [[a, b, "contain" | "link" | "sibling"]] }. A "sibling" link is the
// invisible spring between the panes of one tab: a shorter link distance, not drawn, not counted in a node's degree or
// size, and not followed by a hover. sync() takes it. Node objects
// are kept per key, so a refresh with the same nodes keeps every x/y/vx/vy; a new node starts one link distance from
// its parent; a structural change reheats gently (alpha to 0.2, never 1). tick() advances while the simulation is
// active (alpha at or above alphaMin, or dragging); settle() runs it out. The view (fitView, zoomAt, panTo) maps world
// coordinates to the panel.

import {
  forceSimulation, forceManyBody, forceCenter, forceLink, forceCollide, forceRadial, forceX, forceY,
} from "./vendor/d3-force/src/index.js";

// Quartz's defaults. graph.inline.ts reads them as data-cfg from Graph.tsx: local = the page's graph, global = all of it.
export const QUARTZ = {
  local: {
    drag: true, zoom: true, depth: 1, scale: 1.1, repelForce: 0.5, centerForce: 0.3, linkDistance: 30,
    fontSize: 0.6, opacityScale: 1, showTags: true, removeTags: [], focusOnHover: false, enableRadial: false,
  },
  global: {
    drag: true, zoom: true, depth: -1, scale: 0.9, repelForce: 0.5, centerForce: 0.2, linkDistance: 30,
    fontSize: 0.6, opacityScale: 1, showTags: true, removeTags: [], focusOnHover: true, enableRadial: true,
  },
};
export const SCALE_EXTENT = [0.25, 4];                 // d3.zoom().scaleExtent in graph.inline.ts
export const FIT_MAX_SCALE = 1.6;
export const FIT_PAD = { x: 44, top: 36, bottom: 30 };  // room for the toolbar and the footer
const KEEP = 600;                                        // remembered positions of nodes that left
const REHEAT = 0.2;                                      // alpha after a structural change (a gentle reheat)
// Damping. d3's defaults (velocityDecay 0.4, alphaDecay 0.0228) and Quartz's drag heat (alphaTarget 1) leave the graph
// floaty: it keeps drifting for about five seconds, and dragging one node swings the rest. Heavier damping, a faster
// cool-down and a cooler drag keep the nodes where they are put: neighbours of a dragged node move about 40% less (measured on the test graph).
const VELOCITY_DECAY = 0.8;                             // share of a node's speed lost each tick
const ALPHA_DECAY = 0.06;                                // alpha 1 reaches alphaMin in about 115 ticks (d3: 300)
const DRAG_HEAT = 0.2;                                   // alphaTarget while a node is dragged (Quartz: 1)
const COLLIDE_ITERATIONS = 3;
const SIBLING_FACTOR = 0.5;                              // a sibling spring is half the link distance
// Machines and spaces push each other less than panes do (charge -40 x repelForce against -100), and the push
// stops at 250 world units. Concentric rings radiate outward from the origin (focus in Local, active machine or root
// hub in Global), with gentle sector springs pulling each node toward its angular slot.
const BROAD_CHARGE_FACTOR = 0.4;                         // machines and spaces: -40 x repelForce
const MAX_CHARGE_DISTANCE = 250;                         // the charge reaches no further than this (world units, zoom 1)
const HUB_RADIUS = 26;                                   // inner hub ring for multi-root Global graphs and extra Local roots
const ISO_RADIUS = 28;                                   // inner tuck radius for isolated roots alongside one active root
const RING_STRENGTH = 0.14;                              // radial pull toward each node's concentric depth ring
const SECTOR_STRENGTH = 0.03;                            // angular pull toward each node's subtree wedge target
const ANCHOR_STRENGTH = 0.65;                            // center anchor pull for rRing === 0 roots/focus
const RING_STEP_FACTOR = 1.45;                           // ring spacing as a multiple of linkDistance

// Quartz: 2 + sqrt(number of links) (graph.inline.ts 208-213).
// Machines and spaces have a fixed size (round frame dots): what hangs off them does not grow them.
const FRAME_RADIUS = { m: 5, s: 4.5 };
// Every other node grows with the nodes that reference it: its links minus the one to its parent, so a leaf is 3 and a
// session with sub-agents, or a note several agents touched, is clearly bigger (Quartz: 2 + sqrt(degree), which barely
// moved). Capped, so a busy node does not swallow its neighbours.
const BASE_RADIUS = 3, RADIUS_SLOPE = 1.8, MAX_RADIUS = 11;
export const radiusOf = (degree, kind) => FRAME_RADIUS[kind]
  ?? Math.min(MAX_RADIUS, BASE_RADIUS + RADIUS_SLOPE * Math.sqrt(Math.max(0, degree - 1)));

// Quartz: labels fade in with zoom (graph.inline.ts 513-514): alpha = max((k * opacityScale - 1) / 3.75, 0), capped at 1.
export function labelOpacity(k, opacityScale = 1) {
  return Math.min(1, Math.max((k * opacityScale - 1) / 3.75, 0));
}

// A label's font size and box (main.js draws it under the node). Size: 9 px at the Quartz scale, clamped 8..13 px.
// The box is taller than the line (1.4 x size), and the line is 1.4 x size, so no glyph is clipped at any zoom.
export function labelLayout(k, scale) {
  const size = Math.max(8, Math.min(13, (9 * k) / scale));
  return { size, lineHeight: size * 1.4, height: Math.ceil(size * 1.5) };
}

// Halo for active agents. A working agent pulses (alpha 0.15 to 0.35 over 1.6 s, ease in-out); a blocked one ("needs
// you") has a steady halo at 0.25; idle and finished agents have none. state is "working" | "blocked" | anything else.
export const HALO_MIN = 0.15, HALO_MAX = 0.35, HALO_STEADY = 0.25, HALO_PERIOD_MS = 1600;
export const PULSE_FPS = 15;
export const FRAME_MS = 16;                 // the frame rate while the graph moves (60 fps)
export const LINK_REST_ALPHA = 0.35, LINK_ACTIVE_ALPHA = 0.6;
// A link from an agent to a note or artifact it touched: a read is faint, a change (edit, write, create, publish) normal.
export const TOUCH_READ_ALPHA = 0.18, TOUCH_CHANGE_ALPHA = 0.45;
export function touchAlpha(op) {
  return op === "read" ? TOUCH_READ_ALPHA : TOUCH_CHANGE_ALPHA;
}

export function haloKind(n) {
  if (n?.state === "working") return "pulse";
  if (n?.state === "blocked") return "steady";
  return null;
}

// The pulse: a raised cosine (ease in-out) between HALO_MIN and HALO_MAX, one period per HALO_PERIOD_MS.
export function haloAlpha(t) {
  const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * t) / HALO_PERIOD_MS);
  return HALO_MIN + (HALO_MAX - HALO_MIN) * w;
}

// The halo alpha of a node t ms into the pulse, or null when it has none.
export function haloFor(n, t) {
  const k = haloKind(n);
  if (k === "pulse") return haloAlpha(t);
  if (k === "steady") return HALO_STEADY;
  return null;
}

// What is drawn: the halo times the node's own alpha (its hover dimming), or null when there is no halo.
export function haloDrawAlpha(n, t, nodeAlpha) {
  const a = haloFor(n, t);
  return a == null ? null : a * nodeAlpha;
}

// A link into an active agent from its parent is stronger than the rest.
export function linkRestAlpha(touchesActive) {
  return touchesActive ? LINK_ACTIVE_ALPHA : LINK_REST_ALPHA;
}

// True when any visible node is working (so the halo pulses).
export function anyPulsing(nodes) {
  return nodes.some((n) => haloKind(n) === "pulse");
}

// The frame interval the loop should run at, or null when nothing needs frames. Motion (the simulation still moving, a
// drag, a hover fade) runs at FRAME_MS; a pulse alone runs at PULSE_FPS.
export function frameIntervalMs(sim, { fading = false, dragging = false, pulsing = false } = {}) {
  if (fading || dragging || isActive(sim)) return FRAME_MS;
  if (pulsing) return Math.round(1000 / PULSE_FPS);
  return null;
}

// Hover (graph.inline.ts 327-329, 287-296): with a node hovered, its neighbourhood stays at 1 and the rest go to 0.2.
export const DIM_ALPHA = 0.2;
export function hoverAlpha(inNeighbourhood, hovering) {
  return hovering && !inNeighbourhood ? DIM_ALPHA : 1;
}

// Hover fades: dim over DIM_MS, restore over RESTORE_MS, ease-out. animateAlpha gives the alpha t ms into a fade.
export const DIM_MS = 100, RESTORE_MS = 200;
export const fadeMs = (from, to) => (to < from ? DIM_MS : RESTORE_MS);
export function animateAlpha(from, to, t, ms = fadeMs(from, to)) {
  const p = Math.min(1, Math.max(0, t / ms));
  const e = 1 - (1 - p) * (1 - p) * (1 - p);
  return from + (to - from) * e;
}

// The force parameters a config asks for (graph.inline.ts 169-175), with concentric ring and sector springs.
export function forceSettings(cfg, _W, _H) {
  return {
    charge: -100 * cfg.repelForce,
    broadCharge: -100 * cfg.repelForce * BROAD_CHARGE_FACTOR,
    maxChargeDistance: MAX_CHARGE_DISTANCE,
    center: cfg.centerForce,
    linkDistance: cfg.linkDistance,
    collideIterations: COLLIDE_ITERATIONS,
    ringStrength: RING_STRENGTH,
    sectorStrength: SECTOR_STRENGTH,
  };
}

// FNV-1a, then murmur3's fmix32: FNV alone leaves keys that differ in the last character (p:1, p:2) a degree apart.
export function hash01(s) {
  let h = 2166136261;
  for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967295;
}

export function createSim() {
  // d3-force's constructor would start d3-timer, which needs setTimeout; the stepper is inert (see vendor/d3-force).
  return { d3: forceSimulation([]).velocityDecay(VELOCITY_DECAY).alphaDecay(ALPHA_DECAY), pos: new Map(), sig: null, settings: null, dragKey: null };
}

// Undirected neighbours of every key.
function adjacency(edges) {
  const adj = new Map();
  for (const [a, b] of edges) {
    (adj.get(a) ?? adj.set(a, []).get(a)).push(b);
    (adj.get(b) ?? adj.set(b, []).get(b)).push(a);
  }
  return adj;
}

// Quartz's hover (graph.inline.ts 219-247): the node and every node one link away.
export function hoverSet(edges, key) {
  const set = new Set([key]);
  for (const [a, b, kind] of edges) {
    if (kind === "sibling") continue;      // an invisible spring is not a hover target
    if (a === key) set.add(b);
    if (b === key) set.add(a);
  }
  return set;
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// Concentric radial layout targets: Map(key -> { x, y, rRing, angle }).
// Local mode anchors `focus` at (0, 0) and spreads non-sibling BFS hops outward; Global mode anchors a single active
// root at (0, 0) (tucking isolated roots onto ISO_RADIUS) or places multiple roots on HUB_RADIUS. Deterministic across
// node and edge reordering.
export function radialTargets(list, edges, { focus = null, linkDistance = 30 } = {}) {
  const seen = new Map();
  for (const n of list ?? []) if (!seen.has(n.key)) seen.set(n.key, n);
  const out = new Map();
  if (!seen.size) return out;

  const nonSibling = (edges ?? []).filter(([a, b, k]) => k !== "sibling" && seen.has(a) && seen.has(b));
  const adjSet = new Map();
  for (const k of seen.keys()) adjSet.set(k, new Set());
  for (const [a, b] of nonSibling) {
    if (a === b) continue;
    adjSet.get(a).add(b);
    adjSet.get(b).add(a);
  }
  const adj = new Map();
  for (const [k, s] of adjSet) adj.set(k, [...s].sort(cmp));

  const kids = new Map();
  const addChild = (p, c) => {
    let cs = kids.get(p);
    if (!cs) { cs = []; kids.set(p, cs); }
    cs.push(c);
  };

  const ringStep = linkDistance * RING_STEP_FACTOR;
  const weights = new Map();
  const wOf = (k) => {
    if (weights.has(k)) return weights.get(k);
    const cs = kids.get(k);
    if (!cs || !cs.length) { weights.set(k, 1); return 1; }
    let w = 0;
    for (const c of cs) w += wOf(c);
    w = Math.max(1, w);
    weights.set(k, w);
    return w;
  };

  const place = (k, a0, a1, r) => {
    const a = (a0 + a1) / 2;
    out.set(k, {
      x: r === 0 ? 0 : Math.cos(a) * r,
      y: r === 0 ? 0 : Math.sin(a) * r,
      rRing: r,
      angle: r === 0 ? 0 : a,
    });
    const cs = kids.get(k);
    if (!cs || !cs.length) return;
    const total = cs.reduce((s, c) => s + wOf(c), 0) || 1;
    const nextR = r + ringStep;
    let cur = a0;
    for (const c of cs) {
      const span = ((a1 - a0) * wOf(c)) / total;
      place(c, cur, cur + span, nextR);
      cur += span;
    }
  };

  const sortedKeys = [...seen.keys()].sort(cmp);
  if (focus && seen.has(focus)) {
    const visited = new Set();
    const bfs = (root) => {
      visited.add(root);
      const q = [root];
      for (let head = 0; head < q.length; head++) {
        const u = q[head];
        for (const v of adj.get(u) ?? []) {
          if (visited.has(v)) continue;
          visited.add(v);
          addChild(u, v);
          q.push(v);
        }
      }
    };
    bfs(focus);
    const extraRoots = [];
    for (const k of sortedKeys) {
      if (!visited.has(k)) {
        extraRoots.push(k);
        bfs(k);
      }
    }
    place(focus, -Math.PI / 2, 1.5 * Math.PI, 0);
    if (extraRoots.length) {
      const total = extraRoots.reduce((s, k) => s + wOf(k), 0) || 1;
      let cur = -Math.PI / 2;
      for (const k of extraRoots) {
        const span = (2 * Math.PI * wOf(k)) / total;
        place(k, cur, cur + span, HUB_RADIUS);
        cur += span;
      }
    }
    return out;
  }

  const parentOf = new Map();
  for (const k of sortedKeys) {
    const n = seen.get(k);
    let p = null;
    if (n.parent && seen.has(n.parent) && n.parent !== k) {
      p = n.parent;
    } else if (n.kind === "n" || n.kind === "a") {
      const nbrs = adj.get(k) ?? [];
      p = nbrs.find((v) => {
        const vk = seen.get(v)?.kind;
        return vk !== "n" && vk !== "a";
      }) ?? nbrs[0] ?? null;
    }
    if (p && p !== k) parentOf.set(k, p);
  }
  const state = new Map();
  for (const k of sortedKeys) {
    if (state.get(k) === 2) continue;
    const path = [];
    const inPath = new Set();
    let cur = k;
    while (cur && state.get(cur) !== 2) {
      if (inPath.has(cur)) {
        parentOf.delete(cur);
        break;
      }
      inPath.add(cur);
      path.push(cur);
      cur = parentOf.get(cur) ?? null;
    }
    for (const node of path) state.set(node, 2);
  }

  const roots = [];
  for (const k of sortedKeys) {
    const p = parentOf.get(k);
    if (p) addChild(p, k);
    else roots.push(k);
  }
  const connRoots = roots.filter((k) => (kids.get(k)?.length ?? 0) > 0);
  const isoRoots = roots.filter((k) => (kids.get(k)?.length ?? 0) === 0);

  if (connRoots.length === 0) {
    if (isoRoots.length === 1) {
      place(isoRoots[0], -Math.PI / 2, 1.5 * Math.PI, 0);
    } else if (isoRoots.length > 1) {
      const step = (2 * Math.PI) / isoRoots.length;
      for (let i = 0; i < isoRoots.length; i++) {
        const a0 = -Math.PI / 2 + i * step;
        place(isoRoots[i], a0, a0 + step, HUB_RADIUS);
      }
    }
  } else if (connRoots.length === 1 && isoRoots.length === 0) {
    place(connRoots[0], -Math.PI / 2, 1.5 * Math.PI, 0);
  } else if (connRoots.length === 1 && isoRoots.length > 0) {
    place(connRoots[0], -Math.PI / 2, 1.5 * Math.PI, 0);
    for (let i = 0; i < isoRoots.length; i++) {
      const a = Math.PI / 4 + (2 * Math.PI * i) / isoRoots.length;
      place(isoRoots[i], a, a, ISO_RADIUS);
    }
  } else {
    const ordered = [...connRoots, ...isoRoots];
    const total = ordered.reduce((s, k) => s + wOf(k), 0) || 1;
    let cur = -Math.PI / 2;
    for (const k of ordered) {
      const span = (2 * Math.PI * wOf(k)) / total;
      place(k, cur, cur + span, HUB_RADIUS);
      cur += span;
    }
  }
  return out;
}

// Takes the new graph. Returns true when the set of nodes or links, or the forces, changed.
export function sync(sim, graph, cfg, W, H) {
  const f = forceSettings(cfg, W, H);
  const focus = graph.focus ?? cfg?.focus ?? null;
  const seen = new Map();
  for (const n of graph.nodes ?? []) if (!seen.has(n.key)) seen.set(n.key, n);
  const edges = (graph.edges ?? []).filter(([a, b]) => seen.has(a) && seen.has(b));
  // Sibling springs are their own force and count for nothing in a node's degree (its radius).
  const links = edges.filter(([, , k]) => k !== "sibling");
  const siblings = edges.filter(([, , k]) => k === "sibling");
  const deg = new Map();
  for (const [a, b] of links) { deg.set(a, (deg.get(a) ?? 0) + 1); deg.set(b, (deg.get(b) ?? 0) + 1); }
  const sig = `${focus ?? ""}\u0000` + edges.map(([a, b, k]) => `${a}>${b}:${k}`).sort().join("|");
  const settings = JSON.stringify(f);

  const before = new Set(sim.d3.nodes().map((o) => o.key).filter((k) => sim.pos.has(k)));
  const added = [...seen.keys()].filter((k) => !before.has(k));
  const removed = [...before].some((k) => !seen.has(k));
  const wasEmpty = before.size === 0;

  // Node objects are reused by key: a refresh keeps x, y, vx and vy; a node that left keeps its place if it returns.
  const list = [];
  for (const [key, n] of seen) {
    let o = sim.pos.get(key);
    if (!o) { o = { key, x: NaN, y: NaN, vx: 0, vy: 0 }; sim.pos.set(key, o); }
    o.kind = n.kind;
    o.parent = n.parent ?? null;
    o.r = radiusOf(deg.get(key) ?? 0, n.kind);
    list.push(o);
  }
  if (sim.pos.size > KEEP) for (const k of [...sim.pos.keys()]) if (!seen.has(k)) sim.pos.delete(k);

  const targets = radialTargets(list, edges, { focus, linkDistance: cfg.linkDistance });
  for (const o of list) {
    const t = targets.get(o.key);
    o.ringR = t?.rRing ?? 0;
    o.tx = t?.x ?? 0;
    o.ty = t?.y ?? 0;
    o.angle = t?.angle ?? 0;
  }
  seed(sim, list, edges, cfg.linkDistance);

  // Forces are removed before the node list changes: d3 re-initialises every force on nodes(), and a link to a
  // node that has left would throw.
  for (const name of ["charge", "center", "sectorX", "sectorY", "link", "sibling", "collide", "radial"]) sim.d3.force(name, null);
  sim.d3.nodes(list);
  sim.d3
    .force("charge", forceManyBody().strength((d) => (d.kind === "m" || d.kind === "s" ? f.broadCharge : f.charge)).distanceMax(f.maxChargeDistance))
    .force("radial", forceRadial((d) => d.ringR ?? 0, 0, 0).strength((d) => ((d.ringR ?? 0) === 0 ? 0 : f.ringStrength)))
    .force("sectorX", forceX((d) => d.tx ?? 0).strength((d) => ((d.ringR ?? 0) === 0 ? ANCHOR_STRENGTH : f.sectorStrength)))
    .force("sectorY", forceY((d) => d.ty ?? 0).strength((d) => ((d.ringR ?? 0) === 0 ? ANCHOR_STRENGTH : f.sectorStrength)))
    .force("link", forceLink(links.map(([a, b]) => ({ source: a, target: b }))).id((d) => d.key).distance(f.linkDistance))
    .force("sibling", forceLink(siblings.map(([a, b]) => ({ source: a, target: b }))).id((d) => d.key).distance(f.linkDistance * SIBLING_FACTOR))
    .force("collide", forceCollide((d) => d.r).iterations(f.collideIterations));

  const changed = added.length > 0 || removed || sig !== sim.sig || settings !== sim.settings;
  // From nothing (the first sync, or an empty graph that cooled): a fresh layout at full heat. Otherwise a gentle reheat.
  if (changed && wasEmpty && seen.size) sim.d3.alpha(1);
  else if (changed && !wasEmpty) sim.d3.alpha(Math.max(sim.d3.alpha(), REHEAT));
  sim.sig = sig;
  sim.settings = settings;
  return changed;
}

// Fresh graphs seed each node at its radial target with <= 1 px deterministic jitter. New nodes in a settled graph
// seed one link distance outward from a placed neighbour (parent first), or at their radial target if unanchored.
function seed(sim, list, edges, linkDistance) {
  const current = new Map(list.map((o) => [o.key, o]));
  const near = adjacency(edges);
  let pending = list.filter((o) => !Number.isFinite(o.x));
  if (!pending.length) return;
  const placed = list.filter((o) => Number.isFinite(o.x));
  const isPending = new Set(pending.map((o) => o.key));
  const at = (o, x, y) => { o.x = x; o.y = y; isPending.delete(o.key); };
  const jitter = (o) => {
    const ja = hash01(o.key) * Math.PI * 2;
    const jr = 0.5 + 0.5 * hash01(`${o.key}#r`);
    return [(o.tx ?? 0) + Math.cos(ja) * jr, (o.ty ?? 0) + Math.sin(ja) * jr];
  };
  if (placed.length === 0) {
    for (const o of pending) {
      const [x, y] = jitter(o);
      at(o, x, y);
    }
    return;
  }
  while (pending.length) {
    let progress = true;
    while (progress) {
      progress = false;
      const next = [];
      for (const o of pending) {
        const anchor = [o.parent, ...(near.get(o.key) ?? [])]
          .map((k) => current.get(k))
          .find((p) => p && Number.isFinite(p.x) && !isPending.has(p.key));
        if (!anchor) { next.push(o); continue; }
        const baseAngle = anchor.x || anchor.y ? Math.atan2(anchor.y, anchor.x) : (o.angle ?? 0);
        const a = baseAngle + (hash01(o.key) - 0.5) * 0.9;
        at(o, anchor.x + Math.cos(a) * linkDistance, anchor.y + Math.sin(a) * linkDistance);
        placed.push(o);
        progress = true;
      }
      pending = next;
    }
    if (pending.length) {
      const o = pending.shift();
      const [x, y] = jitter(o);
      at(o, x, y);
      placed.push(o);
    }
  }
}

// One step of the simulation while it is active: alpha at or above alphaMin, or a drag holding alphaTarget above 0.
// Returns false once it has settled (and does nothing).
export function isActive(sim) {
  const d = sim.d3;
  return d.alpha() >= d.alphaMin() || d.alphaTarget() > 0;
}

// The frame loop runs while this holds: the simulation is active, a node is being dragged, or a hover fade runs.
// Nothing else ticks, and render never does (it only draws what sim.pos holds).
export function wantsFrames(sim, { fading = false, dragging = false, pulsing = false } = {}) {
  return frameIntervalMs(sim, { fading, dragging, pulsing }) != null;
}

export function tick(sim) {
  if (!isActive(sim)) return false;
  sim.d3.tick();
  return true;
}

// Runs the simulation out (up to max steps). Returns the steps taken.
export function settle(sim, max = 2000) {
  let n = 0;
  while (n < max && tick(sim)) n++;
  return n;
}

// The node being dragged follows the pointer (world units) and holds still while the rest relaxes around it
// (Quartz: fx/fy while dragging, graph.inline.ts 458-488; the heat is DRAG_HEAT, not Quartz's 1).
export function drag(sim, key, x, y) {
  const o = sim.pos.get(key);
  if (!o || !sim.d3.nodes().includes(o)) return false;
  o.x = x; o.y = y; o.vx = 0; o.vy = 0;
  o.fx = x; o.fy = y;
  sim.dragKey = key;
  sim.d3.alphaTarget(DRAG_HEAT);
  return true;
}

// Release: unpin and let the graph cool (alphaTarget back to 0; graph.inline.ts 477-478).
export function release(sim) {
  const o = sim.dragKey != null ? sim.pos.get(sim.dragKey) : null;
  if (o) { o.fx = null; o.fy = null; }
  sim.dragKey = null;
  sim.d3.alphaTarget(0);
}

// ---------------------------------------------------------------- view
export function boundsOf(sim, keys) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const k of keys) {
    const p = sim.pos.get(k);
    if (!p || !Number.isFinite(p.x)) continue;
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  return Number.isFinite(x0) ? { x0, y0, x1, y1 } : null;
}

// The transform that puts the box inside the panel with FIT_PAD around it.
export function fitView(box, W, H) {
  if (!box) return { scale: 1, x: W / 2, y: H / 2 };
  const bw = Math.max(1, box.x1 - box.x0), bh = Math.max(1, box.y1 - box.y0);
  const availW = Math.max(1, W - FIT_PAD.x * 2), availH = Math.max(1, H - FIT_PAD.top - FIT_PAD.bottom);
  const scale = Math.min(FIT_MAX_SCALE, availW / bw, availH / bh);
  return {
    scale,
    x: W / 2 - ((box.x0 + box.x1) / 2) * scale,
    y: (FIT_PAD.top + (H - FIT_PAD.bottom)) / 2 - ((box.y0 + box.y1) / 2) * scale,
  };
}

export function viewFrom(saved) {
  return saved && Number.isFinite(saved.scale)
    ? { scale: saved.scale, x: saved.x, y: saved.y, manual: Boolean(saved.manual) }
    : { scale: 1, x: 0, y: 0, manual: false };
}

// Auto-fit follows the graph until the person pans or zooms by hand; then it stays put until fitNow.
export function autoFit(view, box, W, H) {
  return view.manual ? view : { ...fitView(box, W, H), manual: false };
}

export function fitNow(box, W, H) { return { ...fitView(box, W, H), manual: false }; }

export function panTo(view, x, y) { return { ...view, x, y, manual: true }; }

// Zoom about a screen point, within Quartz's scale extent.
export function zoomAt(view, factor, px, py) {
  const s0 = view.scale;
  const s1 = Math.max(SCALE_EXTENT[0], Math.min(SCALE_EXTENT[1], s0 * factor));
  if (s1 === s0) return view;
  return { scale: s1, x: px - ((px - view.x) / s0) * s1, y: py - ((py - view.y) / s0) * s1, manual: true };
}

// Links as a few paths: [{ seg, alpha }] -> [{ alpha, segs }], alpha rounded to `step`. One path per alpha step is
// drawn instead of one full-size layer per link; alpha 0 is not drawn.
export function linkBatches(links, step = 0.05) {
  const by = new Map();
  for (const l of links) {
    const a = Math.round(Math.max(0, Math.min(1, l.alpha)) / step) * step;
    if (a <= 0) continue;
    const key = a.toFixed(3);
    if (!by.has(key)) by.set(key, { alpha: a, segs: [] });
    by.get(key).segs.push(l.seg);
  }
  return [...by.values()];
}
