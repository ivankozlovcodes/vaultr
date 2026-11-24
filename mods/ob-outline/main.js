// ob-outline: the one panel for what runs in each tab (Subagents folded in). Two views picked by props:
//   { slot }            the panel (right sidebar, bottom group, next to Graph)          this file
//   { view, path, ... } a log / transcript viewer (popup, or pane after "Move to main window")  viewer.js
//   { view: "attach", terminal, ... } a header for a live hc child terminal in a popup         viewer.js
//
// The panel lists the active tab's panes. Under each pane: the sub-agents that run in its terminal (runs,
// sub-agents, child terminals), each with state, tools and tokens; a click expands it into steps and actions
// (Follow log, Transcript, Open child session, Bookmark). A pinned session outside this tab is shown after the
// panes. "All" groups every machine by session, with "Unattached" background terminals last. Live only and
// the machine filter apply to both.
// Logs, transcripts and live terminals open in a popup (openViewer / openAttach in obc.js); "Move to main
// window" in the popup puts them on screen. Data: provider (kit/provider.js) + terminals().records + hc children.
//
// Commands (ob-outline.<cmd>; keys and tests): focus, next, prev, open, expand:<key>, collapse:<key>,
//   live-only:<on|off>, log:<runKey>, transcript:<runKey|agentKey>[#<step>], copy-id:<key>,
//   open-session:<runKey>[#<step>], attach:<address>, bookmark:<runKey>, menu:<key>, scope:<tab|all>,
//   machine:<name|local|all>, inspect:<address>, unpin, up, down, enter, refresh. Viewer copies take viewer-*.
// Router intents: run:<key> (expand + scroll to it), term:<address> (inspect that session).

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { props, run, nextCommand, settings, exec, hc, machines, spaces, panes, layout, focused, terminals, notify } from "herdr";
import {
  S, tc, alpha, icon, iconButton, badge, statusMark, normStatus, sectionHeader, treeRow, emptyState, openMenu,
  programIcon, feed, provider, machineLabel, machineOf, ago, dur, fmtTokens, fmtCost, takeFocus,
  isBookmarked, toggleBookmark, isShown, base, stop, kbd, feedLine, paneLabelOf, tabLabel, cleanTitle,
  sessionTitleOf, tilde,
} from "./kit.js";
import {
  MONO, splitCmd, sessionOf, placedSessionOf, inspected, inspect, revealTerminal, runTitle, runModels, shortModel, runWhen, currentStep, lastTool,
  runMeta, stepTranscript, allSubagents, openViewer, openAttach, copied, lines,
} from "./obc.js";
import { Viewer } from "./viewer.js";
import { rowClick } from "./rows.js";
import { listedTerminals, parentAddr, parentMap } from "./terminals.js";
import { paneAgents, onMachine, liveCount, sessionGroups, keepLiveAncestors, nestItems } from "./tree.js";
import { resolveKey, transcriptPlan, attachPlan, attachStep, ATTACH_WAIT, detachItem } from "./actions.js";

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
    this.scope = load("scope", "tab") === "all" ? "all" : "tab";
    this.folded = new Set(load("folded", []));
    this.cursor = null;     // item key under the keyboard cursor
    this.w = 0;
    this.sessionSupport = {}; // "<machine>:<prog>" -> true/false: accepts --session there
    this.index = new Map(); // item key -> row index (for scroll_to_item)
    cx.timer.every(1000, (cx) => {
      // Elapsed times of live runs (data, not animation): only while something runs and the panel shows.
      if (provider.subagents().some((r) => r.kind === "run" && r.live) && isShown(layout(), props()?.slot ?? "ob-outline")) cx.notify();
    });
  }

  persist() {
    save("open", [...this.open].slice(-80));
    save("filter", { liveOnly: this.liveOnly, machine: this.machine });
    save("scope", this.scope);
    save("folded", [...this.folded]);
  }

  // ---------------------------------------------------------------- lookups
  allSubagents() { return allSubagents(); }
  runOf(key) { return this.allSubagents().runs.find((r) => r.key === key) ?? null; }
  agentOf(key) { return this.allSubagents().agents.find((c) => c.key === key) ?? null; }

  // Does a run provider CLI on that machine accept --session? Checked once per (machine, program).
  checkSessionSupport(machine, prog, cx) {
    if (!prog) return;
    const k = `${machine ?? "local"}:${prog}`;
    if (k in this.sessionSupport) return;
    this.sessionSupport[k] = false;
    cx.spawn(async (cx) => {
      try {
        const r = await exec(prog, ["--help"], { ...(machine ? { on: machine } : {}), timeout: 15000 });
        this.sessionSupport[k] = /--session\s/.test(`${r.stdout}\n${r.stderr}`);
      } catch { this.sessionSupport[k] = false; }
      cx.notify();
    });
  }

  // ---------------------------------------------------------------- actions
  toggle(key, on) {
    const want = on ?? !this.open.has(key);
    if (want) this.open.add(key); else this.open.delete(key);
    this.persist();
  }

  // A short notice (info or error). Nothing in the panel fails silently.
  notice(title, body, level = "info") {
    notify({ title, body: String(body ?? "").slice(0, 160), level, timeout: level === "error" ? 4000 : 2500 });
  }

  // Open a popup. A failure shows an error notice.
  showViewer(what, p) {
    const fail = (e) => this.notice(`Couldn't open the ${what}`, e?.message ?? e, "error");
    try {
      Promise.resolve(openViewer(p)).catch(fail);
    } catch (e) { fail(e); }
  }

  follow(r) {
    if (!r) return;
    if (!r.log) { this.notice("No log", "This run has no log file to follow"); return; }
    this.showViewer("log", { view: "log", machine: r.machine, path: r.log, title: `${runTitle(r)} · log`, live: r.live, key: `log-${r.key}`, runKey: r.key });
  }

  // Transcript of a run step, sub-agent, or child terminal. A sub-agent seen only through a live record has no
  // path in the feed: its transcript is found by agent id via provider.transcript(..., { find: true }).
  async transcript(key) {
    if (String(key ?? "").startsWith("h:")) {
      const addr = String(key).slice(2);
      const k = terminals().find((x) => x.address === addr);
      const plan = transcriptPlan({ path: provider.session(addr)?.transcript ?? null, title: `${this.childTitle(k ?? { address: addr })} · transcript` });
      if (!plan.open) { this.notice("No transcript", plan.notice); return; }
      const st = normStatus(typeof k?.status === "string" ? k.status : k?.status?.state);
      this.showViewer("transcript", { view: "transcript", machine: machineOf(addr), path: plan.path, title: plan.title, live: st === "working" || st === "blocked", key: `tx-h-${addr}` });
      return;
    }
    const { runs, agents } = this.allSubagents();
    const hit = resolveKey(key, { runs: runs.map((r) => r.key), agents: agents.map((c) => c.key) });
    if (!hit) { this.notice("No transcript", "That agent is no longer in the feed", "error"); return; }
    const r = runs.find((x) => x.key === hit.key) ?? null;
    if (r) {
      const step = hit.step != null ? r.steps[hit.step] : (stepTranscript(currentStep(r)) ? currentStep(r) : r.steps.find(stepTranscript));
      const plan = transcriptPlan({ path: stepTranscript(step), title: `${step?.agent ?? provider.of(r)?.noun ?? "run"}${step?.label ? " · " + step.label : ""} · transcript` });
      if (!plan.open) { this.notice("No transcript", "No transcript is recorded for this run yet"); return; }
      this.showViewer("transcript", { view: "transcript", machine: r.machine, path: plan.path, title: plan.title, live: r.live, key: `tx-${r.key}-${r.steps.indexOf(step)}`, runKey: r.key });
      return;
    }
    const c = agents.find((x) => x.key === hit.key) ?? null;
    if (!c) { this.notice("No transcript", "That agent is no longer in the feed", "error"); return; }
    let path = c.transcript;
    if (!path && c.id) {
      const found = await provider.transcript(c, { find: true });
      if (found.ok) path = found.path;
      else if (found.reason === "failed") this.notice("Couldn't find the transcript", found.error, "error");
    }
    const plan = transcriptPlan({ transcript: path, desc: c.desc, type: c.type });
    if (!plan.open) { this.notice("No transcript", "No transcript file for this agent yet: it writes one as it runs"); return; }
    this.showViewer("transcript", { view: "transcript", machine: c.machine, path: plan.path, title: plan.title, live: c.live, key: `tx-${c.key}`, runKey: c.live ? null : c.key });
  }

  // A click or Enter on a card head: expand in place or collapse (rows.js). A starting run says why.
  click(key, cx, pending = false) {
    if (key.startsWith("pane:")) { this.cursor = key; this.focusPane(key.slice(5)); cx.notify(); return; }
    const { expanded, notice } = rowClick(key, this.open, { pending });
    this.open = expanded;
    this.cursor = key;
    this.persist();
    if (notice) this.notice("Not yet", notice);
    cx.notify();
  }

  // Open a step's child session in a new terminal started as a child of the run's parent
  // (so it shows under the parent), attached in a popup. Local runs only; it reaches the main window
  // only through the popup's "Move to main window".
  async openSession(key, cx = null) {
    const runs = this.allSubagents().runs;
    const hit = resolveKey(key, { runs: runs.map((x) => x.key) });
    const r = hit ? runs.find((x) => x.key === hit.key) ?? null : null;
    if (!r || r.machine) return;
    const prog = provider.of(r)?.id;
    const step = hit.step != null ? r.steps[hit.step] : currentStep(r);
    if (!step?.session || !prog || !this.sessionSupport[`local:${prog}`]) return;
    const parentLocal = r.parent && !machineOf(r.parent) ? r.parent : null;
    const args = ["run", "--json", ...(r.cwd ? ["--cwd", r.cwd] : []),
      ...(parentLocal ? ["--parent", parentLocal, "--outlive-parent"] : ["--no-parent"]),
      "--", prog, "--session", step.session];
    try {
      const res = await hc(args);
      const address = JSON.parse(String(res.stdout).trim().split("\n").pop())?.address;
      if (!address) throw new Error(res.stderr || "no address");
      this.attach(address, `${step.agent} ${r.short}`, cx);
    } catch (e) {
      notify({ title: "Couldn't open the child session", body: String(e?.message ?? e).slice(0, 160), level: "error", timeout: 4000 });
    }
  }

  childTitle(k) {
    const raw = k?.name || (k?.address ? sessionTitleOf(k.address) : null) || k?.title;
    return cleanTitle(raw) || k?.program?.name || k?.address || "terminal";
  }

  // Attach: a popup with a live hc child terminal (local or remote), typeable. Nothing enters the main window.
  // A terminal not live yet is looked for again a few ticks later (with cx); then a notice says why not.
  attach(address, title, cx = null, tries = 0) {
    const t = terminals().find((x) => x.address === address);
    const step = attachStep(address, t, tries, Boolean(cx));
    if (step.do === "retry") {
      try { cx.timer.after(ATTACH_WAIT, (cx) => this.attach(address, title, cx, tries + 1)); return; } catch { step.do = "fail"; step.why = `No live terminal ${address}`; }
    }
    if (step.do === "fail") { this.notice("Couldn't attach", step.why, "error"); return; }
    const pAddr = parentAddr(t);
    const parent = pAddr ? sessionOf(pAddr) : null;
    const mainSess = placedSessionOf(address);
    openAttach({
      terminal: address,
      title: title ?? this.childTitle(t),
      parent: parent?.label ?? pAddr ?? null,
      machine: machineOf(address),
      mainTerminal: mainSess?.address ?? null,
      mainTab: mainSess?.label ?? null,
    });
  }

  bookmark(r) { toggleBookmark({ kind: "run", id: r.key, label: runTitle(r), machine: r.machine }); }

  menu(key, cx) {
    if (String(key ?? "").startsWith("h:")) {
      const addr = String(key).slice(2);
      const k = terminals().find((x) => x.address === addr);
      if (k) this.childMenu(k, this.childTitle(k), attachPlan({ kind: "terminal", address: addr, state: k.state }), provider.session(addr)?.transcript ?? null);
      return;
    }
    const r = this.runOf(key);
    if (r) {
      const step = currentStep(r);
      const prog = provider.of(r)?.id;
      const canOpen = Boolean(step?.session) && !r.machine && Boolean(prog && this.sessionSupport[`local:${prog}`]);
      const mainSess = r.parent ? placedSessionOf(r.parent) : null;
      const toMain = Boolean(mainSess && mainSess.address !== r.parent);
      openMenu([
        { label: this.open.has(key) ? "Collapse" : "Expand", icon: this.open.has(key) ? "chevron-up" : "chevron-down", command: `ob-outline.${this.open.has(key) ? "collapse" : "expand"}:${key}` },
        { label: "Follow log", icon: "scroll", command: `ob-outline.log:${key}`, disabled: !r.log },
        { label: "Transcript", icon: "file-text", command: `ob-outline.transcript:${key}`, disabled: !r.steps.some(stepTranscript) },
        { label: "Open child session", icon: "play", command: `ob-outline.open-session:${key}`, disabled: !canOpen, hint: canOpen ? "popup" : null },
        { separator: true },
        ...(r.parent ? [{ label: toMain ? "Go to main tab" : "Go to parent session", icon: "locate", command: `ob-outline.reveal-session:${r.parent}`, hint: toMain ? mainSess.label : null },
          { label: "Show parent's properties", icon: "info", command: `ob-tabs.open:ob-props@term:${r.parent}` }] : []),
        { label: "Copy run id", icon: "copy", copy: r.id },
        ...(r.dir ? [{ label: "Copy run folder", icon: "folder", copy: r.dir }] : []),
        { label: isBookmarked("run", r.key) ? "Remove bookmark" : "Bookmark", icon: "bookmark", command: `ob-outline.bookmark:${key}` },
      ], { width: 240, title: `${runTitle(r)} · ${r.short}` });
      return;
    }
    const c = this.agentOf(key);
    if (c) {
      const mainSess = c.parent ? placedSessionOf(c.parent) : null;
      const toMain = Boolean(mainSess && mainSess.address !== c.parent);
      const showTx = Boolean(c.transcript || (c.id && (!c.type || (provider.of(c) ?? provider.of(c.type))?.can("transcript"))));
      openMenu([
        ...(showTx ? [{ label: "Transcript", icon: "file-text", command: `ob-outline.transcript:${key}` }] : []),
        { label: "Attach", icon: "terminal", disabled: true, hint: "no terminal" },
        ...(c.parent ? [{ label: toMain ? "Go to main tab" : "Go to parent session", icon: "locate", command: `ob-outline.reveal-session:${c.parent}`, hint: toMain ? mainSess.label : null },
          { label: "Show parent's properties", icon: "info", command: `ob-tabs.open:ob-props@term:${c.parent}` }] : []),
        { separator: true },
        { label: "Copy agent id", icon: "copy", copy: c.id },
        ...(c.transcript ? [{ label: "Copy transcript path", icon: "copy", copy: c.transcript }] : []),
      ], { width: 240, title: c.desc || c.type || provider.of(c)?.noun || c.id });
    }
  }

  async command(c, cx) {
    const [verb, arg] = splitCmd(c);
    switch (verb) {
      case "focus": this.handle.focus(); break;
      case "next": this.move(1); break;
      case "prev": this.move(-1); break;
      case "open": if (this.cursor) this.click(this.cursor, cx); break;
      case "expand": this.toggle(arg, true); this.reveal(arg); break;
      case "collapse": this.toggle(arg, false); break;
      case "live-only": this.liveOnly = arg !== "off"; this.persist(); break;
      case "scope": this.scope = arg === "all" ? "all" : "tab"; this.persist(); break;
      case "machine": this.machine = !arg || arg === "all" ? null : arg; this.persist(); break;
      case "log": this.follow(this.runOf(arg)); break;
      case "transcript": await this.transcript(arg); break;
      case "open-session": await this.openSession(arg, cx); break;
      case "attach": this.attach(arg, undefined, cx); break;
      case "reveal-session": revealTerminal(arg); break;
      case "copy-id": { const r = this.runOf(arg) ?? this.agentOf(arg); if (r) copied(cx, r.short ? "run id" : "agent id", r.id); break; }
      case "bookmark": { const r = this.runOf(arg); if (r) this.bookmark(r); break; }
      case "menu": this.menu(arg, cx); break;
      case "inspect": inspect(arg || null); this.persist(); break;
      case "unpin": inspect(null); break;
      case "refresh": run("ob-feed.refresh"); break;
      case "down": case "up": this.move(verb === "down" ? 1 : -1); break;
      case "enter": if (this.cursor) this.click(this.cursor, cx); break;
      default: break;
    }
  }

  // Router intents (ob-tabs.open:ob-outline@<intent>).
  intent(intent) {
    if (!intent) return;
    if (intent.startsWith("run:")) {
      const key = intent.slice(4);
      const r = this.runOf(key), c = r ? null : this.agentOf(key);
      const parent = r?.parent ?? c?.parent ?? null;
      if (parent !== inspected().address) this.scope = "all";
      const mk = r ? (r.machine ?? "local") : c ? (c.machine ?? "local") : null;
      if (mk && this.machine && this.machine !== mk) this.machine = null;
      if (this.liveOnly && r && !r.live) this.liveOnly = false;
      this.open.add(key);
      this.persist();
      this.reveal(key);
    } else if (intent.startsWith("term:")) {
      const addr = intent.slice(5);
      const f = focused();
      const sp = spaces(), ps = panes();
      const curSpace = sp.find((x) => x.id === f?.space) ?? sp.find((x) => x.active) ?? sp[0] ?? null;
      const curTab = curSpace?.tabs?.find((x) => x.id === f?.tab) ?? curSpace?.tabs?.find((x) => x.active) ?? curSpace?.tabs?.[0] ?? null;
      const inTab = Boolean(curTab && ps.some((p) => p.tab === curTab.id && p.terminal === addr));
      if (inTab) {
        inspect(addr);
        this.scope = "tab";
      } else {
        const mainSess = placedSessionOf(addr, ps, sp);
        if (mainSess && curTab && mainSess.tab?.id === curTab.id) {
          this.scope = "tab";
          this.reveal(`h:${addr}`);
        } else {
          this.scope = "all";
          const rootAddr = mainSess?.address ?? addr;
          const mk = machineOf(rootAddr) ?? "local";
          const key = `p:${mk}:${rootAddr}`;
          this.folded.delete(`m:${mk}`);
          this.folded.delete(key);
          this.reveal(mainSess && mainSess.address !== addr ? `h:${addr}` : key);
        }
      }
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
  kidActive(k) {
    const s = normStatus(typeof k?.status === "string" ? k.status : k?.status?.state);
    return s === "working" || s === "blocked";
  }

  // Items of one parent (or of "no parent" on a machine): runs, sub-agents, hc children.
  build() {
    const f = feed();
    const merged = this.allSubagents();
    const runs = merged.runs.filter((r) => !this.liveOnly || r.live);
    const agents = merged.agents.filter((c) => !this.liveOnly || c.live);
    const ts = terminals();
    const allKids = listedTerminals(ts, panes());
    const parents = parentMap(ts);
    const kids = this.liveOnly ? keepLiveAncestors(allKids, { runs, agents }, (k) => this.kidActive(k), parents) : allKids;
    return { f, runs, agents, kids, parents };
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

  // opts.disabled: dimmed (nothing recorded yet); a click still runs onClick, which says why.
  actionButton(t, id, ic, label, tip, onClick, opts = {}) {
    const narrow = this.w > 0 && this.w < 330;
    return h_flex().id(id).h(24).px(narrow ? 5 : 8).gap(5).flex_none().items_center().rounded(S.radius).cursor_pointer()
      .border_1().border_color(t.input).text_size(S.textXs).text_color(opts.active ? t.accent : opts.disabled ? t.dim : t.muted)
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
    const prog = provider.of(r)?.id;
    if (open && prog) this.needSession.add(`${r.machine ?? "local"}\u0000${prog}`);
    const canOpen = Boolean(step?.session) && !r.machine && Boolean(prog && this.sessionSupport[`local:${prog}`]);
    const anyTx = r.steps.some(stepTranscript);
    return v_flex().id(id).relative().flex_none().ml(S.pad + depth * 10).mr(S.pad).mb(6).rounded(S.radiusLg).overflow_hidden()
      .border_1().border_color(cur ? alpha(t.accent, 0.7) : live ? alpha(t.working, 0.45) : t.border)
      .when(live, (e) => e.bg(t.background))
      .when(open && !live, (e) => e.bg(alpha(t.background, 0.55)))
      .child(v_flex().id(`${id}-head`).pl(live ? 10 : 9).pr(8).py(6).gap(2).cursor_pointer().hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => this.click(r.key, cx, r.pending))
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
          .child(this.actionButton(t, `${id}-tx`, "file-text", "Transcript", anyTx ? "Read the transcript of the current step" : "No transcript recorded for this run yet", () => this.transcript(r.key), { disabled: !anyTx }))
          .child(this.actionButton(t, `${id}-copy`, "copy", "Copy id", `Copy run id ${r.id}`, (_e, cx) => copied(cx, "run id", r.id)))
          .when(canOpen, (x) => x.child(this.actionButton(t, `${id}-open`, "play", "Open session", "Open this step's child session in a popup, a new terminal shown there", (_e, cx) => this.openSession(r.key, cx))))
          .child(this.actionButton(t, `${id}-bm`, isBookmarked("run", r.key) ? "bookmark" : "bookmark-plus", isBookmarked("run", r.key) ? "Bookmarked" : "Bookmark", "Bookmark this run", () => this.bookmark(r), { active: isBookmarked("run", r.key) }))
          .child(div().flex_1())
          .child(div().flex_none().font_family(MONO).text_size(10.5).text_color(t.dim).child(r.short)))));
  }

  agentCard(t, c, depth) {
    const open = this.open.has(c.key);
    const cur = this.cursor === c.key;
    const id = `cl-${c.key}`;
    const meta = [c.type, shortModel(c.model), c.toolCount ? `${c.toolCount} tool${c.toolCount === 1 ? "" : "s"}` : null, c.outTokens ? `${fmtTokens(c.outTokens)} out` : null, c.updatedAt ? `${ago(c.updatedAt)}${ago(c.updatedAt) === "now" ? "" : " ago"}` : null].filter(Boolean).join(" · ");
    const tool = c.lastTool ? `${c.lastTool.tool ?? ""} ${c.lastTool.args ?? ""}`.trim() : null;
    const st = c.live ? (c.state === "blocked" ? "blocked" : "working") : "ok";
    const showTx = Boolean(c.transcript || (c.id && (!c.type || (provider.of(c) ?? provider.of(c.type))?.can("transcript"))));
    const shortId = String(c.id ?? "").split("/").pop().slice(0, 8);
    return v_flex().id(id).relative().flex_none().ml(S.pad + depth * 10).mr(S.pad).mb(6).rounded(S.radiusLg).overflow_hidden()
      .border_1().border_color(cur ? alpha(t.accent, 0.7) : c.live ? alpha(t.working, 0.45) : t.border)
      .when(c.live, (e) => e.bg(t.background))
      .child(v_flex().id(`${id}-head`).pl(c.live ? 10 : 9).pr(8).py(6).gap(2).cursor_pointer().hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => this.click(c.key, cx))
        .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.cursor = c.key; this.menu(c.key, cx); })
        .child(h_flex().h(18).gap(6).items_center()
          .child(statusMark(st, 12))
          .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.text).font_medium().text_color(c.live || open ? t.foreground : t.muted).child(c.desc || c.type || provider.of(c)?.noun || c.id))
          .child(div().flex_1().min_w(4))
          .child(icon("bot", S.iconXs, t.dim)))
        .when(Boolean(meta), (e) => e.child(div().truncate().text_size(S.textXs).text_color(t.dim).child(meta)))
        .when(Boolean(tool) && (c.live || open), (e) => e.child(h_flex().gap(5).min_w(0).font_family(MONO).text_size(11)
          .child(div().flex_none().text_color(c.live ? t.working : t.dim).child("▸")).child(div().flex_1().min_w(0).truncate().text_color(t.muted).child(tool)))))
      .when(c.live, (e) => e.child(div().absolute().left(0).top(0).bottom(0).w(2).bg(t.working)))
      .when(open, (e) => e.child(h_flex().px(9).pb(8).pt(2).gap(5).flex_wrap()
        .when(showTx, (x) => x.child(this.actionButton(t, `${id}-tx`, "file-text", "Transcript", "Read this agent's transcript", () => this.transcript(c.key))))
        .child(this.actionButton(t, `${id}-copy`, "copy", "Copy id", `Copy agent id ${c.id}`, (_e, cx) => copied(cx, "agent id", c.id)))
        .child(div().flex_1())
        .child(div().flex_none().font_family(MONO).text_size(10.5).text_color(t.dim).child(shortId))));
  }

  childMenu(k, name, plan, tx) {
    const pAddr = parentAddr(k);
    const mainSess = placedSessionOf(k.address);
    const navTarget = pAddr ?? mainSess?.address ?? null;
    const toMain = Boolean(mainSess && mainSess.address !== pAddr);
    openMenu([
      plan.show ? { label: "Attach", icon: "terminal", command: plan.enabled ? `ob-outline.attach:${k.address}` : undefined, disabled: !plan.enabled } : null,
      tx ? { label: "Transcript", icon: "file-text", command: `ob-outline.transcript:h:${k.address}` } : null,
      { label: "Peek", icon: "eye", command: "terminal.peek", args: { terminal: k.address } },
      navTarget ? { label: toMain ? "Go to main tab" : "Go to parent session", icon: "locate", command: `ob-outline.reveal-session:${navTarget}`, hint: toMain ? mainSess.label : null } : null,
      pAddr ? { label: "Show parent's properties", icon: "info", command: `ob-tabs.open:ob-props@term:${pAddr}` } : null,
      { separator: true },
      { label: "Copy address", icon: "copy", copy: k.address },
    ].filter(Boolean), { width: 230, title: name });
  }

  childRow(t, k, depth, rootAddr = null) {
    const st = normStatus(typeof k.status === "string" ? k.status : k.status?.state ?? null);
    const name = this.childTitle(k);
    const slug = cleanTitle(k.name);
    const showSlug = Boolean(slug && slug !== name);
    const mainSess = this.scope === "all" ? placedSessionOf(k.address) : null;
    const showGo = Boolean(mainSess && mainSess.address !== rootAddr);
    const sess = provider.session(k.address);
    const tx = sess?.transcript ?? null;
    const last = sess?.lastTool;
    const tool = st === "working" && last ? `${last.tool ?? ""} ${last.args ?? ""}`.trim() || null : null;
    const active = st === "working" || st === "blocked";
    const plan = attachPlan({ kind: "terminal", address: k.address, state: k.state });
    return treeRow({
      id: `hc-${k.address}`, depth, height: S.rowSm, selected: false, cursor: this.cursor === `h:${k.address}`,
      lead: h_flex().gap(5).items_center().child(statusMark(st, 11)).child(programIcon(k.program, S.iconXs)),
      label: name, dim: !active,
      after: [
        !this.compact() ? (tool
          ? div().min_w(0).flex_shrink(2).truncate().text_size(S.textXs).text_color(t.muted).child(`· ${tool}`)
          : div().flex_none().text_size(S.textXs).text_color(t.dim).child(showSlug ? slug : k.address)) : null,
      ],
      right: [
        showGo ? iconButton({ id: `hc-${k.address}-go`, icon: "locate", size: 22, iconSize: 12, tip: `Go to main tab (${mainSess.label})`, onClick: () => revealTerminal(k.address) }) : null,
        tx ? iconButton({ id: `hc-${k.address}-tx`, icon: "file-text", size: 22, iconSize: 12, tip: "Read this terminal's transcript", onClick: () => this.transcript(`h:${k.address}`) }) : null,
        plan.show ? this.actionButton(t, `hc-${k.address}-attach`, "terminal", "Attach", plan.tip, (_e, cx) => this.attach(k.address, name, cx), { disabled: !plan.enabled }) : null,
      ],
      onClick: (_e, cx) => { this.cursor = `h:${k.address}`; this.attach(k.address, name, cx); cx.notify(); },
      onRight: () => this.childMenu(k, name, plan, tx),
    });
  }

  parentRow(t, key, s, counts) {
    const unattached = !s;
    const hasItems = counts.total > 0;
    const st = unattached ? null : normStatus(s.status);
    const active = st === "working" || st === "blocked" || counts.live > 0;
    const mainSess = !unattached && !s.pane ? placedSessionOf(s.address) : null;
    return treeRow({
      id: `par-${key}`, depth: 0, chevron: hasItems ? !this.folded.has(key) : undefined,
      onToggle: hasItems ? (_e, cx) => { this.folded.has(key) ? this.folded.delete(key) : this.folded.add(key); this.persist(); cx.notify(); } : undefined,
      lead: unattached ? icon("layers", S.iconSm, t.dim) : h_flex().gap(5).items_center().child(statusMark(s.status, 11)).child(programIcon(s.program, S.iconSm)),
      label: unattached ? "Unattached" : s.label, bold: !unattached && active, dim: unattached || !active,
      after: [
        !unattached && !this.compact() ? div().flex_none().text_size(S.textXs).text_color(t.dim).child(s.address) : null,
        mainSess && !this.compact() ? div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(`→ ${mainSess.label}`) : null,
      ],
      right: [
        mainSess ? iconButton({ id: `par-${key}-go`, icon: "locate", size: 22, iconSize: 12, tip: `Go to main tab (${mainSess.label})`, onClick: () => revealTerminal(s.address) }) : null,
        counts.live ? badge(`${counts.live} live`, "working") : null,
        !counts.live && counts.total ? div().text_size(S.textXs).text_color(t.dim).child(String(counts.total)) : null,
      ],
      onClick: unattached ? (_e, cx) => { this.folded.has(key) ? this.folded.delete(key) : this.folded.add(key); this.persist(); cx.notify(); } : () => revealTerminal(s.address),
      onRight: unattached ? null : () => openMenu([
        { label: mainSess ? "Go to main tab" : "Go to session", icon: "locate", command: `ob-outline.reveal-session:${s.address}`, hint: mainSess?.label ?? null },
        { label: "Show only this session", icon: "filter", command: `ob-outline.inspect:${s.address}` },
        { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${s.address}` },
        { label: "Copy address", icon: "copy", copy: s.address },
      ], { width: 230, title: s.label }),
    });
  }

  renderSubtree(t, rows, sub, depth, rootAddr = null) {
    const sorted = [
      ...(sub.runs ?? []).map((r) => ({ live: r.live, at: r.lastUpdate ?? 0, el: () => this.runCard(t, r, depth), key: r.key })),
      ...(sub.agents ?? []).map((c) => ({ live: c.live, at: c.updatedAt ?? Date.now(), el: () => this.agentCard(t, c, depth), key: c.key })),
    ].sort((a, b) => (b.live - a.live) || (b.at - a.at));
    for (const x of sorted) rows.push([x.key, x.el()]);
    for (const k of sub.kids ?? []) {
      rows.push([`h:${k.address}`, this.childRow(t, k, depth + 1, rootAddr)]);
      if (k.sub && (k.sub.runs.length || k.sub.agents.length || k.sub.kids.length)) {
        this.renderSubtree(t, rows, k.sub, depth + 1, rootAddr);
      }
    }
  }

  // Rows for one parent's items. Pushes [key, element] pairs.
  items(t, rows, runs, agents, kids, depth, rootAddr = null) {
    this.renderSubtree(t, rows, nestItems({ runs, agents, kids }), depth, rootAddr);
  }

  toolbar(t, pinned) {
    const seg = (id, label, on, onClick) => h_flex().id(id).h(22).px(this.compact() ? 6 : 9).items_center().rounded(S.radius).cursor_pointer()
      .text_size(S.textXs).font_medium().text_color(on ? t.foreground : t.dim).when(on, (e) => e.bg(t.selected))
      .when(!on, (e) => e.hover((s) => s.bg(t.hover).text_color(t.muted)))
      .on_click((_e, cx) => { onClick(); this.persist(); cx.notify(); }).child(label);
    const ms = machines().map((m) => m.name ?? null);
    return h_flex().id("tb").h(S.toolbar).flex_none().px(S.pad).gap(4).items_center()
      .child(h_flex().p(2).gap(2).rounded(S.radiusLg).bg(alpha(t.raised, 0.7)).border_1().border_color(t.border)
        .child(seg("seg-tab", this.compact() ? "Tab" : "This tab", this.scope === "tab", () => { this.scope = "tab"; }))
        .child(seg("seg-all", "All", this.scope === "all", () => { this.scope = "all"; })))
      .child(div().flex_1())
      .when(pinned, (e) => e.child(iconButton({ id: "unpin", icon: "pin", active: true, tip: "Showing a pinned session. Click: follow the focused one", onClick: () => inspect(null) })))
      .child(iconButton({ id: "live-only", icon: "zap", active: this.liveOnly, tip: this.liveOnly ? "Live only (click: show finished too)" : "Show live only", onClick: (_e, cx) => { this.liveOnly = !this.liveOnly; this.persist(); cx.notify(); } }))
      .child(iconButton({ id: "machines", icon: "filter", active: this.machine != null, tip: this.machine ? `Only ${machineLabel(this.machine === "local" ? null : this.machine)}` : "Filter by machine",
        onClick: () => openMenu([
          { label: "All machines", checked: this.machine == null, command: "ob-outline.machine:all" },
          { separator: true },
          ...ms.map((m) => ({ label: machineLabel(m), icon: m ? "server" : "monitor", checked: this.machine === (m ?? "local"), command: `ob-outline.machine:${m ?? "local"}` })),
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

  // The active tab's panes, each followed by the agents that run in its terminal.
  // The machine filter applies here as in "All".
  tabView(t, rows, data0) {
    const data = onMachine(data0, this.machine);
    const f = focused();
    const sp = spaces(), ps = panes();
    const curSpace = sp.find((x) => x.id === f?.space) ?? sp.find((x) => x.active) ?? sp[0] ?? null;
    const curTab = curSpace?.tabs?.find((x) => x.id === f?.tab) ?? curSpace?.tabs?.find((x) => x.active) ?? curSpace?.tabs?.[0] ?? null;
    const tabPanes = curTab ? ps.filter((p) => p.tab === curTab.id) : [];
    const { address: pinnedAddr, pinned } = inspected();
    const pinnedInTab = Boolean(pinned && pinnedAddr && tabPanes.some((p) => p.terminal === pinnedAddr));
    this.pinnedInTab = pinnedInTab;
    const shownPanes = pinnedInTab ? tabPanes.filter((p) => p.terminal === pinnedAddr) : tabPanes;
    if (!shownPanes.length) {
      return { empty: emptyState({ icon: "list", title: "No panes in active tab", body: "Panes and the agents running in them show up here." }) };
    }
    rows.push(["hdr:tab", sectionHeader({ id: `tab-sec-${curTab.id}`, title: `${curSpace?.name ?? "Space"} / ${tabLabel(curTab, ps)}`.toUpperCase(), count: shownPanes.length, open: true })]);
    const tree = paneAgents(shownPanes, data, { parents: data.parents });
    let live = 0;
    shownPanes.forEach((p, i) => {
      const g = tree.groups[i];
      const addr = p.terminal ?? null;
      live += liveCount(g, (k) => this.kidActive(k));
      rows.push([`pane:${p.pane}`, this.paneRow(t, p, Boolean(pinned) && pinnedAddr === addr && addr != null, curTab.named ? tabLabel(curTab, ps) : "")]);
      this.items(t, rows, g.runs, g.agents, g.kids, 1);
    });
    return { live };
  }

  // One pane of the tab: its title, cwd, branch and status. Click focuses it; right-click pins its agents.
  paneRow(t, p, pinnedHere, tabName) {
    const f = focused();
    const key = `pane:${p.pane}`;
    const isSelected = p.focused || p.pane === f?.pane;
    const pTitle = paneLabelOf(p, tabName);
    const cwdStr = tilde(p.cwd);
    const after = [];
    if (p.branch && !this.compact()) after.push(h_flex().flex_none().gap(3).items_center().text_size(10).text_color(t.dim).child(icon("git-branch", 10, t.dim)).child(p.branch));
    if (cwdStr && this.w >= 240) after.push(div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(cwdStr));
    const right = [];
    if (p.zoomed) right.push(icon("maximize", S.iconXs, t.accent));
    if (p.status && p.status !== "idle") right.push(statusMark(p.status, S.iconSm));
    if (pinnedHere) right.push(icon("pin", S.iconXs, t.accent));
    const lead = p.program ? programIcon(p.program, S.iconSm, t.muted) : icon(p.terminal ? "terminal" : "file-text", S.iconSm, t.muted);
    return treeRow({
      id: `pane-row-${p.pane}`, depth: 0, selected: isSelected, cursor: this.cursor === key, lead, label: pTitle,
      labelColor: isSelected ? t.foreground : t.muted,
      after: after.length ? after : undefined, right: right.length ? right : undefined,
      onClick: (_e, cx) => { this.click(key, cx); },
      onRight: p.terminal ? () => openMenu([
        pinnedHere ? { label: "Unpin", icon: "pin-off", command: "ob-outline.unpin" } : { label: "Show only this pane's agents", icon: "pin", command: `ob-outline.inspect:${p.terminal}` },
        { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${p.terminal}` },
        { separator: true },
        detachItem(p.terminal),
      ], { width: 230, title: pTitle }) : null,
    });
  }

  focusPane(paneId) {
    if (!paneId) return;
    run("pane.focus", { pane: paneId });
  }

  allView(t, rows, data) {
    this.pinnedInTab = false;
    const f = data.f;
    const order = [null, ...machines().map((m) => m.name ?? null).filter((m) => m !== null)];
    for (const k of Object.keys(f?.machines ?? {})) { const m = k === "local" ? null : k; if (!order.includes(m)) order.push(m); }
    const ps = panes(), sp = spaces();
    let shown = 0;
    for (const m of order) {
      const mk = m ?? "local";
      if (this.machine && this.machine !== mk) continue;
      const runs = data.runs.filter((r) => (r.machine ?? null) === m);
      const agents = data.agents.filter((c) => (c.machine ?? null) === m);
      const kids = data.kids.filter((k) => machineOf(k.address) === m);
      const sessions = new Map();
      const sess = (a) => { if (!sessions.has(a)) sessions.set(a, sessionOf(a, ps, sp)); return sessions.get(a); };
      const isOn = (a) => { const st = normStatus(sess(a)?.status); return st === "working" || st === "blocked"; };
      const placed = ps.filter((p) => p?.terminal && machineOf(p.terminal) === m)
        .map((p) => ({ address: p.terminal, active: isOn(p.terminal), at: provider.session(p.terminal)?.updatedAt ?? Number(sess(p.terminal)?.term?.status_ms ?? sess(p.terminal)?.term?.created_ms ?? 0) }));
      // Active sessions and children first, then by newest activity, Unattached last.
      const list = sessionGroups(placed, { runs, agents, kids }, { kidActive: (k) => this.kidActive(k), sessionActive: isOn, liveOnly: this.liveOnly, parents: data.parents });
      const n = list.length;
      const st = f?.machines?.[mk];
      if (!n && !(st && !st.ok)) continue;
      shown += n;
      const live = list.filter(([, x]) => x.sessActive || x.live > 0).length;
      rows.push([`m:${mk}`, this.machineHeader(t, mk, f, n, live)]);
      if (this.folded.has(`m:${mk}`)) continue;
      for (const [p, x] of list) {
        const key = `p:${mk}:${p ?? "-"}`;
        const s = p ? sess(p) : null;
        rows.push([key, this.parentRow(t, key, p ? s : null, { live: x.live, total: x.runs.length + x.agents.length + x.kids.length })]);
        if (this.folded.has(key)) continue;
        this.items(t, rows, x.runs, x.agents, x.kids, 0, p);
      }
    }
    if (!shown && !rows.length) {
      return { empty: emptyState({ icon: this.liveOnly ? "zap" : "subagents", title: this.liveOnly ? "Nothing running" : f ? "No sub-agents" : "Scanning machines…",
        body: this.liveOnly ? "No run, sub-agent or child terminal is working right now." : f ? "Background runs from the last 48 h, sub-agents and child terminals of every machine show up here." : "Reading runs and sub-agents on every machine.",
        action: this.liveOnly ? { id: "show-finished", label: "Show finished too", onClick: (_e, cx) => { this.liveOnly = false; this.persist(); cx.notify(); } } : null }) };
    }
    return {};
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-outline", this.handle, (_cx, intent) => this.intent(intent));
    const data = this.build();
    const rows = [];
    this.needSession = new Set();
    const res = this.scope === "all" ? this.allView(t, rows, data) : this.tabView(t, rows, data);
    this.index = new Map(rows.map(([k], i) => [k, i]));
    this.order = rows.map(([k]) => k).filter((k) => this.runOf(k) || this.agentOf(k) || k.startsWith("h:") || k.startsWith("pane:"));
    if (this.pendingScroll && this.index.has(this.pendingScroll)) {
      this.scroll.scroll_to_item(this.index.get(this.pendingScroll));
      this.pendingScroll = null;
    }
    const need = [...this.needSession].filter((pair) => {
      const [mk, prog] = pair.split("\u0000");
      return !(`${mk}:${prog}` in this.sessionSupport);
    });
    this.needSession.clear();
    if (need.length) cx.timer.after(0, (cx) => {
      for (const pair of need) {
        const [mk, prog] = pair.split("\u0000");
        this.checkSessionSupport(mk === "local" ? null : mk, prog, cx);
      }
    });
    const pinned = this.scope === "tab" && Boolean(this.pinnedInTab);
    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .on_key_down((e, cx) => {
        if (e.key === "down" || e.key === "j") this.move(1);
        else if (e.key === "up" || e.key === "k") this.move(-1);
        else if ((e.key === "enter" || e.key === "space") && this.cursor) {
          if (this.cursor.startsWith("h:")) this.attach(this.cursor.slice(2), undefined, cx); else this.click(this.cursor, cx);
        } else if (e.key === "l" && this.cursor) this.follow(this.runOf(this.cursor));
        else if (e.key === "t" && this.cursor) this.transcript(this.cursor);
        else if (e.key === "escape") { this.cursor = null; const f = focused(); if (f?.pane) run("pane.focus", { pane: f.pane }); }
        else return;
        cx.stop_propagation();
        cx.notify();
      })
      .child(this.toolbar(t, pinned))
      .child(div().h(1).flex_none().bg(t.border))
      .when(Boolean(feedLine(feed()?.at)), (e) => e.child(div().id("feed-paused").px(S.pad).py(3).text_size(S.textXs).text_color(t.dim).child(feedLine(feed()?.at))))
      .child(div().id("list-wrap").relative().flex_1().min_h(0)
        .child(v_flex().id("list").size_full().pt(4).overflow_y_scroll().track_scroll(this.scroll)
          .children(rows.map(([, el]) => el))
          .when(Boolean(res.empty), (e) => e.child(res.empty))
          .child(div().id("list-end").h(8).flex_none()))
        .child(Scrollbar.vertical("list").absolute().inset_0()));
  }
}

export default class Outline extends View {
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
        } catch (e) { notify({ title: `Couldn't do ${c.split(":")[0]}`, body: String(e?.message ?? e).slice(0, 160), level: "error", timeout: 4000 }); }
        cx.notify();
      }
    });
  }
  render(cx) { return this.view.render(cx); }
}
