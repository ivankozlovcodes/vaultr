// ob-graph tab shape: pure, no Herdr or gpui imports (test/test_ob_graph.py runs it under node).
//
// A tab has no node of its own. Its panes are nodes (key p:<pane>), each labelled by the caller (kit paneLabel), and the
// panes of one tab are joined in a chain by sibling links. A sibling link is a spring the simulation pulls with and
// nothing draws, so a tab reads as a small cluster (like a folder in Obsidian's graph). A pane keeps its key whatever its
// tab holds, so adding or closing a pane does not move the pane that stays.
//
// paneShape(tabId, panes): panes = [{ pane, label }] in order. Returns { nodes: [{ key, kind: "p", label, pane }],
// edges: [[a, b, "sibling"]] }. Two panes with the same label get a number each ("Claude Code 1", "Claude Code 2").

export function paneLabels(labels) {
  const base = labels.map((l) => (typeof l === "string" && l.trim() ? l.trim() : "Terminal"));
  const count = new Map();
  for (const b of base) count.set(b, (count.get(b) ?? 0) + 1);
  return base.map((b, i) => (count.get(b) > 1 ? `${b} ${i + 1}` : b));
}

export function paneShape(tabId, panes) {
  const list = panes ?? [];
  const labels = paneLabels(list.map((p) => p.label));
  const nodes = list.map((p, i) => ({ key: `p:${p.pane}`, kind: "p", label: labels[i], pane: p.pane }));
  const edges = [];
  for (let i = 1; i < list.length; i++) edges.push([`p:${list[i - 1].pane}`, `p:${list[i].pane}`, "sibling"]);
  return { tab: tabId ?? null, nodes, edges };
}

// placeSubs(subs, paneOf): where each sub-agent hangs. subs = [{ key, parentAddr, machine, ... }], paneOf = Map(terminal
// address -> pane key). The parent is the pane of parentAddr, else the hc child at that address (h:<address>, itself
// in subs, in any order: nested hc children), else the machine (m:<machine or local>). Returns the subs in order, each
// with parent and edge ("link" to a session, "contain" to a machine). A cycle of hc children falls back to the machine.
export function placeSubs(subs, paneOf) {
  const list = subs ?? [];
  const keys = new Set(list.map((s) => s.key));
  const at = new Map();                                    // key -> parent key, or null for the machine
  let pending = list;
  for (let grew = true; grew && pending.length;) {
    grew = false;
    const next = [];
    for (const s of pending) {
      const pane = s.parentAddr ? paneOf.get(s.parentAddr) : null;
      const hk = s.parentAddr ? `h:${s.parentAddr}` : null;
      const viaHc = hk && hk !== s.key && keys.has(hk);
      if (pane) at.set(s.key, pane);
      else if (viaHc && at.has(hk)) at.set(s.key, hk);
      else if (viaHc) { next.push(s); continue; }
      else at.set(s.key, null);
      grew = true;
    }
    pending = next;
  }
  return list.map((s) => {
    const p = at.get(s.key) ?? null;
    return { ...s, parent: p ?? `m:${s.machine ?? "local"}`, edge: p ? "link" : "contain" };
  });
}

// The argv that opens a plain file in an editor pane. `editor` is obsidian.json's `editor` (a command and its arguments,
// as the Notes mod reads it); anything else is not an editor. Without one: $VISUAL, then $EDITOR (often unset in a pane:
// they live in the person's shell profile), then the first of nvim, vim, nano, vi that is installed.
const PICK = 'e="${VISUAL:-$EDITOR}"; if [ -z "$e" ]; then for c in nvim vim nano vi; do '
  + 'if command -v "$c" >/dev/null 2>&1; then e=$c; break; fi; done; fi; exec ${e:-vi} "$1"';

export function editorArgv(editor, path) {
  if (Array.isArray(editor) && editor.length && editor.every((x) => typeof x === "string" && x)) return [...editor, path];
  return ["sh", "-c", PICK, "editor", path];
}

// The toolbar (main.js): Local/Global/Active only, Notes/Artifacts and the zoom buttons are about 415 px in one row. In a
// narrower panel the zoom buttons go on a second row rather than off the edge. A width of 0 (before the first layout) is
// one row. toolbarBottom is the y below which the canvas begins: top 6 + a 26 px row (+ 4 gap + 26 for a second row).
export const TOOLBAR_WIDE = 430;
export function toolbarRows(width) { return width > 0 && width < TOOLBAR_WIDE ? 2 : 1; }
export function toolbarBottom(rows) { return 6 + 26 + (rows === 2 ? 30 : 0) + 4; }

// How machines and spaces are drawn so they stand out from the dots (panes, agents) and squares (artifacts): a diamond for a
// machine, a hexagon for a space (`scale`: how far the corners reach beyond the node's radius, so the shapes weigh about as
// much as a dot), a stronger colour (`tone`: the opacity of the foreground colour; null: the node's usual colour), and a
// label that is always shown rather than fading in with zoom.
export function framePaint(kind) {
  if (kind === "m") return { shape: "diamond", scale: 1.3, tone: 0.9, label: true };
  if (kind === "s") return { shape: "hexagon", scale: 1.1, tone: 0.7, label: true };
  return { shape: null, scale: 1, tone: null, label: false };
}

// The corners of a shape around (x, y), `r` from the centre to a corner: [[x, y], ...] (empty for no shape).
export function shapePoints(shape, x, y, r) {
  if (shape === "diamond") return [[x, y - r], [x + r, y], [x, y + r], [x - r, y]];
  if (shape === "hexagon") return Array.from({ length: 6 }, (_, i) => { const a = (Math.PI / 3) * i - Math.PI / 2; return [x + r * Math.cos(a), y + r * Math.sin(a)]; });
  return [];
}

// Agents are coloured by the program that runs them, so claude, pi, codex and antigravity (agy) tell apart at a glance.
// By the program's table key (Herdr's: "claude", "pi", ...); a Claude Code sub-agent (kind c) is claude's and a pi run
// (kind r) is pi's. A program the table does not know uses its own `color` when that is a #rrggbb. A pane that is not an
// agent (a shell, an editor), and every other kind of node, has none (null): its usual colour.
const AGENT_HUES = {
  claude: "#d97757", pi: "#8b7cf6", codex: "#10a37f", antigravity: "#4a90e2", gemini: "#8e75b2", opencode: "#e8a33d",
  amp: "#f2594b", copilot: "#6e9bf0", cursor: "#9aa0a6", crush: "#d65db1", kiro: "#9b6dff",
};
const AGENT_ALIAS = { "claude-code": "claude", agy: "antigravity", "gemini-cli": "gemini", "codex-cli": "codex" };
export function agentHue(n) {
  if (!n) return null;
  if (n.kind === "c") return AGENT_HUES.claude;
  if (n.kind === "r") return AGENT_HUES.pi;
  const pr = n.program;
  if (n.kind !== "p" || !pr?.agent) return null;
  const key = String(pr.key ?? "").toLowerCase();
  const known = AGENT_HUES[AGENT_ALIAS[key] ?? key];
  if (known) return known;
  return typeof pr.color === "string" && /^#[0-9a-f]{6}$/i.test(pr.color) ? pr.color : null;
}
