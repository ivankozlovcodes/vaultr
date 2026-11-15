// ob-strip's half decisions: which layout node a strip collapses or restores. A side (left or right) has two halves,
// a top stack and a bottom stack, each with its own strip. A strip offers "collapse" for its own half while the other
// half shows, and "restore" for the other half while that one is hidden. A side never loses both halves.
// Pure: no Herdr or kit imports, so test/test_ob_strip.py runs it under node.

// Each half stack, the node that holds it and its strip (what collapses), and the other half of the same side.
export const HALVES = {
  "ob-lt-stack": { node: "ob-lt", sibling: "ob-lb-stack", top: true },
  "ob-lb-stack": { node: "ob-lb-stack", sibling: "ob-lt-stack", top: false },
  "ob-rt-stack": { node: "ob-rt", sibling: "ob-rb-stack", top: true },
  "ob-rb-stack": { node: "ob-rb-stack", sibling: "ob-rt-stack", top: false },
};

function findById(root, id) {
  if (!root || typeof root !== "object") return null;
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const hit = findById(c, id);
    if (hit) return hit;
  }
  return null;
}

// What the strip of `stack` offers, given the layout tree (hidden flags included):
//   { kind: "collapse", node }  its own half, while the other half shows
//   { kind: "restore", node }   the other half, while it is hidden (this strip stays visible)
//   null                        not a half, its own half is hidden, or the layout lacks the node
export function halfAction(tree, stack) {
  const mine = HALVES[stack];
  if (!mine) return null;
  const own = findById(tree, mine.node);
  const other = HALVES[mine.sibling];
  const otherNode = findById(tree, other.node);
  if (!own || !otherNode || own.hidden) return null;
  if (otherNode.hidden) return { kind: "restore", node: other.node };
  return { kind: "collapse", node: mine.node };
}

// The top strip of a side (a block above its top stack) holds that side's own controls: the window buttons on the
// right, the close-left-sidebar toggle on the left. It collapses with its half, so while a top half is hidden the
// bottom strip of that side draws them. -> the hidden top strip's props (stack, side, windowButtons, ...) for that
// bottom strip, else null.
export function standInFor(tree, stack) {
  const mine = HALVES[stack];
  if (!mine || mine.top) return null;
  const own = findById(tree, mine.node);
  const topNode = findById(tree, HALVES[mine.sibling].node);
  if (!own || own.hidden || !topNode?.hidden) return null;
  const strip = findStrip(topNode, mine.sibling);
  return strip ? { ...strip } : null;
}

function findStrip(root, stack) {
  if (!root || typeof root !== "object") return null;
  const p = root.content?.mod === "ob-strip" ? root.content.props : null;
  if (p && p.stack === stack && p.place !== "bottom") return p;
  for (const c of root.children ?? []) {
    const hit = findStrip(c, stack);
    if (hit) return hit;
  }
  return null;
}
