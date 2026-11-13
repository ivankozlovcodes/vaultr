// ob-search: Obsidian's "Search in all files", over the text of every live terminal shown in a space.
// Each terminal's screen and history (`hc read <addr> --lines 1500`, at most 6 at once, cached 15 s)
// is searched for the query (plain or regex, case-sensitive or not), within a scope: all machines,
// this machine, or this space. Results are grouped by session; a hit opens its pane and scrolls the
// terminal to the line.
//
// Commands (herdr-app do ob-search.<cmd>): focus, query:<text>, next, prev, open, rescan,
// scope:<all|machine|space>, case:<on|off|toggle>, regex:<on|off|toggle>, clear-recent.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, Input, InputState, ScrollHandle, Scrollbar } from "gpui-base";
import { spaces, panes, terminals, focused, run, hc, theme, props, nextCommand, settings } from "herdr";
import {
  S, alpha, icon, programIcon, iconButton, badge, treeRow, emptyState, inputFrame, openMenu, statusMark,
  takeFocus, tabLabel, paneName, machineOf, machineLabel, current,
} from "./kit.js";

const LINES = 1500, PARALLEL = 6, TTL = 15000, SHOW = 5, MAX_HITS = 400;
const SCOPES = [["all", "All machines", "layers"], ["machine", "This machine", "monitor"], ["space", "This space", "folder"]];
function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } }
function splitCmd(c) { const s = String(c ?? ""); const i = s.indexOf(":"); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; }
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const onOff = (arg, cur) => (arg === "toggle" ? !cur : arg !== "off");

