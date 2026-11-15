// menu_anchor.js: where a menu opened from a control inside this dialog goes. Pure: no Herdr or kit imports, so
// test/test_ob_settings.py can run it through node.
//
// bounds: the control's box in window pixels ({x, y, width, height}), as a press on it reports it (`bounds`).
// Returns the menu's top-left in the same window pixels: just under the control, its left edge on the control's.
// With no bounds (the control was not painted yet) it returns null, and the caller falls back to the pointer.
export function menuAnchor(bounds, gap = 4) {
  if (!bounds || !Number.isFinite(bounds.x) || !Number.isFinite(bounds.y) || !Number.isFinite(bounds.height)) return null;
  return { x: bounds.x, y: bounds.y + bounds.height + gap };
}
