// lights.js: pure macOS traffic-light clearance rule for top-left chrome bars.
// MASTER COPY: kit/lights.js. sync.sh copies it into mods/ob-*/lights.js.
// Pure module (no herdr or gpui imports) so unit tests run directly under node.

export function lightsLeftPad(basePad, win, root, zoom = 1, leftOffset = 0) {
  if (
    win?.platform !== "macos" ||
    win?.titlebar !== "none" ||
    Boolean(win?.fullscreen) ||
    !Array.isArray(root?.traffic_lights)
  ) {
    return basePad;
  }
  const z = zoom > 0 ? zoom : 1;
  const needed = Math.ceil((Number(root.traffic_lights[0] ?? 12) + 64) / z - (Number(leftOffset) || 0));
  return Math.max(basePad, needed);
}

export function paneLightsLeftPad(basePad, o = {}) {
  const {
    win, root, zoom = 1, zen = false, leftHidden = false, leftWidth = 300,
    tabbarHidden = false, tabbarHeight = 40, mainPad = 6, paneBorder = 1, isTopLeft = true,
  } = o ?? {};
  if (!isTopLeft) return basePad;
  const noTabbar = Boolean(zen || tabbarHidden || Number(tabbarHeight ?? 40) < 28);
  if (!noTabbar) return basePad;
  const effLeft = (zen || leftHidden) ? 0 : Number(leftWidth ?? 300);
  const offset = effLeft + Math.max(0, Number(mainPad ?? 6)) + Math.max(0, Number(paneBorder ?? 1));
  return lightsLeftPad(basePad, win, root, zoom, offset);
}
