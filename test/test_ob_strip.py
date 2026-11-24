"""mods/ob-strip: each half of a side (its top and bottom stack) has a collapse control of its own, and the strip that
stays visible restores the other half. Which node a strip collapses or restores is decided by mods/ob-strip/halves.js, a
pure function run here through node. The tree is the real layouts/vaultr.json with `hidden` set where a test says."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest

ROOT = home_guard.ROOT
HALVES = os.path.join(ROOT, "mods", "ob-strip", "halves.js")
LAYOUT = os.path.join(ROOT, "layouts", "vaultr.json")

# The four half stacks, and the node each one collapses (its own half, strip included).
HALF_NODES = {"ob-lt-stack": "ob-lt", "ob-lb-stack": "ob-lb-stack", "ob-rt-stack": "ob-rt", "ob-rb-stack": "ob-rb-stack"}


def run_node(code, payload):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def tree(hidden=()):
    with open(LAYOUT) as f:
        root = json.load(f)
    def mark(n):
        if n.get("id") in hidden:
            n["hidden"] = True
        for c in n.get("children") or []:
            mark(c)
    mark(root)
    return root


def action(stack, hidden=()):
    url = "file://" + HALVES
    code = (f'import * as h from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'process.stdout.write(JSON.stringify(h.halfAction(d.tree, d.stack) ?? null));\n')
    return run_node(code, {"tree": tree(hidden), "stack": stack})


class Halves(unittest.TestCase):
    def test_each_half_collapses_its_own_node_when_the_other_half_shows(self):
        for stack, node in HALF_NODES.items():
            with self.subTest(stack=stack):
                self.assertEqual(action(stack), {"kind": "collapse", "node": node})

    def test_the_remaining_strip_restores_a_hidden_top_left_half(self):
        self.assertEqual(action("ob-lb-stack", hidden={"ob-lt"}), {"kind": "restore", "node": "ob-lt"})

    def test_the_remaining_strip_restores_a_hidden_bottom_right_half(self):
        self.assertEqual(action("ob-rt-stack", hidden={"ob-rb-stack"}), {"kind": "restore", "node": "ob-rb-stack"})

    def test_a_hidden_half_has_no_control_of_its_own(self):
        # Its strip is hidden with it, so it offers nothing; the other half's strip offers the restore.
        self.assertIsNone(action("ob-lt-stack", hidden={"ob-lt"}))

    def test_never_offers_to_hide_the_last_half_of_a_side(self):
        for stack, sibling in (("ob-lt-stack", "ob-lb-stack"), ("ob-rb-stack", "ob-rt-stack")):
            with self.subTest(stack=stack):
                got = action(stack, hidden={HALF_NODES[sibling]})
                self.assertNotEqual(got and got.get("kind"), "collapse")

    def test_a_node_that_is_not_a_half_gets_nothing(self):
        self.assertIsNone(action("ob-sessions"))
        self.assertIsNone(action("no-such-stack"))

    def test_every_half_stack_of_the_layout_is_covered_and_its_node_exists(self):
        ids = set()
        def walk(n):
            ids.add(n.get("id"))
            for c in n.get("children") or []:
                walk(c)
        walk(tree())
        for stack, node in HALF_NODES.items():
            with self.subTest(stack=stack):
                self.assertIn(stack, ids)
                self.assertIn(node, ids)


def stand_in(stack, hidden=()):
    url = "file://" + HALVES
    code = (f'import * as h from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'process.stdout.write(JSON.stringify(h.standInFor(d.tree, d.stack) ?? null));\n')
    return run_node(code, {"tree": tree(hidden), "stack": stack})


class StandIn(unittest.TestCase):
    """A top half collapses with its strip, and that strip holds the side's own controls: the window buttons (right)
    and the close-left-sidebar toggle (left). While the top half is hidden, the bottom strip of that side draws them,
    so the window buttons never vanish."""

    def test_the_bottom_right_strip_takes_the_window_buttons_while_the_top_is_hidden(self):
        got = stand_in("ob-rb-stack", hidden={"ob-rt"})
        self.assertTrue(got and got.get("windowButtons"))
        self.assertEqual(got.get("side"), "right")

    def test_the_bottom_left_strip_stands_in_for_the_top_left_strip(self):
        got = stand_in("ob-lb-stack", hidden={"ob-lt"})
        self.assertEqual(got and got.get("stack"), "ob-lt-stack")
        self.assertEqual(got.get("side"), "left")

    def test_no_stand_in_while_the_top_half_shows(self):
        self.assertIsNone(stand_in("ob-rb-stack"))
        self.assertIsNone(stand_in("ob-lb-stack"))

    def test_a_top_strip_never_stands_in(self):
        self.assertIsNone(stand_in("ob-rt-stack", hidden={"ob-rb-stack"}))
        self.assertIsNone(stand_in("ob-sessions"))

    def test_main_js_draws_the_lent_controls(self):
        with open(MAIN) as f:
            src = f.read()
        self.assertIn("const lent = standInFor(root, p.stack);", src)
        self.assertIn("Boolean(p.windowButtons || lent?.windowButtons)", src)
        self.assertIn("const sideToggle = (top || Boolean(lent)) && p.side === \"left\";", src)


STRIP_VIEW = os.path.join(ROOT, "mods", "ob-strip", "strip_view.js")
MAIN = os.path.join(ROOT, "mods", "ob-strip", "main.js")

# Stack children as main.js reads them (id, title from the kit's VIEWS, icon name). Left and right use the same shape.
LEFT_TOP = [{"id": "ob-sessions", "title": "Sessions", "icon": "sessions"},
            {"id": "ob-search", "title": "Search", "icon": "search"},
            {"id": "ob-bookmarks", "title": "Bookmarks", "icon": "bookmark"}]
LEFT_BOTTOM = [{"id": "ob-agents", "title": "Agents", "icon": "bot"},
               {"id": "ob-recent", "title": "Recent", "icon": "history"}]
RIGHT_TOP = [{"id": "ob-props", "title": "Properties", "icon": "info"},
             {"id": "ob-files", "title": "Files", "icon": "folder"},
             {"id": "ob-changes", "title": "Changes", "icon": "git"}]
RIGHT_BOTTOM = [{"id": "ob-graph", "title": "Graph", "icon": "graph"},
                {"id": "ob-outline", "title": "Outline", "icon": "list-tree"}]


def strip_view(payload):
    url = "file://" + STRIP_VIEW
    code = (f'import * as v from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'process.stdout.write(JSON.stringify(v.stripView(d)));\n')
    return run_node(code, payload)


class StripView(unittest.TestCase):
    """The strip's look decision (mods/ob-strip/strip_view.js, pure): label, tooltips, active tab, half control."""

    def test_the_active_panels_name_is_the_strip_label(self):
        got = strip_view({"kids": LEFT_TOP, "active": "ob-search"})
        self.assertEqual(got["label"], "Search")
        got = strip_view({"kids": RIGHT_BOTTOM, "active": "ob-outline"})
        self.assertEqual(got["label"], "Outline")

    def test_without_an_active_child_the_label_is_the_first_panel(self):
        self.assertEqual(strip_view({"kids": LEFT_BOTTOM})["label"], "Agents")

    def test_every_tab_has_a_tooltip_with_its_panel_name(self):
        for kids in (LEFT_TOP, LEFT_BOTTOM, RIGHT_TOP, RIGHT_BOTTOM):
            got = strip_view({"kids": kids, "active": kids[0]["id"]})
            self.assertEqual(len(got["tabs"]), len(kids))
            for tab, kid in zip(got["tabs"], kids):
                with self.subTest(tab=kid["id"]):
                    self.assertEqual(tab["tip"], kid["title"])
                    self.assertTrue(tab["tip"])

    def test_exactly_the_active_tab_is_marked(self):
        got = strip_view({"kids": RIGHT_TOP, "active": "ob-changes"})
        self.assertEqual([t["id"] for t in got["tabs"] if t["active"]], ["ob-changes"])

    def test_only_the_shown_tabs_are_returned_but_the_label_still_names_the_active_one(self):
        got = strip_view({"kids": LEFT_TOP, "shown": LEFT_TOP[:1], "active": "ob-bookmarks"})
        self.assertEqual([t["id"] for t in got["tabs"]], ["ob-sessions"])
        self.assertEqual(got["label"], "Bookmarks")

    def test_collapse_and_restore_controls_have_their_tooltips(self):
        got = strip_view({"kids": LEFT_TOP, "active": "ob-sessions", "half": {"kind": "collapse", "node": "ob-lt"}})
        self.assertEqual(got["half"], {"kind": "collapse", "node": "ob-lt", "tip": "Hide this half"})
        got = strip_view({"kids": LEFT_BOTTOM, "active": "ob-agents", "half": {"kind": "restore", "node": "ob-lt"}})
        self.assertEqual(got["half"], {"kind": "restore", "node": "ob-lt", "tip": "Show the other half"})

    def test_no_half_gives_no_half_control(self):
        self.assertIsNone(strip_view({"kids": LEFT_TOP, "active": "ob-sessions", "half": None})["half"])

    def test_left_and_right_strips_give_the_same_shape(self):
        left = strip_view({"kids": LEFT_TOP, "active": "ob-sessions", "half": {"kind": "collapse", "node": "ob-lt"}})
        right = strip_view({"kids": RIGHT_TOP, "active": "ob-props", "half": {"kind": "collapse", "node": "ob-rt"}})
        self.assertEqual(set(left), set(right))
        self.assertEqual(set(left["tabs"][0]), set(right["tabs"][0]))
        self.assertEqual(set(left["half"]), set(right["half"]))

    def test_main_js_draws_the_strip_from_this_view(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('from "./strip_view.js"', src)
        self.assertIn("stripView(", src)
        self.assertIn(".label", src)
        self.assertIn("view.half.tip", src)

    def test_toggle_left_tooltip_uses_dynamic_bindingFor_not_hardcoded_ctrl_b(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('chordLabel', src.split('from "./kit.js"')[0])
        self.assertIn('bindingFor', src.split('from "./kit.js"')[0])
        self.assertIn('tip("Close left sidebar", "layout.toggle:ob-left")', src)
        self.assertNotIn('tip: "Close left sidebar (Ctrl+B)"', src)



REORDER = os.path.join(ROOT, "mods", "ob-strip", "reorder.js")


def reorder_children(children, from_id, to_id):
    url = "file://" + REORDER
    code = (f'import * as r from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'process.stdout.write(JSON.stringify(r.reorderChildren(d.children, d.fromId, d.toId)));\n')
    return run_node(code, {"children": children, "fromId": from_id, "toId": to_id})


def reorder_stack(root, stack_id, from_id, to_id):
    url = "file://" + REORDER
    code = (f'import * as r from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'const before = JSON.stringify(d.tree);\n'
            'const out = r.reorderStack(d.tree, d.stackId, d.fromId, d.toId);\n'
            'process.stdout.write(JSON.stringify({ out, mutated: JSON.stringify(d.tree) !== before }));\n')
    return run_node(code, {"tree": root, "stackId": stack_id, "fromId": from_id, "toId": to_id})


class Reorder(unittest.TestCase):
    """Pure intra-strip reorder helpers in mods/ob-strip/reorder.js."""

    def test_reorder_children_moves_forward_and_backward_without_mutating_input(self):
        kids = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        fwd = reorder_children(kids, "a", "c")
        self.assertEqual([c["id"] for c in fwd], ["b", "c", "a", "d"])
        bwd = reorder_children(kids, "c", "a")
        self.assertEqual([c["id"] for c in bwd], ["c", "a", "b", "d"])

    def test_reorder_children_preserves_hidden_siblings(self):
        kids = [{"id": "a"}, {"id": "h", "hidden": True}, {"id": "b"}, {"id": "c"}]
        fwd = reorder_children(kids, "a", "b")
        self.assertEqual([c["id"] for c in fwd], ["h", "b", "a", "c"])
        bwd = reorder_children(kids, "b", "a")
        self.assertEqual([c["id"] for c in bwd], ["b", "a", "h", "c"])

    def test_reorder_children_returns_null_on_noop_or_unknown_ids(self):
        kids = [{"id": "a"}, {"id": "b"}]
        self.assertIsNone(reorder_children(kids, "a", "a"))
        self.assertIsNone(reorder_children(kids, "a", "missing"))
        self.assertIsNone(reorder_children(kids, "missing", "a"))
        self.assertIsNone(reorder_children(None, "a", "b"))

    def test_reorder_stack_updates_target_stack_and_preserves_other_stacks_and_active(self):
        base = tree()
        res = reorder_stack(base, "ob-lt-stack", "ob-sessions", "ob-bookmarks")
        self.assertFalse(res["mutated"])
        out = res["out"]
        self.assertIsNotNone(out)

        def find(n, nid):
            if n.get("id") == nid:
                return n
            for c in n.get("children") or []:
                hit = find(c, nid)
                if hit:
                    return hit
            return None

        lt = find(out, "ob-lt-stack")
        self.assertEqual([c["id"] for c in lt["children"]], ["ob-search", "ob-bookmarks", "ob-sessions"])
        self.assertEqual(lt["active"], "ob-sessions")
        lb = find(out, "ob-lb-stack")
        self.assertEqual([c["id"] for c in lb["children"]], ["ob-agents", "ob-recent"])

    def test_reorder_stack_preserves_implicit_first_active_when_active_omitted(self):
        custom = {
            "id": "root",
            "type": "stack",
            "children": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        }
        res = reorder_stack(custom, "root", "a", "c")
        self.assertFalse(res["mutated"])
        self.assertEqual([c["id"] for c in res["out"]["children"]], ["b", "c", "a"])
        self.assertEqual(res["out"]["active"], "a")

    def test_reorder_stack_rejects_non_stack_or_cross_stack_ids(self):
        base = tree()
        self.assertIsNone(reorder_stack(base, "ob-lt", "ob-lt-strip", "ob-lt-stack")["out"])
        self.assertIsNone(reorder_stack(base, "ob-lt-stack", "ob-sessions", "ob-agents")["out"])
        self.assertIsNone(reorder_stack(base, "no-stack", "ob-sessions", "ob-search")["out"])

    def test_move_between_stacks_supports_left_right_top_bottom_and_insert_slot(self):
        url = "file://" + os.path.join(ROOT, "mods", "ob-strip", "reorder.js")
        code = (
            f'import * as R from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'const before = JSON.stringify(d.tree);\n'
            'const leftToRight = R.moveBetweenStacks(d.tree, "ob-sessions", "ob-rt-stack", "ob-props");\n'
            'const topToBottom = R.moveBetweenStacks(leftToRight, "ob-search", "ob-lb-stack", null);\n'
            'let emptySource = topToBottom;\n'
            'const findLt = (n) => n?.id === "ob-lt-stack" ? n : (n?.children ?? []).reduce((a, c) => a || findLt(c), null);\n'
            'for (const c of [...findLt(emptySource).children]) emptySource = R.moveBetweenStacks(emptySource, c.id, "ob-rb-stack", "ob-outline");\n'
            'const backIntoEmpty = R.moveBetweenStacks(emptySource, "ob-agents", "ob-lt-stack", null);\n'
            'const activeOk = R.activeStripDrag({ fromStack: "ob-lt-stack", childId: "ob-sessions", at: 1000 }, 5000);\n'
            'const activeStale = R.activeStripDrag({ fromStack: "ob-lt-stack", childId: "ob-sessions", at: 1000 }, 40000);\n'
            'process.stdout.write(JSON.stringify({ mutated: JSON.stringify(d.tree) !== before, leftToRight, topToBottom, emptySource, backIntoEmpty, activeOk, activeStale }));\n'
        )
        base = tree()
        res = run_node(code, {"tree": base})
        self.assertFalse(res["mutated"])

        def kids(root, sid):
            def find(n):
                if n.get("id") == sid:
                    return n
                for c in n.get("children") or []:
                    h = find(c)
                    if h:
                        return h
                return None
            st = find(root)
            return ([c["id"] for c in st["children"]], st.get("active"))

        orig_lt, _ = kids(base, "ob-lt-stack")
        exp_after_lr = [x for x in orig_lt if x != "ob-sessions"]
        self.assertEqual(kids(res["leftToRight"], "ob-lt-stack"), (exp_after_lr, exp_after_lr[0]))
        rt_ids, rt_act = kids(res["leftToRight"], "ob-rt-stack")
        self.assertEqual(rt_ids[rt_ids.index("ob-props") - 1], "ob-sessions")
        self.assertEqual(rt_act, "ob-sessions")

        self.assertEqual(kids(res["topToBottom"], "ob-lb-stack"), (["ob-agents", "ob-recent", "ob-search"], "ob-search"))
        self.assertEqual(kids(res["emptySource"], "ob-lt-stack"), ([], None))
        rb_ids, rb_act = kids(res["emptySource"], "ob-rb-stack")
        self.assertIn("ob-bookmarks", rb_ids)
        self.assertEqual(rb_ids[-1], "ob-outline")
        self.assertEqual(rb_act, "ob-bookmarks")
        self.assertEqual(kids(res["backIntoEmpty"], "ob-lt-stack"), (["ob-agents"], "ob-agents"))
        self.assertEqual(res["activeOk"], {"fromStack": "ob-lt-stack", "childId": "ob-sessions", "at": 1000})
        self.assertIsNone(res["activeStale"])


class StripDragWiring(unittest.TestCase):
    """End-to-end Strip render & pointer wiring in node with stubbed gpui/herdr."""

    def _run_strip(self, script_body):
        import tempfile
        from pathlib import Path
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node is not installed")
        with tempfile.TemporaryDirectory(prefix="ob-strip-drag-") as folder:
            mod_dir = Path(folder)
            for name in ("main.js", "halves.js", "strip_view.js", "reorder.js"):
                txt = Path(ROOT, "mods", "ob-strip", name).read_text(encoding="utf-8")
                txt = (txt
                       .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                       .replace('from "gpui-base"', 'from "./gpui-base.js"')
                       .replace('from "herdr"', 'from "./herdr.js"'))
                (mod_dir / name).write_text(txt, encoding="utf-8")
            (mod_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (mod_dir / "gpui-kit.js").write_text(
                "export class View {}\n"
                "export const elements = new Map();\n"
                "export function makeEl() {\n"
                "  const rec = { id: null, handlers: { down: {}, up: {}, winUp: {}, move: [], winMove: [], hover: [], click: [] }, children: [] };\n"
                "  const p = new Proxy(() => p, {\n"
                "    get(_t, prop) {\n"
                "      if (prop === '__rec') return rec;\n"
                "      if (prop === 'id') return (v) => { rec.id = v; elements.set(v, rec); return p; };\n"
                "      if (prop === 'when') return (c, fn) => { if (c) fn(p); return p; };\n"
                "      if (prop === 'child') return (c) => { if (c) rec.children.push(c); return p; };\n"
                "      if (prop === 'children') return (arr) => { for (const c of arr ?? []) if (c) rec.children.push(c); return p; };\n"
                "      if (prop === 'on_mouse_down') return (btn, fn) => { (rec.handlers.down[btn] ??= []).push(fn); return p; };\n"
                "      if (prop === 'on_mouse_up') return (btn, fn) => { (rec.handlers.up[btn] ??= []).push(fn); return p; };\n"
                "      if (prop === 'on_window_mouse_up') return (btn, fn) => { (rec.handlers.winUp[btn] ??= []).push(fn); return p; };\n"
                "      if (prop === 'on_mouse_move') return (fn) => { rec.handlers.move.push(fn); return p; };\n"
                "      if (prop === 'on_window_mouse_move') return (fn) => { rec.handlers.winMove.push(fn); return p; };\n"
                "      if (prop === 'on_hover') return (fn) => { rec.handlers.hover.push(fn); return p; };\n"
                "      if (prop === 'on_click') return (fn) => { rec.handlers.click.push(fn); return p; };\n"
                "      return () => p;\n"
                "    },\n"
                "  });\n"
                "  return p;\n"
                "}\n"
                "export const div = () => makeEl();\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-base.js").write_text(
                'import { makeEl } from "./gpui-kit.js";\nexport const h_flex = () => makeEl();\n',
                encoding="utf-8",
            )
            (mod_dir / "herdr.js").write_text(
                f"export const state = {{ layout: {json.dumps(tree())}, props: {{ stack: 'ob-lt-stack', side: 'left', place: 'top' }}, runs: [], shared: {{}}, sharedWrites: [] }};\n"
                "export const layout = () => state.layout;\n"
                "export const props = () => state.props;\n"
                "export const run = (cmd, args) => { state.runs.push([cmd, args]); if (cmd === 'layout.set' && args?.layout) state.layout = args.layout; };\n"
                "export const nextCommand = () => new Promise(() => {});\n"
                "export const settings = () => ({ zoom: 1 });\n"
                "export const agents = () => [];\n"
                "export const terminals = () => [];\n"
                "export const shared = (k) => state.shared[k];\n"
                "export const setShared = (k, v) => { state.sharedWrites.push([k, v]); state.shared[k] = v; };\n"
                "export const window = () => ({ platform: 'linux', buttons: false });\n",
                encoding="utf-8",
            )
            (mod_dir / "kit.js").write_text(
                'import { makeEl } from "./gpui-kit.js";\n'
                "export const S = { pad: 8, tab: 28, textXs: 11, textSm: 12, radius: 4 };\n"
                "export const NODE = { left: 'ob-left', right: 'ob-right', leftTop: 'ob-lt', leftTopStack: 'ob-lt-stack', leftBottomStack: 'ob-lb-stack', rightTop: 'ob-rt', rightTopStack: 'ob-rt-stack', rightBottomStack: 'ob-rb-stack' };\n"
                "export const icon = () => makeEl();\n"
                "export const iconButton = (o) => makeEl().id(o.id);\n"
                "export const stripTab = (o) => makeEl().id(o.id).on_mouse_down('left', (_e, cx) => cx.stop_propagation());\n"
                "export const viewInfo = (n) => ({ title: n.id, icon: 'info' });\n"
                "export function findNode(n, id) { if (!n) return null; if (n.id === id) return n; for (const c of n.children ?? []) { const f = findNode(c, id); if (f) return f; } return null; }\n"
                "export function findParent(n, id, p = null) { if (!n) return null; if (n.id === id) return p; for (const c of n.children ?? []) { const f = findParent(c, id, n); if (f) return f; } return null; }\n"
                "export const openMenu = () => {};\n"
                "export const subagentCounts = () => ({ live: 0, total: 0 });\n"
                "export const alpha = () => '#000';\n"
                "export const stop = (_e, cx) => cx?.stop_propagation?.();\n"
                "export const tc = () => ({ raised: '#111', border: '#222', dim: '#333', accent: '#444', foreground: '#fff', blocked: '#f00' });\n"
                "export const agentAttention = () => null;\n"
                "export const attentionCounts = () => ({ blocked: 0 });\n"
                "export const getDismissed = () => ({});\n"
                "export const terminalsByAddress = () => new Map();\n"
                "export const chordLabel = (k) => k;\n"
                "export const bindingFor = () => null;\n"
                "export const lightsLeftPad = (p) => p;\n",
                encoding="utf-8",
            )
            code = (
                f'import Strip from "{(mod_dir / "main.js").as_uri()}";\n'
                f'import {{ elements }} from "{(mod_dir / "gpui-kit.js").as_uri()}";\n'
                f'import {{ state }} from "{(mod_dir / "herdr.js").as_uri()}";\n'
                "const timers = [];\n"
                "const cx = { spawn: () => {}, notify: () => {}, stop_propagation: () => {}, timer: { after: (_ms, fn) => timers.push(fn) } };\n"
                "const flushTimers = () => { while (timers.length) timers.shift()(cx); };\n"
                "const s = new Strip();\n"
                "s.init({}, cx);\n"
                "const fire = (id, kind, btn = 'left') => {\n"
                "  const rec = elements.get(id);\n"
                "  if (!rec) throw new Error('missing element ' + id);\n"
                "  const list = kind === 'down' || kind === 'up' ? (rec.handlers[kind][btn] ?? []) : rec.handlers[kind];\n"
                "  for (const fn of list) fn({}, cx);\n"
                "};\n"
                + script_body
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            return json.loads(res.stdout)

    def test_drag_tab_reorders_stack_and_persists_via_layout_set(self):
        got = self._run_strip("""
            s.render();
            fire('tab-ob-sessions', 'down');
            fire('tab-ob-bookmarks', 'move');
            fire('tab-ob-bookmarks', 'up');
            const lt = state.layout.children[0].children[0].children[0].children[1];
            console.log(JSON.stringify({ runs: state.runs.map(([c]) => c), order: lt.children.map((c) => c.id), active: lt.active }));
        """)
        self.assertEqual(got["runs"], ["layout.set"])
        self.assertEqual(got["order"], ["ob-search", "ob-bookmarks", "ob-sessions"])
        self.assertEqual(got["active"], "ob-sessions")

    def test_click_tab_without_drag_selects_without_layout_set(self):
        got = self._run_strip("""
            s.render();
            fire('tab-ob-search', 'down');
            fire('tab-ob-search', 'up');
            console.log(JSON.stringify({ runs: state.runs }));
        """)
        self.assertEqual(got["runs"], [["layout.select", {"stack": "ob-lt-stack", "child": "ob-search"}]])

    def test_drag_cancelled_on_strip_leave_makes_no_layout_call(self):
        got = self._run_strip("""
            s.render();
            fire('tab-ob-sessions', 'down');
            fire('tab-ob-bookmarks', 'move');
            for (const fn of elements.get('strip').handlers.hover) fn(false, cx);
            fire('tab-ob-bookmarks', 'up');
            console.log(JSON.stringify({ runs: state.runs }));
        """)
        self.assertEqual(got["runs"], [])

    def test_reorder_command_persists_new_order(self):
        got = self._run_strip("""
            await s.command('reorder:ob-bookmarks@ob-sessions', cx);
            const lt = state.layout.children[0].children[0].children[0].children[1];
            console.log(JSON.stringify({ runs: state.runs.map(([c]) => c), order: lt.children.map((c) => c.id) }));
        """)
        self.assertEqual(got["runs"], ["layout.set"])
        self.assertEqual(got["order"], ["ob-bookmarks", "ob-sessions", "ob-search"])

    def test_cross_strip_drag_left_to_right_and_top_to_bottom_and_cancel(self):
        got = self._run_strip("""
            const find = (n, id) => { if (!n) return null; if (n.id === id) return n; for (const c of n.children ?? []) { const h = find(c, id); if (h) return h; } return null; };
            // 1) Plain click makes zero setShared writes.
            s.render();
            fire('tab-ob-search', 'down');
            fire('tab-ob-search', 'up');
            const clickWrites = state.sharedWrites.length;
            state.runs.length = 0;

            // 2) Left-top -> Right-top onto a specific tab (even when source winUp fires BEFORE target up!).
            s.render();
            fire('tab-ob-sessions', 'down');
            for (const fn of elements.get('strip').handlers.winMove) fn({ position: { x: 100, y: 20 } }, cx);
            const dragWhileMoving = state.shared['ob.stripDrag'];
            const srcWinUp = elements.get('strip').handlers.winUp.left;

            const rt = new Strip();
            state.props = { stack: 'ob-rt-stack', side: 'right', place: 'top' };
            rt.init({}, cx);
            rt.render();
            for (const fn of elements.get('strip').handlers.hover) fn(true, cx);
            fire('tab-ob-props', 'move');
            // Simulate source strip receiving window_mouse_up BEFORE target strip receives mouse_up:
            state.props = { stack: 'ob-lt-stack', side: 'left', place: 'top' };
            for (const fn of srcWinUp) fn({}, cx);
            state.props = { stack: 'ob-rt-stack', side: 'right', place: 'top' };
            fire('tab-ob-props', 'up');
            flushTimers();
            const afterLR = {
              lt: find(state.layout, 'ob-lt-stack').children.map((c) => c.id),
              rt: find(state.layout, 'ob-rt-stack').children.map((c) => c.id),
              rtActive: find(state.layout, 'ob-rt-stack').active,
              dragCleared: state.shared['ob.stripDrag'],
            };

            // 3) Left-top -> Left-bottom dropped on empty strip bar (appends).
            state.props = { stack: 'ob-lt-stack', side: 'left', place: 'top' };
            s.render();
            fire('tab-ob-bookmarks', 'down');
            for (const fn of elements.get('strip').handlers.hover) fn(false, cx);
            const lb = new Strip();
            state.props = { stack: 'ob-lb-stack', side: 'left', place: 'bottom' };
            lb.init({}, cx);
            lb.render();
            for (const fn of elements.get('strip').handlers.hover) fn(true, cx);
            fire('strip', 'up');
            flushTimers();
            const afterTB = {
              lt: find(state.layout, 'ob-lt-stack').children.map((c) => c.id),
              lb: find(state.layout, 'ob-lb-stack').children.map((c) => c.id),
              lbActive: find(state.layout, 'ob-lb-stack').active,
            };

            // 4) Drag released outside any strip cancels cleanly on window_mouse_up.
            state.runs.length = 0;
            state.props = { stack: 'ob-lt-stack', side: 'left', place: 'top' };
            s.render();
            fire('tab-ob-search', 'down');
            for (const fn of elements.get('strip').handlers.hover) fn(false, cx);
            for (const fn of elements.get('strip').handlers.winUp.left) fn({}, cx);
            flushTimers();
            console.log(JSON.stringify({ clickWrites, dragWhileMoving, afterLR, afterTB, cancelRuns: state.runs, cancelDrag: state.shared['ob.stripDrag'] }));
        """)
        self.assertEqual(got["clickWrites"], 0)
        self.assertEqual(got["dragWhileMoving"]["fromStack"], "ob-lt-stack")
        self.assertEqual(got["dragWhileMoving"]["childId"], "ob-sessions")
        self.assertNotIn("ob-sessions", got["afterLR"]["lt"])
        self.assertEqual(got["afterLR"]["rt"][got["afterLR"]["rt"].index("ob-props") - 1], "ob-sessions")
        self.assertEqual(got["afterLR"]["rtActive"], "ob-sessions")
        self.assertIsNone(got["afterLR"]["dragCleared"])
        self.assertNotIn("ob-bookmarks", got["afterTB"]["lt"])
        self.assertEqual(got["afterTB"]["lb"], ["ob-agents", "ob-recent", "ob-bookmarks"])
        self.assertEqual(got["afterTB"]["lbActive"], "ob-bookmarks")
        self.assertEqual(got["cancelRuns"], [])
        self.assertIsNone(got["cancelDrag"])

    def test_close_and_show_panel_via_command_middle_click_and_menu(self):
        got = self._run_strip("""
            const find = (n, id) => { if (!n) return null; if (n.id === id) return n; for (const c of n.children ?? []) { const h = find(c, id); if (h) return h; } return null; };
            state.props = { stack: 'ob-rt-stack', side: 'right', place: 'top' };
            s.render();
            // 1) Close an inactive panel (ob-files): only hides it, does not switch active (ob-quotas).
            await s.command('close:ob-files', cx);
            const inactiveRuns = [...state.runs];
            state.runs.length = 0;

            // 2) Middle-click active panel (ob-quotas): hides it and advances active to next visible sibling.
            fire('tab-ob-quotas', 'down', 'middle');
            const activeRuns = [...state.runs];
            state.runs.length = 0;

            // 3) Show a hidden panel: unhides and selects it.
            find(state.layout, 'ob-files').hidden = true;
            await s.command('show:ob-files', cx);
            const showRuns = [...state.runs];
            console.log(JSON.stringify({ inactiveRuns, activeRuns, showRuns }));
        """)
        self.assertEqual(got["inactiveRuns"], [["layout.hide", {"id": "ob-files"}]])
        self.assertEqual(got["activeRuns"][0], ["layout.hide", {"id": "ob-quotas"}])
        self.assertEqual(got["activeRuns"][1][0], "layout.select")
        self.assertEqual(got["activeRuns"][1][1]["stack"], "ob-rt-stack")
        self.assertNotEqual(got["activeRuns"][1][1]["child"], "ob-quotas")
        self.assertEqual(
            got["showRuns"],
            [
                ["layout.show", {"id": "ob-files"}],
                ["layout.select", {"stack": "ob-rt-stack", "child": "ob-files"}],
            ],
        )

    def test_real_strip_tab_skips_left_click_handlers_when_onClick_omitted(self):
        import tempfile
        from pathlib import Path
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            mod_dir = Path(tmp)
            for p in Path(ROOT, "kit").glob("*.js"):
                shutil.copy2(p, mod_dir / p.name)
            (mod_dir / "kit.js").write_text(
                (mod_dir / "kit.js").read_text(encoding="utf-8")
                .replace('"gpui-kit"', '"./gpui-kit.js"')
                .replace('"gpui-base"', '"./gpui-base.js"')
                .replace('"herdr"', '"./herdr.js"'),
                encoding="utf-8",
            )
            (mod_dir / "gpui-kit.js").write_text(
                "export const elements = new Map();\n"
                "export function makeEl() {\n"
                "  const rec = { id: null, downLeft: 0, clicks: 0 };\n"
                "  const p = new Proxy({}, {\n"
                "    get(_t, k) {\n"
                "      if (k === 'id') return (v) => { rec.id = v; elements.set(v, rec); return p; };\n"
                "      if (k === 'when') return (cond, fn) => { if (cond) fn(p); return p; };\n"
                "      if (k === 'on_mouse_down') return (btn, _fn) => { if (btn === 'left') rec.downLeft++; return p; };\n"
                "      if (k === 'on_click') return (_fn) => { rec.clicks++; return p; };\n"
                "      return () => p;\n"
                "    },\n"
                "  });\n"
                "  return p;\n"
                "}\n"
                "export const div = () => makeEl();\n"
                "export const svg = () => makeEl();\n"
                "export const image = () => makeEl();\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-base.js").write_text(
                'import { makeEl } from "./gpui-kit.js";\n'
                "export const h_flex = () => makeEl();\n"
                "export const v_flex = () => makeEl();\n",
                encoding="utf-8",
            )
            (mod_dir / "herdr.js").write_text(
                "export const theme = () => ({ foreground: '#fff', dim: '#888', selected: '#222', hover: '#333', muted: '#aaa', accent: '#09f', accent_foreground: '#000' });\n"
                "export const shared = () => ({});\n"
                "export const setShared = () => {};\n"
                "export const layout = () => ({});\n"
                "export const run = () => {};\n"
                "export const openOverlay = () => {};\n"
                "export const closeOverlay = () => {};\n"
                "export const exec = async () => ({ code: 0, stdout: '' });\n"
                "export const readTextFile = async () => null;\n"
                "export const home = () => '/srv/home';\n"
                "export const appHome = () => '/app';\n"
                "export const keys = () => [];\n"
                "export const spaces = () => [];\n"
                "export const agents = () => [];\n"
                "export const panes = () => [];\n"
                "export const terminals = () => [];\n"
                "export const focused = () => null;\n"
                "export const window = () => ({ platform: 'linux' });\n",
                encoding="utf-8",
            )
            code = (
                f'import {{ stripTab }} from "{(mod_dir / "kit.js").as_uri()}";\n'
                f'import {{ elements }} from "{(mod_dir / "gpui-kit.js").as_uri()}";\n'
                "stripTab({ id: 'drag-tab', icon: 'info', title: 'Drag' });\n"
                "stripTab({ id: 'click-tab', icon: 'info', title: 'Click', onClick: () => {} });\n"
                "console.log(JSON.stringify({ drag: elements.get('drag-tab'), click: elements.get('click-tab') }));\n"
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
        self.assertEqual(got["drag"], {"id": "drag-tab", "downLeft": 0, "clicks": 0})
        self.assertEqual(got["click"], {"id": "click-tab", "downLeft": 1, "clicks": 1})

if __name__ == "__main__":
    unittest.main()
