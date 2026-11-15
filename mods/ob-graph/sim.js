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
// Machines and spaces push each other less than panes do (charge -60 x repelForce against -100), the push stops at
// 250 world units, and machines are drawn gently to the middle, so disconnected machines (spare, sandbox-vm) do not
// sit on the rim and connected ones do not fly apart. Everything else keeps Quartz's values.
const BROAD_CHARGE_FACTOR = 0.4;                         // machines and spaces: -40 x repelForce
const MAX_CHARGE_DISTANCE = 250;                         // the charge reaches no further than this (world units, zoom 1)
const MACHINE_GRAVITY = 0.2;                             // pull of each machine toward the centre

// Quartz: 2 + sqrt(number of links) (graph.inline.ts 208-213).
// Machines and spaces have a fixed size (drawn as a diamond and a hexagon, shape.js): what hangs off them does not grow them.
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

// The force parameters a config asks for (graph.inline.ts 169-175). Radial: min(W, max(H, 250)) / 2 * 0.8 at 0.2.
export function forceSettings(cfg, W, H) {
  const radial = cfg.enableRadial
    ? { radius: 0.8 * Math.min(W, Math.max(H, 250)) / 2, strength: 0.2 }
    : null;
  return {
    charge: -100 * cfg.repelForce,
    broadCharge: -100 * cfg.repelForce * BROAD_CHARGE_FACTOR,
    maxChargeDistance: MAX_CHARGE_DISTANCE,
    machineGravity: MACHINE_GRAVITY,
    center: cfg.centerForce,
    linkDistance: cfg.linkDistance,
    collideIterations: COLLIDE_ITERATIONS,
    radial,
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

// Takes the new graph. Returns true when the set of nodes or links, or the forces, changed.
export function sync(sim, graph, cfg, W, H) {
  const f = forceSettings(cfg, W, H);
  const seen = new Map();
  for (const n of graph.nodes ?? []) if (!seen.has(n.key)) seen.set(n.key, n);
  const edges = (graph.edges ?? []).filter(([a, b]) => seen.has(a) && seen.has(b));
  // Sibling springs are their own force and count for nothing in a node's degree (its radius).
  const links = edges.filter(([, , k]) => k !== "sibling");
  const siblings = edges.filter(([, , k]) => k === "sibling");
  const deg = new Map();
  for (const [a, b] of links) { deg.set(a, (deg.get(a) ?? 0) + 1); deg.set(b, (deg.get(b) ?? 0) + 1); }
  const sig = edges.map(([a, b, k]) => `${a}>${b}:${k}`).sort().join("|");
  const settings = JSON.stringify(f);

  const before = new Set(sim.d3.nodes().map((o) => o.key));
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
  seed(sim, list, edges, cfg.linkDistance);

  // Forces are removed before the node list changes: d3 re-initialises every force on nodes(), and a link to a
  // node that has left would throw.
  for (const name of ["charge", "center", "gatherX", "gatherY", "link", "sibling", "collide", "radial"]) sim.d3.force(name, null);
  sim.d3.nodes(list);
  sim.d3
    .force("charge", forceManyBody().strength((d) => (d.kind === "m" || d.kind === "s" ? f.broadCharge : f.charge)).distanceMax(f.maxChargeDistance))
    .force("center", forceCenter().strength(f.center))
    .force("gatherX", forceX(0).strength((d) => (d.kind === "m" ? f.machineGravity : 0)))
    .force("gatherY", forceY(0).strength((d) => (d.kind === "m" ? f.machineGravity : 0)))
    .force("link", forceLink(links.map(([a, b]) => ({ source: a, target: b }))).id((d) => d.key).distance(f.linkDistance))
    .force("sibling", forceLink(siblings.map(([a, b]) => ({ source: a, target: b }))).id((d) => d.key).distance(f.linkDistance * SIBLING_FACTOR))
    .force("collide", forceCollide((d) => d.r).iterations(f.collideIterations));
  if (f.radial) sim.d3.force("radial", forceRadial(f.radial.radius).strength(f.radial.strength));

  const changed = added.length > 0 || removed || sig !== sim.sig || settings !== sim.settings;
  // From nothing (the first sync, or an empty graph that cooled): a fresh layout at full heat. Otherwise a gentle reheat.
  if (changed && wasEmpty && seen.size) sim.d3.alpha(1);
  else if (changed && !wasEmpty) sim.d3.alpha(Math.max(sim.d3.alpha(), REHEAT));
  sim.sig = sig;
  sim.settings = settings;
  return changed;
}

// New nodes go one link distance from a placed neighbour (the parent first), at an angle set by their key. A node with
// no placed neighbour goes on a ring round what is drawn, or at the origin for the first one.
function seed(sim, list, edges, linkDistance) {
  const current = new Map(list.map((o) => [o.key, o]));
  const near = adjacency(edges);
  let pending = list.filter((o) => !Number.isFinite(o.x));
  if (!pending.length) return;
  const placed = list.filter((o) => Number.isFinite(o.x));
  const isPending = new Set(pending.map((o) => o.key));
  const at = (o, x, y) => { o.x = x; o.y = y; isPending.delete(o.key); };
  const angle = (o) => hash01(o.key) * Math.PI * 2;
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
        const a = angle(o);
        at(o, anchor.x + Math.cos(a) * linkDistance, anchor.y + Math.sin(a) * linkDistance);
        placed.push(o);
        progress = true;
      }
      pending = next;
    }
    if (pending.length) {
      const o = pending.shift();
      let cx = 0, cy = 0, rad = 0;
      if (placed.length) {
        for (const p of placed) { cx += p.x; cy += p.y; }
        cx /= placed.length; cy /= placed.length;
        rad = 120 + 20 * Math.sqrt(list.length);
      }
      const a = angle(o);
      at(o, cx + Math.cos(a) * rad, cy + Math.sin(a) * rad);
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
