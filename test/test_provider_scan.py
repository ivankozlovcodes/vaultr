"""mods/ob-feed/providers: live Claude Code background agents are listed with the same fields as finished ones.

The scan runs on a fixture home (`claudeHome`) with a fake claude process (`procs`), so no real session is read.
Transcripts are invented: nothing personal, only the shape Claude Code writes (message lines with usage,
tool_use and stop_reason).
"""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
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
_SCANNER_CACHE = None
PID = 4242
TERM = "tfix1"
SID = "11111111-2222-3333-4444-555555555555"


def _assembled_scanner():
    global _SCANNER_CACHE
    if _SCANNER_CACHE is not None:
        return _SCANNER_CACHE
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot assemble scanner")
    with open(PROVIDERS_DIR / "index.json", encoding="utf-8") as f:
        programs = json.load(f)
    payload = {"providersDir": str(PROVIDERS_DIR), "programs": programs}
    js = (
        'import fs from "node:fs";\n'
        'import path from "node:path";\n'
        f'import * as P from {json.dumps(PROVIDER_JS.as_uri())};\n'
        'const cfg = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'const read = (p) => fs.readFileSync(p, "utf8");\n'
        'const progs = cfg.programs\n'
        '  .filter((id) => fs.existsSync(path.join(cfg.providersDir, id, "scan.py")))\n'
        '  .map((id) => ({\n'
        '    id,\n'
        '    reader: read(path.join(cfg.providersDir, id, "reader.py")),\n'
        '    scan: read(path.join(cfg.providersDir, id, "scan.py")),\n'
        '  }));\n'
        'process.stdout.write(P.assembleScanner(read(path.join(cfg.providersDir, "scan_core.py")), progs));\n'
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", js], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "provider.js failed")
    _SCANNER_CACHE = out.stdout
    return _SCANNER_CACHE


def line(obj):
    return json.dumps(obj)


def asst(mid, blocks, stop=None, out=0):
    return {"type": "assistant", "message": {"id": mid, "role": "assistant", "model": "claude-haiku-5-5",
            "content": blocks, "stop_reason": stop, "usage": {"output_tokens": out}}}


def tool_use(tid, name, cmd):
    return {"type": "tool_use", "id": tid, "name": name, "input": {"command": cmd}}


def tool_result(tid):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


def scan(home, procs):
    opts = json.dumps({"claude": True, "claudeHome": home, "procs": procs, "limit": 40})
    out = subprocess.run([sys.executable, "-I", "-c", _assembled_scanner(), opts], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip()[-400:])
    return json.loads(out.stdout)


class ScanFixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="scan-fixture-")
        self.addCleanup(shutil.rmtree, self.home, True)
        os.makedirs(os.path.join(self.home, ".claude", "sessions"))
        with open(os.path.join(self.home, ".claude", "sessions", f"{PID}.json"), "w") as f:
            json.dump({"pid": PID, "sessionId": SID, "cwd": "/srv/example"}, f)
        self.sub = os.path.join(self.home, ".claude", "projects", "proj-a", SID, "subagents")
        os.makedirs(self.sub)

    def agent(self, aid, lines, finished_meta=False, age_s=0):
        base = os.path.join(self.sub, f"agent-{aid}")
        with open(base + ".meta.json", "w") as f:
            json.dump({"agentType": "general-purpose", "description": f"task {aid}", "finished": finished_meta}, f)
        with open(base + ".jsonl", "w") as f:
            f.write("\n".join(lines) + "\n")
        t = time.time() - age_s
        os.utime(base + ".jsonl", (t, t))
        return base + ".jsonl"

    def result(self):
        return scan(self.home, [{"pid": PID, "term": TERM, "comm": "claude", "cwd": "/srv/example"}])

    def agent_entry(self, res, aid):
        return next(a for a in res["terms"][TERM]["agents"] if a["id"] == aid)