export default class Search extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    const o = load("opts", {});
    this.opts = { case: Boolean(o.case), regex: Boolean(o.regex), scope: SCOPES.some(([id]) => id === o.scope) ? o.scope : "all" };
    this.recent = load("recent", []).filter((x) => typeof x === "string").slice(0, 10);
    this.input = InputState.new({ placeholder: "Search all sessions…" });
    this.input.on("change", (_e, cx) => {
      const g = ++this.typing;
      cx.timer.after(250, (cx) => { if (g === this.typing && this.input.value().trim() !== this.q) { this.search(cx, false); } });
      cx.notify();
    });
    this.input.on("submit", (_e, cx) => { this.search(cx, true); cx.notify(); });
    this.input.on("focus", (_e, cx) => { this.inputFocused = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.inputFocused = false; cx.notify(); });
    this.typing = 0;
    this.gen = 0;
    this.q = "";
    this.cache = new Map(); // address -> { lines, at }
    this.results = []; // groups
    this.pending = new Map(); // machine label -> count of reads in flight
    this.error = null;
    this.folded = new Set();
    this.expanded = new Set();
    this.cursor = -1; // index into this.hits()
    this.rowIndex = new Map();
    this.kbd = false;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c, cx); } catch (e) { console.log(`ob-search: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    switch (verb) {
      case "focus": this.input.focus(); break;
      case "query": this.input.set_value(arg); this.search(cx, true); break;
      case "next": this.move(1); break;
      case "prev": this.move(-1); break;
      case "open": { const h = this.hits()[Math.max(0, this.cursor)]; if (h) this.openHit(h.group, h.line); break; }
      case "rescan": this.cache.clear(); this.search(cx, false, true); break;
      case "scope": if (SCOPES.some(([id]) => id === arg)) { this.opts.scope = arg; this.saveOpts(); this.search(cx, false, true); } break;
      case "case": this.opts.case = onOff(arg, this.opts.case); this.saveOpts(); this.search(cx, false, true); break;
      case "regex": this.opts.regex = onOff(arg, this.opts.regex); this.saveOpts(); this.search(cx, false, true); break;
      case "clear-recent": this.recent = []; save("recent", []); break;
      default: console.log(`ob-search: unknown command ${c}`);
    }
  }
  saveOpts() { save("opts", this.opts); }

  // Live terminals shown in a space, within the scope.
  targets() {
    const sp = spaces(), ps = panes();
    const tabOf = new Map();
    for (const s of sp) for (const t of s.tabs ?? []) tabOf.set(t.id, { space: s, tab: t });
    const live = new Map(terminals().filter((t) => t.state === "live").map((t) => [t.address, t]));
    const cur = current();
    const out = [];
    for (const p of ps) {
      if (!p.terminal || !live.has(p.terminal)) continue;
      const at = tabOf.get(p.tab);
      if (!at) continue;
      if (this.opts.scope === "machine" && (at.space.machine ?? null) !== (cur.machine ?? null)) continue;
      if (this.opts.scope === "space" && at.space.id !== cur.space?.id) continue;
      out.push({ addr: p.terminal, pane: p, space: at.space, tab: at.tab, single: ps.filter((x) => x.tab === p.tab).length === 1 });
    }
    return out;
  }

  matcher(q) {
    try {
      const src = this.opts.regex ? q : escapeRe(q);
      const re = new RegExp(src, this.opts.case ? "g" : "gi");
      if (re.test("")) return { error: "This pattern matches empty text." };
      return { re };
    } catch (e) { return { error: String(e?.message ?? e).replace(/^Invalid regular expression: /, "") }; }
  }

  // Runs the query: cached texts at once, the rest read (6 at a time); a newer query cancels this one.
  search(cx, remember, force = false) {
    const q = this.input.value().trim();
    if (!force && q === this.q && this.results.length && !remember) return;
    const gen = ++this.gen;
    this.q = q;
    this.results = [];
    this.error = null;
    this.cursor = -1;
    this.expanded.clear();
    this.pending.clear();
    if (!q) return;
    const m = this.matcher(q);
    if (m.error) { this.error = m.error; return; }
    if (remember) { this.recent = [q, ...this.recent.filter((x) => x !== q)].slice(0, 10); save("recent", this.recent); }
    const queue = this.targets();
    const now = Date.now();
    const todo = [];
    for (const tg of queue) {
      const c = this.cache.get(tg.addr);
      if (c && now - c.at < TTL) this.addResult(tg, c.lines, m.re);
      else todo.push(tg);
    }
    for (const tg of todo) { const k = machineLabel(machineOf(tg.addr)); this.pending.set(k, (this.pending.get(k) ?? 0) + 1); }
    if (!todo.length) return;
    cx.spawn(async (cx) => {
      const worker = async () => {
        while (todo.length && gen === this.gen) {
          const tg = todo.shift();
          let lines = null;
          try {
            const r = await hc(["read", tg.addr, "--lines", String(LINES)]);
            if (r.code === 0) { lines = r.stdout.replace(/\n$/, "").split("\n"); this.cache.set(tg.addr, { lines, at: Date.now() }); }
          } catch { /* machine away: skip it */ }
          if (gen !== this.gen) return;
          const k = machineLabel(machineOf(tg.addr));
          const left = (this.pending.get(k) ?? 1) - 1;
          left > 0 ? this.pending.set(k, left) : this.pending.delete(k);
          if (lines) this.addResult(tg, lines, m.re);
          cx.notify();
        }
      };
      try { await Promise.all(Array.from({ length: Math.min(PARALLEL, todo.length) }, worker)); } catch (e) { console.log(`ob-search: ${e}`); }
      if (gen === this.gen) { this.pending.clear(); cx.notify(); }
    });
  }

  addResult(tg, lines, re) {
    const hits = [];
    let count = 0;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      re.lastIndex = 0;
      const m = re.exec(line);
      if (!m) continue;
      count++;
      if (hits.length < MAX_HITS) hits.push({ idx: i, text: line, at: m.index, len: Math.max(1, m[0].length) });
    }
    if (!count) return;
    // Newest first: the bottom of a terminal is what happened last.
    hits.reverse();
    const sp = spaces();
    const group = { addr: tg.addr, pane: tg.pane, space: tg.space, tab: tg.tab, single: tg.single, total: lines.length, count, hits,
      order: sp.findIndex((s) => s.id === tg.space.id) * 1000 + (tg.tab.index ?? 0) };
    this.results = [...this.results.filter((g) => g.addr !== tg.addr), group].sort((a, b) => a.order - b.order);
  }

  // Hit lines in display order (what next/prev/open walk through).
  hits() {
    const out = [];
    for (const g of this.results) {
      if (this.folded.has(g.addr)) continue;
      const shown = this.expanded.has(g.addr) ? g.hits : g.hits.slice(0, SHOW);
      for (const line of shown) out.push({ group: g, line });
    }
    return out;
  }
  move(d) {
    const hs = this.hits();
    if (!hs.length) return;
    this.cursor = this.cursor < 0 ? (d > 0 ? 0 : hs.length - 1) : Math.max(0, Math.min(hs.length - 1, this.cursor + d));
    this.kbd = true;
    const h = hs[this.cursor];
    const i = this.rowIndex.get(`${h.group.addr}#${h.line.idx}`);
    if (i != null) this.scroll.scroll_to_item(i);
  }

  reveal(g) {
    run("space.select", { id: g.space.id });
    run("tab.select", { id: g.tab.id });
    run("pane.focus", { pane: g.pane.pane });
  }
  openHit(g, line) {
    this.reveal(g);
    // Lines counted from the bottom of what `hc read` returned (history above the screen, then the screen).
    const fromBottom = g.total - line.idx;
    const rows = terminals().find((t) => t.address === g.addr)?.rows ?? 24;
    run("terminal.scroll", { terminal: g.addr, to: "bottom" });
    if (fromBottom > rows) run("terminal.scroll", { terminal: g.addr, lines: -(fromBottom - Math.floor(rows / 2)) });
  }

  // ------------------------------------------------------------------ drawing
  label(g) {
    const ps = panes();
    const parts = [g.space.name, tabLabel(g.tab, ps)];
    if (!g.single) parts.push(paneName(g.pane));
    return this.w < 260 ? parts.slice(1).join(" / ") : parts.join(" / ");
  }
  lineEl(g, line, i, t) {
    const raw = line.text.replace(/\t/g, "  ");
    let at = line.at, text = raw;
    const lead = text.length - text.trimStart().length;
    text = text.trimStart(); at = Math.max(0, at - lead);
    const ctx = this.w < 260 ? 10 : 22;
    let pre = "";
    if (at > ctx) { pre = "…"; text = text.slice(at - ctx); at = ctx; }
    const before = pre + text.slice(0, at), hit = text.slice(at, at + line.len), after = text.slice(at + line.len);
    const cur = this.kbd && this.cursor === i;
    return h_flex().id(`hit-${g.addr}-${line.idx}`).h(S.rowSm).flex_none().pl(S.pad + S.indent + 4).pr(8).items_center().rounded(S.radius)
      .text_size(S.textSm).text_color(t.muted).overflow_hidden().cursor_pointer()
      .when(cur, (e) => e.bg(t.hover).border_1().border_color(alpha(t.accent, 0.55)))
      .when(!cur, (e) => e.hover((s) => s.bg(t.hover)))
      .child(div().absolute().top(0).bottom(0).left(S.pad + 7).w(1).bg(t.border))
      .relative()
      .on_click((_e, cx) => { this.cursor = i; this.kbd = false; this.openHit(g, line); cx.notify(); })
      .child(div().flex_none().whitespace_nowrap().child(before))
      .child(div().flex_none().whitespace_nowrap().px(1).rounded(2).bg(alpha(t.accent, 0.25)).text_color(t.foreground).child(hit))
      .child(div().min_w(0).flex_1().truncate().child(after));
  }
  groupEl(g, t) {
    const open = !this.folded.has(g.addr);
    const machine = machineOf(g.addr);
    return treeRow({
      id: `grp-${g.addr}`, depth: 0, chevron: open,
      onToggle: (_e, cx) => { open ? this.folded.add(g.addr) : this.folded.delete(g.addr); cx.notify(); },
      lead: programIcon(g.pane.program, S.iconSm, t.muted), label: this.label(g), labelColor: t.foreground,
      after: machine && this.w >= 240 ? [div().flex_none().text_size(10.5).text_color(t.dim).child(machine)] : [],
      right: [statusMark(g.pane.status && g.pane.status !== "idle" ? g.pane.status : null), badge(String(g.count), "accent")],
      onClick: (_e, cx) => { this.reveal(g); cx.notify(); },
    }).tooltip(`${machineLabel(machine)} · ${g.space.name} / ${tabLabel(g.tab, panes())} / ${paneName(g.pane)}`);
  }

  optToggle(id, text, on, tip, cmd) {
    const t = theme();
    return h_flex().id(id).h(20).min_w(22).px(4).flex_none().items_center().justify_center().rounded(S.radius)
      .text_size(11).font_semibold().text_color(on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
      .cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip(tip)
      .on_click((_e, cx) => { this.command(cmd, cx); cx.notify(); }).child(text);
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-search", null, (cx, intent) => {
      this.input.focus();
      if (intent?.startsWith("q:")) { this.input.set_value(intent.slice(2)); this.search(cx, true); }
    });
    const scope = SCOPES.find(([id]) => id === this.opts.scope) ?? SCOPES[0];
    const busy = this.pending.size > 0;
    const sessions = this.results.length, total = this.results.reduce((n, g) => n + g.count, 0);
    const rows = [];
    this.rowIndex = new Map();
    const hits = [];
    for (const g of this.results) {
      rows.push(this.groupEl(g, t));
      if (this.folded.has(g.addr)) continue;
      const shown = this.expanded.has(g.addr) ? g.hits : g.hits.slice(0, SHOW);
      for (const line of shown) {
        this.rowIndex.set(`${g.addr}#${line.idx}`, rows.length);
        rows.push(this.lineEl(g, line, hits.length, t));
        hits.push(line);
      }
      const more = g.hits.length - shown.length + (g.count - g.hits.length);
      if (more > 0 && !this.expanded.has(g.addr)) {
        rows.push(h_flex().id(`more-${g.addr}`).h(S.rowSm).flex_none().pl(S.pad + S.indent + 4).items_center().rounded(S.radius)
          .text_size(S.textXs).text_color(t.dim).cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.muted))
          .on_click((_e, cx) => { this.expanded.add(g.addr); cx.notify(); })
          .child(`+ ${more} more`));
      } else if (g.count > g.hits.length && this.expanded.has(g.addr)) {
        rows.push(div().h(S.rowSm).flex_none().pl(S.pad + S.indent + 4).flex().items_center().text_size(S.textXs).text_color(t.dim)
          .child(`${g.count - g.hits.length} more not listed`));
      }
    }
    const summary = this.error ? null
      : !this.q ? null
      : busy ? `${total} result${total === 1 ? "" : "s"} so far`
      : `${total} result${total === 1 ? "" : "s"} in ${sessions} session${sessions === 1 ? "" : "s"}`;

    let body;
    if (this.error) body = v_flex().px(S.pad + 4).pt(8).gap(4).child(div().text_size(S.textSm).text_color(t.blocked).child("Invalid pattern"))
      .child(div().text_size(S.textXs).text_color(t.dim).child(this.error));
    else if (!this.q) {
      body = v_flex().flex_1().min_h(0)
        .when(this.recent.length > 0, (e) => e.child(v_flex().px(S.pad).pt(4).gap(6)
          .child(h_flex().items_center().text_size(S.textXs).font_semibold().text_color(t.dim).child("RECENT").child(div().flex_1())
            .child(div().id("recent-clear").px(4).rounded(3).font_normal().cursor_pointer().hover((s) => s.text_color(t.foreground)).on_click((_e, cx) => { this.command("clear-recent", cx); cx.notify(); }).child("Clear")))
          .child(h_flex().flex_wrap().gap(4).children(this.recent.map((q, i) => h_flex().id(`recent-${i}`).h(22).max_w(220).px(8).rounded(11)
            .items_center().bg(t.raised).text_size(S.textSm).text_color(t.muted).cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.foreground))
            .on_click((_e, cx) => { this.input.set_value(q); this.search(cx, true); cx.notify(); })
            .child(div().truncate().child(q)))))))
        .child(emptyState({ icon: "search", title: "Search all sessions", body: "Finds text in the screen and history of every terminal in your spaces, on every machine. Press Enter to search." }));
    } else if (!rows.length) {
      body = busy ? v_flex().flex_1().items_center().justify_center().gap(8).child(statusMark("working", 16)).child(div().text_size(S.textSm).text_color(t.dim).child("Reading terminals…"))
        : emptyState({ icon: "search", title: "No matches", body: `No terminal in ${scope[1].toLowerCase()} shows “${this.q}”.` });
    } else {
      body = div().relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().px(4).pb(12).overflow_y_scroll().track_scroll(this.scroll).children(rows))
        .child(Scrollbar.vertical("list").absolute().inset_0());
    }

    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom ?? 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => this.key(e, cx))
      .child(h_flex().flex_none().pt(8).pb(4).child(inputFrame("q", Input.new(this.input).h_full().text_size(S.textSm).text_color(t.foreground), {
        focused: this.inputFocused,
        right: [
          ...(this.input.value() ? [iconButton({ id: "q-clear", icon: "x", size: 18, iconSize: S.iconXs, tip: "Clear", onClick: (_e, cx) => { this.input.set_value(""); this.search(cx, false, true); this.input.focus(); cx.notify(); } })] : []),
          this.optToggle("opt-case", "Aa", this.opts.case, "Match case", "case:toggle"),
          this.optToggle("opt-regex", ".*", this.opts.regex, "Use regular expression", "regex:toggle"),
        ],
      }).flex_1()))
      .child(h_flex().h(26).flex_none().px(S.pad).gap(6).items_center().text_size(S.textXs).text_color(t.dim)
        .child(h_flex().id("scope").h(20).px(5).gap(4).flex_none().items_center().rounded(S.radius).cursor_pointer()
          .hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip("Where to search")
          .on_click(() => openMenu(SCOPES.map(([id, label, ic]) => ({ label, icon: ic, checked: id === this.opts.scope, command: `ob-search.scope:${id}` })), { width: 200, title: "Search in" }))
          .child(icon(scope[2], S.iconXs)).child(scope[1]).child(icon("chevron-down", 10)))
        .child(div().flex_1().min_w(0).truncate().text_right().child(summary ?? ""))
        .when(busy, (e) => e.child(h_flex().flex_none().gap(4).items_center().tooltip(`Reading: ${[...this.pending.keys()].join(", ")}`)
          .child(statusMark("working", S.iconXs)).when(this.w >= 240, (x) => x.child(div().max_w(90).truncate().child(`${[...this.pending.keys()].join(", ")}…`)))))
        .when(Boolean(this.q) && !busy && !this.error, (e) => e.child(iconButton({ id: "rescan", icon: "refresh", size: 20, iconSize: S.iconXs, tip: "Read the terminals again", onClick: (_e, cx) => { this.command("rescan", cx); cx.notify(); } }))))
      .child(body);
  }

  key(e, cx) {
    if (this.inputFocused) {
      if (e.key === "down" && this.results.length) { this.handle.focus(); this.cursor = -1; this.move(1); }
      else if (e.key === "escape" && this.input.value()) { this.input.set_value(""); this.search(cx, false, true); }
      else return;
    } else {
      if (e.key === "down") this.move(1);
      else if (e.key === "up") { if (this.cursor <= 0) { this.input.focus(); this.kbd = false; } else this.move(-1); }
      else if (e.key === "enter") { const h = this.hits()[this.cursor]; if (h) this.openHit(h.group, h.line); }
      else if (e.key === "escape") { this.kbd = false; this.input.focus(); }
      else return;
    }
    cx.stop_propagation();
    cx.notify();
  }
}
