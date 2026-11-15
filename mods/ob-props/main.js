// ob-props: Obsidian's Properties for a session (SPEC 8.C3). Target: ob.inspect's terminal while pinned, else the
// last focused main pane that holds a terminal (kit/follow_target.js); before any, the focused mod pane (pane facts only).
// Sections: Session, Location, Process, Labels, Relations, Usage, Session file. Usage reads the followed agent's
// transcript with usage.py (exec, off the UI path) on target change and every 10 s; usage.js does the arithmetic. Key column 96 px; hover a
// row for its copy button. `hc get <addr> --json` adds what terminals() lacks (status time, exit,
// notify), on target change and every 10 s while the view shows.
// Commands (ob-props.<cmd>): inspect:<address>, unpin, pin (pin the focused session), copy:<field>
//   (address, cwd, pid, argv, title, session, transcript, branch, pane, space, tab, machine, parent),
//   transcript (open the session file in the viewer), fold:<section>, refresh, focus.
// Router intent: term:<address> (= inspect).

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { props, run, nextCommand, settings, hc, layout, focused, panes, spaces, shared, exec, readTextFile, appHome } from "herdr";
import {
  S, tc, alpha, icon, iconButton, badge, statusMark, normStatus, sectionHeader, emptyState, programIcon, feed,
  machineLabel, machineOf, ago, dur, tilde, takeFocus, isShown, openView, subagentCounts, feedLine,
} from "./kit.js";
import { summarize, usageLines, subagentsLine } from "./usage.js";
import { MONO, splitCmd, sessionOf, inspected, inspect, revealTerminal, claudeAll, hcChildren, openViewer, copied } from "./obc.js";

const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* keep in memory */ } };
const WORD = { working: "Working", blocked: "Needs you", done: "Finished", idle: "Idle" };

