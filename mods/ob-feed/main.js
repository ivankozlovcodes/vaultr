// ob-feed: the ONE poller of sub-agent data. Runs scan_pi.py on every reachable machine (one exec per
// machine at a time: exec("python3", ["-c", script, opts], { on })), merges the results and publishes
// shared "ob.subagents" (SPEC.md 7.3) only when its content changed. Lives in the always-shown status
// row, so it is alive whenever the layout is. Draws the status-bar segment: live sub-agent count, a
// warning per machine that couldn't be scanned (tooltip says why); click opens the Subagents view.
//
// Commands (ob-feed.<cmd>):
//   refresh                 scan every machine now
//   refresh:<machine|local> scan one machine now
//   fixture:<dir>           TEST HOOK: also read pi-subagents runs from <dir> on this computer (a folder
//                           laid out like <tmp>/pi-subagents-uid-N/async-subagent-runs). In memory only:
//                           gone on reload. `fixture:` (empty) turns it off.
//
// Cadence (SPEC 7.5): ticks every second; a machine is scanned the first time, on refresh, when any
// agent status or live sub-agent record changes, 2 s after its last scan while it has live runs or
// records, 15 s otherwise, 60 s after a failure. Unavailable machines are not asked; their last
// result is kept and marked stale. Publishing compares a signature without timestamps, so a quiet
// system writes nothing to shared.json.

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { exec, machines, readTextFile, appHome, setShared, agents, nextCommand, settings, props, run, panes } from "herdr";
import { S, tc, icon, statusMark, liveRecords, machineOf, addrOn, openView, subagentCounts, machineLabel, ago, feed, publishDue, tickerChips } from "./kit.js";
import { mainAgentAt } from "./ticker_at.js";

const FAST = 2000;      // a machine with live runs or live claude records
const SLOW = 15000;     // otherwise
const RETRY = 60000;    // after a failed scan
const MIN_PUBLISH = 1000; // never write shared.json more than once a second
const KEEP_DETAIL = 6;  // finished runs that keep their tools/output lines in the payload
const OPT = { maxAgeH: 48, limit: 40, claude: true };

const mkey = (m) => m ?? "local";
const str = (v, n = 400) => (typeof v === "string" ? (v.length > n ? v.slice(0, n - 1) + "…" : v) : null);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
// Files the agents touch (scan_pi.py `touches`): paths and ops only. TOUCH_TOTAL caps all of them, newest first.
const TOUCH_OPS = ["read", "edit", "write", "create", "publish"];
const TOUCH_TOTAL = 400;

// A scanner key to the graph's node key: term:<terminal> (a main agent's pane), a:<id> (a Claude sub-agent, c:<key>),
// r:<id> (a pi run, r:<key>), with the machine as ob-feed keys them.
function touchKey(key, k, m) {
  const i = key.indexOf(":");
  const kind = key.slice(0, i), id = key.slice(i + 1);
  if (!id) return null;
  if (kind === "term") return `term:${addrOn(m, id)}`;
  if (kind === "a") return `c:${k}:${id}`;
  if (kind === "r") return `r:${k}:${id}`;
  return null;
}

function cleanTouch(x) {
  if (!x || typeof x !== "object" || typeof x.path !== "string" || !TOUCH_OPS.includes(x.op)) return null;
  const t = { path: str(x.path, 600), op: x.op, at: num(x.at) };
  if (x.artifact && typeof x.artifact === "object") t.artifact = { id: str(x.artifact.id, 80), title: str(x.artifact.title, 120), v: num(x.artifact.v) };
  return t;
}

// Scanner output is trusted to nothing: every field is typed here before it reaches shared state.
function cleanStep(s) {
  if (!s || typeof s !== "object") return null;
  return {
    agent: str(s.agent, 60) ?? "agent", label: str(s.label, 80), task: str(s.task, 200), status: str(s.status, 30),
    model: str(s.model, 60), startedAt: num(s.startedAt), endedAt: num(s.endedAt), tokens: num(s.tokens), cost: num(s.cost),
    turns: num(s.turns), toolCount: num(s.toolCount),
    tools: arr(s.tools).filter((x) => x && typeof x === "object").slice(-3).map((x) => ({ tool: str(x.tool, 40) ?? "tool", args: str(x.args, 120) ?? "", at: num(x.at) })),
    out: arr(s.out).filter((x) => typeof x === "string").slice(-4).map((x) => str(x, 200)),
    error: str(s.error, 240), session: str(s.session, 600), transcript: str(s.transcript, 600),
  };
}