class LiveAgents(ScanFixture):
    def test_a_live_agent_mid_run_is_live_with_its_tools_and_tokens_so_far(self):
        # Latest line asks for a tool (stop_reason tool_use): no final end_turn yet. Written just now.
        self.agent("live01", [
            line(asst("m1", [{"type": "text", "text": "Looking."}], stop="tool_use", out=120)),
            line(tool_result("t1")),
            line(asst("m2", [tool_use("t2", "Bash", "ls notes")], stop="tool_use", out=80)),
        ])
        a = self.agent_entry(self.result(), "live01")
        self.assertEqual(a["live"], True)
        self.assertEqual(a["ended"], False)
        self.assertEqual(a["toolCount"], 1)
        self.assertEqual(a["outTokens"], 200)
        self.assertEqual(a["lastTool"], {"tool": "Bash", "args": "ls notes"})
        self.assertTrue(a["transcript"].endswith("agent-live01.jsonl"))

    def test_a_finished_agent_has_the_same_fields_and_is_not_live(self):
        self.agent("done01", [
            line(asst("m1", [tool_use("t1", "Read", "notes.md")], stop="tool_use", out=40)),
            line(tool_result("t1")),
            line(asst("m2", [{"type": "text", "text": "Done."}], stop="end_turn", out=60)),
        ], finished_meta=True, age_s=3600)
        a = self.agent_entry(self.result(), "done01")
        self.assertEqual(a["live"], False)
        self.assertEqual(a["ended"], True)
        self.assertEqual(a["toolCount"], 1)
        self.assertEqual(a["outTokens"], 100)
        self.assertEqual(a["lastTool"], {"tool": "Read", "args": "notes.md"})
        self.assertEqual(sorted(a.keys()), sorted(self.agent_entry(self.result(), "done01").keys()))

    def test_a_mid_run_file_nobody_writes_any_more_is_not_live(self):
        # No final line, but untouched for an hour: the agent is gone, not running.
        self.agent("stale1", [line(asst("m1", [tool_use("t1", "Bash", "sleep 9")], stop="tool_use", out=5))], age_s=3600)
        a = self.agent_entry(self.result(), "stale1")
        self.assertEqual(a["live"], False)
        self.assertEqual(a["ended"], False)

    def test_a_malformed_tail_line_is_skipped(self):
        self.agent("bad01", [
            line(asst("m1", [tool_use("t1", "Grep", "todo")], stop="tool_use", out=30)),
            '{"type": "assistant", "message": {"id": "m2", "conte',   # cut off mid-write
            "not json at all",
            line(asst("m3", [tool_use("t2", "Read", "a.md")], stop="tool_use", out=10)),
        ])
        a = self.agent_entry(self.result(), "bad01")
        self.assertEqual(a["live"], True)
        self.assertEqual(a["toolCount"], 2)
        self.assertEqual(a["outTokens"], 40)
        self.assertEqual(a["lastTool"], {"tool": "Read", "args": "a.md"})

    def test_a_message_split_over_lines_counts_its_tokens_once(self):
        # Claude Code writes one line per content block; the usage repeats on each line of the same message id.
        self.agent("split1", [
            line(asst("m1", [{"type": "text", "text": "a"}], stop=None, out=50)),
            line(asst("m1", [tool_use("t1", "Bash", "pwd")], stop="tool_use", out=50)),
        ])
        a = self.agent_entry(self.result(), "split1")
        self.assertEqual(a["outTokens"], 50)
        self.assertEqual(a["toolCount"], 1)

    def test_a_split_message_without_first_line_usage_counts_zero_for_that_message(self):
        # Only the first line of a message id counts for output tokens, even when that first line omits usage.
        self.agent("split2", [
            line({"type": "user", "message": {"role": "user", "content": "check"}}),
            line({"type": "assistant", "message": {"id": "m1", "role": "assistant", "model": "claude-haiku-5-5",
                  "content": [{"type": "text", "text": "a"}], "stop_reason": None}}),
            line(asst("m1", [tool_use("t1", "Bash", "pwd")], stop="tool_use", out=50)),
        ])
        a = self.agent_entry(self.result(), "split2")
        self.assertIsNone(a["outTokens"])
        self.assertEqual(a["turns"], 1)


