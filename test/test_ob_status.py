"""mods/ob-status: the status row's key hints. main.js needs the app, so this reads its source (weak) next to
keys/vaultr-keys.json."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import re
import unittest

ROOT = home_guard.ROOT
MAIN = os.path.join(ROOT, "mods", "ob-status", "main.js")
KEYS = os.path.join(ROOT, "keys", "vaultr-keys.json")


class CommandsHint(unittest.TestCase):
    """The "commands" hint names the key of the action the layout's commands key runs, not app.palette (which the
    layout's ctrl-shift-p no longer runs), with app.palette only as the fallback."""
    def test_the_hint_looks_up_what_the_commands_key_runs(self):
        with open(KEYS, encoding="utf-8") as f:
            action = json.load(f)["layout:vaultr"]["ctrl-shift-p"]
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"const paletteKey = (.+);", src)
        self.assertIsNotNone(m)
        self.assertTrue(m.group(1).startswith(f'bindingFor("{action}")'), m.group(1))
        self.assertIn('bindingFor("app.palette")', m.group(1), "app.palette stays the fallback")


if __name__ == "__main__":
    unittest.main()
