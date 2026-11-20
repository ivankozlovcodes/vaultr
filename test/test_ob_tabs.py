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


if __name__ == "__main__":
    unittest.main()
