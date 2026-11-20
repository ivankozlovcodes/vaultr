"""Tests for mods/ob-feed/providers/antigravity: boundary, identity, SQLite titles, and transcripts."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import ast
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(home_guard.ROOT)
PROVIDERS_DIR = ROOT / "mods" / "ob-feed" / "providers"
AGY_DIR = PROVIDERS_DIR / "antigravity"
PROVIDER_JS = ROOT / "kit" / "provider.js"
FIXTURE_TX = ROOT / "test" / "fixtures" / "providers" / "antigravity" / "transcript.jsonl"
CLAUDE_TX = ROOT / "test" / "fixtures" / "providers" / "claude" / "session.jsonl"
PI_TX = ROOT / "test" / "fixtures" / "providers" / "pi" / "session.jsonl"
NODE = shutil.which("node")

CID_1 = "11111111-2222-3333-4444-555555555555"
CID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_reader():
    ns = {}
    exec(compile(_read_text(AGY_DIR / "reader.py"), str(AGY_DIR / "reader.py"), "exec"), ns)
    return ns


def _assemble(mode):
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot run kit/provider.js")
    with open(PROVIDERS_DIR / "index.json", encoding="utf-8") as f:
        programs = json.load(f)
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
    res = subprocess.run([NODE, "--input-type=module", "-e", js], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise AssertionError(res.stderr.strip() or "provider.js failed")
    return res.stdout


def _run_py(script_text, args, home):
    env = dict(os.environ, HOME=str(home))
    res = subprocess.run(
        [sys.executable, "-I", "-c", script_text, *[str(a) for a in args]],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    if res.returncode != 0:
        raise AssertionError(f"python3 exited {res.returncode}: {res.stderr.strip()[-400:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def _make_summaries_db(db_path, rows):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE conversation_summaries "
            "(conversation_id TEXT PRIMARY KEY, title TEXT, last_modified_time TEXT)"
        )
        for cid, title, modified in rows:
            conn.execute(
                "INSERT INTO conversation_summaries (conversation_id, title, last_modified_time) VALUES (?, ?, ?)",
                (cid, title, modified),
            )
        conn.commit()
    finally:
        conn.close()


def _write_fake_proc(proc_root, pid, comm, argv, term, cwd, fd_targets=()):
    pdir = Path(proc_root, str(pid))
    (pdir / "fd").mkdir(parents=True)
    with open(pdir / "comm", "w", encoding="utf-8") as f:
        f.write(comm + "\n")
    with open(pdir / "cmdline", "wb") as f:
        f.write(b"\0".join(a.encode("utf-8") for a in argv) + b"\0")
    with open(pdir / "environ", "wb") as f:
        f.write(f"PATH=/usr/bin\0HC_TERMINAL_ID={term}\0".encode("utf-8"))
    os.symlink(cwd, pdir / "cwd")
    for idx, target in enumerate(fd_targets, start=3):
        os.symlink(target, pdir / "fd" / str(idx))


class AntigravityBoundaries(unittest.TestCase):
    def test_reads_only_dot_gemini_antigravity_cli_with_no_overrides_or_labels(self):
        manifest = json.loads(_read_text(AGY_DIR / "manifest.json"))
        self.assertEqual(manifest, {
            "id": "antigravity",
            "name": "Antigravity",
            "noun": "Antigravity agent",
            "caps": ["title", "transcript"],
        })

        allowed_dots = {".gemini", ".system_generated"}
        slash_dot = re.compile(r"/(\.[A-Za-z0-9_-]+)")
        quoted_dot = re.compile(r"""(["'])(\.[A-Za-z0-9_-]+)\1""")
        str_dot = re.compile(r"(?:^|/)(\.[A-Za-z0-9_-]+)")
        for p in sorted(AGY_DIR.iterdir()):
            if not p.is_file():
                continue
            src = _read_text(p)
            with self.subTest(file=p.name):
                found = set(slash_dot.findall(src))
                found.update(m[1] for m in quoted_dot.findall(src))
                if p.suffix == ".py":
                    for node in ast.walk(ast.parse(src)):
                        if isinstance(node, ast.Constant) and isinstance(node.value, str):
                            found.update(str_dot.findall(node.value))
                self.assertTrue(found.issubset(allowed_dots), f"unexpected dot-folder token(s) in {p.name}: {sorted(found)}")
                self.assertNotIn("os.environ", src)
                self.assertNotIn("getenv", src)
                self.assertNotIn("label", src.lower())
                self.assertNotIn("conversations", src)
        scan_src = _read_text(AGY_DIR / "scan.py")
        self.assertIn('os.path.join(HOME, ".gemini", "antigravity-cli")', scan_src)
        self.assertNotIn("OPT.get", scan_src.replace('OPT.get("fds")', ""))


class AntigravityIdentityAndTitles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agy-scan-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.agy = self.home / ".gemini" / "antigravity-cli"
        (self.agy / "presence").mkdir(parents=True)
        self.scanner = _assemble("scan")

    def test_agy_and_antigravity_without_presence_lock_yield_zero_rows(self):
        other_lock = self.root / "elsewhere" / "presence" / f"{CID_1}.lock"
        other_lock.parent.mkdir(parents=True)
        with open(other_lock, "wb"):
            pass
        bad_name = self.agy / "presence" / "not-a-uuid.lock"
        with open(bad_name, "wb"):
            pass

        # 1) procs fixture without fds or with lock outside ~/.gemini/antigravity-cli/presence/
        res_procs = _run_py(self.scanner, [json.dumps({
            "procs": [
                {"pid": 900001, "term": "tagy1", "comm": "agy", "cwd": "/srv/work"},
                {"pid": 900002, "term": "tagy2", "comm": "antigravity", "cwd": "/srv/work", "fds": [str(other_lock)]},
                {"pid": 900003, "term": "tagy3", "comm": "agy", "cwd": "/srv/work", "fds": [str(bad_name)]},
            ],
        })], self.home)
        self.assertEqual(res_procs["terms"], {})

        # 2) Linux procRoot without presence lock
        proc_dir = self.root / "proc"
        _write_fake_proc(proc_dir, 900004, "agy", ["agy"], "tagy4", "/srv/work", fd_targets=[str(other_lock)])
        _write_fake_proc(proc_dir, 900005, "antigravity", ["antigravity"], "tagy5", "/srv/work", fd_targets=[])
        res_proc = _run_py(self.scanner, [json.dumps({"procRoot": str(proc_dir)})], self.home)
        self.assertEqual(res_proc["terms"], {})

        # 3) macOS psOutput without matching presence lock in lsof
        ps_out = {
            "list": "\n".join([
                "  900006 Sat Nov 14 10:41:08 2026 agy             agy",
                "  900007 Sat Nov 14 10:41:08 2026 antigravity     /usr/local/bin/antigravity",
                "",
            ]),
            "env": "\n".join([
                "900006 agy HC_TERMINAL_ID=tagy6",
                "900007 antigravity HC_TERMINAL_ID=tagy7",
            ]),
            "cwd": "p900006\nfcwd\nn/srv/work\np900007\nfcwd\nn/srv/work\n",
            "lsof": f"p900006\nf3\nn{other_lock}\np900007\nf3\nn{bad_name}\n",
        }
        res_ps = _run_py(self.scanner, [json.dumps({"psOutput": ps_out})], self.home)
        self.assertEqual(res_ps["terms"], {})

    def test_sqlite_title_updated_at_and_transcript_via_proc_lsof_and_open_fd(self):
        modified_iso = "2026-11-18 12:34:56.250000000 +00:00"
        expected_ms = int(datetime.datetime(2026, 11, 18, 12, 34, 56, 250000, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        _make_summaries_db(self.agy / "conversation_summaries.db", [
            (CID_1, "Investigate port mismatch", modified_iso),
            (CID_2, "macOS session title", "2026-11-18T13:00:00Z"),
        ])
        tx1 = self.agy / "brain" / CID_1 / ".system_generated" / "logs" / "transcript.jsonl"
        tx1.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE_TX, tx1)
        lock1 = self.agy / "presence" / f"{CID_1}.lock"
        lock2 = self.agy / "presence" / f"{CID_2}.lock"
        with open(lock1, "wb"), open(lock2, "wb"):
            pass

        # A) Real open lock fd held by current process (works on Linux /proc/<pid>/fd and macOS lsof)
        with open(lock1, "rb"):
            res_live = _run_py(self.scanner, [json.dumps({
                "procs": [{"pid": os.getpid(), "term": "tagy_live", "comm": "agy", "cwd": "/srv/work"}],
            })], self.home)
        self.assertEqual(res_live["errors"], [])
        row_live = res_live["terms"]["tagy_live"]
        self.assertEqual(row_live["provider"], "antigravity")
        self.assertEqual(row_live["name"], "Investigate port mismatch")
        self.assertEqual(row_live["session"], CID_1)
        self.assertEqual(row_live["transcript"], str(tx1))
        self.assertEqual(row_live["updatedAt"], expected_ms)

        # B) Linux procRoot symlink fd
        proc_dir = self.root / "proc"
        _write_fake_proc(proc_dir, 910001, "antigravity", ["antigravity"], "tagy_linux", "/srv/linux", fd_targets=[str(lock1)])
        res_linux = _run_py(self.scanner, [json.dumps({"procRoot": str(proc_dir)})], self.home)
        row_linux = res_linux["terms"]["tagy_linux"]
        self.assertEqual(row_linux["provider"], "antigravity")
        self.assertEqual(row_linux["name"], "Investigate port mismatch")
        self.assertEqual(row_linux["session"], CID_1)
        self.assertEqual(row_linux["transcript"], str(tx1))
        self.assertEqual(row_linux["updatedAt"], expected_ms)

        # C) macOS psOutput + lsof (CID_2 has no transcript.jsonl yet -> transcript is None)
        expected_ms_2 = int(datetime.datetime(2026, 11, 18, 13, 0, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        ps_out = {
            "list": "  920001 Sat Nov 14 10:41:08 2026 agy             /usr/local/bin/agy\n",
            "env": "920001 agy HC_TERMINAL_ID=tagy_mac\n",
            "cwd": "p920001\nfcwd\nn/srv/mac\n",
            "lsof": f"p920001\nf0\nn/dev/ttys001\nf4\nn{lock2}\n",
        }
        res_mac = _run_py(self.scanner, [json.dumps({"psOutput": ps_out})], self.home)
        row_mac = res_mac["terms"]["tagy_mac"]
        self.assertEqual(row_mac["provider"], "antigravity")
        self.assertEqual(row_mac["name"], "macOS session title")
        self.assertEqual(row_mac["session"], CID_2)
        self.assertIsNone(row_mac["transcript"])
        self.assertEqual(row_mac["updatedAt"], expected_ms_2)

        # D) Node-wrapped agy command with open lock confirms; unrelated node binary does not
        res_node = _run_py(self.scanner, [json.dumps({
            "procs": [
                {"pid": 930001, "term": "tnode_agy", "comm": "node", "cwd": "/srv/work", "args": ["node", "/usr/local/bin/agy"], "fds": [str(lock1)]},
                {"pid": 930002, "term": "tnode_other", "comm": "node", "cwd": "/srv/work", "args": ["node", "/usr/local/bin/other"], "fds": [str(lock1)]},
            ],
        })], self.home)
        self.assertEqual(sorted(res_node["terms"].keys()), ["tnode_agy"])

    def test_missing_or_corrupt_summaries_db_falls_back_cleanly(self):
        tx1 = self.agy / "brain" / CID_1 / ".system_generated" / "logs" / "transcript.jsonl"
        tx1.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE_TX, tx1)
        os.utime(tx1, (1700000123, 1700000123))
        lock1 = self.agy / "presence" / f"{CID_1}.lock"
        with open(lock1, "wb"):
            pass

        # No DB yet -> name=None, updatedAt=transcript mtime ms
        res_no_db = _run_py(self.scanner, [json.dumps({
            "procs": [{"pid": 940001, "term": "t_nodb", "comm": "agy", "cwd": "/srv/work", "fds": [str(lock1)]}],
        })], self.home)
        self.assertEqual(res_no_db["errors"], [])
        row = res_no_db["terms"]["t_nodb"]
        self.assertIsNone(row["name"])
        self.assertEqual(row["transcript"], str(tx1))
        self.assertEqual(row["updatedAt"], 1700000123000)

        # Corrupt DB -> still no crash or scanner error
        with open(self.agy / "conversation_summaries.db", "wb") as f:
            f.write(b"not a sqlite database")
        res_bad_db = _run_py(self.scanner, [json.dumps({
            "procs": [{"pid": 940002, "term": "t_baddb", "comm": "agy", "cwd": "/srv/work", "fds": [str(lock1)]}],
        })], self.home)
        self.assertEqual(res_bad_db["errors"], [])
        self.assertIsNone(res_bad_db["terms"]["t_baddb"]["name"])
        self.assertEqual(res_bad_db["terms"]["t_baddb"]["updatedAt"], 1700000123000)


class AntigravityReaderUnitTests(unittest.TestCase):
    def test_results_attach_in_call_order_and_generic_never_becomes_assistant(self):
        ns = _load_reader()
        records = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-18T10:00:00Z",
                "thinking": "Run three steps.",
                "content": "",
                "tool_calls": [
                    {"name": "read_file", "args": {"Path": "/srv/a.txt"}},
                    {"name": "run_command", "args": {"CommandLine": "check-b"}},
                    {"name": "write_file", "args": {"Path": "/srv/c.txt"}},
                ],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:01Z",
                "content": "contents of a",
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:02Z",
                "content": "check-b failed",
                "error": "exit status 2",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:03Z",
                "content": "wrote /srv/c.txt",
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:04Z",
                "content": "trailing model note with nothing pending " + ("x" * 220),
            },
        ]
        evs = ns["events"](records)
        self.assertEqual([e["k"] for e in evs], ["tool", "tool", "tool", "meta"])
        self.assertNotIn("assistant", [e["k"] for e in evs])
        self.assertEqual(evs[0]["tool"], "read_file")
        self.assertEqual(evs[0]["args"], "/srv/a.txt")
        self.assertEqual(evs[0]["result"], "contents of a")
        self.assertFalse(evs[0]["error"])
        self.assertEqual(evs[1]["tool"], "run_command")
        self.assertEqual(evs[1]["args"], "check-b")
        self.assertEqual(evs[1]["result"], "check-b failed")
        self.assertTrue(evs[1]["error"])
        self.assertEqual(evs[2]["tool"], "write_file")
        self.assertEqual(evs[2]["args"], "/srv/c.txt")
        self.assertEqual(evs[2]["result"], "wrote /srv/c.txt")
        self.assertFalse(evs[2]["error"])
        self.assertLessEqual(len(evs[3]["text"]), 200)

    def test_call_without_result_stays_open_at_eof_and_after_new_turn_or_planner(self):
        ns = _load_reader()
        records = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-18T10:00:00Z",
                "content": "",
                "tool_calls": [
                    {"name": "read_file", "args": {"Path": "/srv/first.txt"}},
                    {"name": "read_file", "args": {"Path": "/srv/unanswered_before_user.txt"}},
                ],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:01Z",
                "content": "first result",
            },
            {
                "step_index": 2,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-18T10:00:02Z",
                "content": "Interrupt and switch target.",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-18T10:00:03Z",
                "content": "",
                "tool_calls": [{"name": "edit_file", "args": {"Path": "/srv/unanswered_before_planner.txt"}}],
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-18T10:00:04Z",
                "content": "",
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "make check"}},
                    {"name": "run_command", "args": {"CommandLine": "make lint"}},
                ],
            },
            {
                "step_index": 5,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:05Z",
                "content": "make check ok",
            },
        ]
        evs = ns["events"](records)
        tools = [e for e in evs if e["k"] == "tool"]
        self.assertEqual(len(tools), 5)
        self.assertEqual(tools[0]["result"], "first result")
        self.assertNotIn("result", tools[1])
        self.assertNotIn("result", tools[2])
        self.assertEqual(tools[3]["args"], "make check")
        self.assertEqual(tools[3]["result"], "make check ok")
        self.assertNotIn("result", tools[4])

    def test_system_message_clipping_error_message_checkpoint_and_id_fallback(self):
        ns = _load_reader()
        records = [
            {
                "step_index": 0,
                "source": "SYSTEM",
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-18T10:00:00Z",
                "content": "notice: " + ("z" * 240),
            },
            {
                "step_index": 1,
                "source": "SYSTEM",
                "type": "ERROR_MESSAGE",
                "created_at": "2026-11-18T10:00:01Z",
                "error": "upstream deadline exceeded",
            },
            {
                "step_index": 2,
                "source": "SYSTEM",
                "type": "CHECKPOINT",
                "created_at": "2026-11-18T10:00:02Z",
                "content": "checkpoint marker",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-18T10:00:03Z",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "read_file", "args": {"Path": "/srv/one"}},
                    {"id": "c2", "name": "read_file", "args": {"Path": "/srv/two"}},
                ],
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:04Z",
                "tool_call_id": "c2",
                "content": "result two",
            },
            {
                "step_index": 5,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-18T10:00:05Z",
                "tool_call_id": "c1",
                "content": "result one",
            },
        ]
        evs = ns["events"](records)
        self.assertEqual([e["k"] for e in evs], ["meta", "meta", "tool", "tool"])
        self.assertEqual(len(evs[0]["text"]), 200)
        self.assertNotIn("error", evs[0])
        self.assertEqual(evs[1]["text"], "upstream deadline exceeded")
        self.assertTrue(evs[1].get("error"))
        self.assertEqual(evs[2]["result"], "result one")
        self.assertEqual(evs[3]["result"], "result two")


