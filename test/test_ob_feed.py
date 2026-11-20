"""mods/ob-feed: the scanner and the status-row segment. main.js needs the app, so the checks on it read the source
(weak: no app here); the pure parts run under node."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MAIN = os.path.join(ROOT, "mods", "ob-feed", "main.js")
TICKER_AT = Path(ROOT, "mods", "ob-feed", "ticker_at.js")
NODE = shutil.which("node")


def run_node(body):
    src = (f'import * as A from "{TICKER_AT.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def main_src():
    with open(MAIN, encoding="utf-8") as f:
        return f.read()


def render_src():
    src = main_src()
    return src[src.index("  render() {"):]


class ScriptError(unittest.TestCase):
    """Weak: with the provider scanner missing, tick() returns before publish(), so the payload never carries the error. The
    segment must also show the copy's own error, or a missing scanner shows nothing at all."""
    def test_render_falls_back_to_its_own_script_error(self):
        self.assertIn("f?.scriptError ?? this.scriptError", render_src())


@unittest.skipUnless(NODE, "node is not installed")
class MainAgentAt(unittest.TestCase):
    """A working main Claude agent's ticker chip is dated by its last known activity, not by now: dated now, every main
    agent outranks every run and sub-agent and fills all TICKER_MAX chips."""
    def test_the_scans_updated_at_wins(self):
        self.assertEqual(run_node('return A.mainAgentAt({updatedAt: 500}, [{at: 900}], 10000);'), 500)

    def test_else_its_newest_touch(self):
        self.assertEqual(run_node('return A.mainAgentAt({}, [{at: 300}, {at: 700}, {at: null}], 10000);'), 700)

    def test_now_only_when_nothing_is_known(self):
        self.assertEqual(run_node('return A.mainAgentAt({}, undefined, 10000);'), 10000)
        self.assertEqual(run_node('return A.mainAgentAt(null, [], 10000);'), 10000)

    def test_main_js_dates_main_agents_with_it(self):
        src = main_src()
        self.assertIn('from "./ticker_at.js"', src)
        self.assertIn("mainAgentAt(", src)
        self.assertNotIn("at: Date.now(), tool: info.lastTool", src)


if __name__ == "__main__":
    unittest.main()
