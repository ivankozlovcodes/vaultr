// ob-recent: a timeline of where you were and what your agents did. Visits come from the router's
// shared "ob.history" (ob-tabs); while no router writes it, this view records focus changes itself.
// Agent events are tracked here: working -> idle/done = "finished", -> blocked = "needs you".
// Grouped Today / Yesterday / Earlier; click goes there.
//
// Commands (herdr-app do ob-recent.<cmd>): focus, open:<index>, clear, next, prev.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { spaces, panes, agents, focused, run, theme, shared, props, nextCommand, settings } from "herdr";
import {
  S, alpha, icon, programIcon, iconButton, sectionHeader, emptyState, statusMark, takeFocus, tabLabel, paneName,
  machineOf, ago,
} from "./kit.js";

const MAX = 200;
function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } }
function splitCmd(c) { const s = String(c ?? ""); const i = s.indexOf(":"); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; }
const dayStart = (ms) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
const clock = (ms) => { const d = new Date(ms); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

export default class Recent extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.events = load("events", []).filter((e) => e && e.at);
    this.clearedAt = load("clearedAt", 0);
    this.prev = null; // address -> status, seeded on the first render (no events for what was already so)
    this.lastPane = undefined;
    this.cursor = -1;
    this.kbd = false;
    this.items = [];
    cx.timer.every(30000, (cx) => cx.notify()); // "3m" labels
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c); } catch (e) { console.log(`ob-recent: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  command(c) {
    const [verb, arg] = splitCmd(c);
    switch (verb) {
      case "focus": this.handle.focus(); this.kbd = true; if (this.cursor < 0 && this.items.length) this.cursor = 0; break;
      case "open": { const i = arg === "" ? this.cursor : Number(arg); if (this.items[i]) this.open(this.items[i]); break; }
      case "clear": this.events = []; this.clearedAt = Date.now(); save("events", []); save("clearedAt", this.clearedAt); this.cursor = -1; break;
      case "next": this.step(1); break;
      case "prev": this.step(-1); break;
      default: console.log(`ob-recent: unknown command ${c}`);
    }
  }
  step(d) {
    if (!this.items.length) return;
    this.cursor = this.cursor < 0 ? 0 : Math.max(0, Math.min(this.items.length - 1, this.cursor + d));
    this.kbd = true;
    const ri = this.rowIndex?.get(this.cursor);
    if (ri != null) this.scroll.scroll_to_item(ri);
  }
  push(ev) {
    this.events.push(ev);
    if (this.events.length > MAX) this.events = this.events.slice(-MAX);
    save("events", this.events);
  }

  // Agent transitions since the last render.
  track(list, now) {
    const cur = new Map(list.map((a) => [a.address, a]));
    if (!this.prev) { this.prev = new Map(list.map((a) => [a.address, a.status])); return; }
    for (const [addr, a] of cur) {
      const was = this.prev.get(addr);
      if (was === a.status) continue;
      const label = `${a.space_name || ""}${a.space_name ? " · " : ""}${a.tab_name && !/^\d+$/.test(a.tab_name) ? a.tab_name : a.program?.name ?? addr}`;
      if (a.status === "blocked" && was !== "blocked") this.push({ kind: "agent", address: addr, status: "blocked", label, at: now });
      else if (was === "working" && (a.status === "idle" || a.status === "done")) this.push({ kind: "agent", address: addr, status: "done", label, at: now });
    }
    this.prev = new Map(list.map((a) => [a.address, a.status]));
  }

  // Visits: the router's history when there is one, else what this view saw.
  visits(now) {
    const h = shared("ob.history");
    if (Array.isArray(h?.entries)) return h.entries.filter((e) => e && e.at).map((e) => ({ kind: "visit", space: e.space, tab: e.tab, pane: e.pane, terminal: e.terminal, at: e.at }));
    const f = focused();
    const pane = f?.pane ?? null;
    if (pane !== this.lastPane) {
      const first = this.lastPane === undefined;
      this.lastPane = pane;
      if (!first && pane && f?.tab) {
        const last = [...this.events].reverse().find((e) => e.kind === "visit");
        if (last?.pane !== pane) this.push({ kind: "visit", space: f.space, tab: f.tab, pane, terminal: f.terminal ?? null, at: now, label: this.visitLabel({ space: f.space, tab: f.tab, pane })?.text });
      }
    }
    return this.events.filter((e) => e.kind === "visit");
  }

  visitLabel(v, sp = spaces(), ps = panes()) {
    const s = sp.find((x) => x.id === v.space);
    const tab = s?.tabs?.find((x) => x.id === v.tab);
    if (!tab) return null;
    const p = ps.find((x) => x.pane === v.pane);
    const mine = ps.filter((x) => x.tab === tab.id);
    const tl = tabLabel(tab, ps);
    const text = p && mine.length > 1 ? `${tl} · ${paneName(p)}` : tl;
    return { text, space: s, tab, pane: p, context: s.name };
  }

  open(it) {
    if (it.kind === "visit") {
      const v = it.live;
      if (!v) return;
      run("space.select", { id: v.space.id });
      run("tab.select", { id: v.tab.id });
      if (v.pane) run("pane.focus", { pane: v.pane.pane });
    } else if (agents().some((a) => a.address === it.address)) run("pane.focus", { terminal: it.address });
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-recent", this.handle, () => { this.kbd = true; if (this.cursor < 0 && this.items.length) this.cursor = 0; });
    const now = Date.now();
    const ag = agents();
    this.track(ag, now);
    const sp = spaces(), ps = panes();
    let items = [...this.visits(now), ...this.events.filter((e) => e.kind === "agent")].filter((e) => e.at > this.clearedAt);
    items.sort((a, b) => b.at - a.at);
    // Back-to-back visits of the same pane read as one.
    items = items.filter((e, i) => !(e.kind === "visit" && items[i - 1]?.kind === "visit" && items[i - 1].pane === e.pane && e.pane));
    items = items.slice(0, MAX).map((e) => (e.kind === "visit" ? { ...e, live: this.visitLabel(e, sp, ps) } : e));
    this.items = items;
    if (this.cursor >= items.length) this.cursor = items.length - 1;

    const today = dayStart(now), yesterday = today - 86400000;
    const sections = [["Today", (x) => x >= today], ["Yesterday", (x) => x >= yesterday && x < today], ["Earlier", (x) => x < yesterday]];
    const rows = [];
    this.rowIndex = new Map();
    const compact = this.w < 220;
    for (const [title, test] of sections) {
      const mine = items.map((e, i) => [e, i]).filter(([e]) => test(e.at));
      if (!mine.length) continue;
      rows.push(sectionHeader({ id: `sec-${title}`, title: title.toUpperCase(), count: mine.length }));
      for (const [e, i] of mine) {
        this.rowIndex.set(i, rows.length);
        rows.push(this.row(e, i, t, now, compact, title !== "Today"));
      }
    }
    const body = items.length
      ? div().relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().px(4).pb(10).overflow_y_scroll().track_scroll(this.scroll).children(rows))
        .child(Scrollbar.vertical("list").absolute().inset_0())
      : emptyState({ icon: "history", title: "Nothing yet", body: "Tabs and sessions you visit, and agents that finish or need you, show up here." });
    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom ?? 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => {
        if (e.key === "down") this.step(1);
        else if (e.key === "up") this.step(-1);
        else if (e.key === "enter") { if (this.items[this.cursor]) this.open(this.items[this.cursor]); }
        else if (e.key === "escape") this.kbd = false;
        else return;
        cx.stop_propagation(); cx.notify();
      })
      .child(h_flex().h(28).flex_none().pl(S.pad + 4).pr(S.pad).items_center().text_size(S.textXs).text_color(t.dim)
        .child(div().flex_1().min_w(0).truncate().child(items.length ? `${items.length} event${items.length === 1 ? "" : "s"}` : ""))
        .child(iconButton({ id: "tb-clear", icon: "trash", size: 22, iconSize: S.iconSm, tip: "Clear the timeline", disabled: !items.length, onClick: (_e, cx) => { this.command("clear"); cx.notify(); } })))
      .child(body);
  }

  row(e, i, t, now, compact, showClock) {
    const cur = this.kbd && this.cursor === i;
    const when = showClock ? clock(e.at) : ago(e.at, now);
    let lead, label, labelColor = t.foreground, after = null, mark = null, gone = false;
    if (e.kind === "visit") {
      const v = e.live;
      gone = !v;
      lead = v?.pane ? programIcon(v.pane.program, S.iconSm, t.muted) : icon("tab", S.iconSm, t.dim);
      label = v?.text ?? e.label ?? "Closed tab";
      labelColor = gone ? t.dim : t.foreground;
      if (v && !compact) after = `${v.context}${v.space.machine ? ` · ${v.space.machine}` : ""}`;
      const st = v?.pane?.status;
      if (st && st !== "idle") mark = statusMark(st);
    } else {
      lead = statusMark(e.status === "blocked" ? "blocked" : "done");
      label = `${e.label} ${e.status === "blocked" ? "needs you" : "finished"}`;
      labelColor = e.status === "blocked" ? t.foreground : t.muted;
      const m = machineOf(e.address);
      if (m && !compact) after = m;
      gone = !agents().some((a) => a.address === e.address);
    }
    return h_flex().id(`ev-${i}-${e.at}`).relative().h(S.row).flex_none().pl(S.pad).pr(6).gap(7).items_center().rounded(S.radius)
      .cursor_pointer().when(gone, (x) => x.opacity(0.65))
      .when(cur, (x) => x.bg(t.hover).border_1().border_color(alpha(t.accent, 0.55)))
      .when(!cur, (x) => x.hover((s) => s.bg(t.hover)))
      .on_click((_ev, cx) => { this.cursor = i; this.kbd = false; this.open(e); cx.notify(); })
      .child(div().w(compact ? 30 : 36).flex_none().text_size(S.textXs).text_color(t.dim).child(when))
      .child(h_flex().size(S.iconSm).flex_none().items_center().justify_center().child(lead))
      .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).text_color(labelColor).child(label))
      .when(Boolean(after), (x) => x.child(div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(after)))
      .child(div().flex_1().min_w(4))
      .when(Boolean(mark), (x) => x.child(mark));
  }
}
