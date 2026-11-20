"""Pinned-output contract tests for the four agent-transcript consumers (scanner, viewer, usage, search).

Each test runs the assembled script built by kit/provider.js with `python3 -I -c <text> ...`. Additive
`"provider"` keys are stripped before comparing against the pinned JSON snapshots in
test/fixtures/providers/pinned_expected.json.
"""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
PROVIDERS_DIR = Path(ROOT, "mods", "ob-feed", "providers")
PROVIDER_JS = Path(ROOT, "kit", "provider.js")
NODE = shutil.which("node")

FIXTURES = Path(ROOT, "test", "fixtures")
PROVIDER_FIX = FIXTURES / "providers"
PROPS_CLAUDE = FIXTURES / "ob-props" / "claude-session.jsonl"
PROPS_PI = FIXTURES / "ob-props" / "pi-session.jsonl"
CLAUDE_SESSION = PROVIDER_FIX / "claude" / "session.jsonl"
CLAUDE_SUBAGENT = PROVIDER_FIX / "claude" / "subagent.jsonl"
PI_SESSION = PROVIDER_FIX / "pi" / "session.jsonl"
PI_SUBAGENT_TX = PROVIDER_FIX / "pi" / "subagent_transcript.jsonl"
EXPECTED_PATH = PROVIDER_FIX / "pinned_expected.json"

CLAUDE_PID = 10000001
PI_GUESS_PID = 10000002
NORMALIZED_PI_PID = 7701


def _assembled_script(mode):
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot assemble provider scripts")
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
        '      reader: read(path.join(cfg.providersDir, id, "reader.py")),\n'
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
    out = subprocess.run([NODE, "--input-type=module", "-e", js], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "provider.js failed")
    return out.stdout


def _run_python_script(script_text, args, env=None):
    run_env = {**os.environ, **env} if env else None
    out = subprocess.run(
        [sys.executable, "-I", "-c", script_text, *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=run_env,
    )
    if out.returncode != 0:
        raise AssertionError(f"python3 exited {out.returncode}: {out.stderr.strip()[-400:]}")
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"empty stdout; stderr={out.stderr.strip()[-400:]}")
    return json.loads(lines[-1])


def run_scanner(opts, env=None):
    return _run_python_script(_assembled_script("scan"), [json.dumps(opts)], env=env)


def run_viewer(args, env=None):
    return _run_python_script(_assembled_script("entries"), [str(a) for a in args], env=env)


def run_usage(args, env=None):
    return _run_python_script(_assembled_script("usage"), [str(a) for a in args], env=env)


def run_search(opts, env=None):
    return _run_python_script(_assembled_script("search"), [json.dumps(opts)], env=env)


