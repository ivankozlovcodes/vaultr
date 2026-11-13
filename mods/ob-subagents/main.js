// ob-subagents: every sub-agent on every machine, mapped to the session that started it (SPEC 8.C2).
// One mod, two views picked by props:
//   { slot }            the panel (right sidebar, bottom group)               this file
//   { view, path, ... } a log / transcript viewer (window overlay or pane)     viewer.js
//
// The panel: toolbar [This session | All] · Live only · machine filter · refresh. "This session" is
// ob.inspect's terminal, else the focused one: its pi-subagents runs, Claude Code agents and hc child
// terminals. "All" groups by machine, then by parent session, then runs; "Unattached" last.
// A run card shows state, agent chain, elapsed, mode/models/tokens/cost/tools and the live tool; click
// expands it into steps (task, meta, last tools, output tail, errors) and actions: Follow log,
// Transcript, Copy run id, Open child session (pi --session, checked per machine), Bookmark.
// Data: kit.feed() (ob-feed's scan) + terminals().records (live Claude agents) + hc children.
//
// Commands (ob-subagents.<cmd>; keys and tests): focus, expand:<key>, collapse:<key>, live-only:<on|off>,
//   log:<runKey>, transcript:<runKey|claudeKey>[#<step>], copy-id:<key>, open-session:<runKey>[#<step>],
//   bookmark:<runKey>, menu:<key>, scope:<session|all>, machine:<name|local|all>, inspect:<address>,
//   unpin, up, down, enter, refresh. Viewer copies take viewer-* (see viewer.js).
// Router intents: run:<key> (expand + scroll to it), term:<address> (inspect that session).

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { props, run, nextCommand, settings, exec, machines, spaces, panes, layout, focused } from "herdr";
import {
  S, tc, alpha, icon, iconButton, badge, statusMark, normStatus, sectionHeader, treeRow, emptyState, openMenu,
  programIcon, feed, machineLabel, machineOf, ago, dur, fmtTokens, fmtCost, takeFocus, isBookmarked, toggleBookmark,
  isShown, base, stop, kbd,
} from "./kit.js";
import {
  MONO, splitCmd, sessionOf, inspected, inspect, revealTerminal, runTitle, runModels, shortModel, runWhen, currentStep, lastTool,
  runMeta, stepTranscript, claudeAll, recordRuns, hcChildren, openViewer, copied, lines,
} from "./obc.js";
import { Viewer } from "./viewer.js";

const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable: keep in memory */ } };

class Panel {
  init(cx) {
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.open = new Set(load("open", []));
    const f = load("filter", {});
    this.liveOnly = Boolean(f.liveOnly);
    this.machine = typeof f.machine === "string" ? f.machine : null;   // null = all
    this.scope = load("scope", "session") === "all" ? "all" : "session";
    this.folded = new Set(load("folded", []));
    this.cursor = null;     // item key under the keyboard cursor
    this.w = 0;
    this.piSession = {};    // machine key -> true/false: pi accepts --session there (U7)
    this.index = new Map(); // item key -> row index (for scroll_to_item)
    cx.timer.every(1000, (cx) => {
      // Elapsed times of live runs (data, not animation): only while something runs and the panel shows.
      const f = feed();
      if ((f?.runs ?? []).some((r) => r.live) && isShown(layout(), props()?.slot ?? "ob-subagents")) cx.notify();
    });
  }

  persist() {
    save("open", [...this.open].slice(-80));
    save("filter", { liveOnly: this.liveOnly, machine: this.machine });
    save("scope", this.scope);
    save("folded", [...this.folded]);
  }

  // ---------------------------------------------------------------- lookups
  runOf(key) { return feed()?.runs.find((r) => r.key === key) ?? null; }
  claudeOf(key) { return claudeAll().find((c) => c.key === key) ?? null; }

  // Does pi on that machine know --session? Checked once per machine (read-only `pi --help`).
  checkPi(machine, cx) {
    const k = machine ?? "local";
    if (k in this.piSession) return;
    this.piSession[k] = false;
    cx.spawn(async (cx) => {
      try {
        const r = await exec("pi", ["--help"], { ...(machine ? { on: machine } : {}), timeout: 15000 });
        this.piSession[k] = /--session\s/.test(`${r.stdout}\n${r.stderr}`);
      } catch { this.piSession[k] = false; }
      cx.notify();
    });
  }

  // ---------------------------------------------------------------- actions
  toggle(key, on) {
    const want = on ?? !this.open.has(key);
    if (want) this.open.add(key); else this.open.delete(key);
    this.persist();
  }

  follow(r) {
    if (!r?.log) return;
    openViewer({ view: "log", machine: r.machine, path: r.log, title: `${runTitle(r)} · log`, live: r.live, key: `log-${r.key}`, runKey: r.key });
  }

