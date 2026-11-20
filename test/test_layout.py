"""layouts/vaultr.json: it parses, its ids are unique, every block names a mod that exists (or one of Herdr's shipped
mods), each stack's active child is one of its children, and the four side stacks hold the panels the README lists."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
LAYOUT = os.path.join(ROOT, "layouts", "vaultr.json")
MODS = os.path.join(ROOT, "mods")
NODE = shutil.which("node")
# Herdr's own mods, used by the layout but not shipped in mods/
SHIPPED = {"files", "changes"}


def walk(node):
    yield node
    for child in node.get("children") or []:
        yield from walk(child)


def dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from dicts(v)


def mod_refs(layout):
    return [d["mod"] for d in dicts(layout) if isinstance(d.get("mod"), str)]


def find(node, node_id):
    return next(n for n in walk(node) if n.get("id") == node_id)


def ancestors(node, target, path=()):
    """The ids from the root down to target's parent (target excluded), or None when target is not under node."""
    if node.get("id") == target.get("id") and node is target:
        return list(path)
    for child in node.get("children") or []:
        found = ancestors(child, target, path + (node.get("id"),))
        if found is not None:
            return found
    return None


def hideable_ids():
    """Every node id kit/kit.js names (NODE), except the ones no toggle or Zen hides: the centre column, the tab
    bar and the tab area. ob-tabs' Zen and the side toggles hide only nodes named there (N = NODE)."""
    with open(os.path.join(ROOT, "kit", "kit.js"), encoding="utf-8") as f:
        src = f.read()
    block = re.search(r"export const NODE = \{(.*?)\};", src, re.S).group(1)
    return set(re.findall(r'"(ob-[a-z-]+)"', block)) - {"ob-center", "ob-tabbar", "ob-main"}


