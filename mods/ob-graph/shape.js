// ob-graph tab shape and dot palette: pure, no Herdr or gpui imports (test/test_ob_graph.py runs it under node).
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

// Machines and spaces are the graph's fixed-size anchors (sim.js FRAME_RADIUS): drawn as round accent dots like every
// other node (`scale: 1`), with fixed stronger accent tones (`0.92` for a machine, `0.78` for a space; `null` leaves the
// tone to `dotTone`) and labels that are always shown rather than fading in with zoom.
export function framePaint(kind) {
  if (kind === "m") return { scale: 1, tone: 0.92, label: true };
  if (kind === "s") return { scale: 1, tone: 0.78, label: true };
  return { scale: 1, tone: null, label: false };
}

// Idle accent opacity for non-frame dots (`p`, `r`, `c`, `h`, `n`, `a`) by settled radius (`sim.js` BASE_RADIUS = 3,
// MAX_RADIUS = 11): hubs (`r >= 7`) at 0.95, connected nodes (`r > 3.5`) at 0.75, and leaves at 0.55.
export function dotTone(r) {
  if (r >= 7) return 0.95;
  if (r > 3.5) return 0.75;
  return 0.55;
}
