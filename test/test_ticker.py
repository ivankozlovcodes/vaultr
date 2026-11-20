"""kit/ticker.js: the status row's ticker of running agents (pure, run under node). One chip per running agent:
its title and its latest action, newest first, a few at most. Nothing running: no chips. Tool output is never shown."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
TICKER = Path(ROOT, "kit", "ticker.js")
NODE = shutil.which("node")


def run_node(body):
    src = (f'import * as T from "{TICKER.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class Ticker(unittest.TestCase):
    def test_nothing_running_gives_no_chips(self):
        self.assertEqual(run_node("return T.tickerChips([]);"), [])
        self.assertEqual(run_node('return T.tickerChips([{key:"a", title:"x", live:false, at:5}]);'), [])

    def test_an_edit_names_the_file_briefly(self):
        r = run_node('return T.tickerChips([{key:"c1", title:"Claude Code", live:true, at:9, tool:{tool:"Edit", args:"main.js"}}]);')
        self.assertEqual(r[0]["text"], "Claude Code · Edit main.js")
        self.assertEqual(r[0]["key"], "c1")

    def test_a_command_is_cut_to_forty_characters(self):
        cmd = "python3 -m unittest discover -s test -p 'test_provider_scan.py' -v"
        r = run_node(f'return T.tickerChips([{{key:"r", title:"Fix hotkeys", live:true, at:9, tool:{{tool:"Bash", args:{json.dumps(cmd)}}}}}]);')
        self.assertEqual(r[0]["text"], "Fix hotkeys · Bash: " + cmd[:39] + "…")

    def test_a_pi_run_without_a_tool_says_its_turn(self):
        r = run_node('return T.tickerChips([{key:"p", title:"pi", live:true, at:9, turns:12}]);')
        self.assertEqual(r[0]["text"], "pi · turn 12")

    def test_newest_first_and_at_most_three(self):
        items = ",".join(f'{{key:"k{i}", title:"t{i}", live:true, at:{i}}}' for i in range(1, 6))
        r = run_node(f"return T.tickerChips([{items}]).map((c) => c.key);")
        self.assertEqual(r, ["k5", "k4", "k3"])

    def test_finished_agents_are_left_out(self):
        r = run_node('return T.tickerChips([{key:"a", title:"a", live:false, at:9}, {key:"b", title:"b", live:true, at:1}]).map((c) => c.key);')
        self.assertEqual(r, ["b"])

    def test_tool_output_is_never_shown(self):
        r = run_node('return T.tickerChips([{key:"o", title:"Claude Code", live:true, at:9, out:["SECRET OUTPUT"], tool:{tool:"Bash", args:"ls"}}]);')
        self.assertNotIn("SECRET", r[0]["text"])

    def test_the_target_comes_with_the_chip(self):
        r = run_node('return T.tickerChips([{key:"m", title:"Claude Code", live:true, at:9, target:{kind:"pane", terminal:"t3"}}]);')
        self.assertEqual(r[0]["target"], {"kind": "pane", "terminal": "t3"})


if __name__ == "__main__":
    unittest.main()
