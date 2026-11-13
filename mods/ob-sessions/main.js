// ob-sessions: the Obsidian file explorer, for sessions. machine > space > tab > pane > sub-agents.
// Carries iv-spaces forward (machine groups, connection state, hide/fold machines, Connect for
// rebuilt machines, login guidance, colored avatars, git tail, worktrees under their repo, drag to
// reorder, "skip a level with one child", fold state per id) and adds Obsidian's toolbar (new tab,
// new space, sort, auto-reveal, collapse/expand all), a fuzzy filter, indent guides, sub-agent
// children and badges from the shared feed, context menus (ob-menu), keyboard navigation and reveal.
//
// Commands (herdr-app do ob-sessions.<cmd>): focus, reveal, collapse-all, expand-all, sort:<mode>,
// auto-reveal:<on|off|toggle>, filter:<text>, menu[:<rowKey>], rename, close, open-right, new-tab,
// new-space, up, down, left, right, enter, toggle, cursor:<rowKey>, fold:<rowKey>,
// hide-machine:<name>, show-machine:<name>, connect:<name>, bookmark:<rowKey>, inspect:<address>,
// move-to:<tabId>, move:<fromKey>@<toKey> (the drag's drop, for tests).  Row keys: m:<machine|local> s:<space> t:<tab> p:<pane> r:<run> c:<claude> h:<addr>.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, Input, InputState, ScrollHandle, Scrollbar } from "gpui-base";
import {
  spaces, machines, panes, terminals, focused, agents, run, hc, theme, shared, setShared, props,
  nextCommand, settings, window as appWindow,
} from "herdr";
import {
  S, alpha, icon, programIcon, normStatus, RANK, statusMark, needsYou, iconButton, badge, treeRow,
  avatar, emptyState, inputFrame, openMenu, ago, dur, tilde, fuzzy, highlight, takeFocus, bindingFor,
  chordLabel, isBookmarked, toggleBookmark, machineLabel, tabLabel, paneName, place, openView,
} from "./kit.js";
import { Git } from "./git.js";
import { subItems, counts } from "./sub.js";

const SORTS = [
  ["manual", "Manual (drag to reorder)"],
  ["name", "Name (A to Z)"],
  ["name-desc", "Name (Z to A)"],
  ["activity", "Last activity"],
  ["status", "Needs attention first"],
];
const PALETTE = ["ansi6", "ansi3", "ansi4", "ansi5", "ansi2", "ansi1"];
const MAX_DONE = 3; // finished sub-agents shown under a session before "n earlier"
const SUB_KINDS = new Set(["run", "claude", "child"]);
const mkey = (m) => `m:${m ?? "local"}`;

function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } }
function splitCmd(c) { const s = String(c ?? ""); const i = s.indexOf(":"); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; }
const keyLabel = (action) => { const k = bindingFor(action); return k ? ` (${chordLabel(k)})` : ""; };

// A fuzzy match that stays readable: letters in order, not spread over the whole label.
function matchQ(q, text) {
  const f = fuzzy(q, text);
  if (!f) return null;
  const n = q.replace(/\s+/g, "").length;
  if (!f.hits.length) return f;
  const span = f.hits[f.hits.length - 1] - f.hits[0] + 1;
  return span <= n * 3 + 2 ? f : null;
}

