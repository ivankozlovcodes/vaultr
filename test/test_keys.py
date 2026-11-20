"""Vaultr's keys file: the session search key is Ctrl+Shift+K (Ctrl+Shift+F stays with find-in-terminal), and the
hotkey labels name the keys that are really bound."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
with open(os.path.join(ROOT, "keys", "vaultr-keys.json"), encoding="utf-8") as f:
    KEYS = json.load(f)
with open(os.path.join(ROOT, "mods", "ob-settings", "registry.js"), encoding="utf-8") as f:
    REGISTRY = f.read()


class SessionSearchKey(unittest.TestCase):
    def test_ctrl_shift_f_is_not_bound_outside_the_terminal(self):
        for section, binds in KEYS.items():
            if section == "terminal":
                continue
            self.assertNotIn("ctrl-shift-f", binds, f"{section} binds ctrl-shift-f (terminal find)")

    def test_search_all_sessions_is_on_ctrl_shift_k(self):
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-shift-k"), "ob-tabs.open:ob-search")

    def test_ctrl_alt_f_still_opens_search(self):
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-alt-f"), "ob-tabs.open:ob-search")

    def test_hotkey_label_names_ctrl_shift_k(self):
        line = next(l for l in REGISTRY.splitlines() if '"ob-tabs.open:ob-search"' in l)
        self.assertIn('"ctrl-shift-k"', line)
        self.assertNotIn("ctrl-shift-f", line)
        self.assertNotIn("Ctrl+Shift+F", line)


class VaultrSettingsKey(unittest.TestCase):
    def test_ctrl_comma_opens_vaultr_settings_in_the_layout(self):
        # The footer gear opens ob-settings with mod.open directly: no tab bar mod in the path (Zen, hidden tab bar).
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-,"), "mod.open:ob-settings")


class CommandPaletteKey(unittest.TestCase):
    def test_ctrl_shift_p_in_the_layout_opens_the_switcher_in_command_mode(self):
        # Herdr's own palette stays one entry in this list ("Herdr command palette…" -> app.palette).
        self.assertEqual(KEYS["layout:vaultr"].get("ctrl-shift-p"), "ob-tabs.switcher:commands")

    def test_hotkey_label_names_ctrl_shift_p_on_the_command_mode(self):
        line = next(l for l in REGISTRY.splitlines() if '"ob-tabs.switcher:commands"' in l)
        self.assertIn('"ctrl-shift-p"', line)


PLATFORM_KEYS = os.path.join(ROOT, "mods", "ob-settings", "platform_keys.js")


def chords_for(platform, chords):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f"import {{ chordForPlatform }} from {json.dumps(PLATFORM_KEYS)};"
            f"const p={json.dumps(platform)};const c={json.dumps(chords)};"
            "process.stdout.write(JSON.stringify(c.map((x)=>chordForPlatform(x,p))));")
    out = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class MacKeys(unittest.TestCase):
    """keys/vaultr-keys.json is written with Ctrl. On macOS the installer and the Hotkeys tab's defaults use Cmd in
    its place, as Herdr's own macOS keys do (Cmd-F finds in a terminal)."""

    def test_ctrl_becomes_cmd_on_macos(self):
        self.assertEqual(chords_for("macos", ["ctrl-p", "ctrl-shift-p", "ctrl-alt-left", "ctrl-,", "ctrl-\\", "ctrl-|"]),
                         ["cmd-p", "cmd-shift-p", "cmd-alt-left", "cmd-,", "cmd-\\", "cmd-|"])

    def test_each_stroke_of_a_sequence_is_translated(self):
        self.assertEqual(chords_for("macos", ["ctrl-k ctrl-s"]), ["cmd-k cmd-s"])

    def test_keys_without_ctrl_are_unchanged(self):
        self.assertEqual(chords_for("macos", ["f2", "delete", "alt-shift-h", "ctrl"]), ["f2", "delete", "alt-shift-h", "ctrl"])

    def test_linux_and_windows_keep_ctrl(self):
        self.assertEqual(chords_for("linux", ["ctrl-p"]), ["ctrl-p"])
        self.assertEqual(chords_for("windows", ["ctrl-p"]), ["ctrl-p"])