class MainAgents(ScanFixture):
    """A live main Claude Code terminal (not a subagent) maps to its session transcript, the shape ob-props reads."""

    def test_a_main_agent_terminal_has_its_session_transcript(self):
        main = os.path.join(self.home, ".claude", "projects", "proj-a", SID + ".jsonl")
        with open(main, "w") as f:
            f.write("\n".join([line(asst("m1", [{"type": "text", "text": "Working."}], stop="end_turn", out=7))]) + "\n")
        t = self.result()["terms"][TERM]
        self.assertEqual(t["kind"], "claude")
        self.assertEqual(t["session"], SID)
        self.assertTrue(t["transcript"].endswith(SID + ".jsonl"))
        self.assertTrue(os.path.exists(t["transcript"]))

    def test_a_main_agent_reports_when_its_transcript_last_changed(self):
        # the ticker orders working main agents by this, not by "now"
        main = os.path.join(self.home, ".claude", "projects", "proj-a", SID + ".jsonl")
        with open(main, "w") as f:
            f.write(line(asst("m1", [{"type": "text", "text": "Working."}], stop="end_turn", out=7)) + "\n")
        os.utime(main, (1_700_000_000, 1_700_000_000))
        self.assertEqual(self.result()["terms"][TERM]["updatedAt"], 1_700_000_000_000)

    def test_a_main_agent_without_a_session_file_has_no_transcript(self):
        t = self.result()["terms"][TERM]
        self.assertEqual(t["session"], SID)
        self.assertIsNone(t["transcript"])


class MacProcesses(ScanFixture):
    """macOS has no /proc: the scan finds pi and claude terminals with ps (start time, name, arguments), ps -E (the
    HC_TERMINAL_ID in each one's environment) and lsof (its folder). `psOutput` stands in for those three commands."""

    PS = {
        "list": "\n".join([
            f"  {PID} Sat Nov 14 10:41:08 2026 claude           claude --resume",
            "  5150 Sat Nov 14 09:00:00 2026 node             node /usr/local/lib/node_modules/pi/dist/cli.js",
            "  5151 Sat Nov 14 09:00:00 2026 node             node /srv/app/server.js",
            "  5152 Sat Nov 14 09:00:00 2026 claude           claude",
            "",
        ]),
        "env": "\n".join([
            f"{PID} claude --resume PATH=/usr/bin HC_TERMINAL_ID={TERM} TERM=xterm-256color",
            "5150 node /usr/local/lib/node_modules/pi/dist/cli.js HC_TERMINAL_ID=tpi9 LANG=C",
            "5152 claude PATH=/usr/bin",
        ]),
        "cwd": "\n".join([f"p{PID}", "fcwd", "n/srv/example", "p5150", "fcwd", "n/srv/pi-work", ""]),
    }

    def result(self):
        return json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home, "limit": 40,
                                     "psOutput": self.PS}))

    def test_a_claude_terminal_is_found_from_ps(self):
        t = self.result()["terms"][TERM]
        self.assertEqual(t["kind"], "claude")
        self.assertEqual(t["session"], SID)

    def test_pi_running_under_node_is_found_with_its_folder(self):
        t = self.result()["terms"]["tpi9"]
        self.assertEqual(t["kind"], "pi")
        self.assertEqual(t["cwd"], "/srv/pi-work")

    def test_a_process_without_a_terminal_id_or_not_an_agent_is_left_out(self):
        terms = self.result()["terms"]
        self.assertEqual(sorted(terms), sorted([TERM, "tpi9"]))


