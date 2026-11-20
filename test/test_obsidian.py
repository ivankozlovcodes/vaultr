"""mods/obsidian: the vault settings are merged and read by pure rules in mods/obsidian/config.js, run here through node.
The Notes panel must notice a change to obsidian.json without a reload: settingsStamp() tells it when the text changed.
A full path is `~/...` or absolute; a relative path is refused, because the mod resolves it against the process folder."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest

ROOT = home_guard.ROOT
CONFIG = os.path.join(ROOT, "mods", "obsidian", "config.js")


def call(fn, *args):
    return call_in(CONFIG, fn, *args)


def call_in(path, fn, *args):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f"import * as m from {json.dumps(path)};"
            "let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{"
            "const a=JSON.parse(s);let r;try{r=m[a.fn](...a.args);}catch(e){r={threw:String(e.message)};}"
            "process.stdout.write(JSON.stringify(r===undefined?null:r));});")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps({"fn": fn, "args": list(args)}),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


HOME = "/tmp/vaultr-home"  # a fixture home that does not look personal (test_repo checks tracked files)
DAILY_RULES = os.path.join(ROOT, "mods", "ob-tabs", "vault_rules.js")
OB_TABS = os.path.join(ROOT, "mods", "ob-tabs", "main.js")
PANEL = os.path.join(ROOT, "mods", "obsidian", "panel.js")
VAULT = os.path.join(ROOT, "mods", "obsidian", "vault.js")


class ExpandPath(unittest.TestCase):
    def test_tilde_becomes_home(self):
        self.assertEqual(call("expandPath", "~/Notes", HOME), "/tmp/vaultr-home/Notes")
        self.assertEqual(call("expandPath", "~", HOME), "/tmp/vaultr-home")

    def test_absolute_kept_without_trailing_slash(self):
        self.assertEqual(call("expandPath", "/srv/vault/", HOME), "/srv/vault")

    def test_relative_is_refused(self):
        self.assertIsNone(call("expandPath", "Notes", HOME))
        self.assertIsNone(call("expandPath", "./Notes", HOME))


class BuildConfig(unittest.TestCase):
    """The value in effect: obsidian.json wins over the vault's daily-notes.json, which wins over the defaults."""
    def build(self, own, registered=None, daily=None, app=None):
        return call("buildConfig", {"own": own, "registered": registered, "daily": daily or {}, "app": app or {}, "home": HOME})

    def test_own_vault_and_daily_keys_win(self):
        c = self.build({"vault": "~/Notes", "dailyFolder": "Journal", "dailyFormat": "DD-MM"},
                       registered="/reg/vault", daily={"folder": "0 Inbox", "format": "YYYY", "template": "T/Day"})
        self.assertEqual(c["root"], "/tmp/vaultr-home/Notes")
        self.assertEqual(c["daily"], {"folder": "Journal", "format": "DD-MM", "template": "T/Day"})

    def test_unset_vault_has_no_fallback_even_when_obsidian_names_one(self):
        self.assertEqual(self.build({}, registered="/reg/vault/"), {"threw": "No vault set."})
        self.assertEqual(self.build({"vault": "   "}, registered="/reg/vault/"), {"threw": "No vault set."})

    def test_relative_own_vault_is_an_error_not_a_guess(self):
        self.assertIn("threw", self.build({"vault": "Notes"}, registered="/reg/vault"))

    def test_no_vault_at_all_is_an_error(self):
        self.assertEqual(self.build({}, registered=None), {"threw": "No vault set."})

    def test_set_vault_names_the_vault(self):
        self.assertEqual(self.build({"vault": "~/Notes"})["name"], "Notes")

    def test_editor_is_an_argument_list_only_when_set(self):
        self.assertEqual(self.build({"vault": "/v", "editor": ["code", "--wait"]})["editor"], ["code", "--wait"])
        self.assertIsNone(self.build({"vault": "/v"})["editor"])


