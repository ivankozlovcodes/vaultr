// obc.js: helpers shared by package C's mods (ob-outline, ob-graph, ob-props).
// MASTER COPY: kit/obc.js. kit/sync.sh copies it into mods/ob-{graph,outline,props}/obc.js; never edit a mod's copy.
// Kit request: move these into kit.js (they only use kit and herdr).

import { terminals, agents, panes, spaces, run, openOverlay, shared, setShared, focused, notify } from "herdr";
import { MOD, machineOf, tabLabel, paneName, dur, ago, fmtTokens, fmtCost, normStatus, copyText, feed, liveRecords, base, followTarget } from "./kit.js";

export const MONO = "JetBrains Mono";

// "verb:payload" -> ["verb", "payload"]; payload may contain ":" and "@".
export function splitCmd(c) {
  const s = String(c ?? "");
  const i = s.indexOf(":");
  return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)];
}

// Everything the app knows about one terminal address, read once from the live lists.
// -> { address, machine, term, agent, pane, tab, space, label, program, status, live }
export function sessionOf(address, ps = panes(), sp = spaces()) {
  if (!address) return null;
  const term = terminals().find((t) => t.address === address) ?? null;
  const agent = agents().find((a) => a.address === address) ?? null;
  const pane = ps.find((p) => p.terminal === address) ?? null;
  let tab = null, space = null;
  const tabId = pane?.tab ?? agent?.tab ?? null;
  if (tabId) for (const s of sp) { const x = s.tabs.find((y) => y.id === tabId); if (x) { tab = x; space = s; break; } }
  if (!space && agent?.space) space = sp.find((s) => s.id === agent.space) ?? null;
  const program = pane?.program ?? agent?.program ?? term?.program ?? null;
  const label = space ? `${space.name} / ${tab ? tabLabel(tab, ps) : "?"}` : term?.name || term?.title || program?.name || address;
  const status = agent?.status ?? (typeof term?.status === "string" ? term.status : term?.status?.state) ?? null;
  return { address, machine: machineOf(address), term, agent, pane, tab, space, label, program, status, live: term ? term.state === "live" : Boolean(pane) };
}

// The session the right sidebar is about: the pinned one (ob.inspect) while it is live, else the last focused
// main-window pane that holds an agent or terminal (kit/follow_target.js). Last followed per panel is in shared "ob.follow".
export function inspected() {
  const f = focused();
  const focus = f ? { pane: f.pane, terminal: f.terminal, agent: Boolean(f.terminal && agents().some((a) => a.address === f.terminal)) } : null;
  const pin = shared("ob.inspect");
  const follow = shared("ob.follow") ?? {};
  const slot = MOD === "ob-props" ? "props" : "subagents";
  const last = follow[slot] ?? null;
  const r = followTarget({ pinned: pin?.terminal ?? null, focused: focus, last, terminals: terminals(), wantAgent: MOD !== "ob-props" });
  if (r.last !== last) setShared("ob.follow", { ...follow, [slot]: r.last });
  return { address: r.terminal, pinned: Boolean(pin?.terminal) && r.terminal === pin.terminal };
}
export function inspect(address) { setShared("ob.inspect", address ? { terminal: address, at: Date.now() } : null); }

// Go to a terminal: its pane when it has one, else agent.focus (agents), else peek.
export function revealTerminal(address) {
  const s = sessionOf(address);
  if (!s) return;
  if (s.pane) {
    if (s.space) run("space.select", { id: s.space.id });
    if (s.tab) run("tab.select", { id: s.tab.id });
    run("pane.focus", { pane: s.pane.pane });
  } else if (s.agent) run("agent.focus", { terminal: address });
  else if (s.live) run("terminal.peek", { terminal: address });
}