class ShortToolArgument(ScanFixture):
    """The last tool of an agent names what it touches, briefly: a file's basename, or the first 40 characters of a
    command. Never the tool's output."""

    def test_a_file_edit_shows_the_basename_only(self):
        self.agent("e1", [line(asst("m1", [{"type": "tool_use", "id": "t1", "name": "Edit",
                                             "input": {"file_path": "/srv/example/mods/ob-outline/main.js"}}]))])
        self.assertEqual(self.agent_entry(self.result(), "e1")["lastTool"], {"tool": "Edit", "args": "main.js"})

    def test_a_long_command_is_cut_to_forty_characters(self):
        cmd = "python3 -m unittest discover -s test -p 'test_provider_scan.py' -v && echo done"
        self.agent("b1", [line(asst("m1", [tool_use("t1", "Bash", cmd)]))])
        args = self.agent_entry(self.result(), "b1")["lastTool"]["args"]
        self.assertLessEqual(len(args), 40)
        self.assertEqual(args, cmd[:39] + "…")

    def test_a_tool_result_is_never_the_argument(self):
        self.agent("r1", [line(asst("m1", [tool_use("t1", "Bash", "ls")])), line(tool_result("t1"))])
        self.assertEqual(self.agent_entry(self.result(), "r1")["lastTool"]["args"], "ls")

    def test_a_main_agent_reports_its_last_tool_from_its_transcript(self):
        main = os.path.join(self.home, ".claude", "projects", "proj-a", SID + ".jsonl")
        with open(main, "w") as f:
            f.write(line(asst("m1", [{"type": "tool_use", "id": "t9", "name": "Read",
                                      "input": {"file_path": "/a/b/notes.md"}}])) + "\n")
        self.assertEqual(self.result()["terms"][TERM]["lastTool"], {"tool": "Read", "args": "notes.md"})

def scan_opts(opts):
    out = subprocess.run([sys.executable, "-I", "-c", _assembled_scanner(), json.dumps(opts)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip()[-400:])
    return out.stdout


def ts(sec):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(1_790_000_000 + sec)) + ".000Z"


def tool_rec(sec, name, inp, tid=None):
    """A Claude Code assistant line that calls one tool (its timestamp is sec seconds after a fixed time)."""
    return {"type": "assistant", "timestamp": ts(sec), "message": {"id": f"m{sec}", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "tool_use", "id": tid or f"t{sec}", "name": name, "input": inp}], "stop_reason": "tool_use",
            "usage": {"output_tokens": 3}}}


def pi_rec(sec, name, args):
    """A pi session line: an assistant message with one toolCall block (pi writes lowercase tool names)."""
    return {"type": "message", "timestamp": ts(sec), "message": {"role": "assistant", "content": [
        {"type": "toolCall", "id": f"c{sec}", "name": name, "arguments": args}]}}


