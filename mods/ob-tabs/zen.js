// Zen mode, as a pure rule (ob-tabs' zen() runs it). Entering hides both sides and the status row; leaving
// shows back what was shown before the FIRST entry (shared "ob.zen" keeps those flags). Leaving when Zen is
// not on changes nothing: a row the person hid by hand stays hidden. No Herdr imports, so
// test/test_ob_tabs.py runs this under node.

// prev: shared "ob.zen" (or undefined). mode: "on" | "off" | "toggle". hidden: { left, right, statusrow } as the
// layout shows them now. Returns { state, hide, show, tabbar }: the state to save, the nodes to hide and show
// (ids: "left", "right", "statusrow"), and the tab bar height to set (px, or null to leave it).
export function zenPlan({ prev, mode, hidden, now }) {
  const wasZen = Boolean(prev?.active);
  const currentlyZen = wasZen && Boolean(hidden?.left) && Boolean(hidden?.right);
  const enter = mode === "on" ? true : mode === "off" ? false : !currentlyZen;
  if (enter) {
    // Entering while in Zen keeps the first entry's saved state: now those flags are Zen's own hiding.
    const state = wasZen ? prev : {
      active: true,
      leftHidden: Boolean(hidden?.left),
      rightHidden: Boolean(hidden?.right),
      statusHidden: Boolean(hidden?.statusrow),
      at: now,
    };
    return { state, hide: ["left", "right", "statusrow"], show: [], tabbar: 0 };
  }
  if (!wasZen) return { state: prev ?? { active: false }, hide: [], show: [], tabbar: null };
  const show = [];
  if (!prev.statusHidden) show.push("statusrow");
  if (!prev.leftHidden) show.push("left");
  if (!prev.rightHidden) show.push("right");
  return { state: { active: false, at: now }, hide: [], show, tabbar: 40 };
}
