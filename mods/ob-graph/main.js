// ob-graph: Obsidian's graph view of the Herdr world (SPEC 8.C4).
// Nodes: machines (r 9, hollow), spaces (r 7, avatar color), tabs (r 5), terminals/agents (r 5, status
// color), sub-agents (r 3.5: pi runs, Claude agents, hc children; finished ones only with
// "finished" on). Edges: containment (1px border) and sub-agent -> parent session links (1px dashed
// accent), drawn with PathBuilder + window.paint_path in one absolute layer under the nodes.
// Modes: Local (Obsidian's local graph: the inspected / focused session and what is within `depth`
// links of it) and Global (everything). Layout: a deterministic radial tree relaxed by a small force
// simulation; positions are cached per node so nothing jumps.
// Hover highlights a node's neighbours; click selects and goes there; right-click: menu. Drag the
// background to pan, wheel to zoom (0.4..2.5).
// Commands (ob-graph.<cmd>): fit, zoom-in, zoom-out, select:<key>, open:<key>, menu:<key>,
//   finished:<on|off>, mode:<local|global>, depth:<1|2|3>, labels:<on|off>, focus.
// Node keys: m:<machine|local>, s:<spaceId>, t:<tabId>, p:<paneId>, r:<runKey>, c:<claudeKey>, h:<address>.

import { View, div, PathBuilder } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { props, run, nextCommand, settings, machines, spaces, panes, shared, focused } from "herdr";
import {
  S, MARK, tc, alpha, icon, iconButton, statusColor, normStatus, feed, machineLabel, machineOf, tabLabel, paneName,
  takeFocus, openMenu, openView, reveal, isBookmarked, toggleBookmark, emptyState,
} from "./kit.js";
import { splitCmd, sessionOf, inspected, inspect, runTitle, claudeAll, recordRuns, hcChildren } from "./obc.js";

const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* keep in memory */ } };
const R = { m: 9, s: 7, t: 5, p: 5, r: 3.5, c: 3.5, h: 3.5 };
const REST = { m: 0, s: 95, t: 58, p: 44, r: 50, c: 50, h: 50 };   // edge rest length to the parent, by child kind
const MIN_SCALE = 0.4, MAX_SCALE = 2.5;
const hash = (s) => { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967295; };

