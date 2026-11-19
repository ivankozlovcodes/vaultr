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

ROOT = home_guard.ROOT
MODS = os.path.join(ROOT, "mods")
ALL_MODS = sorted(d for d in os.listdir(MODS) if os.path.isdir(os.path.join(MODS, d)))
OB_MODS = [d for d in ALL_MODS if d.startswith("ob-")]
with open(os.path.join(ROOT, "keys", "vaultr-keys.json"), encoding="utf-8") as f:
    KEYS = json.load(f)


def tracked():
    """Files git tracks (what the repo ships); the plain tree when this is not a git checkout."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout
        return [os.path.join(ROOT, p) for p in out.decode().split("\0") if p]
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


# Words too common to mean a person: a machine that happens to be named after one is not flagged.
COMMON = {"claude", "local", "localhost", "laptop", "server", "desktop", "sandbox", "machine"}


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
        # kit/sync.sh writes kit.js with its MOD name filled in, agents.js, follow_target.js, fuzzy.js, the icons and (for ob-feed) scan_pi.py: all byte-exact
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
                for name in icons:
                    with open(os.path.join(ROOT, "kit", "icons", name), "rb") as a, \
                            open(os.path.join(MODS, m, "icons", name), "rb") as b:
                        self.assertEqual(a.read(), b.read(), f"icons/{name}")
        for m in ("ob-graph", "ob-outline", "ob-props"):
            with open(os.path.join(ROOT, "kit", "obc.js"), "rb") as a, \
                    open(os.path.join(MODS, m, "obc.js"), "rb") as b:
                self.assertEqual(a.read(), b.read(), f"{m}/obc.js: run kit/sync.sh; never edit a mod's copy")
        with open(os.path.join(ROOT, "kit", "scan_pi.py"), "rb") as a, \
                open(os.path.join(MODS, "ob-feed", "scan_pi.py"), "rb") as b:
            self.assertEqual(a.read(), b.read(), "ob-feed/scan_pi.py")

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
        # Only files git tracks are checked.
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

    def test_keys_name_mods_that_exist(self):
        for ctx, binds in KEYS.items():
            self.assertIsInstance(binds, dict, ctx)
            if ctx.startswith("mod:"):
                self.assertIn(ctx[4:], ALL_MODS, ctx)
            for key, command in binds.items():
                with self.subTest(key=key, command=command):
                    head, _, arg = command.partition(":")
                    verb = head.split(".")[0]
                    if verb.startswith("ob-"):
                        self.assertIn(verb, ALL_MODS)
                    if head == "mod.open":
                        self.assertIn(arg, ALL_MODS)
                    if head.split(".")[0] == "ob-tabs" and head.split(".")[1:] and head.split(".")[1] in ("open", "toggle"):
                        self.assertIn(arg.split("@")[0], ALL_MODS)

    def test_install_merges_every_keys_section(self):
        # install.sh copies only the sections it names: a section it doesn't name would never reach keys.json
        install = read("install.sh")
        merged = re.search(r'for k in \(([^)]*)\):\n\s*if k in vaultr_keys', install)
        self.assertIsNotNone(merged, "install.sh's keys merge loop was not found")
        names = re.findall(r'"([^"]+)"', merged.group(1))
        self.assertEqual(sorted(names), sorted(KEYS))

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
        for rel in paths:
            with self.subTest(path=rel):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), f"missing {rel} named in NOTICE")

    def test_no_dangling_spec_or_architect_references(self):
        pat = rb"SPEC\.md|SPEC[ ]section|\bSPEC\s+(?:[0-9]|U4)|Ask[ ]the[ ]architect|\$[S]/"
        bad = []
        for path in tracked():
            if path.endswith((".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf")):
                continue
            with open(path, "rb") as f:
                data = f.read()
            for m in re.finditer(pat, data):
                bad.append(f"{os.path.relpath(path, ROOT)}: {m.group(0).decode(errors='replace')}")
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
