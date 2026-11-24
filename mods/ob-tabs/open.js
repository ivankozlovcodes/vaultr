// Pure open/toggle decision for ob-tabs (open() carries it out). No Herdr or kit imports, so
// test/test_ob_tabs.py runs this under node.

function findPath(node, id, path = []) {
  if (!node || typeof node !== "object") return null;
  const next = [...path, node];
  if (node.id === id) return next;
  for (const c of node.children ?? []) {
    const hit = findPath(c, id, next);
    if (hit) return hit;
  }
  return null;
}

function isShownPath(path) {
  for (let i = 0; i < path.length; i++) {
    const n = path[i];
    if (n.hidden) return false;
    if (n.type === "stack" && path[i + 1] && (n.active ?? n.children?.[0]?.id) !== path[i + 1].id) return false;
  }
  return true;
}

// Decide what ob-tabs.open / ob-tabs.toggle must do before anything changes.
// Missing view -> { notify: { title, body, level }, tabbar: null, show: [], hide: [], select: null, shared: [] }.
export function openPlan({ root, verb, child, intent = null, zen = null, now = Date.now(), statusrow = "ob-statusrow" }) {
  const name = String(child ?? "");
  const path = name ? findPath(root, name) : null;
  const st = path && path.length >= 2 && path[path.length - 2]?.type === "stack" ? path[path.length - 2] : null;
  if (!st) {
    return {
      notify: {
        title: `No panel "${name}" in this layout`,
        body: "Run install.sh again to add the panels the repo has added.",
        level: "warning",
      },
      tabbar: null,
      show: [],
      hide: [],
      select: null,
      shared: [],
    };
  }

  const side = path.length >= 3 ? path[1] : st;
  const show = [];
  const hide = [];
  const shared = [];
  let tabbar = null;

  if (zen?.active) {
    tabbar = 40;
    if (!zen.statusHidden) show.push(statusrow);
    shared.push(["ob.zen", { active: false, at: now }]);
  }

  if (verb === "toggle" && isShownPath(path)) {
    hide.push(side.id);
    return { notify: null, tabbar, show, hide, select: null, shared };
  }

  show.push(side.id);
  for (const anc of path.slice(2)) {
    if (anc.hidden && !show.includes(anc.id)) show.push(anc.id);
  }
  if (intent && intent.startsWith("term:") && intent.length > 5) {
    shared.push(["ob.inspect", { terminal: intent.slice(5), at: now }]);
  }
  shared.push(["ob.focus", { child: name, intent: intent ?? null, at: now }]);

  return {
    notify: null,
    tabbar,
    show,
    hide,
    select: { stack: st.id, child: name },
    shared,
  };
}