export default class Graph extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.pos = new Map();          // key -> {x, y} world coordinates (cached layout)
    this.sig = "";
    const v = load("view", null);
    this.view = v && Number.isFinite(v.scale) ? v : { scale: 1, x: 0, y: 0 };
    this.manual = Boolean(v?.manual);
    this.finished = Boolean(load("show", {}).finished);
    this.mode = load("mode", "global") === "local" ? "local" : "global";
    this.depth = Math.max(1, Math.min(3, Number(load("depth", 2)) || 2));
    this.labelsAll = Boolean(load("labels", false));
    this.hover = null;
    this.selected = null;
    this.drag = null;
    this.nodeDrag = null;
    this.W = 0; this.H = 0;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-graph: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  persist() {
    save("view", { ...this.view, manual: this.manual });
    save("show", { finished: this.finished });
    save("mode", this.mode);
    save("depth", this.depth);
    save("labels", this.labelsAll);
  }

  // ---------------------------------------------------------------- model
  // -> { nodes: Map(key -> node), edges: [[a, b, "contain"|"link"]] }
  model() {
    const t = tc();
    const nodes = new Map(), edges = [];
    const add = (n) => { nodes.set(n.key, n); return n; };
    const colors = shared("space.colors") ?? {};
    const ps = panes(), sp = spaces();
    for (const m of machines()) {
      const k = `m:${m.name ?? "local"}`;
      add({ key: k, kind: "m", label: machineLabel(m.name ?? null), machine: m.name ?? null, down: m.layout === "unavailable" });
    }
    if (!nodes.has("m:local")) add({ key: "m:local", kind: "m", label: machineLabel(null), machine: null });
    const paneOf = new Map();
    for (const s of sp) {
      const mk = `m:${s.machine ?? "local"}`;
      if (!nodes.has(mk)) add({ key: mk, kind: "m", label: machineLabel(s.machine), machine: s.machine });
      const c = colors[s.id] ?? "ansi6";
      add({ key: `s:${s.id}`, kind: "s", label: s.name, parent: mk, status: s.status, color: c.startsWith("#") ? c : MARK[c] ?? t[c] ?? t.accent, space: s });
      edges.push([mk, `s:${s.id}`, "contain"]);
      for (const tab of s.tabs) {
        add({ key: `t:${tab.id}`, kind: "t", label: tabLabel(tab, ps), parent: `s:${s.id}`, status: tab.status, space: s, tab });
        edges.push([`s:${s.id}`, `t:${tab.id}`, "contain"]);
        for (const p of ps.filter((x) => x.tab === tab.id)) {
          add({ key: `p:${p.pane}`, kind: "p", label: paneName(p), parent: `t:${tab.id}`, status: p.status, program: p.program, space: s, tab, pane: p, address: p.terminal });
          edges.push([`t:${tab.id}`, `p:${p.pane}`, "contain"]);
          if (p.terminal) paneOf.set(p.terminal, `p:${p.pane}`);
        }
      }
    }
    // Sub-agents hang off their parent session's pane; without one, off their machine.
    const sub = (key, kind, label, status, live, parentAddr, machine, extra) => {
      if (!live && !this.finished) return;
      const par = (parentAddr && paneOf.get(parentAddr)) || `m:${machine ?? "local"}`;
      if (!nodes.has(par)) return;
      add({ key, kind, label, status, live, parent: par, orphan: !paneOf.get(parentAddr), ...extra });
      edges.push([par, key, paneOf.get(parentAddr) ? "link" : "contain"]);
    };
    const f = feed();
    for (const r of [...recordRuns(), ...(f?.runs ?? [])]) sub(`r:${r.key}`, "r", `${runTitle(r)} · ${r.short}`, r.state, r.live, r.parent, r.machine, { run: r });
    for (const c of claudeAll()) sub(`c:${c.key}`, "c", c.desc || c.type || c.id, c.live ? (c.state === "blocked" ? "blocked" : "working") : "ok", c.live, c.parent, c.machine, { claude: c });
    for (const k of hcChildren(null)) sub(`h:${k.address}`, "h", k.name || k.title || k.address, typeof k.status === "string" ? k.status : k.status?.state ?? "working", true, k.parent, machineOf(k.address), { address: k.address });
    return { nodes, edges };
  }

  // The local graph: nodes within `depth` links of the focus (never walking through a machine).
  localize(model) {
    const { address } = inspected();
    let focus = null;
    if (address) for (const n of model.nodes.values()) if (n.address === address) { focus = n.key; break; }
    if (!focus) {
      const fp = focused();
      focus = fp?.pane && model.nodes.has(`p:${fp.pane}`) ? `p:${fp.pane}` : fp?.tab && model.nodes.has(`t:${fp.tab}`) ? `t:${fp.tab}` : null;
    }
    if (!focus) return { ...model, focus: null };
    const adj = new Map();
    for (const [a, b] of model.edges) { (adj.get(a) ?? adj.set(a, []).get(a)).push(b); (adj.get(b) ?? adj.set(b, []).get(b)).push(a); }
    const keep = new Set([focus]);
    let front = [focus];
    for (let d = 0; d < this.depth; d++) {
      const next = [];
      for (const k of front) for (const o of adj.get(k) ?? []) if (!keep.has(o)) { keep.add(o); if (!o.startsWith("m:")) next.push(o); }
      front = next;
    }
    // Always show the path up to the machine, so the local graph says where it is.
    for (let k = focus; k; k = model.nodes.get(k)?.parent) keep.add(k);
    const nodes = new Map([...model.nodes].filter(([k]) => keep.has(k)));
    return { nodes, edges: model.edges.filter(([a, b]) => keep.has(a) && keep.has(b)), focus };
  }

  // ---------------------------------------------------------------- layout
  layoutGraph(g) {
    const nodes = [...g.nodes.values()];
    const kids = new Map();
    let roots;
    if (g.focus) {
      // Local graph: a tree grown from the focused session outwards, so it sits in the middle.
      const adj = new Map();
      for (const [x, y] of g.edges) { (adj.get(x) ?? adj.set(x, []).get(x)).push(y); (adj.get(y) ?? adj.set(y, []).get(y)).push(x); }
      const seen = new Set([g.focus]);
      let front = [g.focus];
      while (front.length) {
        const next = [];
        for (const k of front) for (const o of adj.get(k) ?? []) if (!seen.has(o)) { seen.add(o); (kids.get(k) ?? kids.set(k, []).get(k)).push(o); next.push(o); }
        front = next;
      }
      roots = [g.focus, ...nodes.map((n) => n.key).filter((k) => !seen.has(k))];
    } else {
      for (const n of nodes) if (n.parent && g.nodes.has(n.parent)) (kids.get(n.parent) ?? kids.set(n.parent, []).get(n.parent)).push(n.key);
      roots = nodes.filter((n) => !n.parent || !g.nodes.has(n.parent)).map((n) => n.key);
    }
    const weight = new Map();
    const wOf = (k) => { if (weight.has(k)) return weight.get(k); const w = Math.max(1, (kids.get(k) ?? []).reduce((s, c) => s + wOf(c), 0)); weight.set(k, w); return w; };
    roots.forEach(wOf);
    const target = new Map();
    const place = (k, a0, a1, r) => {
      const a = (a0 + a1) / 2;
      target.set(k, { x: Math.cos(a) * r, y: Math.sin(a) * r });
      const cs = kids.get(k) ?? [];
      const tot = cs.reduce((s, c) => s + wOf(c), 0) || 1;
      let at = a0;
      for (const c of cs) {
        const span = ((a1 - a0) * wOf(c)) / tot;
        const kind = g.nodes.get(c).kind;
        place(c, at, at + span, r + (REST[kind] || 70) * (r === 0 ? 1.1 : 1));
        at += span;
      }
    };
    const total = roots.reduce((s, k) => s + wOf(k), 0) || 1;
    if (roots.length === 1) place(roots[0], -Math.PI / 2, Math.PI * 1.5, 0);
    else {
      let at = -Math.PI / 2;
      const R0 = Math.max(70, roots.length * 26);
      for (const k of roots) { const span = (Math.PI * 2 * wOf(k)) / total; place(k, at, at + span, R0); at += span; }
    }
    // Fit the drawing to the panel's shape: stretch the targets along its long side.
    const ky = Math.sqrt(this.aspect()), kx = 1 / ky;
    for (const p of target.values()) { p.x *= kx; p.y *= ky; }
    // Start from the cache (known nodes) or the radial target (new ones, nudged so none coincide).
    const P = new Map();
    let known = 0;
    for (const n of nodes) {
      const c = this.pos.get(n.key);
      if (c) { P.set(n.key, { ...c }); known++; }
      else { const tg = target.get(n.key); P.set(n.key, { x: tg.x + (hash(n.key) - 0.5) * 6, y: tg.y + (hash(n.key + "y") - 0.5) * 6 }); }
    }
    const iters = known === nodes.length ? 0 : known > nodes.length / 2 ? 40 : 110;
    // Typed arrays: this runs inside render, so it must stay well under a frame's script budget.
    const keys = nodes.map((n) => n.key);
    const N = keys.length, idx = new Map(keys.map((k, i) => [k, i]));
    const X = new Float64Array(N), Y = new Float64Array(N), TX = new Float64Array(N), TY = new Float64Array(N), FX = new Float64Array(N), FY = new Float64Array(N);
    keys.forEach((k, i) => { const p = P.get(k), tg = target.get(k); X[i] = p.x; Y[i] = p.y; TX[i] = tg.x; TY[i] = tg.y; });
    const E = g.edges.map(([a, b]) => [idx.get(a), idx.get(b), REST[g.nodes.get(b)?.kind] || 60]).filter(([a, b]) => a != null && b != null);
    for (let it = 0; it < iters; it++) {
      const cool = 1 - it / iters;
      FX.fill(0); FY.fill(0);
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          let dx = X[i] - X[j], dy = Y[i] - Y[j];
          let d2 = dx * dx + dy * dy;
          if (d2 > 160000) continue;
          if (d2 < 1) { dx = ((i * 7 + j * 13) % 11) / 11 - 0.5; dy = ((i * 5 + j * 3) % 7) / 7 - 0.5; d2 = 1; }
          const d = Math.sqrt(d2), f = 1300 / d2 / d;
          FX[i] += dx * f; FY[i] += dy * f; FX[j] -= dx * f; FY[j] -= dy * f;
        }
      }
      for (const [a, b, rest] of E) {
        const dx = X[b] - X[a], dy = Y[b] - Y[a], d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const f = ((d - rest) * 0.06) / d;
        FX[a] += dx * f; FY[a] += dy * f; FX[b] -= dx * f; FY[b] -= dy * f;
      }
      const lim = 12 * cool + 0.5;
      for (let i = 0; i < N; i++) {
        const fx = FX[i] + (TX[i] - X[i]) * 0.02, fy = FY[i] + (TY[i] - Y[i]) * 0.02;
        const m = Math.sqrt(fx * fx + fy * fy), s = m > lim ? lim / m : 1;
        X[i] += fx * s; Y[i] += fy * s;
      }
    }
    keys.forEach((k, i) => P.set(k, { x: X[i], y: Y[i] }));
    for (const [k, p] of P) this.pos.set(k, p);
    // Forget positions of nodes gone for good (keep the cache small).
    if (this.pos.size > 600) for (const k of [...this.pos.keys()]) if (!g.nodes.has(k)) this.pos.delete(k);
  }

  aspect() { return this.W && this.H ? Math.max(0.6, Math.min(2.2, this.H / this.W)) : 1; }

  bounds(g) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const k of g.nodes.keys()) { const p = this.pos.get(k); if (!p) continue; x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }
    return Number.isFinite(x0) ? { x0, y0, x1, y1 } : { x0: 0, y0: 0, x1: 0, y1: 0 };
  }

  fit(g) {
    if (!this.W || !this.H || !g) return;
    const b = this.bounds(g);
    const pad = 44;
    const bw = Math.max(1, b.x1 - b.x0), bh = Math.max(1, b.y1 - b.y0);
    const scale = Math.max(MIN_SCALE, Math.min(1.6, (this.W - pad * 2) / bw, (this.H - pad * 2 - 20) / bh));
    this.view = { scale, x: this.W / 2 - ((b.x0 + b.x1) / 2) * scale, y: (this.H + 14) / 2 - ((b.y0 + b.y1) / 2) * scale };
    this.manual = false;
  }

  zoomAt(factor, px, py) {
    const s0 = this.view.scale;
    const s1 = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s0 * factor));
    if (s1 === s0) return;
    this.view = { scale: s1, x: px - ((px - this.view.x) / s0) * s1, y: py - ((py - this.view.y) / s0) * s1 };
    this.manual = true;
    this.persist();
  }

  // ---------------------------------------------------------------- actions
  open(key) {
    const n = this.g?.nodes.get(key) ?? this.model().nodes.get(key);
    if (!n) return;
    this.selected = key;
    if (n.kind === "m") { const s = spaces().find((x) => (x.machine ?? null) === n.machine); if (s) run("space.select", { id: s.id }); }
    else if (n.kind === "s") run("space.select", { id: n.space.id });
    else if (n.kind === "t") reveal({ space: n.space.id, tab: n.tab.id });
    else if (n.kind === "p") reveal({ space: n.space.id, tab: n.tab.id, pane: n.pane.pane });
    else if (n.kind === "r") openView("ob-subagents", `run:${n.run.key}`);
    else if (n.kind === "c") openView("ob-subagents", `run:${n.claude.key}`);
    else if (n.kind === "h") run("terminal.peek", { terminal: n.address });
  }

  menu(key) {
    const n = this.g?.nodes.get(key);
    if (!n) return;
    const addr = n.address ?? n.run?.parent ?? n.claude?.parent ?? null;
    const bm = n.kind === "s" ? ["space", n.space.id] : n.kind === "t" ? ["tab", n.tab.id] : n.kind === "p" && n.address ? ["terminal", n.address] : n.kind === "r" ? ["run", n.run.key] : null;
    openMenu([
      { label: n.kind === "r" || n.kind === "c" ? "Open in Subagents" : n.kind === "h" ? "Peek" : "Reveal", icon: "locate", command: `ob-graph.open:${key}` },
      ...(addr ? [{ label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${addr}` }] : []),
      ...(n.kind === "p" && n.address ? [{ label: "Local graph of this session", icon: "graph", command: `ob-graph.focus-on:${n.address}` }] : []),
      ...(bm ? [{ label: isBookmarked(bm[0], bm[1]) ? "Remove bookmark" : "Bookmark", icon: "bookmark", command: `ob-graph.bookmark:${key}` }] : []),
    ], { width: 230, title: n.label });
  }

  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    const cxW = this.W / 2, cxH = this.H / 2;
    if (verb === "fit") { this.fit(this.g); this.persist(); }
    else if (verb === "zoom-in") this.zoomAt(1.25, cxW, cxH);
    else if (verb === "zoom-out") this.zoomAt(0.8, cxW, cxH);
    else if (verb === "select") this.selected = arg || null;
    else if (verb === "open") this.open(arg);
    else if (verb === "menu") this.menu(arg);
    else if (verb === "finished") { this.finished = arg !== "off"; this.refit = true; this.persist(); }
    else if (verb === "mode") { this.mode = arg === "local" ? "local" : "global"; this.refit = true; this.persist(); }
    else if (verb === "depth") { this.depth = Math.max(1, Math.min(3, Number(arg) || 2)); this.refit = true; this.persist(); }
    else if (verb === "labels") { this.labelsAll = arg !== "off"; this.persist(); }
    else if (verb === "focus-on") { inspect(arg || null); this.mode = "local"; this.refit = true; this.persist(); }
    else if (verb === "bookmark") {
      const n = this.g?.nodes.get(arg);
      if (n?.kind === "s") toggleBookmark({ kind: "space", id: n.space.id, label: n.label, machine: n.space.machine ?? null });
      else if (n?.kind === "t") toggleBookmark({ kind: "tab", id: n.tab.id, label: n.label, machine: n.space.machine ?? null });
      else if (n?.kind === "p" && n.address) toggleBookmark({ kind: "terminal", id: n.address, label: n.label, machine: machineOf(n.address) });
      else if (n?.kind === "r") toggleBookmark({ kind: "run", id: n.run.key, label: runTitle(n.run), machine: n.run.machine });
    }
    else if (verb === "focus") this.handle.focus();
  }

  // ---------------------------------------------------------------- render
  nodeColor(t, n) {
    if (n.kind === "m") return n.down ? t.dim : t.muted;
    if (n.kind === "s") return n.color;
    if (n.kind === "t") return n.status ? statusColor(t, n.status) : alpha(t.muted, 0.8);
    const k = normStatus(n.status);
    if (!k) return alpha(t.dim, 0.9);
    return k === "ok" ? t.ansi2 : statusColor(t, n.status);
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
    return h_flex().id("gtb").absolute().top(6).left(6).right(6).h(26).gap(4).items_center()
      .child(h_flex().p(2).gap(2).rounded(S.radiusLg).bg(alpha(t.chrome, 0.9)).border_1().border_color(t.border)
        .on_mouse_down("left", stop).on_mouse_down("right", stop)
        .child(seg("g-local", "Local", this.mode === "local", "mode:local"))
        .child(seg("g-global", "Global", this.mode === "global", "mode:global")))
      .child(div().flex_1())
      .child(h_flex().p(2).gap(1).rounded(S.radiusLg).bg(alpha(t.chrome, 0.9)).border_1().border_color(t.border)
        .on_mouse_down("left", stop).on_mouse_down("right", stop)
        .child(iconButton({ id: "g-finished", icon: "circle-check", size: 22, iconSize: 13, active: this.finished, tip: this.finished ? "Hide finished sub-agents" : "Show finished sub-agents", onClick: (_e, cx) => { this.command(`finished:${this.finished ? "off" : "on"}`, cx); cx.notify(); } }))
        .child(iconButton({ id: "g-labels", icon: "hash", size: 22, iconSize: 13, active: this.labelsAll, tip: this.labelsAll ? "Labels: all" : "Labels: machines and spaces (hover for the rest)", onClick: (_e, cx) => { this.command(`labels:${this.labelsAll ? "off" : "on"}`, cx); cx.notify(); } }))
        .child(txt("g-out", "−", "Zoom out", "zoom-out"))
        .child(txt("g-in", "+", "Zoom in", "zoom-in"))
        .child(iconButton({ id: "g-fit", icon: "maximize", size: 22, iconSize: 13, tip: "Fit to view", onClick: (_e, cx) => { this.command("fit", cx); cx.notify(); } })));
  }

  hitNode(mx, my) {
    if (!this.g?.nodes) return null;
    if (my < 36 || (my > this.H - 24 && mx < 250)) return null;
    const { scale, x: ox, y: oy } = this.view;
    const ns = Math.max(0.75, Math.min(1.6, Math.sqrt(scale)));
    let bestKey = null, bestDist = Infinity;
    for (const n of this.g.nodes.values()) {
      const p = this.pos.get(n.key);
      if (!p) continue;
      const x = p.x * scale + ox, y = p.y * scale + oy;
      const hitR = Math.max(10, (R[n.kind] ?? 5) * ns + 4);
      const dx = x - mx, dy = y - my;
      if (Math.abs(dx) > hitR || Math.abs(dy) > hitR) continue;
      const d = Math.hypot(dx, dy);
      if (d <= hitR && d < bestDist) {
        bestDist = d;
        bestKey = n.key;
      }
    }
    return bestKey;
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-graph", this.handle, () => {});
    const full = this.model();
    const g = this.mode === "local" ? this.localize(full) : { ...full, focus: null };
    this.g = g;
    // Re-lay out only when the structure changed.
    const sig = (g.focus ?? "") + "|" + [...g.nodes.keys()].join("|") + "#" + g.edges.length + "@" + Math.round(this.aspect() * 4);
    if (sig !== this.sig) {
      const T1 = Date.now();
      // A new panel shape lays everything out again (from the radial targets, not the cache).
      if (this.sig && sig.split("@")[1] !== this.sig.split("@")[1]) this.pos.clear();
      this.layoutGraph(g);
      this.sig = sig;
      console.log(`ob-graph: layout ${Date.now() - T1}ms ${g.nodes.size} nodes`);
      if (!this.manual || this.refit) this.fit(g);
      this.refit = false;
    } else if (this.refit) { this.fit(g); this.refit = false; }
    const zoom = settings().zoom || 1;
    const root = div().id("root").track_focus(this.handle).relative().size_full().min_h(0).overflow_hidden().bg(t.chrome)
      .on_size_change((s, cx) => {
        const W = s.width / zoom, H = s.height / zoom;
        if (Math.abs(W - this.W) > 1 || Math.abs(H - this.H) > 1) { this.W = W; this.H = H; this.fit(this.g); cx.notify(); }
      })
      .on_key_down((e, cx) => {
        if (e.key === "=" || e.key === "+") this.zoomAt(1.25, this.W / 2, this.H / 2);
        else if (e.key === "-") this.zoomAt(0.8, this.W / 2, this.H / 2);
        else if (e.key === "0" || e.key === "f") this.fit(this.g);
        else if (e.key === "enter" && this.selected) this.open(this.selected);
        else if (e.key === "escape") this.selected = null;
        else return;
        cx.stop_propagation(); cx.notify();
      });
    if (!g.nodes.size || (this.mode === "local" && !g.focus)) {
      return root.child(v_flex().size_full().child(emptyState({ icon: "graph", title: this.mode === "local" ? "No session focused" : "Nothing to draw",
        body: this.mode === "local" ? "The local graph follows the focused session. Switch to Global to see every machine." : "Machines, spaces, tabs and agents appear here.",
        action: this.mode === "local" ? { id: "to-global", label: "Show the global graph", onClick: (_e, cx) => { this.command("mode:global", cx); cx.notify(); } } : null })))
        .child(this.toolbar(t));
    }
    const { scale, x: ox, y: oy } = this.view;
    const W = Math.max(1, this.W), H = Math.max(1, this.H);
    const scr = (k) => { const p = this.pos.get(k) ?? { x: 0, y: 0 }; return [p.x * scale + ox, p.y * scale + oy]; };
    const focusKey = this.hover ?? this.selected;
    const near = new Set(focusKey ? [focusKey] : []);
    if (focusKey) for (const [a, b] of g.edges) { if (a === focusKey) near.add(b); if (b === focusKey) near.add(a); }
    const dimmed = (k) => focusKey && !near.has(k);
    // Edges: four paths (containment / sub-agent link, each normal or highlighted).
    const groups = { c: [], ch: [], l: [], lh: [] };
    for (const [a, b, kind] of g.edges) {
      const hl = focusKey && (a === focusKey || b === focusKey);
      groups[(kind === "link" ? "l" : "c") + (hl ? "h" : "")].push([scr(a), scr(b)]);
    }
    const pathOf = (segs, w, dash) => {
      let p = PathBuilder.stroke(w);
      for (const [[x1, y1], [x2, y2]] of segs) p = p.move_to(x1, y1).line_to(x2, y2);
      if (dash) p = p.dash_array(dash);
      return p.build();
    };
    const layer = (id, segs, w, color, dash) => (segs.length ? div().id(id).absolute().left(0).top(0).w(W).h(H).child(window.paint_path(pathOf(segs, w, dash), color)) : null);
    const ns = Math.max(0.75, Math.min(1.6, Math.sqrt(scale)));
    const nodes = [], labels = [];
    for (const n of g.nodes.values()) {
      const [x, y] = scr(n.key);
      if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
      const r = R[n.kind] * ns;
      const color = this.nodeColor(t, n);
      const sel = this.selected === n.key, isFocus = g.focus === n.key;
      const st = normStatus(n.status);
      const id = `n-${n.key}`;
      const dim = dimmed(n.key);
      if (st === "working" && (n.kind === "p" || n.kind === "r" || n.kind === "c" || n.kind === "h")) {
        nodes.push(div().id(`${id}-halo`).absolute().left(x - r - 4).top(y - r - 4).size(r * 2 + 8).rounded_full().bg(alpha(t.working, 0.28))
          .loop("opacity", { from: 0.2, to: 1, period: 1200 }));
      }
      if (st === "blocked" && n.kind === "p") {
        nodes.push(div().id(`${id}-halo`).absolute().left(x - r - 4).top(y - r - 4).size(r * 2 + 8).rounded_full().bg(alpha(t.blocked, 0.3))
          .loop("opacity", { from: 0.3, to: 1, period: 1100 }));
      }
      const tip = [n.label, n.kind === "p" ? n.program?.name : null, n.status ? `${n.status}` : null, n.address ?? null].filter(Boolean).join(" · ");
      let el = div().id(id).absolute().left(x - r).top(y - r).size(r * 2).rounded_full().cursor_pointer()
        .tooltip(tip);
      if (n.kind === "m") el = el.bg(t.chrome).border(1.5 * ns).border_color(color);
      else el = el.bg(color).when(n.kind === "p" && !n.status, (e) => e.border(1).border_color(t.muted));
      if (n.orphan) el = el.opacity(0.7);
      if (sel || isFocus) el = el.border(2).border_color(t.accent);
      if (dim) el = el.opacity(0.3);
      nodes.push(el);
      const always = n.kind === "m" || n.kind === "s" || this.labelsAll || (scale >= 1.35 && n.kind !== "r" && n.kind !== "c");
      if (always || sel || isFocus || near.has(n.key)) {
        const lw = n.kind === "m" ? 140 : 120;
        labels.push(div().id(`${id}-l`).absolute().left(x - lw / 2).top(y + r + 2).w(lw).h(14).text_center().truncate()
          .text_size(n.kind === "m" ? 11 : 10).when(n.kind === "m" || n.kind === "s", (e) => e.font_medium())
          .text_color(this.hover === n.key || sel ? t.foreground : n.kind === "m" ? t.muted : t.dim).when(Boolean(dim), (e) => e.opacity(0.35))
          .child(n.label));
      }
    }
    const f = feed();
    const live = [...g.nodes.values()].filter((n) => (n.kind === "r" || n.kind === "c" || n.kind === "h") && n.live).length;
    const bad = Object.entries(f?.machines ?? {}).filter(([, m]) => !m.ok).map(([k]) => machineLabel(k === "local" ? null : k));
    return root
      .when(Boolean(this.nodeDrag || this.drag?.moved), (e) => e.cursor_grabbing())
      .when(!this.nodeDrag && !this.drag?.moved && Boolean(this.hover), (e) => e.cursor_pointer())
      .on_mouse_down("left", (e, cx) => {
        const p = e.local_position ?? e.position;
        const mx = p.x / zoom, my = p.y / zoom;
        const hit = this.hitNode(mx, my);
        if (hit) {
          const cur = this.pos.get(hit) ?? { x: 0, y: 0 };
          this.nodeDrag = { key: hit, x: mx, y: my, nx: cur.x, ny: cur.y, moved: false };
          this.drag = null;
          this.hover = hit;
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
          this.pos.set(this.nodeDrag.key, {
            x: this.nodeDrag.nx + dx / sc,
            y: this.nodeDrag.ny + dy / sc,
          });
          this.manual = true;
          cx.notify();
          return;
        }
        if (this.drag) {
          const dx = mx - this.drag.x, dy = my - this.drag.y;
          if (!this.drag.moved && Math.hypot(dx, dy) < 3) return;
          this.drag.moved = true;
          this.view = { ...this.view, x: this.drag.vx + dx, y: this.drag.vy + dy };
          this.manual = true;
          cx.notify();
          return;
        }
        const nextHover = this.hitNode(mx, my);
        if (nextHover !== this.hover) {
          this.hover = nextHover;
          cx.notify();
        }
      })
      .on_mouse_up("left", (_e, cx) => {
        if (this.nodeDrag) {
          const nd = this.nodeDrag;
          this.nodeDrag = null;
          if (!nd.moved) this.open(nd.key);
          else this.persist();
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
        if (!h) {
          if (!this.nodeDrag && !this.drag && this.hover) {
            this.hover = null;
            cx.notify();
          }
        }
      })
      .on_scroll_wheel((e, cx) => {
        const dy = e.delta?.y ?? 0;
        if (!dy) return;
        const p = e.local_position ?? { x: this.W * zoom / 2, y: this.H * zoom / 2 };
        this.zoomAt(Math.exp(dy * 0.004), p.x / zoom, p.y / zoom);
        cx.stop_propagation();
        cx.notify();
      })
      .children([
        layer("e-c", groups.c, 1, focusKey ? alpha(t.border, 0.6) : t.border),
        layer("e-l", groups.l, 1, alpha(t.accent, focusKey ? 0.3 : 0.55), [3, 3]),
        layer("e-ch", groups.ch, 1.5, t.muted),
        layer("e-lh", groups.lh, 1.5, t.accent, [3, 3]),
      ].filter(Boolean))
      .children(nodes)
      .children(labels)
      .child(this.toolbar(t))
      .child(h_flex().id("g-foot").absolute().left(8).bottom(6).gap(8).items_center().text_size(10.5).text_color(t.dim)
        .on_mouse_down("left", (_e, cx) => cx.stop_propagation()).on_mouse_down("right", (_e, cx) => cx.stop_propagation())
        .child(div().child(`${g.nodes.size} nodes`))
        .when(live > 0, (e) => e.child(div().text_color(t.working).child(`${live} live`)))
        .when(this.mode === "local", (e) => e.child(div().child(`depth ${this.depth}`)))
        .when(bad.length > 0, (e) => e.child(h_flex().gap(3).items_center().tooltip(`Couldn't scan: ${bad.join(", ")}`).child(icon("alert", 11, t.blocked)).child(div().text_color(t.blocked).child(bad.join(", "))))));
  }
}
