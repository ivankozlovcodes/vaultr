"""mods/ob-settings: a menu opened from a control in the dialog (the Hotkeys "Keys for" picker) opens directly under
that control, not at the pointer or at the dialog's opener. The placement is decided by mods/ob-settings/menu_anchor.js,
a pure function run here through node. hotkeys.js must hand that position to openMenu."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest

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
                       "Move to Vaultr layout", "scopeInfo("):
            self.assertIn(needle, src)
