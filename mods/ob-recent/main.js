// ob-recent: a timeline of where you were and what your agents did. Visits come from the router's
// shared "ob.history" (ob-tabs); while no router writes it, this view records focus changes itself.
// Agent events are tracked here for main agents only (terminal in a pane of a tab; kit/agents.js): working -> idle/done
// = "finished", -> blocked = "needs you". Background agents (hc --bg workers, sub-agents) make no entries.
// Grouped Today / Yesterday / Earlier; click goes there.
//
// Commands (herdr-app do ob-recent.<cmd>): focus, open:<index>, clear, next, prev.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { spaces, panes, agents, focused, run, theme, shared, props, nextCommand, settings, notify } from "herdr";
import {
  S, alpha, icon, programIcon, iconButton, sectionHeader, emptyState, statusMark, takeFocus, ago, mainAgents, placedTerminals,
} from "./kit.js";
import { agentChanges, newVisits, keepNewest } from "./events.js";
import { visitRecord, agentRecord, liveOf, rowText, clickPlan } from "./rows.js";

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
    this.histSeen = load("histSeen", null); // the newest ob.history entry already recorded here (null: none yet)
    this.prev = null; // address -> status for every agent, seeded on the first render (no events for what was already so)
    this.mainAddrs = new Set(); // the main agents of the last render
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
  // Adds entries (in order), keeping the newest MAX visits and the newest MAX agent events; one save per call.
  push(...evs) {
    if (!evs.length) return;
    this.events = keepNewest(this.events, evs, MAX);
    save("events", this.events);
  }

  // Agent transitions since the last render, for main agents only. Each entry keeps the names of its space, tab and agent.
  track(list, placed, now, sp) {
    const { changes, next } = agentChanges(this.prev, list, placed);
    this.prev = next;
    this.push(...changes.map(({ agent: a, status }) => agentRecord(a, sp, status, now)));
  }

  // Visits: the router's entries in shared "ob.history" (copied here once, with their names, the first time they are
  // seen), else the focus changes this view saw itself.
  visits(now, sp, ps) {
    const h = shared("ob.history");
    if (Array.isArray(h?.entries)) {
      const { take, histSeen } = newVisits(h.entries, this.histSeen, this.clearedAt);
      this.push(...take.map((e) => visitRecord(e, sp, ps)));
      if (histSeen !== this.histSeen) { this.histSeen = histSeen; save("histSeen", histSeen); }
    } else {
      const f = focused();
      const pane = f?.pane ?? null;
      if (pane !== this.lastPane) {
        const first = this.lastPane === undefined;
        this.lastPane = pane;
        if (!first && pane && f?.tab) {
          const last = [...this.events].reverse().find((e) => e.kind === "visit");
          if (last?.pane !== pane) this.push(visitRecord({ space: f.space, tab: f.tab, pane, terminal: f.terminal ?? null, at: now }, sp, ps));
        }
      }
    }
    return this.events.filter((e) => e.kind === "visit");
  }

  // A click: focus the tab (and the pane, or the agent's terminal). A tab that is gone gets a notice instead.
  open(it) {
    const plan = clickPlan(it, it.live);
    if (plan.notice) { notify({ title: "Tab closed", body: plan.notice, level: "info" }); return; }
    run("space.select", { id: plan.space });
    run("tab.select", { id: plan.tab });
    if (plan.pane) run("pane.focus", { pane: plan.pane });
    if (plan.terminal) run("pane.focus", { terminal: plan.terminal });
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-recent", this.handle, () => { this.kbd = true; if (this.cursor < 0 && this.items.length) this.cursor = 0; });
    const now = Date.now();
    const sp = spaces(), ps = panes();
    const ag = agents();
    const placed = placedTerminals(ps);
    this.track(ag, placed, now, sp);
    this.mainAddrs = new Set(mainAgents(ag, placed).map((a) => a.address));
    const world = { spaces: sp, panes: ps, agents: ag, mains: [...this.mainAddrs] };
    let items = [...this.visits(now, sp, ps), ...this.events.filter((e) => e.kind === "agent")].filter((e) => e.at > this.clearedAt);
    items.sort((a, b) => b.at - a.at);
    // Back-to-back visits of the same pane read as one.
    items = items.filter((e, i) => !(e.kind === "visit" && items[i - 1]?.kind === "visit" && items[i - 1].pane === e.pane && e.pane));
    items = items.slice(0, MAX).map((e) => ({ ...e, live: liveOf(e, world) }));
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
    const r = rowText(e, e.live);
    let lead, labelColor, mark = null;
    if (e.kind === "visit") {
      const program = e.live?.program;
      lead = program ? programIcon(program, S.iconSm, t.muted) : icon("tab", S.iconSm, t.dim);
      labelColor = r.closed ? t.dim : t.foreground;
      const st = e.live?.paneStatus;
      if (st && st !== "idle") mark = statusMark(st);
    } else {
      lead = statusMark(e.status === "blocked" ? "blocked" : "done");
      labelColor = e.status === "blocked" ? t.foreground : t.muted;
    }
    return h_flex().id(`ev-${i}-${e.at}`).relative().h(S.row).flex_none().pl(S.pad).pr(6).gap(7).items_center().rounded(S.radius)
      .cursor_pointer().when(r.closed, (x) => x.opacity(0.65))
      .when(cur, (x) => x.bg(t.hover).border_1().border_color(alpha(t.accent, 0.55)))
      .when(!cur, (x) => x.hover((s) => s.bg(t.hover)))
      .tooltip(r.path)
      .on_click((_ev, cx) => { this.cursor = i; this.kbd = false; this.open(e); cx.notify(); })
      .child(div().w(compact ? 30 : 36).flex_none().text_size(S.textXs).text_color(t.dim).child(when))
      .child(h_flex().size(S.iconSm).flex_none().items_center().justify_center().child(lead))
      .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).text_color(labelColor).child(r.main))
      .when(Boolean(r.sub) && !compact, (x) => x.child(div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(r.sub)))
      .child(div().flex_1().min_w(4))
      .child(div().min_w(0).flex_none().max_w(compact ? 96 : 180).truncate().text_size(S.textXs).text_color(r.closed ? t.dim : t.muted).child(r.trail))
      .when(Boolean(mark), (x) => x.child(mark));
  }
}
