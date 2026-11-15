// ob-bookmarks: Obsidian's Bookmarks, for sessions. Spaces, tabs, sessions (terminals) and sub-agent
// runs you bookmarked (shared "ob.bookmarks", via kit), grouped by kind, with live status. A target
// that no longer exists is dimmed with "gone" and a remove button. Click opens; drag reorders;
// right-click: Open, Remove, Move up/down.
//
// Commands (herdr-app do ob-bookmarks.<cmd>): focus, open:<index>, remove:<index>, up:<index>,
// down:<index>, add:<tab|space|session>, move:<from>@<to>, next, prev.  <index> = position in ob.bookmarks.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { spaces, panes, terminals, run, theme, props, nextCommand, settings, setShared } from "herdr";
import {
  S, icon, programIcon, iconButton, treeRow, avatar, emptyState, openMenu, statusMark, needsYou, normStatus,
  sectionHeader, takeFocus, bookmarks, toggleBookmark, tabLabel, paneName, current, feed, bindingFor, chordLabel,
  openView, machineOf, ago,
} from "./kit.js";

const KINDS = [["space", "Spaces"], ["tab", "Tabs"], ["terminal", "Sessions"], ["run", "Runs"]];
function splitCmd(c) { const s = String(c ?? ""); const i = s.indexOf(":"); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; }
function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } }

