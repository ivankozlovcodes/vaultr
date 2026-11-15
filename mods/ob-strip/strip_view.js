// ob-strip's look decision, pure: which panel name the strip shows, which tabs it draws with their tooltips, and the
// tooltip of the collapse or restore control. No Herdr or kit imports, so test/test_ob_strip.py runs it under node.
// The output has the same shape for a left and a right strip; main.js only draws what it returns.

export const HALF_TIPS = { collapse: "Hide this half", restore: "Show the other half" };

// kids: the stack's visible children [{ id, title, icon }] in stack order.
// shown: the children that fit as tabs (default: all of kids). The label still names the active child when it is
// not shown.
// active: the active child's id (default: the first child).
// half: halfAction() from halves.js, { kind, node } or null.
export function stripView({ kids = [], shown = kids, active, half = null } = {}) {
  const current = kids.find((k) => k.id === active) ?? kids[0];
  return {
    label: current?.title ?? "",
    tabs: shown.map((k) => ({ id: k.id, icon: k.icon, title: k.title, tip: k.title, active: k.id === current?.id })),
    half: half ? { kind: half.kind, node: half.node, tip: HALF_TIPS[half.kind] ?? "" } : null,
  };
}
