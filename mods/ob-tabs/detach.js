// ob-tabs: Detach on a tab (Herdr's terminal.park). No Herdr or kit imports, so test/test_ob_tabs.py runs it
// under node. A tab that holds one terminal pane and nothing else can go back to the background as a whole:
// the tab goes away, the program keeps running and the Outline lists it. Close tab ends the program.

// -> the address of the tab's terminal when the tab is exactly one terminal pane, else null.
export function soleTerminal(panes, tabId) {
  const mine = (panes ?? []).filter((p) => p && p.tab === tabId);
  return mine.length === 1 && mine[0].terminal ? mine[0].terminal : null;
}

// -> the menu item that parks that terminal, or null when the tab is not one terminal pane.
export function detachItem(panes, tabId) {
  const terminal = soleTerminal(panes, tabId);
  return terminal ? { label: "Detach to background", icon: "win-min", command: "terminal.park", args: { terminal } } : null;
}