export default class Feed extends View {
  init(_p, cx) {
    // The role (props): "scan" is the scanner alone, mounted where no toggle hides it (layouts/vaultr.json);
    // "draw" is the status-row segment alone, reading the published payload; "both" (the default) does each.
    this.role = props()?.role ?? "both";
    this.res = {};      // mkey -> { ok, at, error, ms, data, stale }
    this.busy = new Set();
    this.last = "";
    this.sig = "";
    this.pubAt = 0;
    this.beatAt = 0;
    this.pending = false;
    this.fixture = null;
    this.scriptError = null;
    this.w = 0;
    if (this.role === "draw") return;
    cx.spawn(async (cx) => {
      try {
        this.script = await readTextFile(`${appHome()}/mods/ob-feed/scan_pi.py`);
        if (!this.script) this.scriptError = "scan_pi.py is missing";
      } catch (e) { this.scriptError = `scan_pi.py: ${e?.message ?? e}`; }
      this.tick(cx, true);
      cx.notify();
    });
    cx.timer.every(1000, (cx) => this.tick(cx, false));
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(String(c), cx); } catch (e) { console.log(`ob-feed: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  command(c, cx) {
    if (c === "refresh") this.tick(cx, true);
    else if (c.startsWith("refresh:")) { const m = c.slice(8); this.scan(m === "local" || m === "" ? null : m, cx); }
    else if (c.startsWith("fixture:")) {
      const dir = c.slice(8).trim();
      this.fixture = dir || null;
      console.log(`ob-feed: fixture root ${this.fixture ?? "off"}`);
      this.scan(null, cx);
    }
  }

  // Every machine Herdr knows (null = this computer), with whether it can be asked now.
  machineList() {
    const list = machines().filter((m) => !m.temporary).map((m) => ({ name: m.name ?? null, up: m.layout !== "unavailable" }));
    if (!list.some((m) => m.name === null)) list.unshift({ name: null, up: true });
    return list;
  }

  due(m, now) {
    const r = this.res[mkey(m)];
    if (!r || r.stale) return true;
    if (!r.ok) return now - r.at > RETRY;
    const live = (r.data?.runs ?? []).some((x) => x.live) || [...liveRecords().keys()].some((a) => machineOf(a) === m);
    return now - r.at > (live ? FAST : SLOW);
  }

  tick(cx, all) {
    if (!this.script) return;
    // Agent status changes (a turn ended, a sub-agent started) are a reason to look now.
    const sig = agents().map((a) => `${a.address}:${a.status}`).join(",") + "|" + [...liveRecords().entries()].map(([a, r]) => a + Object.keys(r).join("+")).join(",");
    const kick = sig !== this.sig;
    this.sig = sig;
    const now = Date.now();
    const list = this.machineList();
    let changed = false;
    // Forget machines that are gone; mark unreachable ones stale (their last result stays, flagged).
    const known = new Set(list.map((m) => mkey(m.name)));
    for (const k of Object.keys(this.res)) if (!known.has(k)) { delete this.res[k]; changed = true; }
    for (const m of list) {
      const k = mkey(m.name);
      if (!m.up) {
        const r = this.res[k];
        if (!r || !r.stale) { this.res[k] = { ...(r ?? { at: now, ms: 0, data: null }), ok: false, stale: true, error: "Machine unavailable" }; changed = true; }
        continue;
      }
      if (all || kick || this.due(m.name, now)) this.scan(m.name, cx);
    }
    if (changed || this.pending || publishDue({ same: true, now, beatAt: this.beatAt })) this.publish(cx);
  }

  scan(m, cx) {
    const k = mkey(m);
    if (this.busy.has(k) || !this.script) return;
    this.busy.add(k);
    const opts = JSON.stringify(m === null && this.fixture ? { ...OPT, extraRoots: [this.fixture] } : OPT);
    cx.spawn(async (cx) => {
      const t0 = Date.now();
      try {
        const r = await exec("python3", ["-c", this.script, opts], { ...(m ? { on: m } : {}), timeout: 20000 });
        const line = String(r.stdout ?? "").trim().split("\n").filter(Boolean).pop() ?? "";
        if (r.code !== 0 || !line.startsWith("{")) throw new Error((r.stderr || r.stdout || `exit ${r.code}`).trim().split("\n").pop() || `exit ${r.code}`);
        const data = JSON.parse(line);
        if (!data || typeof data !== "object") throw new Error("scanner printed no object");
        this.res[k] = { ok: true, at: Date.now(), ms: Date.now() - t0, error: data.errors?.length ? str(String(data.errors[0]), 200) : null, data, stale: false };
      } catch (e) {
        this.res[k] = { ok: false, at: Date.now(), ms: Date.now() - t0, error: str(String(e?.message ?? e), 200), data: this.res[k]?.data ?? null, stale: false };
      }
      this.busy.delete(k);
      try { this.publish(cx); } catch (e) { console.log(`ob-feed: publish failed: ${e}`); }
      cx.notify();
    });
  }

  // Merge every machine's scan into the shared payload (SPEC 7.3).
  publish(cx) {
    const now = Date.now();
    if (now - this.pubAt < MIN_PUBLISH) {
      // Too soon: the next tick publishes (the pending flag makes it).
      this.pending = true;
      return;
    }
    this.pending = false;
    const runs = [], claude = [], ms = {}, terms = {}, touches = {};
    for (const [k, r] of Object.entries(this.res)) {
      const m = k === "local" ? null : k;
      ms[k] = { ok: r.ok, at: r.at, ms: r.ms, error: r.error ?? null, ...(r.stale ? { stale: true } : {}) };
      const d = r.data;
      if (!d) continue;
      for (const x of arr(d.runs)) {
        if (!x || typeof x !== "object" || typeof x.id !== "string") continue;
        // A stale machine's runs can't be live as far as we know.
        const live = Boolean(x.live) && !r.stale;
        runs.push({
          key: `${k}:${x.id}`, machine: m, id: x.id, short: x.id.slice(0, 8), mode: str(x.mode, 20), state: live || !x.live ? str(x.state, 20) ?? "unknown" : "unknown", live,
          startedAt: num(x.startedAt), endedAt: num(x.endedAt), lastUpdate: num(x.lastUpdate), cwd: str(x.cwd, 600),
          parent: typeof x.term === "string" ? addrOn(m, x.term) : null, parentGuess: Boolean(x.termGuess), parentSession: str(x.parentSession, 600),
          tokens: num(x.tokens), cost: num(x.cost), turns: num(x.turns), toolCount: num(x.toolCount), error: str(x.error, 240), log: str(x.log, 600), dir: str(x.dir, 600),
          currentStep: num(x.currentStep),
          steps: arr(x.steps).map(cleanStep).filter(Boolean),
        });
      }
      for (const [key, rows] of Object.entries(d.touches && typeof d.touches === "object" ? d.touches : {})) {
        const gk = touchKey(key, k, m);
        const list = arr(rows).map(cleanTouch).filter(Boolean);
        if (gk && list.length) touches[gk] = list;
      }
      for (const [term, info] of Object.entries(d.terms && typeof d.terms === "object" ? d.terms : {})) {
        if (!info || typeof info !== "object") continue;
        const addr = addrOn(m, term);
        terms[addr] = { kind: str(info.kind, 20), pid: num(info.pid), cwd: str(info.cwd, 600), session: str(info.session, 600), sessionGuess: Boolean(info.guess), name: str(info.name, 120), transcript: str(info.transcript, 600), updatedAt: num(info.updatedAt),
          lastTool: info.lastTool && typeof info.lastTool === "object" ? { tool: str(info.lastTool.tool, 40), args: str(info.lastTool.args, 40) } : null };
        for (const a of arr(info.agents)) {
          if (!a || typeof a.id !== "string") continue;
          claude.push({ key: `${k}:${a.id}`, machine: m, parent: addr, id: a.id, type: str(a.type, 60), desc: str(a.desc, 160), model: str(a.model, 60),
            updatedAt: num(a.updatedAt), lastTool: a.lastTool && typeof a.lastTool === "object" ? { tool: str(a.lastTool.tool, 40), args: str(a.lastTool.args, 120) } : null,
            outTokens: num(a.outTokens), toolCount: num(a.toolCount), turns: num(a.turns),
            live: Boolean(a.live) && !r.stale, ended: Boolean(a.ended), transcript: str(a.transcript, 600) });
        }
      }
    }
    runs.sort((a, b) => (b.live - a.live) || ((b.lastUpdate ?? 0) - (a.lastUpdate ?? 0)));
    runs.forEach((r, i) => { if (!r.live && i >= KEEP_DETAIL) r.steps = r.steps.map((s) => ({ ...s, tools: s.tools.slice(-1), out: [] })); });
    claude.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
    // A run whose owner process is gone still belongs to the terminal now writing its parent session.
    for (const r of runs) {
      if (r.parent || !r.parentSession) continue;
      const hit = Object.entries(terms).find(([a, x]) => x.session === r.parentSession && (machineOf(a) ?? null) === r.machine);
      if (hit) { r.parent = hit[0]; r.parentGuess = true; }
    }
    // The newest TOUCH_TOTAL touches across every agent (each agent already kept its own 40).
    const all = Object.entries(touches).flatMap(([gk, list]) => list.map((t) => ({ gk, t })));
    all.sort((a, b) => (b.t.at ?? 0) - (a.t.at ?? 0));
    const kept = {};
    for (const { gk, t } of all.slice(0, TOUCH_TOTAL)) (kept[gk] ??= []).push(t);
    const body = { v: 1, machines: ms, runs, claude: claude.slice(0, 60), terms, touches: kept, scriptError: this.scriptError };
    // Compare without the timestamps that change on every scan. An unchanged payload is still published once a
    // beat (kit/feed_age.js), so `at` says the scanner is alive: consumers call the feed paused when it goes stale.
    const sig = JSON.stringify({ runs, claude: body.claude, terms, touches: kept, scriptError: body.scriptError, ok: Object.fromEntries(Object.entries(ms).map(([k, v]) => [k, [v.ok, v.error, Boolean(v.stale)]])) });
    const same = sig === this.last;
    if (!publishDue({ same, now, beatAt: this.beatAt })) return;
    this.last = sig;
    this.pubAt = now;
    this.beatAt = now;
    setShared("ob.subagents", { ...body, at: now });
  }

  // What the ticker can say: each running agent on this computer, with its latest action (kit/ticker.js). Pi runs
  // and Claude subagents come from the feed; a main Claude agent is a working agent in a pane of its terminal.
  tickerItems() {
    const f = feed();
    const working = new Map(agents().filter((a) => a.status === "working").map((a) => [a.address, a]));
    const items = [];
    for (const r of f?.runs ?? []) {
      if (r.machine || !r.live) continue;
      const step = (r.steps ?? []).at(-1);
      items.push({ key: r.key, title: step?.label || step?.agent || "pi", live: true, at: r.lastUpdate ?? 0, turns: r.turns,
        tool: step?.tools?.at(-1) ?? null, target: { kind: "outline", key: r.key } });
    }
    for (const c of f?.claude ?? []) {
      if (c.machine || !c.live) continue;
      items.push({ key: c.key, title: c.desc || c.type || "Claude Code", live: true, at: c.updatedAt ?? 0, turns: c.turns,
        tool: c.lastTool ?? null, target: { kind: "outline", key: c.key } });
    }
    for (const [addr, info] of Object.entries(f?.terms ?? {})) {
      if (info?.kind !== "claude" || machineOf(addr) || !working.has(addr)) continue;
      items.push({ key: `main:${addr}`, title: "Claude Code", live: true, at: mainAgentAt(info, f?.touches?.[`term:${addr}`], Date.now()), tool: info.lastTool ?? null, target: { kind: "pane", terminal: addr } });
    }
    return items;
  }

  // A click on a chip: a main agent's pane is focused; a subagent's card opens in Outline.
  go(target) {
    if (target?.kind === "pane") {
      const p = panes().find((x) => x.terminal === target.terminal);
      if (p) run("pane.focus", { pane: p.pane });
    } else if (target?.kind === "outline") {
      openView("ob-outline", `run:${target.key}`);
    }
  }

  render() {
    const t = tc();
    if (this.role === "scan") return div().id("root").size_full();
    // The segment reads the published payload, so it shows the same failures whichever copy scans.
    const f = feed();
    const bad = Object.entries(f?.machines ?? {}).filter(([, m]) => m && !m.ok);
    // A missing scanner never publishes (tick returns first), so this copy's own error is shown too.
    const scriptError = f?.scriptError ?? this.scriptError;
    const why = [
      ...(scriptError ? [scriptError] : []),
      ...bad.map(([k, m]) => `${machineLabel(k === "local" ? null : k)}: ${m.error ?? "scan failed"}${m.stale && m.at ? ` (showing data from ${ago(m.at)} ago)` : ""}`),
    ];
    // Nothing running: nothing shown (no placeholder). Otherwise a chip per agent, newest first.
    const chips = tickerChips(this.tickerItems());
    return h_flex().id("root").size_full().min_w(0).overflow_hidden().px(8).gap(6).items_center().bg(t.chrome).border_t(1).border_color(t.border)
      .text_size(S.textXs).text_color(t.muted)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .children(chips.map((c) => h_flex().id(`tk-${c.key}`).h(20).px(6).min_w(0).flex_shrink(1).items_center().gap(5).rounded(S.radius).cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .tooltip(`${c.text}\nClick: ${c.target?.kind === "pane" ? "go to its pane" : "open it in Outline"}`)
        .on_click(() => this.go(c.target))
        .child(statusMark("working", 10))
        .child(div().min_w(0).truncate().child(c.text))))
      .when(why.length > 0, (e) => e.child(h_flex().id("feed-alert").flex_none().tooltip(why.join("\n")).child(icon("alert", S.iconXs, t.blocked))));
  }
}
