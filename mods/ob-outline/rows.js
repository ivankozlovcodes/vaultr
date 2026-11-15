// ob-outline: what a click (or Enter) on a subagent row does. Pure: no Herdr or kit imports, so it can be
// tested under node. A row is expanded in place (its steps, tool calls and actions show); a second click
// collapses it. A run still starting has no steps to show yet, so it stays collapsed and says why.

// -> { expanded: Set (a new set; the given one is not changed), notice: string | null }
export function rowClick(key, expanded, { pending = false } = {}) {
  const next = new Set(expanded);
  if (pending) return { expanded: next, notice: "Still starting: its steps appear after the next scan" };
  if (next.has(key)) next.delete(key); else next.add(key);
  return { expanded: next, notice: null };
}