def strip_additive_provider(obj):
    """Recursively strip ONLY `"provider"` keys from dicts/lists so additive fields do not break pinned checks."""
    if isinstance(obj, list):
        return [strip_additive_provider(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_additive_provider(v) for k, v in obj.items() if k != "provider"}
    return obj


def _replace_roots(obj, replacements):
    if isinstance(obj, list):
        return [_replace_roots(x, replacements) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_roots(v, replacements) for k, v in obj.items()}
    if isinstance(obj, str):
        for src, dst in replacements:
            obj = obj.replace(src, dst)
        return obj
    return obj


def build_scanner_fixture(base_dir):
    """Populate a self-contained Claude Code + pi + artifact-store + async-subagent-runs fixture home."""
    fix = Path(base_dir)
    home = fix / "home"
    pi_tmp = fix / "pi-tmp"
    runs_dir = pi_tmp / "async-subagent-runs"
    store = fix / "artifact-store"

    claude_sess_dir = home / ".claude" / "sessions"
    claude_proj = home / ".claude" / "projects" / "proj-work"
    claude_sub = claude_proj / "claude-sess-01" / "subagents"
    pi_owned_dir = home / ".pi" / "agent" / "sessions" / "--srv-work-studio--"
    pi_guess_dir = home / ".pi" / "agent" / "sessions" / "--srv-work-studio-guess--"
    for d in (claude_sess_dir, claude_sub, pi_owned_dir, pi_guess_dir, runs_dir, store):
        d.mkdir(parents=True, exist_ok=True)

    with open(claude_sess_dir / f"{CLAUDE_PID}.json", "w", encoding="utf-8") as f:
        json.dump({"pid": CLAUDE_PID, "sessionId": "claude-sess-01", "cwd": "/srv/work", "name": "Build check"}, f)

    claude_main = claude_proj / "claude-sess-01.jsonl"
    shutil.copyfile(CLAUDE_SESSION, claude_main)
    os.utime(claude_main, (1700000200, 1700000200))

    done_meta = claude_sub / "agent-done01.meta.json"
    done_jsonl = claude_sub / "agent-done01.jsonl"
    with open(done_meta, "w", encoding="utf-8") as f:
        json.dump({"agentType": "code-review", "description": "Inspect helper module",
                   "model": "claude-haiku-4-5", "finished": True}, f)
    shutil.copyfile(CLAUDE_SUBAGENT, done_jsonl)
    os.utime(done_meta, (1700000100, 1700000100))
    os.utime(done_jsonl, (1700000100, 1700000100))

    live_meta = claude_sub / "agent-live01.meta.json"
    live_jsonl = claude_sub / "agent-live01.jsonl"
    with open(live_meta, "w", encoding="utf-8") as f:
        json.dump({"agentType": "Explore", "description": "Scan test suite",
                   "model": "claude-haiku-4-5", "finished": False}, f)
    live_lines = [
        {"type": "user", "uuid": "lu1", "sessionId": "claude-sess-01", "timestamp": "2026-04-01T10:01:00.000Z",
         "message": {"role": "user", "content": "Check test suite files"}},
        {"type": "assistant", "uuid": "la1", "timestamp": "2026-04-01T10:01:01.000Z",
         "message": {"id": "msg_l1", "model": "claude-haiku-4-5", "role": "assistant",
                     "content": [{"type": "tool_use", "id": "tu_l1", "name": "Read",
                                  "input": {"file_path": "/srv/work/tests/test_app.py"}}],
                     "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 42}}},
    ]
    with open(live_jsonl, "w", encoding="utf-8") as f:
        for row in live_lines:
            f.write(json.dumps(row) + "\n")
    now_s = time.time()
    os.utime(live_jsonl, (now_s, now_s))
    os.utime(live_meta, (now_s + 1, now_s + 1))

    with open(store / "work.json", "w", encoding="utf-8") as f:
        json.dump({
            "folder": "/srv/work",
            "artifacts": [{
                "id": "cov-report-01",
                "title": "Coverage summary",
                "versions": [
                    {"v": 1, "at": 1775037615000, "publisher": "tcl1"},
                    {"v": 2, "at": 1775037620000, "publisher": "tcl1"},
                ],
            }],
        }, f)

    pi_sess_owned = pi_owned_dir / "2026-04-02T08-00-00-000Z_s1.jsonl"
    shutil.copyfile(PI_SESSION, pi_sess_owned)
    pi_sess_guess = pi_guess_dir / "2026-04-02T08-00-00-000Z_s2.jsonl"
    shutil.copyfile(PI_SESSION, pi_sess_guess)
    os.utime(pi_sess_guess, (1775116800, 1775116800))

    pi_pid = os.getpid()

    live_run_dir = runs_dir / "run-live-01"
    live_child_dir = runs_dir / "run-live-01-child"
    done_run_dir = runs_dir / "run-done-01"
    for d in (live_run_dir, live_child_dir, done_run_dir):
        d.mkdir(parents=True, exist_ok=True)

    live_step_sess = live_run_dir / "step-0-session.jsonl"
    live_step_tx = live_run_dir / "step-0-transcript.jsonl"
    shutil.copyfile(PI_SESSION, live_step_sess)
    shutil.copyfile(PI_SUBAGENT_TX, live_step_tx)
    with open(live_run_dir / "output-0.log", "w", encoding="utf-8") as f:
        f.write("running step 0\n")
    with open(live_child_dir / "status.json", "w", encoding="utf-8") as f:
        json.dump({
            "runId": "run-live-01-child",
            "parentWorkflowRunId": "run-live-01",
            "steps": [{"model": "anthropic/claude-sonnet-4-5", "turnCount": 2, "toolCount": 3}],
        }, f)
    with open(live_run_dir / "status.json", "w", encoding="utf-8") as f:
        json.dump({
            "runId": "run-live-01",
            "mode": "chain",
            "state": "running",
            "pid": pi_pid,
            "startedAt": 1775116800000,
            "lastUpdate": 1775116850000,
            "cwd": "/srv/work/studio",
            "sessionId": str(pi_sess_owned),
            "completionOwnerProcess": {"pid": pi_pid},
            "outputFile": str(live_run_dir / "output-0.log"),
            "currentStep": 0,
            "totalTokens": {"total": 1250},
            "totalCost": {"costUsd": 0.0125},
            "turnCount": 2,
            "toolCount": 3,
            "steps": [{
                "agent": "scout",
                "label": "audit",
                "sessionName": "scout: Audit studio config",
                "status": "running",
                "model": "anthropic/claude-sonnet-4-5",
                "startedAt": 1775116800000,
                "tokens": {"total": 1250},
                "totalCost": {"costUsd": 0.0125},
                "turnCount": 2,
                "toolCount": 3,
                "recentTools": [{"tool": "read", "args": "/srv/work/studio/studio.json", "endMs": 1775116820000}],
                "recentOutput": ["Checking studio.json"],
                "sessionFile": str(live_step_sess),
                "transcriptPath": str(live_step_tx),
                "runId": "run-live-01-child",
            }],
        }, f)

    done_step_sess = done_run_dir / "done-session.jsonl"
    done_step_tx = done_run_dir / "done-transcript.jsonl"
    shutil.copyfile(PI_SESSION, done_step_sess)
    shutil.copyfile(PI_SUBAGENT_TX, done_step_tx)
    with open(done_run_dir / "status.json", "w", encoding="utf-8") as f:
        json.dump({
            "runId": "run-done-01",
            "mode": "single",
            "state": "complete",
            "startedAt": 1775116000000,
            "endedAt": 1775116100000,
            "lastUpdate": 1775116100000,
            "cwd": "/srv/work/studio",
            "sessionId": str(pi_sess_owned),
            "completionOwnerProcess": {"pid": 10000099},
            "currentStep": 0,
            "totalTokens": {"total": 820},
            "totalCost": {"costUsd": 0.008},
            "turnCount": 1,
            "toolCount": 2,
            "error": "minor lint warning",
            "steps": [{
                "agent": "builder",
                "label": "verify",
                "description": "Verify build artifact",
                "status": "complete",
                "model": "anthropic/claude-haiku-4-5",
                "startedAt": 1775116000000,
                "endedAt": 1775116100000,
                "tokens": {"total": 820},
                "totalCost": {"costUsd": 0.008},
                "turnCount": 1,
                "toolCount": 2,
                "recentTools": [{"tool": "edit", "args": "/srv/work/studio/studio.json", "endMs": 1775116050000}],
                "recentOutput": ["Studio port updated to 8443"],
                "sessionFile": str(done_step_sess),
                "transcriptPath": str(done_step_tx),
            }],
        }, f)

    opts = {
        "claude": True,
        "claudeHome": str(home),
        "piHome": str(home),
        "artifactStore": str(store),
        "maxAgeH": 1000000,
        "limit": 40,
        "procs": [
            {
                "pid": CLAUDE_PID,
                "term": "tcl1",
                "comm": "claude",
                "cwd": "/srv/work",
                "args": ["claude", "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js"],
            },
            {
                "pid": pi_pid,
                "term": "tpi1",
                "comm": "pi",
                "cwd": "/srv/work/studio",
                "start": 1775116700000,
                "args": ["node", "/usr/local/lib/node_modules/@mariozechner/pi-coding-agent/dist/cli.js"],
            },
            {
                "pid": PI_GUESS_PID,
                "term": "tpi2",
                "comm": "pi",
                "cwd": "/srv/work/studio-guess",
                "start": 1775116700000,
                "args": ["node", "/usr/local/lib/node_modules/@mariozechner/pi-coding-agent/dist/cli.js"],
            },
        ],
    }
    return opts, {"PI_SUBAGENTS_TEMP_ROOT": str(pi_tmp)}, fix, pi_pid


def normalize_scanner(raw, fix_dir, pi_pid):
    data = strip_additive_provider(raw)
    now = data.get("now")
    data = _replace_roots(data, [(str(fix_dir), "<FIXTURE>"), (str(ROOT), "<REPO>")])
    data["host"] = "<HOST>" if data.get("host") == socket.gethostname() else data.get("host")
    data["uid"] = "<UID>" if data.get("uid") == os.getuid() else data.get("uid")
    data["now"] = "<NOW>" if isinstance(now, int) else now
    data["ms"] = "<MS>" if isinstance(data.get("ms"), int) and data["ms"] >= 0 else data.get("ms")
    for r in data.get("runs") or []:
        if r.get("ownerPid") == pi_pid:
            r["ownerPid"] = NORMALIZED_PI_PID
    for t in (data.get("terms") or {}).values():
        if t.get("pid") == pi_pid:
            t["pid"] = NORMALIZED_PI_PID
        for a in t.get("agents") or []:
            if a.get("id") == "live01" and isinstance(a.get("updatedAt"), int) and isinstance(now, int):
                if abs(now - a["updatedAt"]) < 60_000:
                    a["updatedAt"] = "<LIVE_MTIME>"
    return data


def normalize_viewer(raw, tmp_dir=None):
    data = strip_additive_provider(raw)
    reps = [(str(ROOT), "<REPO>")]
    if tmp_dir is not None:
        reps.insert(0, (str(tmp_dir), "<TMP>"))
    return _replace_roots(data, reps)


def normalize_usage(raw):
    data = strip_additive_provider(raw)
    if "sig" in data and "size" in data and re.fullmatch(rf"{data['size']}:\d+", str(data["sig"])):
        data["sig"] = "<SIG>"
    return data


def normalize_search(raw, tmp_dir=None):
    data = strip_additive_provider(raw)
    if isinstance(data.get("ms"), int) and data["ms"] >= 0:
        data["ms"] = "<MS>"
    reps = [(str(ROOT), "<REPO>")]
    if tmp_dir is not None:
        reps.insert(0, (str(tmp_dir), "<TMP>"))
    return _replace_roots(data, reps)


class PinnedContracts(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        with open(EXPECTED_PATH, encoding="utf-8") as f:
            cls.expected = json.load(f)

    def test_strip_additive_provider_only_strips_provider_keys(self):
        sample = {"v": 1, "provider": "claude", "terms": {"t1": {"kind": "claude", "provider": "claude", "agents": [{"id": "a1", "provider": "claude"}]}}}
        self.assertEqual(strip_additive_provider(sample), {"v": 1, "terms": {"t1": {"kind": "claude", "agents": [{"id": "a1"}]}}})

    def test_scanner_pinned_output(self):
        with tempfile.TemporaryDirectory(prefix="providers-scan-") as tmp:
            opts, env, fix_dir, pi_pid = build_scanner_fixture(tmp)
            raw = run_scanner(opts, env=env)
            self.assertEqual(raw["errors"], [])
            actual = normalize_scanner(raw, fix_dir, pi_pid)
            self.assertEqual(actual, self.expected["scanner"])

    def test_viewer_pinned_outputs(self):
        cases = {
            "props_claude": PROPS_CLAUDE,
            "props_pi": PROPS_PI,
            "claude_session": CLAUDE_SESSION,
            "claude_subagent": CLAUDE_SUBAGENT,
            "pi_session": PI_SESSION,
            "pi_subagent_transcript": PI_SUBAGENT_TX,
        }
        for name, path in cases.items():
            with self.subTest(case=name):
                actual = normalize_viewer(run_viewer([path]))
                self.assertEqual(actual, self.expected["viewer"][name])

    def test_viewer_max_truncation_missing_and_find(self):
        with self.subTest("max_cap"):
            actual = normalize_viewer(run_viewer([CLAUDE_SESSION, "3"]))
            self.assertEqual(actual, self.expected["viewer"]["claude_session_max3"])

        with tempfile.TemporaryDirectory(prefix="providers-view-") as tmp:
            tmp_path = Path(tmp)
            with self.subTest("missing_file"):
                missing = tmp_path / "missing.jsonl"
                actual = normalize_viewer(run_viewer([missing]), tmp_dir=tmp_path)
                self.assertEqual(actual, self.expected["viewer"]["missing"])

            with self.subTest("find_agent"):
                old_dir = tmp_path / ".claude" / "projects" / "proj-old" / "s0" / "subagents"
                new_dir = tmp_path / ".claude" / "projects" / "proj-new" / "s1" / "subagents"
                old_dir.mkdir(parents=True)
                new_dir.mkdir(parents=True)
                old_hit = old_dir / "agent-find01.jsonl"
                new_hit = new_dir / "agent-find01.jsonl"
                with open(old_hit, "w", encoding="utf-8") as f:
                    f.write("{}\n")
                with open(new_hit, "w", encoding="utf-8") as f:
                    f.write("{}\n")
                os.utime(old_hit, (1700000000, 1700000000))
                os.utime(new_hit, (1700000500, 1700000500))
                found = normalize_viewer(run_viewer(["--find", "find01"], env={"HOME": str(tmp_path)}), tmp_dir=tmp_path)
                self.assertEqual(found, self.expected["viewer"]["find_hit"])
                bad = normalize_viewer(run_viewer(["--find", "../bad"], env={"HOME": str(tmp_path)}), tmp_dir=tmp_path)
                self.assertEqual(bad, {"path": None})

    def test_usage_pinned_outputs(self):
        cases = {
            "props_claude": PROPS_CLAUDE,
            "props_pi": PROPS_PI,
            "claude_session": CLAUDE_SESSION,
            "pi_session": PI_SESSION,
        }
        for name, path in cases.items():
            with self.subTest(case=name):
                raw = run_usage([path])
                self.assertEqual(normalize_usage(raw), self.expected["usage"][name])
                unchanged = run_usage([path, "", raw["sig"]])
                self.assertEqual(unchanged, {"unchanged": True, "sig": raw["sig"]})

        with tempfile.TemporaryDirectory(prefix="providers-usage-") as tmp:
            missing = Path(tmp) / "no-such-session.jsonl"
            self.assertEqual(run_usage([missing]), self.expected["usage"]["missing"])

    def test_search_pinned_outputs(self):
        files = [
            {"id": "claude-main", "path": str(CLAUDE_SESSION)},
            {"id": "claude-sub", "path": str(CLAUDE_SUBAGENT)},
            {"id": "pi-sess", "path": str(PI_SESSION)},
            {"id": "pi-sub", "path": str(PI_SUBAGENT_TX)},
        ]
        with self.subTest("batch_case_insensitive"):
            raw = run_search({"terms": ["lighthousebeacon"], "files": files})
            self.assertEqual(normalize_search(raw), self.expected["search"]["batch_insensitive"])

        with self.subTest("case_sensitive"):
            raw_miss = run_search({"terms": ["lighthousebeacon"], "caseSensitive": True, "files": files})
            self.assertEqual(normalize_search(raw_miss), self.expected["search"]["batch_case_miss"])
            raw_hit = run_search({"terms": ["LighthouseBeacon"], "caseSensitive": True, "files": files})
            self.assertEqual(normalize_search(raw_hit), self.expected["search"]["batch_case_hit"])

        with self.subTest("max_files_skipped"):
            raw_skip = run_search({"terms": ["lighthousebeacon"], "maxFiles": 2, "files": files})
            self.assertEqual(normalize_search(raw_skip), self.expected["search"]["batch_max_files_2"])

        with self.subTest("max_text_window_clipping"):
            with tempfile.TemporaryDirectory(prefix="providers-search-") as tmp:
                long_path = Path(tmp) / "long.jsonl"
                long_text = ("prefix " * 300) + "LighthouseBeacon signal locked" + (" suffix" * 300)
                self.assertGreater(len(long_text), 2000)
                with open(long_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"type": "user", "timestamp": "2026-04-01T12:00:00.000Z",
                                        "message": {"role": "user", "content": long_text}}) + "\n")
                raw_win = run_search({"terms": ["LighthouseBeacon", "locked"],
                                      "files": [{"id": "long", "path": str(long_path)}]})
                actual_win = normalize_search(raw_win, tmp_dir=tmp)
                self.assertLessEqual(len(actual_win["files"][0]["msgs"][0]["text"]), 2000)
                self.assertTrue(actual_win["files"][0]["msgs"][0]["text"].startswith("…"))
                self.assertTrue(actual_win["files"][0]["msgs"][0]["text"].endswith("…"))
                self.assertEqual(actual_win, self.expected["search"]["long_window"])


if __name__ == "__main__":
    unittest.main()
