"""kit/names.js: one naming rule for panes (paneLabel) and the folder shortening it uses. Pure functions, run under
node (no Herdr or gpui imports). A pane is named for what it runs: an agent by its session title (else its program),
a shell by its folder, a mod by its panel's name. A label never equals the tab's name when a better one exists."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest

ROOT = home_guard.ROOT
MODULE = os.path.join(ROOT, "kit", "names.js")
NODE = shutil.which("node")
CLAUDE = {"name": "Claude Code", "agent": True}
SHELL = {"name": "zsh", "shell": True}


def run_node(body):
    src = (f'import * as N from "{MODULE}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def label(pane, ctx=None):
    return run_node(f'return N.paneLabel({json.dumps(pane)}, {json.dumps(ctx or {})});')


def short(folder, home="/fixture/user"):
    return run_node(f'return N.shortFolder({json.dumps(folder)}, {json.dumps(home)});')


def clean(s):
    return run_node(f'return N.cleanTitle({json.dumps(s)});')


@unittest.skipUnless(NODE, "node is not installed")
class AgentPane(unittest.TestCase):
    def test_an_agent_with_a_session_title_is_named_by_the_title(self):
        self.assertEqual(label({"program": CLAUDE}, {"sessionTitle": "herdr-trials", "home": "/fixture/user"}), "herdr-trials")

    def test_an_agent_without_a_title_is_named_by_its_program(self):
        self.assertEqual(label({"program": CLAUDE}, {"home": "/fixture/user"}), "Claude Code")
        self.assertEqual(label({"program": CLAUDE}, {"sessionTitle": "  ", "home": "/fixture/user"}), "Claude Code")

    def test_a_pi_agent_with_a_session_name_uses_it(self):
        self.assertEqual(label({"program": {"name": "pi", "agent": True}}, {"sessionTitle": "vaultr panes"}), "vaultr panes")

    def test_the_agent_kind_can_be_given_by_kind_or_by_program(self):
        self.assertEqual(label({"kind": "agent", "program": CLAUDE}, {"sessionTitle": "x"}), "x")

    def test_the_title_is_trimmed(self):
        self.assertEqual(label({"program": CLAUDE}, {"sessionTitle": "  herdr-trials \n"}), "herdr-trials")


@unittest.skipUnless(NODE, "node is not installed")
class ShellPane(unittest.TestCase):
    def test_a_shell_is_named_by_its_folder_with_home_shortened(self):
        self.assertEqual(label({"program": SHELL}, {"folder": "/fixture/user/git/vaultr", "home": "/fixture/user"}), "~/git/vaultr")

    def test_home_itself_is_tilde(self):
        self.assertEqual(short("/fixture/user", "/fixture/user"), "~")

    def test_a_folder_outside_home_is_kept_whole_when_short(self):
        self.assertEqual(short("/etc/nginx"), "/etc/nginx")

    def test_a_long_folder_keeps_only_its_last_two_parts(self):
        self.assertEqual(short("/fixture/user/vault/2 Projects/vaultr"), "…/2 Projects/vaultr")

    def test_a_trailing_slash_is_dropped(self):
        self.assertEqual(short("/fixture/user/git/vaultr/"), "~/git/vaultr")

    def test_a_shell_with_no_folder_is_named_by_its_program(self):
        self.assertEqual(label({"program": SHELL}, {"home": "/fixture/user"}), "zsh")

    def test_a_shell_falls_back_to_the_folder_from_the_pane_cwd(self):
        self.assertEqual(label({"program": SHELL, "cwd": "/fixture/user/git/vaultr"}, {"home": "/fixture/user"}), "~/git/vaultr")


@unittest.skipUnless(NODE, "node is not installed")
class ModPane(unittest.TestCase):
    def test_a_mod_pane_is_named_by_its_panel(self):
        self.assertEqual(label({"kind": "mod", "mod": "ob-outline"}, {"panelName": "Outline"}), "Outline")

    def test_a_mod_pane_with_no_panel_name_uses_the_mod_name(self):
        self.assertEqual(label({"kind": "mod", "mod": "ob-notes"}), "ob-notes")

    def test_a_mod_pane_ignores_a_session_title(self):
        self.assertEqual(label({"kind": "mod", "mod": "ob-notes"}, {"panelName": "Notes", "sessionTitle": "x"}), "Notes")


@unittest.skipUnless(NODE, "node is not installed")
class OtherPanes(unittest.TestCase):
    def test_a_program_that_is_neither_agent_nor_shell_is_named_by_its_program(self):
        self.assertEqual(label({"program": {"name": "htop"}}, {"folder": "/fixture/user"}), "htop")

    def test_a_pane_with_nothing_to_go_by_is_named_terminal(self):
        self.assertEqual(label({}), "Terminal")


@unittest.skipUnless(NODE, "node is not installed")
class NeverTheTabName(unittest.TestCase):
    def test_an_agent_titled_as_its_tab_is_named_by_its_program_instead(self):
        # The tab is named after its first program, and the session title happens to match it: the pane must not repeat it.
        self.assertEqual(label({"program": CLAUDE}, {"sessionTitle": "herdr-trials", "tabName": "herdr-trials"}), "Claude Code")

    def test_a_shell_whose_folder_is_the_tab_name_is_still_named_by_the_folder_when_that_differs(self):
        self.assertEqual(label({"program": SHELL}, {"folder": "/fixture/user/git/vaultr", "home": "/fixture/user", "tabName": "Claude Code"}), "~/git/vaultr")

    def test_when_every_candidate_is_the_tab_name_the_first_is_kept(self):
        self.assertEqual(label({"program": CLAUDE}, {"tabName": "Claude Code"}), "Claude Code")

    def test_the_label_never_equals_the_tab_name_when_a_better_one_exists(self):
        cases = [
            ({"program": CLAUDE}, {"sessionTitle": "herdr-trials"}),
            ({"program": SHELL}, {"folder": "/fixture/user/git/vaultr", "home": "/fixture/user"}),
            ({"kind": "mod", "mod": "ob-notes"}, {"panelName": "Notes"}),
        ]
        for pane, ctx in cases:
            tab = "Claude Code"
            self.assertNotEqual(label(pane, {**ctx, "tabName": tab}), tab, (pane, ctx))


@unittest.skipUnless(NODE, "node is not installed")
class Secondary(unittest.TestCase):
    """A tab row that stands for its only pane shows the pane's label under its name, when the two differ."""

    def secondary(self, tab, pane):
        return run_node(f'return N.paneSecondary({json.dumps(tab)}, {json.dumps(pane)});')

    def test_the_pane_label_shows_when_it_differs_from_the_tab_name(self):
        self.assertEqual(self.secondary("1", "herdr-trials"), "herdr-trials")

    def test_nothing_shows_when_the_pane_label_is_the_tab_name(self):
        self.assertIsNone(self.secondary("Claude Code", "Claude Code"))

    def test_nothing_shows_for_an_empty_pane_label(self):
        self.assertIsNone(self.secondary("1", ""))
        self.assertIsNone(self.secondary("1", None))

    def test_the_comparison_ignores_surrounding_spaces(self):
        self.assertIsNone(self.secondary(" vaultr ", "vaultr"))