class Touches(ScanFixture):
    """The files each agent touches, from invented transcripts (paths only: the tool results carry a secret word that
    must never reach the output)."""

    def main_path(self):
        return os.path.join(self.home, ".claude", "projects", "proj-a", SID + ".jsonl")

    def write_main(self, recs):
        with open(self.main_path(), "w") as f:
            f.write("\n".join(line(r) for r in recs) + "\n")

    def run_scan(self, **extra):
        opts = {"claude": True, "claudeHome": self.home, "limit": 40,
                "procs": [{"pid": PID, "term": TERM, "comm": "claude", "cwd": "/srv/example"}]}
        opts.update(extra)
        return json.loads(scan_opts(opts))

    def test_claude_main_session_reads_edits_and_writes_are_collected_with_their_op(self):
        self.write_main([
            tool_rec(1, "Read", {"file_path": "/srv/notes/a.md"}),
            tool_rec(2, "Edit", {"file_path": "/srv/src/x.js", "old_string": "a", "new_string": "b"}),
            tool_rec(3, "Write", {"file_path": "/srv/out/new.txt", "content": "SECRET-BODY-1"}),
            tool_rec(4, "Bash", {"command": "ls"}),
        ])
        got = {t["path"]: t["op"] for t in self.run_scan()["touches"][f"term:{TERM}"]}
        self.assertEqual(got, {"/srv/notes/a.md": "read", "/srv/src/x.js": "edit", "/srv/out/new.txt": "create"})

    def test_a_write_to_a_path_already_read_in_the_tail_is_a_write_not_a_create(self):
        self.write_main([tool_rec(1, "Read", {"file_path": "/srv/a.txt"}), tool_rec(2, "Write", {"file_path": "/srv/a.txt", "content": "x"})])
        got = {t["path"]: t["op"] for t in self.run_scan()["touches"][f"term:{TERM}"]}
        self.assertEqual(got, {"/srv/a.txt": "write"})

    def test_one_path_is_listed_once_with_its_strongest_op_and_newest_time(self):
        self.write_main([
            tool_rec(1, "Write", {"file_path": "/srv/p.md", "content": "x"}),
            tool_rec(5, "Read", {"file_path": "/srv/p.md"}),
            tool_rec(9, "Edit", {"file_path": "/srv/p.md", "old_string": "x", "new_string": "y"}),
        ])
        rows = self.run_scan()["touches"][f"term:{TERM}"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["op"], "create")
        self.assertEqual(rows[0]["at"], 1_790_000_000_000 + 9000)

    def test_a_notebook_edit_counts_as_an_edit(self):
        self.write_main([tool_rec(1, "NotebookEdit", {"notebook_path": "/srv/nb.ipynb", "new_source": "SECRET"})])
        got = {t["path"]: t["op"] for t in self.run_scan()["touches"][f"term:{TERM}"]}
        self.assertEqual(got, {"/srv/nb.ipynb": "edit"})

    def test_at_most_forty_distinct_paths_per_agent_keeping_the_newest(self):
        self.write_main([tool_rec(i, "Read", {"file_path": f"/srv/f{i:03d}.md"}) for i in range(1, 61)])
        rows = self.run_scan()["touches"][f"term:{TERM}"]
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0]["path"], "/srv/f060.md")
        self.assertNotIn("/srv/f020.md", {r["path"] for r in rows})

    def test_a_subagent_has_its_own_touches_under_its_agent_key(self):
        self.agent("sub01", [line(tool_rec(1, "Read", {"file_path": "/srv/sub/read-me.md"}))])
        out = self.run_scan()
        self.assertEqual(out["touches"]["a:sub01"], [{"path": "/srv/sub/read-me.md", "op": "read", "at": 1_790_000_000_000 + 1000}])

    def test_a_danger_folder_path_is_never_collected_at_all(self):
        self.write_main([tool_rec(1, "Read", {"file_path": "/srv/vault/danger/keys.md"}),
                         tool_rec(2, "Read", {"file_path": "/srv/vault/Danger/Keys.md"}),
                         tool_rec(3, "Read", {"file_path": "/srv/vault/ok.md"})])
        paths = [t["path"] for t in self.run_scan()["touches"][f"term:{TERM}"]]
        self.assertEqual(paths, ["/srv/vault/ok.md"])

    def test_only_paths_are_kept_never_contents(self):
        self.write_main([tool_rec(1, "Write", {"file_path": "/srv/out.txt", "content": "SECRET-BODY-1"})])
        self.agent("sub02", [line(tool_rec(2, "Read", {"file_path": "/srv/r.md"})), line(tool_result("t2"))])
        raw = scan_opts({"claude": True, "claudeHome": self.home, "limit": 40,
                         "procs": [{"pid": PID, "term": TERM, "comm": "claude", "cwd": "/srv/example"}]})
        self.assertNotIn("SECRET-BODY-1", raw)
        self.assertNotIn("\"ok\"", raw)

    def test_pi_session_file_tools_are_collected_from_a_terminal_session(self):
        sess_dir = os.path.join(self.home, ".pi", "agent", "sessions", "--srv-example--")
        os.makedirs(sess_dir)
        sess = os.path.join(sess_dir, "2026-11-14T09-00-00-000Z_fixture.jsonl")
        with open(sess, "w") as f:
            f.write("\n".join(line(r) for r in [
                pi_rec(1, "read", {"path": "/srv/pi/notes.md"}),
                pi_rec(2, "write", {"path": "/srv/pi/made.md", "content": "SECRET-PI"}),
                pi_rec(3, "edit", {"path": "/srv/pi/made.md", "oldText": "a", "newText": "b"}),
            ]) + "\n")
        out = json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home, "limit": 40, "procs": [
            {"pid": 777, "term": "pfix1", "comm": "pi", "cwd": "/srv/example", "start": None}]}))
        got = {t["path"]: t["op"] for t in out["touches"]["term:pfix1"]}
        self.assertEqual(got, {"/srv/pi/notes.md": "read", "/srv/pi/made.md": "create"})
        self.assertNotIn("SECRET-PI", json.dumps(out))

    def test_herdr_artifact_publications_are_collected_for_the_terminal_that_published_them(self):
        store = os.path.join(self.home, "store")
        os.makedirs(store)
        with open(os.path.join(store, "fixture.json"), "w") as f:
            json.dump({"folder": "/srv/example", "artifacts": [
                {"id": "cov-ab12", "title": "Coverage by package", "publisher": TERM, "at": 1_790_000_500_000,
                 "versions": [{"v": 1, "at": 1_790_000_100_000, "publisher": TERM}, {"v": 2, "at": 1_790_000_500_000, "publisher": TERM}]},
                {"id": "nobody-01", "title": "No publisher", "publisher": None, "at": 1_790_000_600_000, "versions": []}]}, f)
        out = self.run_scan(artifactStore=store)
        rows = out["touches"][f"term:{TERM}"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["op"], "publish")
        self.assertEqual(rows[0]["artifact"]["id"], "cov-ab12")
        self.assertEqual(rows[0]["artifact"]["title"], "Coverage by package")
        self.assertEqual(rows[0]["at"], 1_790_000_500_000)
        self.assertNotIn("term:None", out["touches"])

    def test_the_scan_records_its_own_time_so_its_cost_can_be_watched(self):
        self.write_main([tool_rec(1, "Read", {"file_path": "/srv/a.md"})])
        self.assertIn("ms", self.run_scan())


