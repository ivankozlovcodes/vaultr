// ob-switcher: Obsidian's quick switcher for Herdr (a popup at the top, 660 x 0.72, `popover`).
// Type to find a tab, space, agent, sub-agent, bookmark or sidebar view; Enter goes there.
// Empty query: Recent visits, then Bookmarks, then every other tab. No match: create a tab or a
// space with that name. Modes (props.mode, Tab cycles go/views): go (default), views (sidebar
// views only), move (ctrl-shift-m: move the active tab; Herdr can only reorder within a space).
//
// Keys: ↑/↓ (PgUp/PgDn) move, Enter open, Shift+Enter create a tab named like the query,
// Ctrl+Enter open to the right (agents and sub-agent terminals: kept as a pane on the right),
// Tab switches go/views, Esc closes.
// Commands (ob-switcher.<cmd>, the test path; no keyboard in tests):
//   mode:<go|move|views>  query:<text>  down  up  enter  close
//   create (= Shift+Enter)  open-right (= Ctrl+Enter)  tab (= Tab)

import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, ScrollHandle, Scrollbar } from "gpui-base";
import {
  props, run, closeOverlay, nextCommand, shared, spaces, panes, agents, terminals, layout, settings,
} from "herdr";
import {
  S, tc, alpha, icon, programIcon, avatar, statusMark, fuzzy, highlight, machineLabel, tabLabel,
  feed, bookmarks, VIEWS, findNode, current, chordParts,
} from "./kit.js";

const ROW_H = 34;
const HEAD_H = 28;
const MODES = ["go", "views"]; // what Tab cycles through (move is its own entry point)
const MAX_RECENT = 10;
const PLACEHOLDER = {
  go: "Find a session, space, agent or view…",
  views: "Find a view…",
  move: "Find a space or a position…",
};

const ls = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
const q = (s) => `“${s}”`;

