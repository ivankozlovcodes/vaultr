// Pure: which agents sit under which pane of the active tab (the Outline's tree). No Herdr or kit imports, so
// test/test_ob_outline.py runs it under node.
//
// A pane's agents are the runs, Claude agents and child terminals whose parent (or ancestor through child
// terminals / exited terminals) is that pane's terminal. A mod pane has no terminal and takes nothing. An agent
// whose root is no pane of this tab comes back apart, in `outside`, so the caller can show it after the panes.

const getParent = (parentOf, addr) => {
  if (!parentOf || !addr) return null;
  return parentOf instanceof Map ? (parentOf.get(addr) ?? null) : (parentOf[addr] ?? null);
};

function buildParentMap(kids, extra) {
  const m = new Map();
  if (extra instanceof Map) {
    for (const [k, v] of extra) if (k && v && k !== v) m.set(k, v);
  } else if (extra && typeof extra === "object") {
    for (const [k, v] of Object.entries(extra)) if (k && v && k !== v) m.set(k, v);
  }
  for (const k of kids ?? []) {
    if (k?.address && k.parent && k.parent !== k.address) m.set(k.address, k.parent);
  }
  return m;
}

// Walk `parentOf` links from `addr` to the nearest address in `roots`, or else the highest known unplaced
// ancestor. Breaks on cycles without looping.
export function resolveRoot(addr, roots, parentOf) {
  if (!addr) return null;
  if (roots?.has(addr)) return addr;
  let cur = addr;
  const seen = new Set([cur]);
  for (;;) {
    const next = getParent(parentOf, cur);
    if (!next || seen.has(next)) return cur;
    seen.add(next);
    if (roots?.has(next)) return next;
    cur = next;
  }
}

// panes: the tab's panes in order ({ pane, terminal? }). data: { runs, claude, kids } (each item has `parent`, or
// `address` for a child terminal's own key). opts: { parents? } (Map or plain object from terminals()).
// Returns { groups: [{ pane, runs, claude, kids }], outside: { runs, claude, kids } }.
export function paneAgents(panes, data, opts = {}) {
  const runs = data?.runs ?? [], claude = data?.claude ?? [], kids = data?.kids ?? [];
  const groups = (panes ?? []).map((p) => {
    return { pane: p?.pane, runs: [], claude: [], kids: [], terminal: p?.terminal ?? null };
  });
  const byTerminal = new Map(groups.filter((g) => g.terminal).map((g) => [g.terminal, g]));
  const roots = new Set(byTerminal.keys());
  const parentOf = buildParentMap(kids, opts?.parents);
  const outside = { runs: [], claude: [], kids: [] };
  for (const r of runs) (byTerminal.get(resolveRoot(r.parent, roots, parentOf))?.runs ?? outside.runs).push(r);
  for (const c of claude) (byTerminal.get(resolveRoot(c.parent, roots, parentOf))?.claude ?? outside.claude).push(c);
  for (const k of kids) (byTerminal.get(resolveRoot(k.parent, roots, parentOf))?.kids ?? outside.kids).push(k);
  return { groups: groups.map(({ terminal, ...g }) => g), outside };
}

// What runs under one session right now: its live runs and agents, and its child terminals that are working or
// blocked. A child terminal that finished its turn (done, idle) is still listed, but it is not "live".
// g: { runs, claude, kids }. kidActive(kid) -> true while that child terminal is working or blocked.
export function liveCount(g, kidActive) {
  return (g?.runs ?? []).filter((r) => r.live).length + (g?.claude ?? []).filter((c) => c.live).length
    + (g?.kids ?? []).filter((k) => kidActive(k)).length;
}

// Keep every kid that is active itself OR is an ancestor of any live run, live Claude agent, or active kid.
export function keepLiveAncestors(allKids, { runs = [], claude = [] } = {}, kidActive = () => false, parents = null) {
  const kids = allKids ?? [];
  const byAddr = new Map();
  for (const k of kids) if (k?.address) byAddr.set(k.address, k);
  const keep = new Set();
  const markUp = (addr) => {
    let cur = addr;
    const seen = new Set();
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      const k = byAddr.get(cur);
      if (k) keep.add(cur);
      const next = k?.parent ?? getParent(parents, cur);
      if (!next) break;
      cur = next;
    }
  };
  for (const k of kids) if (kidActive(k)) markUp(k.address);
  for (const r of runs ?? []) if (r?.live && r.parent) markUp(r.parent);
  for (const c of claude ?? []) if (c?.live && c.parent) markUp(c.parent);
  return kids.filter((k) => keep.has(k.address));
}

