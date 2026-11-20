// ob-pane: Detach (Herdr's terminal.park). No Herdr or kit imports, so test/test_ob_pane.py runs it under node.
// Detach takes a terminal's pane away (its tab too, when it was the only pane) and leaves the program running
// in the background, where the Outline lists it. Close pane ends the program.

export const DETACH_ICON = "win-min";
export const DETACH_TIP = "Detach to background (leaves terminal running)";

// A terminal started by another terminal (`parent`). Closing its pane by mistake ends an agent at work, so
// its header shows Detach all the time, not only in the menu.
export function isChildTerminal(term) {
  return Boolean(term?.parent);
}

// -> the menu item that parks the terminal at `terminal`.
export function detachItem(terminal) {
  return { label: "Detach to background", icon: DETACH_ICON, command: "terminal.park", args: { terminal } };
}
