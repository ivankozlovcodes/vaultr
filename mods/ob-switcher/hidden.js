// hidden.js: pure helpers for hiding machines, spaces, and tabs across Vaultr.
// MASTER COPY: kit/hidden.js. sync.sh copies it into mods/ob-*/hidden.js.
// Pure ES module: no herdr or gpui imports so tests can run it in node.

export function mKeyOf(machine) {
  return machine ? String(machine) : "local";
}

export function normHidden(raw) {
  const normList = (arr) => (Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : []);
  return {
    machines: new Set(normList(raw?.machines)),
    spaces: new Set(normList(raw?.spaces)),
    tabs: new Set(normList(raw?.tabs)),
  };
}

export function isMachineHidden(h, machine) {
  const norm = h?.machines instanceof Set ? h : normHidden(h);
  return norm.machines.has(mKeyOf(machine));
}

export function isSpaceHidden(h, space) {
  if (!space) return false;
  const norm = h?.spaces instanceof Set ? h : normHidden(h);
  return isMachineHidden(norm, space.machine) || norm.spaces.has(String(space.id));
}

export function isTabHidden(h, tab, space = null) {
  if (!tab) return false;
  const norm = h?.tabs instanceof Set ? h : normHidden(h);
  if (space && isSpaceHidden(norm, space)) return true;
  if (norm.tabs.has(String(tab.id))) return true;
  return Boolean(tab.settled);
}

export function patchHidden(raw, kind, id, hide) {
  const norm = normHidden(raw);
  const key = kind === "machine" ? mKeyOf(id) : String(id);
  const target = kind === "machine" ? norm.machines : kind === "space" ? norm.spaces : norm.tabs;
  if (hide) {
    target.add(key);
  } else {
    target.delete(key);
  }
  return {
    machines: [...norm.machines].sort(),
    spaces: [...norm.spaces].sort(),
    tabs: [...norm.tabs].sort(),
  };
}
