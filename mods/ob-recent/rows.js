// ob-recent's rows: what each timeline entry says and where a click goes. Pure (no Herdr or kit imports), so
// test/test_ob_recent.py runs it under node. main.js passes the live data (spaces(), panes(), agents() and the
// main agents' addresses) and gets back plain objects to draw.
//
// Stored entries (saved in localStorage "events"):
//   visit: { kind: "visit", space, tab, pane, terminal, at, machine, spaceName, tabName, tabNamed, paneTitle }
//   agent: { kind: "agent", address, space, tab, pane, status, at, machine, spaceName, tabName, tabNamed, agentTitle }
// Entries saved before these names were stored have only the ids (or, for agents, a label), and still render.

// The tab's name as a person reads it: a named tab by its name, an unnamed one by its place ("Tab 2").
export function tabText(name, named) {
  const s = String(name ?? "");
  return named || !/^\d+$/.test(s) ? s : `Tab ${s}`;
}

// A pane's title for a person: the terminal's title, else the program's name.
export function paneTitle(p) {
  return p ? (p.title || p.program?.name || null) : null;
}

// The names a visit keeps with its ids. v: { space, tab, pane, terminal, at }; spaces and panes as the Herdr API gives them.
export function visitRecord(v, spaces, panes) {
  const space = (spaces ?? []).find((s) => s.id === v.space) ?? null;
  const tab = space?.tabs?.find((t) => t.id === v.tab) ?? null;
  const pane = v.pane ? (panes ?? []).find((p) => p.pane === v.pane) ?? null : null;
  return {
    kind: "visit", space: v.space, tab: v.tab, pane: v.pane ?? null, terminal: v.terminal ?? null, at: v.at,
    machine: space?.machine ?? null, spaceName: space?.name ?? null,
    tabName: tab?.name ?? null, tabNamed: Boolean(tab?.named), paneTitle: paneTitle(pane),
  };
}

// The names an agent event keeps. a: an AgentInfo; status: "blocked" or "done"; at: ms since the epoch.
export function agentRecord(a, spaces, status, at) {
  const space = (spaces ?? []).find((s) => s.id === a.space) ?? null;
  const tab = space?.tabs?.find((t) => t.id === a.tab) ?? null;
  return {
    kind: "agent", address: a.address, space: a.space, tab: a.tab, pane: a.pane || null, status, at,
    machine: space?.machine ?? null, spaceName: space?.name ?? a.space_name ?? null,
    tabName: tab?.name ?? a.tab_name ?? null, tabNamed: Boolean(tab?.named),
    agentTitle: a.title || a.program?.name || null,
  };
}

// Where an entry is now, found by ids (a tab that moved within its space is still found). world: { spaces, panes,
// agents, mains } where mains lists the main agents' addresses. Returns null when the tab no longer exists.
export function liveOf(entry, world) {
  const agentNow = entry.kind === "agent" ? (world.agents ?? []).find((a) => a.address === entry.address) ?? null : null;
  const spaceId = entry.space ?? agentNow?.space ?? null;
  const tabId = entry.tab ?? agentNow?.tab ?? null;
  const space = (world.spaces ?? []).find((s) => s.id === spaceId) ?? null;
  const tab = space?.tabs?.find((t) => t.id === tabId) ?? null;
  if (!tab) return null;
  const pane = entry.kind === "visit" && entry.pane
    ? (world.panes ?? []).find((p) => p.pane === entry.pane && p.tab === tab.id) ?? null : null;
  const agentLive = agentNow && (world.mains ?? []).includes(agentNow.address);
  return {
    space: space.id, spaceName: space.name, machine: space.machine ?? null,
    tab: tab.id, tabName: tab.name, tabNamed: Boolean(tab.named),
    pane: pane?.pane ?? null, paneTitle: paneTitle(pane), program: pane?.program ?? null, paneStatus: pane?.status ?? null,
    terminal: agentLive ? agentNow.address : null,
    agentTitle: agentNow ? (agentNow.title || agentNow.program?.name || null) : null,
  };
}

// What a row says. entry: a stored entry; live: liveOf's result, or null when the tab is gone.
// Returns { main, sub, trail, closed, path }: main = the tab; sub = space (and machine when remote);
// trail = agent title (when it differs from the tab), the event and "closed"; path = the full place for a tooltip.
export function rowText(entry, live) {
  const src = live ?? {
    spaceName: entry.spaceName ?? null, machine: entry.machine ?? null, tabName: entry.tabName ?? null,
    tabNamed: entry.tabNamed, paneTitle: entry.paneTitle ?? null, agentTitle: entry.agentTitle ?? null,
  };
  const main = src.tabName != null ? tabText(src.tabName, src.tabNamed)
    : (entry.kind === "agent" && entry.label) || "Closed tab";
  const sub = [src.spaceName, src.machine].filter(Boolean).join(" · ");
  const event = entry.kind === "visit" ? "visited" : entry.status === "blocked" ? "needs you" : "finished";
  const agent = entry.kind === "agent" && src.agentTitle && src.agentTitle !== main ? src.agentTitle : null;
  const closed = !live;
  const trail = [agent, event, closed ? "closed" : null].filter(Boolean).join(" · ");
  const pane = entry.kind === "agent" ? src.agentTitle : src.paneTitle;
  const place = [src.spaceName, main, pane].filter(Boolean).join(" › ");
  const path = src.machine ? `${place} (${src.machine})` : place;
  return { main, sub, trail, closed, path };
}

// Where a click goes. Returns { space, tab, pane } for a visit, { space, tab, terminal } for an agent event (terminal
// null when that agent is no longer a main agent: the tab is focused), or { notice } when the tab is gone.
export function clickPlan(entry, live) {
  if (!live) return { notice: "That tab is closed." };
  if (entry.kind === "visit") return { space: live.space, tab: live.tab, pane: live.pane ?? null };
  return { space: live.space, tab: live.tab, terminal: live.terminal ?? null };
}
