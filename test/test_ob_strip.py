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


if __name__ == "__main__":
    unittest.main()
