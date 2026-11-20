// ob-status: the status bar of the obsidian layout (26 px, chrome, top hairline).
// Right-aligned agent attention overview, scanner error alert, and zoom indicator.
//
// Clicks: the agent overview opens Agents; zoom resets zoom.
// Commands (ob-status.<cmd>): refresh, copy-cwd, agents, zoom-reset

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { agents, panes, spaces, terminals, run, nextCommand, settings, notify, shared } from "herdr";
import {
  S, tc, icon, statusMark, normStatus, current, place, copyText,
  mainAgents, placedTerminals, machineOf, machineLabel, ago, feed,
  terminalsByAddress, agentAttention, attentionCounts, getDismissed,
  normHidden, isMachineHidden, isSpaceHidden, isTabHidden, getHidden,
} from "./kit.js";

const ORDER = ["blocked", "working", "done", "idle"];
const LABEL = {
  blocked: (n) => `${n} ${n === 1 ? "needs you" : "need you"}`,
  working: (n) => `${n} working`,
  done: (n) => `${n} done`,
  idle: (n) => `${n} idle`,
};

export default class Status extends View {
  init(_p, cx) {
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-status: ${c} failed: ${e?.message ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
  }

  cwd() {
    const c = current();
    return c.cwd || (c.space ? place(c.space, panes()) : "");
  }

  command(c, cx) {
    if (c === "refresh") return; // the loop re-renders
    if (c === "copy-cwd") this.copyCwd(cx);
    else if (c === "agents") run("ob-tabs.open:ob-agents");
    else if (c === "zoom-reset") run("app.zoom_reset");
  }

  copyCwd(cx) {
    const path = this.cwd();
    if (!path) return;
    copyText(cx, path);
    notify({ title: "Copied path", body: path, level: "info", timeout: 1500 });
  }

  render(_cx) {
    const t = tc();
    const zoom = settings().zoom ?? 1;
    const zoomPct = Math.round(zoom * 100);

    // Filter counted agents using the same visible-agent rule as ob-agents so counts match 1:1.
    const ps = panes();
    const tmap = terminalsByAddress(terminals());
    const dis = getDismissed();
    const h = normHidden(shared("ob.hidden") ?? getHidden());
    const spList = spaces();
    const spMap = new Map(spList.map((s) => [s.id, s]));
    const tbMap = new Map(spList.flatMap((s) => (s.tabs ?? []).map((tb) => [tb.id, { tab: tb, space: s }])));
    const visibleStatuses = mainAgents(agents(), placedTerminals(ps))
      .map((a) => ({ a, att: agentAttention(a, tmap, dis) }))
      .filter(({ a, att }) => {
        if (normStatus(att) === "blocked") return true;
        const tabId = a.tab ?? ps.find((p) => p.pane === a.pane || (p.terminal && p.terminal === a.address))?.tab;
        const match = tabId ? tbMap.get(tabId) : null;
        const sp = match?.space ?? (a.space ? spMap.get(a.space) : null);
        const tb = match?.tab;
        const m = sp ? sp.machine : (a.machine ?? machineOf(a.address));
        if (isMachineHidden(h, m)) return false;
        if (isSpaceHidden(h, sp)) return false;
        if (isTabHidden(h, tb, sp)) return false;
        return true;
      })
      .map(({ att }) => att);
    const counts = attentionCounts(visibleStatuses);

    const present = ORDER.filter((s) => counts[s] > 0);
    const agentsEl = present.length > 0
      ? h_flex().id("agents").h(20).px(6).gap(12).items_center().rounded(S.radius).cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .tooltip("Open Agents")
        .on_click(() => run("ob-tabs.open:ob-agents"))
        .children(present.map((s) => h_flex().gap(5).items_center()
          .when(s === "blocked", (e) => e.text_color(t.blocked).font_medium())
          .when(s === "working", (e) => e.text_color(t.foreground))
          .child(statusMark(s, 10))
          .child(LABEL[s](counts[s]))))
      : div().id("agents-empty").text_color(t.dim).cursor_pointer()
        .on_click(() => run("ob-tabs.open:ob-agents"))
        .child("0 active");

    const f = feed();
    const bad = Object.entries(f?.machines ?? {}).filter(([, m]) => m && !m.ok);
    const why = [
      ...(f?.scriptError ? [f.scriptError] : []),
      ...bad.map(([k, m]) => `${machineLabel(k === "local" ? null : k)}: ${m.error ?? "scan failed"}${m.stale && m.at ? ` (showing data from ${ago(m.at)} ago)` : ""}`),
    ];

    const items = [agentsEl];
    if (why.length > 0) {
      items.push(h_flex().id("feed-alert").flex_none().tooltip(why.join("\n")).child(icon("alert", S.iconXs, t.blocked)));
    }
    if (zoomPct !== 100) {
      items.push(h_flex().id("zoom").px(4).h(20).items_center().rounded(S.radius).cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip("Zoom: click to reset to 100%")
        .on_click(() => run("app.zoom_reset")).child(`${zoomPct}%`));
    }

    return h_flex().id("root").size_full().min_w(0).overflow_hidden().px(12).gap(14).items_center().justify_end().bg(t.chrome)
      .border_t(1).border_color(t.border).text_size(S.textXs).text_color(t.muted).whitespace_nowrap()
      .children(items);
  }
}