class MasterAndCopies(unittest.TestCase):
    def test_the_feed_copy_is_the_kit_master(self):
        master = Path(ROOT, "kit", "provider.js").read_bytes()
        self.assertEqual(master, Path(ROOT, "mods", "ob-feed", "provider.js").read_bytes())

    def test_the_feed_publishes_touches_under_the_graph_node_keys(self):
        src = Path(ROOT, "mods", "ob-feed", "main.js").read_text(encoding="utf-8")
        self.assertIn('if (kind === "term") return `term:${addrOn(m, id)}`;', src)
        self.assertIn("if (kind === \"a\") return `c:${k}:${id}`;", src)
        self.assertIn("if (kind === \"r\") return `r:${k}:${id}`;", src)
        self.assertIn("TOUCH_TOTAL = 400", src)

    def test_the_feed_keeps_live_and_tool_count(self):
        src = Path(ROOT, "mods", "ob-feed", "main.js").read_text(encoding="utf-8")
        self.assertIn("live: Boolean(a.live)", src)
        self.assertIn("toolCount", src)


def _write_fake_proc(proc_root, pid, comm, argv, term, cwd, exe=None):
    pdir = Path(proc_root, str(pid))
    pdir.mkdir(parents=True)
    with open(pdir / "comm", "w", encoding="utf-8") as f:
        f.write(comm + "\n")
    with open(pdir / "cmdline", "wb") as f:
        f.write(b"\0".join(a.encode("utf-8") for a in argv) + b"\0")
    with open(pdir / "environ", "wb") as f:
        f.write(f"PATH=/usr/bin\0HC_TERMINAL_ID={term}\0".encode("utf-8"))
    os.symlink(cwd, pdir / "cwd")
    if exe:
        os.symlink(exe, pdir / "exe")


