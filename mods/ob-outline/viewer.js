// The log / transcript viewer and the attach view of ob-outline: a popup over the window (or a pane
// after "Move to main window").
// props: { view: "log"|"transcript", machine, path, title, live, runKey, overlay? }
//   view "attach": a header only, for a popup whose layout puts the live terminal block below it:
//      { view: "attach", title, parent, machine, terminal, overlay }. Its header: name, parent, machine,
//      "Move to main window" (terminal.keep: the terminal gets a pane or tab) and "Detach" (the popup closes,
//      the terminal keeps running in the background; a click outside the popup does the same).
// log: `tail -n 400 <path>` on that machine, every 1.5 s while the run is live; follows the end
//      unless you scroll up (Follow button / viewer-follow:on brings it back).
// transcript: transcript.py parses the jsonl there (pi session, pi-subagents transcript, Claude Code)
//      into prompts, replies (markdown) and tool calls (click one to see its result); refreshed every
//      4 s while live.
// Commands (only viewers act on them): viewer-follow:<on|off>, viewer-move, viewer-copy, viewer-close,
//      viewer-tool:<index> (expand/collapse a tool call), viewer-refresh.

import { div } from "gpui-kit";
import { v_flex, h_flex, TextView, v_virtual_list, VirtualListScrollHandle, Scrollbar } from "gpui-base";
import { props, exec, readTextFile, appHome, run, closeOverlay, settings, focused, terminals, keys } from "herdr";
import { S, tc, icon, iconButton, alpha, ago, machineLabel, tilde, base, feed, statusMark, normStatus, stop } from "./kit.js";
import { MONO, splitCmd, copied, revealTerminal, placedSessionOf } from "./obc.js";
import { escapeOwner, moveTarget, DETACH_ICON, DETACH_POPUP_TIP } from "./actions.js";
import { endStep, rowHeights } from "./tail.js";

