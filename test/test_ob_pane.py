"""mods/ob-pane Detach: which pane headers show the Detach button, and what it runs (pure: detach.js, run under
node). Detach is Herdr's terminal.park: the pane goes away, the program keeps running in the background. The header
and the menu are wired to it in main.js (checked on the source: the header is built from live Herdr lists)."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
DETACH = Path(ROOT, "mods", "ob-pane", "detach.js")
MAIN = Path(ROOT, "mods", "ob-pane", "main.js")
NODE = shutil.which("node")


def run_detach(body):
    """Import detach.js in node, run `body` (JS using the exports as D), return the JSON it prints."""
    src = f'import * as D from "{DETACH.as_uri()}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed: the detach tests are skipped")
class ChildTerminal(unittest.TestCase):
    def test_a_terminal_with_a_parent_is_a_child(self):
        self.assertTrue(run_detach('return D.isChildTerminal({ address: "t9", parent: "t1" });'))

    def test_a_plain_session_is_not(self):
        r = run_detach('return [D.isChildTerminal({ address: "t1" }), D.isChildTerminal({ address: "t1", parent: "" }),'
                       ' D.isChildTerminal(null), D.isChildTerminal(undefined)];')
        self.assertEqual(r, [False, False, False, False])


@unittest.skipUnless(NODE, "node is not installed: the detach tests are skipped")
class DetachItem(unittest.TestCase):
    def test_the_menu_item_parks_the_terminal(self):
        r = run_detach('return D.detachItem("box/t9");')
        self.assertEqual(r, {"label": "Detach to background", "icon": "win-min", "command": "terminal.park", "args": {"terminal": "box/t9"}})

    def test_the_icon_is_shipped_and_the_tip_says_it_keeps_running(self):
        self.assertTrue(Path(ROOT, "kit", "icons", run_detach("return D.DETACH_ICON;") + ".svg").is_file())
        self.assertEqual(run_detach("return D.DETACH_TIP;"), "Detach to background (leaves terminal running)")


class Wiring(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_the_header_of_a_child_terminal_shows_detach_also_when_not_hovered(self):
        head = self.src[self.src.index("  header(cx, zenActive"):]
        block = head[head.index("if (addr && isChildTerminal("):head.index("if (!addr || this.hovered)")]
        self.assertNotIn("this.hovered", block)
        self.assertIn('run("terminal.park", { terminal: addr })', block)
        self.assertIn('.child("Detach")', block)
        self.assertIn(".tooltip(DETACH_TIP)", block)
        self.assertNotIn("pane.close", block)

    def test_the_more_menu_offers_detach_right_above_close_pane(self):
        menu = self.src[self.src.index("  moreMenu(x) {"):self.src.index("  render(cx) {")]
        lines = [ln.strip() for ln in menu.splitlines()]
        at = lines.index("detachItem(addr),")
        self.assertTrue(lines[at + 1].startswith('{ label: "Close pane"'))


if __name__ == "__main__":
    unittest.main()