export default class Switcher extends View {
  init(_p, cx) {
    const m = props()?.mode;
    this.mode = m === "move" || m === "views" ? m : "go";
    this.query = "";
    this.at = 0;
    this.width = 0;
    this.recent = ls("recent", []).filter((k) => typeof k === "string");
    this.scroll = ScrollHandle.new();
    this.handle = cx.focus_handle();
    // One input per mode (an InputState's placeholder is fixed); Tab swaps them, keeping the text.
    this.inputs = {};
    for (const m of ["go", "views", "move"]) {
      const inp = InputState.new({ placeholder: PLACEHOLDER[m] });
      inp.on("change", (_e, cx) => { if (this.input !== inp) return; this.query = inp.value(); this.at = this.firstPick(); this.reveal(); cx.notify(); });
      inp.on("submit", (_e, cx) => {
        // Shift/Ctrl+Enter are handled in on_key_down (which runs first and stops the event); this
        // guard covers an Input that submits on them anyway.
        if (this.input !== inp || Date.now() - (this.modEnterAt ?? 0) < 200) return;
        this.accept(cx, "open");
      });
      this.inputs[m] = inp;
    }
    this.input = this.inputs[this.mode];
    this.input.focus();
    cx.timer.after(60, () => this.input.focus());
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c, cx); } catch (e) { console.log(`ob-switcher: ${c} failed: ${e?.stack ?? e}`); }
        cx.notify();
      }
    });
  }

  close() { closeOverlay(props()?.overlay); }

  command(c, cx) {
    const s = String(c ?? "");
    const i = s.indexOf(":");
    const verb = i < 0 ? s : s.slice(0, i);
    const arg = i < 0 ? "" : s.slice(i + 1);
    if (verb === "close") return this.close();
    if (verb === "focus") return this.input.focus();
    if (verb === "mode") { if (["go", "move", "views"].includes(arg)) this.setMode(arg); return; }
    if (verb === "query") { this.query = arg; this.input.set_value(arg); this.at = this.firstPick(); this.reveal(); return; }
    if (verb === "down") return this.move(1);
    if (verb === "up") return this.move(-1);
    if (verb === "enter") return this.accept(cx, "open");
    if (verb === "create") return this.accept(cx, "create");
    if (verb === "open-right") return this.accept(cx, "right");
    if (verb === "tab") return this.cycleMode();
  }

  setMode(m) {
    this.mode = m;
    const next = this.inputs[m];
    if (next && next !== this.input) {
      next.set_value(this.query);
      this.input = next;
      this.input.focus();
    }
    this.at = this.firstPick();
    this.reveal();
  }
  cycleMode() {
    const i = MODES.indexOf(this.mode);
    this.setMode(MODES[(i + 1) % MODES.length] ?? "go");
  }

  // ---------------------------------------------------------------- data
  // Everything the switcher can go to, as items:
  // { key, kind, label, context, words, status, here, bookmarked, settled, terminal (address: Ctrl+Enter
  //   keeps it on the right), lead: () => element, go: () => void, disabled, hint, quiet, create }
  model() {
    const sp = spaces() ?? [];
    const ps = panes() ?? [];
    const ag = agents() ?? [];
    const terms = terminals() ?? [];
    const cur = current();
    const bms = bookmarks();
    const isBm = (kind, id) => bms.some((b) => b.kind === kind && b.id === id);
    const where = new Map(); // terminal address -> { space, tab }
    const tabById = new Map();
    for (const s of sp) for (const tb of s.tabs ?? []) tabById.set(tb.id, { space: s, tab: tb });
    for (const p of ps) if (p.terminal && tabById.has(p.tab)) where.set(p.terminal, tabById.get(p.tab));
    const tabText = (tb) => tabLabel(tb, ps);
    const ctxOf = (s) => (s ? `${machineLabel(s.machine)} / ${s.name}` : "");
    const items = [];

    for (const s of sp) {
      for (const tb of s.tabs ?? []) {
        const mine = ps.filter((p) => p.tab === tb.id);
        const lead = mine.find((p) => p.program?.agent) ?? mine.find((p) => p.focused) ?? mine[0];
        const progs = [...new Set(mine.map((p) => p.program?.name).filter(Boolean))];
        items.push({
          key: `tab:${tb.id}`, kind: "tab", label: tabText(tb), context: ctxOf(s), words: progs.join(" "),
          status: tb.status, here: tb.id === cur.tab?.id, bookmarked: isBm("tab", tb.id), settled: tb.settled,
          lead: () => (lead?.program ? programIcon(lead.program, S.icon) : icon("tab", S.icon)),
          go: () => { run("space.select", { id: s.id }); run("tab.select", { id: tb.id }); },
        });
      }
      items.push({
        key: `space:${s.id}`, kind: "space", label: s.name, context: `${machineLabel(s.machine)} · space · ${(s.tabs ?? []).length} tab${(s.tabs ?? []).length === 1 ? "" : "s"}`,
        words: "space", status: s.status, here: s.id === cur.space?.id, bookmarked: isBm("space", s.id),
        lead: () => avatar(s, 16), go: () => run("space.select", { id: s.id }),
      });
    }

    for (const a of ag) {
      const w = where.get(a.address);
      const tl = w ? tabText(w.tab) : a.tab_name ?? "";
      items.push({
        key: `agent:${a.address}`, kind: "agent", label: a.title || a.program?.name || a.app || "agent",
        context: `${a.program?.name ?? "agent"} · ${w ? ctxOf(w.space) : a.space_name ?? ""} / ${tl}`, words: `agent ${a.app ?? ""} ${tl}`,
        status: a.status, bookmarked: isBm("terminal", a.address), terminal: a.address,
        lead: () => programIcon(a.program, S.icon), go: () => run("agent.focus", { terminal: a.address }),
      });
    }

    // Sub-agents: hc child terminals, pi runs, Claude agents.
    const parentText = (addr) => { const w = where.get(addr); return w ? tabText(w.tab) : addr ?? "?"; };
    for (const t of terms) {
      if (!t?.parent || t.state !== "live") continue;
      items.push({
        key: `child:${t.address}`, kind: "child", label: t.name || t.program?.name || t.title || t.address,
        context: `subagent of ${parentText(t.parent)}`, words: `subagent ${t.program?.name ?? ""}`,
        status: t.status ?? null, terminal: t.address, bookmarked: isBm("terminal", t.address),
        lead: () => programIcon(t.program, S.icon), go: () => run("terminal.peek", { terminal: t.address }),
      });
    }
    const f = feed();
    for (const r of f?.runs ?? []) {
      const chain = (r.steps ?? []).map((st) => st.agent).filter(Boolean);
      const label = chain.length > 3 ? `workflow · ${chain.length} agents` : chain.join(" → ") || `run ${r.short ?? r.id ?? ""}`;
      const task = r.steps?.[0]?.task ?? "";
      items.push({
        key: `run:${r.key}`, kind: "run", label, context: `subagent of ${r.parent ? parentText(r.parent) : `unattached · ${machineLabel(r.machine)}`}`,
        words: `subagent pi ${task} ${r.short ?? ""}`, status: r.live ? "working" : r.state, bookmarked: isBm("run", r.key) || isBm("run", r.id),
        lead: () => icon("subagents", S.icon), go: () => run(`ob-tabs.open:ob-subagents@run:${r.key}`),
      });
    }
    const liveRec = new Map();
    for (const t of terms) for (const [id, rec] of Object.entries(t?.records ?? {})) liveRec.set(`${t.address}#${id}`, rec);
    for (const c of f?.claude ?? []) {
      const rec = liveRec.get(`${c.parent}#${c.id}`);
      const live = rec ? rec.state === "working" || rec.state === "blocked" : Boolean(c.live);
      items.push({
        key: `claude:${c.key}`, kind: "claude", label: c.desc || c.type || "Claude agent", context: `subagent of ${parentText(c.parent)}${c.type ? ` · ${c.type}` : ""}`,
        words: `subagent claude ${c.type ?? ""}`, status: live ? "working" : "ok",
        lead: () => icon("bot", S.icon), go: () => run(`ob-tabs.open:ob-subagents@run:${c.key}`),
      });
    }

    // Sidebar views of this layout.
    const root = layout();
    for (const [id, v] of Object.entries(VIEWS)) {
      if (!findNode(root, id)) continue;
      items.push({
        key: `view:${id}`, kind: "view", label: `View: ${v.title}`, context: "sidebar", words: "view panel sidebar",
        lead: () => icon(v.icon, S.icon), go: () => run(`ob-tabs.open:${id}`),
      });
    }

    // Bookmarks whose target is gone still show (dimmed) so they can be found and removed.
    const byKey = new Map(items.map((it) => [it.key, it]));
    const bmItems = [];
    for (const b of bms) {
      const k = b.kind === "tab" ? `tab:${b.id}` : b.kind === "space" ? `space:${b.id}` : b.kind === "run" ? (byKey.has(`run:${b.id}`) ? `run:${b.id}` : `run:${(f?.runs ?? []).find((r) => r.id === b.id)?.key}`)
        : byKey.has(`agent:${b.id}`) ? `agent:${b.id}` : `child:${b.id}`;
      const it = byKey.get(k);
      bmItems.push(it ?? { key: `bm:${b.kind}:${b.id}`, kind: "gone", label: b.label || b.id, context: `bookmark · ${b.kind} · gone`, disabled: true, hint: "gone", lead: () => icon("bookmark", S.icon) });
    }
    return { items, byKey, bmItems, cur };
  }

  // ---------------------------------------------------------------- rows
  // rows: [{ head }, { item, hits }]; picks: indexes of selectable rows.
  rows() {
    const { items, byKey, bmItems, cur } = this.model();
    const query = this.query.trim();
    const out = [];
    if (this.mode === "move") return this.moveRows(cur, query);
    const pool = this.mode === "views" ? items.filter((it) => it.kind === "view") : items;
    if (!query) {
      if (this.mode === "views") { for (const it of pool) out.push({ item: it }); return out; }
      const recent = this.recentItems(byKey, cur);
      const used = new Set();
      if (recent.length) { out.push({ head: "Recent" }); for (const it of recent) { out.push({ item: it }); used.add(it.key); } }
      const bm = bmItems.filter((it) => !used.has(it.key));
      if (bm.length) { out.push({ head: "Bookmarks" }); for (const it of bm) { out.push({ item: it }); used.add(it.key); } }
      const tabs = items.filter((it) => it.kind === "tab" && !used.has(it.key) && !it.here);
      if (tabs.length) { out.push({ head: "Tabs" }); for (const it of tabs) out.push({ item: it }); }
      return out;
    }
    const rank = this.recencyRank(byKey, cur);
    const scored = [];
    for (const it of pool) {
      const title = fuzzy(query, it.label);
      const more = title ? null : fuzzy(query, `${it.label} ${it.context ?? ""} ${it.words ?? ""}`);
      const best = title ?? (more && { score: more.score - 4, hits: [] });
      if (!best) continue;
      // Settled tabs and where you already are sink a little; bookmarks rise a little.
      const adj = (it.here ? -2 : 0) + (it.settled ? -1 : 0) + (it.bookmarked ? 1 : 0);
      scored.push({ item: it, hits: best.hits, score: best.score + adj, r: rank.get(it.key) ?? 999 });
    }
    scored.sort((a, b) => Math.round(b.score) - Math.round(a.score) || a.r - b.r || b.score - a.score);
    for (const s of scored) out.push(s);
    if (this.mode === "go") {
      const m = cur.space;
      if (!scored.length) out.push({ head: "No matches" });
      else out.push({ head: "Create" });
      out.push({ item: { key: "create:tab", kind: "create", label: `Create tab ${q(query)} here`, context: m ? `in ${m.name}` : "", lead: () => icon("plus", S.icon), go: () => run("tab.new", { name: query, ...(m ? { space: m.id } : {}) }), create: "tab" } });
      out.push({ item: { key: "create:space", kind: "create", label: `Create space ${q(query)}`, context: machineLabel(m?.machine ?? null), lead: () => icon("folder-plus", S.icon), go: () => run("space.new", { name: query, machine: m?.machine ?? "" }), create: "space" } });
    }
    return out;
  }

  // Recent: the visits in ob.history (newest first) and this switcher's own picks, max 10.
  recentKeys(byKey, cur) {
    const h = shared("ob.history");
    const entries = Array.isArray(h?.entries) ? [...h.entries].sort((a, b) => (b?.at ?? 0) - (a?.at ?? 0)) : [];
    const keys = [];
    const add = (k) => { if (k && byKey.has(k) && !keys.includes(k) && k !== `tab:${cur.tab?.id}`) keys.push(k); };
    for (const e of entries) add(e?.tab ? `tab:${e.tab}` : e?.space ? `space:${e.space}` : null);
    for (const k of this.recent) add(k);
    return keys;
  }
  recentItems(byKey, cur) { return this.recentKeys(byKey, cur).slice(0, MAX_RECENT).map((k) => byKey.get(k)); }
  recencyRank(byKey, cur) {
    const m = new Map();
    this.recentKeys(byKey, cur).forEach((k, i) => m.set(k, i));
    return m;
  }

  // Move mode: reorder the active tab in its space; other spaces are listed but Herdr has no
  // command to move a tab between spaces (SPEC U4), so they are disabled with that hint.
  moveRows(cur, query) {
    const out = [];
    const space = cur.space;
    const tab = cur.tab;
    if (!space || !tab) { out.push({ head: "No tab to move" }); return out; }
    const tabs = space.tabs ?? [];
    const pos = tabs.findIndex((x) => x.id === tab.id) + 1; // 1 = first (tab.move's index)
    const n = tabs.length;
    const mv = (label, index, ic, enabled) => ({
      key: `move:${label}`, kind: "move", label, context: enabled ? `position ${index} of ${n}` : "already there",
      disabled: !enabled, lead: () => icon(ic, S.icon), go: () => run("tab.move", { id: tab.id, index }),
    });
    const here = [
      mv("Move left", Math.max(1, pos - 1), "arrow-left", pos > 1),
      mv("Move right", Math.min(n, pos + 1), "arrow-right", pos < n),
      mv("Move to the start", 1, "chevron-left", pos > 1),
      mv("Move to the end", n, "chevron-right", pos < n),
    ];
    const others = (spaces() ?? []).filter((s) => s.id !== space.id).map((s) => ({
      key: `move-to:${s.id}`, kind: "space", label: s.name, context: machineLabel(s.machine), disabled: true,
      hint: "Herdr can't move tabs between spaces yet", quiet: true, lead: () => avatar(s, 16),
    }));
    const match = (it) => {
      if (!query) return { item: it, hits: [] };
      const f = fuzzy(query, it.label);
      return f ? { item: it, hits: f.hits, score: f.score } : null;
    };
    const a = here.map(match).filter(Boolean);
    const b = others.map(match).filter(Boolean).sort((x, y) => (y.score ?? 0) - (x.score ?? 0));
    if (a.length) { out.push({ head: `In ${space.name}` }); out.push(...a); }
    if (b.length) { out.push({ head: "Other spaces · Herdr can't move tabs between spaces yet" }); out.push(...b); }
    return out;
  }

  // ---------------------------------------------------------------- cursor
  picks(rows) { return rows.map((r, i) => (r.item && !r.item.disabled ? i : -1)).filter((i) => i >= 0); }
  firstPick() { return 0; }
  move(d) {
    const rows = this.rows();
    const picks = this.picks(rows);
    if (!picks.length) return;
    this.at = Math.max(0, Math.min(picks.length - 1, this.at + d));
    this.reveal(rows);
  }
  reveal(rows) {
    const r = rows ?? this.rows();
    const picks = this.picks(r);
    const idx = picks[Math.min(this.at, picks.length - 1)];
    if (idx == null) return;
    // A row that opens a group is shown with its title.
    this.scroll.scroll_to_item(idx > 0 && r[idx - 1]?.head ? idx - 1 : idx);
  }

  accept(cx, how) {
    const rows = this.rows();
    const picks = this.picks(rows);
    let it = rows[picks[Math.min(this.at, picks.length - 1)]]?.item;
    if (how === "create" && this.mode === "go" && this.query.trim()) it = rows.find((r) => r.item?.create === "tab")?.item ?? it;
    if (!it || it.disabled || !it.go) return;
    if (!it.create && it.kind !== "move") {
      this.recent = [it.key, ...this.recent.filter((k) => k !== it.key)].slice(0, 30);
      lsSet("recent", this.recent);
    }
    this.close();
    if (how === "right" && it.terminal) run("terminal.keep", { terminal: it.terminal, place: "right" });
    else it.go(how);
  }

  onKey(e, cx) {
    const k = e.key;
    const m = e.modifiers ?? {};
    if (k === "escape") { cx.stop_propagation(); return this.close(); }
    if (k === "down" || (k === "n" && m.control && !m.shift)) this.move(1);
    else if (k === "up" || (k === "p" && m.control && !m.shift)) this.move(-1);
    else if (k === "pagedown") this.move(8);
    else if (k === "pageup") this.move(-8);
    else if (k === "tab" && !m.control && !m.alt) { if (this.mode !== "move") this.cycleMode(); }
    else if (k === "enter" && m.shift) { this.modEnterAt = Date.now(); this.accept(cx, "create"); }
    else if (k === "enter" && (m.control || m.platform)) { this.modEnterAt = Date.now(); this.accept(cx, "right"); }
    else return;
    cx.stop_propagation();
    cx.notify();
  }

  // ---------------------------------------------------------------- render
  render() {
    const t = tc();
    const rows = this.rows();
    const picks = this.picks(rows);
    this.at = Math.max(0, Math.min(this.at, picks.length - 1));
    const sel = picks[this.at];
    const zoom = settings().zoom || 1;
    let vh = 900;
    try { vh = globalThis.window?.viewport_size?.()?.height ?? vh; } catch { /* no window */ }
    // The popup may be 72% of the window tall; the list gets what the input and footer leave.
    const listMax = Math.max(4 * ROW_H, Math.floor((vh * 0.72) / zoom) - 56 - 40 - (this.mode === "move" ? 34 : 0) - 8);
    const contentH = rows.reduce((h, r) => h + (r.head ? HEAD_H : ROW_H), 8);
    const listH = Math.min(listMax, contentH);
    const tab = current().tab;
    const tabName = tab ? tabLabel(tab, panes() ?? []) : "";
    return v_flex().id("root").track_focus(this.handle).w_full().min_h(0).bg(t.popover).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / zoom; if (Math.abs(w - this.width) > 1) { this.width = w; cx.notify(); } })
      .on_key_down((e, cx) => this.onKey(e, cx))
      .when(this.mode === "move", (el) => el.child(h_flex().h(34).flex_none().px(16).pt(10).gap(8).items_center()
        .child(icon("move", S.iconSm, t.muted))
        .child(div().min_w(0).truncate().text_size(S.textLg - 1).font_semibold().child(`Move ${q(tabName)} to…`))))
      .child(h_flex().h(56).flex_none().px(16).gap(10).items_center().border_b(1).border_color(t.border)
        .child(icon(this.mode === "views" ? "layers" : this.mode === "move" ? "move" : "search", S.icon + 2, t.dim))
        .child(div().flex_1().min_w(0).child(Input.new(this.input).h(36).text_size(S.textLg + 1).text_color(t.foreground)))
        .when(this.mode !== "move", (el) => el.child(h_flex().id("sw-mode").flex_none().h(22).px(8).gap(5).rounded(S.radius).items_center()
          .bg(t.raised).text_size(S.textXs).text_color(t.muted).cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.foreground))
          .tooltip("Tab switches between everything and sidebar views")
          .on_click((_e, cx) => { this.cycleMode(); cx.notify(); })
          .child(this.mode === "views" ? "Views" : "Everything").child(icon("chevron-down", S.iconXs)))))
      .child(rows.length
        ? div().relative().flex_none().h(listH)
          .child(v_flex().id("sw-list").size_full().overflow_y_scroll().track_scroll(this.scroll).px(6).py(4)
            .children(rows.map((r, i) => (r.head ? this.head(t, r.head, i) : this.row(t, r, i, i === sel)))))
          .child(Scrollbar.vertical("sw-list").absolute().inset_0())
        : this.empty(t))
      .child(this.footer(t));
  }

  head(t, text, i) {
    return h_flex().id(`sw-h-${i}`).flex_none().h(HEAD_H).px(10).pt(8).items_center().text_size(S.textXs).font_semibold().text_color(t.dim).child(text);
  }

  row(t, r, i, on) {
    const it = r.item;
    const narrow = this.width > 0 && this.width < 480;
    const labelColor = it.disabled ? t.dim : t.foreground;
    const label = r.hits?.length ? highlight(it.label, r.hits, labelColor) : div().min_w(0).truncate().text_color(labelColor).child(it.label);
    return h_flex().id(`sw-r-${i}`).flex_none().h(ROW_H).px(10).gap(10).items_center().rounded(S.radiusLg).text_size(S.text)
      .when(on, (el) => el.bg(t.selected))
      .when(!on && !it.disabled, (el) => el.hover((s) => s.bg(t.hover)))
      .when(!it.disabled, (el) => el.cursor_pointer().on_click((_e, cx) => {
        const picks = this.picks(this.rows());
        const at = picks.indexOf(i);
        if (at >= 0) { this.at = at; this.accept(cx, "open"); }
      }))
      .when(Boolean(it.hint), (el) => el.tooltip(it.hint))
      .child(h_flex().size(18).flex_none().items_center().justify_center().when(Boolean(it.disabled), (el) => el.opacity(0.5)).child(it.lead ? it.lead() : div()))
      .child(h_flex().flex_1().min_w(0).gap(8).items_center().overflow_hidden()
        .child(h_flex().flex_shrink(0).max_w(narrow ? 220 : 380).min_w(0).overflow_hidden().child(label))
        .when(Boolean(it.bookmarked), (el) => el.child(icon("bookmark", S.iconXs, t.accent)))
        .when(Boolean(it.context) && !narrow, (el) => el.child(div().flex_1().min_w(0).truncate().text_size(S.textSm).text_color(t.dim).child(it.context)))
        .when(Boolean(it.settled), (el) => el.child(div().flex_none().text_size(S.textXs).text_color(t.dim).child("settled"))))
      .when(Boolean(it.disabled && it.hint && !it.quiet), (el) => el.child(div().flex_none().text_size(S.textXs).text_color(t.dim).child(it.hint)))
      .when(it.status != null, (el) => el.child(statusMark(it.status)))
      .when(on, (el) => el.child(h_flex().flex_none().h(18).px(5).rounded(4).items_center().border_1().border_color(t.input).bg(t.raised)
        .text_size(S.textXs).text_color(t.muted).child("↵")));
  }

  empty(t) {
    const text = this.mode === "move" ? "Nothing to move here." : this.mode === "views" ? `No view matches ${q(this.query)}.` : "Nothing yet: no tabs or spaces to show.";
    return v_flex().flex_none().py(28).gap(6).items_center()
      .child(icon(this.mode === "views" ? "layers" : "search", 24, t.dim))
      .child(div().text_size(S.textSm).text_color(t.muted).child(text));
  }

  footer(t) {
    const key = (k) => h_flex().flex_none().h(16).min_w(16).px(4).rounded(3).items_center().justify_center()
      .border_1().border_color(t.input).bg(t.raised).text_size(10).font_medium().text_color(t.muted).child(k);
    const hint = (keysList, text) => h_flex().flex_none().gap(4).items_center().child(h_flex().gap(2).children(keysList.map(key))).child(div().text_color(t.dim).child(text));
    const ctrl = chordParts("ctrl")[0] ?? "Ctrl";
    const items = this.mode === "move"
      ? [hint(["↑", "↓"], "to navigate"), hint(["↵"], "to move"), hint(["esc"], "to dismiss")]
      : [
        hint(["↑", "↓"], "to navigate"), hint(["↵"], "to open"),
        ...(this.mode === "go" ? [hint(["⇧", "↵"], "to create"), hint([ctrl, "↵"], "to the right")] : []),
        hint(["tab"], this.mode === "views" ? "everything" : "views"), hint(["esc"], "to dismiss"),
      ];
    return h_flex().h(40).flex_none().px(16).gap(14).items_center().border_t(1).border_color(t.border).text_size(S.textXs)
      .bg(alpha(t.background, 0.35)).overflow_hidden().children(items);
  }
}
