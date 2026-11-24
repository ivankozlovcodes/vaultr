// ob-graph: the Graph panel of the Herdr world, drawn on Quartz's graph model (jackyzha0/quartz v4, MIT).
// Nodes: machines, spaces, panes (terminals and mod panes) and sub-agents (runs, sub-agents, hc children). There is no
// tab node: a pane links straight to its space, and the panes of one tab are joined by sibling links (shape.js), an
// invisible spring that makes a tab read as a small cluster, like a folder in Obsidian's graph. Pane names: paneLabel
// (kit/names.js). Edges: containment and sub-agent -> parent session links, both 1 px solid (Obsidian's one style).
// "Active only" (on by default, remembered per Local/Global view): the foreground agents placed in tabs, their live
// sub-agents, and every machine and space (always shown). Off shows every sub-agent, finished ones too (filter.js).
// Modes: Local (Quartz's local graph: the focused session and what is within `depth` links of it) and Global (all).
// Layout: sim.js (Quartz's forces on the vendored d3-force; tested by test/test_ob_graph.py). Positions are kept per
// node, so a refresh does not move anything; a new node enters a link distance from its parent; the simulation
// cools and stops; the view fits the drawing until the person pans or zooms by hand.
// Look: round theme-accent dots with 1 px canvas cutout borders (foreground on hover/selection) and degree-weighted
// opacity, status halos on active agents (pulsing working, steady blocked), 1.5 px accent-lit incident links and chrome
// pill-backed labels on hover/selection, and zoom-faded labels at rest. Hover fades the rest of the graph to 0.2 (dim
// 100 ms, restore 200 ms); the timer runs only during a fade. Click (down and up under 500 ms, no drag) selects and goes
// there; right-click: menu. Drag the background to pan, wheel to zoom (Quartz's scale extent 0.25..4), drag a node to
// pull it (it reheats, then cools).
// Notes and artifacts (touch_shape.js; the switches "Notes" and "Artifacts", off by default, per view like Active only): the
// files the agents touched (the feed's `touches`, paths only), both drawn as small round dots (notes, from the vault's
// .md files, and artifacts: herdr-artifact publications or files written outside the vault; no squares). A link from each
// agent by its op (a read is faint). Notes need the vault in obsidian.json (read here, never written); danger/ and hidden
// folders are never shown. Click a note: the Notes viewer; an artifact: `herdr-artifact open`, or an editor for a plain file.
// Commands (ob-graph.<cmd>): fit, zoom-in, zoom-out, select:<key>, open:<key>, menu:<key>,
//   mode:<local|global>, depth:<1|2|3>, labels:<on|off>, active:<on|off>, notes:<on|off>, artifacts:<on|off>,
//   focus-on:<address>, bookmark:<key>, focus.
// Node keys: m:<machine|local>, s:<spaceId>, p:<paneId>, r:<runKey>, c:<agentKey>, h:<address>.

import { View, div, PathBuilder } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { props, run, nextCommand, settings, machines, spaces, panes, agents, shared, setShared, focused, exec, readTextFile, appHome, home as userHome, notify } from "herdr";
import {
  S, tc, alpha, icon, iconButton, feed, machineLabel, machineOf, tabLabel, paneLabelOf,
  takeFocus, openMenu, openView, reveal, isBookmarked, toggleBookmark, emptyState, placedTerminals, mainAgents,
  normHidden, isMachineHidden, isSpaceHidden, isTabHidden, getHidden,
} from "./kit.js";
import { shownGraph, emptyCopy, activeState, activeOf, setActive, touchState, touchOn, setTouch } from "./filter.js";
import { touchShape } from "./touch_shape.js";
import { expandPath } from "./touches.js";
import { activityOf, activeStatus } from "./agents.js";
import { paneShape, placeSubs, editorArgv, toolbarRows, toolbarBottom, framePaint, dotTone, placeLabels, nextDepth } from "./shape.js";
import { splitCmd, inspected, inspect, runTitle, allSubagents, hcChildren } from "./obc.js";
import {
  QUARTZ, createSim, sync, tick, wantsFrames, frameIntervalMs, anyPulsing, haloDrawAlpha, linkRestAlpha, drag, release,
  boundsOf, fitNow, autoFit as autoFitView, linkBatches,
  viewFrom, panTo, zoomAt as zoomView, labelOpacity, labelLayout, hoverSet, hoverAlpha, animateAlpha, fadeMs,
  DIM_MS, RESTORE_MS, DIM_ALPHA, touchAlpha,
} from "./sim.js";


const LABEL_GAP = 8;                // label top = node bottom + 8 px
// The model is rebuilt off the render path (Herdr's way): render marks it stale, a timer rebuilds it at most this
// often and redraws only when the graph changed. Nodes may appear this late; a command rebuilds at once.
const REBUILD_MS = 500;
const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* keep in memory */ } };
const drop = (k) => { try { localStorage.removeItem(k); } catch { /* nothing to remove */ } };
const clampDepth = (v) => Math.max(1, Math.min(3, Number(v) || 1));
const linkId = (a, b) => `l:${a}\u0001${b}`;
const nodeId = (k) => `n:${k}`;

