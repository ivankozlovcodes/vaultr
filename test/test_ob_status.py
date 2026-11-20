"""mods/ob-status: the main-slot footer renders only the high-level agent overview."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import os
import unittest

ROOT = home_guard.ROOT
MAIN = os.path.join(ROOT, "mods", "ob-status", "main.js")


def read_main():
    with open(MAIN, encoding="utf-8") as f:
        return f.read()


class AgentOverview(unittest.TestCase):
    def setUp(self):
        self.src = read_main()

    def test_renders_human_readable_overview_labels(self):
        for label in ('"needs you"', '"need you"', " working", " done", " idle", '"0 active"'):
            self.assertIn(label, self.src)

    def test_filters_visible_agents_like_ob_agents_keeping_blocked(self):
        for sym in (
            "mainAgents(",
            "placedTerminals(",
            'normStatus(att) === "blocked"',
            "isMachineHidden(",
            "isSpaceHidden(",
            "isTabHidden(",
            "attentionCounts(",
        ):
            self.assertIn(sym, self.src)

    def test_no_key_hint_or_repo_clutter(self):
        for clutter in (" switch", " commands", "bindingFor", "chordLabel"):
            self.assertNotIn(clutter, self.src)


if __name__ == "__main__":
    unittest.main()