@unittest.skipUnless(NODE, "node is not installed: cannot test kit/provider.js")
class AntigravityTranscriptAndFacade(unittest.TestCase):
    def test_provider_transcript_and_caps_over_twelve_record_synthetic_transcript(self):
        with tempfile.TemporaryDirectory(prefix="agy-tx-") as tmp:
            tx_path = Path(tmp) / "transcript.jsonl"
            shutil.copyfile(FIXTURE_TX, tx_path)
            with open(tx_path, encoding="utf-8") as f:
                raw_lines = [ln for ln in f if ln.strip()]
            self.assertEqual(len(raw_lines), 12)
            raw_records = [json.loads(ln) for ln in raw_lines]

            ns = _load_reader()
            direct_evs = ns["events"](raw_records)
            self.assertEqual(
                [e["k"] for e in direct_evs],
                ["user", "assistant", "tool", "tool", "meta", "tool", "meta", "tool", "assistant"],
            )
            self.assertNotIn("error", direct_evs[4])
            self.assertTrue(direct_evs[6].get("error"))
            self.assertEqual(direct_evs[6]["text"], "Transient telemetry upload timeout")

            with open(AGY_DIR / "manifest.json", encoding="utf-8") as f:
                manifest = json.load(f)

            js = (
                'import fs from "node:fs";\n'
                'import { execFileSync } from "node:child_process";\n'
                f'import {{ makeProvider }} from {json.dumps(PROVIDER_JS.as_uri())};\n'
                'const readTextFile = async (p) => fs.readFileSync(p, "utf8");\n'
                'const exec = async (cmd, args) => {\n'
                '  const stdout = execFileSync(cmd, args, { encoding: "utf8" });\n'
                '  return { code: 0, stdout, stderr: "" };\n'
                '};\n'
                'const feed = {\n'
                '  v: 2,\n'
                f'  providers: {{ antigravity: {json.dumps(manifest)} }},\n'
                '  terms: {\n'
                f'    tagy1: {{ provider: "antigravity", name: "Port check", session: {json.dumps(CID_1)}, transcript: {json.dumps(str(tx_path))}, updatedAt: 1700000000000 }},\n'
                '  },\n'
                '};\n'
                'const p = makeProvider({ feed: () => feed, exec, readTextFile, appHome: () => ' + json.dumps(str(ROOT)) + ' });\n'
                'const sess = p.session("tagy1");\n'
                'const cap = p.of("antigravity");\n'
                'const tx = await p.transcript("tagy1");\n'
                'const usg = await p.usage("tagy1");\n'
                'const qt = await p.quota();\n'
                'console.log(JSON.stringify({\n'
                '  title: sess.title,\n'
                '  prompts: sess.prompts,\n'
                '  caps: cap.caps,\n'
                '  canTitle: cap.can("title"),\n'
                '  canTx: cap.can("transcript"),\n'
                '  canUsage: cap.can("usage"),\n'
                '  tx,\n'
                '  usg,\n'
                '  qt,\n'
                '}));\n'
            )
            res = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            got = json.loads(res.stdout)

            self.assertEqual(got["title"], "Port check")
            self.assertEqual(got["prompts"], [])
            self.assertEqual(got["caps"], ["title", "transcript"])
            self.assertTrue(got["canTitle"])
            self.assertTrue(got["canTx"])
            self.assertFalse(got["canUsage"])
            self.assertEqual(got["usg"]["reason"], "unsupported")
            self.assertEqual(got["qt"]["reason"], "unsupported")

            tx = got["tx"]
            self.assertTrue(tx["ok"])
            self.assertEqual(tx["format"], "antigravity")
            entries = tx["entries"]
            self.assertEqual(
                [e["k"] for e in entries],
                ["user", "assistant", "tool", "tool", "meta", "tool", "meta", "tool", "assistant"],
            )
            self.assertEqual(entries[0]["text"], "Check service config and verify port 8443.")
            self.assertNotIn("Inspect config.json and run the port suite.", json.dumps(entries))
            self.assertNotIn("checkpoint 8", json.dumps(entries))
            self.assertEqual(entries[2]["tool"], "read_file")
            self.assertEqual(entries[2]["args"], "/srv/app/config.json")
            self.assertEqual(entries[2]["result"], '{"port":8080}')
            self.assertFalse(entries[2]["error"])
            self.assertEqual(entries[3]["tool"], "run_command")
            self.assertEqual(entries[3]["args"], "pytest -q tests/test_port.py")
            self.assertTrue(entries[3]["error"])
            self.assertIn("expected 8443", entries[3]["result"])
            self.assertEqual(entries[4]["text"], "Workspace file watcher reloaded configuration.")
            self.assertEqual(entries[5]["tool"], "edit_file")
            self.assertEqual(entries[5]["result"], "Edited /srv/app/config.json")
            self.assertFalse(entries[5]["error"])
            self.assertEqual(entries[6]["text"], "Transient telemetry upload timeout")
            self.assertEqual(entries[7]["tool"], "run_command")
            self.assertEqual(entries[7]["result"], "2 passed in 0.08s")
            self.assertFalse(entries[7]["error"])
            self.assertEqual(entries[-1]["text"], "Updated port to 8443 and all port checks pass.")

    def test_sniff_ignores_claude_and_pi_records(self):
        ns = _load_reader()
        for path in (CLAUDE_TX, PI_TX):
            recs = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        recs.append(json.loads(line))
            with self.subTest(fixture=path.name):
                self.assertIsNone(ns["sniff"](recs))


if __name__ == "__main__":
    unittest.main()
