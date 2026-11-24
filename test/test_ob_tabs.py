"""mods/ob-tabs Zen: what Zen saves and restores (pure: zen.js, run under node). Entering Zen hides both sides
and the status row; leaving it shows back exactly what was shown before the first entry."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
ZEN = Path(ROOT, "mods", "ob-tabs", "zen.js")
NODE = shutil.which("node")
VISIBLE = {"left": False, "right": False, "statusrow": False}
ALL_HIDDEN = {"left": True, "right": True, "statusrow": True}


def run_node(body, module):
    src = (f'import * as M from "{module.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def plan(prev, mode, hidden, now=1000):
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    src = (f'import * as Z from "{ZEN.as_uri()}";\n'
           f'console.log(JSON.stringify(Z.zenPlan({json.dumps({"prev": prev, "mode": mode, "hidden": hidden, "now": now})})));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


class Zen(unittest.TestCase):
    def test_entering_hides_both_sides_and_the_status_row_and_saves_what_was_shown(self):
        r = plan(None, "on", VISIBLE)
        self.assertEqual(sorted(r["hide"]), ["left", "right", "statusrow"])
        self.assertEqual(r["state"], {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False, "at": 1000})

    def test_leaving_shows_back_what_was_shown(self):
        prev = {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False}
        r = plan(prev, "off", ALL_HIDDEN)
        self.assertEqual(sorted(r["show"]), ["left", "right", "statusrow"])
        self.assertFalse(r["state"]["active"])

    def test_a_row_hidden_before_zen_stays_hidden_after(self):
        prev = {"active": True, "leftHidden": True, "rightHidden": False, "statusHidden": True}
        r = plan(prev, "off", ALL_HIDDEN)
        self.assertEqual(sorted(r["show"]), ["right"])

    def test_entering_again_keeps_the_state_saved_on_the_first_entry(self):
        # Zen's own hiding is not "what was shown": a second "on" (or the toggle while in Zen, or a router open
        # that exits) must not overwrite the saved flags, or the status row stays hidden after leaving.
        prev = {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False, "at": 5}
        r = plan(prev, "on", ALL_HIDDEN, now=2000)
        self.assertEqual(r["state"], prev)
        self.assertEqual(sorted(plan(r["state"], "off", ALL_HIDDEN)["show"]), ["left", "right", "statusrow"])

    def test_toggle_leaves_when_both_sides_are_hidden_by_zen(self):
        prev = {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False}
        self.assertFalse(plan(prev, "toggle", ALL_HIDDEN)["state"]["active"])
        self.assertTrue(plan(None, "toggle", VISIBLE)["state"]["active"])

    def test_leaving_when_not_in_zen_changes_nothing(self):
        # A side or the status row the person hid by hand stays hidden.
        r = plan(None, "off", {"left": True, "right": False, "statusrow": True})
        self.assertEqual((r["show"], r["hide"], r["tabbar"]), ([], [], None))


SETTINGS_OPEN = Path(ROOT, "mods", "ob-tabs", "settings_open.js")


class SettingsOpenFlag(unittest.TestCase):
    """ob-tabs opens Settings only while the dialog says it is open. Shared "ob-settings.open" is the time of the dialog's
    last beat (it beats while open, and close() sets false), so a dialog that died open, or an ob-tabs that reloaded
    under an open one, needs no clean-up: a beat that stops goes stale on its own."""

    def setUp(self):
        self.src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")

    def is_open(self, value, now):
        return run_node('return M.isSettingsOpen(%s, %s);' % (json.dumps(value), now), SETTINGS_OPEN)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_a_fresh_beat_is_open_and_a_stale_one_is_not(self):
        self.assertTrue(self.is_open(1_000_000, 1_000_000 + 5_000))
        self.assertFalse(self.is_open(1_000_000, 1_000_000 + 60_000), "a dialog that died open")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_closed_and_old_style_values_are_not_open(self):
        for v in (False, None, True, 0, "x"):  # true is what an older version left in the saved state
            self.assertFalse(self.is_open(v, 1_000_000), repr(v))

    def test_settings_asks_isSettingsOpen_and_init_clears_nothing(self):
        self.assertIn('isSettingsOpen(shared("ob-settings.open"))', self.src)
        init = self.src[self.src.index("  init(_p, cx) {"):]
        init = init[:init.index("\n  }\n")]
        self.assertNotIn("ob-settings.open", init)

    def test_a_closed_dialog_stops_beating(self):
        # A beat after close() would set the flag fresh again and ob-tabs would never open Settings.
        dialog = Path(ROOT, "mods", "ob-settings", "main.js").read_text(encoding="utf-8")
        self.assertRegex(dialog, r"this\.beat = cx\.timer\.every\(BEAT_MS, \(\) => \{ if \(this\.closed\) return; setShared\(OPEN, Date\.now\(\)\); \}\)")
        close = dialog[dialog.index("  close() {"):]
        close = close[:close.index("\n")]
        self.assertIn("this.closed = true", close)
        self.assertIn("this.beat?.cancel()", close)
        self.assertLess(close.index("this.closed = true"), close.index("setShared(OPEN, false)"))

    def test_the_dialog_beats_faster_than_the_flag_goes_stale(self):
        dialog = Path(ROOT, "mods", "ob-settings", "main.js").read_text(encoding="utf-8")
        beat = int(re.search(r"const BEAT_MS = (\d+);", dialog).group(1))
        ttl = int(re.search(r"export const OPEN_TTL_MS = (\d+);", SETTINGS_OPEN.read_text(encoding="utf-8")).group(1))
        self.assertLessEqual(beat * 2, ttl)
        self.assertRegex(dialog, r"setShared\(OPEN, Date\.now\(\)\)")


TAB_DETACH = Path(ROOT, "mods", "ob-tabs", "detach.js")
TAB_PANES = ('const P = [{pane:"a", tab:"t1", terminal:"box/t9"}, {pane:"b", tab:"t2", terminal:"t4"}, {pane:"c", tab:"t2", terminal:"t5"},'
             ' {pane:"d", tab:"t3", mod:"notes"}, {pane:"e", tab:"t4", terminal:"t6"}, {pane:"f", tab:"t4", mod:"notes"}];')


@unittest.skipUnless(NODE, "node is not installed: the tab detach tests are skipped")
class TabDetach(unittest.TestCase):
    """A tab that is one terminal pane can go back to the background as a whole (Herdr's terminal.park): the tab
    goes away, the program keeps running. Close tab ends it."""

    def test_a_tab_of_one_terminal_pane_offers_detach(self):
        r = run_node(TAB_PANES + 'return M.detachItem(P, "t1");', TAB_DETACH)
        self.assertEqual(r, {"label": "Detach to background", "icon": "win-min", "command": "terminal.park", "args": {"terminal": "box/t9"}})

    def test_a_tab_with_more_panes_a_mod_pane_or_no_pane_does_not(self):
        r = run_node(TAB_PANES + 'return ["t2", "t3", "t4", "t9"].map((id) => M.detachItem(P, id));', TAB_DETACH)
        self.assertEqual(r, [None, None, None, None])

    def test_the_sole_terminal_is_read_from_the_tabs_panes_only(self):
        r = run_node(TAB_PANES + 'return [M.soleTerminal(P, "t1"), M.soleTerminal(P, "t2"), M.soleTerminal(null, "t1")];', TAB_DETACH)
        self.assertEqual(r, ["box/t9", None, None])

    def test_the_tab_menu_offers_it_right_above_close_tab(self):
        src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")
        menu = src[src.index("  tabMenu(space, tab) {"):]
        lines = [ln.strip() for ln in menu[:menu.index("\n  }\n")].splitlines()]
        at = lines.index("detachItem(ps, tab.id),")
        self.assertTrue(lines[at + 1].startswith('{ label: "Close tab"'))
        self.assertTrue(Path(ROOT, "kit", "icons", "win-min.svg").is_file())


OPEN = Path(ROOT, "mods", "ob-tabs", "open.js")


def sample_layout(*, left_hidden=False, lt_hidden=False, lb_hidden=False, right_hidden=False,
                  lt_active="ob-sessions", rb_active="ob-graph"):
    return {
        "id": "root",
        "type": "row",
        "children": [
            {
                "id": "ob-left",
                "type": "column",
                "hidden": left_hidden,
                "children": [
                    {
                        "id": "ob-left-body",
                        "type": "column",
                        "children": [
                            {
                                "id": "ob-lt",
                                "type": "column",
                                "hidden": lt_hidden,
                                "children": [
                                    {
                                        "id": "ob-lt-stack",
                                        "type": "stack",
                                        "active": lt_active,
                                        "children": [
                                            {"id": "ob-sessions", "type": "block"},
                                            {"id": "ob-search", "type": "block"},
                                        ],
                                    },
                                ],
                            },
                            {
                                "id": "ob-lb-stack",
                                "type": "stack",
                                "hidden": lb_hidden,
                                "active": "ob-agents",
                                "children": [{"id": "ob-agents", "type": "block"}],
                            },
                        ],
                    },
                ],
            },
            {
                "id": "ob-right",
                "type": "column",
                "hidden": right_hidden,
                "children": [
                    {
                        "id": "ob-rb-stack",
                        "type": "stack",
                        "active": rb_active,
                        "children": [
                            {"id": "ob-graph", "type": "block"},
                            {"id": "ob-outline", "type": "block"},
                        ],
                    },
                ],
            },
        ],
    }


@unittest.skipUnless(NODE, "node is not installed")
class OpenPlan(unittest.TestCase):
    def plan(self, **kw):
        return run_node(f"return M.openPlan({json.dumps(kw)});", OPEN)

    def test_missing_view_shows_warning_toast_and_changes_nothing_even_in_zen(self):
        zen_on = {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False}
        for verb in ("open", "toggle"):
            for child in ("ob-inbox", "", "ob-left"):
                with self.subTest(verb=verb, child=child):
                    r = self.plan(root=sample_layout(left_hidden=True, right_hidden=True),
                                  verb=verb, child=child, intent="reveal", zen=zen_on, now=1234)
                    self.assertEqual(r["notify"], {
                        "title": f'No panel "{child}" in this layout',
                        "body": "Run install.sh again to add the panels the repo has added.",
                        "level": "warning",
                    })
                    self.assertIsNone(r["tabbar"])
                    self.assertEqual(r["show"], [])
                    self.assertEqual(r["hide"], [])
                    self.assertIsNone(r["select"])
                    self.assertEqual(r["shared"], [])

    def test_open_existing_view_shows_side_and_hidden_group_and_sets_focus(self):
        r = self.plan(root=sample_layout(left_hidden=True, lt_hidden=True),
                      verb="open", child="ob-search", intent="reveal", now=2000)
        self.assertIsNone(r["notify"])
        self.assertEqual(r["show"], ["ob-left", "ob-lt"])
        self.assertEqual(r["hide"], [])
        self.assertEqual(r["select"], {"stack": "ob-lt-stack", "child": "ob-search"})
        self.assertEqual(r["shared"], [["ob.focus", {"child": "ob-search", "intent": "reveal", "at": 2000}]])

        rb = self.plan(root=sample_layout(lb_hidden=True), verb="open", child="ob-agents", now=2001)
        self.assertEqual(rb["show"], ["ob-left", "ob-lb-stack"])

    def test_open_works_when_view_moved_to_another_stack(self):
        root = sample_layout(lt_hidden=True)
        outline = root["children"][1]["children"][0]["children"].pop()
        root["children"][0]["children"][0]["children"][0]["children"][0]["children"].append(outline)
        r = self.plan(root=root, verb="open", child="ob-outline", now=3000)
        self.assertEqual(r["show"], ["ob-left", "ob-lt"])
        self.assertEqual(r["select"], {"stack": "ob-lt-stack", "child": "ob-outline"})

    def test_open_in_zen_leaves_zen_before_opening_existing_view(self):
        zen_on = {"active": True, "leftHidden": False, "rightHidden": False, "statusHidden": False}
        r = self.plan(root=sample_layout(left_hidden=True, right_hidden=True),
                      verb="open", child="ob-outline", zen=zen_on, now=4000)
        self.assertEqual(r["tabbar"], 40)
        self.assertEqual(r["show"], ["ob-statusrow", "ob-right"])
        self.assertEqual(r["select"], {"stack": "ob-rb-stack", "child": "ob-outline"})
        self.assertEqual(r["shared"], [
            ["ob.zen", {"active": False, "at": 4000}],
            ["ob.focus", {"child": "ob-outline", "intent": None, "at": 4000}],
        ])

        zen_status_hidden = {**zen_on, "statusHidden": True}
        r2 = self.plan(root=sample_layout(left_hidden=True, right_hidden=True),
                       verb="open", child="ob-outline", zen=zen_status_hidden, now=4001)
        self.assertEqual(r2["show"], ["ob-right"])

    def test_toggle_shown_view_hides_side_and_toggle_inactive_view_shows_it(self):
        shown = self.plan(root=sample_layout(), verb="toggle", child="ob-sessions", now=5000)
        self.assertEqual(shown["hide"], ["ob-left"])
        self.assertEqual(shown["show"], [])
        self.assertIsNone(shown["select"])
        self.assertEqual(shown["shared"], [])

        inactive = self.plan(root=sample_layout(), verb="toggle", child="ob-search", now=5001)
        self.assertEqual(inactive["hide"], [])
        self.assertEqual(inactive["show"], ["ob-left"])
        self.assertEqual(inactive["select"], {"stack": "ob-lt-stack", "child": "ob-search"})

    def test_term_intent_sets_ob_inspect(self):
        r = self.plan(root=sample_layout(), verb="open", child="ob-props" if False else "ob-outline",
                      intent="term:devbox/t7", now=6000)
        self.assertEqual(r["shared"], [
            ["ob.inspect", {"terminal": "devbox/t7", "at": 6000}],
            ["ob.focus", {"child": "ob-outline", "intent": "term:devbox/t7", "at": 6000}],
        ])

    def test_open_method_carries_out_openPlan_before_changing_anything(self):
        src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")
        body = src[src.index("  open(root, verb, child, intent) {"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("openPlan(", body)
        self.assertLess(body.index("if (plan.notify)"), body.index("run("))
        self.assertLess(body.index("if (plan.notify)"), body.index("setShared("))
        pure = OPEN.read_text(encoding="utf-8")
        self.assertNotIn('"herdr"', pure)
        self.assertNotIn("kit.js", pure)

    def test_switcher_closes_previous_overlay_before_opening_new_one(self):
        src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")
        body = src[src.index("  switcher(mode) {"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("closeOverlay(this.switcherOverlayId)", body)
        self.assertIn("this.switcherOverlayId = openOverlay(", body)


if __name__ == "__main__":
    unittest.main()
