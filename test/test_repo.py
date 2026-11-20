"""The repo as Herdr, the installer and the kit sync see it: every mod has its manifest and entry, the kit copies match
kit/, every script parses, the keys and install.sh name mods that exist, and nothing personal is tracked."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import py_compile
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = home_guard.ROOT
MODS = os.path.join(ROOT, "mods")
ALL_MODS = sorted(d for d in os.listdir(MODS) if os.path.isdir(os.path.join(MODS, d)))
OB_MODS = [d for d in ALL_MODS if d.startswith("ob-")]
with open(os.path.join(ROOT, "keys", "vaultr-keys.json"), encoding="utf-8") as f:
    KEYS = json.load(f)


def tracked():
    """Tracked plus untracked, non-ignored files in the repo; the plain tree when this is not a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, check=True,
        ).stdout
        return [os.path.join(ROOT, p) for p in out.decode().split("\0") if p and os.path.isfile(os.path.join(ROOT, p))]
    except (OSError, subprocess.CalledProcessError):
        found = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "node_modules")]
            found += [os.path.join(d, f) for f in files]
        return found


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def suffix(paths, *ends):
    return [p for p in paths if p.endswith(ends)]


# Words too common to mean a person: a machine that happens to be named after one is not flagged. `runner` is the
# login name on GitHub's hosted runners, where this suite runs for every pull request.
COMMON = {"claude", "local", "localhost", "laptop", "server", "desktop", "sandbox", "machine", "runner"}


