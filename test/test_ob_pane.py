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
PROMPT = Path(ROOT, "mods", "ob-pane", "prompt.js")
PROVIDER = Path(ROOT, "kit", "provider.js")
LAYOUT = Path(ROOT, "layouts", "vaultr.json")
MAIN = Path(ROOT, "mods", "ob-pane", "main.js")
NODE = shutil.which("node")


def run_detach(body):
    """Import detach.js in node, run `body` (JS using the exports as D), return the JSON it prints."""
    src = f'import * as D from "{DETACH.as_uri()}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


def run_prompt(body):
    """Import prompt.js and kit/provider.js in node, run `body` (exports as P and makeProvider), return JSON."""
    src = (
        f'import * as P from "{PROMPT.as_uri()}";\n'
        f'import {{ makeProvider }} from "{PROVIDER.as_uri()}";\n'
        f'console.log(JSON.stringify((() => {{ {body} }})()));'
    )
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
        with open(MAIN, encoding="utf-8") as f:
            self.src = f.read()

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

    def test_layout_sets_two_row_pane_header_height_56(self):
        with open(LAYOUT, encoding="utf-8") as f:
            tree = json.load(f)

        def find_node(n, nid):
            if not isinstance(n, dict):
                return None
            if n.get("id") == nid:
                return n
            for c in n.get("children") or []:
                hit = find_node(c, nid)
                if hit:
                    return hit
            return None

        main_node = find_node(tree, "ob-main")
        self.assertIsNotNone(main_node)
        hdr = main_node["content"]["pane"]["header"]
        self.assertEqual(hdr["content"]["mod"], "ob-pane")
        self.assertEqual(hdr["height"], 56)

    def test_header_wires_sticky_prompt_and_history_dialog(self):
        with open(PROMPT, encoding="utf-8") as f:
            prompt_src = f.read()
        self.assertIn("provider.session(addr)", self.src)
        self.assertIn("isChildTerminalOf(tm, addr)", self.src)
        self.assertIn('provider.of(sess)?.can("prompts")', self.src)
        self.assertIn("latestPrompt(sess)", self.src)
        self.assertIn("session?.prompts", prompt_src)
        self.assertNotRegex(prompt_src, r"(?:\?\.|\.)turns\b")
        self.assertIn(".track_scroll(this.scroll)", self.src)
        self.assertIn('mod: "ob-pane"', self.src)
        self.assertIn('kind: "dialog"', self.src)


@unittest.skipUnless(NODE, "node is not installed: the prompt tests are skipped")
class PromptLogic(unittest.TestCase):
    def test_missing_or_empty_returns_empty_and_null(self):
        r = run_prompt("""
            return {
              turnsMissing: P.promptTurns(null),
              latestMissing: P.latestPrompt(null),
              latestEmpty: P.latestPrompt({ prompts: [{ text: "  " }, null] }),
            };
        """)
        self.assertEqual(r, {"turnsMissing": [], "latestMissing": None, "latestEmpty": None})

    def test_latest_prompt_reverses_history_and_falls_back_full_to_text(self):
        r = run_prompt(r"""
            const sess = { prompts: [
              { text: "first", ts: "2026-11-17T01:00:00Z" },
              { step: 4, text: "second line", full: "second line\nwith details", ts: "2026-11-17T02:00:00Z" },
            ] };
            return P.latestPrompt(sess);
        """)
        self.assertEqual(r["text"], "second line")
        self.assertEqual(r["full"], "second line\nwith details")
        self.assertEqual(r["step"], 4)
        self.assertEqual(r["count"], 2)
        self.assertEqual([x["text"] for x in r["history"]], ["second line", "first"])
        self.assertEqual(r["history"][1]["full"], "first")

    def test_v2_provider_facade_gates_prompts_by_capability(self):
        r = run_prompt(r"""
            const feedData = {
              v: 2,
              providers: {
                alpha: { id: "alpha", name: "Alpha", noun: "alpha", caps: ["prompts"] },
                beta: { id: "beta", name: "Beta", noun: "beta", caps: [] },
              },
              terms: {
                t9: { provider: "alpha", turns: [
                  { text: "one", ts: "2026-11-17T01:00:00Z" },
                  { text: "two", full: "two\nmore", ts: "2026-11-17T02:00:00Z" },
                ] },
                t10: { provider: "beta", turns: [{ text: "should hide" }] },
              },
            };
            const prov = makeProvider({ feed: () => feedData });
            const s9 = prov.session("t9");
            const s10 = prov.session("t10");
            const read = (addr) => {
              const sess = prov.session(addr);
              return sess && prov.of(sess)?.can("prompts") ? P.latestPrompt(sess) : null;
            };
            return {
              t9HasTurns: Object.hasOwn(s9, "turns"),
              t9Prompts: s9.prompts,
              t10Prompts: s10.prompts,
              t9: read("t9"),
              t10: read("t10"),
              missing: read("t404"),
            };
        """)
        self.assertFalse(r["t9HasTurns"])
        self.assertEqual(len(r["t9Prompts"]), 2)
        self.assertEqual(r["t10Prompts"], [])
        self.assertEqual(r["t9"]["text"], "two")
        self.assertEqual(r["t9"]["count"], 2)
        self.assertEqual([x["text"] for x in r["t9"]["history"]], ["two", "one"])
        self.assertIsNone(r["t10"])
        self.assertIsNone(r["missing"])


if __name__ == "__main__":
    unittest.main()
