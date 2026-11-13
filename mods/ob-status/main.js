// ob-status: the status bar of the obsidian layout (26 px, chrome, top hairline). SPEC.md 8.A4.
// Right-aligned like Obsidian's, 11 px muted text, items 14 px apart; when the bar is narrow
// items drop from the left: key hint · machine · folder · branch · agents by status · zoom.
// The sub-agent count is the next block's (ob-feed).
//
// Clicks: folder copies it; an agent count opens Agents; zoom resets the zoom.
// Commands (ob-status.<cmd>): refresh, copy-cwd, agents, zoom-reset

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { agents, machines, panes, run, nextCommand, settings, notify } from "herdr";
import { S, tc, icon, statusMark, current, machineLabel, tilde, chordLabel, bindingFor, place, copyText } from "./kit.js";

const ORDER = ["blocked", "done", "working", "idle"];
const WORD = { blocked: "need you", done: "finished", working: "working", idle: "idle" };
// Rough width of 11 px UI text (design px).
const textW = (s) => Math.ceil(String(s ?? "").length * 6.1);
// "~" for home folders: this computer's exactly, another machine's by the usual /home/<user> (or /root).
const short = (path, machine) => (machine ? String(path).replace(/^(\/home\/[^/]+|\/root)(?=\/|$)/, "~") : tilde(path));

export default class Status extends View {
  init(_p, cx) {
    this.w = 0;
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

  render() {
    const t = tc();
    const c = current();
    const list = agents();
    const zoom = settings().zoom || 1;
    const counts = Object.fromEntries(ORDER.map((s) => [s, list.filter((a) => a.status === s).length]));
    const m = c.machine ?? null;
    const mstate = m ? machines().find((x) => x.name === m)?.layout : "ready";
    const branch = c.pane?.branch ?? c.space?.branch ?? null;
    const cwd = this.cwd();
    const switchKey = bindingFor("mod.open:ob-switcher");
    const paletteKey = bindingFor("app.palette");
    const hint = [switchKey && `${chordLabel(switchKey)} switch`, paletteKey && `${chordLabel(paletteKey)} commands`].filter(Boolean).join("  ·  ");

    // Items right to left, each with its width; keep what fits.
    const items = [];
    const zoomPct = Math.round(zoom * 100);
    if (zoomPct !== 100) items.push([textW(`${zoomPct}%`) + 4, h_flex().id("zoom").px(4).h(20).items_center().rounded(S.radius).cursor_pointer()
      .hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip("Zoom: click to reset to 100%")
      .on_click(() => run("app.zoom_reset")).child(`${zoomPct}%`)]);
    const present = ORDER.filter((s) => counts[s] > 0);
    if (present.length) {
      const el = h_flex().id("agents").h(20).px(4).gap(10).items_center().rounded(S.radius).cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .tooltip(present.map((s) => `${counts[s]} ${WORD[s]}`).join(", ") + " · open Agents")
        .on_click(() => run("ob-tabs.open:ob-agents"))
        .children(present.map((s) => h_flex().gap(4).items_center().when(s === "blocked", (e) => e.text_color(t.blocked))
          .child(statusMark(s, 10)).child(String(counts[s]))));
      items.push([present.reduce((n, s) => n + 14 + textW(counts[s]) + 10, 8), el]);
    }
    if (branch) items.push([Math.min(180, textW(branch)) + 18, h_flex().gap(5).items_center().max_w(180).tooltip(`Branch ${branch}`)
      .child(icon("git-branch", S.iconXs)).child(div().min_w(0).truncate().child(branch))]);
    if (cwd) items.push([Math.min(260, textW(short(cwd, m))) + 8, h_flex().id("cwd").h(20).px(4).max_w(260).items_center().rounded(S.radius).cursor_pointer()
      .hover((s) => s.bg(t.hover).text_color(t.foreground)).tooltip(`${cwd} · click to copy`)
      .on_click((_e, cx) => this.copyCwd(cx)).child(div().min_w(0).truncate().child(short(cwd, m)))]);
    items.push([textW(machineLabel(m)) + 18 + (mstate !== "ready" ? 12 : 0), h_flex().gap(5).items_center()
      .tooltip(m ? `On ${m}${mstate === "unavailable" ? " (unavailable)" : mstate === "loading" ? " (connecting)" : ""}` : "On this computer")
      .child(icon(m ? "server" : "monitor", S.iconXs))
      .child(machineLabel(m))
      .when(mstate === "unavailable", (e) => e.child(div().size(6).rounded_full().bg(t.blocked)))
      .when(mstate === "loading", (e) => e.child(statusMark("working", 10)))]);
    if (hint) items.push([textW(hint), div().text_color(t.dim).child(hint)]);

    const avail = (this.w || 2000) - 24;
    const keep = [];
    let used = 0;
    for (const [wd, el] of items) {
      if (keep.length && used + wd + 14 > avail) break;
      keep.push(el);
      used += wd + 14;
    }
    return h_flex().id("root").size_full().min_w(0).overflow_hidden().px(12).gap(14).items_center().justify_end().bg(t.chrome)
      .border_t(1).border_color(t.border).text_size(S.textXs).text_color(t.muted).whitespace_nowrap()
      .on_size_change((s, cx) => { const w0 = s.width / (settings().zoom || 1); if (Math.abs(w0 - this.w) > 1) { this.w = w0; cx.notify(); } })
      .children(keep.reverse());
  }
}
