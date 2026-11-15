"""mods/ob-sessions (the Sessions tree) names panes for what they run, through the kit's one rule (paneLabelOf). A tab
keeps its own name. A tab that holds exactly one pane and shows as that pane's row shows the pane's label under its
name when the two differ. The tree is built from live Herdr lists, so these are wiring checks on the source."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MAIN = Path(ROOT, "mods", "ob-sessions", "main.js")


class PaneNames(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_a_pane_row_is_named_by_the_kit_rule_with_its_tab_name_passed_in(self):
        self.assertIn('paneLabelOf(p, tab ? tabLabel(tab, ps) : "")', self.src)

    def test_the_old_pane_name_is_no_longer_used_for_rows(self):
        self.assertNotIn("paneName(p)", self.src)

    def test_a_tab_row_still_shows_the_tab_name(self):
        self.assertRegex(self.src, r'kind: "tab", label, text: label')

    def test_a_single_pane_tab_row_gets_the_pane_label_as_secondary_text_when_it_differs(self):
        self.assertIn("paneSecondary(label, paneLabelOf(mine[0], label))", self.src)

    def test_the_secondary_text_is_drawn_in_the_tab_row(self):
        self.assertRegex(self.src, r"n\.secondary[\s\S]{0,200}text_color\(t\.dim\)")


class MacKeys(unittest.TestCase):
    def test_cmd_enter_opens_to_the_right_like_ctrl_enter(self):
        # On macOS install.sh binds cmd-enter where keys/ says ctrl-enter; the tree's own key handler takes both.
        src = MAIN.read_text(encoding="utf-8")
        self.assertRegex(src, r'case "ctrl-enter": case "cmd-enter": if \(this\.once\("open-right"\)\)')


MATCH = Path(ROOT, "mods", "ob-sessions", "match.js")
NODE = shutil.which("node")


def match_q(q, text):
    src = (f'import {{ matchQ }} from "{MATCH.as_uri()}";\n'
           f'console.log(JSON.stringify(matchQ({json.dumps(q)}, {json.dumps(text)})));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class Filter(unittest.TestCase):
    """The tree's filter: the kit's fuzzy() (every space-separated term, anywhere, in any order), but a term's own
    letters may not spread over the whole label. The spread is checked per term, not from the first term's hit to
    the last one's."""

    def test_two_terms_far_apart_match(self):
        self.assertIsNotNone(match_q("vault test", "vaultr · ~/src/projects/foo/test"))
        self.assertIsNotNone(match_q("test vault", "vaultr · ~/src/projects/foo/test"))

    def test_a_single_term_still_may_not_spread(self):
        # fuzzy() lets a short term's letters spread inside one long word; the filter does not.
        self.assertIsNone(match_q("vrst", "v" + "a" * 20 + "rst"))
        self.assertIsNotNone(match_q("vrst", "vxrst"))
        self.assertIsNone(match_q("vault vrst", "vault " + "v" + "a" * 20 + "rst"))

    def test_a_missing_term_fails(self):
        self.assertIsNone(match_q("vault zebra", "vaultr · ~/src/projects/foo/test"))

    def test_empty_query_matches_with_no_hits(self):
        self.assertEqual(match_q("", "anything"), {"score": 0, "hits": []})

    def test_main_uses_the_module(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('import { matchQ } from "./match.js";', src)
        self.assertNotIn("function matchQ(", src)


if __name__ == "__main__":
    unittest.main()
