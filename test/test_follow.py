"""The right-hand panels' target (Properties, Outline): kit/follow_target.js, a pure function run here through node.

Rule: a pin wins while its terminal is live. Otherwise the panel shows the last focused main-window pane that holds a
terminal (Properties) or an agent (Outline). Focus on anything else keeps the previous target. A closed target gives
an empty state. The old "right pane follows" setting (ob.settings.paneFollows) is no longer read by any mod.
"""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = home_guard.ROOT
FOLLOW = os.path.join(ROOT, "kit", "follow_target.js")
KIT = os.path.join(ROOT, "kit", "kit.js")
MODS = os.path.join(ROOT, "mods")
NODE = shutil.which("node")

LIVE = [{"address": "t1", "state": "live"}, {"address": "t2", "state": "live"}, {"address": "t4", "state": "live"}]
AGENT = {"pane": "p1", "terminal": "t2", "agent": True}     # a main agent pane
SHELL = {"pane": "p2", "terminal": "t4", "agent": False}    # a main shell pane
SIDE = None                                                  # a side panel or dialog: focused() has no pane/terminal
MOD_PANE = {"pane": "p3", "terminal": None, "agent": False}  # a mod pane in the main window


def follow(args):
    """Run followTarget with `args` (a JS object literal body) and return its JSON result."""
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    code = (f'import {{ followTarget }} from "{FOLLOW}";\n'
            f'process.stdout.write(JSON.stringify(followTarget({args})));\n')
    res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def args(**kw):
    return json.dumps(kw)


class PropertiesRule(unittest.TestCase):
    def test_pinned_wins_over_focus(self):
        r = follow(args(pinned="t1", focused=AGENT, last=None, terminals=LIVE, wantAgent=False))
        self.assertEqual(r["terminal"], "t1")

    def test_focus_on_a_main_agent_switches(self):
        r = follow(args(pinned=None, focused=AGENT, last="t1", terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": "t2", "last": "t2"})

    def test_focus_on_a_shell_switches(self):
        r = follow(args(pinned=None, focused=SHELL, last="t1", terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": "t4", "last": "t4"})

    def test_focus_on_a_side_panel_keeps_the_last(self):
        r = follow(args(pinned=None, focused=SIDE, last="t1", terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": "t1", "last": "t1"})

    def test_focus_on_a_mod_pane_keeps_the_last(self):
        r = follow(args(pinned=None, focused=MOD_PANE, last="t1", terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": "t1", "last": "t1"})

    def test_closed_last_falls_back_to_the_focused_main_pane(self):
        r = follow(args(pinned=None, focused=AGENT, last="t9", terminals=LIVE, wantAgent=False))
        self.assertEqual(r["terminal"], "t2")

    def test_closed_last_with_side_focus_is_empty(self):
        r = follow(args(pinned=None, focused=SIDE, last="t9", terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": None, "last": None})

    def test_a_terminal_that_is_not_live_counts_as_closed(self):
        dead = [{"address": "t1", "state": "exited"}, {"address": "t2", "state": "live"}]
        r = follow(args(pinned=None, focused=SIDE, last="t1", terminals=dead, wantAgent=False))
        self.assertEqual(r, {"terminal": None, "last": None})

    def test_nothing_ever_focused_is_the_empty_state(self):
        r = follow(args(pinned=None, focused=SIDE, last=None, terminals=LIVE, wantAgent=False))
        self.assertEqual(r, {"terminal": None, "last": None})

    def test_a_closed_pin_is_ignored(self):
        r = follow(args(pinned="t9", focused=AGENT, last=None, terminals=LIVE, wantAgent=False))
        self.assertEqual(r["terminal"], "t2")

    def test_stale_paneFollows_is_ignored(self):
        r = follow(args(pinned=None, focused=AGENT, last="t1", terminals=LIVE, wantAgent=False,
                        paneFollows="selection", settings={"paneFollows": "selection"}))
        self.assertEqual(r, {"terminal": "t2", "last": "t2"})


class SubagentsRule(unittest.TestCase):
    def test_focus_on_a_main_agent_switches(self):
        r = follow(args(pinned=None, focused=AGENT, last="t1", terminals=LIVE, wantAgent=True))
        self.assertEqual(r, {"terminal": "t2", "last": "t2"})

    def test_shell_pane_does_not_switch(self):
        r = follow(args(pinned=None, focused=SHELL, last="t1", terminals=LIVE, wantAgent=True))
        self.assertEqual(r, {"terminal": "t1", "last": "t1"})

    def test_side_panel_keeps_the_last_agent(self):
        r = follow(args(pinned=None, focused=SIDE, last="t2", terminals=LIVE, wantAgent=True))
        self.assertEqual(r, {"terminal": "t2", "last": "t2"})

    def test_closed_agent_with_a_shell_focused_is_empty(self):
        r = follow(args(pinned=None, focused=SHELL, last="t9", terminals=LIVE, wantAgent=True))
        self.assertEqual(r, {"terminal": None, "last": None})

    def test_pinned_wins(self):
        r = follow(args(pinned="t4", focused=AGENT, last="t1", terminals=LIVE, wantAgent=True))
        self.assertEqual(r["terminal"], "t4")


@unittest.skipUnless(NODE, "node is not installed: the wiring checks still run")
class Wiring(unittest.TestCase):
    def test_kit_re_exports_follow_targets(self):
        with open(KIT, encoding="utf-8") as f:
            self.assertRegex(f.read(), r'export \{[^}]*followTarget[^}]*\} from "\./follow_target\.js"')

    def test_both_panels_call_the_kit_rule(self):
        for mod in ("ob-props", "ob-outline"):
            with self.subTest(mod=mod):
                with open(os.path.join(MODS, mod, "obc.js"), encoding="utf-8") as f:
                    src = f.read()
                self.assertIn("followTarget(", src)
                self.assertRegex(src, r'import \{[^}]*followTarget[^}]*\} from "\./kit\.js"')

    def test_no_mod_reads_paneFollows(self):
        for mod in sorted(os.listdir(MODS)):
            d = os.path.join(MODS, mod)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if not name.endswith((".js", ".mjs")) or name == "gpui-kit.d.ts":
                    continue
                with self.subTest(file=f"{mod}/{name}"):
                    with open(os.path.join(d, name), encoding="utf-8") as f:
                        self.assertNotIn("paneFollows", f.read())


if __name__ == "__main__":
    unittest.main()