  transcript(key) {
    const [k, si] = key.split("#");
    const r = this.runOf(k);
    if (r) {
      const step = si != null && si !== "" ? r.steps[Number(si)] : (stepTranscript(currentStep(r)) ? currentStep(r) : r.steps.find(stepTranscript));
      const path = stepTranscript(step);
      if (!path) return;
      openViewer({ view: "transcript", machine: r.machine, path, title: `${step.agent}${step.label ? " · " + step.label : ""} · transcript`, live: r.live, key: `tx-${r.key}-${r.steps.indexOf(step)}`, runKey: r.key });
      return;
    }
    const c = this.claudeOf(k);
    if (c?.transcript) openViewer({ view: "transcript", machine: c.machine, path: c.transcript, title: `${c.desc || c.type || "agent"} · transcript`, live: c.live, key: `tx-${c.key}`, runKey: c.live ? null : c.key });
  }

  // Open a step's child session in pi, as a new tab in the parent's space (structural).
  openSession(key) {
    const [k, si] = key.split("#");
    const r = this.runOf(k);
    if (!r) return;
    const step = si != null && si !== "" ? r.steps[Number(si)] : currentStep(r);
    if (!step?.session || !this.piSession[r.machine ?? "local"]) return;
    const sp = spaces();
    const parent = r.parent ? sessionOf(r.parent) : null;
    const space = parent?.space ?? sp.find((s) => s.active && (s.machine ?? null) === r.machine) ?? sp.find((s) => (s.machine ?? null) === r.machine);
    if (!space) return;
    run("tab.new", { space: space.id, argv: ["pi", "--session", step.session], ...(r.cwd ? { folder: r.cwd } : {}), name: `${step.agent} ${r.short}` });
  }

  bookmark(r) { toggleBookmark({ kind: "run", id: r.key, label: runTitle(r), machine: r.machine }); }

  menu(key, cx) {
    const r = this.runOf(key);
    if (r) {
      const step = currentStep(r);
      const canOpen = Boolean(step?.session) && this.piSession[r.machine ?? "local"];
      openMenu([
        { label: this.open.has(key) ? "Collapse" : "Expand", icon: this.open.has(key) ? "chevron-up" : "chevron-down", command: `ob-subagents.${this.open.has(key) ? "collapse" : "expand"}:${key}` },
        { label: "Follow log", icon: "scroll", command: `ob-subagents.log:${key}`, disabled: !r.log },
        { label: "Transcript", icon: "file-text", command: `ob-subagents.transcript:${key}`, disabled: !r.steps.some(stepTranscript) },
        { label: "Open child session", icon: "play", command: `ob-subagents.open-session:${key}`, disabled: !canOpen, hint: canOpen ? "new tab" : null },
        { separator: true },
        ...(r.parent ? [{ label: "Go to parent session", icon: "locate", command: "agent.focus", args: { terminal: r.parent } },
          { label: "Show parent's properties", icon: "info", command: `ob-tabs.open:ob-props@term:${r.parent}` }] : []),
        { label: "Copy run id", icon: "copy", copy: r.id },
        ...(r.dir ? [{ label: "Copy run folder", icon: "folder", copy: r.dir }] : []),
        { label: isBookmarked("run", r.key) ? "Remove bookmark" : "Bookmark", icon: "bookmark", command: `ob-subagents.bookmark:${key}` },
      ], { width: 240, title: `${runTitle(r)} · ${r.short}` });
      return;
    }
    const c = this.claudeOf(key);
    if (c) {
      openMenu([
        { label: "Transcript", icon: "file-text", command: `ob-subagents.transcript:${key}`, disabled: !c.transcript },
        { label: "Go to parent session", icon: "locate", command: "agent.focus", args: { terminal: c.parent } },
        { label: "Show parent's properties", icon: "info", command: `ob-tabs.open:ob-props@term:${c.parent}` },
        { separator: true },
        { label: "Copy agent id", icon: "copy", copy: c.id },
        ...(c.transcript ? [{ label: "Copy transcript path", icon: "copy", copy: c.transcript }] : []),
      ], { width: 240, title: c.desc || c.type });
    }
  }