@unittest.skipUnless(NODE, "node is not installed")
class Exports(unittest.TestCase):
    def test_kit_re_exports_the_naming_rule_like_the_agent_helpers(self):
        with open(os.path.join(ROOT, "kit", "kit.js"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('from "./names.js"', text)
        self.assertIn("paneLabel", text)
        self.assertIn("cleanTitle", text)

    def test_sync_copies_names_js_into_every_mod(self):
        with open(os.path.join(ROOT, "kit", "sync.sh"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("names.js", text)


@unittest.skipUnless(NODE, "node is not installed")
class CleanTitleAndWrappedAgent(unittest.TestCase):
    def test_clean_title_trims_and_drops_leading_symbols_while_keeping_words_and_paths(self):
        self.assertEqual(run_node("return N.cleanTitle.length;"), 1)
        cases = [
            ("🟢 Refactor Graph Layout", "Refactor Graph Layout"),
            ("⠋ · Audit Session Sync", "Audit Session Sync"),
            ("— Build Bundle", "Build Bundle"),
            ("🟢 Working · Refactor Graph Layout", "Working · Refactor Graph Layout"),
            ("Idle: Audit Session Sync", "Idle: Audit Session Sync"),
            ("~/git/vaultr", "~/git/vaultr"),
            ("/usr/local/bin", "/usr/local/bin"),
            ("  plain session title  ", "plain session title"),
            ("🟢 ", ""),
            ("", ""),
            (None, ""),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean(raw), want)

    def test_shell_wrapped_agent_pane_uses_session_title(self):
        self.assertEqual(
            label(
                {"program": SHELL, "cwd": "/fixture/user"},
                {"sessionTitle": "🟢 Audit Session Sync", "home": "/fixture/user"},
            ),
            "Audit Session Sync",
        )


if __name__ == "__main__":
    unittest.main()