export default class Graph extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.cx = cx;
    this.sim = createSim();
    this.view = viewFrom(load("view", null));
    this.mode = load("mode", "global") === "local" ? "local" : "global";
    this.depth = clampDepth(load("depth", 1));          // Quartz's local default is depth 1
    this.labelsAll = Boolean(load("labels", false));
    // "Active only" is remembered per view: { local, global }, both on by default. The old "show finished" setting
    // (key "show") migrates once: its finished-visible state turns Active only off in both views.
    this.activeOn = activeState(load("active", null), load("show", null));
    // Notes and Artifacts: { local, global } of { notes, artifacts }, off by default.
    this.touchOn = touchState(load("touch", null));
    this.vault = null;                                  // the vault's full path (obsidian.json), null when none
    this.homeDir = userHome();                          // known at once: it keeps the agents' own state out of artifacts
    this.hover = null;
    this.near = new Set();                              // the hovered node and its neighbours
    this.fade = null;                                   // { start, from: Map(id -> alpha) } while the hover fades
    this.selected = null;
    this.drag = null;
    this.nodeDrag = null;
    this.looping = false;
    this.cfg = QUARTZ.global;
    this.W = 0; this.H = 0;
    this.g = null;                                      // the graph render draws (rebuild() sets it)
    this.sig = "";                                      // what the last rebuild drew, to skip redraws with no change
    this.dirty = true;                                  // rebuild before the next draw (first draw, a command)
    this.stale = false;                                 // render ran: Herdr's data may have changed since the rebuild
    cx.timer.every(REBUILD_MS, (cx) => {
      if (!this.stale) return;
      this.stale = false;
      if (this.rebuild()) cx.notify();
    });
    this.readVault(cx);
    cx.timer.every(10000, (cx) => this.readVault(cx));
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-graph: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  persist() {
    save("view", this.view);
    drop("show");
    save("mode", this.mode);
    save("depth", this.depth);
    save("labels", this.labelsAll);
    save("active", this.activeOn);
    save("touch", this.touchOn);
  }

  // The vault and the editor: obsidian.json's `vault` and `editor` (read only; the obsidian mod owns that file). Unset or relative: no vault.
  readVault(cx) {
    cx.spawn(async (cx) => {
      try {
        const text = await readTextFile(`${appHome()}/obsidian.json`);
        const own = JSON.parse(text || "{}") ?? {};
        this.vault = expandPath(own.vault, this.homeDir);
        this.editor = own.editor;
      } catch {
        this.vault = null;
        this.editor = null;
      }
      this.dirty = true;
      cx.notify();
    });
  }

  activeNow() { return activeOf(this.activeOn, this.mode); }

  // ---------------------------------------------------------------- model
  // -> { nodes: Map(key -> node), edges: [[a, b, "contain"|"link"]] }
  model() {
    const nodes = new Map(), edges = [];
    const add = (n) => { nodes.set(n.key, n); return n; };
    const ps = panes(), sp = spaces();
    const h = normHidden(shared("ob.hidden") ?? getHidden());
    for (const m of machines()) {
      if (isMachineHidden(h, m.name ?? null)) continue;
      const k = `m:${m.name ?? "local"}`;
      add({ key: k, kind: "m", label: machineLabel(m.name ?? null), machine: m.name ?? null, down: m.layout === "unavailable" });
    }
    if (!nodes.has("m:local") && !isMachineHidden(h, null)) add({ key: "m:local", kind: "m", label: machineLabel(null), machine: null });
    const paneOf = new Map();
    // Foreground: a main agent (its terminal is in a pane of a tab), kit/agents.js.
    const main = new Map(mainAgents(agents(), placedTerminals(ps)).map((a) => [a.address, a]));
    for (const s of sp) {
      if (isMachineHidden(h, s.machine ?? null) || isSpaceHidden(h, s)) continue;
      const visibleTabs = (s.tabs ?? []).filter((tab) => !isTabHidden(h, tab, s));
      if ((s.tabs ?? []).length > 0 && visibleTabs.length === 0) continue;
      const mk = `m:${s.machine ?? "local"}`;
      if (!nodes.has(mk)) add({ key: mk, kind: "m", label: machineLabel(s.machine), machine: s.machine });
      const sk = `s:${s.id}`;
      add({ key: sk, kind: "s", label: s.name, parent: mk, status: s.status, space: s });
      edges.push([mk, sk, "contain"]);
      for (const tab of visibleTabs) {
        // No tab node: each pane is a node under its space, and the panes of one tab are joined by sibling links (shape.js).
        // Respect manual pane.name first; for a single-pane tab, respect manual tab rename via tabLabel; otherwise use paneLabelOf without tabName suppression.
        const mine = ps.filter((x) => x.tab === tab.id);
        const shape = paneShape(tab.id, mine.map((p) => ({
          pane: p.pane,
          label: p.name?.trim() ? paneLabelOf(p) : (mine.length === 1 ? tabLabel(tab, ps) : paneLabelOf(p)),
        })));
        for (const sn of shape.nodes) {
          const p = mine.find((x) => x.pane === sn.pane);
          // A foreground pane takes its agent's status (the one the Agents panel shows); other panes keep the pane's.
          const agent = p?.terminal ? main.get(p.terminal) : undefined;
          add({
            key: sn.key, kind: "p", label: sn.label, parent: sk,
            status: agent ? agent.status : p.status, space: s, tab, pane: p, program: p.program, address: p.terminal,
            foreground: Boolean(agent),
          });
          if (p.terminal) paneOf.set(p.terminal, sn.key);
          edges.push([sk, sn.key, "contain"]);
        }
        for (const [a, b, k] of shape.edges) edges.push([a, b, k]);
      }
    }
    // Sub-agents hang off their parent session: its pane, or an unplaced hc child (shape.js placeSubs); without one, off
    // their machine. A sub-agent: live is the feed's (or the local record's) say so; extra.feedAt is the feed's `at` when
    // the feed is its source.
    const subs = [];
    const sub = (key, kind, label, status, live, parentAddr, machine, extra) =>
      subs.push({ key, parentAddr, machine, node: { key, kind, label, status, live, ...extra } });
    const f = feed();
    const { runs, agents: subAgents } = allSubagents();
    for (const r of runs) sub(`r:${r.key}`, "r", `${runTitle(r)} · ${r.short}`, r.state, r.live, r.parent, r.machine, r.pending ? { run: r } : { run: r, feedAt: f?.at });
    for (const c of subAgents) sub(`c:${c.key}`, "c", c.desc || c.type || c.id, c.live ? (c.state === "blocked" ? "blocked" : "working") : "ok", c.live, c.parent, c.machine, { subagent: c, feedAt: c.updatedAt != null ? f?.at : undefined });
    for (const k of hcChildren(null)) {
      // An hc child is active by the status hc reports (working, blocked); no status, or an idle or done one, is not.
      const st = typeof k.status === "string" ? k.status : k.status?.state ?? null;
      sub(`h:${k.address}`, "h", k.name || k.title || k.address, st, activeStatus(st) != null, k.parent, machineOf(k.address), { address: k.address });
    }
    // A sub-agent is drawn when its parent is: a machine in the graph, or a sub-agent that is drawn.
    const placed = placeSubs(subs, paneOf), drawn = new Set();
    for (let grew = true; grew;) {
      grew = false;
      for (const s of placed) if (!drawn.has(s.key) && (nodes.has(s.parent) || drawn.has(s.parent))) { drawn.add(s.key); grew = true; }
    }
    for (const s of placed) {
      if (!drawn.has(s.key)) continue;
      add({ ...s.node, parent: s.parent });
      edges.push([s.parent, s.key, s.edge]);
    }
    // Notes and artifacts the agents touched: a link from each agent node that is in the graph (a terminal's pane, a sub-agent).
    const touched = touchShape(f?.touches ?? {}, {
      vault: this.vault, home: this.homeDir, notes: touchOn(this.touchOn, this.mode, "notes"),
      artifacts: touchOn(this.touchOn, this.mode, "artifacts"),
      resolve: (k) => (k.startsWith("term:") ? paneOf.get(k.slice(5)) ?? null : nodes.has(k) ? k : null),
    });
    for (const n of touched.nodes) add(n);
    for (const e of touched.edges) edges.push(e);
    // On a thin client where remote machines exist and local has no spaces or agents, omit the empty m:local dot.
    if (nodes.has("m:local") && [...nodes.values()].some((n) => n.kind === "m" && n.machine != null)
        && !edges.some(([a, b]) => a === "m:local" || b === "m:local")) {
      nodes.delete("m:local");
    }
    return { nodes, edges };
  }

  // The focus (Quartz's "current page"): the inspected session, else the focused pane, else none.
  focusOf(model) {
    const { address } = inspected();
    if (address) for (const n of model.nodes.values()) if (n.address === address) return n.key;
    const fp = focused();
    if (fp?.pane && model.nodes.has(`p:${fp.pane}`)) return `p:${fp.pane}`;
    return null;
  }


  // ---------------------------------------------------------------- frames
  // Nothing ticks inside render: render draws the positions sim.js holds. The frame loop (here) ticks the simulation
  // and redraws while wantsFrames(): alpha above alphaMin, a node being dragged, a hover fade, or a pulsing halo. The
  // interval is 16 ms while the graph moves and 67 ms (15 fps) for a pulse alone (sim.js frameIntervalMs).
  // A structural change (sync), a view switch, a drag or a fade only reheats and calls startLoop(); a still graph
  // starts no loop. The loop is one task at a time (this.looping), and clears that flag even when it throws.
  startLoop() {
    if (this.looping || !this.cx) return;
    this.looping = true;
    this.cx.spawn(async (cx) => {
      try {
        while (this.wantsFrames()) {
          tick(this.sim);
          this.autoFit(this.g);
          cx.notify();
          await cx.sleep(frameIntervalMs(this.sim, this.frameOpts()) ?? 16);
        }
      } finally {
        this.looping = false;
      }
      this.persist();
      cx.notify();
    });
  }

  fadeRunning() { return Boolean(this.fade && Date.now() - this.fade.start < Math.max(DIM_MS, RESTORE_MS)); }

  frameOpts() {
    return { fading: this.fadeRunning(), dragging: Boolean(this.nodeDrag?.moved), pulsing: Boolean(this.pulsing) };
  }

  wantsFrames() { return wantsFrames(this.sim, this.frameOpts()); }

  fit(g) {
    if (!this.W || !this.H || !g) return;
    this.view = fitNow(boundsOf(this.sim, g.nodes.keys()), this.W, this.H);
  }

  autoFit(g) {
    if (!this.W || !this.H || !g) return;
    this.view = autoFitView(this.view, boundsOf(this.sim, g.nodes.keys()), this.W, this.H);
  }

  zoomAt(factor, px, py) {
    const v = zoomView(this.view, factor, px, py);
    if (v === this.view) return;
    this.view = v;
    this.persist();
  }

  // ---------------------------------------------------------------- hover fade
  // Targets: a node is 1 in the hovered neighbourhood and 0.2 outside it while something is hovered; a link is 1 when it
  // touches the hovered node, 0.2 when it does not, and 0.35 at rest.
  targetOf(id) {
    const hovering = this.hover != null;
    if (id.startsWith("n:")) return hoverAlpha(this.near.has(id.slice(2)), hovering);
    const [a, b] = id.slice(2).split("\u0001");
    if (!hovering) return this.restAlpha(id);
    return a === this.hover || b === this.hover ? 1 : DIM_ALPHA;
  }

  // A link's rest alpha: stronger when it joins an active agent (working or blocked) to its parent.
  restAlpha(id) {
    const [a, b] = id.slice(2).split("\u0001");
    const edge = this.g?.edgeOf.get(id);
    if (edge && edge[2] === "touch") return touchAlpha(edge[3]);
    const touches = (k) => { const st = this.stateOf?.get(k); return st === "working" || st === "blocked"; };
    return linkRestAlpha(Boolean(edge && edge[2] === "link" && (touches(a) || touches(b))));
  }

  // The halo's state: working or blocked ("needs you") when the agent is active (kit/agents.js activityOf), else idle.
  agentState(n) {
    return activityOf(n, Date.now()) ?? "idle";
  }

  alphaNow(id, now) {
    const to = this.targetOf(id);
    if (!this.fade) return to;
    const from = this.fade.from.has(id) ? this.fade.from.get(id) : to;
    return animateAlpha(from, to, now - this.fade.start, fadeMs(from, to));
  }

  setHover(key, cx) {
    if (key === this.hover) return;
    const now = Date.now();
    const from = new Map();
    for (const k of this.g?.nodes.keys() ?? []) from.set(nodeId(k), this.alphaNow(nodeId(k), now));
    for (const [a, b] of this.g?.edges ?? []) from.set(linkId(a, b), this.alphaNow(linkId(a, b), now));
    this.hover = key;
    this.near = key && this.g ? hoverSet(this.g.edges, key) : new Set();
    this.fade = { start: now, from };
    this.startLoop();
    cx.notify();
  }

  // ---------------------------------------------------------------- actions
  open(key) {
    const n = this.g?.nodes.get(key) ?? this.model().nodes.get(key);
    if (!n) return;
    this.selected = key;
    if (n.kind === "m") { const s = spaces().find((x) => (x.machine ?? null) === n.machine); if (s) run("space.select", { id: s.id }); }
    else if (n.kind === "s") run("space.select", { id: n.space.id });
    else if (n.kind === "p") reveal({ space: n.space.id, tab: n.tab.id, pane: n.pane.pane });
    else if (n.kind === "r") openView("ob-outline", `run:${n.run.key}`);
    else if (n.kind === "c") openView("ob-outline", `run:${n.subagent.key}`);
    else if (n.kind === "h") run("terminal.peek", { terminal: n.address });
    else if (n.kind === "n") this.openNote(n);
    else if (n.kind === "a") this.openArtifact(n);
  }

  // A note: the Notes viewer that shows this tab (through shared "obsidian.show", as the obsidian mod does), else a new
  // Notes pane beside it. The obsidian mod's own rule: a viewer registers its tab under "obsidian.viewers".
  openNote(n) {
    const tab = focused()?.tab;
    const viewers = Object.values(shared("obsidian.viewers") ?? {});
    const live = panes().some((p) => p.tab === tab && p.mod === "obsidian");
    if (tab && viewers.includes(tab) && live) setShared("obsidian.show", { tab, note: n.rel, line: null, n: Date.now() });
    else run("pane.split", { direction: "right", mod: "obsidian", props: { note: n.rel, line: null } });
  }

  // A herdr-artifact publication: `herdr-artifact open` shows it in a pane beside the focused one. A plain file: an
  // editor pane.
  // The editor: obsidian.json's `editor`, else $VISUAL, then $EDITOR, then the first of nvim, vim, nano, vi installed.
  openArtifact(n) {
    if (n.artifact?.id) {
      // exec resolves on a failed run too: its exit code and stderr say so, shown as a toast.
      const fail = (why) => notify({ title: `Couldn't open ${n.label}`, body: String(why), level: "error" });
      exec("herdr-artifact", ["open", n.artifact.id]).then((r) => {
        if (r.code !== 0) fail((r.stderr || r.stdout || `exit ${r.code}`).trim().split("\n").pop());
      }, fail);
      return;
    }
    run("pane.split", { direction: "right", argv: editorArgv(this.editor, n.path) });
  }

  // Ends a node drag or a pan without a click (the pointer left the panel): the node is let go, so alphaTarget drops
  // and the loop cools and stops; a moved pan is saved.
  endDrag(cx) {
    if (this.nodeDrag?.moved) release(this.sim);
    if (this.drag?.moved) this.persist();
    this.nodeDrag = null;
    this.drag = null;
    this.startLoop();
    cx.notify();
  }

  menu(key) {
    const n = this.g?.nodes.get(key);
    if (!n) return;
    const addr = n.address ?? n.run?.parent ?? n.subagent?.parent ?? null;
    const bm = n.kind === "s" ? ["space", n.space.id] : n.kind === "p" && n.address ? ["terminal", n.address] : n.kind === "r" ? ["run", n.run.key] : null;
    openMenu([
      { label: n.kind === "r" || n.kind === "c" ? "Open in Outline" : n.kind === "h" ? "Peek" : n.kind === "n" ? "Open note" : n.kind === "a" ? "Open" : "Reveal", icon: "locate", command: `ob-graph.open:${key}` },
      ...(addr ? [{ label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${addr}` }] : []),
      ...(n.kind === "p" && n.address ? [{ label: "Local graph of this session", icon: "graph", command: `ob-graph.focus-on:${n.address}` }] : []),
      ...(bm ? [{ label: isBookmarked(bm[0], bm[1]) ? "Remove bookmark" : "Bookmark", icon: "bookmark", command: `ob-graph.bookmark:${key}` }] : []),
    ], { width: 230, title: n.label });
  }

  command(c, cx) {
    this.dirty = true;
    const [verb, arg] = splitCmd(c);
    const cxW = this.W / 2, cxH = this.H / 2;
    if (verb === "fit") { this.fit(this.g); this.persist(); }
    else if (verb === "zoom-in") this.zoomAt(1.25, cxW, cxH);
    else if (verb === "zoom-out") this.zoomAt(0.8, cxW, cxH);
    else if (verb === "select") this.selected = arg || null;
    else if (verb === "open") this.open(arg);
    else if (verb === "menu") this.menu(arg);
    else if (verb === "mode") { const next = arg === "local" ? "local" : "global"; if (next !== this.mode) this.sim.pos.clear(); this.mode = next; this.refit = true; this.persist(); }
    else if (verb === "depth") { this.depth = clampDepth(arg); this.refit = true; this.persist(); }
    else if (verb === "labels") { this.labelsAll = arg !== "off"; this.persist(); }
    else if (verb === "active") { this.activeOn = setActive(this.activeOn, this.mode, arg !== "off"); this.refit = true; this.persist(); }
    else if (verb === "notes" || verb === "artifacts") { this.touchOn = setTouch(this.touchOn, this.mode, verb, arg !== "off"); this.refit = true; this.persist(); }
    else if (verb === "focus-on") { this.sim.pos.clear(); inspect(arg || null); this.mode = "local"; this.refit = true; this.persist(); }
    else if (verb === "bookmark") {
      const n = this.g?.nodes.get(arg);
      if (n?.kind === "s") toggleBookmark({ kind: "space", id: n.space.id, label: n.label, machine: n.space.machine ?? null });
      else if (n?.kind === "p" && n.address) toggleBookmark({ kind: "terminal", id: n.address, label: n.label, machine: machineOf(n.address) });
      else if (n?.kind === "r") toggleBookmark({ kind: "run", id: n.run.key, label: runTitle(n.run), machine: n.run.machine });
    }
    else if (verb === "focus") this.handle.focus();
  }

  // ---------------------------------------------------------------- rebuild (off the render path)
  // Builds the model, filters it to what the view shows and syncs the simulation. Returns true when the drawn graph
  // changed (a node, its label or status, a link, the focus), so the caller redraws only then.
  rebuild() {
    this.dirty = false;
    const model = this.model();
    const lists = { nodes: [...model.nodes.values()], edges: model.edges };
    const focus = this.focusOf(model);
    // Local: the focus's neighbourhood first (a pane's subagents free), then "Active only" over it, anchored on the focus.
    // Global: everything, then "Active only" with no anchor. (filter.js shownGraph)
    const shown = shownGraph(lists, { mode: this.mode, focus, depth: this.depth, active: this.activeNow() });
    // edgeOf: link id -> its first edge, so a link's rest alpha (read per link per frame) is one lookup.
    const edgeOf = new Map();
    for (const e of shown.edges) { const id = linkId(e[0], e[1]); if (!edgeOf.has(id)) edgeOf.set(id, e); }
    const g = { nodes: new Map(shown.nodes.map((n) => [n.key, n])), edges: shown.edges, edgeOf, focus: shown.focus };
    this.g = g;
    this.cfg = this.mode === "local" ? { ...QUARTZ.local, depth: this.depth } : QUARTZ.global;
    // A change of nodes or links (or of the forces) reheats gently; a refresh with the same ones changes nothing.
    // sync() moves nothing; it reheats on a change, and the frame loop does the moving.
    const moved = sync(this.sim, { nodes: g.nodes.values(), edges: g.edges, focus: g.focus }, this.cfg, this.W, Math.max(this.H, 250));
    if (moved) {
      if (this.refit) this.fit(g); else this.autoFit(g);
      this.startLoop();
    } else if (this.refit) this.fit(g);
    this.refit = false;
    let sig = `${g.focus}\u0002${g.edges.length}`;
    for (const n of g.nodes.values()) sig += `\u0002${n.key}\u0001${n.label}\u0001${n.status}\u0001${n.live}`;
    const changed = moved || sig !== this.sig;
    this.sig = sig;
    return changed;
  }

  // ---------------------------------------------------------------- render
  // Colours: clean theme-accent dots (full accent on focus or active, dim when an anchor machine is offline, fixed frame
  // tones for machines and spaces, and degree-stepped opacity for everything else).
  nodeColor(t, n, focusKey) {
    if (n.key === focusKey) return t.accent;
    if (n.kind === "m" && n.down) return t.dim;
    if (activityOf(n, Date.now())) return t.accent;
    const fp = framePaint(n.kind);
    if (fp.tone != null) return alpha(t.accent, fp.tone);
    return alpha(t.accent, dotTone(this.sim.pos.get(n.key)?.r ?? 3));
  }

  toolbar(t) {
    const stop = (_e, cx) => cx.stop_propagation();
    const seg = (id, label, on, cmd) => h_flex().id(id).h(20).px(7).items_center().rounded(S.radius).cursor_pointer()
      .text_size(S.textXs).font_medium().text_color(on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
      .when(!on, (e) => e.hover((s) => s.bg(t.hover).text_color(t.muted)))
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .on_click((_e, cx) => { this.command(cmd, cx); cx.notify(); }).child(label);
    const txt = (id, label, tip, cmd) => h_flex().id(id).size(22).items_center().justify_center().rounded(S.radius).cursor_pointer()
      .text_size(14).text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip(tip)
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .on_click((_e, cx) => { this.command(cmd, cx); cx.notify(); }).child(label);
    const activeSwitch = (on, cmd) => h_flex().id("g-active").h(20).px(7).items_center().rounded(S.radius).cursor_pointer()
      .text_size(S.textXs).font_medium().border_1().border_color(on ? t.selected : t.border)
      .text_color(on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
      .when(!on, (e) => e.hover((s) => s.bg(t.hover).text_color(t.muted)))
      .tooltip(on ? "Showing only active agents" : "Showing all")
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .on_click((_e, cx) => { this.command(cmd, cx); cx.notify(); }).child("Active only");
    // Notes and Artifacts: off by default. Notes need a vault; without one the switch is disabled and says why.
    const touchSwitch = (id, label, which, tip, enabled = true) => {
      const on = touchOn(this.touchOn, this.mode, which) && enabled;
      return h_flex().id(id).h(20).px(7).items_center().rounded(S.radius).border_1().border_color(on ? t.selected : t.border)
        .text_size(S.textXs).font_medium().text_color(!enabled ? t.dim : on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
        .when(enabled && !on, (e) => e.cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.muted)))
        .when(!enabled, (e) => e.opacity(0.5))
        .tooltip(tip).on_mouse_down("left", stop).on_mouse_down("right", stop)
        .when(enabled, (e) => e.on_click((_e, cx) => { this.command(`${which}:${on ? "off" : "on"}`, cx); cx.notify(); }))
        .child(label);
    };
    const noVault = !this.vault;
    const touchGroup = h_flex().p(2).gap(2).rounded(S.radiusLg).bg(alpha(t.chrome, 0.9)).border_1().border_color(t.border)
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .child(touchSwitch("g-notes", "Notes", "notes", noVault ? "Set your vault in Settings" : "Notes your agents touched", !noVault))
      .child(touchSwitch("g-artifacts", "Artifacts", "artifacts", "Artifacts agents publish or write outside the vault"));
    const zoomGroup = h_flex().p(2).gap(1).rounded(S.radiusLg).bg(alpha(t.chrome, 0.9)).border_1().border_color(t.border)
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .child(iconButton({ id: "g-labels", icon: "hash", size: 22, iconSize: 13, active: this.labelsAll, tip: this.labelsAll ? "Labels: all" : "Labels: fade in with zoom (hover for the rest)", onClick: (_e, cx) => { this.command(`labels:${this.labelsAll ? "off" : "on"}`, cx); cx.notify(); } }))
      .child(txt("g-out", "−", "Zoom out", "zoom-out"))
      .child(txt("g-in", "+", "Zoom in", "zoom-in"))
      .child(iconButton({ id: "g-fit", icon: "maximize", size: 22, iconSize: 13, tip: "Fit to view", onClick: (_e, cx) => { this.command("fit", cx); cx.notify(); } }));
    const nextD = nextDepth(this.depth, 1);
    const depthBtn = h_flex().id("g-depth").h(20).px(6).items_center().rounded(S.radius).cursor_pointer()
      .text_size(S.textXs).font_medium().border_1().border_color(t.border)
      .text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground))
      .tooltip(`Local depth: ${this.depth} hop${this.depth === 1 ? "" : "s"} (click for ${nextD}, or [ / ])`)
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .on_click((_e, cx) => { this.command(`depth:${nextD}`, cx); cx.notify(); }).child(`d${this.depth}`);
    const modeGroup = h_flex().p(2).gap(2).rounded(S.radiusLg).bg(alpha(t.chrome, 0.9)).border_1().border_color(t.border)
      .on_mouse_down("left", stop).on_mouse_down("right", stop)
      .child(seg("g-local", "Local", this.mode === "local", "mode:local"))
      .when(this.mode === "local", (e) => e.child(depthBtn))
      .child(seg("g-global", "Global", this.mode === "global", "mode:global"))
      .child(activeSwitch(this.activeNow(), `active:${this.activeNow() ? "off" : "on"}`));
    // One row when it fits; in a narrow panel the zoom buttons go on a second row (shape.js toolbarRows).
    if (toolbarRows(this.W) === 1) {
      return h_flex().id("gtb").absolute().top(6).left(6).right(6).h(26).gap(4).items_center()
        .child(modeGroup).child(touchGroup).child(div().flex_1()).child(zoomGroup);
    }
    return v_flex().id("gtb").absolute().top(6).left(6).right(6).gap(4)
      .child(h_flex().h(26).gap(4).items_center().child(modeGroup).child(touchGroup))
      .child(h_flex().h(26).items_center().child(div().flex_1()).child(zoomGroup));
  }

  hitNode(mx, my) {
    if (!this.g?.nodes) return null;
    if (my < toolbarBottom(toolbarRows(this.W)) || (my > this.H - 24 && mx < 250)) return null;
    const { scale, x: ox, y: oy } = this.view;
    let bestKey = null, bestDist = Infinity;
    for (const n of this.g.nodes.values()) {
      const p = this.sim.pos.get(n.key);
      if (!p || !Number.isFinite(p.x)) continue;
      const x = p.x * scale + ox, y = p.y * scale + oy;
      const hitR = Math.max(8, p.r * scale + 4);
      const dx = x - mx, dy = y - my;
      if (Math.abs(dx) > hitR || Math.abs(dy) > hitR) continue;
      const d = Math.hypot(dx, dy);
      if (d <= hitR && d < bestDist) { bestDist = d; bestKey = n.key; }
    }
    return bestKey;
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-graph", this.handle, () => {});
    // Draw the cached graph. Herdr re-renders when its data changes: mark the model stale and let the timer rebuild
    // it (a command or the first draw rebuilds here, at once).
    if (this.dirty || !this.g) this.rebuild();
    this.stale = true;
    const g = this.g;
    if (this.fadeRunning() || this.wantsFrames()) this.startLoop();
    const zoom = settings().zoom || 1;
    const root = div().id("root").track_focus(this.handle).relative().size_full().min_h(0).overflow_hidden().bg(t.canvas)
      .on_size_change((s, cx) => {
        const W = s.width / zoom, H = s.height / zoom;
        if (Math.abs(W - this.W) > 1 || Math.abs(H - this.H) > 1) { this.W = W; this.H = H; this.autoFit(this.g); cx.notify(); }
      })
      .on_key_down((e, cx) => {
        if (e.key === "=" || e.key === "+") this.zoomAt(1.25, this.W / 2, this.H / 2);
        else if (e.key === "-") this.zoomAt(0.8, this.W / 2, this.H / 2);
        else if (e.key === "0" || e.key === "f") this.fit(this.g);
        else if (e.key === "[" && this.mode === "local") this.command(`depth:${Math.max(1, this.depth - 1)}`, cx);
        else if (e.key === "]" && this.mode === "local") this.command(`depth:${Math.min(3, this.depth + 1)}`, cx);
        else if (e.key === "enter" && this.selected) this.open(this.selected);
        else if (e.key === "escape") { this.selected = null; this.nodeDrag = null; release(this.sim); this.startLoop(); }
        else return;
        cx.stop_propagation(); cx.notify();
      });
    if (!g.nodes.size || (this.mode === "local" && !g.focus)) {
      const words = emptyCopy(this.mode);
      return root.child(v_flex().size_full().child(emptyState({ icon: "graph", title: words.title, body: words.body,
        action: this.mode === "local" ? { id: "to-global", label: "Show the global graph", onClick: (_e, cx) => { this.command("mode:global", cx); cx.notify(); } } : null })))
        .child(this.toolbar(t));
    }
    const { scale: k, x: ox, y: oy } = this.view;
    const W = Math.max(1, this.W), H = Math.max(1, this.H);
    const pt = (key) => { const p = this.sim.pos.get(key); return p && Number.isFinite(p.x) ? [p.x * k + ox, p.y * k + oy] : [0, 0]; };
    const now = Date.now();
    const pathOf = (segs, w, dash) => {
      let p = PathBuilder.stroke(w);
      for (const [[x1, y1], [x2, y2]] of segs) p = p.move_to(x1, y1).line_to(x2, y2);
      if (dash) p = p.dash_array(dash);
      return p.build();
    };
    const layer = (id, segs, w, color, dash) => div().id(id).absolute().left(0).top(0).w(W).h(H).child(window.paint_path(pathOf(segs, w, dash), color));
    // The state of every node (halo, pulse, link strength), set before anything is drawn.
    this.stateOf = new Map([...g.nodes.values()].map((n) => [n.key, this.agentState(n)]));
    this.pulsing = anyPulsing([...this.stateOf.values()].map((state) => ({ state })));
    // Links: 1 px muted lines at rest; incident links on the hovered node render at 1.5 px in the accent colour above
    // the rest. The sibling links are springs only: nothing draws them (or hovers them).
    const restLinks = [], litLinks = [];
    for (const [a, b, kind] of g.edges) {
      if (kind === "sibling") continue;
      const item = { seg: [pt(a), pt(b)], alpha: this.alphaNow(linkId(a, b), now) };
      if (this.hover != null && (a === this.hover || b === this.hover)) litLinks.push(item);
      else restLinks.push(item);
    }
    const linkEls = [
      ...linkBatches(restLinks).map((b, i) => layer(`e-${i}`, b.segs, 1, alpha(t.muted, b.alpha))),
      ...linkBatches(litLinks).map((b, i) => layer(`eh-${i}`, b.segs, 1.5, alpha(t.accent, b.alpha))),
    ];
    const nodes = [], labelItems = [];
    const L = labelLayout(k, this.cfg.scale);
    const lw = 120;
    for (const n of g.nodes.values()) {
      const p = this.sim.pos.get(n.key);
      if (!p || !Number.isFinite(p.x)) continue;
      const [x, y] = pt(n.key);
      if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
      const fp = framePaint(n.kind);
      const rs = p.r * k * fp.scale;
      const na = this.alphaNow(nodeId(n.key), now);
      const color = this.nodeColor(t, n, g.focus);
      // The halo: a filled status-coloured ring under the dot, radius + 4 px; pulsing when working, steady when blocked.
      const st = this.stateOf.get(n.key);
      const ha = haloDrawAlpha({ state: st }, now, na);
      if (ha != null) {
        const haloColor = st === "blocked" ? t.blocked : t.working;
        nodes.push(div().id(`${nodeId(n.key)}-halo`).absolute().left(x - rs - 4).top(y - rs - 4).size((rs + 4) * 2).rounded_full().bg(alpha(haloColor, ha)));
      }
      const tip = [n.label, n.kind === "p" ? n.program?.name : null, n.status ? `${n.status}` : null, n.address ?? null].filter(Boolean).join(" · ");
      nodes.push(div().id(nodeId(n.key)).absolute().left(x - rs).top(y - rs).size(rs * 2).rounded_full().bg(color)
        .border_1().border_color(this.hover === n.key || this.selected === n.key || g.focus === n.key ? t.foreground : t.canvas)
        .opacity(na).cursor_pointer().tooltip(tip));
      // Labels: hovered neighbourhood and selected/focused nodes are pinned; the rest place without overlap until `#` forces all.
      const pill = (this.hover != null && this.near.has(n.key)) || this.selected === n.key;
      const pinned = pill || g.focus === n.key;
      const shown = pinned || this.labelsAll || fp.label ? 1 : labelOpacity(k, this.cfg.opacityScale);
      const la = shown * na;
      if (la > 0.05) {
        labelItems.push({
          key: n.key, kind: n.kind, label: n.label, x, top: y + rs + LABEL_GAP, maxW: lw,
          size: L.size, height: L.height, r: p.r, active: st === "working" || st === "blocked",
          pinned, pill, la, fpLabel: fp.label,
        });
      }
    }
    const chosenLabels = placeLabels(labelItems, this.labelsAll);
    const labels = [];
    for (const it of labelItems) {
      if (!chosenLabels.has(it.key)) continue;
      const labelColor = this.hover === it.key || this.selected === it.key || g.focus === it.key || it.fpLabel ? t.foreground : t.muted;
      if (it.pill) {
        labels.push(h_flex().id(`${nodeId(it.key)}-l`).absolute().left(it.x - lw / 2).top(it.top).w(lw).h(L.height).justify_center().items_center()
          .opacity(it.la)
          .child(div().max_w(lw).truncate().px(4).rounded(3).bg(alpha(t.chrome, 0.9))
            .text_size(L.size).line_height(`${L.lineHeight}px`).font_medium().text_color(labelColor)
            .child(it.label)));
      } else {
        labels.push(div().id(`${nodeId(it.key)}-l`).absolute().left(it.x - lw / 2).top(it.top).w(lw).h(L.height).text_center().truncate()
          .text_size(L.size).line_height(`${L.lineHeight}px`).font_medium().text_color(labelColor).opacity(it.la)
          .child(it.label));
      }
    }
    const f = feed();
    const live = [...g.nodes.values()].filter((n) => (n.kind === "r" || n.kind === "c" || n.kind === "h") && activityOf(n, now)).length;
    const bad = Object.entries(f?.machines ?? {}).filter(([, m]) => !m.ok).map(([k]) => machineLabel(k === "local" ? null : k));
    return root
      .when(Boolean(this.nodeDrag || this.drag?.moved), (e) => e.cursor_grabbing())
      .when(!this.nodeDrag && !this.drag?.moved && Boolean(this.hover), (e) => e.cursor_pointer())
      .on_mouse_down("left", (e, cx) => {
        const p = e.local_position ?? e.position;
        const mx = p.x / zoom, my = p.y / zoom;
        const hit = this.hitNode(mx, my);
        if (hit) {
          const cur = this.sim.pos.get(hit);
          this.nodeDrag = { key: hit, x: mx, y: my, nx: cur.x, ny: cur.y, moved: false, t0: Date.now() };
          this.drag = null;
          this.setHover(hit, cx);
        } else {
          this.nodeDrag = null;
          this.drag = { x: mx, y: my, vx: this.view.x, vy: this.view.y, moved: false };
        }
        cx.notify();
      })
      .on_mouse_down("right", (e, cx) => {
        const p = e.local_position ?? e.position;
        const mx = p.x / zoom, my = p.y / zoom;
        const hit = this.hitNode(mx, my);
        if (hit) {
          this.selected = hit;
          this.menu(hit);
          cx.notify();
        }
      })
      .on_mouse_move((e, cx) => {
        const p = e.local_position ?? e.position;
        const mx = p.x / zoom, my = p.y / zoom;
        if (this.nodeDrag) {
          const dx = mx - this.nodeDrag.x, dy = my - this.nodeDrag.y;
          if (!this.nodeDrag.moved && Math.hypot(dx, dy) < 3) return;
          this.nodeDrag.moved = true;
          const sc = this.view.scale || 1;
          drag(this.sim, this.nodeDrag.key, this.nodeDrag.nx + dx / sc, this.nodeDrag.ny + dy / sc);
          this.view = { ...this.view, manual: true };
          this.startLoop();
          cx.notify();
          return;
        }
        if (this.drag) {
          const dx = mx - this.drag.x, dy = my - this.drag.y;
          if (!this.drag.moved && Math.hypot(dx, dy) < 3) return;
          this.drag.moved = true;
          this.view = panTo(this.view, this.drag.vx + dx, this.drag.vy + dy);
          cx.notify();
          return;
        }
        const nextHover = this.hitNode(mx, my);
        if (nextHover !== this.hover) this.setHover(nextHover, cx);
      })
      .on_mouse_up("left", (_e, cx) => {
        if (this.nodeDrag) {
          const nd = this.nodeDrag;
          this.nodeDrag = null;
          if (nd.moved) { release(this.sim); this.startLoop(); }
          else if (Date.now() - nd.t0 < 500) this.open(nd.key);       // a click: down and up under 500 ms, no drag
          cx.notify();
          return;
        }
        if (this.drag) {
          if (this.drag.moved) this.persist();
          else this.selected = null;
          this.drag = null;
          cx.notify();
        }
      })
      .on_hover((h, cx) => {
        if (h) return;
        // A drag released outside the panel never gets its mouse up: leaving the panel ends it.
        if (this.nodeDrag || this.drag) this.endDrag(cx);
        if (this.hover) this.setHover(null, cx);
      })
      .on_scroll_wheel((e, cx) => {
        const dy = e.delta?.y ?? 0;
        if (!dy) return;
        const p = e.local_position ?? { x: this.W * zoom / 2, y: this.H * zoom / 2 };
        this.zoomAt(Math.exp(dy * 0.004), p.x / zoom, p.y / zoom);
        cx.stop_propagation();
        cx.notify();
      })
      .children(linkEls)
      .children(nodes)
      .children(labels)
      .child(this.toolbar(t))
      .child(h_flex().id("g-foot").absolute().left(8).bottom(6).gap(8).items_center().text_size(10.5).text_color(t.dim)
        .on_mouse_down("left", (_e, cx) => cx.stop_propagation()).on_mouse_down("right", (_e, cx) => cx.stop_propagation())
        .child(div().child(`${g.nodes.size} nodes`))
        .when(live > 0, (e) => e.child(div().text_color(t.working).child(`${live} live`)))
        .when(this.mode === "local", (e) => e.child(div().id("g-foot-depth").px(4).rounded(3).cursor_pointer()
          .hover((s) => s.bg(t.hover).text_color(t.foreground))
          .tooltip(`Cycle Local depth (${this.depth} → ${nextDepth(this.depth, 1)})`)
          .on_click((_e, cx) => { this.command(`depth:${nextDepth(this.depth, 1)}`, cx); cx.notify(); })
          .child(`depth ${this.depth}`)))
        .when(bad.length > 0, (e) => e.child(h_flex().gap(3).items_center().tooltip(`Couldn't scan: ${bad.join(", ")}`).child(icon("alert", 11, t.blocked)).child(div().text_color(t.blocked).child(bad.join(", "))))));
  }
}