export default class Sessions extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.filter = String(load("filter", "") ?? "");
    this.input = InputState.new({ placeholder: "Filter sessions…", value: this.filter });
    this.input.on("change", (_e, cx) => { this.setFilter(this.input.value()); cx.notify(); });
    this.input.on("submit", (_e, cx) => { const r = this.rows?.find((x) => x.node && x.node.kind !== "machine"); if (r) this.activate(r.node); cx.notify(); });
    this.input.on("focus", (_e, cx) => { this.inputFocused = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.inputFocused = false; cx.notify(); });
    this.open = load("tree.open", {});
    this.folded = new Set(load("machines.folded", []));
    this.hidden = new Set(load("machines.hidden", []));
    this.reconnecting = load("machines.reconnecting", {});
    for (const st of Object.values(this.reconnecting)) if (st) st.busy = false;
    this.sort = SORTS.some(([id]) => id === load("sort", "manual")) ? load("sort", "manual") : "manual";
    this.autoReveal = Boolean(load("autoReveal", false));
    this.git = new Git();
    this.machinesLs = [];
    this.cursor = null;
    this.kbd = false;
    this.pressed = null;
    this.over = null;
    this.hover = null;
    this.filterExpand = new Set();
    this.pendingReveal = null;
    this.lastFocus = undefined;
    this.lastAct = {};
    this.copied = null;
    this.rows = [];
    this.refreshMachines(cx);
    cx.timer.every(15000, (cx) => this.refreshMachines(cx));
    cx.timer.every(30000, (cx) => cx.notify()); // elapsed times and the git fallback
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c, cx); } catch (e) { console.log(`ob-sessions: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  // ------------------------------------------------------------------ machines
  refreshMachines(cx) {
    cx.spawn(async (cx) => {
      try {
        const r = await hc(["machine", "ls", "--json"]);
        if (r.code === 0) this.machinesLs = (JSON.parse(r.stdout).machines ?? []).filter((m) => !m.temporary);
      } catch { /* keep the last list */ }
      cx.notify();
    });
  }
  rebuilt(machine) { return machine?.state === "unreachable" && /^a different core answers there \("[^"]+"\)$/.test(machine.why ?? ""); }
  reconnect(name, cx) {
    const machine = this.machinesLs.find((k) => k.name === name) ?? this.reconnecting[name]?.machine;
    if (!machine || this.reconnecting[name]?.busy) return;
    const state = this.reconnecting[name] ??= { machine, removed: false };
    state.busy = true; state.error = null;
    save("machines.reconnecting", this.reconnecting);
    cx.spawn(async (cx) => {
      try {
        const ask = async (args) => {
          const r = await hc([...args, "--json"]);
          if (r.code !== 0) {
            let error;
            try { error = JSON.parse(r.stdout || r.stderr).error?.message; } catch { /* plain text */ }
            throw new Error(error || r.stderr || r.stdout || "Couldn't connect.");
          }
        };
        if (!state.removed) { await ask(["machine", "rm", name]); state.removed = true; save("machines.reconnecting", this.reconnecting); }
        const args = ["machine", "add"];
        if (machine.via) args.push("--via", machine.target); else args.push(machine.target);
        args.push("--name", name);
        if (machine.session) args.push("--session", machine.session);
        await ask(args);
        this.folded.delete(mkey(name)); save("machines.folded", [...this.folded]);
        delete this.reconnecting[name];
      } catch (e) { state.error = String(e?.message ?? e); state.busy = false; }
      save("machines.reconnecting", this.reconnecting);
      this.refreshMachines(cx);
      cx.notify();
    });
  }
  setHidden(m, hide) {
    if (!m) return;
    hide ? this.hidden.add(m) : this.hidden.delete(m);
    save("machines.hidden", [...this.hidden]);
  }

  // ------------------------------------------------------------------ fold state
  isOpen(n) {
    if (n.kind === "machine") return !this.folded.has(n.key);
    if (!n.children.length) return false;
    return this.open[n.key] ?? n.defaultOpen;
  }
  setOpen(n, v) {
    if (n.kind === "machine") { v ? this.folded.delete(n.key) : this.folded.add(n.key); save("machines.folded", [...this.folded]); return; }
    this.open[n.key] = v;
    save("tree.open", this.open);
  }
  setFilter(text) {
    const v = String(text ?? "");
    if (v === this.filter) return;
    this.filter = v;
    this.filterExpand.clear();
    save("filter", v);
  }

  // ------------------------------------------------------------------ the model
  // A tree of nodes: { key, kind, label, text, children, parent, defaultOpen, reps: {machine, space, tab, pane, terminal}, ... }
  sortSpaces(list) {
    const by = this.sort;
    const order = new Map(spaces().map((s, i) => [s.id, i]));
    const act = (s) => Math.max(0, ...(s.tabs ?? []).map((x) => x.changed_at ?? 0));
    const out = [...list];
    if (by === "name") out.sort((a, b) => a.name.localeCompare(b.name));
    else if (by === "name-desc") out.sort((a, b) => b.name.localeCompare(a.name));
    else if (by === "activity") out.sort((a, b) => act(b) - act(a) || order.get(a.id) - order.get(b.id));
    else if (by === "status") out.sort((a, b) => (RANK[normStatus(b.status)] ?? -1) - (RANK[normStatus(a.status)] ?? -1) || order.get(a.id) - order.get(b.id));
    return out;
  }
  sortTabs(list, ps) {
    const by = this.sort;
    const out = [...(list ?? [])];
    const label = (x) => tabLabel(x, ps);
    if (by === "name") out.sort((a, b) => label(a).localeCompare(label(b)));
    else if (by === "name-desc") out.sort((a, b) => label(b).localeCompare(label(a)));
    else if (by === "activity") out.sort((a, b) => (b.changed_at ?? 0) - (a.changed_at ?? 0) || a.index - b.index);
    else if (by === "status") out.sort((a, b) => (RANK[normStatus(b.status)] ?? -1) - (RANK[normStatus(a.status)] ?? -1) || a.index - b.index);
    return out;
  }

  model() {
    const now = Date.now();
    const sp = spaces(), ps = panes(), ts = terminals();
    const byKey = new Map();
    const add = (n, parent) => { n.parent = parent ?? null; n.children ??= []; byKey.set(n.key, n); if (parent) parent.children.push(n); return n; };
    const subs = (addr, parent) => {
      const items = subItems(addr, ts, now);
      parent.subs = items;
      for (const it of items) add({ key: it.key, kind: it.kind, label: it.label, text: it.text, sub: it, reps: { terminal: addr, machine: parent.reps.machine } }, parent);
      parent.liveSubs = items.some((i) => i.live);
    };
    const paneNode = (w, tab, p, parent) => {
      const n = add({ key: `p:${p.pane}`, kind: "pane", label: paneName(p), text: paneName(p), space: w, tab, pane: p,
        reps: { machine: w.machine ?? null, space: w.id, tab: tab.id, pane: p.pane, terminal: p.terminal ?? null } }, parent);
      if (p.terminal) subs(p.terminal, n);
      n.defaultOpen = Boolean(n.liveSubs);
      return n;
    };
    const tabNode = (w, tab, parent) => {
      const mine = ps.filter((p) => p.tab === tab.id);
      const label = tabLabel(tab, ps);
      const n = add({ key: `t:${tab.id}`, kind: "tab", label, text: label, space: w, tab, reps: { machine: w.machine ?? null, space: w.id, tab: tab.id } }, parent);
      if (mine.length > 1) for (const p of mine) paneNode(w, tab, p, n);
      else if (mine.length === 1) {
        Object.assign(n.reps, { pane: mine[0].pane, terminal: mine[0].terminal ?? null });
        n.pane = mine[0];
        if (mine[0].terminal) subs(mine[0].terminal, n);
      }
      n.defaultOpen = (w.active && tab.active) || Boolean(n.liveSubs);
      return n;
    };
    const spaceNode = (w, parent, worktree) => {
      const n = add({ key: `s:${w.id}`, kind: "space", label: w.name, text: w.name, space: w, worktree, git: this.git.of(w, ps),
        reps: { machine: w.machine ?? null, space: w.id } }, parent);
      const tabs = this.sortTabs(w.tabs, ps);
      if (tabs.length > 1) for (const tab of tabs) tabNode(w, tab, n);
      else if (tabs.length === 1) {
        const tab = tabs[0];
        n.tab = tab; n.reps.tab = tab.id;
        const mine = ps.filter((p) => p.tab === tab.id);
        if (mine.length > 1) for (const p of mine) paneNode(w, tab, p, n);
        else if (mine.length === 1) {
          Object.assign(n.reps, { pane: mine[0].pane, terminal: mine[0].terminal ?? null });
          n.pane = mine[0];
          if (mine[0].terminal) subs(mine[0].terminal, n);
        }
      }
      n.defaultOpen = w.active || Boolean(n.liveSubs);
      return n;
    };
    // Spaces of one machine, worktree checkouts under their repo's main checkout (display only).
    const placeSpaces = (list, parent) => {
      const sorted = this.sortSpaces(list);
      const info = new Map(sorted.map((w) => [w.id, this.git.of(w, ps)]));
      const mains = new Map();
      for (const w of sorted) { const g = info.get(w.id); if (g && !g.linked && !mains.has(g.repo)) mains.set(g.repo, w.id); }
      const nested = (w) => { const g = info.get(w.id); return g?.linked && mains.has(g.repo); };
      const nodes = new Map();
      for (const w of sorted) if (!nested(w)) nodes.set(w.id, spaceNode(w, parent, false));
      for (const w of sorted) if (nested(w)) { const host = nodes.get(mains.get(info.get(w.id).repo)); if (host) { spaceNode(w, host, true); host.defaultOpen = true; } }
    };

    const known = [...new Set([
      ...sp.map((s) => s.machine).filter(Boolean), ...this.machinesLs.map((m) => m.name), ...Object.keys(this.reconnecting),
    ])].sort();
    const remote = known.filter((m) => !this.hidden.has(m));
    const roots = [];
    const meta = { grouped: remote.length > 0, known, hiddenNames: known.filter((m) => this.hidden.has(m)) };
    const loading = (m) => {
      const lay = machines().find((k) => (k.name ?? null) === m)?.layout;
      return lay === "loading" || (!lay && m && this.machinesLs.some((k) => k.name === m && k.state === "connected"));
    };
    if (!meta.grouped) {
      const holder = { key: "root", kind: "root", children: [], reps: {} };
      placeSpaces(sp.filter((s) => !s.machine), holder);
      for (const n of holder.children) { n.parent = null; roots.push(n); }
      meta.loadingLocal = !roots.length && loading(null);
    } else {
      for (const m of [null, ...remote]) {
        const repair = m ? this.reconnecting[m] : null;
        const machine = m ? this.machinesLs.find((k) => k.name === m) ?? repair?.machine : null;
        const connected = !m || machine?.state === "connected";
        const n = add({ key: mkey(m), kind: "machine", label: machineLabel(m), text: machineLabel(m), machineName: m, machine, connected,
          rebuilt: this.rebuilt(machine) || Boolean(repair), repair,
          login: machine?.state === "needs_login" ? `hc machine login ${m}` : null,
          loading: loading(m), reps: { machine: m } }, null);
        roots.push(n);
        if (!n.rebuilt) placeSpaces(sp.filter((s) => (s.machine ?? null) === m), n);
      }
    }
    // Sub-agent totals under each node (badges on folded rows).
    const agg = (n) => {
      let live = 0, total = 0;
      for (const it of n.subs ?? []) { total++; if (it.live) live++; }
      for (const c of n.children) if (!SUB_KINDS.has(c.kind)) { const a = agg(c); live += a.live; total += a.total; }
      n.agg = { live, total };
      return n.agg;
    };
    roots.forEach(agg);
    return { roots, byKey, meta, now };
  }

  // Filtering: mark kept nodes (self or a descendant matches) and their label hits.
  markFilter(roots, q) {
    const walk = (n) => {
      const f = q ? matchQ(q, n.text ?? n.label ?? "") : null;
      n.match = Boolean(f);
      n.hits = f ? matchQ(q, n.label ?? "")?.hits ?? [] : [];
      let kept = n.match;
      for (const c of n.children) if (walk(c)) kept = true;
      n.kept = kept;
      return kept;
    };
    roots.forEach(walk);
  }

  // Rows in display order: { key, node?, depth, open, kind } (kinds of pseudo rows: more, new, loading, login, shelf).
  flatten(model) {
    const out = [];
    const q = this.filter.trim();
    const filtering = Boolean(q);
    if (filtering) this.markFilter(model.roots, q);
    const visit = (nodes, depth, mode) => {
      const isSub = (n) => SUB_KINDS.has(n.kind);
      let list = nodes;
      if (mode === "filter") list = nodes.filter((n) => n.kept);
      // Finished sub-agents beyond the newest few fold into an "n earlier" row.
      let more = null;
      if (mode === "normal") {
        const subsHere = list.filter(isSub);
        const done = subsHere.filter((n) => !n.sub.live);
        if (done.length > MAX_DONE) {
          const drop = new Set(done.slice(MAX_DONE).map((n) => n.key));
          list = list.filter((n) => !drop.has(n.key));
          more = { count: drop.size, addr: subsHere[0].reps.terminal, after: list.filter(isSub).at(-1)?.key };
        }
      }
      for (const n of list) {
        let open, childMode = mode;
        if (n.kind === "machine") open = mode === "filter" ? true : this.isOpen(n);
        else if (mode === "filter") {
          if (this.filterExpand.has(n.key)) { open = n.children.length > 0; childMode = "normal"; }
          else open = n.children.some((c) => c.kept);
        } else open = this.isOpen(n);
        out.push({ key: n.key, node: n, depth, open, foldable: n.children.length > 0 });
        if (n.kind === "machine") {
          if (n.login && mode === "normal") out.push({ key: `login:${n.key}`, kind: "login", depth, machine: n });
          if (open && !n.rebuilt) {
            if (n.children.length) visit(n.children, depth, childMode);
            else if (mode === "normal") out.push(n.loading ? { key: `loading:${n.key}`, kind: "loading", depth } : { key: `n:${n.key}`, kind: "new", depth, machine: n });
          }
        } else if (open) visit(n.children, depth + 1, childMode);
        if (more && n.key === more.after) out.push({ key: `x:${more.addr}`, kind: "more", depth, count: more.count, addr: more.addr });
      }
    };
    visit(model.roots, 0, filtering ? "filter" : "normal");
    if (!model.meta.grouped && model.meta.loadingLocal && !filtering) out.push({ key: "loading:local", kind: "loading", depth: 0 });
    if (model.meta.hiddenNames.length && !filtering) out.push({ key: "shelf", kind: "shelf", names: model.meta.hiddenNames });
    return out;
  }

  // The row that shows what the window shows: the focused pane, else its tab, else its space.
  selectedKey(rows) {
    const f = focused();
    if (!f) return null;
    let best = null, score = 0;
    for (const r of rows) {
      const n = r.node;
      if (!n || SUB_KINDS.has(n.kind) || n.kind === "machine") continue;
      const s = f.pane && n.reps.pane === f.pane ? 3 : n.reps.tab && n.reps.tab === f.tab && !n.reps.pane ? 2 : n.reps.space === f.space && !n.reps.tab ? 1 : 0;
      if (s > score || (s === score && s > 0)) { best = r.key; score = s; }
    }
    return best;
  }

  // ------------------------------------------------------------------ reveal
  reveal(explicit) {
    const f = focused();
    if (!f?.space) return;
    const sp = spaces().find((s) => s.id === f.space);
    if (!sp) return;
    if (sp.machine && this.hidden.has(sp.machine)) { if (!explicit) return; this.setHidden(sp.machine, false); }
    let model = this.model();
    const target = (m) => {
      let best = null, score = 0;
      for (const n of m.byKey.values()) {
        if (SUB_KINDS.has(n.kind) || n.kind === "machine") continue;
        const s = f.pane && n.reps.pane === f.pane ? 3 : n.reps.tab === f.tab && f.tab ? 2 : n.reps.space === f.space ? 1 : 0;
        if (s > score) { best = n; score = s; }
      }
      return best;
    };
    let n = target(model);
    if (!n) return;
    if (explicit && this.filter.trim()) {
      this.markFilter(model.roots, this.filter.trim());
      if (!n.kept) { this.setFilter(""); this.input.set_value(""); model = this.model(); n = target(model); if (!n) return; }
    }
    for (let p = n.parent; p; p = p.parent) this.setOpen(p, true);
    this.pendingReveal = { key: n.key, explicit };
  }

  // ------------------------------------------------------------------ actions
  once(name) {
    const now = Date.now();
    if (now - (this.lastAct[name] ?? 0) < 150) return false;
    this.lastAct[name] = now;
    return true;
  }
  activate(n) {
    if (!n) return;
    const r = n.reps ?? {};
    switch (n.kind) {
      case "machine": this.setOpen(n, !this.isOpen(n)); break;
      case "space": run("space.select", { id: r.space }); break;
      case "tab": run("space.select", { id: r.space }); run("tab.select", { id: r.tab }); break;
      case "pane": run("space.select", { id: r.space }); run("tab.select", { id: r.tab }); run("pane.focus", { pane: r.pane }); break;
      case "run": case "claude": openView("ob-subagents", `run:${n.sub.id}`); break;
      case "child": run("terminal.peek", { terminal: n.sub.id }); break;
      default: break;
    }
  }
  activateRow(r) {
    if (!r) return;
    if (r.node) return this.activate(r.node);
    if (r.kind === "more") openView("ob-subagents", `term:${r.addr}`);
    else if (r.kind === "new") run("space.new", { machine: r.machine.machineName ?? "" });
  }
  rename(n) {
    if (!n) return;
    if (n.kind === "space") run("space.rename", { id: n.reps.space });
    else if (n.kind === "tab" || n.kind === "pane") run("tab.rename", { id: n.reps.tab });
  }
  close(n) {
    if (!n) return;
    if (n.kind === "space") run("space.close", { id: n.reps.space });
    else if (n.kind === "tab") run("tab.close", { id: n.reps.tab });
    else if (n.kind === "pane") run("pane.close", { pane: n.reps.pane });
  }
  openRight(n) {
    if (!n) return;
    if (n.kind === "child") { run("terminal.keep", { terminal: n.sub.id, place: "right" }); return; }
    if (!["space", "tab", "pane"].includes(n.kind)) return;
    this.activate(n);
    run("pane.split", n.kind === "pane" ? { direction: "right", pane: n.reps.pane } : { direction: "right" });
  }
  bookmarkItem(n) {
    if (!n) return null;
    const m = n.reps?.machine ?? null;
    if (n.kind === "space") return { kind: "space", id: n.reps.space, label: n.label, machine: m };
    if (n.kind === "tab") return { kind: "tab", id: n.reps.tab, label: n.label, machine: m };
    if (n.kind === "pane" && n.reps.terminal) return { kind: "terminal", id: n.reps.terminal, label: `${n.space?.name ?? ""} · ${n.label}`, machine: m };
    if (n.kind === "run") return { kind: "run", id: n.sub.id, label: n.label, machine: n.sub.item.machine ?? null };
    return null;
  }
  inspect(addr) {
    if (!addr) return;
    setShared("ob.inspect", { terminal: addr, at: Date.now() });
    openView("ob-props", `term:${addr}`);
  }
  newSpace() {
    const remote = this.machinesLs.filter((m) => m.state === "connected" && !this.hidden.has(m.name));
    if (!remote.length) { run("space.new", {}); return; }
    openMenu([
      { label: "New space on this computer", icon: "monitor", command: "space.new", args: { machine: "" } },
      ...remote.map((m) => ({ label: `New space on ${m.name}`, icon: "server", command: "space.new", args: { machine: m.name } })),
    ], { width: 250, title: "New space" });
  }
  newTab() {
    const n = this.byKey?.get(this.cursor);
    const space = n?.reps?.space;
    run("tab.new", space && this.kbd ? { space } : {});
  }
  foldAll(open) {
    const model = this.model();
    for (const n of model.byKey.values()) {
      if (n.kind === "machine") { if (open) this.folded.delete(n.key); continue; }
      if (n.children.length) this.open[n.key] = open;
    }
    save("tree.open", this.open);
    save("machines.folded", [...this.folded]);
  }
  anyOpen() { return (this.rows ?? []).some((r) => r.node && r.node.kind !== "machine" && r.foldable && r.open); }

  moveCursor(delta) {
    const nav = this.rows.filter((r) => r.node || r.kind === "more" || r.kind === "new");
    if (!nav.length) return;
    let i = nav.findIndex((r) => r.key === this.cursor);
    if (i < 0) { const sel = this.selectedKey(this.rows); i = nav.findIndex((r) => r.key === sel); if (i < 0) i = delta > 0 ? -1 : nav.length; else i -= delta; }
    i = Math.max(0, Math.min(nav.length - 1, i + delta));
    this.cursor = nav[i].key;
    this.kbd = true;
    this.scrollTo(this.cursor);
  }
  scrollTo(key) { const i = this.rows.findIndex((r) => r.key === key); if (i >= 0) this.scroll.scroll_to_item(i); }
  cursorRow() { return this.rows.find((r) => r.key === this.cursor) ?? null; }
  left() {
    const r = this.cursorRow();
    if (!r?.node) return;
    if (r.foldable && r.open && !this.filter.trim()) { this.setOpen(r.node, false); return; }
    const p = r.node.parent;
    if (p) { this.cursor = p.key; this.scrollTo(p.key); }
  }
  right() {
    const r = this.cursorRow();
    if (!r?.node || !r.foldable) return;
    if (!r.open) { this.setOpen(r.node, true); return; }
    const i = this.rows.indexOf(r);
    const next = this.rows[i + 1];
    if (next?.node?.parent === r.node || (r.node.kind === "machine" && next?.node)) { this.cursor = next.key; this.scrollTo(next.key); }
  }

  // ------------------------------------------------------------------ commands
  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    const node = (k) => this.byKey?.get(k || this.cursor) ?? null;
    switch (verb) {
      case "focus": this.handle.focus(); this.kbd = true; if (!this.cursor) this.cursor = this.selectedKey(this.rows); break;
      case "reveal": this.reveal(true); break;
      case "collapse-all": this.foldAll(false); break;
      case "expand-all": this.foldAll(true); break;
      case "sort": if (SORTS.some(([id]) => id === arg)) { this.sort = arg; save("sort", arg); } break;
      case "auto-reveal": this.autoReveal = arg === "toggle" ? !this.autoReveal : arg !== "off"; save("autoReveal", this.autoReveal); if (this.autoReveal) this.reveal(false); break;
      case "filter": this.input.set_value(arg); this.setFilter(arg); break;
      case "menu": this.menu(arg || this.cursor); break;
      case "rename": if (this.once("rename")) this.rename(node(arg)); break;
      case "close": if (this.once("close")) this.close(node(arg)); break;
      case "open-right": if (this.once("open-right")) this.openRight(node(arg)); break;
      case "new-tab": this.newTab(); break;
      case "new-space": this.newSpace(); break;
      case "up": this.moveCursor(-1); break;
      case "down": this.moveCursor(1); break;
      case "left": this.kbd = true; this.left(); break;
      case "right": this.kbd = true; this.right(); break;
      case "enter": this.activateRow(this.cursorRow()); break;
      case "toggle": { const r = this.cursorRow(); if (r?.foldable) this.setOpen(r.node, !r.open); break; }
      case "cursor": if (this.byKey?.has(arg) || this.rows.some((r) => r.key === arg)) { this.cursor = arg; this.kbd = true; this.scrollTo(arg); } break;
      case "fold": { const n = node(arg); if (n) { if (this.filter.trim()) this.toggleFilterExpand(n); else this.setOpen(n, !this.isOpen(n)); } break; }
      case "hide-machine": this.setHidden(arg, true); break;
      case "show-machine": this.setHidden(arg, false); break;
      case "connect": this.reconnect(arg, cx); break;
      case "bookmark": { const it = this.bookmarkItem(node(arg)); if (it) toggleBookmark(it); break; }
      case "inspect": this.inspect(arg); break;
      case "move": { const [from, to] = arg.split("@"); if (from && to && this.byKey?.has(from) && this.byKey?.has(to)) this.drop(from, to); break; }
      case "move-to": {
        const sp = spaces().find((s) => (s.tabs ?? []).some((x) => x.id === arg));
        if (sp) { run("space.select", { id: sp.id }); run("tab.select", { id: arg }); run("ob-tabs.switcher:move"); }
        break;
      }
      default: console.log(`ob-sessions: unknown command ${c}`);
    }
  }
  toggleFilterExpand(n) {
    this.filterExpand.has(n.key) ? this.filterExpand.delete(n.key) : this.filterExpand.add(n.key);
  }

  // ------------------------------------------------------------------ context menus
  viewer(view, key, machine, path, title, live) {
    return { mod: "ob-subagents", kind: "window", key: `ob-view-${key}`, width: 760, height: 0.7, props: { view, machine: machine ?? null, path, title, live: Boolean(live) } };
  }
  menu(key) {
    const n = this.byKey?.get(key);
    const r = this.rows.find((x) => x.key === key);
    if (!n && r?.kind === "more") { openView("ob-subagents", `term:${r.addr}`); return; }
    if (!n) return;
    const items = this.menuItems(n);
    if (items.length) openMenu(items, { title: n.kind === "machine" ? n.label : n.label, width: 250 });
  }
  menuItems(n) {
    const me = (cmd) => `ob-sessions.${cmd}`;
    const sp = spaces();
    const items = [];
    const bm = (kind, id) => (isBookmarked(kind, id) ? "Remove bookmark" : "Bookmark");
    const sessionItems = (addr, paneId, cwd) => {
      const out = [];
      if (!addr) return out;
      const agent = agents().find((a) => a.address === addr);
      out.push({ label: "Show properties", icon: "info", command: me(`inspect:${addr}`) });
      out.push({ label: "Show subagents", icon: "subagents", command: `ob-tabs.open:ob-subagents@term:${addr}` });
      if (agent) out.push({ label: agent.pinned ? "Unpin agent" : "Pin agent to the top", icon: agent.pinned ? "pin-off" : "pin", command: "terminal.pin", args: { terminal: addr, pinned: !agent.pinned } });
      out.push({ label: "Peek", icon: "eye", command: "terminal.peek", args: { terminal: addr } });
      out.push({ label: "Copy address", icon: "copy", copy: addr });
      if (cwd) out.push({ label: "Copy path", icon: "copy", copy: cwd, hint: tilde(cwd).length > 22 ? "" : tilde(cwd) });
      return out;
    };
    if (n.kind === "machine") {
      const m = n.machineName;
      if (n.connected) items.push({ label: "New space here", icon: "folder-plus", command: "space.new", args: { machine: m ?? "" } });
      if (n.rebuilt) items.push({ label: n.repair?.busy ? "Connecting…" : "Connect to the new machine", icon: "refresh", command: me(`connect:${m}`), disabled: Boolean(n.repair?.busy) });
      if (n.login) items.push({ label: "Copy login command", icon: "copy", copy: n.login, hint: "then run it" });
      items.push({ label: this.isOpen(n) ? "Fold" : "Unfold", icon: this.isOpen(n) ? "chevron-right" : "chevron-down", command: me(`fold:${n.key}`) });
      if (m) items.push({ label: "Hide machine", icon: "eye-off", command: me(`hide-machine:${m}`) });
      items.push({ separator: true });
      items.push({ label: "Machine settings", icon: "settings", command: "app.settings", args: { section: "machines" } });
      items.push({ label: "Copy name", icon: "copy", copy: m ?? "This computer" });
      return items;
    }
    if (n.kind === "space") {
      const w = n.space;
      const cwd = place(w, panes());
      const g = n.git;
      const list = sp.filter((s) => (s.machine ?? null) === (w.machine ?? null));
      const i = list.findIndex((s) => s.id === w.id);
      const gi = sp.findIndex((s) => s.id === w.id);
      items.push({ label: "New tab here", icon: "square-pen", command: "tab.new", args: { space: w.id } });
      items.push({ label: "Rename…", icon: "rename", command: "space.rename", args: { id: w.id }, kbd: "shift-f2" });
      items.push({ label: bm("space", w.id), icon: isBookmarked("space", w.id) ? "bookmark" : "bookmark-plus", command: me(`bookmark:${n.key}`) });
      if (cwd) items.push({ label: "Copy path", icon: "copy", copy: cwd });
      if (g) {
        items.push({ separator: true });
        items.push({ label: "New worktree…", icon: "git-branch", overlay: { mod: "worktree", kind: "dialog", width: 460, height: 280, props: { space: w.id, folder: cwd, action: "new" } } });
        items.push({ label: "Open worktree…", icon: "folder-open", overlay: { mod: "worktree", kind: "dialog", width: 560, height: 480, props: { space: w.id, folder: cwd, action: "open" } } });
        if (g.linked) items.push({ label: "Remove worktree…", icon: "trash", danger: true, overlay: { mod: "worktree", kind: "dialog", width: 460, height: 280, props: { space: w.id, folder: cwd, action: "remove" } } });
      }
      items.push({ separator: true });
      items.push({ label: "Move up", icon: "chevron-up", command: "space.move", args: { id: w.id, index: gi }, disabled: i <= 0 });
      items.push({ label: "Move down", icon: "chevron-down", command: "space.move", args: { id: w.id, index: gi + 2 }, disabled: i < 0 || i >= list.length - 1 });
      if (n.reps.terminal) { items.push({ separator: true }); items.push(...sessionItems(n.reps.terminal, n.reps.pane, null)); }
      items.push({ separator: true });
      items.push({ label: "Close space", icon: "trash", danger: true, command: "space.close", args: { id: w.id } });
      return items;
    }
    if (n.kind === "tab") {
      const w = n.space, tab = n.tab;
      const ps = panes();
      const cwd = (ps.find((p) => p.tab === tab.id && p.focused) ?? ps.find((p) => p.tab === tab.id))?.cwd;
      const tabs = w.tabs ?? [];
      const i = tabs.findIndex((x) => x.id === tab.id);
      items.push({ label: "Rename…", icon: "rename", command: "tab.rename", args: { id: tab.id }, kbd: "f2" });
      items.push({ label: bm("tab", tab.id), icon: isBookmarked("tab", tab.id) ? "bookmark" : "bookmark-plus", command: me(`bookmark:${n.key}`) });
      if (cwd) items.push({ label: "Copy path", icon: "copy", copy: cwd });
      items.push({ label: tab.settled ? "Unsettle" : "Settle", icon: tab.settled ? "eye" : "eye-off", hint: tab.settled ? "" : "hide from the tab bar", command: tab.settled ? "tab.unsettle" : "tab.settle", args: { id: tab.id } });
      items.push({ separator: true });
      items.push({ label: "Move up", icon: "chevron-up", command: "tab.move", args: { id: tab.id, index: i }, disabled: i <= 0 });
      items.push({ label: "Move down", icon: "chevron-down", command: "tab.move", args: { id: tab.id, index: i + 2 }, disabled: i < 0 || i >= tabs.length - 1 });
      items.push({ label: "Move to space…", icon: "move", command: me(`move-to:${tab.id}`) });
      items.push({ label: "New tab here", icon: "square-pen", command: "tab.new", args: { space: w.id } });
      if (n.reps.terminal) { items.push({ separator: true }); items.push(...sessionItems(n.reps.terminal, n.reps.pane, null)); }
      items.push({ separator: true });
      items.push({ label: "Close tab", icon: "trash", danger: true, command: "tab.close", args: { id: tab.id } });
      return items;
    }
    if (n.kind === "pane") {
      const p = n.pane;
      items.push({ label: "Focus", icon: "locate", command: "pane.focus", args: { pane: p.pane } });
      items.push({ label: "Split right", icon: "split-right", command: "pane.split", args: { direction: "right", pane: p.pane } });
      items.push({ label: "Split down", icon: "split-down", command: "pane.split", args: { direction: "down", pane: p.pane } });
      items.push({ label: p.zoomed ? "Unzoom" : "Zoom", icon: p.zoomed ? "minimize" : "maximize", command: "pane.zoom", args: { pane: p.pane } });
      if (p.terminal) {
        items.push({ separator: true });
        items.push({ label: bm("terminal", p.terminal), icon: isBookmarked("terminal", p.terminal) ? "bookmark" : "bookmark-plus", command: me(`bookmark:${n.key}`) });
        items.push(...sessionItems(p.terminal, p.pane, p.cwd));
      }
      items.push({ separator: true });
      items.push({ label: "Close pane", icon: "trash", danger: true, command: "pane.close", args: { pane: p.pane } });
      return items;
    }
    if (n.kind === "run") {
      const r = n.sub.item;
      const last = (r.steps ?? []).at(-1);
      const tr = last?.transcript || last?.session;
      items.push({ label: "Open in Subagents", icon: "subagents", command: `ob-tabs.open:ob-subagents@run:${r.key}` });
      if (r.log) items.push({ label: "Follow log", icon: "scroll", overlay: this.viewer("log", r.key, r.machine, r.log, `${n.label} · log`, r.live) });
      if (tr) items.push({ label: "Transcript", icon: "file-text", overlay: this.viewer("transcript", r.key, r.machine, tr, `${n.label} · transcript`, r.live) });
      items.push({ label: "Copy run id", icon: "copy", copy: r.id });
      items.push({ label: bm("run", r.key), icon: isBookmarked("run", r.key) ? "bookmark" : "bookmark-plus", command: me(`bookmark:${n.key}`) });
      return items;
    }
    if (n.kind === "claude") {
      const c = n.sub.item;
      items.push({ label: "Open in Subagents", icon: "subagents", command: `ob-tabs.open:ob-subagents@run:${c.key}` });
      if (c.transcript) items.push({ label: "Transcript", icon: "file-text", overlay: this.viewer("transcript", c.key, c.machine, c.transcript, `${n.label} · transcript`, n.sub.live) });
      items.push({ label: "Copy agent id", icon: "copy", copy: c.id });
      return items;
    }
    if (n.kind === "child") {
      const addr = n.sub.id;
      items.push({ label: "Peek", icon: "eye", command: "terminal.peek", args: { terminal: addr } });
      items.push({ label: "Keep as a pane to the right", icon: "split-right", command: "terminal.keep", args: { terminal: addr, place: "right" } });
      items.push({ label: "Show properties", icon: "info", command: me(`inspect:${addr}`) });
      items.push({ label: "Copy address", icon: "copy", copy: addr });
      return items;
    }
    return items;
  }

  // ------------------------------------------------------------------ drawing
  gitTail(g, n, t) {
    if (!g) return null;
    const name = n.space.name;
    const raw = g.branch ?? "detached";
    const same = (a) => String(a).toLowerCase() === String(name).toLowerCase();
    const branch = same(raw) || raw === "master" || raw === "main" ? "" : raw;
    const repo = n.worktree || same(g.name) ? "" : g.name;
    const text = [repo, branch].filter(Boolean).join(" · ");
    if (!text && !(g.ahead > 0) && !(g.behind > 0)) return null;
    return h_flex().min_w(0).flex_shrink(100).gap(4).items_center().text_size(11.5).text_color(t.dim)
      .when(Boolean(text), (e) => e.child(div().min_w(0).truncate().child(text)))
      .when(g.ahead > 0, (e) => e.child(div().flex_none().text_color(t.ansi2).child(`↑${g.ahead}`)))
      .when(g.behind > 0, (e) => e.child(div().flex_none().text_color(t.ansi1).child(`↓${g.behind}`)));
  }
  tag(text, t) { return div().flex_none().text_size(10.5).text_color(t.dim).child(text); }
  subBadge(c, compact, id) {
    if (!c?.total) return null;
    const txt = compact ? String(c.live || c.total) : c.live ? `${c.live}/${c.total}` : String(c.total);
    return h_flex().id(`bdg-${id}`).flex_none().child(badge(txt, c.live ? "working" : null))
      .tooltip(`${c.live} running · ${c.total} sub-agent${c.total === 1 ? "" : "s"}`);
  }
  status(st, agentRow, t) {
    if (!st) return null;
    const k = normStatus(st);
    if (k === "blocked" && agentRow && this.w >= 220) return needsYou();
    if (!agentRow && k === "idle") return null;
    return statusMark(st);
  }

  machineRow(r, t, sel) {
    const n = r.node;
    const m = n.machineName;
    const hovered = this.hover === r.key || (this.kbd && this.cursor === r.key);
    const cur = this.kbd && this.cursor === r.key;
    const dotColor = n.connected ? t.ansi2 : n.machine?.state === "needs_login" ? t.blocked : t.dim;
    const stateWord = !m ? null : n.rebuilt ? null : n.connected ? null : n.login ? "needs login" : (n.machine?.state ?? "asleep").replace(/_/g, " ");
    const spacesN = n.children.filter((c) => c.kind === "space").length + n.children.reduce((a, c) => a + c.children.filter((x) => x.worktree).length, 0);
    return h_flex().id(`row-${r.key}`).relative().h(S.header).flex_none().mt(r === this.rows[0] ? 0 : 6).pl(S.pad).pr(6).gap(6).items_center()
      .rounded(S.radius).text_size(S.textXs).font_semibold().text_color(t.dim).cursor_pointer()
      .when(cur, (e) => e.bg(t.hover).border_1().border_color(alpha(t.accent, 0.55)))
      .hover((s) => s.text_color(t.muted))
      .on_hover((on, cx) => { const v = on ? r.key : this.hover === r.key ? null : this.hover; if (v !== this.hover) { this.hover = v; cx.notify(); } })
      .on_click((_e, cx) => { this.kbd = false; this.cursor = r.key; if (!this.filter.trim()) this.setOpen(n, !this.isOpen(n)); cx.notify(); })
      .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.cursor = r.key; this.menu(r.key); })
      .child(icon(r.open ? "chevron-down" : "chevron-right", S.iconXs))
      .child(h_flex().relative().flex_none().child(icon(m ? "server" : "monitor", S.iconXs))
        .when(Boolean(m), (e) => e.child(div().absolute().right(-3).bottom(-2).size(6).rounded_full().border_1().border_color(t.chrome).bg(dotColor))))
      .child(div().min_w(0).truncate().child(n.label.toUpperCase()))
      .when(spacesN > 0, (e) => e.child(div().flex_none().font_normal().child(String(spacesN))))
      .when(Boolean(stateWord) && this.w >= 180, (e) => e.child(div().flex_none().font_normal().text_color(n.login ? t.blocked : t.dim).child(stateWord)))
      .when(n.rebuilt, (e) => e.child(h_flex().flex_none().gap(4).font_normal().items_center()
        .child(div().max_w(120).truncate().child(n.repair?.error || "rebuilt"))
        .child(div().id(`connect-${r.key}`).px(5).rounded(4).text_color(n.repair?.error ? t.blocked : t.foreground).bg(t.raised).cursor_pointer()
          .hover((s) => s.bg(t.hover)).tooltip(n.repair?.error || "This machine was rebuilt or replaced. Connect to the new one.")
          .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
          .on_click((_e, cx) => { cx.stop_propagation(); this.reconnect(m, cx); cx.notify(); })
          .child(n.repair?.busy ? "Connecting…" : "Connect"))))
      .child(div().flex_1())
      .when(hovered && n.connected, (e) => e.child(iconButton({ id: `add-${r.key}`, icon: "plus", size: 20, iconSize: S.iconXs, tip: `New space on ${m ?? "this computer"}`,
        onClick: () => run("space.new", { machine: m ?? "" }) })))
      .when(hovered && Boolean(m), (e) => e.child(iconButton({ id: `hide-${r.key}`, icon: "eye-off", size: 20, iconSize: S.iconXs, tip: `Hide ${m}`,
        onClick: (_e, cx) => { this.setHidden(m, true); cx.notify(); } })))
      .when(!hovered && Boolean(m) && this.w >= 200, (e) => e.child(div().size(6).flex_none().rounded_full().bg(dotColor)));
  }

  nodeRow(r, t, sel, now) {
    const n = r.node;
    const compact = this.w < 220;
    const cur = this.kbd && this.cursor === r.key;
    const q = this.filter.trim();
    const label = q && n.hits?.length ? highlight(n.label, n.hits) : n.label;
    const isSub = SUB_KINDS.has(n.kind);
    const o = {
      id: `row-${r.key}`, depth: r.depth, selected: sel === r.key, cursor: cur,
      chevron: r.foldable ? r.open : undefined,
      onToggle: (_e, cx) => { if (q) this.toggleFilterExpand(n); else this.setOpen(n, !r.open); cx.notify(); },
      label, after: [], right: [],
      onRight: (_e, cx) => { this.cursor = r.key; this.menu(r.key); cx.notify(); },
    };
    const selected = sel === r.key;
    const bmMark = (kind, id) => (isBookmarked(kind, id) ? icon("bookmark", 11, t.dim) : null);
    const termCounts = n.subs ? counts(n.subs) : null;
    const foldBadge = !r.open && !n.subs && n.agg?.total ? this.subBadge(n.agg, compact, r.key) : null;
    if (n.kind === "space") {
      const w = n.space;
      o.lead = n.worktree ? icon("git-branch", S.iconSm, t.dim) : avatar(w, 16);
      o.bold = true;
      o.labelColor = t.foreground;
      if (!compact) o.after.push(this.gitTail(n.git, n, t));
      o.after.push(bmMark("space", w.id));
      if (n.reps.terminal) o.right.push(this.subBadge(termCounts, compact, r.key));
      else o.right.push(foldBadge);
      const st = n.pane ? n.pane.status : w.status;
      o.right.push(this.status(st, Boolean(n.pane?.program?.agent), t));
    } else if (n.kind === "tab") {
      const tab = n.tab;
      o.lead = n.pane ? programIcon(n.pane.program, S.iconSm, t.muted) : icon("tab", S.iconSm, t.dim);
      o.labelColor = selected ? t.foreground : t.muted;
      o.after.push(bmMark("tab", tab.id));
      if (tab.settled && !compact) o.right.push(this.tag("settled", t));
      if (tab.status === "working" && tab.working_since && now - tab.working_since > 60000 && !compact) o.right.push(this.tag(ago(tab.working_since, now), t));
      if (n.reps.terminal) o.right.push(this.subBadge(termCounts, compact, r.key)); else o.right.push(foldBadge);
      o.right.push(this.status(n.pane ? n.pane.status : tab.status, Boolean(n.pane?.program?.agent), t));
    } else if (n.kind === "pane") {
      const p = n.pane;
      o.lead = p.mod ? icon("layers", S.iconSm, t.dim) : programIcon(p.program, S.iconSm, t.muted);
      o.labelColor = selected ? t.foreground : t.muted;
      if (p.terminal) o.after.push(bmMark("terminal", p.terminal));
      if (p.zoomed && !compact) o.right.push(this.tag("zoomed", t));
      o.right.push(this.subBadge(termCounts, compact, r.key));
      o.right.push(this.status(p.status, Boolean(p.program?.agent), t));
    } else if (isSub) {
      const it = n.sub;
      o.height = S.rowSm;
      o.lead = n.kind === "child" ? programIcon(it.item.program, S.iconXs, t.dim) : icon(n.kind === "run" ? "subagents" : "bot", S.iconXs, t.dim);
      o.labelColor = it.live ? t.muted : t.dim;
      o.label = h_flex().min_w(0).text_size(S.textSm).child(label);
      if (it.detail && this.w >= 340 && n.kind !== "child") o.after.push(div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(it.detail));
      if (n.kind === "run") o.after.push(bmMark("run", it.id));
      let time = "";
      if (n.kind === "run") time = it.live ? dur(now - (it.item.startedAt ?? now)) : ago(it.item.endedAt ?? it.item.lastUpdate, now);
      else if (n.kind === "claude" && !it.live) time = ago(it.item.updatedAt, now);
      if (time && this.w >= 200) o.right.push(this.tag(time, t));
      o.right.push(statusMark(it.status, S.iconXs));
    }
    let el = treeRow(o);
    // Drag to reorder: spaces within their machine, tabs within their space (manual sort, no filter).
    const drag = !q && this.sort === "manual" && (n.kind === "space" || n.kind === "tab");
    const group = n.kind === "space" ? mkey(n.space.machine) : n.kind === "tab" ? n.space.id : null;
    el = el
      .on_mouse_down("left", (e, cx) => {
        this.pressed = { key: r.key, kind: n.kind, group, drag };
        this.over = r.key;
        if (e.click_count === 2) this.rename(n);
      })
      .on_mouse_move((_e, cx) => {
        if (!this.pressed) return;
        const ok = this.pressed.drag && drag && this.pressed.kind === n.kind && this.pressed.group === group;
        const over = ok ? r.key : null;
        if (this.over !== over) { this.over = over; cx.notify(); }
      })
      .on_mouse_up("left", (e, cx) => {
        const p = this.pressed, over = this.over;
        this.pressed = null; this.over = null;
        if (p && p.key !== r.key && over === r.key) this.drop(p.key, r.key);
        else if (p?.key === r.key && e.click_count !== 2) { this.kbd = false; this.cursor = r.key; this.activate(n); }
        cx.notify();
      });
    if (this.pressed?.key === r.key && this.over && this.over !== r.key) el = el.opacity(0.5);
    if (this.pressed && this.over === r.key && this.pressed.key !== r.key) {
      const below = this.dropBelow(this.pressed.key, r.key);
      el = el.child(div().absolute().left(0).right(0).h(2).bg(t.accent).when(below, (l) => l.bottom(0)).when(!below, (l) => l.top(0)));
    }
    return el;
  }
  indexOf(key) {
    const [kind, id] = [key.slice(0, 1), key.slice(2)];
    const sp = spaces();
    if (kind === "s") return sp.findIndex((s) => s.id === id);
    for (const s of sp) { const i = (s.tabs ?? []).findIndex((x) => x.id === id); if (i >= 0) return i; }
    return -1;
  }
  dropBelow(from, to) { return this.indexOf(from) < this.indexOf(to); }
  drop(from, to) {
    const to1 = this.indexOf(to) + 1;
    if (to1 <= 0 || this.indexOf(from) < 0) return;
    if (from.startsWith("s:")) run("space.move", { id: from.slice(2), index: to1 });
    else if (from.startsWith("t:")) run("tab.move", { id: from.slice(2), index: to1 });
  }

  pseudoRow(r, t) {
    const cur = this.kbd && this.cursor === r.key;
    if (r.kind === "more") {
      return treeRow({ id: `row-${r.key}`, depth: r.depth, height: S.rowSm, cursor: cur, lead: icon("more-h", S.iconXs, t.dim),
        label: h_flex().text_size(S.textSm).child(`${r.count} earlier`), labelColor: t.dim,
        right: [icon("arrow-right", S.iconXs, t.dim)],
        onClick: (_e, cx) => { this.cursor = r.key; openView("ob-subagents", `term:${r.addr}`); cx.notify(); } }).tooltip("Show them all in Subagents");
    }
    if (r.kind === "new") {
      const m = r.machine.machineName;
      if (!r.machine.connected) return div().id(`row-${r.key}`).h(S.row).flex_none().pl(S.pad + 17).flex().items_center().text_size(S.textSm).text_color(t.dim).child("Not connected");
      return treeRow({ id: `row-${r.key}`, depth: r.depth, cursor: cur, lead: icon("plus", S.iconSm, t.dim), label: "New space there", labelColor: t.dim,
        onClick: (_e, cx) => { this.cursor = r.key; run("space.new", { machine: m ?? "" }); cx.notify(); } }).tooltip(`New space on ${m ?? "this computer"}`);
    }
    if (r.kind === "loading") {
      return h_flex().id(`row-${r.key}`).h(S.row).flex_none().pl(S.pad + 17).gap(6).items_center().text_size(S.textSm).text_color(t.dim)
        .child(statusMark("working", S.iconXs)).child("Loading…");
    }
    if (r.kind === "login") {
      const login = r.machine.login;
      return v_flex().id(`row-${r.key}`).flex_none().pl(S.pad + 17).pr(8).pb(6).gap(3)
        .child(div().text_size(S.textXs).text_color(t.blocked).child("Needs a login. Run in a terminal:"))
        .child(h_flex().gap(5).items_center()
          .child(div().flex_1().min_w(0).truncate().tooltip(login).text_size(S.textXs).text_color(t.muted).child(login))
          .child(div().id(`copy-${r.key}`).flex_none().px(6).h(18).rounded(4).flex().items_center().text_size(S.textXs).text_color(t.foreground).bg(t.raised)
            .cursor_pointer().hover((s) => s.bg(t.hover))
            .on_click((_e, cx) => { cx.stop_propagation(); cx.write_to_clipboard(login); this.copied = login; cx.notify(); })
            .child(this.copied === login ? "Copied" : "Copy")));
    }
    if (r.kind === "shelf") {
      return h_flex().id("row-shelf").mt(8).mx(4).px(6).py(4).flex_none().gap(6).items_center().flex_wrap().border_t_1().border_color(t.border)
        .text_size(S.textXs).text_color(t.dim)
        .child(icon("eye-off", S.iconXs, t.dim).tooltip("Hidden machines: click one to show it"))
        .children(r.names.map((m) => div().id(`unhide-${m}`).px(5).h(18).flex().items_center().rounded(4).cursor_pointer()
          .hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip(`Show ${m}`)
          .on_click((_e, cx) => { this.setHidden(m, false); cx.notify(); }).child(m)));
    }
    return div();
  }

  toolbar(t) {
    const anyOpen = this.anyOpen();
    const sortLabel = SORTS.find(([id]) => id === this.sort)?.[1] ?? "";
    return h_flex().id("toolbar").h(S.toolbar).flex_none().px(S.pad).gap(2).items_center().justify_center()
      .child(iconButton({ id: "tb-new-tab", icon: "square-pen", tip: `New tab${keyLabel("tab.new")}`, onClick: (_e, cx) => { this.newTab(); cx.notify(); } }))
      .child(iconButton({ id: "tb-new-space", icon: "folder-plus", tip: `New space${keyLabel("space.new")}`, onClick: () => this.newSpace() }))
      .child(iconButton({ id: "tb-sort", icon: "sort", tip: `Sort: ${sortLabel}`, active: this.sort !== "manual",
        onClick: () => openMenu(SORTS.map(([id, label]) => ({ label, checked: id === this.sort, command: `ob-sessions.sort:${id}` })), { width: 240, title: "Sort sessions" }) }))
      .child(iconButton({ id: "tb-reveal", icon: "locate", active: this.autoReveal,
        tip: this.autoReveal ? "Auto-reveal current session: on" : `Auto-reveal current session: off`,
        onClick: (_e, cx) => { this.command("auto-reveal:toggle", cx); cx.notify(); } }))
      .child(iconButton({ id: "tb-fold", icon: anyOpen ? "collapse-all" : "expand-all", tip: anyOpen ? "Collapse all" : "Expand all",
        onClick: (_e, cx) => { this.foldAll(!anyOpen); cx.notify(); } }));
  }

  rail(model, t, sel) {
    const cells = [];
    for (const root of model.roots) {
      const list = root.kind === "machine" ? root.children : [root];
      if (root.kind === "machine") cells.push(h_flex().id(`rail-${root.key}`).h(22).w_full().flex_none().justify_center().items_center().tooltip(root.label)
        .child(icon(root.machineName ? "server" : "monitor", S.iconXs, t.dim)));
      for (const n of list) {
        if (n.kind !== "space") continue;
        const on = sel && n.reps.space === focused()?.space;
        cells.push(h_flex().id(`rail-${n.key}`).relative().h(28).w_full().flex_none().justify_center().items_center().rounded(S.radius)
          .when(on, (e) => e.bg(t.selected)).when(!on, (e) => e.hover((s) => s.bg(t.hover))).cursor_pointer()
          .tooltip(n.label).on_click(() => run("space.select", { id: n.reps.space }))
          .child(avatar(n.space, 18))
          .when(["blocked", "done", "working"].includes(n.space.status), (e) => e.child(div().absolute().right(6).bottom(3).child(statusMark(n.space.status, 8)))));
      }
    }
    return v_flex().id("list").flex_1().min_h(0).px(4).gap(1).overflow_y_scroll().children(cells);
  }

  assignColors() {
    const sp = spaces();
    const ids = new Set(sp.map((p) => p.id));
    const cur = shared("space.colors") ?? {};
    const kept = Object.fromEntries(Object.entries(cur).filter(([id]) => ids.has(id)));
    let changed = Object.keys(kept).length !== Object.keys(cur).length;
    for (const p of sp) {
      if (kept[p.id] || p.name === "~") continue;
      const uses = (c) => Object.values(kept).filter((v) => v === c).length;
      kept[p.id] = PALETTE.reduce((best, c) => (uses(c) < uses(best) ? c : best));
      changed = true;
    }
    if (changed && JSON.stringify(kept) !== JSON.stringify(cur)) setShared("space.colors", kept);
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-sessions", this.handle, (_cx, intent) => {
      this.kbd = true;
      if (intent === "reveal") this.reveal(true);
      else if (!this.cursor) this.cursor = this.selectedKey(this.rows);
    });
    this.assignColors();
    const now = Date.now();
    const sp = spaces(), ps = panes();
    const due = this.git.due(now, sp, ps, machines(), Boolean(appWindow()?.active), (m) => this.folded.has(mkey(m)) || this.hidden.has(m));
    if (due.size) cx.timer.after(0, (cx) => this.git.refresh(due, cx));

    const f = focused();
    const fkey = f ? `${f.space}|${f.tab}|${f.pane}` : null;
    if (fkey !== this.lastFocus) { const first = this.lastFocus === undefined; this.lastFocus = fkey; if (this.autoReveal && !first) this.reveal(false); }

    const model = this.model();
    this.byKey = model.byKey;
    let rows = this.flatten(model);
    this.rows = rows;
    if (this.cursor && !rows.some((r) => r.key === this.cursor)) {
      // The cursor's row went away (closed, folded, filtered): keep it on its nearest shown ancestor.
      let n = model.byKey.get(this.cursor)?.parent;
      while (n && !rows.some((r) => r.key === n.key)) n = n.parent;
      this.cursor = n?.key ?? null;
    }
    if (this.pendingReveal) {
      const pr = this.pendingReveal;
      const i = rows.findIndex((r) => r.key === pr.key);
      if (i >= 0) { this.cursor = pr.key; if (pr.explicit) this.kbd = true; this.scroll.scroll_to_item(i); }
      this.pendingReveal = null;
    }
    const sel = this.selectedKey(rows);
    const railMode = this.w < 160;
    const q = this.filter.trim();
    const matches = q ? [...model.byKey.values()].filter((n) => n.match).length : 0;

    let body;
    if (railMode) body = this.rail(model, t, sel);
    else if (!sp.length && !rows.some((r) => r.kind === "loading" || r.kind === "new" || r.node)) {
      body = emptyState({ icon: "sessions", title: "No sessions yet", body: "A session is a tab: its terminals and agents, on this computer or another machine.",
        action: { id: "empty-new", label: "New tab", onClick: () => run("tab.new", {}) } });
    } else if (q && !rows.some((r) => r.node)) {
      body = emptyState({ icon: "search", title: "No matches", body: `Nothing here matches “${q}”.`,
        action: { id: "empty-clear", label: "Clear filter", onClick: (_e, cx) => { this.input.set_value(""); this.setFilter(""); cx.notify(); } } });
    } else {
      body = div().relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().px(4).pb(12).overflow_y_scroll().track_scroll(this.scroll)
          .on_mouse_up("left", (_e, cx) => { if (this.pressed) { this.pressed = null; this.over = null; cx.notify(); } })
          .children(rows.map((r) => (r.node ? (r.node.kind === "machine" ? this.machineRow(r, t, sel) : this.nodeRow(r, t, sel, now)) : this.pseudoRow(r, t)))))
        .child(Scrollbar.vertical("list").absolute().inset_0());
    }

    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom ?? 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => this.key(e, cx))
      .when(!railMode, (e) => e.child(this.toolbar(t))
        .child(h_flex().flex_none().pb(6).child(inputFrame("filter", Input.new(this.input).h_full().text_size(S.textSm).text_color(t.foreground), {
          focused: this.inputFocused, icon: "filter",
          right: q ? [badge(String(matches)), iconButton({ id: "filter-clear", icon: "x", size: 18, iconSize: S.iconXs, tip: "Clear filter (Esc)",
            onClick: (_e, cx) => { this.input.set_value(""); this.setFilter(""); cx.notify(); } })] : [],
        }).flex_1())))
      .child(body);
  }

  key(e, cx) {
    const k = e.keystroke ?? e.key;
    if (this.inputFocused) {
      if (e.key === "escape") {
        if (this.filter) { this.input.set_value(""); this.setFilter(""); } else this.handle.focus();
      } else if (e.key === "down") { this.handle.focus(); this.kbd = true; this.cursor = null; this.moveCursor(1); }
      else return;
      cx.stop_propagation(); cx.notify();
      return;
    }
    const r = this.cursorRow();
    switch (k) {
      case "up": this.moveCursor(-1); break;
      case "down": this.moveCursor(1); break;
      case "left": this.kbd = true; this.left(); break;
      case "right": this.kbd = true; this.right(); break;
      case "enter": this.activateRow(r); break;
      case "space": if (r?.foldable) this.setOpen(r.node, !r.open); break;
      case "f2": if (this.once("rename")) this.rename(r?.node); break;
      case "delete": if (this.once("close")) this.close(r?.node); break;
      case "ctrl-enter": if (this.once("open-right")) this.openRight(r?.node); break;
      case "shift-f10": case "menu": if (r) this.menu(r.key); break;
      case "/": this.input.focus(); break;
      case "escape":
        if (this.filter) { this.input.set_value(""); this.setFilter(""); }
        else { this.kbd = false; const p = focused()?.pane; if (p) run("pane.focus", { pane: p }); }
        break;
      default: return;
    }
    cx.stop_propagation();
    cx.notify();
  }
}
