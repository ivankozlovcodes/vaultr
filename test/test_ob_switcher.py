"""mods/ob-switcher/commands.js: the switcher's command mode (">") lists Vaultr's commands and Herdr's app commands
as one fuzzy-matched list. Pure functions, run under node (no Herdr or gpui imports)."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MODULE = os.path.join(ROOT, "mods", "ob-switcher", "commands.js")
NODE = shutil.which("node")

# A plain substring matcher stands in for the switcher's fuzzy(): the rules under test are the list's, not the scorer's.
MATCH = "(q, text) => { const i = String(text).toLowerCase().indexOf(String(q).toLowerCase()); return i < 0 ? null : { score: 10 - i / 100, hits: [] }; }"

VAULTR = [
    {"route": "ob-tabs.zen", "label": "Toggle Zen mode", "context": "Zen mode: Toggle", "words": "zen mode toggle focus"},
    {"route": "ob-tabs.open:ob-outline", "label": "View: Outline", "context": "sidebar", "words": "view panel sidebar", "kind": "view"},
]
HERDR = [
    {"name": "tab.new", "args": [{"name": "name", "required": False}], "about": "Make a tab in this space."},
    {"name": "pane.split", "args": [{"name": "direction", "required": True}], "about": "Split the pane."},
    {"name": "space.move", "args": [{"name": "id", "required": True}, {"name": "index", "required": True}], "about": "Move a space."},
    {"name": "app.palette", "args": [], "about": "Toggle the command palette."},
    {"name": "ob-tabs.zen", "args": [], "about": "A Herdr command that duplicates a Vaultr route."},
]
KEYS = [
    {"section": "layout:vaultr", "keys": "ctrl-shift-z", "action": "ob-tabs.zen"},
    {"section": "global", "keys": "ctrl-shift-z", "action": "pane.zoom"},
    {"section": "global", "keys": "ctrl-shift-t", "action": "tab.new"},
    {"section": "global", "keys": "ctrl-shift-p", "action": "app.palette"},
    {"section": "global", "keys": "ctrl-x", "action": "tab.new:x"},
    {"section": "layout:vaultr", "keys": "ctrl-y", "action": "tab.new"},
]


def run_node(body):
    src = (f'import * as C from "{MODULE}";\n'
           f'const MATCH = {MATCH};\n'
           f'const VAULTR = {json.dumps(VAULTR)};\n'
           f'const HERDR = {json.dumps(HERDR)};\n'
           f'const KEYS = {json.dumps(KEYS)};\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def rows(query):
    return run_node(f'return C.commandRows({{ vaultr: VAULTR, herdr: HERDR, keys: KEYS, query: {json.dumps(query)}, match: MATCH }})'
                    '.map((r) => ({ route: r.item.route, label: r.item.label, chord: r.item.chord ?? null, '
                    'disabled: !!r.item.disabled, hint: r.item.hint ?? null, source: r.item.source, kind: r.item.kind }));')


@unittest.skipUnless(NODE, "node is not installed")
class CommandPrefix(unittest.TestCase):
    def test_greater_than_enters_command_mode(self):
        self.assertEqual(run_node('return C.commandQuery(">");'), "")
        self.assertEqual(run_node('return C.commandQuery("> zen");'), "zen")
        self.assertEqual(run_node('return C.commandQuery("  >tab ");'), "tab")

    def test_plain_query_is_not_command_mode(self):
        self.assertIsNone(run_node('return C.commandQuery("zen");'))
        self.assertIsNone(run_node('return C.commandQuery("");'))


@unittest.skipUnless(NODE, "node is not installed")
class MergedList(unittest.TestCase):
    def test_empty_query_lists_vaultr_then_herdr(self):
        labels = [r["label"] for r in rows("")]
        self.assertEqual(labels[0], "Toggle Zen mode")
        self.assertIn("tab.new", labels)
        self.assertIn("pane.split", labels)

    def test_herdr_palette_entry_is_present_once_and_routes_to_app_palette(self):
        palette = [r for r in rows("") if r["route"] == "app.palette"]
        self.assertEqual(len(palette), 1)
        self.assertEqual(palette[0]["label"], "Herdr command palette…")
        self.assertEqual(palette[0]["source"], "herdr-palette")

    def test_query_matches_both_sources(self):
        labels = [r["label"] for r in rows("tab")]
        self.assertIn("tab.new", labels)
        self.assertNotIn("Toggle Zen mode", labels)
        self.assertEqual(rows("palette")[0]["route"], "app.palette")

    def test_no_match_is_empty(self):
        self.assertEqual(rows("zzzz-nothing"), [])

    def test_same_route_in_both_lists_appears_once_as_vaultr(self):
        hits = [r for r in rows("zen") if r["route"] == "ob-tabs.zen"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["source"], "vaultr")
        self.assertEqual(len([r for r in rows("") if r["route"] == "ob-tabs.zen"]), 1)


@unittest.skipUnless(NODE, "node is not installed")
class KeyHints(unittest.TestCase):
    def test_vaultr_command_gets_its_layout_key(self):
        zen = next(r for r in rows("") if r["route"] == "ob-tabs.zen")
        self.assertEqual(zen["chord"], "ctrl-shift-z")

    def test_herdr_command_gets_its_global_key(self):
        tab = next(r for r in rows("") if r["route"] == "tab.new")
        self.assertEqual(tab["chord"], "ctrl-y")  # layout:vaultr wins over global for the same action

    def test_global_key_is_used_when_the_layout_has_none(self):
        self.assertEqual(run_node('return C.chordFor(KEYS, "app.palette", "vaultr");'), "ctrl-shift-p")

    def test_command_without_a_key_has_no_hint(self):
        self.assertIsNone(run_node('return C.chordFor(KEYS, "pane.split", "vaultr");'))

    def test_action_with_arguments_does_not_match_the_bare_command(self):
        # "tab.new:x" is bound; the bare command's hint must come from its own binding, not the argument form.
        self.assertEqual(run_node('return C.chordFor(KEYS, "tab.new:x", "vaultr");'), "ctrl-x")


@unittest.skipUnless(NODE, "node is not installed")
class Arguments(unittest.TestCase):
    def test_command_with_required_arguments_is_listed_but_not_runnable(self):
        split = next(r for r in rows("") if r["route"] == "pane.split")
        self.assertTrue(split["disabled"])
        self.assertEqual(split["hint"], "needs: direction")

    def test_greyed_rows_sort_after_every_runnable_row(self):
        labels = [r for r in rows("")]
        last_runnable = max(i for i, r in enumerate(labels) if not r["disabled"])
        first_disabled = min(i for i, r in enumerate(labels) if r["disabled"])
        self.assertLess(last_runnable, first_disabled)
        self.assertEqual(labels[-1]["disabled"], True)

    def test_several_required_arguments_are_named_in_order(self):
        move = next(r for r in rows("") if r["route"] == "space.move")
        self.assertEqual(move["hint"], "needs: id, index")

    def test_commands_mode_drops_view_rows(self):
        # Views have their own mode: a Vaultr view row never appears in the command list.
        self.assertEqual([r for r in rows("") if r["kind"] == "view"], [])
        self.assertEqual([r for r in rows("outline") if r["kind"] == "view"], [])


class CommandModeWiring(unittest.TestCase):
    def test_ob_tabs_switcher_accepts_the_commands_mode(self):
        with open(os.path.join(ROOT, "mods", "ob-tabs", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('["go", "move", "views", "commands"].includes(mode)', src)

    def test_switcher_opens_in_command_mode_from_props(self):
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('m === "commands"', src)
        self.assertIn('modeForQuery', src)


MODES_MODULE = os.path.join(ROOT, "mods", "ob-switcher", "modes.js")


def run_modes(body):
    src = (f'import * as M from "{MODES_MODULE}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class OneModeSystem(unittest.TestCase):
    """Everything (go), Views, Commands: one cycle for Tab, one prefix rule for ">", one header, one hint."""

    def test_tab_cycles_everything_views_commands(self):
        self.assertEqual(run_modes('return [M.nextMode("go"), M.nextMode("views"), M.nextMode("commands")];'),
                         ["views", "commands", "go"])

    def test_shift_tab_goes_backwards(self):
        self.assertEqual(run_modes('return [M.nextMode("go", -1), M.nextMode("views", -1), M.nextMode("commands", -1)];'),
                         ["commands", "go", "views"])

    def test_typing_greater_than_enters_commands_from_any_mode(self):
        self.assertEqual(run_modes('return M.modeForQuery("views", null, ">");'), {"mode": "commands", "base": "views"})
        self.assertEqual(run_modes('return M.modeForQuery("go", null, "> zen");'), {"mode": "commands", "base": "go"})

    def test_deleting_the_prefix_returns_to_the_mode_you_came_from(self):
        self.assertEqual(run_modes('return M.modeForQuery("commands", "views", "zen");'),
                         {"mode": "views", "base": "views"})
        self.assertEqual(run_modes('return M.modeForQuery("commands", "go", "");'), {"mode": "go", "base": "go"})

    def test_plain_typing_keeps_the_mode(self):
        self.assertEqual(run_modes('return M.modeForQuery("views", null, "zen");'), {"mode": "views", "base": "views"})

    def test_query_text_follows_the_mode(self):
        self.assertEqual(run_modes('return M.queryForMode("commands", "zen");'), "> zen")
        self.assertEqual(run_modes('return M.queryForMode("commands", "> zen");'), "> zen")
        self.assertEqual(run_modes('return M.queryForMode("go", "> zen");'), "zen")
        self.assertEqual(run_modes('return M.queryForMode("views", "zen");'), "zen")

    def test_header_names_the_current_mode(self):
        self.assertEqual(run_modes('return [M.headerLabel("go"), M.headerLabel("views"), M.headerLabel("commands")];'),
                         ["Everything", "Views", "Commands"])

    def test_footer_says_where_tab_goes_next(self):
        self.assertEqual(run_modes('return [M.tabHint("go"), M.tabHint("views"), M.tabHint("commands")];'),
                         ["→ Views", "→ Commands", "→ Everything"])

    def test_placeholder_per_mode(self):
        self.assertEqual(run_modes('return [M.placeholder("go"), M.placeholder("views"), M.placeholder("commands")];'),
                         ["Go to a tab, space or view…", "Find a view…", "Run a command…"])


@unittest.skipUnless(NODE, "node is not installed")
class ModeRowFilter(unittest.TestCase):
    def test_commands_takes_commands_only(self):
        self.assertFalse(run_modes('return M.allowsRow("commands", {kind: "view"});'))
        self.assertTrue(run_modes('return M.allowsRow("commands", {kind: "command"});'))

    def test_views_takes_views_only(self):
        self.assertTrue(run_modes('return M.allowsRow("views", {kind: "view"});'))
        self.assertFalse(run_modes('return M.allowsRow("views", {kind: "tab"});'))

    def test_everything_takes_every_kind(self):
        self.assertTrue(run_modes('return M.allowsRow("go", {kind: "view"}) && M.allowsRow("go", {kind: "tab"});'))

    def test_disabled_rows_sink_to_the_end_in_order(self):
        out = run_modes('const r = [{item: {label: "a", disabled: true}}, {item: {label: "b"}}, '
                        '{item: {label: "c", disabled: true}}, {item: {label: "d"}}];'
                        'return M.sinkDisabled(r).map((x) => x.item.label);')
        self.assertEqual(out, ["b", "d", "a", "c"])


class ModeWiring(unittest.TestCase):
    def test_main_uses_the_mode_module(self):
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('from "./modes.js"', src)
        self.assertIn("headerLabel(", src)
        self.assertIn("tabHint(", src)
        self.assertNotIn('"Views" : "Everything"', src)

    def test_shift_tab_cycles_the_modes_backwards(self):
        # modes.js has the step (nextMode(mode, -1)); the key handler must pass it, not always go forward.
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(src, r"cycleMode\(step = 1\) \{[^}]*this\.select\(nextMode\(this\.mode, step\)\)")
        self.assertRegex(src, r'k === "tab"[^\n]*this\.cycleMode\(m\.shift \? -1 : 1\)')

    def test_query_command_goes_through_the_typing_rule(self):
        # set_value does not fire "change" (setMode and ob-search call their own handlers after it), so the query:
        # verb must run typed() itself, or "query:>zen" never enters Commands.
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        line = next(l for l in src.splitlines() if 'verb === "query"' in l)
        self.assertIn("this.input.set_value(arg); this.typed(arg);", line)

    def test_ob_tabs_tells_an_open_switcher_the_mode(self):
        with open(os.path.join(ROOT, "mods", "ob-tabs", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("ob-switcher.mode:", src)


TITLES_MODULE = os.path.join(ROOT, "mods", "ob-switcher", "titles.js")


def run_titles(body):
    src = (f'import * as T from "{TITLES_MODULE}";\n'
           f'const SUB = (q, text) => {{ const i = String(text).toLowerCase().indexOf(String(q).toLowerCase()); return i < 0 ? null : {{ score: 10 - i / 100, hits: [] }}; }};\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class SessionTitles(unittest.TestCase):
    """A tab's searchable titles: the titles of the agents and terminals in its panes, and the session names the
    sub-agent feed knows for them. Every one is read from shared state; none is copied into the mod."""

    def test_an_agents_session_title_belongs_to_its_tab(self):
        r = run_titles('const tabOf = new Map([["t-1", "tab-1"]]);'
                       'return T.sessionTitles(tabOf, { agents: [{ address: "t-1", title: "herdr-trials" }] }).get("tab-1");')
        self.assertEqual(r, ["herdr-trials"])

    def test_feed_session_names_and_terminal_titles_are_included_once(self):
        r = run_titles('const tabOf = new Map([["t-1", "tab-1"], ["t-2", "tab-1"]]);'
                       'return T.sessionTitles(tabOf, { agents: [{ address: "t-1", title: "herdr-trials" }],'
                       ' terminals: [{ address: "t-2", title: "herdr-trials", name: "pi notes" }],'
                       ' terms: { "t-1": { name: "herdr-trials" } } }).get("tab-1");')
        self.assertEqual(sorted(r), ["herdr-trials", "pi notes"])

    def test_blank_titles_and_unplaced_terminals_are_left_out(self):
        r = run_titles('const tabOf = new Map([["t-1", "tab-1"]]);'
                       'const m = T.sessionTitles(tabOf, { agents: [{ address: "t-1", title: "  " }, { address: "t-9", title: "orphan" }] });'
                       'return [...m.entries()];')
        self.assertEqual(r, [])

    def test_leading_symbols_are_cleaned_and_symbol_only_titles_are_dropped(self):
        r = run_titles('const tabOf = new Map([["t-1", "tab-1"], ["t-2", "tab-1"], ["t-3", "tab-1"]]);'
                       'return T.sessionTitles(tabOf, {'
                       '  agents: [{ address: "t-1", title: "✦ ✳ herdr-trials" }],'
                       '  terminals: [{ address: "t-2", title: " · " }, { address: "t-3", title: "~/git/vaultr" }],'
                       '}).get("tab-1");')
        self.assertEqual(r, ["herdr-trials", "~/git/vaultr"])

    def test_bestTitle_returns_the_matching_title(self):
        r = run_titles('return T.bestTitle("herdr-trials", ["Claude Code", "herdr-trials"], SUB);')
        self.assertEqual(r["title"], "herdr-trials")

    def test_bestTitle_is_null_when_no_title_matches(self):
        self.assertIsNone(run_titles('return T.bestTitle("zzz", ["Claude Code", "herdr-trials"], SUB);'))
        self.assertIsNone(run_titles('return T.bestTitle("herdr", [], SUB);'))


class TitleWiring(unittest.TestCase):
    def test_tab_rows_carry_their_session_titles(self):
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('from "./titles.js"', src)
        self.assertIn("sessionTitles(", src)
        self.assertIn("bestTitle(", src)



class AgentNames(unittest.TestCase):
    """An agent row in the switcher is named by its session title (kit sessionTitleOf), else its program, not its raw
    terminal title, which is a task line that changes."""

    def setUp(self):
        self.src = Path(ROOT, "mods", "ob-switcher", "main.js").read_text(encoding="utf-8")

    def test_an_agent_row_is_labelled_by_its_session_title_then_its_program(self):
        self.assertIn('label: sessionTitleOf(a.address) || a.program?.name || a.app || "agent"', self.src)


if __name__ == "__main__":
    unittest.main()
