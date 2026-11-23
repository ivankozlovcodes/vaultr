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
from pathlib import Path

ROOT = home_guard.ROOT
INSTALL = os.path.join(ROOT, "install.sh")
KEYSFILE_JS = Path(ROOT, "mods", "ob-settings", "keysfile.js")
OB_MODS = sorted(d for d in os.listdir(os.path.join(ROOT, "mods")) if d.startswith("ob-"))
EXTRA = ["insights", "obsidian"]


def run(app, *args, env=None):
    e = dict(os.environ, HERDR_APP_HOME=app, VAULTR_OS="Linux", **(env or {}))
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

    def test_install_writes_layout_record_outside_layouts_and_uninstall_removes_it(self):
        run(self.app)
        rec = self.p("vaultr-layout.installed.json")
        self.assertTrue(os.path.isfile(rec))
        self.assertFalse(os.path.exists(self.p("layouts", "vaultr-layout.installed.json")))
        with open(os.path.join(ROOT, "layouts", "vaultr.json"), "rb") as a, open(rec, "rb") as b:
            self.assertEqual(a.read(), b.read())
        run(self.app, "--uninstall")
        self.assertFalse(os.path.lexists(rec))

    def test_ci_smoke_install_then_uninstall_leaves_no_layout(self):
        fresh_app = os.path.join(self.base, "fresh-app")
        os.makedirs(fresh_app)
        run(fresh_app)
        self.assertTrue(os.path.isfile(os.path.join(fresh_app, "layouts", "vaultr.json")))
        self.assertTrue(os.path.islink(os.path.join(fresh_app, "mods", "ob-tabs")))
        run(fresh_app, "--uninstall")
        self.assertFalse(os.path.lexists(os.path.join(fresh_app, "layouts", "vaultr.json")))
        self.assertFalse(os.path.lexists(os.path.join(fresh_app, "mods", "ob-tabs")))
        self.assertFalse(os.path.lexists(os.path.join(fresh_app, "vaultr-layout.installed.json")))


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

    def record(self):
        return os.path.join(self.app, "vaultr-layout.installed.json")

    def build_checkout(self, layout_data, name="checkout"):
        repo = os.path.join(self.base, name)
        os.makedirs(os.path.join(repo, "kit"), exist_ok=True)
        os.makedirs(os.path.join(repo, "keys"), exist_ok=True)
        os.makedirs(os.path.join(repo, "layouts"), exist_ok=True)
        os.makedirs(os.path.join(repo, "mods"), exist_ok=True)
        shutil.copy(INSTALL, os.path.join(repo, "install.sh"))
        shutil.copy(os.path.join(ROOT, "kit", "sync.sh"), os.path.join(repo, "kit", "sync.sh"))
        shutil.copy(os.path.join(ROOT, "keys", "vaultr-keys.json"), os.path.join(repo, "keys", "vaultr-keys.json"))
        shutil.copy(os.path.join(ROOT, "layouts", "vaultr.svg"), os.path.join(repo, "layouts", "vaultr.svg"))
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(layout_data, indent=2) + "\n")
        return repo

    def install_from(self, repo, *args):
        p = subprocess.run(["bash", os.path.join(repo, "install.sh"), *args], capture_output=True, text=True,
                           env=dict(os.environ, HERDR_APP_HOME=self.app), cwd=repo, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def test_a_fresh_install_copies_the_layout(self):
        self.install()
        self.assertFalse(os.path.islink(self.target()))
        self.assertEqual(self.read(self.target()), self.default)
        self.assertTrue(os.path.isfile(os.path.join(self.app, "layouts", "vaultr.svg")))
        self.assertEqual(self.read(self.record()), self.default)

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
        self.assertEqual(os.path.realpath(self.target()), os.path.realpath(os.path.join(self.repo, "layouts", "vaultr.json")))
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
        self.assertEqual(os.path.realpath(self.target()), os.path.realpath(os.path.join(self.repo, "layouts", "vaultr.json")))

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
        self.assertEqual(os.path.realpath(self.target()), os.path.realpath(os.path.join(self.repo, "layouts", "vaultr.json")))
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
        self.assertFalse(os.path.lexists(self.record()))

    def _base_layout(self):
        return {
            "id": "root",
            "type": "row",
            "children": [
                {
                    "id": "ob-left",
                    "type": "column",
                    "size": {"px": 300},
                    "children": [
                        {
                            "id": "ob-lt-stack",
                            "type": "stack",
                            "active": "ob-sessions",
                            "children": [
                                {"id": "ob-sessions", "type": "block", "content": {"mod": "ob-sessions"}},
                                {"id": "ob-search", "type": "block", "content": {"mod": "ob-search"}},
                            ],
                        },
                    ],
                },
                {
                    "id": "ob-right",
                    "type": "column",
                    "size": {"px": 368},
                    "children": [
                        {
                            "id": "ob-rb-stack",
                            "type": "stack",
                            "active": "ob-graph",
                            "children": [
                                {"id": "ob-graph", "type": "block", "content": {"mod": "ob-graph"}},
                                {"id": "ob-outline", "type": "block", "content": {"mod": "ob-outline"}},
                            ],
                        },
                    ],
                },
            ],
        }

    def test_b1_no_copy_with_and_without_record(self):
        # Without record (already covered by fresh install) and with an older stale record:
        self.write(self.record(), '{"id": "stale"}\n')
        out = self.install()
        self.assertIn("copied layout:", out)
        self.assertEqual(self.read(self.target()), self.default)
        self.assertEqual(self.read(self.record()), self.default)

    def test_b2_copy_equals_repo_with_and_without_record(self):
        # Without a record: copy matches repo -> stays untouched and record is written.
        self.write(self.target(), self.default)
        out = self.install()
        self.assertEqual(self.read(self.target()), self.default)
        self.assertEqual(self.read(self.record()), self.default)
        self.assertNotIn("updated layout:", out)
        self.assertNotIn("kept your layout:", out)
        # With a stale record: refreshes record while leaving matching copy alone.
        self.write(self.record(), '{"id": "stale"}\n')
        out = self.install()
        self.assertEqual(self.read(self.record()), self.default)
        self.assertEqual(self.backups(), [])
        self.assertNotIn("updated layout:", out)

    def test_b3_copy_differs_and_equals_record_replaces_without_backup(self):
        v1 = json.dumps({"id": "root", "children": [{"id": "a"}]}) + "\n"
        v2 = json.dumps({"id": "root", "children": [{"id": "a"}, {"id": "b"}]}) + "\n"
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), v1)
        self.install()
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), v2)
        out = self.install()
        self.assertEqual(self.read(self.target()), v2)
        self.assertEqual(self.read(self.record()), v2)
        self.assertEqual(self.backups(), [])
        self.assertIn(f"updated layout: {self.target()} (unchanged since the last install)", out)

    def test_b3_without_record_falls_back_to_b4(self):
        v1 = {"id": "root", "children": [{"id": "a"}]}
        v2 = {"id": "root", "children": [{"id": "a"}, {"id": "b"}]}
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), json.dumps(v1) + "\n")
        self.install()
        os.remove(self.record())
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), json.dumps(v2) + "\n")
        out = self.install()
        self.assertNotIn("unchanged since the last install", out)
        self.assertIn("added to your layout: b (in root)", out)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual([c["id"] for c in load(self.target())["children"]], ["a", "b"])

    def test_b4_with_and_without_record_when_nothing_to_add(self):
        # With record: nothing new in repo -> keeps copy unrewritten and prints kept your layout.
        self.install()
        mine = '{"name": "mine",  "extra": 1}\n'
        self.write(self.target(), mine)
        out = self.install()
        self.assertEqual(self.read(self.target()), mine)
        self.assertIn("kept your layout:", out)
        self.assertEqual(self.backups(), [])
        # Without record: still keeps copy unrewritten and writes the record.
        os.remove(self.record())
        out = self.install()
        self.assertEqual(self.read(self.target()), mine)
        self.assertIn("kept your layout:", out)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.read(self.record()), self.default)

    def test_untouched_old_copy_in_checkout_receives_new_panel(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        v2 = self._base_layout()
        v2["children"][0]["children"][0]["children"].append(
            {"id": "ob-inbox", "type": "block", "content": {"mod": "ob-inbox"}}
        )
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertIn("(unchanged since the last install)", out)
        ids = [c["id"] for c in load(self.target())["children"][0]["children"][0]["children"]]
        self.assertEqual(ids, ["ob-sessions", "ob-search", "ob-inbox"])

    def test_changed_copy_receives_new_panel_and_keeps_change(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        # Person resizes ob-left, reorders ob-lt-stack, and adds a custom field.
        mine = load(self.target())
        mine["children"][0]["size"] = {"px": 420}
        mine["children"][0]["children"][0]["children"].reverse()
        mine_text = json.dumps(mine, indent=2) + "\n"
        self.write(self.target(), mine_text)
        # Repo changes ob-left size (must not overwrite person's) and inserts ob-inbox after ob-sessions.
        v2 = self._base_layout()
        v2["children"][0]["size"] = {"px": 250}
        v2["children"][0]["children"][0]["children"].insert(
            1, {"id": "ob-inbox", "type": "block", "content": {"mod": "ob-inbox"}}
        )
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertIn("added to your layout: ob-inbox (in ob-lt-stack)", out)
        self.assertEqual([self.read(b) for b in self.backups()], [mine_text])
        updated_raw = self.read(self.target())
        self.assertTrue(updated_raw.endswith("\n"))
        updated = json.loads(updated_raw)
        self.assertEqual(updated_raw, json.dumps(updated, indent=2) + "\n")
        self.assertEqual(updated["children"][0]["size"], {"px": 420}, "person size preserved; repo property not merged")
        stack_ids = [c["id"] for c in updated["children"][0]["children"][0]["children"]]
        self.assertEqual(stack_ids, ["ob-search", "ob-sessions", "ob-inbox"])
        self.assertEqual(load(self.record()), v2)

    def test_moved_view_is_not_duplicated_and_fallback_placement_appends_at_end(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        # Person moves ob-outline from ob-rb-stack to ob-lt-stack.
        mine = load(self.target())
        outline = mine["children"][1]["children"][0]["children"].pop()
        mine["children"][0]["children"][0]["children"].append(outline)
        self.write(self.target(), json.dumps(mine, indent=2) + "\n")
        # Repo adds ob-inbox right after ob-outline in ob-rb-stack (copy's ob-rb-stack lacks ob-outline).
        v2 = self._base_layout()
        v2["children"][1]["children"][0]["children"].append(
            {"id": "ob-inbox", "type": "block", "content": {"mod": "ob-inbox"}}
        )
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertIn("added to your layout: ob-inbox (in ob-rb-stack)", out)
        merged = load(self.target())
        all_ids = []
        stack = [merged]
        while stack:
            n = stack.pop()
            if "id" in n:
                all_ids.append(n["id"])
            stack.extend(n.get("children") or [])
        self.assertEqual(all_ids.count("ob-outline"), 1, "moved view must not be duplicated")
        self.assertEqual([c["id"] for c in merged["children"][0]["children"][0]["children"]],
                         ["ob-sessions", "ob-search", "ob-outline"])
        self.assertEqual([c["id"] for c in merged["children"][1]["children"][0]["children"]],
                         ["ob-graph", "ob-inbox"])

    def test_person_removed_panel_does_not_come_back_and_dropped_repo_node_stays(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        # Person removes ob-search.
        mine = load(self.target())
        mine["children"][0]["children"][0]["children"] = [
            c for c in mine["children"][0]["children"][0]["children"] if c["id"] != "ob-search"
        ]
        mine_text = json.dumps(mine, indent=2) + "\n"
        self.write(self.target(), mine_text)
        # Repo drops ob-outline and adds ob-inbox.
        v2 = self._base_layout()
        v2["children"][1]["children"][0]["children"] = [
            c for c in v2["children"][1]["children"][0]["children"] if c["id"] != "ob-outline"
        ]
        v2["children"][0]["children"][0]["children"].append(
            {"id": "ob-inbox", "type": "block", "content": {"mod": "ob-inbox"}}
        )
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertNotIn("ob-search", out)
        merged = load(self.target())
        left_ids = [c["id"] for c in merged["children"][0]["children"][0]["children"]]
        right_ids = [c["id"] for c in merged["children"][1]["children"][0]["children"]]
        self.assertEqual(left_ids, ["ob-sessions", "ob-inbox"], "removed panel stayed removed")
        self.assertEqual(right_ids, ["ob-graph", "ob-outline"], "dropped repo node stayed in copy")

    def test_candidate_subtree_strips_existing_descendants_and_is_not_handled_twice(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        mine = load(self.target())
        mine["children"][0]["size"] = {"px": 320}
        self.write(self.target(), json.dumps(mine, indent=2) + "\n")
        # Repo adds a new group under ob-left holding a new node ob-new-child and already-present ob-search.
        v2 = self._base_layout()
        v2["children"][0]["children"].append({
            "id": "ob-new-group",
            "type": "column",
            "children": [
                {"id": "ob-new-child", "type": "block", "content": {"mod": "ob-inbox"}},
                {"id": "ob-search", "type": "block", "content": {"mod": "ob-search"}},
            ],
        })
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertIn("added to your layout: ob-new-group (in ob-left)", out)
        self.assertNotIn("added to your layout: ob-new-child", out)
        merged = load(self.target())
        group = next(c for c in merged["children"][0]["children"] if c["id"] == "ob-new-group")
        self.assertEqual([c["id"] for c in group["children"]], ["ob-new-child"])

    def test_candidate_whose_parent_is_gone_prints_not_added(self):
        v1 = self._base_layout()
        repo = self.build_checkout(v1)
        self.install_from(repo)
        # Person removes ob-rb-stack (and its children).
        mine = load(self.target())
        mine["children"][1]["children"] = []
        mine_text = json.dumps(mine, indent=2) + "\n"
        self.write(self.target(), mine_text)
        # Repo adds ob-inbox inside ob-rb-stack.
        v2 = self._base_layout()
        v2["children"][1]["children"][0]["children"].append(
            {"id": "ob-inbox", "type": "block", "content": {"mod": "ob-inbox"}}
        )
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        out = self.install_from(repo)
        self.assertIn(
            "not added: ob-inbox (your layout has no ob-rb-stack; --reset-layout takes the repo's layout, after a backup)",
            out,
        )
        self.assertEqual(self.read(self.target()), mine_text)
        self.assertEqual(self.backups(), [])

    def test_record_is_written_refreshed_and_removed_and_reset_writes_record(self):
        v1 = {"id": "root", "children": [{"id": "a"}]}
        v2 = {"id": "root", "children": [{"id": "a"}, {"id": "b"}]}
        repo = self.build_checkout(v1)
        self.install_from(repo)
        self.assertEqual(load(self.record()), v1)
        self.assertFalse(os.path.exists(os.path.join(self.app, "layouts", "vaultr-layout.installed.json")))
        self.write(os.path.join(repo, "layouts", "vaultr.json"), json.dumps(v2, indent=2) + "\n")
        self.install_from(repo)
        self.assertEqual(load(self.record()), v2)
        os.remove(self.record())
        self.write(self.target(), '{"id": "root", "children": []}\n')
        self.install_from(repo, "--reset-layout")
        self.assertEqual(load(self.record()), v2)
        self.install_from(repo, "--uninstall")
        self.assertFalse(os.path.lexists(self.record()))

    def test_preview_svg_is_copied_whenever_it_differs(self):
        self.install()
        svg = os.path.join(self.app, "layouts", "vaultr.svg")
        self.write(svg, "<svg>old</svg>")
        out = self.install()
        self.assertEqual(self.read(svg), "<svg/>")
        self.assertEqual(glob.glob(svg + ".bak-*"), [])
        self.assertIn("updated layout:", out)

    def test_uninstall_removes_copy_matching_record_and_leaves_differing_copy(self):
        v1 = json.dumps({"id": "root", "children": [{"id": "a"}]}) + "\n"
        v2 = json.dumps({"id": "root", "children": [{"id": "a"}, {"id": "b"}]}) + "\n"
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), v1)
        self.install()
        # Repo advances without reinstalling: copy still matches record v1, so uninstall removes it.
        self.write(os.path.join(self.repo, "layouts", "vaultr.json"), v2)
        self.install("--uninstall")
        self.assertFalse(os.path.lexists(self.target()))
        self.assertFalse(os.path.lexists(self.record()))
        # Differing copy stays on uninstall, while the record is removed.
        self.install()
        self.write(self.target(), '{"name": "mine"}\n')
        self.install("--uninstall")
        self.assertEqual(self.read(self.target()), '{"name": "mine"}\n')
        self.assertFalse(os.path.lexists(self.record()))


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

    def drop_key(self, section, chord):
        keys = self.installed()
        del keys[section][chord]
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)

    def test_a_vaultr_key_the_person_removed_stays_removed_on_reinstall(self):
        self.install()
        self.drop_key("layout:vaultr", "ctrl-shift-f")
        out = self.install()
        layout = self.installed()["layout:vaultr"]
        self.assertNotIn("ctrl-shift-f", layout, "removed in Settings, so not put back")
        self.assertEqual(layout.get("ctrl-x"), "old", "the other Vaultr keys are still installed")
        self.install()
        self.assertNotIn("ctrl-shift-f", self.installed()["layout:vaultr"], "and it stays removed on every install after")
        self.assertIn("ctrl-shift-f", out, "the install says it left that key out")

    def test_a_removed_key_comes_back_with_a_fresh_install_after_uninstall(self):
        self.install()
        self.drop_key("layout:vaultr", "ctrl-shift-f")
        self.install()
        self.install("--uninstall")
        self.assertFalse(os.path.exists(os.path.join(self.app, "vaultr-keys.owned.json")), "the record goes with the keys")
        self.install()
        self.assertEqual(self.installed()["layout:vaultr"].get("ctrl-shift-f"), "ob-tabs.open:ob-search")

    def test_a_removed_key_is_forgotten_when_the_repo_drops_it(self):
        self.install()
        self.drop_key("layout:vaultr", "ctrl-shift-f")
        self.install()
        self.write_repo_keys({"layout:vaultr": {"ctrl-x": "old"}, "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        self.install()
        self.write_repo_keys({"layout:vaultr": {"ctrl-shift-f": "ob-tabs.other", "ctrl-x": "old"},
                              "mod:ob-sessions": {"f2": "ob-sessions.rename"}})
        self.install()
        self.assertEqual(self.installed()["layout:vaultr"].get("ctrl-shift-f"), "ob-tabs.other",
                         "a chord the repo dropped and later brought back is new again")

    def hotkeys_edit(self, scope, op):
        """Edit keys.json the way Settings > Hotkeys does: through ob-settings' keysfile.js applyEdit."""
        path = os.path.join(self.app, "keys.json")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        src = (f'import {{ applyEdit }} from "{KEYSFILE_JS.as_uri()}";\n'
               f'const a = JSON.parse(process.argv[1]);\n'
               f'process.stdout.write(applyEdit(a.text, a.scope, a.op).text);')
        out = subprocess.run(["node", "--input-type=module", "-e", src, json.dumps({"text": text, "scope": scope, "op": op})],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(path, "w", encoding="utf-8") as f:
            f.write(out.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_key_removed_in_the_hotkeys_tab_stays_removed(self):
        self.install()
        self.hotkeys_edit("layout:vaultr", {"kind": "unbind", "chord": "ctrl-shift-f", "action": "ob-tabs.open:ob-search"})
        self.install()
        layout = self.installed()["layout:vaultr"]
        self.assertNotIn("ctrl-shift-f", layout)
        self.assertEqual(layout.get("ctrl-x"), "old")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_a_key_restored_in_the_hotkeys_tab_is_vaultrs_again(self):
        self.install()
        self.hotkeys_edit("layout:vaultr", {"kind": "unbind", "chord": "ctrl-shift-f", "action": "ob-tabs.open:ob-search"})
        self.install()
        self.hotkeys_edit("layout:vaultr", {"kind": "restore", "action": "ob-tabs.open:ob-search", "defaults": ["ctrl-shift-f"]})
        self.install()
        self.assertEqual(self.installed()["layout:vaultr"].get("ctrl-shift-f"), "ob-tabs.open:ob-search")
        self.install("--uninstall")
        self.assertNotIn("layout:vaultr", self.installed(), "a restored default is Vaultr's again, so uninstall removes it")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_removing_every_key_of_a_section_removes_the_section_and_keeps_it_removed(self):
        # the Hotkeys tab drops a section when its last key goes
        self.install()
        self.hotkeys_edit("mod:ob-sessions", {"kind": "unbind", "chord": "f2", "action": "ob-sessions.rename"})
        self.assertNotIn("mod:ob-sessions", self.installed())
        self.install()
        self.assertNotIn("mod:ob-sessions", self.installed())
        self.assertIn("layout:vaultr", self.installed())

    def test_an_owned_record_from_before_removed_keys_were_tracked_still_works(self):
        self.install()
        with open(os.path.join(self.app, "vaultr-keys.owned.json")) as f:
            rec = json.load(f)
        rec.pop("_removed", None)
        with open(os.path.join(self.app, "vaultr-keys.owned.json"), "w") as f:
            json.dump(rec, f)
        self.install()
        self.assertEqual(self.installed()["layout:vaultr"], {"ctrl-shift-f": "ob-tabs.open:ob-search", "ctrl-x": "old"})
        self.install("--uninstall")
        self.assertNotIn("layout:vaultr", self.installed())

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

    def test_a_third_section_is_installed_recorded_and_removed_on_uninstall(self):
        self.write_repo_keys({
            "layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search"},
            "mod:ob-sessions": {"f2": "ob-sessions.rename"},
            "mod:ob-extra": {"ctrl-alt-x": "ob-extra.ping"},
        })
        self.install()
        keys = self.installed()
        self.assertEqual(keys["mod:ob-extra"], {"ctrl-alt-x": "ob-extra.ping"})
        owned = load(os.path.join(self.app, "vaultr-keys.owned.json"))
        self.assertEqual(owned["mod:ob-extra"], ["ctrl-alt-x"])
        keys["mod:ob-extra"]["ctrl-m"] = "mine.extra"
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)
        self.install()
        self.assertEqual(self.installed()["mod:ob-extra"], {"ctrl-m": "mine.extra", "ctrl-alt-x": "ob-extra.ping"})
        self.install("--uninstall")
        after = self.installed()
        self.assertEqual(after["mod:ob-extra"], {"ctrl-m": "mine.extra"})
        self.assertNotIn("layout:vaultr", after)
        self.assertNotIn("mod:ob-sessions", after)
        self.assertFalse(os.path.exists(os.path.join(self.app, "vaultr-keys.owned.json")))

    def test_uninstall_without_owned_record_removes_every_repo_keys_section(self):
        self.write_repo_keys({
            "layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search"},
            "mod:ob-sessions": {"f2": "ob-sessions.rename"},
            "mod:ob-extra": {"ctrl-alt-x": "ob-extra.ping"},
        })
        self.install()
        os.remove(os.path.join(self.app, "vaultr-keys.owned.json"))
        self.install("--uninstall")
        after = self.installed()
        self.assertNotIn("layout:vaultr", after)
        self.assertNotIn("mod:ob-sessions", after)
        self.assertNotIn("mod:ob-extra", after)
        self.assertEqual(after["global"], {"ctrl-k": "mine.open"})

    def test_a_section_dropped_from_repo_keys_is_cleaned_from_keys_and_owned(self):
        self.write_repo_keys({
            "layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search"},
            "mod:ob-sessions": {"f2": "ob-sessions.rename"},
            "mod:ob-extra": {"ctrl-alt-x": "ob-extra.ping"},
        })
        self.install()
        keys = self.installed()
        keys["mod:ob-extra"]["ctrl-m"] = "mine.extra"
        with open(os.path.join(self.app, "keys.json"), "w") as f:
            json.dump(keys, f)
        self.write_repo_keys({
            "layout:vaultr": {"ctrl-shift-f": "ob-tabs.open:ob-search"},
            "mod:ob-sessions": {"f2": "ob-sessions.rename"},
        })
        self.install()
        self.assertEqual(self.installed()["mod:ob-extra"], {"ctrl-m": "mine.extra"})
        self.assertNotIn("mod:ob-extra", load(os.path.join(self.app, "vaultr-keys.owned.json")))


if __name__ == "__main__":
    unittest.main()
