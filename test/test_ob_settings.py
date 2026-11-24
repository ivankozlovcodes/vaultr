"""mods/ob-settings: a menu opened from a control in the dialog (the Hotkeys "Keys for" picker) opens directly under
that control, not at the pointer or at the dialog's opener. The placement is decided by mods/ob-settings/menu_anchor.js,
a pure function run here through node. hotkeys.js must hand that position to openMenu."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
ANCHOR = os.path.join(ROOT, "mods", "ob-settings", "menu_anchor.js")
HOTKEYS = os.path.join(ROOT, "mods", "ob-settings", "hotkeys.js")


def run_node(code, payload):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def anchor(bounds, gap=None):
    code = (f"import {{ menuAnchor }} from {json.dumps(ANCHOR)};"
            "let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{"
            "const b=JSON.parse(s);const a=menuAnchor(b.bounds,b.gap);"
            "process.stdout.write(JSON.stringify(a));});")
    payload = {"bounds": bounds} if gap is None else {"bounds": bounds, "gap": gap}
    return run_node(code, payload)


class MenuAnchor(unittest.TestCase):
    def test_opens_under_the_control_left_edges_aligned(self):
        # The "Vaultr layout" button: x 700, y 240, 160 wide, 28 tall. The menu's top-left is just below it.
        self.assertEqual(anchor({"x": 700, "y": 240, "width": 160, "height": 28}), {"x": 700, "y": 272})

    def test_uses_the_control_position_not_a_fixed_point(self):
        self.assertEqual(anchor({"x": 40, "y": 90, "width": 96, "height": 24}), {"x": 40, "y": 118})

    def test_gap_is_added_below_the_control(self):
        self.assertEqual(anchor({"x": 10, "y": 20, "width": 50, "height": 20}, gap=0), {"x": 10, "y": 40})


class HotkeysPicker(unittest.TestCase):
    def test_scope_menu_is_anchored_to_its_button(self):
        # The scope button records its own bounds on press and opens the menu at them, not at the pointer.
        with open(HOTKEYS, encoding="utf-8") as f:
            src = f.read()
        start = src.index('id("hk-scope")')
        block = src[start:src.index("child(icon(\"layers\"", start)]
        self.assertIn("on_mouse_down", block)
        self.assertIn("menuAnchor", block)
        call = next(line for line in src.splitlines() if "openMenu(scopes" in line)
        self.assertIn("at:", call)


RULES = os.path.join(ROOT, "mods", "ob-settings", "vault_rules.js")


def rules(fn, *args):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f"import * as m from {json.dumps(RULES)};"
            "let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{"
            "const a=JSON.parse(s);const r=m[a.fn](...a.args);process.stdout.write(JSON.stringify(r===undefined?null:r));});")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps({"fn": fn, "args": list(args)}),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


class VaultRules(unittest.TestCase):
    def test_vault_must_be_a_full_path(self):
        self.assertIn("error", rules("parseVault", "Notes"))
        self.assertEqual(rules("parseVault", "~/Notes"), {"value": "~/Notes"})

    def test_empty_field_removes_the_key(self):
        self.assertEqual(rules("parseVault", "   "), {"value": None})

    def test_the_rules_module_has_only_the_vault_field(self):
        # The one-field tab: no parser for the daily note keys or the editor command, and no editor splitting.
        with open(RULES, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("parseValue", src)
        self.assertNotIn("split(", src)
        self.assertNotIn("editor", src.lower())

    def test_merge_keeps_other_keys_and_removes_on_null(self):
        own = {"vault": "/a", "dailyFolder": "J"}
        self.assertEqual(rules("mergeOwn", own, "vault", "/b"), {"vault": "/b", "dailyFolder": "J"})
        self.assertEqual(rules("mergeOwn", own, "vault", None), {"dailyFolder": "J"})
        self.assertEqual(own, {"vault": "/a", "dailyFolder": "J"})  # the input is not modified

    def test_a_vault_folder_must_exist(self):
        self.assertIn("No folder", rules("vaultProblem", "/nope", False))
        self.assertIsNone(rules("vaultProblem", "/yes", True))

    def test_unset_field_says_the_notes_are_off(self):
        with open(os.path.join(ROOT, "mods", "ob-settings", "vault.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Not set: the Notes panel and daily notes are off until you set it.", src)
        self.assertNotIn("Not set. In effect", src)
        self.assertNotIn("registeredVault", src)
        self.assertNotIn("fallback", src)  # no vault is used when the field is unset

    def test_placeholder_is_marked_as_an_example(self):
        with open(os.path.join(ROOT, "mods", "ob-settings", "vault.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"e.g. ~/Notes"', src)
        self.assertNotIn('"~/Notes"', src)

    def test_vault_tab_builds_only_the_vault_field(self):
        with open(os.path.join(ROOT, "mods", "ob-settings", "vault.js"), encoding="utf-8") as f:
            src = f.read()
        for gone in ("dailyFolder", "dailyFormat", "dailyTemplate", 'key: "editor"', "parseValue"):
            self.assertNotIn(gone, src)
        self.assertIn('KEY = "vault"', src)
        self.assertIn("set your vault folder once", src.lower())
        self.assertIn("$VISUAL", src)


KEYSFILE = os.path.join(ROOT, "mods", "ob-settings", "keysfile.js")

# The shapes of a live keys.json (copied from its layout), with no personal content: a stray "ctrl-*" key under
# mod:obsidian for ob-tabs.tab-list, the Vaultr layout's ctrl-p for mod.open:ob-switcher, and the same command in
# two sections.
LIVE_SHAPES = """{
  "global": { "ctrl-pageup": "tab.prev", "ctrl-shift-p": "app.palette" },
  "mod:obsidian": { "ctrl-j": "obsidian.next", "ctrl-*": "ob-tabs.tab-list" },
  "layout:vaultr": {
    "ctrl-p": "mod.open:ob-switcher",
    "ctrl-shift-p": "app.palette",
    "ctrl-alt-t": "ob-tabs.tab-list"
  }
}
"""


def keysfile_js(body, arg):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f"import * as m from {json.dumps(KEYSFILE)};"
            "const A = JSON.parse(process.env.A);"
            f"const r = (() => {{ {body} }})();"
            "process.stdout.write(JSON.stringify(r === undefined ? null : r));")
    res = subprocess.run([node, "--input-type=module", "-e", code], env={**os.environ, "A": json.dumps(arg)},
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def sections_of(text):
    # What the Hotkeys tab reads: name -> pairs, from keysfile's parser.
    return keysfile_js("const p = m.parseKeys(A.text); const o = {}; "
                       "for (const [n, s] of Object.entries(p.sections)) o[n] = s.pairs; return o;", {"text": text})


class KeysFile(unittest.TestCase):
    def test_the_star_chord_is_one_chord_with_shift_8(self):
        # "ctrl-*" is how the file spells it: the same physical chord as ctrl-shift-8 on a US layout.
        self.assertEqual(keysfile_js("return m.canon(A.c);", {"c": "ctrl-*"}), "ctrl-shift-8")
        self.assertEqual(keysfile_js("return m.canon(A.c);", {"c": "ctrl-shift-8"}), "ctrl-shift-8")

    def test_quick_switcher_is_bound_only_in_the_vaultr_layout(self):
        # All layouts shows no key for it, because ctrl-p lives in the Vaultr layout's section.
        secs = sections_of(LIVE_SHAPES)
        self.assertEqual(keysfile_js("return m.boundElsewhere(A.s, 'mod.open:ob-switcher', 'global');", {"s": secs}),
                         [{"section": "layout:vaultr", "chord": "ctrl-p"}])
        self.assertEqual(keysfile_js("return m.boundElsewhere(A.s, 'mod.open:ob-switcher', 'layout:vaultr');", {"s": secs}),
                         [])

    def test_a_stray_star_key_is_listed_under_its_own_command(self):
        # The "Ctrl + *" chip belongs to ob-tabs.tab-list under mod:obsidian, and must show there and nowhere else.
        secs = sections_of(LIVE_SHAPES)
        self.assertEqual(keysfile_js("return m.boundElsewhere(A.s, 'ob-tabs.tab-list', 'layout:vaultr');", {"s": secs}),
                         [{"section": "mod:obsidian", "chord": "ctrl-*"}])
        self.assertEqual(keysfile_js("return m.boundElsewhere(A.s, 'mod.open:ob-switcher', 'mod:obsidian');", {"s": secs}),
                         [{"section": "layout:vaultr", "chord": "ctrl-p"}])

    def test_add_writes_the_key_into_the_scope_section_as_written_by_herdr(self):
        out = keysfile_js("return m.applyEdit(A.t, 'layout:vaultr', {kind: 'bind', chord: 'ctrl-alt-j', action: 'mod.open:ob-switcher'});",
                          {"t": LIVE_SHAPES})
        expected = LIVE_SHAPES.replace('"ctrl-p": "mod.open:ob-switcher",\n',
                                       '"ctrl-p": "mod.open:ob-switcher",\n    "ctrl-alt-j": "mod.open:ob-switcher",\n')
        self.assertEqual(out["text"], expected)
        self.assertTrue(out["changed"])

    def test_remove_then_add_again_round_trips_the_text(self):
        removed = keysfile_js("return m.applyEdit(A.t, 'mod:obsidian', {kind: 'unbind', chord: 'ctrl-*', action: 'ob-tabs.tab-list'});",
                              {"t": LIVE_SHAPES})
        self.assertTrue(removed["changed"])
        self.assertNotIn("ctrl-*", removed["text"])
        self.assertEqual(json.loads(removed["text"])["mod:obsidian"], {"ctrl-j": "obsidian.next"})
        self.assertEqual(json.loads(removed["text"])["layout:vaultr"], json.loads(LIVE_SHAPES)["layout:vaultr"])
        back = keysfile_js("return m.applyEdit(A.t, 'mod:obsidian', {kind: 'bind', chord: 'ctrl-*', action: 'ob-tabs.tab-list'});",
                           {"t": removed["text"]})
        self.assertEqual(back["text"], LIVE_SHAPES)




PANEL_WARNING = {"text": "This key will only work while the Notes panel has focus. Add it to Vaultr layout instead?",
                 "to": "layout:vaultr", "button": "Add to Vaultr layout"}
ZEN_IN_PANEL = """{
  "global": { "ctrl-pageup": "tab.prev" },
  "mod:obsidian": { "ctrl-j": "obsidian.next", "ctrl-alt-z": "ob-tabs.zen" },
  "layout:vaultr": {
    "ctrl-p": "mod.open:ob-switcher"
  }
}
"""


class ScopePicker(unittest.TestCase):
    def test_default_scope_is_the_vaultr_layout_and_is_not_remembered(self):
        self.assertEqual(keysfile_js("return m.DEFAULT_SCOPE;", {}), "layout:vaultr")
        with open(HOTKEYS, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("this.scope = DEFAULT_SCOPE", src)
        self.assertNotIn('ls("scope"', src)
        self.assertNotIn('lsSet("scope"', src)

    def test_every_scope_says_in_plain_words_when_its_keys_work(self):
        cases = {
            "global": "All layouts — everywhere unless a layout overrides",
            "layout:vaultr": "Vaultr layout — anywhere in this layout",
            "layout:quiet": "Layout quiet — anywhere in this layout",
            "terminal": "In terminals — only while a terminal has focus",
            "mod:obsidian": "Notes panel (mod:obsidian) — only while that panel has focus",
            "mod:ob-sessions": "Sessions panel (mod:ob-sessions) — only while that panel has focus",
        }
        for scope, line in cases.items():
            self.assertEqual(keysfile_js("return m.scopeInfo(A.s).line;", {"s": scope}), line, scope)
        self.assertIn("weird", keysfile_js("return m.scopeInfo(A.s).line;", {"s": "weird"}))

    def test_the_header_and_picker_use_the_description(self):
        with open(HOTKEYS, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("scopeInfo(", src)


class PanelScopes(unittest.TestCase):
    def test_a_foreign_command_in_a_panel_scope_warns_with_the_layout_button(self):
        for action in ["ob-tabs.zen", "terminal.copy", "app.palette", "mod.open:ob-switcher"]:
            out = keysfile_js("return m.scopeWarning(A.s, A.a);", {"s": "mod:obsidian", "a": action})
            self.assertEqual(out, PANEL_WARNING, action)

    def test_no_warning_for_the_panels_own_command_or_outside_a_panel(self):
        self.assertIsNone(keysfile_js("return m.scopeWarning(A.s, A.a);", {"s": "mod:obsidian", "a": "obsidian.next"}))
        self.assertIsNone(keysfile_js("return m.scopeWarning(A.s, A.a);", {"s": "mod:ob-sessions", "a": "ob-sessions.rename"}))
        self.assertIsNone(keysfile_js("return m.scopeWarning(A.s, A.a);", {"s": "layout:vaultr", "a": "ob-tabs.zen"}))
        self.assertIsNone(keysfile_js("return m.scopeWarning(A.s, A.a);", {"s": "global", "a": "ob-tabs.zen"}))

    def test_a_panel_lists_only_its_own_commands_unless_it_already_has_a_key_or_all_is_shown(self):
        def listed(scope, action, has_key, show_all):
            return keysfile_js("return m.listedIn(A.s, A.a, A.h, A.w);",
                               {"s": scope, "a": action, "h": has_key, "w": show_all})
        self.assertFalse(listed("mod:obsidian", "ob-tabs.zen", False, False))
        self.assertTrue(listed("mod:obsidian", "ob-tabs.zen", True, False))
        self.assertTrue(listed("mod:obsidian", "obsidian.next", False, False))
        self.assertTrue(listed("mod:obsidian", "ob-tabs.zen", False, True))
        self.assertTrue(listed("layout:vaultr", "ob-tabs.zen", False, False))

    def test_a_panel_only_key_is_tagged_unless_it_is_the_panels_own(self):
        def tag(section, action):
            return keysfile_js("return m.panelOnlyTag(A.s, A.a);", {"s": section, "a": action})
        self.assertEqual(tag("mod:obsidian", "ob-tabs.zen"), {"text": "only in Notes panel", "from": "mod:obsidian"})
        self.assertIsNone(tag("mod:obsidian", "obsidian.next"))
        self.assertIsNone(tag("global", "ob-tabs.zen"))
        self.assertIsNone(tag("terminal", "ob-tabs.zen"))

    def test_move_to_layout_writes_the_layout_section_and_removes_it_from_the_panel(self):
        expected = """{
  "global": { "ctrl-pageup": "tab.prev" },
  "mod:obsidian": { "ctrl-j": "obsidian.next" },
  "layout:vaultr": {
    "ctrl-p": "mod.open:ob-switcher",
    "ctrl-alt-z": "ob-tabs.zen"
  }
}
"""
        out = keysfile_js("return m.moveKey(A.t, 'mod:obsidian', 'layout:vaultr', 'ctrl-alt-z', 'ob-tabs.zen');",
                          {"t": ZEN_IN_PANEL})
        self.assertEqual(out["text"], expected)
        self.assertTrue(out["changed"])

    def test_move_and_move_back_keeps_every_other_key(self):
        moved = keysfile_js("return m.moveKey(A.t, 'mod:obsidian', 'layout:vaultr', 'ctrl-*', 'ob-tabs.tab-list');",
                            {"t": LIVE_SHAPES})
        before, after = json.loads(LIVE_SHAPES), json.loads(moved["text"])
        self.assertEqual(after["mod:obsidian"], {"ctrl-j": "obsidian.next"})
        self.assertEqual(after["layout:vaultr"]["ctrl-*"], "ob-tabs.tab-list")
        self.assertEqual(after["global"], before["global"])
        self.assertEqual({k: v for k, v in after["layout:vaultr"].items() if k != "ctrl-*"}, before["layout:vaultr"])
        back = keysfile_js("return m.moveKey(A.t, 'layout:vaultr', 'mod:obsidian', 'ctrl-*', 'ob-tabs.tab-list');",
                           {"t": moved["text"]})
        self.assertEqual(json.loads(back["text"]), before)

    def test_move_stops_when_the_layout_already_holds_the_chord_for_another_command(self):
        text = ('{\n  "mod:obsidian": { "ctrl-alt-t": "ob-tabs.zen" },\n'
                '  "layout:vaultr": { "ctrl-alt-t": "ob-tabs.tab-list" }\n}\n')
        out = keysfile_js("return m.moveKey(A.t, 'mod:obsidian', 'layout:vaultr', 'ctrl-alt-t', 'ob-tabs.zen');", {"t": text})
        self.assertEqual(out["conflict"], ["ob-tabs.tab-list"])
        self.assertFalse(out["changed"])
        self.assertEqual(out["text"], text)


class PanelScopeWiring(unittest.TestCase):
    def test_hotkeys_uses_the_pure_rules_for_the_warning_tag_and_moves(self):
        with open(HOTKEYS, encoding="utf-8") as f:
            src = f.read()
        for needle in ("scopeWarning(", "panelOnlyTag(", "listedIn(", "moveKey(", "Add to Vaultr layout",
                       "Move to Vaultr layout", "scopeInfo(", "captureKeystroke(", "missingArg"):
            self.assertIn(needle, src)


REGISTRY_RULES = os.path.join(ROOT, "mods", "ob-settings", "registry_rules.js")
SAMPLE_CMDS = [
    {"name": "tab.new", "args": [{"name": "name", "required": False}]},
    {"name": "tab.select", "args": [{"name": "index", "required": False}, {"name": "id", "required": False}]},
    {"name": "space.select", "args": [{"name": "index", "required": False}, {"name": "id", "required": False}]},
    {"name": "space.move", "args": [{"name": "id", "required": True}, {"name": "index", "required": True}]},
    {"name": "pane.split", "args": [{"name": "direction", "required": True}]},
    {"name": "pane.go", "args": [{"name": "direction", "required": True}]},
    {"name": "pane.swap", "args": [{"name": "direction", "required": False}]},
    {"name": "layout.switch", "args": [{"name": "name", "required": False}]},
    {"name": "layout.clone", "args": [{"name": "name", "required": True}, {"name": "as", "required": False}]},
    {"name": "mod.clone", "args": [{"name": "name", "required": True}, {"name": "as", "required": False}]},
    {"name": "mod.open", "args": [{"name": "name", "required": True}]},
    {"name": "app.theme", "args": [{"name": "name", "required": True}]},
]


def registry_js(body, arg):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    if not os.path.exists(REGISTRY_RULES):
        raise AssertionError(f"missing {REGISTRY_RULES}")
    code = (f"import * as m from {json.dumps(REGISTRY_RULES)};"
            "const A = JSON.parse(process.env.A);"
            f"const r = (() => {{ {body} }})();"
            "process.stdout.write(JSON.stringify(r === undefined ? null : r));")
    res = subprocess.run([node, "--input-type=module", "-e", code], env={**os.environ, "A": json.dumps(arg)},
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


class RegistryActions(unittest.TestCase):
    def test_named_actions_drop_bare_required_arg_commands_and_include_select_numbers(self):
        rows = registry_js("return m.buildRegistry({ commands: A.cmds, keys: [], platform: 'macos' });",
                           {"cmds": SAMPLE_CMDS})
        by_action = {r["action"]: r for r in rows}
        self.assertIn("layout.clone:vaultr", by_action)
        self.assertEqual(by_action["layout.clone:vaultr"]["title"], "Duplicate Vaultr layout")
        self.assertNotIn("layout.clone", by_action)
        self.assertNotIn("mod.clone", by_action)
        for n in range(1, 10):
            self.assertEqual(by_action[f"tab.select:{n}"]["title"], f"Go to tab {n}")
            self.assertEqual(by_action[f"space.select:{n}"]["title"], f"Go to space {n}")
        self.assertEqual([r["action"] for r in rows if r.get("missingArg")], [])

    def test_existing_broken_bare_binding_is_flagged_with_missing_arg_so_user_can_remove_it(self):
        keys = [
            {"section": "layout:vaultr", "keys": "cmd-shift-x", "action": "pane.split"},
            {"section": "global", "keys": "ctrl-shift-m", "action": '{"command":"space.move","args":{"id":"s1"}}'},
            {"section": "layout:vaultr", "keys": "cmd-\\", "action": "pane.split:right"},
            {"section": "global", "keys": "ctrl-alt-r", "action": '{"command":"pane.split","args":{"direction":"right"}}'},
        ]
        rows = registry_js("return m.buildRegistry({ commands: A.cmds, keys: A.keys, platform: 'macos' });",
                           {"cmds": SAMPLE_CMDS, "keys": keys})
        by_action = {r["action"]: r for r in rows}
        self.assertEqual(by_action["pane.split"]["missingArg"], "direction")
        self.assertEqual(by_action['{"command":"space.move","args":{"id":"s1"}}']["missingArg"], "index")
        self.assertIsNone(by_action['{"command":"pane.split","args":{"direction":"right"}}'].get("missingArg"))
        self.assertIsNone(by_action["pane.split:right"].get("missingArg"))


class MacChordCapture(unittest.TestCase):
    def test_writeForm_normalizes_uppercase_and_redundant_shift_on_shifted_symbols(self):
        self.assertEqual(keysfile_js("return m.writeForm('cmd-P');", {}), "cmd-shift-p")
        self.assertEqual(keysfile_js("return m.writeForm('cmd-shift-|');", {}), "cmd-|")
        self.assertEqual(keysfile_js("return m.writeForm('cmd-|');", {}), "cmd-|")
        self.assertEqual(keysfile_js("return m.writeForm('cmd-shift-\\\\');", {}), "cmd-shift-\\")
        self.assertEqual(keysfile_js("return m.writeForm('cmd-backspace');", {}), "cmd-backspace")
        self.assertEqual(keysfile_js("return m.canon('cmd-P');", {}), "cmd-shift-p")
        self.assertEqual(keysfile_js("return m.canon('cmd-|');", {}), "cmd-shift-\\")

    def test_captureKeystroke_keeps_cmd_and_fn_backspace_and_escape(self):
        cases = [
            ({"key": "backspace", "modifiers": {"platform": True}, "keystroke": "cmd-backspace"}, "cmd-backspace"),
            ({"key": "escape", "modifiers": {"platform": True}, "keystroke": "cmd-escape"}, "cmd-escape"),
            ({"key": "backspace", "modifiers": {"function": True}, "keystroke": "fn-backspace"}, "fn-backspace"),
            ({"key": "backspace", "modifiers": {}, "keystroke": "backspace"}, "backspace"),
            ({"key": "escape", "modifiers": {}, "keystroke": "escape"}, "escape"),
            ({"key": "|", "modifiers": {"platform": True}, "keystroke": "cmd-|"}, "cmd-|"),
        ]
        for event, want in cases:
            self.assertEqual(keysfile_js("return m.captureKeystroke(A.e);", {"e": event}), want)


class HotkeysCaching(unittest.TestCase):
    def test_effectivePairs_memoizes_by_array_identity_avoiding_repeat_scans(self):
        out = keysfile_js("""
            const base = Array.from({ length: 200 }, (_, i) => ({
              key: i % 50 === 0 ? "ctrl-dup" : `ctrl-${i}`,
              action: `act.${i}`,
            }));
            let reads = 0;
            const proxied = new Proxy(base, {
              get(target, prop, receiver) {
                if (typeof prop === "string" && /^\\d+$/.test(prop)) reads++;
                return Reflect.get(target, prop, receiver);
              },
            });
            const first = m.effectivePairs(proxied);
            let sameRef = true;
            for (let r = 0; r < 149; r++) {
              const next = m.effectivePairs(proxied);
              if (!Object.is(first, next)) sameRef = false;
            }
            const fresh = m.effectivePairs([...base]);
            return {
              reads,
              sameRef,
              freshIsNew: !Object.is(first, fresh),
              firstLen: first.length,
              lastDupAction: first.find((p) => p.key === "ctrl-dup")?.action,
              emptySame: Object.is(m.effectivePairs([]), m.effectivePairs([])),
            };
        """, {})
        # 150 row checks on a 200-pair section would read >= 30,000 elements uncached; WeakMap reads once.
        self.assertEqual(out["reads"], 200)
        self.assertTrue(out["sameRef"])
        self.assertTrue(out["freshIsNew"])
        self.assertEqual(out["firstLen"], 197)
        self.assertEqual(out["lastDupAction"], "act.150")
        self.assertTrue(out["emptySame"])

    def test_canon_cache_correctness_eviction_and_speed(self):
        out = keysfile_js("""
            const samples = ["cmd-P", "cmd-|", "ctrl-alt-shift-k", "ctrl-k ctrl-s", "cmd-backspace"];
            const cold = samples.map((s) => m.canon(s));
            const warm = samples.map((s) => m.canon(s));
            for (let i = 0; i < 2100; i++) m.canon(`ctrl-alt-k${i}`);
            const afterEvict = samples.map((s) => m.canon(s));
            const t0 = performance.now();
            for (let r = 0; r < 4000; r++) {
              for (const s of samples) m.canon(s);
            }
            const cachedMs = performance.now() - t0;
            return { cold, warm, afterEvict, cachedMs };
        """, {})
        want = ["cmd-shift-p", "cmd-shift-\\", "ctrl-alt-shift-k", "ctrl-k ctrl-s", "cmd-backspace"]
        self.assertEqual(out["cold"], want)
        self.assertEqual(out["warm"], want)
        self.assertEqual(out["afterEvict"], want)
        self.assertLess(out["cachedMs"], 200)

    def test_hotkeys_uses_effectiveOf_memo_and_avoids_version_numbers(self):
        with open(HOTKEYS, encoding="utf-8") as f:
            hk_src = f.read()
        with open(KEYSFILE, encoding="utf-8") as f:
            kf_src = f.read()
        self.assertIn("effectiveOf(", hk_src)
        self.assertIn("const EFFECTIVE = new WeakMap();", hk_src)
        for src in (hk_src, kf_src):
            self.assertNotRegex(src, r"0\.1\.1[0-9]\b")


class SettingsOverlayKeys(unittest.TestCase):
    """ObSettings binds Escape under ObSettings key_context and cancels Hotkeys capture/pending before closing."""

    def test_ob_settings_escape_precedence_and_keys_reload_rebind(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node is not installed")
        with tempfile.TemporaryDirectory(prefix="ob-settings-keys-") as folder:
            shutil.copy(os.path.join(ROOT, "mods", "ob-settings", "main.js"), os.path.join(folder, "main.js"))
            src = Path(folder, "main.js").read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            Path(folder, "main.js").write_text(src, encoding="utf-8")
            el_stub = (
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
            Path(folder, "gpui-kit.js").write_text(
                el_stub + "export class View {}\nexport const div = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "gpui-base.js").write_text(
                el_stub + "export const h_flex = () => proxyEl();\nexport const v_flex = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "herdr.js").write_text(
                "export const state = { keys: [{ section: 'global', keys: 'a', action: 'b' }], closed: [], shared: {} };\n"
                "export const props = () => ({ overlay: 'st-ov' });\n"
                "export const closeOverlay = (ov) => state.closed.push(ov);\n"
                "export const nextCommand = () => new Promise(() => {});\n"
                "export const run = () => {};\n"
                "export const shared = (k) => state.shared[k];\n"
                "export const setShared = (k, v) => { state.shared[k] = v; };\n"
                "export const keys = () => state.keys;\n",
                encoding="utf-8",
            )
            Path(folder, "kit.js").write_text(
                el_stub
                + "export const S = { text: 13, textSm: 12, textLg: 15, iconSm: 14, radiusLg: 6 };\n"
                + "export const tc = () => ({});\n"
                + "export const icon = () => proxyEl();\n"
                + "export const iconButton = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "vault.js").write_text(
                el_stub + "export const render = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "feedback.js").write_text(
                el_stub + "export const render = () => proxyEl();\n",
                encoding="utf-8",
            )
            Path(folder, "hotkeys.js").write_text(
                el_stub
                + "export const presses = [];\n"
                + "export function init(host) {\n"
                + "  host.state.hotkeys = {\n"
                + "    capture: 'pane.split:right',\n"
                + "    pending: { action: 'a', chord: 'b', others: ['c'] },\n"
                + "    press(ch) { presses.push(ch); this.capture = null; },\n"
                + "  };\n"
                + "}\n"
                + "export const render = () => proxyEl();\n",
                encoding="utf-8",
            )
            code = (
                f'import Settings from "{Path(folder, "main.js").as_uri()}";\n'
                f'import {{ state }} from "{Path(folder, "herdr.js").as_uri()}";\n'
                f'import {{ presses }} from "{Path(folder, "hotkeys.js").as_uri()}";\n'
                "const binds = [];\n"
                "const timers = [];\n"
                "let notifies = 0;\n"
                "const cx = {\n"
                "  focus_handle: () => ({ focus() {} }),\n"
                "  bind_keys: (list) => binds.push(list),\n"
                "  timer: { after: (_ms, fn) => timers.push(fn), every: () => ({ cancel() {} }) },\n"
                "  spawn: () => {},\n"
                "  notify: () => { notifies++; },\n"
                "};\n"
                "const s = new Settings();\n"
                "s.init({}, cx);\n"
                "s.tabId = 'hotkeys';\n"
                "const root = s.render(cx).__rec;\n"
                "root.actions['ob_settings.escape'](null, cx);\n"
                "const closedAfterCapture = state.closed.length;\n"
                "const pendingAfterCapture = Boolean(s.state.hotkeys.pending);\n"
                "root.actions['ob_settings.escape'](null, cx);\n"
                "const closedAfterPending = state.closed.length;\n"
                "const pendingAfterSecond = s.state.hotkeys.pending;\n"
                "root.actions['ob_settings.escape'](null, cx);\n"
                "state.keys = [{ section: 'global', keys: 'c', action: 'd' }];\n"
                "s.render(cx);\n"
                "for (const fn of timers.splice(0)) fn(cx);\n"
                "console.log(JSON.stringify({\n"
                "  bindCount: binds.length,\n"
                "  firstBind: binds[0],\n"
                "  keyContext: root.keyContext,\n"
                "  presses,\n"
                "  closedAfterCapture,\n"
                "  pendingAfterCapture,\n"
                "  closedAfterPending,\n"
                "  pendingAfterSecond,\n"
                "  closedFinal: state.closed,\n"
                "  notifies,\n"
                "}));\n"
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["bindCount"], 2)  # initial bind in init() + rebind after keys() changed
            self.assertEqual(got["firstBind"], [{"keystroke": "escape", "action": "ob_settings.escape", "context": "ObSettings"}])
            self.assertEqual(got["keyContext"], "ObSettings")
            self.assertEqual(got["presses"], ["escape"])
            self.assertEqual(got["closedAfterCapture"], 0)
            self.assertTrue(got["pendingAfterCapture"])
            self.assertEqual(got["closedAfterPending"], 0)
            self.assertIsNone(got["pendingAfterSecond"])
            self.assertEqual(got["closedFinal"], ["st-ov"])
            self.assertGreaterEqual(got["notifies"], 2)


FEEDBACK_RULES = os.path.join(ROOT, "mods", "ob-settings", "feedback_rules.js")
FEEDBACK_TAB = os.path.join(ROOT, "mods", "ob-settings", "feedback.js")
SETTINGS_MAIN = os.path.join(ROOT, "mods", "ob-settings", "main.js")


def fb_rules(fn, *args):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f"import * as m from {json.dumps(FEEDBACK_RULES)};"
            "let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{"
            "const a=JSON.parse(s);const r=m[a.fn](...a.args);process.stdout.write(JSON.stringify(r===undefined?null:r));});")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps({"fn": fn, "args": list(args)}),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


class FeedbackRules(unittest.TestCase):
    def test_expand_feedback_path_handles_tilde_unix_windows_and_relative(self):
        self.assertIsNone(fb_rules("expandFeedbackPath", "", "/srv/u"))
        self.assertIsNone(fb_rules("expandFeedbackPath", "   ", "/srv/u"))
        self.assertIsNone(fb_rules("expandFeedbackPath", "relative/dir", "/srv/u"))
        self.assertIsNone(fb_rules("expandFeedbackPath", "./local", "/srv/u"))
        self.assertEqual(fb_rules("expandFeedbackPath", "~", "/srv/u"), "/srv/u")
        self.assertEqual(fb_rules("expandFeedbackPath", "~/", "/srv/u"), "/srv/u")
        self.assertEqual(fb_rules("expandFeedbackPath", "~/Feedback/vaultr/", "/srv/u"), "/srv/u/Feedback/vaultr")
        self.assertEqual(fb_rules("expandFeedbackPath", "/", "/srv/u"), "/")
        self.assertEqual(fb_rules("expandFeedbackPath", "/var/tmp/fb///", "/srv/u"), "/var/tmp/fb")
        self.assertEqual(fb_rules("expandFeedbackPath", "C:\\", "/srv/u"), "C:\\")
        self.assertEqual(fb_rules("expandFeedbackPath", "C:\\Feedback\\vaultr\\\\", "/srv/u"), "C:\\Feedback\\vaultr")
        self.assertEqual(fb_rules("expandFeedbackPath", "\\\\server\\share\\", "/srv/u"), "\\\\server\\share")

    def test_parse_feedback_folder_accepts_full_or_empty_and_rejects_relative(self):
        self.assertEqual(fb_rules("parseFeedbackFolder", "   "), {"value": None})
        self.assertEqual(fb_rules("parseFeedbackFolder", "~/Feedback/vaultr"), {"value": "~/Feedback/vaultr"})
        self.assertEqual(fb_rules("parseFeedbackFolder", "/var/tmp/feedback"), {"value": "/var/tmp/feedback"})
        err = fb_rules("parseFeedbackFolder", "feedback/rel")
        self.assertIn("error", err)
        self.assertIn("full path", err["error"])

    def test_merge_feedback_own_preserves_other_keys_and_deletes_on_null(self):
        own = {"folder": "~/Feedback/vaultr", "other": 42}
        self.assertEqual(fb_rules("mergeFeedbackOwn", own, "/tmp/fb"), {"folder": "/tmp/fb", "other": 42})
        self.assertEqual(fb_rules("mergeFeedbackOwn", own, None), {"other": 42})
        self.assertEqual(fb_rules("mergeFeedbackOwn", "bad", "/tmp/fb"), {"folder": "/tmp/fb"})
        self.assertEqual(own, {"folder": "~/Feedback/vaultr", "other": 42})


class FeedbackTabWiring(unittest.TestCase):
    def test_feedback_tab_uses_portable_fs_and_feedback_json(self):
        src = Path(FEEDBACK_TAB).read_text(encoding="utf-8")
        for needle in ("feedback.json", "pickFolder(", "ensureDir(", "fs.unlink(", "writeTextFile(", "checking()"):
            self.assertIn(needle, src)
        for forbidden in ("fs.mkdir", "fs.writeFile", "fs.readdir", "fs.readFile", "fs.stat", "fs.access", "fs.copyFile", "fs.rm", "fs.exists"):
            self.assertNotIn(forbidden, src)

    def test_settings_tabs_place_feedback_between_vault_and_hotkeys(self):
        src = Path(SETTINGS_MAIN).read_text(encoding="utf-8")
        self.assertIn('import * as feedback from "./feedback.js";', src)
        vault_at = src.index('id: "vault"')
        fb_at = src.index('id: "feedback"')
        hk_at = src.index('id: "hotkeys"')
        self.assertLess(vault_at, fb_at)
        self.assertLess(fb_at, hk_at)
        self.assertIn('icon: "square-pen"', src)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_feedback_tab_browse_save_and_clear_lifecycle(self):
        node = shutil.which("node")
        with tempfile.TemporaryDirectory(prefix="ob-fb-tab-") as tmp:
            home_dir = Path(tmp, "userdir")
            app_dir = Path(tmp, "app")
            chosen_dir = Path(home_dir, "Feedback", "picked")
            outside_dir = Path(tmp, "outside-feedback")
            home_dir.mkdir()
            app_dir.mkdir()
            Path(app_dir, "feedback.json").write_text('{"keep": 1}\n', encoding="utf-8")
            mod_dir = Path(tmp, "mod")
            mod_dir.mkdir()
            shutil.copy(FEEDBACK_RULES, mod_dir / "feedback_rules.js")
            bundle_copy = Path(FEEDBACK_RULES).parent / "feedback_bundle.js"
            if bundle_copy.exists():
                shutil.copy(bundle_copy, mod_dir / "feedback_bundle.js")
            bundle_copy = Path(FEEDBACK_RULES).parent / "feedback_bundle.js"
            if bundle_copy.exists():
                shutil.copy(bundle_copy, mod_dir / "feedback_bundle.js")
            src = Path(FEEDBACK_TAB).read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "fs/promises"', 'from "./fs-sandbox.js"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            (mod_dir / "feedback.js").write_text(src, encoding="utf-8")
            (mod_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            # Enforce Herdr's real gpui-kit fs/promises sandbox: synchronous throws outside roots.
            (mod_dir / "fs-sandbox.js").write_text(
                'import * as nodeFs from "node:fs/promises";\n'
                'import * as nodePath from "node:path";\n'
                f"const READ_ROOTS = [{json.dumps(str(home_dir))}];\n"
                f"const WRITE_ROOTS = [{json.dumps(str(app_dir))}];\n"
                "function assertUnder(roots, p, op) {\n"
                "  const norm = nodePath.resolve(String(p));\n"
                "  for (const r of roots) {\n"
                "    const base = nodePath.resolve(String(r));\n"
                "    if (norm === base || norm.startsWith(base + nodePath.sep)) return;\n"
                "  }\n"
                "  throw new Error(`OutsideRoots (${op}): ${norm}`);\n"
                "}\n"
                "export function mkdir(p, opts) { assertUnder(WRITE_ROOTS, p, 'mkdir'); return nodeFs.mkdir(p, opts); }\n"
                "export function readFile(p, opts) { assertUnder(READ_ROOTS, p, 'readFile'); return nodeFs.readFile(p, opts); }\n"
                "export function writeFile(p, data, opts) { assertUnder(WRITE_ROOTS, p, 'writeFile'); return nodeFs.writeFile(p, data, opts); }\n"
                "export function readdir(p, opts) { assertUnder(READ_ROOTS, p, 'readdir'); return nodeFs.readdir(p, opts); }\n"
                "export function unlink(p) { assertUnder(WRITE_ROOTS, p, 'unlink'); return nodeFs.unlink(p); }\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-kit.js").write_text(
                "const el = () => new Proxy(() => el(), { get: () => el }); export const div = el;\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-base.js").write_text(
                "const el = () => new Proxy(() => el(), { get: () => el });\n"
                "export const h_flex = el, v_flex = el, Input = { new: () => el() };\n"
                "export const InputState = { new: (o = {}) => { let val = o.value || ''; const h = {}; return { on: (e, fn) => { h[e] = fn; }, value: () => val, set_value: (v) => { val = v; }, focus: () => {}, triggerSubmit: (cx) => h.submit?.({}, cx) }; } };\n",
                encoding="utf-8",
            )
            (mod_dir / "kit.js").write_text(
                "export const S = { text: 13, textSm: 12, textXs: 11, radius: 4, radiusLg: 6 };\n"
                "export const alpha = () => '#000';\n"
                f"export const tilde = (p) => p.startsWith({json.dumps(str(home_dir))} + '/') ? '~' + p.slice({len(str(home_dir))}) : p;\n",
                encoding="utf-8",
            )
            (mod_dir / "herdr.js").write_text(
                'import * as fs from "node:fs/promises";\n'
                'import * as fsSync from "node:fs";\n'
                'import * as nodePath from "node:path";\n'
                "export const execLog = [];\n"
                f"export const home = () => {json.dumps(str(home_dir))};\n"
                f"export const appHome = () => {json.dumps(str(app_dir))};\n"
                "export const checking = () => false;\n"
                "export const window = () => ({ platform: 'linux' });\n"
                f"export const pickFolder = async () => {json.dumps(str(chosen_dir))};\n"
                "export async function exec(cmd, args = []) {\n"
                "  execLog.push([cmd, args]);\n"
                "  if (cmd === 'mkdir' && args[0] === '-p' && args[1]) { fsSync.mkdirSync(args[1], { recursive: true }); return { code: 0, stdout: '', stderr: '' }; }\n"
                "  return { code: 1, stdout: '', stderr: `unexpected cmd ${cmd}` };\n"
                "}\n"
                "export const readTextFile = async (p) => { try { return await fs.readFile(p, 'utf8'); } catch (e) { if (e.code === 'ENOENT') return null; throw e; } };\n"
                "export const writeTextFile = async (p, text, expected) => { await fs.mkdir(nodePath.dirname(p), { recursive: true }); const cur = await readTextFile(p); if (cur !== expected) throw new Error('stale'); await fs.writeFile(p, text, 'utf8'); return null; };\n",
                encoding="utf-8",
            )
            code = (
                f'import * as fb from "{(mod_dir / "feedback.js").as_uri()}";\n'
                f'import {{ execLog }} from "{(mod_dir / "herdr.js").as_uri()}";\n'
                "const tasks = [];\n"
                "let notifies = 0;\n"
                "const cx = { spawn: (fn) => { const p = fn(cx); tasks.push(p); return p; }, notify: () => { notifies++; } };\n"
                "const host = { state: {} };\n"
                "fb.init(host, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "fb.command(host, 'feedback-browse', '', cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterBrowse = { val: host.state.feedback.input.value(), root: host.state.feedback.root, notice: host.state.feedback.notice };\n"
                f"host.state.feedback.input.set_value({json.dumps(str(outside_dir))});\n"
                "host.state.feedback.input.triggerSubmit(cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterOutside = { root: host.state.feedback.root, notice: host.state.feedback.notice };\n"
                "host.state.feedback.input.set_value('~/Feedback/typed');\n"
                "host.state.feedback.input.triggerSubmit(cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterSave = { root: host.state.feedback.root, notice: host.state.feedback.notice };\n"
                "fb.command(host, 'feedback-clear', '', cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "console.log(JSON.stringify({ afterBrowse, afterOutside, afterSave, noticeAfterClear: host.state.feedback.notice, notifies, execLog }));\n"
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["afterBrowse"]["val"], "~/Feedback/picked")
            self.assertEqual(got["afterBrowse"]["root"], str(chosen_dir))
            self.assertEqual(got["afterBrowse"]["notice"]["level"], "ok")
            self.assertTrue(chosen_dir.is_dir())
            self.assertEqual(got["afterOutside"]["root"], str(outside_dir))
            self.assertEqual(got["afterOutside"]["notice"]["level"], "ok")
            self.assertTrue(outside_dir.is_dir())
            self.assertEqual(got["afterSave"]["root"], str(home_dir / "Feedback" / "typed"))
            self.assertTrue((home_dir / "Feedback" / "typed").is_dir())
            self.assertEqual(got["noticeAfterClear"]["level"], "ok")
            self.assertEqual(json.loads(Path(app_dir, "feedback.json").read_text(encoding="utf-8")), {"keep": 1})
            # Also prove clearing the last key unlinks feedback.json inside app_dir cleanly under sandbox.
            Path(app_dir, "feedback.json").write_text('{"folder": "~/Feedback/typed"}\n', encoding="utf-8")
            code_unlink = (
                f'import * as fb from "{(mod_dir / "feedback.js").as_uri()}";\n'
                "const tasks = [];\n"
                "const cx = { spawn: (fn) => { const p = fn(cx); tasks.push(p); return p; }, notify: () => {} };\n"
                "const host = { state: {} };\n"
                "fb.init(host, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "fb.command(host, 'feedback-clear', '', cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "console.log(JSON.stringify(host.state.feedback.notice));\n"
            )
            res2 = subprocess.run([node, "--input-type=module", "-e", code_unlink], capture_output=True, text=True, timeout=60)
            self.assertEqual(res2.returncode, 0, res2.stderr)
            self.assertEqual(json.loads(res2.stdout)["level"], "ok")
            self.assertFalse(Path(app_dir, "feedback.json").exists())

@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FolderDrop(unittest.TestCase):
    """Dropping a folder from Finder onto the Vault or Feedback folder card populates and saves it."""

    def test_vault_tab_drop_populates_and_saves_folder_and_rejects_invalid(self):
        node = shutil.which("node")
        with tempfile.TemporaryDirectory(prefix="ob-vault-drop-") as tmp:
            home_dir = Path(tmp, "userdir")
            app_dir = Path(tmp, "app")
            in_home = Path(home_dir, "MyVault")
            outside = Path(tmp, "outside-vault")
            missing = Path(tmp, "no-such-vault")
            in_home.mkdir(parents=True)
            outside.mkdir(parents=True)
            app_dir.mkdir(parents=True)
            mod_dir = Path(tmp, "mod")
            mod_dir.mkdir()
            shutil.copy(RULES, mod_dir / "vault_rules.js")
            src = Path(ROOT, "mods", "ob-settings", "vault.js").read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "fs/promises"', 'from "node:fs/promises"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            (mod_dir / "vault.js").write_text(src, encoding="utf-8")
            (mod_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (mod_dir / "gpui-kit.js").write_text(
                "export const drops = new Map();\n"
                "export function makeEl() {\n"
                "  let id = null;\n"
                "  const p = new Proxy(() => p, {\n"
                "    get(_t, prop) {\n"
                "      if (prop === 'id') return (v) => { id = v; return p; };\n"
                "      if (prop === 'on_drop') return (fn) => { drops.set(id, fn); return p; };\n"
                "      return () => p;\n"
                "    },\n"
                "  });\n"
                "  return p;\n"
                "}\n"
                "export const div = () => makeEl();\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-base.js").write_text(
                'import { makeEl } from "./gpui-kit.js";\n'
                "export const h_flex = () => makeEl(), v_flex = () => makeEl(), Input = { new: () => makeEl() };\n"
                "export const InputState = { new: (o = {}) => { let val = o.value || ''; return { on() {}, value: () => val, set_value: (v) => { val = v; } }; } };\n",
                encoding="utf-8",
            )
            (mod_dir / "kit.js").write_text(
                "export const S = { text: 13, textSm: 12, textXs: 11, radius: 4, radiusLg: 6 };\n"
                "export const alpha = () => '#000';\n"
                f"export const tilde = (p) => p.startsWith({json.dumps(str(home_dir))} + '/') ? '~' + p.slice({len(str(home_dir))}) : p;\n",
                encoding="utf-8",
            )
            (mod_dir / "herdr.js").write_text(
                'import * as fs from "node:fs/promises";\n'
                'import * as fsSync from "node:fs";\n'
                'import * as nodePath from "node:path";\n'
                f"export const home = () => {json.dumps(str(home_dir))};\n"
                f"export const appHome = () => {json.dumps(str(app_dir))};\n"
                "export const window = () => ({ platform: 'linux' });\n"
                "export async function exec(cmd, args = []) {\n"
                "  if (cmd === 'test' && args[0] === '-d' && args[1]) return { code: fsSync.existsSync(args[1]) && fsSync.statSync(args[1]).isDirectory() ? 0 : 1, stdout: '', stderr: '' };\n"
                "  return { code: 1, stdout: '', stderr: '' };\n"
                "}\n"
                "export const readTextFile = async (p) => { try { return await fs.readFile(p, 'utf8'); } catch (e) { if (e.code === 'ENOENT') return null; throw e; } };\n"
                "export const writeTextFile = async (p, text, expected) => { await fs.mkdir(nodePath.dirname(p), { recursive: true }); const cur = await readTextFile(p); if (cur !== expected) throw new Error('stale'); await fs.writeFile(p, text, 'utf8'); return null; };\n",
                encoding="utf-8",
            )
            code = (
                f'import * as vt from "{(mod_dir / "vault.js").as_uri()}";\n'
                f'import {{ drops }} from "{(mod_dir / "gpui-kit.js").as_uri()}";\n'
                "const tasks = [];\n"
                "const cx = { spawn: (fn) => { const p = fn(cx); tasks.push(p); return p; }, notify: () => {} };\n"
                "const host = { state: {} };\n"
                "vt.init(host, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "vt.render(host, {});\n"
                "const onDrop = drops.get('vt-vault');\n"
                "if (!onDrop) throw new Error('missing on_drop on vt-vault');\n"
                f"onDrop({{ paths: [{json.dumps(str(in_home) + '/')}] }}, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterHome = { val: host.state.vault.input.value(), own: host.state.vault.own, notice: host.state.vault.notice };\n"
                f"onDrop({{ paths: [{json.dumps(str(outside))}] }}, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterOutside = { val: host.state.vault.input.value(), own: host.state.vault.own, notice: host.state.vault.notice };\n"
                f"onDrop({{ paths: [{json.dumps(str(missing))}] }}, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterMissing = { own: host.state.vault.own, notice: host.state.vault.notice };\n"
                "onDrop({ paths: ['relative/bad'] }, cx);\n"
                "const afterRel = { own: host.state.vault.own, notice: host.state.vault.notice };\n"
                "console.log(JSON.stringify({ afterHome, afterOutside, afterMissing, afterRel }));\n"
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["afterHome"]["val"], "~/MyVault")
            self.assertEqual(got["afterHome"]["own"], {"vault": "~/MyVault"})
            self.assertEqual(got["afterHome"]["notice"]["level"], "ok")
            self.assertEqual(got["afterOutside"]["val"], str(outside))
            self.assertEqual(got["afterOutside"]["own"], {"vault": str(outside)})
            self.assertEqual(got["afterMissing"]["notice"]["level"], "error")
            self.assertEqual(got["afterMissing"]["own"], {"vault": str(outside)})
            self.assertEqual(got["afterRel"]["notice"]["level"], "error")
            self.assertEqual(got["afterRel"]["own"], {"vault": str(outside)})

    def test_feedback_tab_drop_populates_and_saves_folder_and_rejects_relative(self):
        node = shutil.which("node")
        with tempfile.TemporaryDirectory(prefix="ob-fb-drop-") as tmp:
            home_dir = Path(tmp, "userdir")
            app_dir = Path(tmp, "app")
            dropped_dir = Path(home_dir, "Feedback", "dropped")
            home_dir.mkdir(parents=True)
            app_dir.mkdir(parents=True)
            Path(app_dir, "feedback.json").write_text('{"keep": true}\n', encoding="utf-8")
            mod_dir = Path(tmp, "mod")
            mod_dir.mkdir()
            shutil.copy(FEEDBACK_RULES, mod_dir / "feedback_rules.js")
            shutil.copy(Path(FEEDBACK_RULES).parent / "feedback_bundle.js", mod_dir / "feedback_bundle.js")
            src = Path(FEEDBACK_TAB).read_text(encoding="utf-8")
            src = (src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "fs/promises"', 'from "node:fs/promises"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
            (mod_dir / "feedback.js").write_text(src, encoding="utf-8")
            (mod_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            (mod_dir / "gpui-kit.js").write_text(
                "export const drops = new Map();\n"
                "export function makeEl() {\n"
                "  let id = null;\n"
                "  const p = new Proxy(() => p, {\n"
                "    get(_t, prop) {\n"
                "      if (prop === 'id') return (v) => { id = v; return p; };\n"
                "      if (prop === 'on_drop') return (fn) => { drops.set(id, fn); return p; };\n"
                "      return () => p;\n"
                "    },\n"
                "  });\n"
                "  return p;\n"
                "}\n"
                "export const div = () => makeEl();\n",
                encoding="utf-8",
            )
            (mod_dir / "gpui-base.js").write_text(
                'import { makeEl } from "./gpui-kit.js";\n'
                "export const h_flex = () => makeEl(), v_flex = () => makeEl(), Input = { new: () => makeEl() };\n"
                "export const InputState = { new: (o = {}) => { let val = o.value || ''; return { on() {}, value: () => val, set_value: (v) => { val = v; }, focus() {} }; } };\n",
                encoding="utf-8",
            )
            (mod_dir / "kit.js").write_text(
                "export const S = { text: 13, textSm: 12, textXs: 11, radius: 4, radiusLg: 6 };\n"
                "export const alpha = () => '#000';\n"
                f"export const tilde = (p) => p.startsWith({json.dumps(str(home_dir))} + '/') ? '~' + p.slice({len(str(home_dir))}) : p;\n",
                encoding="utf-8",
            )
            (mod_dir / "herdr.js").write_text(
                'import * as fs from "node:fs/promises";\n'
                'import * as fsSync from "node:fs";\n'
                'import * as nodePath from "node:path";\n'
                f"export const home = () => {json.dumps(str(home_dir))};\n"
                f"export const appHome = () => {json.dumps(str(app_dir))};\n"
                "export const checking = () => false;\n"
                "export const window = () => ({ platform: 'linux' });\n"
                "export const pickFolder = async () => null;\n"
                "export async function exec(cmd, args = []) {\n"
                "  if (cmd === 'mkdir' && args[0] === '-p' && args[1]) { fsSync.mkdirSync(args[1], { recursive: true }); return { code: 0, stdout: '', stderr: '' }; }\n"
                "  return { code: 1, stdout: '', stderr: '' };\n"
                "}\n"
                "export const readTextFile = async (p) => { try { return await fs.readFile(p, 'utf8'); } catch (e) { if (e.code === 'ENOENT') return null; throw e; } };\n"
                "export const writeTextFile = async (p, text, expected) => { await fs.mkdir(nodePath.dirname(p), { recursive: true }); const cur = await readTextFile(p); if (cur !== expected) throw new Error('stale'); await fs.writeFile(p, text, 'utf8'); return null; };\n",
                encoding="utf-8",
            )
            code = (
                f'import * as fb from "{(mod_dir / "feedback.js").as_uri()}";\n'
                f'import {{ drops }} from "{(mod_dir / "gpui-kit.js").as_uri()}";\n'
                "const tasks = [];\n"
                "const cx = { spawn: (fn) => { const p = fn(cx); tasks.push(p); return p; }, notify: () => {} };\n"
                "const host = { state: {} };\n"
                "fb.init(host, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "fb.render(host, {});\n"
                "const onDrop = drops.get('fb-folder');\n"
                "if (!onDrop) throw new Error('missing on_drop on fb-folder');\n"
                f"onDrop({{ paths: [{json.dumps(str(dropped_dir) + '/')}] }}, cx);\n"
                "await Promise.all(tasks.splice(0));\n"
                "const afterDrop = { val: host.state.feedback.input.value(), root: host.state.feedback.root, notice: host.state.feedback.notice };\n"
                "onDrop({ paths: ['rel/bad'] }, cx);\n"
                "const afterRel = { root: host.state.feedback.root, notice: host.state.feedback.notice };\n"
                "console.log(JSON.stringify({ afterDrop, afterRel }));\n"
            )
            res = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)
            self.assertEqual(got["afterDrop"]["val"], "~/Feedback/dropped")
            self.assertEqual(got["afterDrop"]["root"], str(dropped_dir))
            self.assertEqual(got["afterDrop"]["notice"]["level"], "ok")
            self.assertTrue(dropped_dir.is_dir())
            self.assertEqual(json.loads(Path(app_dir, "feedback.json").read_text(encoding="utf-8")), {"keep": True, "folder": "~/Feedback/dropped"})
            self.assertEqual(got["afterRel"]["notice"]["level"], "error")
            self.assertEqual(got["afterRel"]["root"], str(dropped_dir))
