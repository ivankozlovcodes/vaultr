"""mods/ob-switcher/commands.js: the switcher's command mode (">") lists Vaultr's commands and Herdr's app commands
as one fuzzy-matched list. Pure functions, run under node (no Herdr or gpui imports)."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
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
    {"name": "pane.go", "args": [{"name": "direction", "required": True}], "about": "Focus neighbor pane."},
    {"name": "pane.swap", "args": [{"name": "direction", "required": False}, {"name": "pane", "required": False}, {"name": "target", "required": False}], "about": "Swap panes."},
    {"name": "tab.select", "args": [{"name": "index", "required": False}, {"name": "id", "required": False}], "about": "Show a tab."},
    {"name": "space.select", "args": [{"name": "index", "required": False}, {"name": "id", "required": False}], "about": "Show a space."},
    {"name": "layout.switch", "args": [{"name": "name", "required": False}], "about": "Show a layout."},
    {"name": "space.move", "args": [{"name": "id", "required": True}, {"name": "index", "required": True}], "about": "Move a space."},
    {"name": "tab.move", "args": [{"name": "id", "required": True}, {"name": "index", "required": True}], "about": "Move a tab."},
    {"name": "pane.focus", "args": [{"name": "pane", "required": False}], "about": "Focus a pane."},
    {"name": "terminal.keep", "args": [{"name": "terminal", "required": True}], "about": "Keep a terminal."},
    {"name": "terminal.park", "args": [{"name": "terminal", "required": True}], "about": "Park a terminal."},
    {"name": "terminal.kill", "args": [{"name": "terminal", "required": True}], "about": "Kill a terminal."},
    {"name": "terminal.show", "args": [{"name": "terminal", "required": False}], "about": "Show a terminal."},
    {"name": "agent.focus", "args": [{"name": "terminal", "required": True}], "about": "Focus an agent."},
    {"name": "layout.set", "args": [{"name": "layout", "required": True}], "about": "Set layout."},
    {"name": "layout.toggle", "args": [{"name": "id", "required": True}], "about": "Toggle layout node."},
    {"name": "layout.show", "args": [{"name": "id", "required": True}], "about": "Show layout node."},
    {"name": "layout.hide", "args": [{"name": "id", "required": True}], "about": "Hide layout node."},
    {"name": "layout.resize", "args": [{"name": "id", "required": True}], "about": "Resize layout node."},
    {"name": "layout.select", "args": [{"name": "stack", "required": True}, {"name": "child", "required": True}], "about": "Select layout child."},
    {"name": "mod.open", "args": [{"name": "name", "required": True}], "about": "Open mod."},
    {"name": "overlay.close", "args": [{"name": "id", "required": False}], "about": "Close overlay."},
    {"name": "tab.settle", "args": [{"name": "id", "required": False}], "about": "Settle tab."},
    {"name": "tab.unsettle", "args": [{"name": "id", "required": False}], "about": "Unsettle tab."},
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


def rows(query, extra=""):
    return run_node(f'return C.commandRows({{ vaultr: VAULTR, herdr: HERDR, keys: KEYS, query: {json.dumps(query)}, match: MATCH{extra} }})'
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
        routes = [r["route"] for r in rows("")]
        self.assertIn("pane.split:right", routes)
        self.assertIn("pane.split:down", routes)

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

    def test_macos_prefers_cmd_chord_over_ctrl_for_same_action(self):
        k = [
            {"section": "layout:vaultr", "keys": "ctrl-\\", "action": "pane.split:right"},
            {"section": "layout:vaultr", "keys": "cmd-\\", "action": "pane.split:right"},
            {"section": "global", "keys": "ctrl-shift-p", "action": "app.palette"},
            {"section": "global", "keys": "cmd-shift-p", "action": "app.palette"},
        ]
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "pane.split:right", "vaultr", "macos");'), "cmd-\\")
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "pane.split:right", "vaultr", "linux");'), "ctrl-\\")
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "app.palette", "vaultr", "macos");'), "cmd-shift-p")
        mac_rows = rows("", f', keys: {json.dumps(k)}, platform: "macos"')
        split = next(r for r in mac_rows if r["route"] == "pane.split:right")
        self.assertEqual(split["chord"], "cmd-\\")

    def test_object_binding_matches_shorthand_route(self):
        k = [
            {"section": "layout:vaultr", "keys": "alt-r", "action": '{"command":"pane.split","args":{"direction":"right"}}'},
            {"section": "global", "keys": "cmd-3", "action": '{"args":{"index":3},"command":"tab.select"}'},
            {"section": "global", "keys": "ctrl-alt-d", "action": '{"command":"pane.split","args":{"direction":"down"}}'},
        ]
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "pane.split:right", "vaultr", "macos");'), "alt-r")
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "pane.split:down", "vaultr", "macos");'), "ctrl-alt-d")
        self.assertEqual(run_node(f'return C.chordFor({json.dumps(k)}, "tab.select:3", "vaultr", "macos");'), "cmd-3")
        self.assertIsNone(run_node(f'return C.chordFor({json.dumps(k)}, "pane.split", "vaultr", "macos");'))


@unittest.skipUnless(NODE, "node is not installed")
class Arguments(unittest.TestCase):
    def test_parameterized_commands_are_expanded_and_runnable(self):
        out = rows("", ', layouts: ["vaultr", "main"]')
        routes = {r["route"]: r for r in out}
        for route in [
            "pane.split:right", "pane.split:down",
            "pane.go:left", "pane.go:right", "pane.go:up", "pane.go:down",
            "pane.swap:left", "pane.swap:right", "pane.swap:up", "pane.swap:down",
            *(f"tab.select:{i}" for i in range(1, 10)),
            *(f"space.select:{i}" for i in range(1, 10)),
            "layout.switch", "layout.switch:vaultr", "layout.switch:main",
        ]:
            self.assertIn(route, routes, route)
            self.assertFalse(routes[route]["disabled"], route)
            self.assertIsNone(routes[route]["hint"], route)
        self.assertFalse(any(r["disabled"] for r in out))

    def test_pointer_only_and_bare_required_commands_are_hidden(self):
        routes = {r["route"] for r in rows("")}
        hidden = {
            "pane.split", "pane.go", "pane.swap", "tab.select", "space.select",
            "space.move", "tab.move", "pane.focus", "terminal.keep", "terminal.park",
            "terminal.kill", "terminal.show", "agent.focus", "layout.set", "layout.toggle",
            "layout.show", "layout.hide", "layout.resize", "layout.select", "mod.open",
            "overlay.close", "tab.settle", "tab.unsettle",
        }
        self.assertEqual(routes & hidden, set())

    def test_vaultr_commands_table_covers_all_vaultr_commands(self):
        vaultr_cmds = run_node('return C.VAULTR_COMMANDS;')
        routes = {c["route"] for c in vaultr_cmds}
        for route in [
            "pane.split:right", "pane.split:down",
            "layout.toggle:ob-left", "layout.toggle:ob-right",
            "ob-tabs.copy-path", "ob-tabs.copy-address", "ob-tabs.daily",
            "ob-tabs.bookmark", "ob-tabs.back", "ob-tabs.forward", "ob-tabs.last",
            "ob-tabs.settings:hotkeys", "mod.open:ob-settings", "ob-tabs.tab-list",
            "ob-tabs.new", "ob-tabs.switcher:views", "ob-tabs.switcher:move",
            "ob-tabs.open:ob-sessions@reveal", "ob-tabs.toggle:ob-outline",
            "ob-sessions.collapse-all",
            "ob-sessions.expand-all", "ob-feed.refresh", "ob-graph.fit", "ob-tabs.zen",
        ]:
            self.assertIn(route, routes, route)

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

    def test_switcher_registers_vaultr_commands_and_passes_platform(self):
        with open(os.path.join(ROOT, "mods", "ob-switcher", "main.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("VAULTR_COMMANDS", src)
        self.assertIn("appWindow()?.platform", src)
        self.assertIn("layouts:", src)


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


def el_stub_js():
    return (
        "const proxyEl = () => {\n"
        "  const rec = { keyContext: null, actions: {} };\n"
        "  const p = new Proxy(() => p, {\n"
        "    get(_t, prop) {\n"
        '      if (prop === "__rec") return rec;\n'
        '      if (prop === "when") return (cond, fn) => { if (cond) fn(p); return p; };\n'
        '      if (prop === "key_context") return (ctx) => { rec.keyContext = ctx; return p; };\n'
        '      if (prop === "on_action") return (name, fn) => { rec.actions[name] = fn; return p; };\n'
        "      return () => p;\n"
        "    },\n"
        "  });\n"
        "  return p;\n"
        "};\n"
    )


@unittest.skipUnless(NODE, "node is not installed")
class OverlayKeyContext(unittest.TestCase):
    """ObSwitcher and ObMenu bind overlay keys via key_context + cx.bind_keys + on_action and rebind on keys() reload."""

    def test_ob_switcher_binds_overlay_keys_and_cycles_mode_and_rebinds_on_keys_reload(self):
        with tempfile.TemporaryDirectory(prefix="ob-switcher-keys-") as folder:
            for f in ("main.js", "commands.js", "titles.js", "modes.js", "names.js"):
                shutil.copy(os.path.join(ROOT, "mods", "ob-switcher", f), os.path.join(folder, f))
            src = Path(folder, "main.js").read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            Path(folder, "main.js").write_text(src, encoding="utf-8")
            Path(folder, "gpui-kit.js").write_text(
                el_stub_js() + "export class View {}\nexport const div = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "gpui-base.js").write_text(
                el_stub_js()
                + "export const v_flex = () => proxyEl();\n"
                + "export const h_flex = () => proxyEl();\n"
                + "export const ScrollHandle = { new: () => ({ scroll_to_item() {} }) };\n"
                + "export const Scrollbar = { vertical: () => proxyEl() };\n"
                + "export const Input = { new: () => proxyEl() };\n"
                + "export const InputState = { new: () => { const handlers = {}; let val = ''; return { handlers, on(ev, fn) { handlers[ev] = fn; }, value() { return val; }, set_value(v) { val = v; }, focus() {} }; } };\n",
                encoding="utf-8",
            )
            Path(folder, "herdr.js").write_text(
                "export const state = { keys: [{ section: 'global', keys: 'ctrl-p', action: 'x' }], closed: [], ran: [] };\n"
                "export const props = () => ({ mode: 'go', overlay: 'sw-ov' });\n"
                "export const run = (a, b) => state.ran.push([a, b]);\n"
                "export const closeOverlay = (ov) => state.closed.push(ov);\n"
                "export const nextCommand = () => new Promise(() => {});\n"
                "export const shared = () => null;\n"
                "export const spaces = () => [];\n"
                "export const panes = () => [];\n"
                "export const agents = () => [];\n"
                "export const terminals = () => [];\n"
                "export const layout = () => null;\n"
                "export const layouts = () => ['vaultr'];\n"
                "export const settings = () => ({ zoom: 1 });\n"
                "export const commands = () => [];\n"
                "export const keys = () => state.keys;\n"
                "export const window = () => ({ platform: 'linux' });\n",
                encoding="utf-8",
            )
            kit_fns = [
                "tc", "alpha", "icon", "programIcon", "avatar", "statusMark", "fuzzy", "highlight",
                "machineLabel", "tabLabel", "feed", "bookmarks", "findNode", "current", "chordParts",
                "kbd", "sessionTitleOf", "normHidden", "isSpaceHidden", "isTabHidden", "patchHidden",
                "updateHidden", "getHidden", "parentAddrOf",
            ]
            Path(folder, "kit.js").write_text(
                el_stub_js()
                + "export const S = { icon: 16, iconSm: 14, iconXs: 12, radius: 4, radiusLg: 6, text: 13, textSm: 12, textXs: 11, textLg: 15 };\n"
                + "export const VIEWS = {};\n"
                + "export const tc = () => ({});\n"
                + "export const bookmarks = () => [];\n"
                + "export const current = () => ({});\n"
                + "export const chordParts = () => ['Ctrl'];\n"
                + "".join(f"export const {n} = () => null;\n" for n in kit_fns if n not in ("tc", "bookmarks", "current", "chordParts")),
                encoding="utf-8",
            )
            code = (
                f'import Switcher from "{Path(folder, "main.js").as_uri()}";\n'
                f'import {{ state }} from "{Path(folder, "herdr.js").as_uri()}";\n'
                "const binds = [];\n"
                "const timers = [];\n"
                "const cx = {\n"
                "  focus_handle: () => ({ focus() {} }),\n"
                "  bind_keys: (list) => binds.push(list),\n"
                "  timer: { after: (_ms, fn) => timers.push(fn) },\n"
                "  spawn: () => {},\n"
                "  notify: () => {},\n"
                "};\n"
                "const sw = new Switcher();\n"
                "sw.init({}, cx);\n"
                "const submitHandlers = Object.values(sw.inputs).map((i) => Boolean(i.handlers.submit));\n"
                "const root1 = sw.render(cx).__rec;\n"
                "root1.actions['ob_switcher.tab'](null, cx);\n"
                "const modeAfterTab = sw.mode;\n"
                "root1.actions['ob_switcher.shift_tab'](null, cx);\n"
                "const modeAfterShiftTab = sw.mode;\n"
                "root1.actions['ob_switcher.escape'](null, cx);\n"
                "state.keys = [{ section: 'global', keys: 'ctrl-k', action: 'y' }];\n"
                "sw.render(cx);\n"
                "for (const fn of timers.splice(0)) fn(cx);\n"
                "console.log(JSON.stringify({\n"
                "  bindCount: binds.length,\n"
                "  contexts: [...new Set(binds[0].map((b) => b.context))],\n"
                "  boundKeys: binds[0].map((b) => [b.keystroke, b.action]),\n"
                "  submitHandlers,\n"
                "  keyContext: root1.keyContext,\n"
                "  actions: Object.keys(root1.actions),\n"
                "  modeAfterTab,\n"
                "  modeAfterShiftTab,\n"
                "  closed: state.closed,\n"
                "}));\n"
            )
            res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["bindCount"], 2)  # initial bind in init() + rebind after keys() changed
            self.assertEqual(got["contexts"], ["ObSwitcher"])
            self.assertIn(["escape", "ob_switcher.escape"], got["boundKeys"])
            self.assertIn(["tab", "ob_switcher.tab"], got["boundKeys"])
            self.assertIn(["shift-tab", "ob_switcher.shift_tab"], got["boundKeys"])
            self.assertIn(["enter", "ob_switcher.open"], got["boundKeys"])
            self.assertEqual(got["submitHandlers"], [False, False, False, False])
            self.assertEqual(got["keyContext"], "ObSwitcher")
            for act in ("ob_switcher.escape", "ob_switcher.down", "ob_switcher.up", "ob_switcher.pagedown",
                        "ob_switcher.pageup", "ob_switcher.tab", "ob_switcher.shift_tab", "ob_switcher.open",
                        "ob_switcher.create", "ob_switcher.right"):
                self.assertIn(act, got["actions"])
            self.assertEqual(got["modeAfterTab"], "views")
            self.assertEqual(got["modeAfterShiftTab"], "go")
            self.assertEqual(got["closed"], ["sw-ov"])

    def test_ob_menu_binds_overlay_keys_and_rebinds_on_keys_reload(self):
        with tempfile.TemporaryDirectory(prefix="ob-menu-keys-") as folder:
            shutil.copy(os.path.join(ROOT, "mods", "ob-menu", "main.js"), os.path.join(folder, "main.js"))
            src = Path(folder, "main.js").read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            Path(folder, "main.js").write_text(src, encoding="utf-8")
            Path(folder, "gpui-kit.js").write_text(
                el_stub_js() + "export class View {}\nexport const div = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "gpui-base.js").write_text(
                el_stub_js() + "export const v_flex = () => proxyEl();\nexport const h_flex = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "herdr.js").write_text(
                "export const state = { keys: [{ section: 'global', keys: 'a', action: 'b' }], closed: [], ran: [] };\n"
                "export const props = () => ({ overlay: 'menu-ov', items: [{ label: 'One', command: 'cmd.one' }, { label: 'Two', command: 'cmd.two' }] });\n"
                "export const run = (a, b) => state.ran.push([a, b]);\n"
                "export const closeOverlay = (ov) => state.closed.push(ov);\n"
                "export const openOverlay = () => {};\n"
                "export const nextCommand = () => new Promise(() => {});\n"
                "export const keys = () => state.keys;\n",
                encoding="utf-8",
            )
            Path(folder, "kit.js").write_text(
                el_stub_js()
                + "export const S = { text: 13, textXs: 11, iconSm: 14, radius: 4 };\n"
                + "export const icon = () => proxyEl();\n"
                + "export const kbd = () => proxyEl();\n"
                + "export const tc = () => ({});\n"
                + "export const alpha = () => '#000';\n",
                encoding="utf-8",
            )
            code = (
                f'import Menu from "{Path(folder, "main.js").as_uri()}";\n'
                f'import {{ state }} from "{Path(folder, "herdr.js").as_uri()}";\n'
                "const binds = [];\n"
                "const timers = [];\n"
                "const cx = {\n"
                "  focus_handle: () => ({ focus() {} }),\n"
                "  bind_keys: (list) => binds.push(list),\n"
                "  timer: { after: (_ms, fn) => timers.push(fn) },\n"
                "  spawn: () => {},\n"
                "  notify: () => {},\n"
                "};\n"
                "const m = new Menu();\n"
                "m.init({}, cx);\n"
                "const root1 = m.render(cx).__rec;\n"
                "root1.actions['ob_menu.end'](null, cx);\n"
                "const atAfterEnd = m.at;\n"
                "root1.actions['ob_menu.enter'](null, cx);\n"
                "root1.actions['ob_menu.escape'](null, cx);\n"
                "state.keys = [{ section: 'global', keys: 'c', action: 'd' }];\n"
                "m.render(cx);\n"
                "for (const fn of timers.splice(0)) fn(cx);\n"
                "console.log(JSON.stringify({\n"
                "  bindCount: binds.length,\n"
                "  contexts: [...new Set(binds[0].map((b) => b.context))],\n"
                "  boundKeys: binds[0].map((b) => [b.keystroke, b.action]),\n"
                "  keyContext: root1.keyContext,\n"
                "  actions: Object.keys(root1.actions),\n"
                "  atAfterEnd,\n"
                "  ran: state.ran,\n"
                "  closed: state.closed,\n"
                "}));\n"
            )
            res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["bindCount"], 2)
            self.assertEqual(got["contexts"], ["ObMenu"])
            self.assertIn(["escape", "ob_menu.escape"], got["boundKeys"])
            self.assertIn(["tab", "ob_menu.down"], got["boundKeys"])
            self.assertIn(["shift-tab", "ob_menu.up"], got["boundKeys"])
            self.assertEqual(got["keyContext"], "ObMenu")
            for act in ("ob_menu.escape", "ob_menu.down", "ob_menu.up", "ob_menu.home", "ob_menu.end", "ob_menu.enter"):
                self.assertIn(act, got["actions"])
            self.assertEqual(got["atAfterEnd"], 1)
            self.assertEqual(got["ran"], [["cmd.two", {}]])
            self.assertEqual(got["closed"], ["menu-ov", "menu-ov"])


if __name__ == "__main__":
    unittest.main()