  async command(c, cx) {
    const [verb, arg] = splitCmd(c);
    switch (verb) {
      case "focus": this.handle.focus(); break;
      case "expand": this.toggle(arg, true); this.reveal(arg); break;
      case "collapse": this.toggle(arg, false); break;
      case "live-only": this.liveOnly = arg !== "off"; this.persist(); break;
      case "scope": this.scope = arg === "all" ? "all" : "session"; this.persist(); break;
      case "machine": this.machine = !arg || arg === "all" ? null : arg; this.persist(); break;
      case "log": this.follow(this.runOf(arg)); break;
      case "transcript": this.transcript(arg); break;
      case "open-session": this.openSession(arg); break;
      case "copy-id": { const r = this.runOf(arg) ?? this.claudeOf(arg); if (r) copied(cx, r.short ? "run id" : "agent id", r.id); break; }
      case "bookmark": { const r = this.runOf(arg); if (r) this.bookmark(r); break; }
      case "menu": this.menu(arg, cx); break;
      case "inspect": inspect(arg || null); this.scope = "session"; this.persist(); break;
      case "unpin": inspect(null); break;
      case "refresh": run("ob-feed.refresh"); break;
      case "down": case "up": this.move(verb === "down" ? 1 : -1); break;
      case "enter": if (this.cursor) { this.toggle(this.cursor); } break;
      default: break;
    }
  }

  // Router intents (ob-tabs.open:ob-subagents@<intent>).
  intent(intent) {
    if (!intent) return;
    if (intent.startsWith("run:")) {
      const key = intent.slice(4);
      const r = this.runOf(key), c = r ? null : this.claudeOf(key);
      const parent = r?.parent ?? c?.parent ?? null;
      if (parent !== inspected().address) this.scope = "all";
      const mk = r ? (r.machine ?? "local") : c ? (c.machine ?? "local") : null;
      if (mk && this.machine && this.machine !== mk) this.machine = null;
      if (this.liveOnly && r && !r.live) this.liveOnly = false;
      this.open.add(key);
      this.persist();
      this.reveal(key);
    } else if (intent.startsWith("term:")) {
      inspect(intent.slice(5));
      this.scope = "session";
      this.persist();
    }
  }

  reveal(key) {
    this.cursor = key;
    this.pendingScroll = key;
  }

  move(d) {
    const keys = this.order ?? [];
    if (!keys.length) return;
    const i = keys.indexOf(this.cursor);
    this.cursor = keys[Math.max(0, Math.min(keys.length - 1, i < 0 ? (d > 0 ? 0 : keys.length - 1) : i + d))];
    this.pendingScroll = this.cursor;
  }

  // ---------------------------------------------------------------- model
  // Items of one parent (or of "no parent" on a machine): runs, Claude agents, hc children.
  build() {
    const f = feed();
    const runs = [...recordRuns(), ...(f?.runs ?? [])].filter((r) => !this.liveOnly || r.live);
    const claude = claudeAll().filter((c) => !this.liveOnly || c.live);
    const kids = hcChildren(null);
    return { f, runs, claude, kids };
  }

  // ---------------------------------------------------------------- rendering pieces
  compact() { return this.w > 0 && this.w < 260; }