// Nest a flat session/pane group `{ runs, claude, kids }` into a recursive tree where each kid carries
// `sub: { runs, claude, kids }` for items whose direct parent is that kid. Cycles and missing parents never drop items.
export function nestItems(group) {
  const runs = group?.runs ?? [];
  const claude = group?.claude ?? [];
  const kids = group?.kids ?? [];
  const kidAddrs = new Set(kids.map((k) => k?.address).filter(Boolean));
  const subOf = new Map();
  for (const a of kidAddrs) subOf.set(a, { runs: [], claude: [], kids: [] });

  const topKids = [];
  const childOf = new Map();
  const reaches = (start, target) => {
    let cur = start;
    const seen = new Set();
    while (cur && !seen.has(cur)) {
      if (cur === target) return true;
      seen.add(cur);
      cur = childOf.get(cur) ?? null;
    }
    return false;
  };
  for (const k of kids) {
    const p = k?.parent;
    if (k?.address && p && p !== k.address && kidAddrs.has(p) && !reaches(p, k.address)) {
      childOf.set(k.address, p);
      subOf.get(p).kids.push(k);
    } else {
      topKids.push(k);
    }
  }

  const topRuns = [];
  for (const r of runs) {
    if (r?.parent && subOf.has(r.parent)) subOf.get(r.parent).runs.push(r);
    else topRuns.push(r);
  }
  const topClaude = [];
  for (const c of claude) {
    if (c?.parent && subOf.has(c.parent)) subOf.get(c.parent).claude.push(c);
    else topClaude.push(c);
  }

  const attach = (k) => {
    const s = k?.address ? subOf.get(k.address) : null;
    if (!s) return { ...k, sub: { runs: [], claude: [], kids: [] } };
    return {
      ...k,
      sub: {
        runs: s.runs,
        claude: s.claude,
        kids: s.kids.map(attach),
      },
    };
  };

  return {
    runs: topRuns,
    claude: topClaude,
    kids: topKids.map(attach),
  };
}

// "All" on one machine: one group per session, keyed by its terminal address; the key null is "Unattached" (items
// with no parent). A session is every terminal that has a pane (also one that started nothing) and every root
// address that owns a run, an agent or a child terminal.
// sessions: [{ address, active, at }], the machine's terminals that have a pane (active: working or blocked now).
// data: { runs, claude, kids } of that machine (with Live only, the caller has already dropped what is not live).
// opts: kidActive(kid), sessionActive(address) (asked for a parent that has no pane), liveOnly (a session with a
//   pane that is not active is left out unless something live hangs under it), parents (Map or object), now.
// -> [[address | null, { runs, claude, kids, live, sessActive, at }]]: active ones first, then the most live
//    items, then the newest activity; Unattached last.
export function sessionGroups(sessions, data, opts = {}) {
  const kidActive = opts.kidActive ?? (() => false);
  const sessionActive = opts.sessionActive ?? (() => false);
  const now = opts.now ?? Date.now();
  const groups = new Map();
  const slot = (p) => { if (!groups.has(p)) groups.set(p, { runs: [], claude: [], kids: [], live: 0, sessActive: false, at: 0 }); return groups.get(p); };
  const roots = new Set();
  const sessMeta = new Map();
  for (const s of sessions ?? []) {
    if (!s?.address) continue;
    roots.add(s.address);
    sessMeta.set(s.address, s);
    if (opts.liveOnly && !s.active) continue;
    const x = slot(s.address);
    x.sessActive = Boolean(s.active);
    x.at = Math.max(x.at, Number(s.at ?? 0) || 0);
  }
  const parentOf = buildParentMap(data?.kids, opts.parents);
  const target = (p) => resolveRoot(p ?? null, roots, parentOf);
  for (const r of data?.runs ?? []) { const x = slot(target(r.parent)); x.runs.push(r); x.live += r.live ? 1 : 0; x.at = Math.max(x.at, r.lastUpdate ?? 0); }
  for (const c of data?.claude ?? []) { const x = slot(target(c.parent)); x.claude.push(c); x.live += c.live ? 1 : 0; x.at = Math.max(x.at, c.updatedAt ?? 0); }
  for (const k of data?.kids ?? []) {
    const act = Boolean(kidActive(k));
    const x = slot(target(k.parent));
    x.kids.push(k);
    x.live += act ? 1 : 0;
    x.at = Math.max(x.at, Number(k.status_ms ?? k.created_ms ?? 0) || (act ? now : 0));
  }
  for (const [p, x] of groups) {
    if (p && sessMeta.has(p)) {
      const s = sessMeta.get(p);
      if (s.active) x.sessActive = true;
      x.at = Math.max(x.at, Number(s.at ?? 0) || 0);
    }
    if (p && !x.sessActive && sessionActive(p)) x.sessActive = true;
  }
  const on = (x) => (x.sessActive || x.live > 0 ? 1 : 0);
  return [...groups.entries()].sort(([a, x], [b, y]) => (a === null) - (b === null) || on(y) - on(x) || (y.live - x.live) || (y.at - x.at));
}

// The machine filter (Panel.machine: null for all, "local" or a machine name), the rule "All" uses: a run or a Claude
// agent by its `machine`, a child terminal by its address ("box/t6" is on box). Other fields of `data` are kept.
const machineOfAddress = (a) => (String(a ?? "").includes("/") ? String(a).split("/")[0] : null);
export function onMachine(data, machine) {
  if (!machine) return data;
  const want = machine === "local" ? null : machine;
  return {
    ...data,
    runs: (data?.runs ?? []).filter((r) => (r.machine ?? null) === want),
    claude: (data?.claude ?? []).filter((c) => (c.machine ?? null) === want),
    kids: (data?.kids ?? []).filter((k) => machineOfAddress(k.address) === want),
  };
}
