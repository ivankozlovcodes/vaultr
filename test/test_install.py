"""install.sh against a scratch Herdr app folder (HERDR_APP_HOME). The herdr-app on PATH is home_guard's stub, which only
logs its calls, so the running window is never switched."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = home_guard.ROOT
INSTALL = os.path.join(ROOT, "install.sh")
OB_MODS = sorted(d for d in os.listdir(os.path.join(ROOT, "mods")) if d.startswith("ob-"))
EXTRA = ["insights", "obsidian"]


def run(app, *args, env=None):
    e = dict(os.environ, HERDR_APP_HOME=app, **(env or {}))
    p = subprocess.run(["bash", INSTALL, *args], capture_output=True, text=True, env=e, cwd=ROOT,
                       stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise AssertionError(f"install.sh {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout + p.stderr


def load(path):
    with open(path) as f:
        return json.load(f)


REPO_KEYS = load(os.path.join(ROOT, "keys", "vaultr-keys.json"))


def snapshot(top):
    out = {}
    for d, dirs, files in os.walk(top):
        for name in dirs + files:
            p = os.path.join(d, name)
            rel = os.path.relpath(p, top)
            if os.path.islink(p):
                out[rel] = ("link", os.readlink(p))
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    out[rel] = ("file", f.read())
    return out


class Install(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(dir=home_guard.TMP)
        self.app = os.path.join(self.base, "herdr-app")
        os.makedirs(self.app)
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump({"global": {"ctrl-k": "mine.open"}, "layout:obsidian": {"x": "stale"},
                       "mod:ob-sessions": {"f2": "old"}}, f)
        if os.path.exists(home_guard.LOG):
            os.remove(home_guard.LOG)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def p(self, *rel):
        return os.path.join(self.app, *rel)

    def calls(self):
        if not os.path.exists(home_guard.LOG):
            return []
        with open(home_guard.LOG) as f:
            return f.read().splitlines()

    def assert_linked(self, name, src):
        self.assertTrue(os.path.islink(self.p("mods", name)), name)
        self.assertEqual(os.path.realpath(self.p("mods", name)), os.path.realpath(src), name)

    def test_install_links_layout_mods_and_merges_keys(self):
        out = run(self.app)
        self.assertIn("Vaultr installation complete.", out)
        for f in ("vaultr.json", "vaultr.svg"):
            self.assertFalse(os.path.islink(self.p("layouts", f)), f"{f} is a copy, not a link into the repo")
            with open(os.path.join(ROOT, "layouts", f), "rb") as a, open(self.p("layouts", f), "rb") as b:
                self.assertEqual(a.read(), b.read(), f)
        for name in OB_MODS + EXTRA:
            self.assert_linked(name, os.path.join(ROOT, "mods", name))
        keys = load(self.p("keys.json"))
        self.assertEqual(keys["layout:vaultr"], REPO_KEYS["layout:vaultr"])
        self.assertEqual(keys["mod:ob-sessions"], REPO_KEYS["mod:ob-sessions"])
        self.assertNotIn("layout:obsidian", keys, "the stale layout:obsidian section is removed")
        self.assertEqual(keys["global"], {"ctrl-k": "mine.open"}, "the person's own keys stay")
        self.assertEqual(self.calls(), [], "a plain install does not switch layouts")

    def test_a_link_to_a_removed_mod_of_this_repo_is_pruned(self):
        # A mod deleted from the repo leaves a dangling link in the app folder: install removes it. A link into
        # another checkout is not ours to remove.
        os.makedirs(self.p("mods"), exist_ok=True)
        stale = self.p("mods", "ob-gone")
        os.symlink(os.path.join(ROOT, "mods", "ob-gone"), stale)
        other = self.p("mods", "ob-other")
        os.symlink(os.path.join(self.base, "other-checkout", "mods", "ob-other"), other)
        out = run(self.app)
        self.assertFalse(os.path.lexists(stale), "the link to the removed mod is gone")
        self.assertIn("removed link to removed mod", out)
        self.assertTrue(os.path.islink(other), "a link into another checkout stays")

    def test_install_twice_changes_nothing(self):
        run(self.app)
        before = snapshot(self.app)
        run(self.app)
        self.assertEqual(snapshot(self.app), before)

    def test_activate_switches_away_and_back(self):
        run(self.app, "--activate")
        self.assertEqual(self.calls(), ["do layout.switch --name main", "do layout.switch --name vaultr"])

    def test_uninstall_removes_links_and_keys(self):
        run(self.app)
        out = run(self.app, "--uninstall")
        self.assertIn("Vaultr uninstalled.", out)
        self.assertFalse(os.path.lexists(self.p("layouts", "vaultr.json")))
        self.assertFalse(os.path.lexists(self.p("layouts", "vaultr.svg")))
        for name in OB_MODS + EXTRA:
            self.assertFalse(os.path.lexists(self.p("mods", name)), name)
        keys = load(self.p("keys.json"))
        self.assertNotIn("layout:vaultr", keys)
        self.assertNotIn("mod:ob-sessions", keys)
        self.assertEqual(keys["global"], {"ctrl-k": "mine.open"})
        self.assertEqual(self.calls(), ["do layout.switch --name main"])

    def test_uninstall_switches_to_the_configured_fallback(self):
        run(self.app)
        run(self.app, "--uninstall", env={"VAULTR_FALLBACK_LAYOUT": "terminals"})
        self.assertEqual(self.calls(), ["do layout.switch --name terminals"])

    def test_a_real_folder_is_left_alone(self):
        os.makedirs(self.p("mods", "obsidian"))
        with open(self.p("mods", "obsidian", "mine.txt"), "w") as f:
            f.write("mine\n")
        out = run(self.app)
        self.assertIn("skipped mod", out)
        self.assertTrue(os.path.isfile(self.p("mods", "obsidian", "mine.txt")))
        run(self.app, "--uninstall")
        self.assertTrue(os.path.isfile(self.p("mods", "obsidian", "mine.txt")))


class LayoutCopy(unittest.TestCase):
    """The layout is copied into the Herdr app folder, so the arrangement the person makes (it is written to that
    file) never lands in the repo. A copy that differs from the repo is the person's and is kept unless
    --reset-layout is passed; --link keeps the old symlink for development."""

    def setUp(self):
        self.base = tempfile.mkdtemp(dir=home_guard.TMP)
        self.app = os.path.join(self.base, "herdr-app")
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(self.repo, "layouts"))
        os.makedirs(self.app)
        shutil.copy(INSTALL, os.path.join(self.repo, "install.sh"))
        self.default = '{"name": "default"}\n'
        with open(os.path.join(self.repo, "layouts", "vaultr.json"), "w") as f:
            f.write(self.default)
        with open(os.path.join(self.repo, "layouts", "vaultr.svg"), "w") as f:
            f.write("<svg/>")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def install(self, *args, ok=True):
        p = subprocess.run(["bash", os.path.join(self.repo, "install.sh"), *args], capture_output=True, text=True,
                           env=dict(os.environ, HERDR_APP_HOME=self.app), cwd=self.repo, stdin=subprocess.DEVNULL)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def target(self):
        return os.path.join(self.app, "layouts", "vaultr.json")

    def read(self, path):
        with open(path) as f:
            return f.read()

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def backups(self):
        return sorted(glob.glob(self.target() + ".bak-*"))

    def test_a_fresh_install_copies_the_layout(self):
        self.install()
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), self.default)
        self.assertTrue(os.path.isfile(os.path.join(self.app, "layouts", "vaultr.svg")))

    def test_an_old_symlink_into_the_repo_becomes_a_copy(self):
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(os.path.join(self.repo, "layouts", "vaultr.json"), self.target())
        self.install()
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), self.default)

    def test_a_personal_copy_is_kept_on_reinstall(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        out = self.install()
        self.assertEqual(self.read(self.target()), '{"name": "mine"}\n')
        self.assertIn("--reset-layout", out)
        self.assertEqual(self.backups(), [])

    def test_a_symlink_to_a_personal_repo_file_keeps_the_arrangement(self):
        # the live case: the old link pointed at a repo file that held the person's own arrangement
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), '{"name": "mine"}\n')
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(os.path.join(self.repo, "layouts", "vaultr.json"), self.target())
        self.install()
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), '{"name": "mine"}\n')

    def test_a_kept_copy_naming_a_mod_that_is_gone_warns(self):
        os.makedirs(os.path.join(self.repo, "mods", "insights"))
        os.makedirs(os.path.join(self.app, "mods", "their-mod"))
        mine = json.dumps({"name": "mine", "children": [
            {"content": {"mod": "ob-gone"}}, {"content": {"mod": "insights"}},
            {"content": {"mod": "files"}}, {"content": {"mod": "changes"}}, {"content": {"mod": "their-mod"}}]}) + "\n"
        self.install()
        self.write(self.target(), mine)
        out = self.install()
        self.assertEqual(self.read(self.target()), mine, "the copy is still kept")
        warn = [line for line in out.splitlines() if "not installed" in line]
        self.assertEqual(len(warn), 1, out)
        self.assertIn("ob-gone", warn[0])
        self.assertIn("--reset-layout", warn[0])
        for name in ("insights", "files", "changes", "their-mod"):
            self.assertNotIn(name, warn[0])

    def test_a_kept_copy_with_every_mod_present_does_not_warn(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        self.assertNotIn("not installed", self.install())

    def test_reset_layout_backs_up_and_replaces(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        self.install("--reset-layout")
        self.assertEqual(self.read(self.target()), self.default)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.read(self.backups()[0]), '{"name": "mine"}\n')

    def test_link_mode_links_and_keeps_a_backup_of_a_personal_copy(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        self.install("--link")
        self.assertTrue(os.path.islink(self.target()))
        self.assertEqual(os.path.realpath(self.target()), os.path.join(self.repo, "layouts", "vaultr.json"))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.read(self.backups()[0]), '{"name": "mine"}\n')

    def test_a_dangling_link_is_replaced_by_a_copy(self):
        # the repo was moved: the old link points nowhere
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(os.path.join(self.base, "moved-away", "layouts", "vaultr.json"), self.target())
        out = self.install()
        self.assertNotIn("skipped layout", out)
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), self.default)

    def test_a_dangling_link_is_relinked_in_link_mode(self):
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(os.path.join(self.base, "moved-away", "layouts", "vaultr.json"), self.target())
        self.install("--link")
        self.assertEqual(os.path.realpath(self.target()), os.path.join(self.repo, "layouts", "vaultr.json"))

    def other_checkout_link(self, text):
        other = os.path.join(self.base, "other", "layouts", "vaultr.json")
        self.write(other, text)
        self.write(os.path.join(self.base, "other", "install.sh"), "#!/bin/bash\n")
        self.write(os.path.join(self.base, "other", "kit", "sync.sh"), "#!/bin/bash\n")
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(other, self.target())
        return other

    def test_a_link_to_another_checkouts_layout_becomes_a_copy(self):
        self.other_checkout_link('{"name": "mine"}\n')
        out = self.install()
        self.assertNotIn("skipped layout", out)
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), '{"name": "mine"}\n', "the arrangement it held is kept")

    def test_a_link_to_another_checkouts_layout_is_replaced_by_reset_layout(self):
        self.other_checkout_link('{"name": "mine"}\n')
        self.install("--reset-layout")
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), self.default)
        self.assertEqual([self.read(b) for b in self.backups()], ['{"name": "mine"}\n'])

    def test_a_link_to_another_checkouts_layout_is_relinked_in_link_mode(self):
        other = self.other_checkout_link('{"name": "mine"}\n')
        self.install("--link")
        self.assertEqual(os.path.realpath(self.target()), os.path.join(self.repo, "layouts", "vaultr.json"))
        self.assertEqual([self.read(b) for b in self.backups()], ['{"name": "mine"}\n'])
        self.assertEqual(self.read(other), '{"name": "mine"}\n', "the other checkout is not touched")

    def test_an_unrecognised_link_is_left_alone(self):
        elsewhere = os.path.join(self.base, "elsewhere", "my-layout.json")
        self.write(elsewhere, '{"name": "mine"}\n')
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(elsewhere, self.target())
        out = self.install()
        self.assertIn("skipped layout", out)
        self.assertEqual(os.readlink(self.target()), elsewhere)

    def test_a_link_to_a_layouts_folder_that_is_not_a_checkout_is_left_alone(self):
        # e.g. a dotfiles repo with its own layouts/ folder: not Vaultr's to turn into a copy
        mine = os.path.join(self.base, "dotfiles", "layouts", "vaultr.json")
        self.write(mine, '{"name": "mine"}\n')
        os.makedirs(os.path.join(self.app, "layouts"))
        os.symlink(mine, self.target())
        out = self.install()
        self.assertIn("skipped layout", out)
        self.assertEqual(os.readlink(self.target()), mine)

    def test_uninstall_removes_an_unchanged_copy(self):
        self.install()
        self.install("--uninstall")
        self.assertFalse(os.path.lexists(self.target()))

    def test_uninstall_leaves_a_personal_copy_and_says_so(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        out = self.install("--uninstall")
        self.assertEqual(self.read(self.target()), '{"name": "mine"}\n')
        self.assertIn("--reset-layout", out)

    def test_uninstall_reset_layout_removes_and_backs_up(self):
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        self.install("--uninstall", "--reset-layout")
        self.assertFalse(os.path.lexists(self.target()))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.read(self.backups()[0]), '{"name": "mine"}\n')


if __name__ == "__main__":
    unittest.main()


class KeyOwnership(unittest.TestCase):
    """Re-installing removes only the keys Vaultr itself put in its sections: a key dropped from the repo file goes,
    a key the person added to the same section stays."""

    def setUp(self):
        self.base = tempfile.mkdtemp(dir=home_guard.TMP)
        self.app = os.path.join(self.base, "herdr-app")
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(self.repo, "keys"))
        os.makedirs(self.app)
        shutil.copy(INSTALL, os.path.join(self.repo, "install.sh"))
        self.keys_file = os.path.join(self.repo, "keys", "vaultr-keys.json")
        self.write_repo_keys({"layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search", "ctrl-x": "old"},
                              "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump({"global": {"ctrl-k": "mine.open"}}, f)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write_repo_keys(self, keys):
        with open(self.keys_file, "w") as f:
            json.dump(keys, f)

    def install(self, *args, os_name="Linux"):
        p = subprocess.run(["bash", os.path.join(self.repo, "install.sh"), *args], capture_output=True, text=True,
                           env=dict(os.environ, HERDR_APP_HOME=self.app, VAULTR_OS=os_name), cwd=self.repo,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def installed(self):
        return load(os.path.join(self.app, "keys.json"))

    def test_key_dropped_from_the_repo_is_removed_on_reinstall(self):
        self.install()
        self.write_repo_keys({"layout:vaultr": {"ctrl-shift-k": "ob-tabs.open:ob-search"},
                              "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        self.install()
        layout = self.installed()["layout:vaultr"]
        self.assertNotIn("ctrl-shift-f", layout, "the old binding must not survive a re-install")
        self.assertNotIn("ctrl-x", layout)
        self.assertEqual(layout, {"ctrl-shift-k": "ob-tabs.open:ob-search"})

    def test_a_key_the_person_added_to_a_vaultr_section_stays(self):
        self.install()
        keys = self.installed()
        keys["layout:vaultr"]["ctrl-q"] = "mine.thing"
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)
        self.write_repo_keys({"layout:vaultr": {"ctrl-shift-k": "ob-tabs.open:ob-search"},
                              "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        self.install()
        layout = self.installed()["layout:vaultr"]
        self.assertEqual(layout.get("ctrl-q"), "mine.thing", "the person's own key is not Vaultr's to remove")
        self.assertNotIn("ctrl-shift-f", layout)

    def test_a_chord_the_person_bound_is_not_taken_over_by_a_new_repo_key(self):
        self.install()
        keys = self.installed()
        keys["layout:vaultr"]["ctrl-q"] = "mine.thing"
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)
        self.write_repo_keys({"layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search", "ctrl-q": "ob-tabs.quit"},
                              "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        out = self.install()
        layout = self.installed()["layout:vaultr"]
        self.assertEqual(layout.get("ctrl-q"), "mine.thing", "the person's binding wins")
        self.assertIn("ctrl-q", out, "the skipped chord is named")
        self.install("--uninstall")
        self.assertEqual(self.installed()["layout:vaultr"], {"ctrl-q": "mine.thing"},
                         "a chord Vaultr did not install is not removed on uninstall")

    def test_uninstall_removes_only_vaultr_keys(self):
        self.install()
        keys = self.installed()
        keys["layout:vaultr"]["ctrl-q"] = "mine.thing"
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)
        self.install("--uninstall")
        after = self.installed()
        self.assertEqual(after["layout:vaultr"], {"ctrl-q": "mine.thing"})
        self.assertNotIn("mod:ob-sessions", after)
        self.assertEqual(after["global"], {"ctrl-k": "mine.open"})

    def test_on_macos_ctrl_keys_install_as_cmd(self):
        self.install(os_name="Darwin")
        keys = self.installed()
        self.assertEqual(keys["layout:vaultr"], {"cmd-shift-f": "ob-tabs.open:ob-search", "cmd-x": "old"})
        self.assertEqual(keys["mod:ob-sessions"], {"f2": "ob-sessions.rename"})
        self.assertEqual(keys["global"], {"ctrl-k": "mine.open"}, "the person's own keys are not translated")

    def test_moving_a_keys_file_to_macos_replaces_the_ctrl_keys(self):
        self.install()
        self.install(os_name="Darwin")
        layout = self.installed()["layout:vaultr"]
        self.assertEqual(sorted(layout), ["cmd-shift-f", "cmd-x"])

    def test_uninstall_on_macos_removes_the_cmd_keys(self):
        self.install(os_name="Darwin")
        self.install("--uninstall", os_name="Darwin")
        after = self.installed()
        self.assertNotIn("layout:vaultr", after)
        self.assertNotIn("mod:ob-sessions", after)


if __name__ == "__main__":
    unittest.main()