export default class Props extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.folded = new Set(load("folded", []));
    this.extra = {};      // address -> hc get (without screen)
    this.busy = new Set();
    this.hover = null;
    this.w = 0;
    this.lastTarget = null;
    this.usage = {};      // address -> { summary, format, truncated, size, error, at }
    this.usageBusy = new Set();
    cx.timer.every(10000, (cx) => { if (this.target() && isShown(layout(), props()?.slot ?? "ob-props")) { this.fetch(this.target(), cx); this.fetchUsage(this.target(), cx); } });
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-props: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  target() { return inspected().address; }

  fetch(addr, cx) {
    if (!addr || this.busy.has(addr)) return;
    this.busy.add(addr);
    cx.spawn(async (cx) => {
      try {
        const r = await hc(["get", addr, "--json"]);
        if (r.code === 0) {
          const d = JSON.parse(r.stdout);
          delete d.screen;
          this.extra[addr] = { ...d, at: Date.now() };
        } else this.extra[addr] = { error: (r.stderr || r.stdout || "").trim().split("\n").pop(), at: Date.now() };
      } catch (e) { this.extra[addr] = { error: String(e?.message ?? e), at: Date.now() }; }
      this.busy.delete(addr);
      cx.notify();
    });
  }

  // The followed agent's token usage: usage.py over its transcript (exec, time-boxed), summed by usage.js.
  // Only a Claude Code or pi session has a transcript; a plain shell has none and gets no section.
  fetchUsage(addr, cx) {
    const path = this.transcriptOf(addr);
    if (!path || this.usageBusy.has(addr)) return;
    this.usageBusy.add(addr);
    cx.spawn(async (cx) => {
      const machine = machineOf(addr);
      try {
        // Read once: it is the same file every 10 s (a missing one is looked for again next time).
        this.usageScript ||= await readTextFile(`${appHome()}/mods/ob-props/usage.py`);
        const script = this.usageScript;
        if (!script) throw new Error("usage.py is missing");
        const r = await exec("python3", ["-c", script, path], { ...(machine ? { on: machine } : {}), timeout: 8000 });
        const line = String(r.stdout ?? "").trim().split("\n").pop() ?? "";
        if (!line.startsWith("{")) throw new Error((r.stderr || `python3 exited ${r.code}`).trim().split("\n").pop());
        const d = JSON.parse(line);
        this.usage[addr] = { summary: summarize(d.turns), format: d.format, truncated: Boolean(d.truncated), size: d.size, error: d.error ?? null, at: Date.now() };
      } catch (e) {
        this.usage[addr] = { summary: null, error: String(e?.message ?? e).slice(0, 200), at: Date.now() };
      }
      this.usageBusy.delete(addr);
      cx.notify();
    });
  }

  // The session file the feed knows for a terminal (Claude Code: transcript; pi: its session file), or null.
  transcriptOf(addr) {
    const term = feed()?.terms?.[addr];
    if (!term) return null;
    return term.transcript ?? (term.kind === "pi" ? term.session : null) ?? null;
  }

  // The value of a copyable field for the current target.
  field(name) {
    const a = this.target();
    const s = sessionOf(a);
    const x = this.extra[a] ?? {};
    const term = feed()?.terms?.[a];
    const v = {
      address: a, cwd: s?.pane?.cwd ?? s?.term?.cwd ?? x.cwd, pid: s?.term?.foreground?.pid ?? s?.term?.pid ?? x.pid,
      argv: (s?.term?.foreground?.argv ?? s?.term?.argv ?? [])?.join(" "), title: s?.term?.title ?? x.title, session: term?.session,
      transcript: term?.transcript ?? (term?.kind === "pi" ? term?.session : null), branch: s?.pane?.branch, pane: s?.pane?.pane, space: s?.space?.id,
      tab: s?.tab?.id, machine: machineLabel(s?.machine ?? null), parent: s?.term?.parent ?? x.parent,
    }[name];
    return v == null || v === "" ? null : String(v);
  }

  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    if (verb === "inspect") inspect(arg || null);
    else if (verb === "unpin") inspect(null);
    else if (verb === "pin") { const a = focused()?.terminal; if (a) inspect(a); }
    else if (verb === "copy") { const v = this.field(arg); if (v) copied(cx, arg, v); }
    else if (verb === "transcript") this.openTranscript();
    else if (verb === "fold") { this.folded.has(arg) ? this.folded.delete(arg) : this.folded.add(arg); save("folded", [...this.folded]); }
    else if (verb === "refresh") { const a = this.target(); if (a) { this.fetch(a, cx); this.fetchUsage(a, cx); } run("ob-feed.refresh"); }
    else if (verb === "focus") this.handle.focus();
  }

  openTranscript() {
    const a = this.target();
    const term = feed()?.terms?.[a];
    const path = term?.transcript ?? (term?.kind === "pi" ? term?.session : null);
    if (!path) return;
    const s = sessionOf(a);
    openViewer({ view: "transcript", machine: machineOf(a), path, title: `${s?.label ?? a} · session`, live: s?.status === "working", key: `sess-${a}` });
  }

  // ---------------------------------------------------------------- pieces
  section(t, rows, id, title, count, body) {
    const open = !this.folded.has(id);
    rows.push(sectionHeader({ id: `sec-${id}`, title, count, open, onToggle: (_e, cx) => { open ? this.folded.add(id) : this.folded.delete(id); save("folded", [...this.folded]); cx.notify(); } }));
    if (open) for (const r of body.filter(Boolean)) rows.push(r);
  }

  // A key/value row. opts: { copy: field name or text, mono, color, lead, after, onClick, tip }
  kv(t, id, key, value, opts = {}) {
    const hover = this.hover === id;
    const copyText = opts.copy ? (this.field(opts.copy) ?? opts.copy) : null;
    const keyW = this.w > 0 && this.w < 230 ? 72 : 96;
    return h_flex().id(`kv-${id}`).h(S.row).flex_none().px(S.pad).mx(4).gap(8).items_center().rounded(S.radius)
      .on_hover((h, cx) => { if (h) this.hover = id; else if (this.hover === id) this.hover = null; cx.notify(); })
      .when(Boolean(opts.onClick), (e) => e.cursor_pointer().hover((s) => s.bg(t.hover)).on_click((ev, cx) => opts.onClick(ev, cx)))
      .when(Boolean(opts.tip), (e) => e.tooltip(opts.tip))
      .child(div().w(keyW).flex_none().truncate().text_size(S.textSm).text_color(t.dim).child(key))
      .child(h_flex().flex_1().min_w(0).gap(6).items_center()
        .when(Boolean(opts.lead), (e) => e.child(opts.lead))
        .child(div().min_w(0).flex_shrink(1).truncate().text_size(opts.mono ? 11.5 : S.textSm).when(Boolean(opts.mono), (e) => e.font_family(MONO))
          .text_color(opts.color ?? (value === "—" ? t.dim : t.foreground)).child(String(value ?? "—")))
        .children((opts.after ?? []).filter(Boolean)))
      .when(Boolean(copyText), (e) => e.child(div().w(20).flex_none().child(hover ? iconButton({ id: `cp-${id}`, icon: "copy", size: 20, iconSize: 12, tip: `Copy ${key.toLowerCase()}`, onClick: (_e, cx) => copied(cx, key.toLowerCase(), copyText) }) : div())));
  }

  chip(t, id, text) {
    return h_flex().id(id).h(20).px(6).rounded(S.radius).items_center().bg(t.raised).border_1().border_color(t.border)
      .font_family(MONO).text_size(10.5).text_color(t.muted).max_w(this.w > 0 ? Math.max(120, this.w - 30) : 320).child(div().truncate().child(text));
  }

  header(t, s, pinned) {
    return h_flex().id("phead").h(40).flex_none().px(S.pad + 4).gap(8).items_center()
      .child(s?.program ? programIcon(s.program, S.icon) : icon("info", S.icon, t.dim))
      .child(v_flex().flex_1().min_w(0)
        .child(div().truncate().text_size(S.text).font_semibold().text_color(t.foreground).child(s?.label ?? "Properties"))
        .child(div().truncate().text_size(S.textXs).text_color(t.dim).child(s ? `${machineLabel(s.machine)} · ${s.address}${pinned ? " · pinned" : ""}` : "")))
      .child(iconButton({ id: "pin", icon: "pin", active: pinned, tip: pinned ? "Pinned: click to follow the focused session again" : "Pin: keep showing this session", onClick: () => (pinned ? inspect(null) : s && inspect(s.address)) }))
      .child(iconButton({ id: "refresh", icon: "refresh", tip: "Read again", onClick: (_e, cx) => { if (s) { this.fetch(s.address, cx); this.fetchUsage(s.address, cx); } } }));
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-props", this.handle, (_cx, intent) => { if (intent?.startsWith("term:")) inspect(intent.slice(5)); });
    const { address, pinned } = inspected();
    if (address !== this.lastTarget) { this.lastTarget = address; if (address) cx.timer.after(0, (cx) => { this.fetch(address, cx); this.fetchUsage(address, cx); }); }
    const root = v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } });
    const ps = panes(), sp = spaces();
    const s = address ? sessionOf(address, ps, sp) : null;
    if (!s) {
      // A mod pane (or nothing) has the focus: pane facts only.
      const f = focused();
      const p = f?.pane ? ps.find((x) => x.pane === f.pane) : null;
      if (!p) return root.child(emptyState({ icon: "info", title: "Nothing to show", body: "Focus a pane or a session to see its properties." }));
      const space = sp.find((x) => x.id === f.space);
      const tab = space?.tabs.find((x) => x.id === p.tab);
      const rows = [];
      this.section(t, rows, "pane", "PANE", null, [
        this.kv(t, "mod", "Mod", p.mod ?? p.program?.name ?? "—", { mono: true }),
        this.kv(t, "title", "Title", p.title || "—"),
        this.kv(t, "pane", "Pane id", p.pane, { mono: true, copy: p.pane }),
        this.kv(t, "space", "Space", space?.name ?? "—"),
        this.kv(t, "tab", "Tab", tab?.name ?? "—"),
        this.kv(t, "machine", "Machine", machineLabel(space?.machine ?? null)),
      ]);
      return root.child(this.header(t, { label: p.title || p.mod || "Pane", program: p.program, machine: space?.machine ?? null, address: p.pane }, false)).child(div().h(1).bg(t.border)).child(v_flex().p(4).children(rows));
    }
    const x = this.extra[address] ?? {};
    const term = s.term ?? {};
    const fterm = feed()?.terms?.[address];
    const now = Date.now();
    const rows = [];
    const st = s.status;
    const stMs = x.status_ms ?? null;
    const rep = term.report ?? x.status ?? null;
    this.section(t, rows, "session", "SESSION", null, [
      this.kv(t, "program", "Program", s.program?.name ?? term.program?.name ?? "—", { lead: programIcon(s.program, S.iconSm) }),
      this.kv(t, "status", "Status", st ? `${WORD[st] ?? st}${stMs ? ` · ${ago(stMs, now)}${ago(stMs, now) === "now" ? "" : " ago"}` : ""}` : "No status", { lead: statusMark(st, 12), color: st ? t[normStatus(st)] ?? t.foreground : t.dim,
        after: [st === "blocked" && this.w >= 220 ? h_flex().px(6).h(18).rounded(5).bg(alpha(t.blocked, 0.15)).text_size(10.5).font_semibold().text_color(t.blocked).items_center().child("Needs you") : null] }),
      this.kv(t, "app", "Agent", rep?.app ?? s.agent?.app ?? "—"),
      term.title || x.title ? this.kv(t, "title", "Title", term.title || x.title, { copy: "title" }) : null,
      term.turn != null || x.turn != null ? this.kv(t, "turn", "Turn", String(term.turn ?? x.turn)) : null,
      rep?.msg ? this.kv(t, "msg", "Message", rep.msg) : null,
    ]);
    this.section(t, rows, "location", "LOCATION", null, [
      this.kv(t, "machine", "Machine", machineLabel(s.machine), { lead: icon(s.machine ? "server" : "monitor", S.iconSm, t.muted) }),
      this.kv(t, "space", "Space", s.space?.name ?? "—", { onClick: s.space ? () => run("space.select", { id: s.space.id }) : null, copy: s.space ? "space" : null }),
      this.kv(t, "tab", "Tab", s.tab ? s.label.split(" / ").slice(1).join(" / ") : "—", { onClick: s.tab ? () => { run("space.select", { id: s.space.id }); run("tab.select", { id: s.tab.id }); } : null }),
      this.kv(t, "pane", "Pane", s.pane?.pane ?? "no pane", { mono: Boolean(s.pane), copy: s.pane ? "pane" : null, color: s.pane ? null : t.dim }),
      this.kv(t, "cwd", "Folder", tilde(s.pane?.cwd ?? term.cwd ?? x.cwd) || "—", { copy: "cwd", tip: s.pane?.cwd ?? term.cwd ?? x.cwd ?? undefined }),
      s.pane?.branch ? this.kv(t, "branch", "Branch", s.pane.branch, { lead: icon("git-branch", S.iconSm, t.muted), copy: "branch" }) : null,
    ]);
    const fg = term.foreground ?? x.foreground;
    const created = term.created_ms ?? x.created_ms;
    this.section(t, rows, "process", "PROCESS", null, [
      this.kv(t, "address", "Address", address, { mono: true, copy: "address" }),
      this.kv(t, "pid", "PID", String(fg?.pid ?? term.pid ?? x.pid ?? "—"), { mono: true, copy: "pid", after: [fg?.name ? div().text_size(S.textXs).text_color(t.dim).child(fg.name) : null] }),
      this.kv(t, "argv", "Running", (fg?.argv ?? term.argv ?? x.argv ?? []).join(" ") || "—", { mono: true, copy: "argv" }),
      created ? this.kv(t, "created", "Started", `${ago(created, now)} ago`, { tip: new Date(created).toLocaleString() }) : null,
      created ? this.kv(t, "uptime", "Uptime", dur(now - created)) : null,
      term.identity || x.identity ? this.kv(t, "identity", "Client", term.identity ?? x.identity) : null,
      this.kv(t, "keep", "Kept", (term.keep ?? x.keep) ? "Yes, by its machine's core" : "No"),
      term.cols ? this.kv(t, "size", "Size", `${term.cols} × ${term.rows}`, { mono: true }) : null,
      x.error ? this.kv(t, "hcerr", "hc get", x.error, { color: t.blocked }) : null,
    ]);
    const labels = Object.entries(term.labels ?? x.labels ?? {});
    if (labels.length) {
      this.section(t, rows, "labels", "LABELS", labels.length, [
        h_flex().id("labels").flex_none().flex_wrap().gap(4).px(S.pad + 4).py(4).children(labels.map(([k, v], i) => this.chip(t, `lab-${i}`, `${k}=${v}`))),
      ]);
    }
    // Relations: parent, hc children, pi runs, Claude agents.
    const parent = term.parent ?? x.parent ?? null;
    const kids = hcChildren(address);
    const runs = (feed()?.runs ?? []).filter((r) => r.parent === address);
    const claude = claudeAll().filter((c) => c.parent === address);
    const liveRuns = runs.filter((r) => r.live).length, liveCl = claude.filter((c) => c.live).length;
    this.section(t, rows, "relations", "RELATIONS", null, [
      this.kv(t, "parent", "Parent", parent ? sessionOf(parent)?.label ?? parent : "None", { color: parent ? t.accent : t.dim, onClick: parent ? () => revealTerminal(parent) : null, copy: parent ? "parent" : null, after: [parent ? div().text_size(S.textXs).text_color(t.dim).child(parent) : null] }),
      ...kids.map((k, i) => this.kv(t, `kid-${i}`, i === 0 ? "Terminals" : "", k.name || k.title || k.address, { lead: statusMark(typeof k.status === "string" ? k.status : k.status?.state, 11), color: t.accent, onClick: () => run("terminal.peek", { terminal: k.address }), tip: "Peek", after: [div().text_size(S.textXs).text_color(t.dim).child(k.address)] })),
      this.kv(t, "pi", "pi runs", runs.length ? `${runs.length} run${runs.length === 1 ? "" : "s"}` : "None", { color: runs.length ? t.accent : t.dim, onClick: runs.length ? () => openView("ob-outline", `term:${address}`) : null, after: [liveRuns ? badge(`${liveRuns} live`, "working") : null], tip: runs.length ? "Open in Outline" : undefined }),
      this.kv(t, "claude", "Claude agents", claude.length ? `${claude.length} agent${claude.length === 1 ? "" : "s"}` : "None", { color: claude.length ? t.accent : t.dim, onClick: claude.length ? () => openView("ob-outline", `term:${address}`) : null, after: [liveCl ? badge(`${liveCl} live`, "working") : null], tip: claude.length ? "Open in Outline" : undefined }),
    ]);
    if (this.transcriptOf(address)) this.usageSection(t, rows, address, now);
    if (fterm) {
      const path = fterm.transcript ?? (fterm.kind === "pi" ? fterm.session : null);
      this.section(t, rows, "file", "SESSION FILE", null, [
        fterm.kind === "claude" && fterm.session ? this.kv(t, "sid", "Session id", fterm.session, { mono: true, copy: fterm.session }) : null,
        fterm.name ? this.kv(t, "sname", "Name", fterm.name) : null,
        path ? this.kv(t, "path", "File", path.split("/").pop(), { mono: true, copy: path, tip: path, after: [fterm.sessionGuess ? badge("guessed", "working") : null] }) : this.kv(t, "path", "File", "Not found", { color: t.dim }),
        path ? h_flex().id("file-actions").flex_none().px(S.pad + 4).py(4).gap(6)
          .child(this.button(t, "open-tx", "file-text", "Open transcript", () => this.openTranscript()))
          .child(this.button(t, "copy-path", "copy", "Copy path", (_e, cx) => copied(cx, "path", path))) : null,
        fterm.sessionGuess ? div().px(S.pad + 4).pb(4).text_size(S.textXs).text_color(t.dim).whitespace_normal().child("Guessed: the newest session file in this folder written since pi started.") : null,
      ]);
    }
    return root
      .child(this.header(t, s, pinned))
      .child(div().h(1).flex_none().bg(t.border))
      .child(div().id("plist-wrap").relative().flex_1().min_h(0)
        .child(v_flex().id("plist").size_full().py(4).overflow_y_scroll().track_scroll(this.scroll).children(rows).child(div().h(8).flex_none()))
        .child(Scrollbar.vertical("plist").absolute().inset_0()));
  }

  // Usage: the agent's tokens over its session (usage.js), and its subagents' output tokens from the feed.
  usageSection(t, rows, address, now) {
    const u = this.usage[address];
    const body = [];
    if (!u) body.push(this.kv(t, "usage-wait", "Usage", "Reading…", { color: t.dim }));
    else if (u.error) body.push(this.kv(t, "usage-err", "Usage", `Couldn't read it: ${u.error}`, { color: t.blocked }));
    else if (!u.summary) body.push(this.kv(t, "usage-none", "Usage", "No turns yet", { color: t.dim }));
    else {
      for (const r of usageLines(u.summary)) body.push(this.kv(t, `u-${r.id}`, r.key, r.value, { mono: true, copy: null }));
      body.push(this.kv(t, "u-subs", "Subagents", subagentsLine(claudeAll().filter((c) => c.parent === address)) ?? "None", { color: null }));
      const paused = feedLine(feed()?.at, now);
      if (paused) body.push(div().id("u-paused").px(S.pad + 4).pb(4).text_size(S.textXs).text_color(t.dim).child(paused));
      const ago_ = u.at ? ago(u.at, now) : "";
      body.push(div().px(S.pad + 4).pb(4).text_size(S.textXs).text_color(t.dim).whitespace_normal()
        .child(`${u.truncated ? "Last 32 MiB of the file" : "Whole file"}${ago_ ? ` · read ${ago_}${ago_ === "now" ? "" : " ago"}` : ""}`));
    }
    this.section(t, rows, "usage", "USAGE", null, body);
  }

  button(t, id, ic, label, onClick) {
    return h_flex().id(id).h(24).px(8).gap(5).items_center().rounded(S.radius).cursor_pointer().border_1().border_color(t.input)
      .text_size(S.textXs).text_color(t.muted).hover((s) => s.bg(t.hover).text_color(t.foreground))
      .on_click((e, cx) => onClick(e, cx)).child(icon(ic, S.iconXs)).child(div().child(label));
  }
}