  stepBlock(t, r, s, i) {
    const now = Date.now();
    const st = normStatus(s.status);
    const end = s.endedAt ?? (st === "working" ? now : null);
    const meta = [shortModel(s.model), s.startedAt && end ? dur(end - s.startedAt) : null, s.tokens != null ? `${fmtTokens(s.tokens)} tok` : null, s.cost ? fmtCost(s.cost) : null, s.turns ? `${s.turns} turn${s.turns === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ");
    const chars = Math.max(20, Math.floor(((this.w || 360) - 60) / 6.3));
    const id = `st-${r.key}-${i}`;
    const tx = stepTranscript(s);
    return v_flex().id(id).flex_none().gap(3).pl(10).pr(2).py(5).border_l(2).border_color(st === "working" ? t.working : st === "failed" ? t.blocked : t.border)
      .child(h_flex().h(20).gap(6).items_center()
        .child(statusMark(s.status, 11))
        .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).font_medium().text_color(t.foreground).child(s.label ? `${s.agent} · ${s.label}` : s.agent))
        .when(r.steps.length > 1, (e) => e.child(div().flex_none().text_size(S.textXs).text_color(t.dim).child(`${i + 1}/${r.steps.length}`)))
        .child(div().flex_1())
        .when(Boolean(s.status) && !this.compact(), (e) => e.child(badge(s.status, st === "working" ? "working" : st === "failed" ? "blocked" : st === "ok" ? "ansi2" : null)))
        .when(Boolean(tx), (e) => e.child(iconButton({ id: `${id}-tx`, icon: "file-text", size: 20, iconSize: 12, tip: "Transcript of this step", onClick: () => this.transcript(`${r.key}#${i}`) }))))
      .children(s.task ? lines(s.task, chars, 2).map((l, j) => div().id(`${id}-task-${j}`).truncate().text_size(S.textSm).text_color(t.muted).child(l)) : [])
      .when(Boolean(meta), (e) => e.child(div().truncate().text_size(S.textXs).text_color(t.dim).child(meta)))
      .when((s.tools?.length ?? 0) > 0, (e) => e.child(v_flex().gap(1).children(s.tools.map((x, j) =>
        h_flex().id(`${id}-tool-${j}`).gap(6).font_family(MONO).text_size(11).min_w(0)
          .child(div().flex_none().text_color(t.muted).child(x.tool))
          .child(div().flex_1().min_w(0).truncate().text_color(t.dim).child(x.args ?? ""))))))
      .when((s.out?.length ?? 0) > 0, (e) => e.child(v_flex().mt(1).px(7).py(4).rounded(S.radius).bg(t.chrome).border_1().border_color(t.border)
        .children(s.out.map((x, j) => div().id(`${id}-out-${j}`).truncate().font_family(MONO).text_size(11).text_color(t.dim).child(x)))))
      .when(Boolean(s.error), (e) => e.child(h_flex().gap(5).items_start().child(icon("alert", S.iconXs, t.blocked)).child(div().flex_1().min_w(0).whitespace_normal().text_size(S.textXs).text_color(t.blocked).child(s.error))));
  }

  actionButton(t, id, ic, label, tip, onClick, opts = {}) {
    const narrow = this.w > 0 && this.w < 330;
    return h_flex().id(id).h(24).px(narrow ? 5 : 8).gap(5).flex_none().items_center().rounded(S.radius).cursor_pointer()
      .border_1().border_color(t.input).text_size(S.textXs).text_color(opts.active ? t.accent : t.muted)
      .hover((s) => s.bg(t.hover).text_color(t.foreground))
      .tooltip(tip)
      .on_mouse_down("left", stop)
      .on_click((e, cx) => { cx.stop_propagation(); onClick(e, cx); })
      .child(icon(ic, S.iconXs))
      .when(!narrow, (e) => e.child(div().whitespace_nowrap().child(label)));
  }

  runCard(t, r, depth) {
    const now = Date.now();
    const open = !r.pending && this.open.has(r.key);
    const cur = this.cursor === r.key;
    const compact = this.compact();
    const live = r.live;
    const tool = live ? lastTool(r) : null;
    const step = currentStep(r);
    const id = `run-${r.key}`;
    if (open) this.needPi.add(r.machine ?? "local");
    const canOpen = Boolean(step?.session) && this.piSession[r.machine ?? "local"];
    const anyTx = r.steps.some(stepTranscript);
    return v_flex().id(id).relative().flex_none().ml(S.pad + depth * 10).mr(S.pad).mb(6).rounded(S.radiusLg).overflow_hidden()
      .border_1().border_color(cur ? alpha(t.accent, 0.7) : live ? alpha(t.working, 0.45) : t.border)
      .when(live, (e) => e.bg(t.background))
      .when(open && !live, (e) => e.bg(alpha(t.background, 0.55)))
      .child(v_flex().id(`${id}-head`).pl(live ? 10 : 9).pr(8).py(6).gap(2).cursor_pointer().hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => { this.cursor = r.key; this.toggle(r.key); cx.notify(); })
        .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.cursor = r.key; this.menu(r.key, cx); })
        .child(h_flex().h(18).gap(6).items_center()
          .child(statusMark(r.state, 12))
          .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.text).font_medium().text_color(live || open ? t.foreground : t.muted).child(runTitle(r)))
          .when(isBookmarked("run", r.key), (e) => e.child(icon("bookmark", 11, t.accent)))
          .child(div().flex_1().min_w(4))
          .child(div().flex_none().text_size(S.textXs).text_color(live ? t.working : t.dim).child(runWhen(r, now))))
        .child(div().truncate().text_size(S.textXs).text_color(t.dim).child(r.pending ? "starting · waiting for the next scan" : runMeta(r, compact) || r.short))
        .when(Boolean(tool) && !open, (e) => e.child(h_flex().gap(5).min_w(0).font_family(MONO).text_size(11)
          .child(div().flex_none().text_color(t.working).child("▸")).child(div().flex_1().min_w(0).truncate().text_color(t.muted).child(tool))))
        .when(!open && !live && Boolean(r.error), (e) => e.child(div().truncate().text_size(S.textXs).text_color(t.blocked).child(r.error))))
      .when(live, (e) => e.child(div().absolute().left(0).top(0).bottom(0).w(2).bg(t.working)))
      .when(open, (e) => e.child(v_flex().px(9).pb(8).pt(2).gap(6)
        .children(r.steps.map((s, i) => this.stepBlock(t, r, s, i)))
        .when(r.steps.length === 0, (x) => x.child(div().text_size(S.textXs).text_color(t.dim).child("No steps recorded for this run.")))
        .when(Boolean(r.error) && !r.steps.some((s) => s.error === r.error), (x) => x.child(div().whitespace_normal().text_size(S.textXs).text_color(t.blocked).child(r.error)))
        .child(h_flex().gap(5).flex_wrap().pt(2)
          .when(Boolean(r.log), (x) => x.child(this.actionButton(t, `${id}-log`, "scroll", "Follow log", `Follow ${base(r.log)} (tail, refreshed while live)`, () => this.follow(r))))
          .when(anyTx, (x) => x.child(this.actionButton(t, `${id}-tx`, "file-text", "Transcript", "Read the transcript of the current step", () => this.transcript(r.key))))
          .child(this.actionButton(t, `${id}-copy`, "copy", "Copy id", `Copy run id ${r.id}`, (_e, cx) => copied(cx, "run id", r.id)))
          .when(canOpen, (x) => x.child(this.actionButton(t, `${id}-open`, "play", "Open session", "Open this step's child session with pi --session in a new tab", () => this.openSession(r.key))))
          .child(this.actionButton(t, `${id}-bm`, isBookmarked("run", r.key) ? "bookmark" : "bookmark-plus", isBookmarked("run", r.key) ? "Bookmarked" : "Bookmark", "Bookmark this run", () => this.bookmark(r), { active: isBookmarked("run", r.key) }))
          .child(div().flex_1())
          .child(div().flex_none().font_family(MONO).text_size(10.5).text_color(t.dim).child(r.short)))));
  }

  claudeCard(t, c, depth) {
    const open = this.open.has(c.key);
    const cur = this.cursor === c.key;
    const id = `cl-${c.key}`;
    const meta = [c.type, shortModel(c.model), c.outTokens ? `${fmtTokens(c.outTokens)} out` : null, c.updatedAt ? `${ago(c.updatedAt)}${ago(c.updatedAt) === "now" ? "" : " ago"}` : null].filter(Boolean).join(" · ");
    const tool = c.lastTool ? `${c.lastTool.tool ?? ""} ${c.lastTool.args ?? ""}`.trim() : null;
    const st = c.live ? (c.state === "blocked" ? "blocked" : "working") : "ok";
    return v_flex().id(id).relative().flex_none().ml(S.pad + depth * 10).mr(S.pad).mb(6).rounded(S.radiusLg).overflow_hidden()
      .border_1().border_color(cur ? alpha(t.accent, 0.7) : c.live ? alpha(t.working, 0.45) : t.border)
      .when(c.live, (e) => e.bg(t.background))
      .child(v_flex().id(`${id}-head`).pl(c.live ? 10 : 9).pr(8).py(6).gap(2).cursor_pointer().hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => { this.cursor = c.key; this.toggle(c.key); cx.notify(); })
        .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.cursor = c.key; this.menu(c.key, cx); })
        .child(h_flex().h(18).gap(6).items_center()
          .child(statusMark(st, 12))
          .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.text).font_medium().text_color(c.live || open ? t.foreground : t.muted).child(c.desc || c.type || c.id))
          .child(div().flex_1().min_w(4))
          .child(icon("bot", S.iconXs, t.dim)))
        .when(Boolean(meta), (e) => e.child(div().truncate().text_size(S.textXs).text_color(t.dim).child(meta)))
        .when(Boolean(tool) && (c.live || open), (e) => e.child(h_flex().gap(5).min_w(0).font_family(MONO).text_size(11)
          .child(div().flex_none().text_color(c.live ? t.working : t.dim).child("▸")).child(div().flex_1().min_w(0).truncate().text_color(t.muted).child(tool)))))
      .when(c.live, (e) => e.child(div().absolute().left(0).top(0).bottom(0).w(2).bg(t.working)))
      .when(open, (e) => e.child(h_flex().px(9).pb(8).pt(2).gap(5).flex_wrap()
        .when(Boolean(c.transcript), (x) => x.child(this.actionButton(t, `${id}-tx`, "file-text", "Transcript", "Read this agent's transcript", () => this.transcript(c.key))))
        .child(this.actionButton(t, `${id}-copy`, "copy", "Copy id", `Copy agent id ${c.id}`, (_e, cx) => copied(cx, "agent id", c.id)))
        .child(div().flex_1())
        .child(div().flex_none().font_family(MONO).text_size(10.5).text_color(t.dim).child(c.id.slice(0, 10)))));
  }

  childRow(t, k, depth) {
    const st = typeof k.status === "string" ? k.status : k.status?.state ?? null;
    return treeRow({
      id: `hc-${k.address}`, depth, height: S.rowSm, selected: false, cursor: this.cursor === `h:${k.address}`,
      lead: h_flex().gap(5).items_center().child(statusMark(st, 11)).child(programIcon(k.program, S.iconXs)),
      label: k.name || k.title || k.program?.name || k.address, dim: true,
      after: [this.compact() ? null : div().flex_none().text_size(S.textXs).text_color(t.dim).child(k.address)],
      right: [div().text_size(S.textXs).text_color(t.dim).child("peek")],
      onClick: () => run("terminal.peek", { terminal: k.address }),
    });
  }

  parentRow(t, key, s, counts) {
    const unattached = !s;
    return treeRow({
      id: `par-${key}`, depth: 0, chevron: !this.folded.has(key), onToggle: (_e, cx) => { this.folded.has(key) ? this.folded.delete(key) : this.folded.add(key); this.persist(); cx.notify(); },
      lead: unattached ? icon("layers", S.iconSm, t.dim) : programIcon(s.program, S.iconSm),
      label: unattached ? "Unattached" : s.label, bold: !unattached, dim: unattached,
      after: [!unattached && !this.compact() ? div().flex_none().text_size(S.textXs).text_color(t.dim).child(s.address) : null],
      right: [counts.live ? badge(`${counts.live} live`, "working") : null, !counts.live ? div().text_size(S.textXs).text_color(t.dim).child(String(counts.total)) : null],
      onClick: unattached ? (_e, cx) => { this.folded.has(key) ? this.folded.delete(key) : this.folded.add(key); this.persist(); cx.notify(); } : () => revealTerminal(s.address),
      onRight: unattached ? null : () => openMenu([
        { label: "Go to session", icon: "locate", command: "agent.focus", args: { terminal: s.address } },
        { label: "Show only this session", icon: "filter", command: `ob-subagents.inspect:${s.address}` },
        { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${s.address}` },
        { label: "Copy address", icon: "copy", copy: s.address },
      ], { width: 230, title: s.label }),
    });
  }

  // Rows for one parent's items. Pushes [key, element] pairs.
  items(t, rows, runs, claude, kids, depth) {
    const sorted = [
      ...runs.map((r) => ({ live: r.live, at: r.lastUpdate ?? 0, el: () => this.runCard(t, r, depth), key: r.key })),
      ...claude.map((c) => ({ live: c.live, at: c.updatedAt ?? Date.now(), el: () => this.claudeCard(t, c, depth), key: c.key })),
    ].sort((a, b) => (b.live - a.live) || (b.at - a.at));
    for (const x of sorted) rows.push([x.key, x.el()]);
    for (const k of kids) rows.push([`h:${k.address}`, this.childRow(t, k, depth + 1)]);
  }

  toolbar(t, pinned) {
    const seg = (id, label, on, onClick) => h_flex().id(id).h(22).px(this.compact() ? 6 : 9).items_center().rounded(S.radius).cursor_pointer()
      .text_size(S.textXs).font_medium().text_color(on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
      .when(!on, (e) => e.hover((s) => s.bg(t.hover).text_color(t.muted)))
      .on_click((_e, cx) => { onClick(); this.persist(); cx.notify(); }).child(label);
    const ms = machines().map((m) => m.name ?? null);
    return h_flex().id("tb").h(S.toolbar).flex_none().px(S.pad).gap(4).items_center()
      .child(h_flex().p(2).gap(2).rounded(S.radiusLg).bg(alpha(t.raised, 0.7)).border_1().border_color(t.border)
        .child(seg("seg-session", this.compact() ? "Session" : "This session", this.scope === "session", () => { this.scope = "session"; }))
        .child(seg("seg-all", "All", this.scope === "all", () => { this.scope = "all"; })))
      .child(div().flex_1())
      .when(pinned, (e) => e.child(iconButton({ id: "unpin", icon: "pin", active: true, tip: "Showing a pinned session. Click: follow the focused one", onClick: () => inspect(null) })))
      .child(iconButton({ id: "live-only", icon: "zap", active: this.liveOnly, tip: this.liveOnly ? "Live only (click: show finished too)" : "Show live only", onClick: (_e, cx) => { this.liveOnly = !this.liveOnly; this.persist(); cx.notify(); } }))
      .child(iconButton({ id: "machines", icon: "filter", active: this.machine != null, tip: this.machine ? `Only ${machineLabel(this.machine === "local" ? null : this.machine)}` : "Filter by machine",
        onClick: () => openMenu([
          { label: "All machines", checked: this.machine == null, command: "ob-subagents.machine:all" },
          { separator: true },
          ...ms.map((m) => ({ label: machineLabel(m), icon: m ? "server" : "monitor", checked: this.machine === (m ?? "local"), command: `ob-subagents.machine:${m ?? "local"}` })),
        ], { width: 210, title: "Machines" }) }))
      .child(iconButton({ id: "refresh", icon: "refresh", tip: "Scan every machine now", onClick: () => run("ob-feed.refresh") }));
  }

  machineHeader(t, mk, f, n, live) {
    const st = f?.machines?.[mk];
    const folded = this.folded.has(`m:${mk}`);
    const m = mk === "local" ? null : mk;
    const warn = st && !st.ok;
    return sectionHeader({
      id: `mh-${mk}`, title: machineLabel(m).toUpperCase(), count: n, open: !folded,
      onToggle: (_e, cx) => { folded ? this.folded.delete(`m:${mk}`) : this.folded.add(`m:${mk}`); this.persist(); cx.notify(); },
      right: [
        live ? badge(`${live} live`, "working") : null,
        warn ? h_flex().id(`mh-${mk}-warn`).gap(4).items_center().tooltip(`${st.error ?? "Scan failed"}${st.stale ? "\nShowing the last result" : ""}`)
          .child(icon("alert", S.iconXs, t.blocked)).when(!this.compact(), (e) => e.child(div().font_normal().text_color(t.blocked).child(st.stale ? "offline" : "scan failed"))) : null,
      ].filter(Boolean),
    });
  }

  sessionView(t, rows, data) {
    const { address, pinned } = inspected();
    const s = address ? sessionOf(address) : null;
    if (!s) return { empty: emptyState({ icon: "subagents", title: "No session focused", body: "Focus a terminal to see the sub-agents it started, or look at every machine.", action: { id: "to-all", label: "Show all machines", onClick: (_e, cx) => { this.scope = "all"; this.persist(); cx.notify(); } } }) };
    const runs = data.runs.filter((r) => r.parent === address);
    const claude = data.claude.filter((c) => c.parent === address);
    const kids = data.kids.filter((k) => k.parent === address);
    const live = runs.filter((r) => r.live).length + claude.filter((c) => c.live).length + kids.length;
    // The session itself, like a note's title row.
    rows.push([`s:${address}`, treeRow({
      id: "sess", depth: 0, height: 30, lead: programIcon(s.program, S.iconSm), label: s.label, bold: true,
      after: [this.compact() ? null : div().flex_none().text_size(S.textXs).text_color(t.dim).child(address)],
      right: [statusMark(s.status, 12)],
      onClick: () => revealTerminal(address),
      onRight: () => openMenu([
        { label: "Go to session", icon: "locate", command: "agent.focus", args: { terminal: address } },
        { label: pinned ? "Unpin" : "Pin this session", icon: pinned ? "pin-off" : "pin", command: pinned ? "ob-subagents.unpin" : `ob-subagents.inspect:${address}` },
        { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${address}` },
      ], { width: 220 }),
    })]);
    const total = runs.length + claude.length + kids.length;
    if (!total) {
      const f = data.f;
      return { empty: emptyState({ icon: this.liveOnly ? "zap" : "subagents", title: this.liveOnly ? "Nothing running here" : "No sub-agents yet",
        body: f ? `pi background runs (last ${48} h), Claude Code agents and terminals this session starts show up here.` : "Scanning machines…",
        action: { id: "to-all", label: "Show all machines", onClick: (_e, cx) => { this.scope = "all"; this.persist(); cx.notify(); } } }) };
    }
    const piN = runs.length, clN = claude.length;
    if (piN) {
      rows.push(["hdr:pi", sectionHeader({ id: "h-pi", title: "PI RUNS", count: piN, right: [runs.some((r) => r.live) ? badge(`${runs.filter((r) => r.live).length} live`, "working") : null].filter(Boolean) })]);
      this.items(t, rows, runs, [], [], 0);
    }
    if (clN) {
      rows.push(["hdr:cl", sectionHeader({ id: "h-cl", title: "CLAUDE AGENTS", count: clN, right: [claude.some((c) => c.live) ? badge(`${claude.filter((c) => c.live).length} live`, "working") : null].filter(Boolean) })]);
      this.items(t, rows, [], claude, [], 0);
    }
    if (kids.length) {
      rows.push(["hdr:hc", sectionHeader({ id: "h-hc", title: "TERMINALS", count: kids.length })]);
      for (const k of kids) rows.push([`h:${k.address}`, this.childRow(t, k, 0)]);
    }
    return { live };
  }

  allView(t, rows, data) {
    const f = data.f;
    const order = [null, ...machines().map((m) => m.name ?? null).filter((m) => m !== null)];
    for (const k of Object.keys(f?.machines ?? {})) { const m = k === "local" ? null : k; if (!order.includes(m)) order.push(m); }
    const ps = panes(), sp = spaces();
    let shown = 0;
    for (const m of order) {
      const mk = m ?? "local";
      if (this.machine && this.machine !== mk) continue;
      const runs = data.runs.filter((r) => (r.machine ?? null) === m);
      const claude = data.claude.filter((c) => (c.machine ?? null) === m);
      const kids = data.kids.filter((k) => machineOf(k.address) === m);
      const n = runs.length + claude.length + kids.length;
      const st = f?.machines?.[mk];
      if (!n && !(st && !st.ok)) continue;
      shown += n;
      const live = runs.filter((r) => r.live).length + claude.filter((c) => c.live).length + kids.length;
      rows.push([`m:${mk}`, this.machineHeader(t, mk, f, n, live)]);
      if (this.folded.has(`m:${mk}`)) continue;
      // Parents: every address that owns something, live ones first, then by newest activity.
      const parents = new Map();
      const slot = (p) => { if (!parents.has(p)) parents.set(p, { runs: [], claude: [], kids: [], live: 0, at: 0 }); return parents.get(p); };
      for (const r of runs) { const x = slot(r.parent ?? null); x.runs.push(r); x.live += r.live ? 1 : 0; x.at = Math.max(x.at, r.lastUpdate ?? 0); }
      for (const c of claude) { const x = slot(c.parent ?? null); x.claude.push(c); x.live += c.live ? 1 : 0; x.at = Math.max(x.at, c.updatedAt ?? 0); }
      for (const k of kids) { const x = slot(k.parent); x.kids.push(k); x.live += 1; x.at = Date.now(); }
      const list = [...parents.entries()].sort(([a, x], [b, y]) => (a === null) - (b === null) || (y.live - x.live) || (y.at - x.at));
      for (const [p, x] of list) {
        const key = `p:${mk}:${p ?? "-"}`;
        const s = p ? sessionOf(p, ps, sp) : null;
        rows.push([key, this.parentRow(t, key, p ? s : null, { live: x.live, total: x.runs.length + x.claude.length + x.kids.length })]);
        if (this.folded.has(key)) continue;
        this.items(t, rows, x.runs, x.claude, x.kids, 0);
      }
    }
    if (!shown && !rows.length) {
      return { empty: emptyState({ icon: this.liveOnly ? "zap" : "subagents", title: this.liveOnly ? "Nothing running" : f ? "No sub-agents" : "Scanning machines…",
        body: this.liveOnly ? "No pi run, Claude agent or child terminal is working right now." : f ? "pi background runs from the last 48 h, Claude Code agents and child terminals of every machine show up here." : "Reading pi-subagents runs and Claude Code agents on every machine.",
        action: this.liveOnly ? { id: "show-finished", label: "Show finished too", onClick: (_e, cx) => { this.liveOnly = false; this.persist(); cx.notify(); } } : null }) };
    }
    return {};
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-subagents", this.handle, (_cx, intent) => this.intent(intent));
    const data = this.build();
    const rows = [];
    this.needPi = new Set();
    const res = this.scope === "all" ? this.allView(t, rows, data) : this.sessionView(t, rows, data);
    this.index = new Map(rows.map(([k], i) => [k, i]));
    this.order = rows.map(([k]) => k).filter((k) => this.runOf(k) || this.claudeOf(k) || k.startsWith("h:"));
    if (this.pendingScroll && this.index.has(this.pendingScroll)) {
      this.scroll.scroll_to_item(this.index.get(this.pendingScroll));
      this.pendingScroll = null;
    }
    const need = [...this.needPi].filter((m) => !(m in this.piSession));
    this.needPi.clear();
    if (need.length) cx.timer.after(0, (cx) => { for (const m of need) this.checkPi(m === "local" ? null : m, cx); });
    const pinned = inspected().pinned;
    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => {
        if (e.key === "down" || e.key === "j") this.move(1);
        else if (e.key === "up" || e.key === "k") this.move(-1);
        else if ((e.key === "enter" || e.key === "space") && this.cursor) {
          if (this.cursor.startsWith("h:")) run("terminal.peek", { terminal: this.cursor.slice(2) }); else this.toggle(this.cursor);
        } else if (e.key === "l" && this.cursor) this.follow(this.runOf(this.cursor));
        else if (e.key === "t" && this.cursor) this.transcript(this.cursor);
        else if (e.key === "escape") { this.cursor = null; const f = focused(); if (f?.pane) run("pane.focus", { pane: f.pane }); }
        else return;
        cx.stop_propagation();
        cx.notify();
      })
      .child(this.toolbar(t, pinned))
      .child(div().h(1).flex_none().bg(t.border))
      .child(div().id("list-wrap").relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().pt(4).overflow_y_scroll().track_scroll(this.scroll)
          .children(rows.map(([, el]) => el))
          .when(Boolean(res.empty), (e) => e.child(res.empty))
          .child(div().id("list-end").h(8).flex_none()))
        .child(Scrollbar.vertical("list").absolute().inset_0()));
  }
}

export default class Subagents extends View {
  init(_p, cx) {
    const p = props() ?? {};
    this.view = p.view ? new Viewer() : new Panel();
    this.isViewer = Boolean(p.view);
    this.view.init(cx);
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try {
          const viewerCmd = c.startsWith("viewer-");
          if (this.isViewer && viewerCmd) this.view.command(c, cx);
          else if (!this.isViewer && !viewerCmd) await this.view.command(c, cx);
        } catch (e) { console.log(`ob-subagents: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }
  render(cx) { return this.view.render(cx); }
}