def run_kit(body, layout_tree=None):
    folder = tempfile.mkdtemp(prefix="kit-layout-")
    try:
        for fp in Path(ROOT, "kit").glob("*.js"):
            text = fp.read_text(encoding="utf-8")
            if fp.name == "kit.js":
                text = (text.replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                            .replace('from "gpui-base"', 'from "./gpui-base.js"')
                            .replace('from "herdr"', 'from "./herdr.js"'))
            (Path(folder) / fp.name).write_text(text, encoding="utf-8")
        (Path(folder) / "gpui-kit.js").write_text(
            "const el = () => new Proxy(() => el(), { get: () => el }); export const div = el, svg = el, image = el;\n",
            encoding="utf-8",
        )
        (Path(folder) / "gpui-base.js").write_text(
            "const el = () => new Proxy(() => el(), { get: () => el }); export const h_flex = el, v_flex = el;\n",
            encoding="utf-8",
        )
        (Path(folder) / "herdr.js").write_text(
            f"const LAYOUT = {json.dumps(layout_tree or {})};\n"
            "export const theme = () => ({});\n"
            "export const run = () => {};\n"
            "export const exec = async () => ({ code: 0, stdout: '' });\n"
            "export const openOverlay = () => {};\n"
            "export const closeOverlay = () => {};\n"
            "export const layout = () => LAYOUT;\n"
            "export const shared = () => undefined;\n"
            "export const setShared = () => {};\n"
            "export const keys = () => [];\n"
            "export const spaces = () => [];\n"
            "export const agents = () => [];\n"
            "export const terminals = () => [];\n"
            "export const panes = () => [];\n"
            "export const focused = () => null;\n"
            "export const home = () => '/srv/home';\n"
            "export const appHome = () => '/app';\n"
            "export const readTextFile = async () => null;\n"
            "export const window = () => ({ platform: 'linux' });\n",
            encoding="utf-8",
        )
        script = (
            f'import * as K from "{(Path(folder) / "kit.js").as_uri()}";\n'
            f'const r = (() => {{ {body} }})();\n'
            'console.log(JSON.stringify(r));\n'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LAYOUT, encoding="utf-8") as f:
            cls.layout = json.load(f)

    def test_parses_and_has_its_preview(self):
        self.assertEqual(self.layout["id"], "root")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, self.layout["preview"])))

    def test_node_ids_are_unique(self):
        ids = [d["id"] for d in dicts(self.layout) if "id" in d]
        self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [])

    def test_blocks_name_mods(self):
        # ob-main's block is the tab area: it names no mod, its pane header does. Every other block names one.
        no_mod = [n["id"] for n in walk(self.layout) if n.get("type") == "block"
                  and not isinstance((n.get("content") or {}).get("mod"), str)]
        self.assertEqual(no_mod, ["ob-main"])
        for name in mod_refs(self.layout):
            if name in SHIPPED:
                continue
            self.assertTrue(os.path.isfile(os.path.join(MODS, name, "main.js")), f"{name} is not in mods/")

    def test_only_shipped_mods_come_from_outside(self):
        outside = {m for m in mod_refs(self.layout) if not os.path.isdir(os.path.join(MODS, m))}
        self.assertEqual(outside, SHIPPED)

    def test_stack_active_is_a_child(self):
        stacks = [n for n in walk(self.layout) if n.get("type") == "stack"]
        self.assertEqual(len(stacks), 4)
        for s in stacks:
            ids = [c["id"] for c in s["children"]]
            self.assertIn(s.get("active"), ids, s["id"])

    def test_side_stacks_hold_the_listed_panels(self):
        # (mods in order, the mod that opens first); top before bottom, in each column
        expected = {
            "ob-left": [(["ob-sessions", "ob-search", "ob-bookmarks"], "ob-sessions"),
                        (["ob-agents", "ob-recent"], "ob-agents")],
            "ob-right": [(["ob-quotas", "ob-props", "files", "changes", "insights", "obsidian"], "ob-quotas"),
                         (["ob-graph", "ob-outline"], "ob-graph")],
        }
        for column, stacks_wanted in expected.items():
            col = find(self.layout, column)
            stacks = [n for n in walk(col) if n.get("type") == "stack"]
            self.assertEqual(len(stacks), 2, column)
            for stack, (mods, opens) in zip(stacks, stacks_wanted):
                got = [c["content"]["mod"] for c in stack["children"]]
                self.assertEqual(got, mods, stack["id"])
                active = next(c for c in stack["children"] if c["id"] == stack["active"])
                self.assertEqual(active["content"]["mod"], opens, stack["id"])

    def test_feed_scanner_sits_where_no_toggle_hides(self):
        # ob-feed polls the sub-agents. Its scanner copy (props role "scan") must stay mounted through Zen and the
        # side toggles, so its block and every ancestor must be outside the hideable set.
        scanners = [n for n in walk(self.layout) if (n.get("content") or {}).get("mod") == "ob-feed"
                    and (n.get("content") or {}).get("props", {}).get("role") == "scan"]
        self.assertEqual(len(scanners), 1, "exactly one scanner copy of ob-feed")
        chain = ancestors(self.layout, scanners[0])
        self.assertIsNotNone(chain)
        self.assertEqual(sorted(set(chain + [scanners[0]["id"]]) & hideable_ids()), [])

    def test_status_row_only_mounts_status_and_feed_only_scans(self):
        self.assertEqual([c["id"] for c in find(self.layout, "ob-statusrow")["children"]], ["ob-status"])
        # Only the 0 px scanner copy of ob-feed remains mounted in vaultr.json.
        roles = [(n.get("content") or {}).get("props", {}).get("role") for n in walk(self.layout)
                 if (n.get("content") or {}).get("mod") == "ob-feed"]
        self.assertEqual(roles, ["scan"])

    def test_side_columns_divide_their_two_halves_alike(self):
        # The node holding a side column's two halves (top and bottom stacks) draws a divider, left and right alike,
        # and the draggable boundary between the halves has the same resizable/min on both sides.
        def halves_parent(col):
            for n in walk(col):
                kids = n.get("children") or []
                if len(kids) == 2 and all(any(x.get("type") == "stack" for x in walk(k)) for k in kids):
                    return n
            self.fail(f"{col['id']} has no node holding its two halves")

        seen = {}
        for column in ("ob-left", "ob-right"):
            parent = halves_parent(find(self.layout, column))
            self.assertTrue(parent.get("divider"), f"{parent['id']} (in {column}) has no divider")
            top, bottom = parent["children"]
            seen[column] = [(k.get("resizable", True), k.get("min")) for k in (top, bottom)]
        self.assertEqual(seen["ob-left"], seen["ob-right"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_view_tables_agree_with_the_layout(self):
        tables = run_kit("return { views: K.VIEWS, node: K.NODE };")
        stack_children = {
            c["id"]
            for n in walk(self.layout) if n.get("type") == "stack"
            for c in (n.get("children") or [])
        }
        view_keys = set(tables["views"])
        self.assertEqual(sorted(stack_children - view_keys), [], "stack children missing from VIEWS")
        self.assertEqual(sorted(view_keys - stack_children), [], "VIEWS keys not in any layout stack")
        layout_ids = {n["id"] for n in walk(self.layout) if "id" in n}
        bad_nodes = {k: v for k, v in tables["node"].items() if v not in layout_ids}
        self.assertEqual(bad_nodes, {}, "NODE values missing from layout")
        self.assertTrue(hideable_ids().issubset(layout_ids))


if __name__ == "__main__":
    unittest.main()
