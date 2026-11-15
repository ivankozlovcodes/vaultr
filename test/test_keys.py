"""Vaultr's keys file: the session search key is Ctrl+Shift+K (Ctrl+Shift+F stays with find-in-terminal), and the
hotkey labels name the keys that are really bound."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import unittest

ROOT = home_guard.ROOT
KEYS = json.load(open(os.path.join(ROOT, "keys", "vaultr-keys.json")))
REGISTRY = open(os.path.join(ROOT, "mods", "ob-settings", "registry.js"), encoding="utf-8").read()


class SessionSearchKey(unittest.TestCase):
    def test_ctrl_shift_f_is_not_bound_outside_the_terminal(self):
        for section, binds in KEYS.items():
            if section == "terminal":
                continue
            self.assertNotIn("ctrl-shift-f", binds, f"{section} binds ctrl-shift-f (terminal find)")

    def test_search_all_sessions_is_on_ctrl_shift_k(self):
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-shift-k"), "ob-tabs.open:ob-search")

    def test_ctrl_alt_f_still_opens_search(self):
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-alt-f"), "ob-tabs.open:ob-search")

    def test_hotkey_label_names_ctrl_shift_k(self):
        line = next(l for l in REGISTRY.splitlines() if '"ob-tabs.open:ob-search"' in l)
        self.assertIn('"ctrl-shift-k"', line)
        self.assertNotIn("ctrl-shift-f", line)
        self.assertNotIn("Ctrl+Shift+F", line)


class VaultrSettingsKey(unittest.TestCase):
    def test_ctrl_comma_opens_vaultr_settings_in_the_layout(self):
        # The footer gear opens ob-settings with mod.open directly: no tab bar mod in the path (Zen, hidden tab bar).
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-,"), "mod.open:ob-settings")


class CommandPaletteKey(unittest.TestCase):
    def test_ctrl_shift_p_in_the_layout_opens_the_switcher_in_command_mode(self):
        # Herdr's own palette stays one entry in this list ("Herdr command palette…" -> app.palette).
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-shift-p"), "ob-tabs.switcher:commands")

    def test_hotkey_label_names_ctrl_shift_p_on_the_command_mode(self):
        line = next(l for l in REGISTRY.splitlines() if '"ob-tabs.switcher:commands"' in l)
        self.assertIn('"ctrl-shift-p"', line)


if __name__ == "__main__":
    unittest.main()