export default class Bookmarks extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.folded = new Set(load("folded", []));
    this.cursor = -1; // a bookmark index
    this.kbd = false;
    this.pressed = null;
    this.over = null;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c); } catch (e) { console.log(`ob-bookmarks: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  list() { return Array.isArray(bookmarks()) ? bookmarks().filter((b) => b && b.kind && b.id) : []; }
  write(list) { setShared("ob.bookmarks", list); }

  command(c) {
    const [verb, arg] = splitCmd(c);
    const i = arg === "" ? this.cursor : Number(arg);
    const list = this.list();
    switch (verb) {
      case "focus": this.handle.focus(); this.kbd = true; if (this.cursor < 0 && list.length) this.cursor = this.order()[0] ?? -1; break;
      case "open": if (list[i]) this.open(list[i]); break;
      case "remove": if (list[i]) { this.write(list.filter((_, k) => k !== i)); if (this.cursor >= list.length - 1) this.cursor = list.length - 2; } break;
      case "up": this.shift(i, -1); break;
      case "down": this.shift(i, 1); break;
      case "move": { const [a, b] = arg.split("@").map(Number); this.drop(a, b); break; }
      case "add": this.add(arg); break;
      case "next": this.step(1); break;
      case "prev": this.step(-1); break;
      default: console.log(`ob-bookmarks: unknown command ${c}`);
    }
  }

  // Bookmark what the window shows now.
  add(what) {
    const cur = current();
    const ps = panes();
    if (what === "space" && cur.space) toggleBookmark({ kind: "space", id: cur.space.id, label: cur.space.name, machine: cur.space.machine ?? null });
    else if (what === "session" && cur.terminal) {
      const p = ps.find((x) => x.terminal === cur.terminal);
      toggleBookmark({ kind: "terminal", id: cur.terminal, label: `${cur.space?.name ?? ""} · ${p ? paneName(p) : cur.terminal}`, machine: machineOf(cur.terminal) });
    } else if (cur.tab) toggleBookmark({ kind: "tab", id: cur.tab.id, label: tabLabel(cur.tab, ps), machine: cur.space?.machine ?? null });
  }

  // Swap with the neighbour of the same kind (the order the list shows).
  shift(i, d) {
    const list = this.list();
    if (!list[i]) return;
    let j = i + d;
    while (j >= 0 && j < list.length && list[j].kind !== list[i].kind) j += d;
    if (j < 0 || j >= list.length) return;
    const next = [...list];
    [next[i], next[j]] = [next[j], next[i]];
    this.write(next);
    if (this.cursor === i) this.cursor = j;
  }
  drop(from, to) {
    const list = this.list();
    if (!list[from] || !list[to] || from === to || list[from].kind !== list[to].kind) return;
    const next = [...list];
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    this.write(next);
  }

  // What a bookmark points at now: { gone, label, status, lead, machine, go }.
  resolve(b, ctx) {
    const t = theme();
    if (b.kind === "space") {
      const s = ctx.sp.find((x) => x.id === b.id);
      if (!s) return { gone: true, lead: icon("folder", S.iconSm, t.dim) };
      return { label: s.name, status: s.status, lead: avatar(s, 16), machine: s.machine, go: () => run("space.select", { id: s.id }) };
    }
    if (b.kind === "tab") {
      const s = ctx.sp.find((x) => (x.tabs ?? []).some((y) => y.id === b.id));
      const tab = s?.tabs.find((y) => y.id === b.id);
      if (!tab) return { gone: true, lead: icon("tab", S.iconSm, t.dim) };
      const mine = ctx.ps.filter((p) => p.tab === tab.id);
      const lead = mine.length === 1 ? programIcon(mine[0].program, S.iconSm, t.muted) : icon("tab", S.iconSm, t.dim);
      return { label: tabLabel(tab, ctx.ps), context: s.name, status: tab.status, lead, machine: s.machine,
        go: () => { run("space.select", { id: s.id }); run("tab.select", { id: tab.id }); } };
    }
    if (b.kind === "terminal") {
      const term = ctx.ts.find((x) => x.address === b.id && x.state === "live");
      if (!term) return { gone: true, lead: icon("terminal", S.iconSm, t.dim) };
      const p = ctx.ps.find((x) => x.terminal === b.id);
      if (!p) return { label: b.label || term.name || b.id, status: term.status, agent: true, lead: programIcon(term.program, S.iconSm, t.muted), machine: machineOf(b.id), go: () => run("terminal.peek", { terminal: b.id }) };
      const s = ctx.sp.find((x) => (x.tabs ?? []).some((y) => y.id === p.tab));
      return { label: b.label || paneName(p), status: p.status, agent: Boolean(p.program?.agent), lead: programIcon(p.program, S.iconSm, t.muted), machine: s?.machine ?? machineOf(b.id),
        go: () => { if (s) run("space.select", { id: s.id }); run("tab.select", { id: p.tab }); run("pane.focus", { pane: p.pane }); } };
    }
    if (b.kind === "run") {
      const r = (feed()?.runs ?? []).find((x) => x.key === b.id);
      const chain = (r?.steps ?? []).map((s) => s.agent).filter(Boolean).join(" → ");
      // A run the feed dropped (older than a day) can still be opened by key in Subagents' history.
      return { label: chain || b.label || b.id, status: r ? (r.live ? "working" : r.state) : null, gone: !r, lead: icon("subagents", S.iconSm, t.dim),
        machine: r?.machine ?? b.machine, meta: r && !r.live ? ago(r.endedAt ?? r.lastUpdate) : "", go: () => openView("ob-outline", `run:${b.id}`) };
    }
    return { gone: true, lead: icon("bookmark", S.iconSm, t.dim) };
  }
  ctx() { return { sp: spaces(), ps: panes(), ts: terminals() }; }
  open(b) { const r = this.resolve(b, this.ctx()); if (!r.gone) r.go?.(); }

  // Bookmark indexes in display order (grouped by kind, folded groups left out).
  order() {
    const list = this.list();
    const out = [];
    for (const [kind] of KINDS) if (!this.folded.has(kind)) list.forEach((b, i) => { if (b.kind === kind) out.push(i); });
    return out;
  }
  step(d) {
    const ord = this.order();
    if (!ord.length) return;
    const at = ord.indexOf(this.cursor);
    this.cursor = ord[at < 0 ? (d > 0 ? 0 : ord.length - 1) : Math.max(0, Math.min(ord.length - 1, at + d))];
    this.kbd = true;
    const ri = this.rowIndex?.get(this.cursor);
    if (ri != null) this.scroll.scroll_to_item(ri);
  }

  menu(i) {
    const b = this.list()[i];
    if (!b) return;
    const gone = this.resolve(b, this.ctx()).gone;
    openMenu([
      { label: "Open", icon: "external", command: `ob-bookmarks.open:${i}`, disabled: gone },
      { label: "Move up", icon: "chevron-up", command: `ob-bookmarks.up:${i}` },
      { label: "Move down", icon: "chevron-down", command: `ob-bookmarks.down:${i}` },
      { separator: true },
      { label: "Remove bookmark", icon: "trash", danger: true, command: `ob-bookmarks.remove:${i}` },
    ], { width: 220, title: b.label || "Bookmark" });
  }

  row(b, i, ctx, t) {
    const r = this.resolve(b, ctx);
    const compact = this.w < 220;
    const cur = this.kbd && this.cursor === i;
    const label = r.label ?? b.label ?? b.id;
    const st = r.status && normStatus(r.status) !== "idle" ? r.status : r.agent ? r.status : null;
    const right = [];
    if (r.meta && !compact) right.push(div().flex_none().text_size(10.5).text_color(t.dim).child(r.meta));
    if (r.gone) {
      right.push(div().flex_none().text_size(10.5).text_color(t.dim).child("gone"));
      right.push(iconButton({ id: `rm-${i}`, icon: "x", size: 18, iconSize: S.iconXs, tip: "Remove bookmark", onClick: (_e, cx) => { this.command(`remove:${i}`); cx.notify(); } }));
    } else if (st) right.push(normStatus(st) === "blocked" && !compact ? needsYou() : statusMark(st));
    let el = treeRow({
      id: `bm-${i}-${b.kind}-${b.id}`, depth: 0, cursor: cur, lead: r.lead, label, dim: r.gone, labelColor: r.gone ? t.dim : t.foreground,
      after: [
        r.context && !compact ? div().min_w(0).flex_shrink(100).truncate().text_size(11).text_color(t.dim).child(r.context) : null,
        r.machine && !compact ? div().flex_none().text_size(10.5).text_color(t.dim).child(r.machine) : null,
      ],
      right,
      onRight: (_e, cx) => { this.cursor = i; this.menu(i); cx.notify(); },
    }).when(Boolean(r.gone), (e) => e.opacity(0.7));
    el = el
      .on_mouse_down("left", () => { this.pressed = i; this.over = i; })
      .on_mouse_move((_e, cx) => {
        if (this.pressed == null) return;
        const src = this.list()[this.pressed];
        const over = src && src.kind === b.kind ? i : null;
        if (this.over !== over) { this.over = over; cx.notify(); }
      })
      .on_mouse_up("left", (_e, cx) => {
        const from = this.pressed, over = this.over;
        this.pressed = null; this.over = null;
        if (from != null && from !== i && over === i) this.drop(from, i);
        else if (from === i) { this.cursor = i; this.kbd = false; if (!r.gone) r.go?.(); }
        cx.notify();
      });
    if (this.pressed === i && this.over != null && this.over !== i) el = el.opacity(0.5);
    if (this.pressed != null && this.over === i && this.pressed !== i) {
      const below = this.pressed < i;
      el = el.child(div().absolute().left(0).right(0).h(2).bg(t.accent).when(below, (l) => l.bottom(0)).when(!below, (l) => l.top(0)));
    }
    return el;
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-bookmarks", this.handle, () => { this.kbd = true; if (this.cursor < 0) this.cursor = this.order()[0] ?? -1; });
    const list = this.list();
    const ctx = this.ctx();
    const rows = [];
    this.rowIndex = new Map();
    for (const [kind, title] of KINDS) {
      const mine = list.map((b, i) => [b, i]).filter(([b]) => b.kind === kind);
      if (!mine.length) continue;
      const open = !this.folded.has(kind);
      rows.push(sectionHeader({ id: `sec-${kind}`, title: title.toUpperCase(), count: mine.length, open,
        onToggle: (_e, cx) => { open ? this.folded.add(kind) : this.folded.delete(kind); save("folded", [...this.folded]); cx.notify(); } }));
      if (open) for (const [b, i] of mine) { this.rowIndex.set(i, rows.length); rows.push(this.row(b, i, ctx, t)); }
    }
    const chord = bindingFor("ob-tabs.bookmark");
    const body = list.length
      ? div().relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().px(4).pb(12).overflow_y_scroll().track_scroll(this.scroll)
          .on_mouse_up("left", (_e, cx) => { if (this.pressed != null) { this.pressed = null; this.over = null; cx.notify(); } })
          .children(rows))
        .child(Scrollbar.vertical("list").absolute().inset_0())
      : emptyState({ icon: "bookmark", title: "No bookmarks yet",
        body: `Right-click a session and choose Bookmark${chord ? `, or press ${chordLabel(chord)}` : ""}. Bookmarked spaces, tabs, sessions and runs stay one click away.`,
        action: { id: "bm-add-tab", label: "Bookmark this tab", onClick: (_e, cx) => { this.add("tab"); cx.notify(); } } });
    const cur = current();
    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom ?? 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => {
        if (e.key === "down") this.step(1);
        else if (e.key === "up") this.step(-1);
        else if (e.key === "enter") { const b = this.list()[this.cursor]; if (b) this.open(b); }
        else if (e.key === "delete" || e.key === "backspace") { if (this.list()[this.cursor]) this.command(`remove:${this.cursor}`); }
        else if (e.key === "escape") { this.kbd = false; }
        else return;
        cx.stop_propagation(); cx.notify();
      })
      .child(h_flex().id("toolbar").h(S.toolbar).flex_none().px(S.pad).gap(2).items_center().justify_center()
        .child(iconButton({ id: "tb-add", icon: "bookmark-plus", tip: "Bookmark what you're looking at",
          onClick: () => openMenu([
            { label: "This tab", icon: "tab", command: "ob-bookmarks.add:tab", disabled: !cur.tab, kbd: chord ?? undefined },
            { label: "This space", icon: "folder", command: "ob-bookmarks.add:space", disabled: !cur.space },
            { label: "This session", icon: "terminal", command: "ob-bookmarks.add:session", disabled: !cur.terminal },
          ], { width: 230, title: "Bookmark" }) }))
        .child(iconButton({ id: "tb-fold", icon: this.folded.size ? "expand-all" : "collapse-all", tip: this.folded.size ? "Expand all" : "Collapse all", disabled: !list.length,
          onClick: (_e, cx) => { if (this.folded.size) this.folded.clear(); else KINDS.forEach(([k]) => this.folded.add(k)); save("folded", [...this.folded]); cx.notify(); } })))
      .child(body);
  }
}
