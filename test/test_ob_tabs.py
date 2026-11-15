"""mods/ob-tabs Zen: what Zen saves and restores (pure: zen.js, run under node). Entering Zen hides both sides
and the status row; leaving it shows back exactly what was shown before the first entry."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
ZEN = Path(ROOT, "mods", "ob-tabs", "zen.js")
NODE = shutil.which("node")
VISIBLE = {"left": False, "right": False, "statusrow": False}
ALL_HIDDEN = {"left": True, "right": True, "statusrow": True}


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


class SettingsOpenFlag(unittest.TestCase):
    """ob-tabs opens Settings only while shared "ob-settings.open" is false, and only the dialog's close() clears it.
    Shared state is saved, so a dialog that died open would block Settings for good: ob-tabs (always in the layout,
    started before any dialog) clears a stale flag when it starts."""

    def setUp(self):
        self.src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")

    def test_init_clears_a_stale_open_flag(self):
        init = self.src[self.src.index("  init(_p, cx) {"):]
        init = init[:init.index("\n  }\n")]
        self.assertRegex(init, r'cx\.timer\.after\(0, \(\) => \{ if \(shared\("ob-settings\.open"\)\) setShared\("ob-settings\.open", false\); \}\)')

    def test_settings_still_checks_the_flag_by_its_name(self):
        self.assertIn('if (shared("ob-settings.open")) return;', self.src)



if __name__ == "__main__":
    unittest.main()