class ProgramIdentity(unittest.TestCase):
    """Unrelated binaries named claude or pi are ignored across ps, procs, and /proc when evidence is absent."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="scan-ident-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_claude_without_evidence_yields_zero_rows_and_confirmed_claude_succeeds(self):
        ps_bare = {
            "list": "  1002 Sat Nov 14 10:41:08 2026 claude           /usr/local/bin/claude --render\n",
            "env": "1002 /usr/local/bin/claude --render HC_TERMINAL_ID=tcl_fake\n",
            "cwd": "p1002\nfcwd\nn/tmp\n",
        }
        self.assertEqual(
            json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home, "psOutput": ps_bare}))["terms"],
            {},
        )
        self.assertEqual(
            json.loads(scan_opts({
                "claude": True,
                "claudeHome": self.home,
                "piHome": self.home,
                "procs": [{"pid": 1002, "term": "tcl_fake", "comm": "claude", "cwd": "/tmp",
                           "args": ["/usr/local/bin/claude", "--render"]}],
            }))["terms"],
            {},
        )
        proc_dir = Path(self.home, "proc")
        _write_fake_proc(proc_dir, 1002, "claude", ["/usr/local/bin/claude", "--render"], "tcl_fake", "/tmp",
                         exe="/usr/local/bin/claude")
        self.assertEqual(
            json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                  "procRoot": str(proc_dir)}))["terms"],
            {},
        )

        # Real evidence (CLI package path in argv/cmdline) confirms claude in ps, procs, and /proc.
        ps_real = {
            "list": "  1004 Sat Nov 14 10:41:08 2026 claude           /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js\n",
            "env": "1004 claude HC_TERMINAL_ID=tcl_real\n",
            "cwd": "p1004\nfcwd\nn/srv/claude\n",
        }
        self.assertEqual(
            sorted(json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                         "psOutput": ps_real}))["terms"]),
            ["tcl_real"],
        )
        _write_fake_proc(proc_dir, 1004, "claude",
                         ["claude", "/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js"],
                         "tcl_real", "/srv/claude")
        self.assertEqual(
            sorted(json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                         "procRoot": str(proc_dir)}))["terms"]),
            ["tcl_real"],
        )

    def test_pi_without_evidence_yields_zero_rows_and_confirmed_pi_succeeds(self):
        ps_bare = {
            "list": "  1001 Sat Nov 14 10:41:08 2026 pi               /usr/bin/pi 100\n",
            "env": "1001 /usr/bin/pi 100 HC_TERMINAL_ID=tpi_fake\n",
            "cwd": "p1001\nfcwd\nn/tmp\n",
        }
        self.assertEqual(
            json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home, "psOutput": ps_bare}))["terms"],
            {},
        )
        self.assertEqual(
            json.loads(scan_opts({
                "claude": True,
                "claudeHome": self.home,
                "piHome": self.home,
                "procs": [{"pid": 1001, "term": "tpi_fake", "comm": "pi", "cwd": "/tmp",
                           "args": ["/usr/bin/pi", "100"]}],
            }))["terms"],
            {},
        )
        proc_dir = Path(self.home, "proc")
        _write_fake_proc(proc_dir, 1001, "pi", ["/usr/bin/pi", "100"], "tpi_fake", "/tmp", exe="/usr/bin/pi")
        self.assertEqual(
            json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                  "procRoot": str(proc_dir)}))["terms"],
            {},
        )

        # Real evidence (CLI package path in argv/cmdline) confirms pi in ps, procs, and /proc.
        ps_real = {
            "list": "  1003 Sat Nov 14 10:41:08 2026 node             node /usr/local/lib/node_modules/@mariozechner/pi-coding-agent/dist/cli.js\n",
            "env": "1003 node HC_TERMINAL_ID=tpi_real\n",
            "cwd": "p1003\nfcwd\nn/srv/pi\n",
        }
        self.assertEqual(
            sorted(json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                         "psOutput": ps_real}))["terms"]),
            ["tpi_real"],
        )
        _write_fake_proc(proc_dir, 1003, "node",
                         ["node", "/usr/local/lib/node_modules/@mariozechner/pi-coding-agent/dist/cli.js"],
                         "tpi_real", "/srv/pi")
        self.assertEqual(
            sorted(json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home,
                                         "procRoot": str(proc_dir)}))["terms"]),
            ["tpi_real"],
        )


class UserPrompts(ScanFixture):
    """Recent human prompts are extracted from Claude Code and pi session transcripts, skipping noise and callbacks."""

    def main_path(self):
        return os.path.join(self.home, ".claude", "projects", "proj-a", SID + ".jsonl")

    def write_main(self, recs):
        with open(self.main_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(line(r) for r in recs) + "\n")

    def run_scan(self, **extra):
        opts = {"claude": True, "claudeHome": self.home, "piHome": self.home, "limit": 40,
                "procs": [{"pid": PID, "term": TERM, "comm": "claude", "cwd": "/srv/example"}]}
        opts.update(extra)
        return json.loads(scan_opts(opts))

    def test_claude_user_prompts_collect_headline_and_multiline_full_skipping_noise(self):
        self.write_main([
            {"type": "user", "isMeta": True, "timestamp": ts(1), "message": {"role": "user", "content": "meta line"}},
            {"type": "user", "timestamp": ts(2), "message": {"role": "user", "content": "<local-command-caveat>ignore</local-command-caveat>"}},
            {"type": "user", "timestamp": ts(3), "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
            {"type": "user", "timestamp": ts(4), "message": {"role": "user", "content": "Caveat: helper text"}},
            {"type": "user", "timestamp": ts(5), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            {"type": "user", "timestamp": ts(6), "message": {"role": "user", "content": [
                {"type": "text", "text": "<system-reminder>hidden</system-reminder>"},
                {"type": "text", "text": "# First task\nLine two detail"},
            ]}},
            {"type": "user", "timestamp": ts(7), "message": {"role": "user", "content": '  <hc from="t9" event="ready">done</hc>'}},
        ])
        turns = self.run_scan()["terms"][TERM]["turns"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["text"], "First task")
        self.assertEqual(turns[0]["full"], "# First task\nLine two detail")
        self.assertEqual(turns[0]["ts"], ts(6))

    def test_claude_user_prompts_keep_at_most_twelve_newest(self):
        self.write_main([
            {"type": "user", "timestamp": ts(i), "message": {"role": "user", "content": f"Prompt {i}"}}
            for i in range(1, 16)
        ])
        turns = self.run_scan()["terms"][TERM]["turns"]
        self.assertEqual(len(turns), 12)
        self.assertEqual([t["text"] for t in turns], [f"Prompt {i}" for i in range(4, 16)])

    def test_pi_session_user_prompts_are_collected_skipping_hc_callbacks(self):
        sess_dir = os.path.join(self.home, ".pi", "agent", "sessions", "--srv-example--")
        os.makedirs(sess_dir)
        sess = os.path.join(sess_dir, "2026-11-14T09-00-00-000Z_prompts.jsonl")
        with open(sess, "w", encoding="utf-8") as f:
            f.write("\n".join(line(r) for r in [
                {"type": "message", "timestamp": ts(1), "message": {"role": "user", "content": "Fix layout spacing\nKeep border 1px"}},
                {"type": "message", "timestamp": ts(2), "message": {"role": "assistant", "content": [{"type": "text", "text": "Working"}]}},
                {"type": "message", "timestamp": ts(3), "message": {"role": "user", "content": [{"type": "text", "text": "And verify header width"}]}},
                {"type": "message", "timestamp": ts(4), "message": {"role": "user", "content": '<hc from="t2" event="ready">worker done</hc>'}},
            ]) + "\n")
        out = json.loads(scan_opts({"claude": True, "claudeHome": self.home, "piHome": self.home, "limit": 40, "procs": [
            {"pid": 778, "term": "pfix2", "comm": "pi", "cwd": "/srv/example", "start": None}]}))
        turns = out["terms"]["pfix2"]["turns"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["text"], "Fix layout spacing")
        self.assertEqual(turns[0]["full"], "Fix layout spacing\nKeep border 1px")
        self.assertEqual(turns[1]["text"], "And verify header width")


if __name__ == "__main__":
    unittest.main()
