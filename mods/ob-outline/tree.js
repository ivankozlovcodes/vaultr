// Pure: which agents sit under which pane of the active tab (the Outline's tree). No Herdr or kit imports, so
// test/test_ob_outline.py runs it under node.
//
// A pane's agents are the runs, Claude agents and child terminals whose parent is that pane's terminal. A mod pane
// has no terminal and takes nothing. An agent whose parent is no pane of this tab (a pinned session elsewhere)
// comes back apart, in `outside`, so the caller can show it after the panes.

// panes: the tab's panes in order ({ pane, terminal? }). data: { runs, claude, kids } (each item has `parent`, or
// `address` for a child terminal's own key). Returns { groups: [{ pane, runs, claude, kids }], outside: { runs, claude, kids } }.
export function paneAgents(panes, data) {
  const runs = data?.runs ?? [], claude = data?.claude ?? [], kids = data?.kids ?? [];
  const groups = (panes ?? []).map((p) => {
    return { pane: p?.pane, runs: [], claude: [], kids: [], terminal: p?.terminal ?? null };
  });
  const byTerminal = new Map(groups.filter((g) => g.terminal).map((g) => [g.terminal, g]));
  const outside = { runs: [], claude: [], kids: [] };
  for (const r of runs) (byTerminal.get(r.parent)?.runs ?? outside.runs).push(r);
  for (const c of claude) (byTerminal.get(c.parent)?.claude ?? outside.claude).push(c);
  for (const k of kids) (byTerminal.get(k.parent)?.kids ?? outside.kids).push(k);
  return { groups: groups.map(({ terminal, ...g }) => g), outside };
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