const LOG_MS = 1500, TX_MS = 4000;
const POPUP_H = 560;   // a popup sizes to its content: the viewer sets its own height there
const MEASURE_MAX = 60; // rows measured per frame (each is drawn once, unseen, to learn its height)

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
    // The transcript is a virtual list too: it is the only kind of scroll area a mod can move from code.
    // Its rows are placed by heights measured after layout (hts: row signature -> height, for width htsW).
    this.tscroll = VirtualListScrollHandle.new();
    this.hts = new Map();
    this.htsW = -1;
    this.wantEnd = false;
    this.w = 0;
    this.handle = cx.focus_handle();
    this.keysSig = "";
    if (this.isAttach()) {
      this.bindKeys(cx);
      cx.timer.after(0, () => { try { this.handle.focus(); } catch { /* not focusable yet */ } });
      cx.timer.after(60, () => { try { this.handle.focus(); } catch { /* not focusable yet */ } });
      return;
    }
    // Keyboard here so Escape reaches this viewer (a popup over the window, or a pane).
    cx.timer.after(0, () => { try { this.handle.focus(); } catch { /* not focusable yet: Herdr's Escape still closes it */ } });
    cx.spawn(async (cx) => {
      if (this.p.view === "transcript") {
        try { this.script = await readTextFile(`${appHome()}/mods/ob-outline/transcript.py`); } catch (e) { this.err = `transcript.py: ${e?.message ?? e}`; }
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

  bindKeys(cx) {
    if (typeof cx.bind_keys !== "function") return;
    cx.bind_keys([
      { keystroke: "escape", action: "ob_outline.attach_detach", context: "ObAttach" },
    ]);
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
  isAttach() { return this.p.view === "attach"; }

  async load(cx) {
    if (this.isAttach()) return;
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
        if (grew && this.follow) this.askEnd();
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
        if (grew) { this.gen++; if (this.follow) this.askEnd(); }
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
    if (verb === "viewer-follow") { this.follow = arg !== "off"; if (this.follow) this.askEnd(); }
    else if (verb === "viewer-move") this.moveToMain();
    else if (verb === "viewer-copy") copied(cx, "path", this.p.path);
    else if (verb === "viewer-close") this.close();
    else if (verb === "viewer-refresh") this.load(cx);
    else if (verb === "viewer-tool") { const i = Number(arg); this.open.has(i) ? this.open.delete(i) : this.open.add(i); }
  }

  // Ask for a jump to the end: log calls scroll_to_bottom() once; transcript repeats until rows are measured.
  askEnd() { this.wantEnd = true; }

  toEnd() {
    if (this.p.view === "log") { if (this.lines.length) this.vscroll.scroll_to_bottom(); }
    else if (this.entries.length) this.tscroll.scroll_to_bottom();
  }

  // A row's height depends on its content, whether it is expanded and the width; this names the first two.
  hkey(i) {
    const e = this.entries[i] ?? {};
    return `${e.k}|${e.ts ?? ""}|${String(e.text ?? "").length}|${e.tool ?? ""}|${String(e.args ?? "").length}|${String(e.result ?? "").length}|${this.open.has(i) ? 1 : 0}`;
  }

  // Move to main window (structural), then the popup closes. An attached terminal gets a pane or a tab
  // of its own (terminal.keep); a viewer becomes the same view as a mod pane beside the focused pane
  // (a new tab when no pane has the focus).
  moveToMain() {
    const { overlay, ...rest } = this.p;
    if (this.isAttach()) {
      if (overlay) closeOverlay(overlay);
      run("terminal.keep", { terminal: rest.terminal });
      return;
    }
    const mv = moveTarget(Boolean(focused()?.pane), rest);
    run(mv.verb, mv.args);
    if (overlay) closeOverlay(overlay);
  }
  close() { if (this.p.overlay) closeOverlay(this.p.overlay); }

  moveButton(t) {
    return h_flex().id("v-move").h(24).px(8).gap(5).flex_none().items_center().rounded(S.radius).cursor_pointer()
      .border_1().border_color(t.input).text_size(S.textXs).text_color(t.muted)
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .tooltip(this.isAttach() ? "Move this terminal to the main window (a pane or tab there); closes this popup" : "Move to the main window as a pane; closes this popup")
      .on_mouse_down("left", stop)
      .on_click((_e, cx) => { cx.stop_propagation(); this.moveToMain(); })
      .child(icon("split-right", S.iconXs))
      .child(div().whitespace_nowrap().child("Move to main window"));
  }

  // The header of an attach popup (the terminal itself is the block below it).
  attachHeader(t) {
    const p = this.p;
    const term = p.terminal ? terminals().find((x) => x.address === p.terminal) : null;
    const raw = term ? (typeof term.status === "string" ? term.status : term.status?.state) : "working";
    const st = normStatus(raw) || "idle";
    const stLabel = st === "blocked" ? "needs you" : st;
    const stColor = st === "blocked" || st === "failed" ? t.blocked : st === "working" ? t.working : t.muted;
    const mainSess = p.terminal ? placedSessionOf(p.terminal) : null;
    const mainAddr = mainSess?.address ?? p.mainTerminal ?? null;
    const mainLabel = mainSess?.label ?? p.mainTab ?? null;
    const where = [
      p.parent ? `started by ${p.parent}` : null,
      p.machine ? machineLabel(p.machine) : null,
      p.terminal,
      "Esc detaches · click terminal to type",
    ].filter(Boolean).join(" · ");
    return h_flex().id("vtitle").h(36).flex_none().pl(12).pr(6).gap(8).items_center().bg(t.chrome).border_b(1).border_color(t.border)
      .child(icon("terminal", S.icon, t.muted))
      .child(div().flex_none().max_w(260).truncate().text_size(S.text).font_semibold().text_color(t.foreground).child(p.title || p.terminal))
      .child(h_flex().flex_none().gap(4).items_center().child(statusMark(st, 11)).child(div().text_size(S.textXs).text_color(stColor).child(stLabel)))
      .child(div().flex_1().min_w(0).truncate().text_size(S.textXs).text_color(t.dim).child(where))
      .when(Boolean(mainAddr), (e) => e.child(
        h_flex().id("v-main-tab").h(24).px(8).gap(5).flex_none().items_center().rounded(S.radius).cursor_pointer()
          .border_1().border_color(t.input).text_size(S.textXs).text_color(t.muted)
          .hover((s) => s.bg(t.hover).text_color(t.foreground))
          .tooltip(`Go to ${mainLabel || mainAddr}`)
          .on_mouse_down("left", stop)
          .on_click((_e, cx) => { cx.stop_propagation(); this.close(); revealTerminal(mainAddr); })
          .child(icon("locate", S.iconXs))
          .child(div().whitespace_nowrap().child("Main tab")),
      ))
      .child(this.moveButton(t))
      .child(this.detachButton(t));
  }

  // Detach, in words (a bare x here reads as "end the program"): the popup closes, the terminal keeps running in
  // the background and stays listed in the Outline.
  detachButton(t) {
    return h_flex().id("v-detach").h(24).px(8).gap(5).flex_none().items_center().rounded(S.radius).cursor_pointer()
      .border_1().border_color(t.input).text_size(S.textXs).text_color(t.muted)
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .tooltip(DETACH_POPUP_TIP)
      .on_mouse_down("left", stop)
      .on_click((_e, cx) => { cx.stop_propagation(); this.close(); })
      .child(icon(DETACH_ICON, S.iconXs))
      .child(div().whitespace_nowrap().child("Detach"));
  }

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
      .child(iconButton({ id: "v-follow", icon: "arrow-right", tip: this.follow ? "Following the end (scroll up to stop)" : "Jump to the end and follow", active: this.follow, onClick: (_e, cx) => { this.follow = true; this.askEnd(); cx.notify(); } }))
      .child(iconButton({ id: "v-refresh", icon: "refresh", tip: "Read again", onClick: (_e, cx) => this.load(cx) }))
      .child(iconButton({ id: "v-copy", icon: "copy", tip: `Copy path\n${p.path}`, onClick: (_e, cx) => copied(cx, "path", p.path) }))
      .when(Boolean(p.overlay), (e) => e
        .child(this.moveButton(t))
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

  // The transcript: a virtual list (scrolled to the end from code), with rows of measured height. Rows whose
  // height is not known yet are also drawn, unseen, in a layer behind the list, where on_size_change reports
  // it; a list row may not register handlers, so a tool row's click goes through the list's on_item_click.
  transcriptBody(t, plan) {
    const n = this.entries.length;
    const zoom = settings().zoom || 1;
    return div().id("vtx-wrap").relative().flex_1().min_h(0).overflow_hidden().bg(t.background)
      .on_scroll_wheel((e, cx) => { if ((e.delta?.y ?? 0) > 0 && this.follow) { this.follow = false; cx.notify(); } })
      .child(v_flex().id("vtx-measure").absolute().top(0).left(0).w_full().opacity(0)
        .children(plan.todo.map((i) => {
          const k = this.hkey(i);
          return v_flex().id(`vm-${i}`).w_full().flex_none()
            .on_size_change((s, cx) => { const h = s.height / zoom; if (h > 0 && Math.abs((this.hts.get(k) ?? 0) - h) > 0.5) { this.hts.set(k, h); cx.notify(); } })
            .child(this.entry(t, this.entries[i], i));
        })))
      .child(v_virtual_list("vtx", n + 1, plan.heights, (i) => (i < n ? `${this.gen}-${i}` : "end"), (range) => {
        const out = [];
        for (let i = range.start; i < range.end; i++) {
          out.push(i < n ? v_flex().w_full().child(this.entry(t, this.entries[i], i)) : div().w_full());
        }
        return out;
      }).track_scroll(this.tscroll).size_full()
        .on_item_click((key, cx) => {
          const i = Number(String(key).split("-")[1]);
          const e = this.entries[i];
          if (e?.k !== "tool" || e.result == null || e.result === "") return;
          this.open.has(i) ? this.open.delete(i) : this.open.add(i);
          cx.notify();
        }))
      .child(Scrollbar.vertical("vtx").viewport_from_layout().absolute().inset_0());
  }

  // Heights for the list, and the rows still to be measured (the width they were measured at is kept:
  // another width wraps text differently, so they are measured again).
  transcriptPlan() {
    const wk = Math.round(this.w);
    if (wk !== this.htsW) { this.hts.clear(); this.htsW = wk; if (this.follow) this.wantEnd = true; }
    if (this.hts.size > 4 * this.entries.length + 64) this.hts.clear();
    const todo = [];
    let unmeasured = 0;
    const heights = rowHeights(this.entries.length, (i) => {
      const h = this.hts.get(this.hkey(i));
      if (h == null) { unmeasured++; if (todo.length < MEASURE_MAX) todo.push(i); }
      return h;
    });
    return { heights, todo, unmeasured };
  }

  render(cx) {
    const t = tc();
    this.p = props() ?? this.p;
    if (this.isAttach()) {
      let sig = "";
      try { sig = JSON.stringify(keys?.() ?? ""); } catch { sig = ""; }
      if (sig !== this.keysSig) {
        const first = this.keysSig === "";
        this.keysSig = sig;
        if (!first) cx.timer.after(0, (cx) => this.bindKeys(cx));
      }
      return v_flex().id("root").size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
        .track_focus(this.handle)
        .key_context("ObAttach")
        .on_action("ob_outline.attach_detach", (_a, cx) => { cx.stop_propagation(); this.close(); })
        .on_key_down((e, cx) => {
          if (e.key === "escape") { cx.stop_propagation(); this.close(); }
        })
        .child(this.attachHeader(t));
    }
    const has = this.p.view === "log" ? this.lines.length > 0 : this.entries.length > 0;
    let plan = null;
    if (has && this.p.view === "log") {
      if (this.wantEnd) {
        this.wantEnd = false;
        this.toEnd();
      }
    } else if (has) {
      plan = this.transcriptPlan();
      const step = endStep({ follow: this.follow, want: this.wantEnd, unmeasured: plan.unmeasured });
      this.wantEnd = step.want;
      if (step.scroll) this.toEnd();
    }
    return v_flex().id("root").size_full().min_h(0).bg(t.background).text_color(t.foreground)
      .when(Boolean(this.p.overlay), (e) => e.h(POPUP_H))
      .track_focus(this.handle)
      .on_key_down((e, cx) => {
        if (e.key === "escape" && escapeOwner(this.p.view) === "close") { cx.stop_propagation(); this.close(); }
      })
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .child(this.titleBar(t))
      .child(has ? (this.p.view === "log" ? this.logBody(t) : this.transcriptBody(t, plan)) : this.stateBody(t))
      .child(this.footer(t));
  }
}
