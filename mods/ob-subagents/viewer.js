// The log / transcript viewer of ob-subagents: a window overlay (or a pane after "Pin as pane").
// props: { view: "log"|"transcript", machine, path, title, live, runKey, overlay? }
// log: `tail -n 400 <path>` on that machine, every 1.5 s while the run is live; follows the end
//      unless you scroll up (Follow button / viewer-follow:on brings it back).
// transcript: transcript.py parses the jsonl there (pi session, pi-subagents transcript, Claude Code)
//      into prompts, replies (markdown) and tool calls (click one to see its result); refreshed every
//      4 s while live.
// Commands (only viewers act on them): viewer-follow:<on|off>, viewer-pin, viewer-copy, viewer-close,
//      viewer-tool:<index> (expand/collapse a tool call), viewer-refresh.

import { div } from "gpui-kit";
import { v_flex, h_flex, TextView, v_virtual_list, VirtualListScrollHandle, ScrollHandle, Scrollbar } from "gpui-base";
import { props, exec, readTextFile, appHome, run, closeOverlay, settings } from "herdr";
import { S, tc, icon, iconButton, alpha, ago, machineLabel, tilde, base, feed, statusMark, stop } from "./kit.js";
import { MONO, splitCmd, copied } from "./obc.js";

const LOG_MS = 1500, TX_MS = 4000;

export class Viewer {
  init(cx) {
    this.p = props() ?? {};
    this.lines = [];
    this.entries = [];
    this.meta = null;
    this.err = null;
    this.loading = true;
    this.at = 0;
    this.follow = true;
    this.open = new Set();
    this.busy = false;
    this.gen = 0;
    this.vscroll = VirtualListScrollHandle.new();
    this.scroll = ScrollHandle.new();
    this.w = 0;
    cx.spawn(async (cx) => {
      if (this.p.view === "transcript") {
        try { this.script = await readTextFile(`${appHome()}/mods/ob-subagents/transcript.py`); } catch (e) { this.err = `transcript.py: ${e?.message ?? e}`; }
      }
      await this.load(cx);
    });
    cx.timer.every(LOG_MS, (cx) => {
      if (!this.isLive() && !this.lastLive) return;
      if (this.p.view === "transcript" && Date.now() - this.at < TX_MS - 100) return;
      // One more read after the run ends, then stop.
      this.lastLive = this.isLive();
      this.load(cx);
    });
  }

  // Live while the run it belongs to is live in the feed (a viewer without a run uses props.live).
  isLive() {
    if (!this.p.live) return false;
    if (!this.p.runKey) return true;
    const f = feed();
    if (!f) return true;
    if (f.runs.some((r) => r.key === this.p.runKey)) return f.runs.some((r) => r.key === this.p.runKey && r.live);
    const c = f.claude.find((x) => x.key === this.p.runKey);
    return c ? !c.ended : false;
  }

  on() { return this.p.machine ? { on: this.p.machine } : {}; }

