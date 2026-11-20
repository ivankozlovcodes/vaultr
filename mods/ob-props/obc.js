// obc.js: helpers shared by package C's mods (ob-outline, ob-graph, ob-props).
// MASTER COPY: kit/obc.js. kit/sync.sh copies it into mods/ob-{graph,outline,props}/obc.js; never edit a mod's copy.
// Kit request: move these into kit.js (they only use kit and herdr).

import { terminals, agents, panes, spaces, run, openOverlay, shared, setShared, focused, notify } from "herdr";
import {
  MOD, machineOf, tabLabel, paneName, dur, ago, fmtTokens, fmtCost, normStatus, copyText, provider, liveRecords, base,
  followTarget, parentAddrOf, isChildTerminalOf, getHidden, updateHidden, patchHidden, normHidden, isSpaceHidden, isTabHidden,
} from "./kit.js";

export const MONO = "JetBrains Mono";

// "verb:payload" -> ["verb", "payload"]; payload may contain ":" and "@".
export function splitCmd(c) {
  const s = String(c ?? "");
  const i = s.indexOf(":");
  return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)];
}

// Everything the app knows about one terminal address, read once from the live lists.
// -> { address, machine, term, agent, pane, tab, space, label, program, status, live }
export function sessionOf(address, ps = panes(), sp = spaces(), ts = terminals()) {
  if (!address) return null;
  const term = ts.find((t) => t.address === address) ?? null;
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

// Walk up parentAddrOf links from `address` to find the nearest ancestor terminal placed in a pane/tab.
export function placedSessionOf(address, ps = panes(), sp = spaces(), ts = terminals()) {
  if (!address) return null;
  let cur = address;
  const seen = new Set();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const s = sessionOf(cur, ps, sp, ts);
    if (s?.pane || (s?.tab && s?.space)) return s;
    const t = s?.term ?? ts.find((x) => x.address === cur);
    cur = parentAddrOf(t);
  }
  return null;
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

// Go to a terminal: walk up to the nearest placed ancestor tab/pane (unhiding if hidden), else focus/peek.
export function revealTerminal(address) {
  if (!address) return false;
  const target = placedSessionOf(address);
  if (target) {
    const h = normHidden(shared("ob.hidden") ?? getHidden());
    if (target.space && (isSpaceHidden(h, target.space) || (target.tab && isTabHidden(h, target.tab, target.space)))) {
      updateHidden((cur) => {
        let next = patchHidden(cur, "machine", target.space.machine ?? null, false);
        next = patchHidden(next, "space", target.space.id, false);
        if (target.tab) next = patchHidden(next, "tab", target.tab.id, false);
        return next;
      });
    }
    if (target.tab?.settled) run("tab.unsettle", { id: target.tab.id });
    if (target.space) run("space.select", { id: target.space.id });
    if (target.tab) run("tab.select", { id: target.tab.id });
    if (target.pane) run("pane.focus", { pane: target.pane.pane });
    else if (target.agent?.tab) run("agent.focus", { terminal: target.address });
    return true;
  }
  const s = sessionOf(address);
  if (!s) return false;
  if (s.agent?.tab) { run("agent.focus", { terminal: address }); return true; }
  if (s.live) { run("terminal.peek", { terminal: address }); return true; }
  return false;
}

// ---------------------------------------------------------------- runs
export function runTitle(r) {
  const steps = r?.steps ?? [];
  if (r?.mode === "workflow") return `workflow · ${steps.length} agent${steps.length === 1 ? "" : "s"}`;
  if (r?.mode === "parallel" && steps.length > 1) {
    const names = [...new Set(steps.map((s) => s.agent))];
    return names.length === 1 ? `${names[0]} ×${steps.length}` : names.join(" ∥ ");
  }
  return steps.map((s) => s.agent).join(" → ") || provider.of(r)?.noun || r?.mode || "run";
}
export function runModels(r) { return [...new Set((r?.steps ?? []).map((s) => s.model).filter(Boolean))].map(shortModel); }
export function shortModel(m) {
  return String(m ?? "").replace(/^[^/]+\//, "").replace(/^[a-z]+-(?=(?:opus|sonnet|haiku|3)-)/i, "").replace(/-(\d+)-(\d+)$/, " $1.$2");
}
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

// All sub-agent runs and sub-agents: provider.subagents(filter) merged with live terminals().records
// (including provisional subagents/<id12> runs started before the next scan). -> { runs, agents }.
export function allSubagents(filter = {}) {
  const subs = provider.subagents(filter);
  const recs = liveRecords();
  const recTool = (r) => {
    const msg = typeof r?.msg === "string" ? r.msg.trim() : "";
    return msg ? { tool: msg, args: "" } : null;
  };
  const runs = subs.filter((x) => x.kind === "run");
  const known = new Set(runs.map((r) => String(r.id ?? "").replace(/-/g, "").slice(0, 12).toLowerCase()).filter(Boolean));
  const agents = subs.filter((x) => x.kind === "agent").map((c) => {
    const r = recs.get(c.parent)?.[c.id];
    // Live: the scan's transcript says it is running, or the terminal's live record says so.
    return {
      ...c,
      live: Boolean(c.live) || (!c.ended && Boolean(r && (r.state === "working" || r.state === "blocked"))),
      state: r?.state ?? null,
      desc: c.desc || r?.title || c.type,
      lastTool: c.lastTool ?? recTool(r),
    };
  });
  const wantParent = filter && Object.prototype.hasOwnProperty.call(filter, "parent") ? filter.parent : undefined;
  const wantMachine = filter && Object.prototype.hasOwnProperty.call(filter, "machine") ? filter.machine : undefined;
  for (const [addr, rs] of recs) {
    if (wantParent !== undefined && addr !== wantParent) continue;
    if (wantMachine !== undefined && machineOf(addr) !== (wantMachine === "local" ? null : wantMachine)) continue;
    if (!rs || typeof rs !== "object") continue;
    for (const [id, r] of Object.entries(rs)) {
      const m = /^subagents\/([0-9a-f]{12})$/i.exec(id);
      if (m) {
        const rid = m[1].toLowerCase();
        if (known.has(rid) || (r.state !== "working" && r.state !== "blocked")) continue;
        const steps = Object.entries(rs).filter(([k]) => k.startsWith(id + ".")).map(([, x]) => ({ agent: x.title || "step", status: x.state === "working" ? "running" : x.state, tools: [], out: [] }));
        runs.push({
          kind: "run", key: `rec:${addr}#${id}`, machine: machineOf(addr), id: m[1], short: m[1].slice(0, 8),
          mode: steps.length ? "workflow" : null, state: "running", live: true, pending: true,
          parent: addr, startedAt: null, lastUpdate: Date.now(),
          steps: steps.length ? steps : [{ agent: r.title || "run", status: "running", tools: [], out: [] }], error: null, log: null,
        });
        continue;
      }
      if (/^subagents\/[0-9a-f]{12}\./i.test(id)) continue;
      if (agents.some((c) => c.parent === addr && c.id === id)) continue;
      agents.push({
        kind: "agent", key: `${addr}#${id}`, machine: machineOf(addr), parent: addr, id,
        provider: null, type: r.app, desc: r.title, model: null, updatedAt: null, lastTool: recTool(r),
        outTokens: null, live: r.state === "working" || r.state === "blocked", state: r.state, transcript: null,
      });
    }
  }
  return { runs, agents };
}
// hc child terminals (an agent's `hc run`): sub-agents with a terminal of their own.
export function hcChildren(address) {
  const out = [];
  for (const t of terminals()) {
    if (!t || t.state !== "live") continue;
    const p = parentAddrOf(t);
    if (!p || p === t.address) continue;
    if (address != null && !isChildTerminalOf(t, address)) continue;
    out.push(t.parent === p ? t : { ...t, parent: p });
  }
  return out;
}

// ---------------------------------------------------------------- popups (ob-outline)
// A log or transcript: a popup over the window, closed with Escape or its close button; "Move to main
// window" in its header makes it a pane. props: { view: "log"|"transcript", machine, path, title, live, runKey }
export function openViewer(p) {
  return openOverlay({ kind: "popup", mod: "ob-outline", width: 760, props: { view: p.view, machine: p.machine ?? null, path: p.path, title: p.title ?? base(p.path), live: Boolean(p.live), runKey: p.runKey ?? null } });
}
// A live hc child terminal: a centered dialog with its header (ob-outline, view "attach") above the terminal
// itself. Not modal, like Herdr's own peek: a click outside it (or Detach in its header) closes the dialog and
// the terminal keeps running in the background. Escape goes to the terminal.
export function openAttach(p) {
  return openOverlay({ kind: "dialog", width: 0.75, height: 0.75, layout: { id: "attach", type: "column", children: [
    { id: "attach-head", type: "block", size: { px: 36 }, content: { mod: "ob-outline", props: {
      view: "attach", title: p.title ?? p.terminal, parent: p.parent ?? null, machine: p.machine ?? null,
      terminal: p.terminal, mainTerminal: p.mainTerminal ?? null, mainTab: p.mainTab ?? null,
    } } },
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
