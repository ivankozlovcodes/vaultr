// ob-strip's intra-strip drag-reorder and cross-strip drag-move rules, pure (no Herdr or kit imports) so
// test/test_ob_strip.py runs them under node. Never mutates the input tree.

export const DRAG_TTL_MS = 30000;

function findById(node, id) {
  if (!node || typeof node !== "object") return null;
  if (node.id === id) return node;
  for (const c of node.children ?? []) {
    const hit = findById(c, id);
    if (hit) return hit;
  }
  return null;
}

function findParentStack(node, childId) {
  if (!node || typeof node !== "object") return null;
  if (node.type === "stack" && Array.isArray(node.children) && node.children.some((c) => c?.id === childId)) {
    return node;
  }
  for (const c of node.children ?? []) {
    const hit = findParentStack(c, childId);
    if (hit) return hit;
  }
  return null;
}

// Validates shared("ob.stripDrag") and drops stale drag state left behind by an interrupted session.
export function activeStripDrag(raw, now = Date.now()) {
  if (!raw || typeof raw !== "object") return null;
  if (typeof raw.fromStack !== "string" || !raw.fromStack || typeof raw.childId !== "string" || !raw.childId) return null;
  if (typeof raw.at === "number" && (now - raw.at > DRAG_TTL_MS || raw.at - now > DRAG_TTL_MS)) return null;
  return raw;
}

// Reorders `children` by moving `fromId` to the slot of `toId`. Returns a new array, or null when no change applies.
export function reorderChildren(children, fromId, toId) {
  if (!Array.isArray(children) || !fromId || !toId || fromId === toId) return null;
  const fromIdx = children.findIndex((c) => c?.id === fromId);
  const toIdx = children.findIndex((c) => c?.id === toId);
  if (fromIdx < 0 || toIdx < 0 || fromIdx === toIdx) return null;
  const next = [...children];
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  return next;
}

// Clones `tree`, moves `fromId` to `toId`'s position inside stack `stackId`, and returns the new tree (or null on no-op).
export function reorderStack(tree, stackId, fromId, toId) {
  if (!tree || typeof tree !== "object" || !stackId || !fromId || !toId || fromId === toId) return null;
  const copy = JSON.parse(JSON.stringify(tree));
  const stack = findById(copy, stackId);
  if (!stack || stack.type !== "stack" || !Array.isArray(stack.children)) return null;
  const next = reorderChildren(stack.children, fromId, toId);
  if (!next) return null;
  if (!stack.active) {
    const firstVisible = stack.children.find((c) => !c?.hidden)?.id ?? stack.children[0]?.id;
    if (firstVisible) stack.active = firstVisible;
  }
  stack.children = next;
  return copy;
}

// Clones `tree` and moves `childId` into `targetStackId` (before `beforeChildId` if given and found, else appended).
// Activates `childId` in the target stack and advances the source stack's active child if needed. Returns null on no-op.
export function moveBetweenStacks(tree, childId, targetStackId, beforeChildId = null) {
  if (!tree || typeof tree !== "object" || !childId || !targetStackId) return null;
  const copy = JSON.parse(JSON.stringify(tree));
  const from = findParentStack(copy, childId);
  const to = findById(copy, targetStackId);
  if (!from || from.type !== "stack" || !to || to.type !== "stack") return null;
  if (from.id === to.id) {
    return beforeChildId && beforeChildId !== childId ? reorderStack(tree, to.id, childId, beforeChildId) : null;
  }
  const node = from.children.find((c) => c?.id === childId);
  if (!node) return null;
  from.children = from.children.filter((c) => c?.id !== childId);
  if (from.active === childId) {
    const nextActive = from.children.find((c) => !c?.hidden)?.id ?? from.children[0]?.id;
    if (nextActive) from.active = nextActive;
    else delete from.active;
  }
  const nextTo = [...(to.children ?? [])];
  const insertAt = beforeChildId ? nextTo.findIndex((c) => c?.id === beforeChildId) : -1;
  if (insertAt >= 0) nextTo.splice(insertAt, 0, node);
  else nextTo.push(node);
  to.children = nextTo;
  to.active = childId;
  return copy;
}
