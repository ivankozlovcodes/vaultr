"""Conformance rules for mods/ob-feed/providers/ folders, manifests, snippets, and kit/provider.js."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import ast
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
import unittest
from pathlib import Path

ROOT = Path(home_guard.ROOT)
PROVIDERS_DIR = ROOT / "mods" / "ob-feed" / "providers"
FIXTURES_DIR = ROOT / "test" / "fixtures" / "providers"
PROVIDER_JS = ROOT / "kit" / "provider.js"
NODE = shutil.which("node")

EXACT_MANIFEST_KEYS = {"id", "name", "noun", "caps"}
ALLOWED_CAPS = {"title", "prompts", "transcript", "usage", "search", "touches", "subagents", "quota"}
CAP_FILE = {
    "title": "scan.py",
    "prompts": "scan.py",
    "touches": "scan.py",
    "subagents": "scan.py",
    "transcript": "reader.py",
    "usage": "reader.py",
    "search": "reader.py",
    "quota": "quota.py",
}
ALLOWED_EVENT_KINDS = {"user", "assistant", "tool", "meta"}
READER_MODES = ("entries", "usage", "search")
SIZE_BUDGET = 100 * 1024


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _index_ids():
    with open(PROVIDERS_DIR / "index.json", encoding="utf-8") as f:
        return json.load(f)


def _folder_ids():
    return sorted(
        p.name for p in PROVIDERS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"
    )


def _find_multiline_string_tokens(src):
    # kit/provider.js indents non-empty snippet lines inside a wrapper function, which silently alters continuation
    # lines inside multi-line string literals.
    hits = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
            hits.append((tok.start[0], tok.end[0]))
    return hits


def _assemble(mode):
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot run kit/provider.js")
    programs = _index_ids()
    payload = {"providersDir": str(PROVIDERS_DIR), "mode": mode, "programs": programs}
    js = (
        'import fs from "node:fs";\n'
        'import path from "node:path";\n'
        f'import * as P from {json.dumps(PROVIDER_JS.as_uri())};\n'
        'const cfg = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'const read = (p) => fs.readFileSync(p, "utf8");\n'
        'if (cfg.mode === "scan") {\n'
        '  const progs = cfg.programs\n'
        '    .filter((id) => fs.existsSync(path.join(cfg.providersDir, id, "scan.py")))\n'
        '    .map((id) => ({\n'
        '      id,\n'
        '      reader: fs.existsSync(path.join(cfg.providersDir, id, "reader.py")) ? read(path.join(cfg.providersDir, id, "reader.py")) : null,\n'
        '      scan: read(path.join(cfg.providersDir, id, "scan.py")),\n'
        '    }));\n'
        '  process.stdout.write(P.assembleScanner(read(path.join(cfg.providersDir, "scan_core.py")), progs));\n'
        '} else {\n'
        '  const readers = cfg.programs\n'
        '    .filter((id) => fs.existsSync(path.join(cfg.providersDir, id, "reader.py")))\n'
        '    .map((id) => ({\n'
        '      id,\n'
        '      reader: read(path.join(cfg.providersDir, id, "reader.py")),\n'
        '    }));\n'
        '  process.stdout.write(P.assembleReader(read(path.join(cfg.providersDir, "reader_main.py")), readers, cfg.mode));\n'
        '}\n'
    )
    out = subprocess.run(
        [NODE, "--input-type=module", "-e", js],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "provider.js failed")
    return out.stdout


class ProviderFoldersConformance(unittest.TestCase):
    def test_index_matches_exact_set_of_provider_folders(self):
        ids = _index_ids()
        folders = _folder_ids()
        self.assertIsInstance(ids, list)
        self.assertTrue(ids, "index.json must list at least one provider")
        self.assertTrue(all(isinstance(x, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", x) for x in ids))
        self.assertEqual(len(ids), len(set(ids)), "index.json must not repeat provider ids")
        self.assertEqual(set(ids), set(folders), "index.json must equal the exact set of provider folders")

    def test_every_provider_folder_satisfies_manifest_and_cap_rules(self):
        ids = _index_ids()
        for pid in ids:
            with self.subTest(provider=pid):
                pdir = PROVIDERS_DIR / pid
                manifest_path = pdir / "manifest.json"
                self.assertTrue(manifest_path.is_file(), f"missing {manifest_path}")
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)

                self.assertEqual(set(manifest.keys()), EXACT_MANIFEST_KEYS)
                self.assertEqual(manifest["id"], pid)
                self.assertIsInstance(manifest["name"], str)
                self.assertTrue(manifest["name"].strip())
                self.assertIsInstance(manifest["noun"], str)
                self.assertTrue(manifest["noun"].strip())

                caps = manifest["caps"]
                self.assertIsInstance(caps, list)
                self.assertTrue(caps, f"{pid}: caps must be non-empty")
                self.assertEqual(len(caps), len(set(caps)), f"{pid}: duplicate entries in caps")
                for cap in caps:
                    self.assertIn(cap, ALLOWED_CAPS, f"{pid}: unknown cap {cap!r}")
                    req = pdir / CAP_FILE[cap]
                    self.assertTrue(req.is_file(), f"{pid}: cap {cap!r} requires {req.name}")

                quota_path = pdir / "quota.py"
                self.assertEqual(quota_path.is_file(), "quota" in caps,
                                 f"{pid}: quota.py must exist if and only if 'quota' is in caps")

                if "prompts" in caps:
                    reader_path = pdir / "reader.py"
                    self.assertTrue(reader_path.is_file(), f"{pid}: prompts cap requires reader.py")
                    reader_src = _read_text(reader_path)
                    scan_src = _read_text(pdir / "scan.py")
                    self.assertIn("turn_group", reader_src, f"{pid}: reader.py must mark turn_group for prompts")
                    self.assertIn("user_turns_from_events(", scan_src,
                                  f"{pid}: scan.py must derive prompts via user_turns_from_events(evs)")
                    for forbidden in (
                        "_user_turns",
                        "collect_turns",
                        "isMeta",
                        "<system-reminder>",
                        "<local-command",
                        "recordType",
                        "tool_result",
                    ):
                        self.assertNotIn(forbidden, scan_src,
                                         f"{pid}: scan.py must not parse transcript records for prompts ({forbidden})")

    def test_core_drivers_name_no_provider_id_or_name(self):
        tokens = set()
        for pid in _index_ids():
            with open(PROVIDERS_DIR / pid / "manifest.json", encoding="utf-8") as f:
                m = json.load(f)
            tokens.add(m["id"])
            tokens.add(m["name"])
        for driver in ("scan_core.py", "reader_main.py"):
            src = _read_text(PROVIDERS_DIR / driver)
            for tok in sorted(tokens):
                with self.subTest(driver=driver, token=tok):
                    m = re.search(rf"\b{re.escape(tok)}\b", src, re.I)
                    self.assertIsNone(m, f"{driver} must not name provider {tok!r}")

    def test_snippets_compile_as_python_39_and_pass_tokenize_guard(self):
        for pid in _index_ids():
            pdir = PROVIDERS_DIR / pid
            for py_path in sorted(pdir.glob("*.py")):
                with self.subTest(provider=pid, file=py_path.name):
                    src = _read_text(py_path)
                    compile(src, str(py_path), "exec")
                    ast.parse(src, filename=str(py_path), feature_version=(3, 9))
                    list(tokenize.generate_tokens(io.StringIO(src).readline))
                    hits = _find_multiline_string_tokens(src)
                    self.assertEqual(
                        hits,
                        [],
                        f"{py_path}: multi-line string literal(s) at lines {hits} would break indentation during assembly",
                    )

    def test_multiline_string_detector_catches_multiline_literal(self):
        hits = _find_multiline_string_tokens('x = """a\nb"""\n')
        self.assertEqual(hits, [(1, 2)])

    def test_assembled_scanner_registers_every_provider(self):
        script = _assemble("scan")
        lines = script.rstrip().splitlines()
        self.assertEqual(lines[-1], "run_scanner_main()")
        setup_code = "\n".join(lines[:-1]) + "\n"
        ns = {}
        saved_argv = sys.argv
        sys.argv = [saved_argv[0], json.dumps({"procs": []})]
        try:
            exec(compile(setup_code, "<assembled-scanner>", "exec"), ns)
        finally:
            sys.argv = saved_argv
        for pid in _index_ids():
            with self.subTest(provider=pid):
                if (PROVIDERS_DIR / pid / "scan.py").is_file():
                    self.assertIn(pid, ns["PROVIDER_BY_ID"])
                    spec = ns["PROVIDER_BY_ID"][pid]
                    self.assertTrue(callable(spec.get("match")))
                    self.assertTrue(callable(spec.get("confirm")))
                    self.assertTrue(callable(spec.get("sessions")))
                if (PROVIDERS_DIR / pid / "reader.py").is_file():
                    self.assertIn(pid, ns["READERS"])

    def test_readers_decode_all_provider_fixtures_into_normalized_events(self):
        for pid in _index_ids():
            fdir = FIXTURES_DIR / pid
            if not fdir.is_dir():
                continue
            fixtures = sorted(fdir.glob("*.jsonl"))
            self.assertTrue(fixtures, f"expected JSONL fixtures in {fdir}")
            reader_src = _read_text(PROVIDERS_DIR / pid / "reader.py")
            ns = {}
            exec(compile(reader_src, str(PROVIDERS_DIR / pid / "reader.py"), "exec"), ns)
            for fx in fixtures:
                with self.subTest(provider=pid, fixture=fx.name):
                    records = []
                    with open(fx, encoding="utf-8") as f:
                        for raw in f:
                            raw = raw.strip()
                            if raw:
                                records.append(json.loads(raw))
                    fmt = ns["sniff"](records)
                    self.assertIsInstance(fmt, str)
                    self.assertTrue(fmt)
                    evs = list(ns["events"](records))
                    self.assertTrue(evs, f"no normalized events from {fx}")
                    for ev in evs:
                        self.assertIsInstance(ev, dict)
                        self.assertIn(ev.get("k"), ALLOWED_EVENT_KINDS)


class AssembledBudgetsAndSyntax(unittest.TestCase):
    def test_core_files_parse_as_python_39_and_tokenize(self):
        for name in ("scan_core.py", "reader_main.py"):
            path = PROVIDERS_DIR / name
            src = _read_text(path)
            ast.parse(src, filename=str(path), feature_version=(3, 9))
            list(tokenize.generate_tokens(io.StringIO(src).readline))

    def test_assembled_scanner_and_readers_parse_as_python_39_within_100_kib(self):
        scanner = _assemble("scan")
        ast.parse(scanner, filename="<assembled-scanner>", feature_version=(3, 9))
        list(tokenize.generate_tokens(io.StringIO(scanner).readline))
        self.assertLess(len(scanner.encode("utf-8")), SIZE_BUDGET)
        for mode in READER_MODES:
            with self.subTest(mode=mode):
                reader = _assemble(mode)
                ast.parse(reader, filename=f"<assembled-{mode}>", feature_version=(3, 9))
                list(tokenize.generate_tokens(io.StringIO(reader).readline))
                self.assertLess(len(reader.encode("utf-8")), SIZE_BUDGET)


@unittest.skipUnless(NODE, "node is not installed: cannot run kit/provider.js")
class ProviderLoaderIndexContract(unittest.TestCase):
    def test_provider_js_has_no_ls_exec_or_fallback_list(self):
        src = _read_text(PROVIDER_JS)
        self.assertNotIn('exec("ls"', src)
        self.assertNotIn("exec('ls'", src)
        self.assertNotIn("fallback", src)
        for pid in _index_ids():
            self.assertNotRegex(src, rf"\b{re.escape(pid)}\b")

    def test_load_providers_reads_index_only_and_fails_cleanly_without_fallback(self):
        js = (
            f'import * as P from {json.dumps(PROVIDER_JS.as_uri())};\n'
            'const cases = [];\n'
            'const runCase = async (name, files) => {\n'
            '  const reads = [];\n'
            '  const readTextFile = async (p) => {\n'
            '    reads.push(p);\n'
            '    if (!(p in files)) throw new Error("ENOENT: " + p);\n'
            '    return files[p];\n'
            '  };\n'
            '  try {\n'
            '    const res = await P.loadProviders({ readTextFile, providersDir: "/fake/providers", needScan: true, needManifest: true });\n'
            '    cases.push({ name, ok: true, ids: res.map((x) => x.id), reads });\n'
            '  } catch (e) {\n'
            '    cases.push({ name, ok: false, error: String(e?.message ?? e), reads });\n'
            '  }\n'
            '};\n'
            'await runCase("missing_index", {});\n'
            'await runCase("bad_json", { "/fake/providers/index.json": "{" });\n'
            'await runCase("non_array", { "/fake/providers/index.json": "{\\"id\\":\\"alpha\\"}" });\n'
            'await runCase("bad_id", { "/fake/providers/index.json": "[\\"../bad\\"]" });\n'
            'await runCase("valid", {\n'
            '  "/fake/providers/index.json": "[\\"beta\\",\\"alpha\\"]",\n'
            '  "/fake/providers/beta/manifest.json": "{\\"id\\":\\"beta\\",\\"name\\":\\"Beta\\",\\"noun\\":\\"beta\\",\\"caps\\":[\\"touches\\"]}",\n'
            '  "/fake/providers/beta/scan.py": "pass",\n'
            '  "/fake/providers/alpha/manifest.json": "{\\"id\\":\\"alpha\\",\\"name\\":\\"Alpha\\",\\"noun\\":\\"alpha\\",\\"caps\\":[\\"touches\\"]}",\n'
            '  "/fake/providers/alpha/scan.py": "pass"\n'
            '});\n'
            'console.log(JSON.stringify(cases));\n'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        by_name = {c["name"]: c for c in json.loads(out.stdout)}

        for bad in ("missing_index", "bad_json", "non_array", "bad_id"):
            with self.subTest(case=bad):
                self.assertFalse(by_name[bad]["ok"])
                self.assertEqual(by_name[bad]["reads"], ["/fake/providers/index.json"])
        self.assertTrue(by_name["valid"]["ok"])
        self.assertEqual(by_name["valid"]["ids"], ["beta", "alpha"])


if __name__ == "__main__":
    unittest.main()