  async load(cx) {
    if (this.busy || !this.p.path) { if (!this.p.path) { this.err = "No file to show"; this.loading = false; cx.notify(); } return; }
    this.busy = true;
    try {
      if (this.p.view === "log") {
        const r = await exec("tail", ["-n", "400", this.p.path], { ...this.on(), timeout: 15000 });
        if (r.code !== 0) throw new Error((r.stderr || `tail exited ${r.code}`).trim().split("\n").pop());
        const next = r.stdout.replace(/\r/g, "").replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").split("\n");
        if (next.length && next[next.length - 1] === "") next.pop();
        const grew = next.length !== this.lines.length || next[next.length - 1] !== this.lines[this.lines.length - 1];
        this.lines = next.map((l) => (l.length > 600 ? l.slice(0, 599) + "…" : l));
        if (grew && this.follow) this.needEnd = 2;
      } else {
        if (!this.script) throw new Error(this.err ?? "transcript.py is missing");
        const r = await exec("python3", ["-c", this.script, this.p.path, "250"], { ...this.on(), timeout: 20000 });
        const line = r.stdout.trim().split("\n").pop() ?? "";
        if (r.code !== 0 || !line.startsWith("{")) throw new Error((r.stderr || `python3 exited ${r.code}`).trim().split("\n").pop());
        const d = JSON.parse(line);
        if (d.error) throw new Error(d.error);
        const grew = (d.entries?.length ?? 0) !== this.entries.length || this.meta?.size !== d.size;
        this.entries = Array.isArray(d.entries) ? d.entries : [];
        this.meta = { format: d.format, truncated: d.truncated, size: d.size };
        if (grew) { this.gen++; if (this.follow) this.needEnd = 2; }
      }
      this.err = null;
    } catch (e) {
      this.err = String(e?.message ?? e).slice(0, 300);
    }
    this.at = Date.now();
    this.loading = false;
    this.busy = false;
    cx.notify();
  }

  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    if (verb === "viewer-follow") { this.follow = arg !== "off"; if (this.follow) this.needEnd = 2; }
    else if (verb === "viewer-pin") this.pin();
    else if (verb === "viewer-copy") copied(cx, "path", this.p.path);
    else if (verb === "viewer-close") this.close();
    else if (verb === "viewer-refresh") this.load(cx);
    else if (verb === "viewer-tool") { const i = Number(arg); this.open.has(i) ? this.open.delete(i) : this.open.add(i); }
  }

  toEnd() {
    if (this.p.view === "log") { if (this.lines.length) this.vscroll.scroll_to_bottom(); }
    else if (this.entries.length) this.scroll.scroll_to_item(this.entries.length);
  }

  // Pin as pane: the same view as a mod pane to the right of the focused pane (structural).
  pin() {
    const { overlay, ...rest } = this.p;
    run("pane.split", { direction: "right", mod: "ob-subagents", props: rest });
    if (overlay) closeOverlay(overlay);
  }
  close() { if (this.p.overlay) closeOverlay(this.p.overlay); }

  // ---------------------------------------------------------------- render
  titleBar(t) {
    const p = this.p;
    const live = this.isLive();
    const where = `${machineLabel(p.machine)} · ${tilde(p.path)}`;
    const narrow = this.w > 0 && this.w < 520;
    return h_flex().id("vtitle").h(36).flex_none().pl(12).pr(6).gap(8).items_center().bg(t.chrome).border_b(1).border_color(t.border)
      .child(icon(p.view === "log" ? "scroll" : "file-text", S.icon, t.muted))
      .child(div().flex_none().max_w(narrow ? 200 : 320).truncate().text_size(S.text).font_semibold().text_color(t.foreground).child(p.title || base(p.path)))
      .when(live, (e) => e.child(h_flex().flex_none().gap(4).items_center().child(statusMark("working", 11)).child(div().text_size(S.textXs).text_color(t.working).child("live"))))
      .child(div().flex_1().min_w(0).truncate().text_size(S.textXs).text_color(t.dim).child(narrow ? "" : where))
      .child(iconButton({ id: "v-follow", icon: "arrow-right", tip: this.follow ? "Following the end (scroll up to stop)" : "Jump to the end and follow", active: this.follow, onClick: (_e, cx) => { this.follow = true; this.needEnd = 2; cx.notify(); } }))
      .child(iconButton({ id: "v-refresh", icon: "refresh", tip: "Read again", onClick: (_e, cx) => this.load(cx) }))
      .child(iconButton({ id: "v-copy", icon: "copy", tip: `Copy path\n${p.path}`, onClick: (_e, cx) => copied(cx, "path", p.path) }))
      .when(Boolean(p.overlay), (e) => e
        .child(iconButton({ id: "v-pin", icon: "split-right", tip: "Pin as a pane to the right", onClick: () => this.pin() }))
        .child(iconButton({ id: "v-close", icon: "x", tip: "Close", onClick: () => this.close() })));
  }

  footer(t) {
    const n = this.p.view === "log" ? `${this.lines.length} line${this.lines.length === 1 ? "" : "s"}${this.lines.length >= 400 ? " (last 400)" : ""}`
      : `${this.entries.length} entr${this.entries.length === 1 ? "y" : "ies"}${this.meta?.truncated ? " (latest)" : ""}`;
    return h_flex().h(24).flex_none().px(12).gap(10).items_center().border_t(1).border_color(t.border).bg(t.chrome)
      .text_size(S.textXs).text_color(t.dim)
      .child(div().child(n))
      .when(Boolean(this.meta?.format), (e) => e.child(div().child(this.meta.format)))
      .child(div().flex_1())
      .when(Boolean(this.err) && (this.lines.length || this.entries.length), (e) => e.child(h_flex().gap(4).items_center().min_w(0).child(icon("alert", S.iconXs, t.blocked)).child(div().truncate().text_color(t.blocked).child(this.err))))
      .child(div().flex_none().child(this.at ? `read ${ago(this.at) === "now" ? "just now" : ago(this.at) + " ago"}` : "reading…"));
  }

  stateBody(t) {
    if (this.loading) return v_flex().flex_1().items_center().justify_center().gap(8).child(statusMark("working", 16)).child(div().text_size(S.textSm).text_color(t.dim).child(`Reading on ${machineLabel(this.p.machine)}…`));
    if (this.err) return v_flex().flex_1().items_center().justify_center().gap(8).px(24)
      .child(icon("alert", 24, t.blocked))
      .child(div().text_size(S.text).text_color(t.muted).text_center().child(`Couldn't read this ${this.p.view === "log" ? "log" : "transcript"}`))
      .child(div().max_w(520).text_size(S.textSm).text_color(t.dim).text_center().child(this.err));
    return v_flex().flex_1().items_center().justify_center().gap(6)
      .child(icon(this.p.view === "log" ? "scroll" : "file-text", 24, t.dim))
      .child(div().text_size(S.textSm).text_color(t.dim).child(this.p.view === "log" ? "The log is empty so far." : "No messages in this transcript yet."));
  }

  logBody(t) {
    const lines = this.lines;
    const fs = 11.5;
    return div().id("vlog-wrap").relative().flex_1().min_h(0).bg(t.background)
      .on_scroll_wheel((e, cx) => { if ((e.delta?.y ?? 0) > 0 && this.follow) { this.follow = false; cx.notify(); } })
      .child(v_virtual_list("vlog", lines.length, 18, (i) => String(i), (range) => {
        const out = [];
        for (let i = range.start; i < range.end; i++) {
          const l = lines[i];
          out.push(h_flex().h(18).px(12).gap(10).items_center().font_family(MONO).text_size(fs)
            .child(div().w(30).flex_none().text_right().text_color(alpha(t.dim, 0.7)).child(String(i + 1)))
            .child(div().flex_1().min_w(0).truncate().text_color(/error|fail|✗|exception/i.test(l) ? t.blocked : /warn/i.test(l) ? t.working : t.foreground).child(l || " ")));
        }
        return out;
      }).track_scroll(this.vscroll).size_full())
      .child(Scrollbar.vertical("vlog").viewport_from_layout().absolute().inset_0());
  }

  entry(t, e, i) {
    const id = `ve-${this.gen}-${i}`;
    if (e.k === "user") {
      return h_flex().id(id).flex_none().mx(14).mt(12).rounded(S.radiusLg).bg(alpha(t.accent, 0.07)).overflow_hidden()
        .child(div().w(3).flex_none().self_stretch().bg(t.accent))
        .child(v_flex().flex_1().min_w(0).px(10).py(7).gap(3)
          .child(h_flex().gap(6).text_size(S.textXs).text_color(t.dim).child(div().font_semibold().text_color(t.accent).child("Prompt")).child(div().child(e.ts ? ago(typeof e.ts === "number" ? e.ts : Date.parse(e.ts)) : "")))
          .child(div().text_size(S.textSm).text_color(t.foreground).whitespace_normal().child(e.text)));
    }
    if (e.k === "assistant") {
      return v_flex().id(id).flex_none().mx(14).mt(10).px(4)
        .child(TextView.markdown(`md-${id}`, e.text).selectable(true).text_size(12.5).text_color(t.foreground));
    }
    if (e.k === "tool") {
      const open = this.open.has(i);
      const hasResult = e.result != null && e.result !== "";
      return v_flex().id(id).flex_none().mx(14).mt(4)
        .child(h_flex().id(`${id}-h`).h(24).px(8).gap(7).items_center().rounded(S.radius).cursor_pointer()
          .bg(open ? t.hover : alpha(t.raised, 0.6)).hover((s) => s.bg(t.hover))
          .on_click((_e, cx) => { open ? this.open.delete(i) : this.open.add(i); cx.notify(); })
          .child(icon(hasResult ? (open ? "chevron-down" : "chevron-right") : "dot", S.iconXs, t.dim))
          .child(icon(e.error ? "circle-x" : "terminal", S.iconXs, e.error ? t.blocked : t.muted))
          .child(div().flex_none().font_family(MONO).text_size(11).font_semibold().text_color(e.error ? t.blocked : t.muted).child(e.tool ?? "tool"))
          .child(div().flex_1().min_w(0).truncate().font_family(MONO).text_size(11).text_color(t.dim).child(e.args ?? "")))
        .when(open && hasResult, (el) => el.child(div().mx(4).mt(2).px(10).py(6).rounded(S.radius).bg(t.background).border_1().border_color(t.border)
          .font_family(MONO).text_size(11).text_color(e.error ? t.blocked : t.muted).whitespace_normal().child(e.result)));
    }
    return h_flex().id(id).flex_none().mx(14).mt(8).gap(6).items_center().text_size(S.textXs).text_color(t.dim)
      .child(div().h(1).w(18).bg(t.border)).child(div().child(e.text ?? "")).child(div().h(1).flex_1().bg(t.border));
  }

  transcriptBody(t) {
    return div().id("vtx-wrap").relative().flex_1().min_h(0).bg(t.background)
      .on_scroll_wheel((e, cx) => { if ((e.delta?.y ?? 0) > 0 && this.follow) { this.follow = false; cx.notify(); } })
      .child(v_flex().id("vtx").size_full().overflow_y_scroll().track_scroll(this.scroll)
        .children(this.entries.map((e, i) => this.entry(t, e, i)))
        .child(div().id("vtx-end").h(14).flex_none()))
      .child(Scrollbar.vertical("vtx").absolute().inset_0());
  }

  render(cx) {
    const t = tc();
    this.p = props() ?? this.p;
    const has = this.p.view === "log" ? this.lines.length > 0 : this.entries.length > 0;
    // Scroll requests are consumed after layout: ask on this frame and the next (the list may be new).
    if (has && this.needEnd > 0) {
      this.toEnd();
      if (--this.needEnd > 0) cx.timer.after(0, (cx) => cx.notify());
    }
    return v_flex().id("root").size_full().min_h(0).bg(t.background).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .child(this.titleBar(t))
      .child(has ? (this.p.view === "log" ? this.logBody(t) : this.transcriptBody(t)) : this.stateBody(t))
      .child(this.footer(t));
  }
}