class SettingsStamp(unittest.TestCase):
    def test_same_text_same_stamp(self):
        self.assertEqual(call("settingsStamp", '{"a":1}', None), call("settingsStamp", '{"a":1}', None))

    def test_changed_obsidian_json_changes_the_stamp(self):
        self.assertNotEqual(call("settingsStamp", '{"vault":"/a"}', None), call("settingsStamp", '{"vault":"/b"}', None))

    def test_changed_daily_notes_changes_the_stamp(self):
        self.assertNotEqual(call("settingsStamp", None, '{"folder":"a"}'), call("settingsStamp", None, '{"folder":"b"}'))

    def test_missing_files_have_a_stamp_distinct_from_empty(self):
        self.assertNotEqual(call("settingsStamp", None, None), call("settingsStamp", "", None))


class PanelReloads(unittest.TestCase):
    """Weak: the Notes panel polls the settings stamp and re-watches a new root. Only the source shows it (no app here)."""
    def test_panel_polls_settings_and_rewatches_a_new_root(self):
        with open(os.path.join(ROOT, "mods", "obsidian", "panel.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("cx.timer.every(SETTINGS_EVERY, (cx) => this.checkSettings(cx))", src)
        self.assertIn("vault.stamp()", src)
        self.assertIn("c.root !== this.root", src)

    def test_a_failed_watch_polls_once_and_a_rewatch_stops_it(self):
        # Weak (source only): a failed watchFolder starts one 15 s reload poll. It used to start a new one per failure
        # and never stop any; the handle is kept, cancelled when the folder is watched again, and checks its gen.
        with open(PANEL, encoding="utf-8") as f:
            src = f.read()
        watch = src[src.index("  watch(root, cx) {"):src.index("  toggle(path) {")]
        self.assertIn("this.poll?.cancel()", watch)
        self.assertIn("this.poll = cx.timer.every(", watch)
        self.assertLess(watch.index("this.poll?.cancel()"), watch.index("cx.spawn("), "cancel before the new watch starts")


class DailyVault(unittest.TestCase):
    """ob-tabs keeps its own copy of the vault rule (mods cannot import each other). It must give the same answer."""
    def rule(self, own):
        return call_in(DAILY_RULES, "vaultFor", own, HOME)

    def test_unset_vault_is_not_guessed(self):
        r = self.rule({})
        self.assertTrue(r.get("unset"))
        self.assertIsNone(r.get("root"))
        self.assertEqual(r["error"], "Set your vault in Settings first.")

    def test_no_fallback_even_with_obsidian_registry_present(self):
        # vaultFor takes obsidian.json only: there is no registry argument to fall back on.
        self.assertTrue(self.rule({"vault": ""}).get("unset"))

    def test_relative_vault_is_refused(self):
        r = self.rule({"vault": "Notes"})
        self.assertIsNone(r.get("root"))
        self.assertIn("full path", r["error"])

    def test_tilde_and_absolute_vaults(self):
        self.assertEqual(self.rule({"vault": "~/Notes/"}), {"root": "/tmp/vaultr-home/Notes"})
        self.assertEqual(self.rule({"vault": "/srv/v"}), {"root": "/srv/v"})

    def test_same_expansion_as_the_obsidian_mod(self):
        for p in ["~/Notes", "~", "/srv/vault/", "Notes", "./x", "   ", "C:\\v\\", "\\\\server\\share\\"]:
            with self.subTest(path=p):
                self.assertEqual(call_in(DAILY_RULES, "expandPath", p, HOME), call("expandPath", p, HOME))


class WiringNoVault(unittest.TestCase):
    """Source checks: the daily command and the Notes panel use the no-fallback rule and show the empty state."""
    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_daily_command_says_set_your_vault_and_uses_the_rule(self):
        src = self.read(OB_TABS)
        self.assertIn("vaultFor", src)  # the rule, with its "Set your vault in Settings first" text, is in vault_rules.js
        self.assertIn("vault.error", src)  # and the command shows that message
        self.assertIn("Set your vault in Settings first", self.read(DAILY_RULES))
        self.assertNotIn("md.obsidian.Obsidian", src)  # the registry copy is gone from ob-tabs

    def test_obsidian_mod_does_not_read_obsidians_vault_list(self):
        src = self.read(VAULT)
        self.assertNotIn("registries", src)
        self.assertNotIn("Application Support", src)

    def test_notes_panel_shows_the_empty_state_with_the_settings_button(self):
        src = self.read(PANEL)
        self.assertIn("noVault", src)
        self.assertIn("No vault set.", src)
        self.assertIn("Set vault…", src)
        self.assertIn('run("ob-tabs.settings:vault")', src)