def kit_keys_eval(body, platform="linux", home_dir="/var/tmp/u", key_list=()):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory(prefix="kit-keys-") as folder:
        for path in glob.glob(os.path.join(ROOT, "kit", "*.js")):
            shutil.copy(path, os.path.join(folder, os.path.basename(path)))
        kit_src = Path(folder, "kit.js").read_text(encoding="utf-8")
        kit_src = (kit_src
                   .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                   .replace('from "gpui-base"', 'from "./gpui-base.js"')
                   .replace('from "herdr"', 'from "./herdr.js"'))
        Path(folder, "kit.js").write_text(kit_src, encoding="utf-8")
        Path(folder, "gpui-kit.js").write_text("export const div = () => null; export const svg = () => null; export const image = () => null;\n", encoding="utf-8")
        Path(folder, "gpui-base.js").write_text("export const h_flex = () => null; export const v_flex = () => null;\n", encoding="utf-8")
        herdr_fns = ["theme", "run", "openOverlay", "closeOverlay", "layout", "shared", "setShared", "spaces", "agents", "terminals", "panes", "focused"]
        Path(folder, "herdr.js").write_text(
            "".join(f"export const {n} = () => [];\n" for n in herdr_fns)
            + f"export const keys = () => {json.dumps(list(key_list))};\n"
            + f"export const home = () => {json.dumps(home_dir)};\n"
            + 'export const appHome = () => "/tmp/herdr-app";\n'
            + "export const readTextFile = async () => null;\n"
            + f"export const window = () => ({json.dumps({'platform': platform}) if platform else 'null'});\n",
            encoding="utf-8",
        )
        code = (f'import * as K from "{Path(folder, "kit.js").as_uri()}";\n'
                f'process.stdout.write(JSON.stringify((() => {{ {body} }})()));')
        out = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        return json.loads(out.stdout)


class KitPlatformBinding(unittest.TestCase):
    BOTH = [
        {"section": "layout:vaultr", "keys": "ctrl-b", "action": "layout.toggle:ob-left"},
        {"section": "layout:vaultr", "keys": "cmd-b", "action": "layout.toggle:ob-left"},
        {"section": "global", "keys": "cmd-shift-p", "action": "app.palette"},
        {"section": "global", "keys": "ctrl-shift-p", "action": "app.palette"},
    ]

    def test_bindingFor_and_chordLabel_prefer_cmd_on_macos_and_ctrl_on_linux(self):
        mac = kit_keys_eval(
            'const b = K.bindingFor("layout.toggle:ob-left");'
            'const g = K.bindingFor("app.palette");'
            'return { b, bl: K.chordLabel(b), g, gl: K.chordLabel(g) };',
            platform="macos", key_list=self.BOTH,
        )
        self.assertEqual(mac, {"b": "cmd-b", "bl": "⌘B", "g": "cmd-shift-p", "gl": "⌘⇧P"})

        lin = kit_keys_eval(
            'const b = K.bindingFor("layout.toggle:ob-left");'
            'const g = K.bindingFor("app.palette");'
            'return { b, bl: K.chordLabel(b), g, gl: K.chordLabel(g) };',
            platform="linux", key_list=self.BOTH,
        )
        self.assertEqual(lin, {"b": "ctrl-b", "bl": "Ctrl+B", "g": "ctrl-shift-p", "gl": "Ctrl+Shift+P"})

    def test_isMac_falls_back_to_mac_home_when_window_platform_is_absent(self):
        mac_home = "/Users" + "/tester"
        got = kit_keys_eval(
            'const b = K.bindingFor("layout.toggle:ob-left");'
            'return { b, label: K.chordLabel(b) };',
            platform=None, home_dir=mac_home, key_list=self.BOTH,
        )
        self.assertEqual(got, {"b": "cmd-b", "label": "⌘B"})


if __name__ == "__main__":
    unittest.main()
