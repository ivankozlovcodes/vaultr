"""mods/ob-agents: the left panel lists only main agents, the ones whose terminal sits in a pane of a tab. A background
agent (a terminal in no tab: an `hc run --bg` worker, a sub-agent) is left out; those belong to ob-outline. The filter
is a pure function in kit/agents.js (copied into the mod by kit/sync.sh), run here through node; main.js must use it for
the list it draws."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MOD = os.path.join(ROOT, "mods", "ob-agents")
FILTER = os.path.join(ROOT, "kit", "agents.js")
MAIN = os.path.join(MOD, "main.js")

# Shaped like the live data: agents() entries (AgentInfo) and panes() entries (PaneInfo), trimmed to the fields used.
AGENTS = [
    {"address": "t3c", "pane": "p1", "tab": "tb1", "status": "working"},      # in a pane of tab 1: main
    {"address": "t3j", "pane": "", "tab": "tb9", "status": "idle"},            # tab with no pane: background
    {"address": "devbox/t22", "pane": "p5", "tab": "tb5", "status": "idle"},  # remote, in a pane: main
    {"address": "t9z", "pane": "", "tab": "tb1", "status": "done"},            # same tab as t3c but no pane: background
]
PANES = [
    {"pane": "p1", "terminal": "t3c", "tab": "tb1"},
    {"pane": "p2", "terminal": "t3w", "tab": "tb1"},       # a shell, not an agent
    {"pane": "p3", "terminal": None, "mod": "notes", "tab": "tb1"},  # a mod pane has no terminal
    {"pane": "p5", "terminal": "devbox/t22", "tab": "tb5"},
]


def run_node(code, payload=None):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def filt(code_body, payload):
    url = "file://" + FILTER
    code = (f'import * as f from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            f'process.stdout.write(JSON.stringify(({code_body})(d)));\n')
    return run_node(code, payload)


class MainAgents(unittest.TestCase):
    def test_keeps_only_agents_whose_terminal_is_in_a_pane(self):
        got = filt("d => f.mainAgents(d.agents, f.placedTerminals(d.panes))", {"agents": AGENTS, "panes": PANES})
        self.assertEqual([a["address"] for a in got], ["t3c", "devbox/t22"])

    def test_keeps_the_order_it_was_given(self):
        agents = list(reversed(AGENTS))
        got = filt("d => f.mainAgents(d.agents, f.placedTerminals(d.panes))", {"agents": agents, "panes": PANES})
        self.assertEqual([a["address"] for a in got], ["devbox/t22", "t3c"])

    def test_a_pane_without_a_terminal_places_nothing(self):
        got = filt("d => [...f.placedTerminals(d.panes)]", {"agents": [], "panes": [PANES[2]]})
        self.assertEqual(got, [])

    def test_no_panes_means_no_main_agents(self):
        got = filt("d => f.mainAgents(d.agents, f.placedTerminals(d.panes))", {"agents": AGENTS, "panes": []})
        self.assertEqual(got, [])

    def test_a_background_agent_is_not_saved_by_the_same_tab(self):
        # t9z shares tab tb1 with t3c but has no pane of its own: only a pane places a terminal.
        got = filt("d => f.mainAgents(d.agents, f.placedTerminals(d.panes))", {"agents": [AGENTS[3]], "panes": PANES})
        self.assertEqual(got, [])


class Wiring(unittest.TestCase):
    def test_main_js_draws_only_the_filtered_list(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        # The mod imports the filter and filters the list it draws (the counts and the empty state follow that list).
        self.assertTrue('mainAgents' in src.split('from "./kit.js"')[0], "main.js must import mainAgents from ./kit.js")
        self.assertTrue("mainAgents(" in src, "main.js must filter agents() with mainAgents")
        self.assertFalse(os.path.exists(os.path.join(MOD, "filter.js")), "the filter moved to kit/agents.js")
        self.assertFalse("let list = agents()" in src, "the list must come from the filter, not agents()")
        self.assertFalse("const live = agents()" in src, "the header counts must use the filtered list")
        self.assertFalse("!agents().length" in src, "the empty state must use the filtered list")


class PanelNames(unittest.TestCase):
    """The Subagents panel is gone (Outline replaced it): no text a person reads may send them there."""
    def test_user_facing_text_names_outline_not_subagents(self):
        for mod, old in (("ob-agents", "listed in Subagents"), ("ob-props", "Open in Subagents"),
                         ("ob-sessions", "Open in Subagents"), ("ob-sessions", "all in Subagents")):
            with self.subTest(mod=mod):
                with open(os.path.join(ROOT, "mods", mod, "main.js"), encoding="utf-8") as f:
                    src = f.read()
                self.assertNotIn(old, src)
                self.assertIn("Outline", src)


def run_main(body, titles=None):
    """Import a copy of ob-agents/main.js in node with gpui/herdr stubbed and kit.js providing real cleanTitle plus
    sessionTitleOf backed by `titles` ({address: title})."""
    folder = tempfile.mkdtemp(prefix="ob-agents-main-")
    try:
        shutil.copy(os.path.join(MOD, "names.js"), os.path.join(folder, "names.js"))
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        src = (src.replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                  .replace('from "gpui-base"', 'from "./gpui-base.js"')
                  .replace('from "herdr"', 'from "./herdr.js"')
               + "\nexport { leadPanes, title };\n")
        Path(folder, "main.js").write_text(src, encoding="utf-8")
        Path(folder, "gpui-kit.js").write_text("export class View {}\nexport const div = () => null;\n", encoding="utf-8")
        Path(folder, "gpui-base.js").write_text(
            "export const v_flex = () => null;\nexport const h_flex = () => null;\n"
            "export const ScrollHandle = { new: () => ({}) };\nexport const Scrollbar = () => null;\n",
            encoding="utf-8",
        )
        herdr_fns = ["agents", "panes", "spaces", "terminals", "focused", "run", "theme", "props", "nextCommand", "settings", "setAgentOrder", "shared"]
        Path(folder, "herdr.js").write_text("".join(f"export const {n} = () => [];\n" for n in herdr_fns), encoding="utf-8")
        kit_stubs = ["S", "icon", "programIcon", "iconButton", "treeRow", "sectionHeader", "emptyState", "openMenu",
                     "statusMark", "needsYou", "normStatus", "takeFocus", "machineOf", "isBookmarked", "toggleBookmark",
                     "mainAgents", "placedTerminals", "normHidden", "isMachineHidden", "isSpaceHidden", "isTabHidden",
                     "getHidden", "isHidden", "hideItem", "unhideItem", "hiddenSummary",
                     "agentAttention", "attentionRank", "attentionCounts", "isNeedsYou", "isDismissed", "dismissStamp",
                     "getDismissed", "setDismissed", "pruneDismissedNow", "terminalsByAddress",
                     "dismissedSet", "needsYouShown", "dismissNeedsYou", "restoreNeedsYou", "pruneDismissed"]
        Path(folder, "kit.js").write_text(
            'export { cleanTitle } from "./names.js";\n'
            + "".join(f"export const {n} = () => null;\n" for n in kit_stubs)
            + f"const TITLES = {json.dumps(titles or {})};\n"
            + "export const sessionTitleOf = (addr) => TITLES[addr] ?? null;\n",
            encoding="utf-8",
        )
        code = (f'import * as M from "{Path(folder, "main.js").as_uri()}";\n'
                f'process.stdout.write(JSON.stringify((() => {{ {body} }})()));\n')
        return run_node(code)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class LeadPaneSessionTitles(unittest.TestCase):
    """ob-agents names an unnamed or program-named tab by its lead pane's sessionTitleOf(), cleaned via cleanTitle."""

    def test_unnamed_or_program_named_tab_uses_session_title_even_on_wrapped_shell_pane(self):
        got = run_main(
            'const shellLead = { terminal: "t3c", title: "~/git/vaultr", program: { name: "zsh", shell: true } };'
            'const agentLead = { terminal: "t3d", title: "Claude Code", program: { name: "Claude Code", key: "claude", agent: true } };'
            'return ['
            '  M.title({ named: false, name: "1" }, shellLead),'
            '  M.title({ named: true, name: "Claude Code" }, agentLead),'
            '  M.title({ named: true, name: "release-prep" }, agentLead),'
            '];',
            {"t3c": "✦ Audit Session Sync", "t3d": "✳ Stack Rebuild"},
        )
        self.assertEqual(got, ["Audit Session Sync", "Stack Rebuild", "release-prep"])

    def test_live_title_fallback_cleans_leading_symbols_and_wiring_imports_cleanTitle(self):
        got = run_main(
            'const lead = { terminal: "t9", title: "✦ · Draft notes", program: { name: "Claude Code", key: "claude", agent: true } };'
            'return M.title({ named: false, name: "1" }, lead);',
            {},
        )
        self.assertEqual(got, "Draft notes")
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        kit_imports = src.split('from "./kit.js"')[0]
        self.assertIn("cleanTitle", kit_imports)
        self.assertIn("sessionTitleOf", kit_imports)


if __name__ == "__main__":
    unittest.main()
