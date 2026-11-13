// ob-agents: every agent, by priority (Needs you / Done / Working / Idle) or grouped by space, pinned
// ones on top. A fork of the shipped `agents` list in the kit look: durations since the last change,
// sub-agents under their parent (hc child terminals, pi runs and Claude agents from the shared feed),
// machine tag for remote agents, Needs-you pill when there is room. setAgentOrder follows this list.
//
// Commands (herdr-app do ob-agents.<cmd>): focus, sort:<priority|grouped>, next, prev, open,
// menu[:<address>], pin[:<address>], bookmark[:<address>], fold:<address|groupId>.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import {
  agents, terminals, panes, spaces, focused, run, theme, props, nextCommand, settings, setAgentOrder,
} from "herdr";
import {
  S, icon, programIcon, iconButton, badge, treeRow, sectionHeader, emptyState, openMenu, statusMark,
  needsYou, normStatus, takeFocus, openView, machineOf, isBookmarked, toggleBookmark,
} from "./kit.js";
import { subItems, counts } from "./sub.js";

const RANK = { blocked: 4, done: 3, working: 2, idle: 1 };
const SECTION = { 4: "Needs you", 3: "Done", 2: "Working", 1: "Idle" };
const SECTION_STATUS = { 4: "blocked", 3: "done", 2: "working", 1: null };
const SORTS = [["priority", "Priority", "clock"], ["grouped", "Grouped by space", "layers"]];
const clean = (s) => (s ?? "").replace(/^[^\p{L}\p{N}]+/u, "").trim();
function load(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } }
function splitCmd(c) { const s = String(c ?? ""); const i = s.indexOf(":"); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; }
// A sub-agent's word: error counts as blocked; it is never "done" (its parent's done is the news).
const kidStatus = (s) => (s === "error" ? "blocked" : s === "done" ? "idle" : s);
const kidRank = (s) => ({ blocked: 4, failed: 4, working: 2 })[normStatus(s)] ?? 0;

function duration(ms) {
  const m = Math.floor(ms / 60000);
  if (m < 1) return "<1m";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}
// Per tab: the first agent pane, else the first focused terminal, else the first terminal.
function leadPanes(all) {
  const leads = new Map();
  for (const p of all) {
    if (!p.terminal) continue;
    const cur = leads.get(p.tab);
    if (!cur || (!cur.program?.agent && (p.program?.agent || (!cur.focused && p.focused)))) leads.set(p.tab, p);
  }
  return leads;
}
// A tab's name, or the agent's live title when the tab is unnamed and the title says something.
function title(tab, l) {
  const prog = l?.program?.name;
  const live = clean(l?.title);
  const path = /^[~/]|^[A-Za-z]:\\/.test((l?.title ?? "").replace(/^[^\p{L}\p{N}~/]+/u, ""));
  const telling = live && live !== prog && !path && !live.includes("@") && live.toLowerCase() !== l?.program?.key;
  return (tab.name === prog || !tab.named) && telling ? live : tab.name;
}