def personal_words():
    """The login name, this machine's host name and the Herdr machines' names and hosts, read now (never stored)."""
    import pwd
    words = set()
    try:
        entry = pwd.getpwuid(os.getuid())
        words.add(entry.pw_name)
        real_home = entry.pw_dir
    except (KeyError, OSError):
        real_home = None
    words.add(socket.gethostname().split(".")[0])
    hc = shutil.which("hc")
    if hc and real_home:
        try:
            out = subprocess.run([hc, "machine", "ls", "--json"], capture_output=True, text=True, timeout=10,
                                 env=dict(os.environ, HOME=real_home)).stdout
            for m in json.loads(out).get("machines", []):
                for k in ("name", "host"):
                    if isinstance(m.get(k), str):
                        words.add(m[k].split(".")[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    login = entry.pw_name if real_home else None
    # 3+ letters (a short machine name is still a name); the login name at any length.
    return sorted(w for w in words if w and w.lower() not in COMMON and (len(w) >= 3 or w == login))


class Repo(unittest.TestCase):
    def test_every_mod_has_manifest_and_entry(self):
        for m in ALL_MODS:
            with self.subTest(mod=m):
                manifest = os.path.join(MODS, m, "mod.json")
                self.assertTrue(os.path.isfile(manifest), "no mod.json")
                with open(manifest) as f:
                    data = json.load(f)
                self.assertTrue(os.path.isfile(os.path.join(MODS, m, "main.js")), "no main.js")
                for icon in re.findall(r'"(mods/[^"]+\.svg)"', json.dumps(data)):
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, icon)), f"missing icon {icon}")

    def test_kit_copies_match_kit(self):
        # kit/sync.sh writes kit.js with its MOD name filled in, provider.js, agents.js, follow_target.js, fuzzy.js, and the icons: all byte-exact
        kit = read("kit/kit.js")
        icons = os.listdir(os.path.join(ROOT, "kit", "icons"))
        self.assertTrue(icons)
        for m in OB_MODS:
            with self.subTest(mod=m):
                want = re.sub(r'(?m)^export const MOD = "__MOD__";',
                              f'export const MOD = "{m}";', kit).encode("utf-8")
                with open(os.path.join(MODS, m, "kit.js"), "rb") as f:
                    self.assertEqual(f.read(), want, "run kit/sync.sh; never edit a mod's kit.js")
                with open(os.path.join(ROOT, "kit", "agents.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "agents.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "agents.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "names.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "names.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "names.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "hidden.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "hidden.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "hidden.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "attention.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "attention.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "attention.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "follow_target.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "follow_target.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "follow_target.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "feed_age.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "feed_age.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "feed_age.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "ticker.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "ticker.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "ticker.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "fuzzy.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "fuzzy.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "fuzzy.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "touches.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "touches.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "touches.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "lights.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "lights.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "lights.js: run kit/sync.sh; never edit a mod's copy")
                with open(os.path.join(ROOT, "kit", "provider.js"), "rb") as a, \
                        open(os.path.join(MODS, m, "provider.js"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), "provider.js: run kit/sync.sh; never edit a mod's copy")
                for name in icons:
                    with open(os.path.join(ROOT, "kit", "icons", name), "rb") as a, \
                            open(os.path.join(MODS, m, "icons", name), "rb") as b:
                        self.assertEqual(a.read(), b.read(), f"icons/{name}")
        for m in ("ob-graph", "ob-outline", "ob-props"):
            with open(os.path.join(ROOT, "kit", "obc.js"), "rb") as a, \
                    open(os.path.join(MODS, m, "obc.js"), "rb") as b:
                self.assertEqual(a.read(), b.read(), f"{m}/obc.js: run kit/sync.sh; never edit a mod's copy")

    def test_kit_imports_what_it_reexports_and_uses(self):
        # `export { x } from "./y.js"` does not bind x in kit.js: a kit function that calls x throws "x is not defined".
        with open(os.path.join(ROOT, "kit", "kit.js"), encoding="utf-8") as f:
            src = f.read()
        reexported, imported = set(), set()
        for kind, names in re.findall(r"^(export|import)\s*\{([^}]*)\}\s*from", src, re.M):
            (reexported if kind == "export" else imported).update(n.strip() for n in names.split(",") if n.strip())
        body = "\n".join(l for l in src.splitlines() if not re.match(r"\s*(export|import)\s*\{", l)
                         and not l.lstrip().startswith("//"))
        for name in sorted(reexported - imported):
            self.assertIsNone(re.search(rf"\b{name}\(", body), f"kit.js calls {name} but only re-exports it")

    @unittest.skipUnless(shutil.which("node"), "node is not installed: skipping the JS syntax check")
    def test_js_parses(self):
        # Mods are ES modules. A copy named .mjs is checked as one; `node --check` only parses, it runs nothing.
        js = suffix(tracked(), ".js", ".mjs")
        self.assertTrue(js)
        with tempfile.TemporaryDirectory() as tmp:
            for i, path in enumerate(js):
                copy = os.path.join(tmp, f"m{i}.mjs")
                shutil.copy(path, copy)
                p = subprocess.run(["node", "--check", copy], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, f"{os.path.relpath(path, ROOT)}: {p.stderr.strip()}")

    def test_untracked_non_ignored_js_file_is_included_in_parse_check(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            with open(os.path.join(tmp, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("ignored.js\n")
            with open(os.path.join(tmp, "staged.js"), "w", encoding="utf-8") as f:
                f.write("export const ok = 1;\n")
            subprocess.run(["git", "-C", tmp, "add", ".gitignore", "staged.js"], check=True)
            untracked_ok = os.path.join(tmp, "mods", "ob-new", "main.js")
            os.makedirs(os.path.dirname(untracked_ok), exist_ok=True)
            with open(untracked_ok, "w", encoding="utf-8") as f:
                f.write("export const fresh = 2;\n")
            ignored = os.path.join(tmp, "ignored.js")
            with open(ignored, "w", encoding="utf-8") as f:
                f.write("this is not valid js;\n")
            with mock.patch(f"{__name__}.ROOT", tmp):
                walked = suffix(tracked(), ".js", ".mjs")
                self.assertIn(untracked_ok, walked)
                self.assertIn(os.path.join(tmp, "staged.js"), walked)
                self.assertNotIn(ignored, walked)
                if shutil.which("node"):
                    self.test_js_parses()
                    with open(untracked_ok, "w", encoding="utf-8") as f:
                        f.write("export const = ;\n")
                    with self.assertRaises(AssertionError):
                        self.test_js_parses()

    def test_shell_parses(self):
        for path in suffix(tracked(), ".sh"):
            with self.subTest(file=os.path.relpath(path, ROOT)):
                p = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_python_compiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, path in enumerate(suffix(tracked(), ".py")):
                with self.subTest(file=os.path.relpath(path, ROOT)):
                    py_compile.compile(path, cfile=os.path.join(tmp, f"{i}.pyc"), doraise=True)

    def test_nothing_personal_is_tracked(self):
        # Paths into a person's home, and names read at run time so they are written nowhere: the login name, this
        # machine's host name and the person's Herdr machines (`hc machine ls`, names and hosts of 3+ letters).
        # Tracked and untracked non-ignored files are checked.
        patterns = [rb"/home/[A-Za-z][A-Za-z0-9._-]*", rb"/Users/[A-Za-z][A-Za-z0-9._-]*"]
        for word in personal_words():
            patterns.append(rb"(?i)(?<![A-Za-z0-9_-])" + re.escape(word.encode()) + rb"(?![A-Za-z0-9_-])")
        bad = []
        for path in tracked():
            if path.endswith((".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf")):
                continue
            with open(path, "rb") as f:
                data = f.read()
            for pat in patterns:
                for m in re.finditer(pat, data):
                    bad.append(f"{os.path.relpath(path, ROOT)}: {m.group(0).decode(errors='replace')}")
        self.assertEqual(bad, [])

    def test_the_login_name_of_a_hosted_runner_is_not_personal(self):
        # GitHub's hosted runners log in as `runner`, a word that tests and fixtures may use.
        entry = mock.Mock(pw_name="runner", pw_dir=ROOT)
        with mock.patch("pwd.getpwuid", return_value=entry), mock.patch("shutil.which", return_value=None):
            self.assertNotIn("runner", personal_words())

    @staticmethod
    def _layout_ids():
        with open(os.path.join(ROOT, "layouts", "vaultr.json"), encoding="utf-8") as f:
            root = json.load(f)
        node_ids = set()
        stack_children = set()

        def walk(node):
            if isinstance(node, dict):
                if "id" in node:
                    node_ids.add(node["id"])
                if node.get("type") == "stack":
                    for child in node.get("children") or []:
                        if isinstance(child, dict) and "id" in child:
                            stack_children.add(child["id"])
                for child in node.get("children") or []:
                    walk(child)

        walk(root)
        return node_ids, stack_children

    @staticmethod
    def _target_error(command, node_ids, stack_children, mods):
        head, _, arg = command.partition(":")
        verb = head.split(".")[0]
        if verb.startswith("ob-") and verb not in mods:
            return f"{command}: unknown mod {verb}"
        if head == "mod.open" and arg not in mods:
            return f"{command}: unknown mod {arg}"
        if head in ("ob-tabs.open", "ob-tabs.toggle"):
            target = arg.split("@", 1)[0]
            if target not in stack_children:
                return f"{command}: {target!r} is not a stack child id in layouts/vaultr.json"
        if head == "layout.toggle" and arg not in node_ids:
            return f"{command}: {arg!r} is not a node id in layouts/vaultr.json"
        return None

    def test_keys_name_mods_that_exist(self):
        node_ids, stack_children = self._layout_ids()
        for ctx, binds in KEYS.items():
            self.assertIsInstance(binds, dict, ctx)
            if ctx.startswith("mod:"):
                self.assertIn(ctx[4:], ALL_MODS, ctx)
            for key, command in binds.items():
                with self.subTest(key=key, command=command):
                    self.assertIsNone(self._target_error(command, node_ids, stack_children, ALL_MODS))

    def test_view_and_layout_target_rule_accepts_non_ob_views_and_rejects_unknown_ids(self):
        node_ids, stack_children = self._layout_ids()
        for view_id in ("ob-notes", "ob-files", "ob-changes", "ob-insights"):
            self.assertIsNone(self._target_error(f"ob-tabs.open:{view_id}", node_ids, stack_children, ALL_MODS))
            self.assertIsNone(self._target_error(f"ob-tabs.toggle:{view_id}@x", node_ids, stack_children, ALL_MODS))
        self.assertIsNotNone(self._target_error("ob-tabs.open:ob-missing", node_ids, stack_children, ALL_MODS))
        self.assertIsNotNone(self._target_error("ob-tabs.toggle:ob-missing", node_ids, stack_children, ALL_MODS))
        self.assertIsNotNone(self._target_error("layout.toggle:ob-missing", node_ids, stack_children, ALL_MODS))
        self.assertIsNotNone(self._target_error("mod.open:ob-missing", node_ids, stack_children, ALL_MODS))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_hotkeys_ob_and_palette_commands_name_valid_targets(self):
        node_ids, stack_children = self._layout_ids()
        with tempfile.TemporaryDirectory(prefix="ob-targets-") as folder:
            src_dir = os.path.join(ROOT, "mods", "ob-settings")
            for name in os.listdir(src_dir):
                if name.endswith(".js"):
                    txt = Path(src_dir, name).read_text(encoding="utf-8").replace('from "herdr"', 'from "./herdr.js"')
                    Path(folder, name).write_text(txt, encoding="utf-8")
            Path(folder, "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
            Path(folder, "herdr.js").write_text(
                'export const keys = () => [];\nexport const commands = () => [];\n'
                'export const window = () => ({ platform: "linux" });\n',
                encoding="utf-8",
            )
            code = (
                f'import {{ registry }} from "{Path(folder, "registry.js").as_uri()}";\n'
                f'import {{ VAULTR_COMMANDS }} from "{Path(ROOT, "mods", "ob-switcher", "commands.js").as_uri()}";\n'
                'const ob = registry().filter((r) => r.group === "Vaultr layout").map((r) => r.action);\n'
                'const pal = VAULTR_COMMANDS.map((c) => c.route);\n'
                'process.stdout.write(JSON.stringify({ ob, pal }));\n'
            )
            res = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(res.stdout)
        self.assertTrue(data["ob"])
        self.assertTrue(data["pal"])
        for source, cmds in (("OB", data["ob"]), ("VAULTR_COMMANDS", data["pal"])):
            for command in cmds:
                with self.subTest(source=source, command=command):
                    self.assertIsNone(self._target_error(command, node_ids, stack_children, ALL_MODS))

    def test_install_merges_every_keys_section(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as base:
            repo = os.path.join(base, "repo")
            app = os.path.join(base, "herdr-app")
            os.makedirs(os.path.join(repo, "keys"))
            os.makedirs(app)
            shutil.copy(os.path.join(ROOT, "install.sh"), os.path.join(repo, "install.sh"))
            keys_data = json.loads(json.dumps(KEYS))
            keys_data["mod:ob-extra"] = {"ctrl-alt-x": "ob-extra.ping"}
            with open(os.path.join(repo, "keys", "vaultr-keys.json"), "w", encoding="utf-8") as f:
                json.dump(keys_data, f)
            with open(os.path.join(app, "keys.json"), "w", encoding="utf-8") as f:
                json.dump({"global": {"ctrl-k": "mine.open"}}, f)
            env = dict(os.environ, HERDR_APP_HOME=app, VAULTR_OS="Linux")
            p1 = subprocess.run(["bash", os.path.join(repo, "install.sh")], capture_output=True, text=True,
                                env=env, cwd=repo, stdin=subprocess.DEVNULL)
            self.assertEqual(p1.returncode, 0, p1.stdout + p1.stderr)
            with open(os.path.join(app, "keys.json"), encoding="utf-8") as f:
                installed = json.load(f)
            with open(os.path.join(app, "vaultr-keys.owned.json"), encoding="utf-8") as f:
                owned = json.load(f)
            self.assertEqual(installed["layout:vaultr"], keys_data["layout:vaultr"])
            self.assertEqual(installed["mod:ob-sessions"], keys_data["mod:ob-sessions"])
            self.assertEqual(installed["mod:ob-extra"], {"ctrl-alt-x": "ob-extra.ping"})
            self.assertEqual(owned["mod:ob-extra"], ["ctrl-alt-x"])
            installed["mod:ob-extra"]["ctrl-m"] = "mine.extra"
            with open(os.path.join(app, "keys.json"), "w", encoding="utf-8") as f:
                json.dump(installed, f)
            p2 = subprocess.run(["bash", os.path.join(repo, "install.sh"), "--uninstall"], capture_output=True,
                                text=True, env=env, cwd=repo, stdin=subprocess.DEVNULL)
            self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
            with open(os.path.join(app, "keys.json"), encoding="utf-8") as f:
                after = json.load(f)
            self.assertNotIn("layout:vaultr", after)
            self.assertNotIn("mod:ob-sessions", after)
            self.assertEqual(after["mod:ob-extra"], {"ctrl-m": "mine.extra"})
            self.assertEqual(after["global"], {"ctrl-k": "mine.open"})
            self.assertFalse(os.path.exists(os.path.join(app, "vaultr-keys.owned.json")))

    def test_install_names_mods_that_exist(self):
        install = read("install.sh")
        extra = re.search(r'^EXTRA_MODS="([^"]*)"', install, re.M)
        self.assertIsNotNone(extra)
        for name in extra.group(1).split():
            self.assertIn(name, ALL_MODS)

    def test_origin_names_the_shipped_extras(self):
        text = read("mods/ORIGIN.md")
        self.assertIn("insights", text)
        self.assertIn("obsidian", text)

    def test_notice_and_herdr_license(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "LICENSE-herdr")))
        notice_path = os.path.join(ROOT, "NOTICE")
        self.assertTrue(os.path.isfile(notice_path))
        with open(notice_path, encoding="utf-8") as f:
            notice = f.read()
        self.assertIn("Some of Vaultr's mods", notice)
        section = notice.split("Some of Vaultr's mods", 1)[1].split("\n\n", 1)[0]
        paths = []
        for line in section.splitlines():
            if line.startswith("- "):
                paths.extend(re.findall(r"mods/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", line))
        self.assertTrue(paths)
        self.assertIn("mods/ob-settings/registry_rules.js", paths)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "LICENSE-shepherdr")))
        with open(os.path.join(ROOT, "LICENSE-shepherdr"), encoding="utf-8") as f:
            lic_sh = f.read()
        self.assertIn("MIT License", lic_sh)
        self.assertIn("Copyright (c) 2026 Elias Stravik", lic_sh)
        self.assertIn("Shepherdr", notice)
        self.assertIn("mods/ob-feed/providers/claude/quota.py", notice)
        self.assertIn("mods/tasks/bin/herdr_task/machine.py", notice)
        self.assertIn("LICENSE-shepherdr", notice)
        for line in notice.splitlines():
            if line.startswith("- ") and "Shepherdr's" in line:
                first_path = re.findall(r"mods/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", line)[0]
                paths.append(first_path)
        with open(os.path.join(ROOT, "mods/ob-feed/providers/claude/quota.py"), encoding="utf-8") as f:
            quota_hdr = "\n".join(f.read().splitlines()[:6])
        self.assertIn("Shepherdr", quota_hdr)
        self.assertIn("mods/tasks/bin/herdr_task/machine.py", quota_hdr)
        self.assertIn("LICENSE-shepherdr", quota_hdr)
        for rel in paths:
            with self.subTest(path=rel):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), f"missing {rel} named in NOTICE")

    def test_no_dangling_spec_or_architect_references(self):
        pat = rb"SPEC\.md|SPEC[ ]section|\bSPEC\s+(?:[0-9]|U4)|Ask[ ]the[ ]architect|\$[S]/"
        removed_scripts = rb"\b(?:scan_pi|transcript_search|transcript|usage)\.py\b|test_scan_pi\.py"
        bad = []
        for path in tracked():
            if path.endswith((".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf")):
                continue
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, "rb") as f:
                data = f.read()
            for m in re.finditer(pat, data):
                bad.append(f"{rel}: {m.group(0).decode(errors='replace')}")
            for m in re.finditer(removed_scripts, data):
                bad.append(f"{rel}: {m.group(0).decode(errors='replace')}")
        self.assertEqual(bad, [])

    def test_every_on_mouse_down_names_its_button(self):
        with self.subTest("no prototype patch"):
            self.assertNotIn("__patched_mouse_down", read("kit/kit.js"))
        pat = re.compile(r"""\.on_mouse_down\(\s*(?!(?:"left"|"right"|"middle"|'left'|'right'|'middle')\s*,)""")
        bad = []
        for path in suffix(tracked(), ".js", ".mjs"):
            rel = os.path.relpath(path, ROOT)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            for m in pat.finditer(src):
                lineno = src.count("\n", 0, m.start()) + 1
                bad.append(f"{rel}:{lineno}")
        with self.subTest("explicit button"):
            self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