// ---------------------------------------------------------------- runs
export function runTitle(r) {
  const steps = r?.steps ?? [];
  if (r?.mode === "workflow") return `workflow · ${steps.length} agent${steps.length === 1 ? "" : "s"}`;
  if (r?.mode === "parallel" && steps.length > 1) {
    const names = [...new Set(steps.map((s) => s.agent))];
    return names.length === 1 ? `${names[0]} ×${steps.length}` : names.join(" ∥ ");
  }
  return steps.map((s) => s.agent).join(" → ") || r?.mode || "run";
}
export function runModels(r) { return [...new Set((r?.steps ?? []).map((s) => s.model).filter(Boolean))].map(shortModel); }
export function shortModel(m) { return String(m ?? "").replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2"); }
export function runWhen(r, now = Date.now()) {
  if (r?.live) return r.startedAt ? dur(now - r.startedAt) : "";
  const t = r?.endedAt ?? r?.lastUpdate;
  return t ? `${ago(t, now)}${ago(t, now) === "now" ? "" : " ago"}` : "";
}
// The step that is running now, else the last one.
export function currentStep(r) {
  const s = r?.steps ?? [];
  return s.find((x) => normStatus(x.status) === "working" && x.startedAt) ?? s.find((x) => normStatus(x.status) === "working") ?? s[s.length - 1] ?? null;
}
// The last tool of a live run's current step.
export function lastTool(r) {
  const st = currentStep(r);
  const t = st?.tools?.[st.tools.length - 1];
  return t ? `${t.tool} ${t.args ?? ""}`.trim() : null;
}
export function runMeta(r, compact) {
  const tools = r.toolCount || r.steps?.reduce((n, s) => n + (s.toolCount ?? 0), 0);
  const tok = r.tokens || r.steps?.reduce((n, s) => n + (s.tokens ?? 0), 0);
  return [
    compact ? null : r.mode,
    compact ? null : runModels(r).join(", "),
    tok ? `${fmtTokens(tok)} tok` : null,
    (r.cost || r.steps?.reduce((n, s) => n + (s.cost ?? 0), 0)) ? fmtCost(r.cost || r.steps.reduce((n, s) => n + (s.cost ?? 0), 0)) : null,
    tools ? `${tools} tool${tools === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(" · ");
}
// A step's best transcript: the child session (full text), else the artifact transcript.
export function stepTranscript(s) { return s?.session || s?.transcript || null; }

// Every Claude Code sub-agent: the feed's, with live state from terminals().records, plus records
// the feed hasn't seen yet. -> [{ key, machine, parent, id, type, desc, model, updatedAt, lastTool, outTokens, live, transcript }]
export function claudeAll() {
  const f = feed();
  const recs = liveRecords();
  const out = (f?.claude ?? []).map((c) => {
    const r = recs.get(c.parent)?.[c.id];
    // Live: the scan's transcript says it is running, or the terminal's live record says so.
    return { ...c, live: Boolean(c.live) || Boolean(r && (r.state === "working" || r.state === "blocked")), state: r?.state ?? null, desc: c.desc || r?.title || c.type };
  });
  for (const [addr, rs] of recs) {
    for (const [id, r] of Object.entries(rs)) {
      if (r?.app === "pi-subagents") continue;   // pi runs report here too: they are runs, see recordRuns()
      if (out.some((c) => c.parent === addr && c.id === id)) continue;
      out.push({ key: `${addr}#${id}`, machine: machineOf(addr), parent: addr, id, type: r.app, desc: r.title, model: null, updatedAt: null, lastTool: null, outTokens: null, live: r.state === "working" || r.state === "blocked", state: r.state, transcript: null });
    }
  }
  return out;
}
// hc child terminals (an agent's `hc run`): sub-agents with a terminal of their own.
export function hcChildren(address) {
  return terminals().filter((t) => t.parent && t.state === "live" && (address == null || t.parent === address));
}

// ---------------------------------------------------------------- popups (ob-outline)
// A log or transcript: a popup over the window, closed with Escape or its close button; "Move to main
// window" in its header makes it a pane. props: { view: "log"|"transcript", machine, path, title, live, runKey }
export function openViewer(p) {
  return openOverlay({ kind: "popup", mod: "ob-outline", width: 760, props: { view: p.view, machine: p.machine ?? null, path: p.path, title: p.title ?? base(p.path), live: Boolean(p.live), runKey: p.runKey ?? null } });
}
// A live hc child terminal: a centered dialog (modal, so a click outside does not close it) with its header
// (ob-outline, view "attach") above the terminal itself. Escape goes to the terminal. Local terminals only.
export function openAttach(p) {
  return openOverlay({ kind: "dialog", modal: true, width: 0.75, height: 0.75, layout: { id: "attach", type: "column", children: [
    { id: "attach-head", type: "block", size: { px: 36 }, content: { mod: "ob-outline", props: { view: "attach", title: p.title ?? p.terminal, parent: p.parent ?? null, machine: p.machine ?? null, terminal: p.terminal } } },
    { id: "attach-term", type: "block", content: { terminal: p.terminal } } ] } });
}

export function copied(cx, what, text) {
  copyText(cx, text);
  notify({ title: `Copied ${what}`, body: String(text ?? "").slice(0, 120), level: "info", timeout: 1500 });
}

// A wrapped string cut into at most `lines` lines of about `chars` characters (no line clamp in GPUI).
export function lines(text, chars, max = 2) {
  const words = String(text ?? "").replace(/\s+/g, " ").trim().split(" ");
  const out = [];
  let cur = "";
  for (const w of words) {
    if (!cur) cur = w;
    else if ((cur + " " + w).length <= chars) cur += " " + w;
    else { out.push(cur); cur = w; if (out.length === max) break; }
  }
  if (cur && out.length < max) out.push(cur);
  const used = out.join(" ").length;
  if (out.length && used < String(text ?? "").replace(/\s+/g, " ").trim().length) out[out.length - 1] = out[out.length - 1].replace(/.{0,1}$/, "") + "…";
  return out;
}

// pi-subagents also reports its background runs as records ("subagents/<run id 12>[.<step>]") on the
// parent terminal, at once. A live one the feed hasn't scanned yet becomes a provisional run, so a
// new run shows up before the next scan. -> Run-shaped objects with `pending: true`.
export function recordRuns() {
  const f = feed();
  const known = new Set((f?.runs ?? []).map((r) => r.id.replace(/-/g, "").slice(0, 12)));
  const out = [];
  for (const [addr, rs] of liveRecords()) {
    for (const [id, r] of Object.entries(rs)) {
      const m = /^subagents\/([0-9a-f]{12})$/i.exec(id);
      if (r?.app !== "pi-subagents" || !m || known.has(m[1].toLowerCase())) continue;
      if (r.state !== "working" && r.state !== "blocked") continue;
      const steps = Object.entries(rs).filter(([k]) => k.startsWith(id + ".")).map(([, x]) => ({ agent: x.title || "step", status: x.state === "working" ? "running" : x.state, tools: [], out: [] }));
      out.push({ key: `rec:${addr}#${id}`, machine: machineOf(addr), id: m[1], short: m[1].slice(0, 8), mode: steps.length ? "workflow" : null, state: "running", live: true, pending: true,
        parent: addr, startedAt: null, lastUpdate: Date.now(), steps: steps.length ? steps : [{ agent: r.title || "pi run", status: "running", tools: [], out: [] }], error: null, log: null });
    }
  }
  return out;
}