export default class Agents extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.changed = load("changed", {});
    this.folded = new Set(load("folded", []));
    this.sort = SORTS.some(([id]) => id === load("sort", "priority")) ? load("sort", "priority") : "priority";
    this.cursor = null; // an agent address
    this.kbd = false;
    this.hovered = null;
    this.order = [];
    cx.timer.every(30000, (cx) => cx.notify()); // durations
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c); } catch (e) { console.log(`ob-agents: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  command(c) {
    const [verb, arg] = splitCmd(c);
    const addr = arg || this.cursor;
    switch (verb) {
      case "focus": this.handle.focus(); this.kbd = true; if (!this.cursor) this.cursor = this.order[0] ?? null; break;
      case "sort": if (SORTS.some(([id]) => id === arg)) { this.sort = arg; save("sort", arg); } break;
      case "next": this.step(1); break;
      case "prev": this.step(-1); break;
      case "open": this.openAgent(addr); break;
      case "menu": if (addr) this.menu(addr); break;
      case "pin": { const a = agents().find((x) => x.address === addr); if (a) run("terminal.pin", { terminal: a.address, pinned: !a.pinned }); break; }
      case "fold": if (arg) this.toggleFold(arg); break;
      case "bookmark": {
        const a = agents().find((x) => x.address === addr);
        if (a) toggleBookmark({ kind: "terminal", id: a.address, label: `${a.space_name ?? ""} · ${a.program?.name ?? a.address}`, machine: machineOf(a.address) });
        break;
      }
      default: console.log(`ob-agents: unknown command ${c}`);
    }
  }
  toggleFold(id) { this.folded.has(id) ? this.folded.delete(id) : this.folded.add(id); save("folded", [...this.folded]); }
  step(d) {
    if (!this.order.length) return;
    const i = this.order.indexOf(this.cursor);
    this.cursor = this.order[i < 0 ? (d > 0 ? 0 : this.order.length - 1) : Math.max(0, Math.min(this.order.length - 1, i + d))];
    this.kbd = true;
    const ri = this.rowIndex?.get(this.cursor);
    if (ri != null) this.scroll.scroll_to_item(ri);
  }
  openAgent(addr) {
    const a = agents().find((x) => x.address === addr);
    if (a) run("pane.focus", { pane: a.pane });
  }

  // Each agent's last state and when it changed (done and idle count as one).
  track(list, now) {
    let dirty = false;
    for (const a of list) {
      const s = a.status === "done" ? "idle" : a.status;
      if (this.changed[a.address]?.s === s) continue;
      this.changed[a.address] = { s, at: now };
      dirty = true;
    }
    if (!dirty) return;
    const listed = new Set(list.map((a) => a.address));
    for (const [k, c] of Object.entries(this.changed)) if (!listed.has(k) && now - c.at > 30 * 86400000) delete this.changed[k];
    save("changed", this.changed);
  }

  // Live hc children of an address, depth first, plus pi runs and Claude agents: [{ it, depth }].
  kids(all, addr, depth = 1, seen = new Set()) {
    if (seen.has(addr)) return [];
    seen.add(addr);
    const out = [];
    for (const it of subItems(addr, all)) {
      // Finished feed entries stay in Subagents; here only what is still going, plus hc children.
      if (it.kind !== "child" && !it.live) continue;
      out.push({ it, depth });
      if (it.kind === "child") out.push(...this.kids(all, it.id, depth + 1, seen));
    }
    return out;
  }

  menu(addr) {
    const a = agents().find((x) => x.address === addr);
    if (!a) return;
    const bm = isBookmarked("terminal", addr);
    openMenu([
      { label: "Focus", icon: "locate", command: "pane.focus", args: { pane: a.pane } },
      { label: a.pinned ? "Unpin" : "Pin to the top", icon: a.pinned ? "pin-off" : "pin", command: "terminal.pin", args: { terminal: addr, pinned: !a.pinned } },
      { label: "Peek", icon: "eye", command: "terminal.peek", args: { terminal: addr } },
      { separator: true },
      { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${addr}` },
      { label: "Show subagents", icon: "subagents", command: `ob-tabs.open:ob-subagents@term:${addr}` },
      { label: "Reveal in Sessions", icon: "sessions", command: "ob-tabs.open:ob-sessions@reveal", disabled: !a.focused },
      { label: bm ? "Remove bookmark" : "Bookmark session", icon: bm ? "bookmark" : "bookmark-plus", command: `ob-agents.bookmark:${addr}` },
      { label: "Copy address", icon: "copy", copy: addr },
    ].filter((x) => !(x.disabled && x.label === "Reveal in Sessions")), { width: 230, title: a.space_name || a.address });
  }

  status(t, st, compact, full = true) {
    const k = normStatus(st);
    if (k === "blocked" && full && !compact && this.w >= 220) return needsYou();
    return statusMark(st);
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-agents", this.handle, () => { this.kbd = true; if (!this.cursor) this.cursor = this.order[0] ?? null; });
    const now = Date.now();
    const compact = this.w < 220;
    const byPriority = this.sort === "priority";
    const all = terminals();
    let list = agents();
    this.track(list, now);
    const listed = new Map(list.map((a) => [a.address, a.status]));
    // A kept sub-agent (one with a pane) also is in agents(): under its parent it gets no row of its own unless pinned.
    const kidsOf = new Map(list.map((a) => [a.address, this.kids(all, a.address)]));
    const nested = new Set([...kidsOf.values()].flatMap((ks) => ks.filter((k) => k.it.kind === "child").map((k) => k.it.id)));
    list = list.filter((a) => a.pinned || !nested.has(a.address));
    const kidState = (k) => (k.it.kind === "child" ? kidStatus(listed.get(k.it.id) ?? k.it.status) : k.it.status);
    const urgency = new Map(list.map((a) => [a.address, Math.max(RANK[a.status] ?? 0, ...(kidsOf.get(a.address) ?? []).map((k) => kidRank(kidState(k))))]));
    const since = (a) => this.changed[a.address]?.at ?? 0;
    if (byPriority) list = [...list].sort((x, y) => urgency.get(y.address) - urgency.get(x.address) || since(y) - since(x) || y.seq - x.seq);
    const pinned = list.filter((a) => a.pinned);
    const rest = list.filter((a) => !a.pinned);
    list = [...pinned, ...rest];
    setAgentOrder(list.map((a) => a.address));

    // Labels: "space · detail", where detail is a named tab or the agent's own title.
    const ps = panes();
    const leads = leadPanes(ps);
    const tabs = new Map(spaces().flatMap((s) => s.tabs ?? []).map((tab) => [tab.id, tab]));
    const tabCounts = new Map();
    for (const a of list) tabCounts.set(a.tab, (tabCounts.get(a.tab) ?? 0) + 1);
    const label = (a) => {
      const tab = tabs.get(a.tab);
      const many = tabCounts.get(a.tab) > 1;
      return tab ? title(many ? { ...tab, named: false } : tab, many ? a : leads.get(a.tab)) : a.title || a.program?.name || "";
    };

    // Groups: pinned, then priority sections or spaces (neighbours in agents() share a space).
    const groups = pinned.length ? [{ id: "pinned", label: "Pinned", status: null, members: pinned }] : [];
    for (const a of rest) {
      const r = urgency.get(a.address) || RANK.idle;
      const id = byPriority ? `sec-${r}` : `sp-${a.space}`;
      if (groups.at(-1)?.id === id) groups.at(-1).members.push(a);
      else groups.push({ id, label: byPriority ? SECTION[r] : a.space_name || "Space", status: byPriority ? SECTION_STATUS[r] : null, members: [a] });
    }

    const rows = [];
    this.rowIndex = new Map();
    this.order = [];
    const f = focused();
    for (const g of groups) {
      const open = !this.folded.has(g.id);
      const top = g.members.reduce((m, a) => ((RANK[a.status] ?? 0) > (RANK[m] ?? 0) ? a.status : m), null);
      rows.push(sectionHeader({
        id: `grp-${g.id}`, title: g.label.toUpperCase(), count: g.members.length, open, color: g.status ? t[g.status] : undefined,
        onToggle: (_e, cx) => { this.toggleFold(g.id); cx.notify(); },
        right: !open && !byPriority && top && top !== "idle" ? [statusMark(top)] : [],
      }));
      if (!open) continue;
      for (const a of g.members) {
        const ks = kidsOf.get(a.address) ?? [];
        const foldOpen = !this.folded.has(a.address);
        const full = !byPriority || a.pinned || g.id === "pinned";
        const detail = label(a);
        const name = byPriority || a.pinned ? a.space_name || detail : /^\d+$/.test(detail) ? a.program?.name || detail : detail;
        const more = byPriority || a.pinned ? (/^\d+$/.test(detail) || detail === name ? null : detail) : null;
        const machine = machineOf(a.address);
        const when = since(a);
        const hov = this.hovered === a.address;
        const c = counts(ks.map((k) => ({ live: ["working", "blocked"].includes(normStatus(kidState(k))) })));
        const right = [];
        if (!foldOpen && ks.length) right.push(badge(compact ? String(c.live || c.total) : c.live ? `${c.live}/${c.total}` : String(c.total), c.live ? "working" : null));
        if (hov) right.push(iconButton({ id: `pin-${a.address}`, icon: a.pinned ? "pin-off" : "pin", size: 20, iconSize: S.iconXs, tip: a.pinned ? "Unpin" : "Pin to the top",
          onClick: (_e, cx) => { run("terminal.pin", { terminal: a.address, pinned: !a.pinned }); this.hovered = null; cx.notify(); } }));
        else if (when && !compact) right.push(div().flex_none().text_size(S.textXs).text_color(t.dim).child(duration(now - when)));
        right.push(this.status(t, a.status, compact, full || g.status !== "blocked"));
        this.rowIndex.set(a.address, rows.length);
        this.order.push(a.address);
        const idle = a.status === "idle" && !a.focused;
        rows.push(treeRow({
          id: `ag-${a.address}`, depth: 0, selected: a.focused || f?.agent === a.address, cursor: this.kbd && this.cursor === a.address,
          chevron: ks.length ? foldOpen : undefined, onToggle: (_e, cx) => { this.toggleFold(a.address); cx.notify(); },
          lead: programIcon(a.program, S.iconSm, t.muted), label: name, labelColor: idle ? t.muted : t.foreground,
          after: [
            more && this.w >= 200 ? div().min_w(0).flex_shrink(100).truncate().text_color(t.dim).child(`· ${more}`) : null,
            machine && !compact ? div().flex_none().text_size(10.5).text_color(t.dim).child(machine) : null,
            a.pinned ? icon("pin", 11, t.dim) : null,
          ],
          right,
          onClick: (_e, cx) => { this.cursor = a.address; this.kbd = false; run("pane.focus", { pane: a.pane }); cx.notify(); },
          onRight: (_e, cx) => { this.cursor = a.address; this.menu(a.address); cx.notify(); },
        }).on_hover((on, cx) => { const v = on ? a.address : this.hovered === a.address ? null : this.hovered; if (v !== this.hovered) { this.hovered = v; cx.notify(); } }));
        if (!foldOpen) continue;
        for (const k of ks) rows.push(this.kidRow(k, kidState(k), listed, t, now, compact));
      }
    }

    const body = !agents().length
      ? emptyState({ icon: "bot", title: "No agents yet", body: "Agents show up here when they report their status. Older versions and agents inside tmux may not." })
      : div().relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().px(4).pb(10).overflow_y_scroll().track_scroll(this.scroll).children(rows))
        .child(Scrollbar.vertical("list").absolute().inset_0());
    const sortInfo = SORTS.find(([id]) => id === this.sort) ?? SORTS[0];
    const live = agents();
    const n = (s) => live.filter((a) => a.status === s).length;
    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom ?? 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => {
        if (e.key === "down") this.step(1);
        else if (e.key === "up") this.step(-1);
        else if (e.key === "enter") this.openAgent(this.cursor);
        else if (e.key === "left" && this.cursor && !this.folded.has(this.cursor)) this.toggleFold(this.cursor);
        else if (e.key === "right" && this.cursor && this.folded.has(this.cursor)) this.toggleFold(this.cursor);
        else if (e.key === "escape") { this.kbd = false; const p = focused()?.pane; if (p) run("pane.focus", { pane: p }); }
        else return;
        cx.stop_propagation(); cx.notify();
      })
      .child(h_flex().h(28).flex_none().pl(S.pad + 4).pr(S.pad).gap(10).items_center().text_size(S.textXs).text_color(t.dim)
        .child(h_flex().flex_1().min_w(0).gap(10).items_center().overflow_hidden()
          .when(n("blocked") > 0, (e) => e.child(h_flex().flex_none().gap(4).items_center().text_color(t.blocked).child(statusMark("blocked", 10)).child(String(n("blocked")))))
          .when(n("working") > 0, (e) => e.child(h_flex().flex_none().gap(4).items_center().child(statusMark("working", 10)).child(String(n("working")))))
          .when(n("done") > 0, (e) => e.child(h_flex().flex_none().gap(4).items_center().child(statusMark("done", 10)).child(String(n("done")))))
          .when(n("idle") > 0, (e) => e.child(h_flex().flex_none().gap(4).items_center().child(statusMark("idle", 10)).child(String(n("idle"))))))
        .child(iconButton({ id: "tb-sort", icon: "sort", size: 22, iconSize: S.iconSm, tip: `Sort agents: ${sortInfo[1]}`,
          onClick: () => openMenu(SORTS.map(([id, l, ic]) => ({ label: l, icon: ic, checked: id === this.sort, command: `ob-agents.sort:${id}` })), { width: 210, title: "Sort agents" }) })))
      .child(body);
  }

  kidRow(k, st, listed, t, now, compact) {
    const it = k.it;
    const lead = it.kind === "child" ? programIcon(it.item.program, S.iconXs, t.dim) : icon(it.kind === "run" ? "subagents" : "bot", S.iconXs, t.dim);
    const time = it.kind === "run" && it.live ? `${Math.max(1, Math.round((now - (it.item.startedAt ?? now)) / 60000))}m` : "";
    return treeRow({
      id: `sub-${it.key}`, depth: k.depth, height: S.rowSm, lead,
      label: h_flex().min_w(0).text_size(S.textSm).child(it.label), labelColor: t.muted,
      after: [it.detail && this.w >= 320 && it.kind !== "child" ? div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(it.detail) : null],
      right: [time && !compact ? div().flex_none().text_size(10.5).text_color(t.dim).child(time) : null, statusMark(st, S.iconXs)],
      onClick: (_e, cx) => {
        if (it.kind === "child") { if (listed.has(it.id)) run("pane.focus", { terminal: it.id }); else run("terminal.peek", { terminal: it.id }); }
        else openView("ob-subagents", `run:${it.id}`);
        cx.notify();
      },
      onRight: (_e, cx) => {
        if (it.kind === "child") openMenu([
          { label: "Peek", icon: "eye", command: "terminal.peek", args: { terminal: it.id } },
          { label: "Keep as a pane to the right", icon: "split-right", command: "terminal.keep", args: { terminal: it.id, place: "right" } },
          { label: "Copy address", icon: "copy", copy: it.id },
        ], { width: 240, title: it.label });
        else openMenu([
          { label: "Open in Subagents", icon: "subagents", command: `ob-tabs.open:ob-subagents@run:${it.id}` },
          { label: it.kind === "run" ? "Copy run id" : "Copy agent id", icon: "copy", copy: it.item.id },
        ], { width: 220, title: it.label });
        cx.notify();
      },
    });
  }
}
