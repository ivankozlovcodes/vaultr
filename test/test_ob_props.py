"""mods/ob-props Usage section: token arithmetic and formatting (node, pure: usage.js) and the transcript reader
(python: assembled from mods/ob-feed/providers/, run the way ob-props runs it: `python3 -c <text> <path> <cap>`).
Fixtures in test/fixtures/ob-props are invented; they copy the shape of real entries and nothing else."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MOD = Path(ROOT, "mods", "ob-props")
USAGE_JS = MOD / "usage.js"
PROVIDERS_DIR = Path(ROOT, "mods", "ob-feed", "providers")
PROVIDER_JS = Path(ROOT, "kit", "provider.js")
FIX = Path(ROOT, "test", "fixtures", "ob-props")
CLAUDE = FIX / "claude-session.jsonl"
PI = FIX / "pi-session.jsonl"
FOLLOW = Path(ROOT, "kit", "follow_target.js")
NODE = shutil.which("node")
_USAGE_CACHE = None


def _assembled_usage():
    global _USAGE_CACHE
    if _USAGE_CACHE is not None:
        return _USAGE_CACHE
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot assemble usage reader")
    with open(PROVIDERS_DIR / "index.json", encoding="utf-8") as f:
        programs = json.load(f)
    payload = {"providersDir": str(PROVIDERS_DIR), "programs": programs}
    js = (
        'import fs from "node:fs";\n'
        'import path from "node:path";\n'
        f'import * as P from {json.dumps(PROVIDER_JS.as_uri())};\n'
        'const cfg = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'const read = (p) => fs.readFileSync(p, "utf8");\n'
        'const readers = cfg.programs\n'
        '  .filter((id) => fs.existsSync(path.join(cfg.providersDir, id, "reader.py")))\n'
        '  .map((id) => ({ id, reader: read(path.join(cfg.providersDir, id, "reader.py")) }));\n'
        'process.stdout.write(P.assembleReader(read(path.join(cfg.providersDir, "reader_main.py")), readers, "usage"));\n'
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", js], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "provider.js failed")
    _USAGE_CACHE = out.stdout
    return _USAGE_CACHE


def run_node(body):
    """Import usage.js in node, run `body` (JS that returns a value), return its JSON."""
    src = (f'import * as U from "{USAGE_JS.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def run_helper(path, cap=None, seen=None):
    """Run assembled usage reader the way ob-props does: python3 -c <text> <path> [<cap bytes> [<seen sig>]]. -> the JSON line."""
    text = _assembled_usage()
    args = ["python3", "-c", text, str(path)] + ([str(cap if cap is not None else "")] if cap is not None or seen else []) + ([seen] if seen else [])
    out = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "helper failed")
    return json.loads(out.stdout.strip().splitlines()[-1])


# The three counted turns of claude-session.jsonl (msg_fx01 and msg_fx02 are written twice each, streamed per
# content block, with the same usage; msg_fx03 is "<synthetic>" with zeros and is not a turn).
CLAUDE_TURNS = [
    {"id": "msg_fx01", "model": "claude-fable-5-2", "input": 10, "output": 20, "cacheRead": 1000, "cacheWrite": 300},
    {"id": "msg_fx02", "model": "claude-fable-5-2", "input": 3, "output": 50, "cacheRead": 1500, "cacheWrite": 200},
    {"id": "msg_fx04", "model": "claude-fable-5-2", "input": 4, "output": 39, "cacheRead": 2000, "cacheWrite": 350},
]


class Arithmetic(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_sums_across_turns(self):
        s = run_node(f"return U.summarize({json.dumps(CLAUDE_TURNS)});")
        self.assertEqual((s["input"], s["output"], s["cacheRead"], s["cacheWrite"]), (17, 109, 4500, 850))
        self.assertEqual(s["total"], 17 + 109 + 4500 + 850)
        self.assertEqual(s["turns"], 3)

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_context_is_the_last_turn_not_the_sum(self):
        s = run_node(f"return U.summarize({json.dumps(CLAUDE_TURNS)});")
        # last turn: input + cache read + cache write
        self.assertEqual(s["context"], 4 + 2000 + 350)
        self.assertEqual(s["model"], "claude-fable-5-2")

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_unknown_model_shows_the_count_only(self):
        s = run_node(f"return U.summarize({json.dumps(CLAUDE_TURNS)});")
        self.assertIsNone(s["window"])
        self.assertIsNone(s["share"])
        rows = run_node(f"return U.usageLines(U.summarize({json.dumps(CLAUDE_TURNS)}));")
        ctx = next(r for r in rows if r["id"] == "context")
        self.assertEqual(ctx["value"], "2,354")
        self.assertNotIn("%", ctx["value"])

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_known_model_shows_the_share_of_its_window(self):
        turns = [{"id": "x", "model": "claude-sonnet-4-5", "input": 1000, "output": 1, "cacheRead": 99000, "cacheWrite": 0}]
        rows = run_node(f"return U.usageLines(U.summarize({json.dumps(turns)}));")
        ctx = next(r for r in rows if r["id"] == "context")
        self.assertEqual(ctx["value"], "100,000 · 50% of 200,000")

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_window_table(self):
        self.assertEqual(run_node('return U.windowOf("claude-sonnet-4-5");'), 200000)
        self.assertEqual(run_node('return U.windowOf("claude-opus-4-1[1m]");'), 1000000)
        self.assertIsNone(run_node('return U.windowOf("claude-fable-5-2");'))
        self.assertIsNone(run_node('return U.windowOf(null);'))

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_claude_3_ids_have_a_200k_window(self):
        for model in ("claude-3-opus-20240229", "claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022", "claude-3-haiku-20240307"):
            with self.subTest(model=model):
                self.assertEqual(run_node(f'return U.windowOf({json.dumps(model)});'), 200000)

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_only_opus_and_sonnet_4_have_the_1m_window(self):
        self.assertEqual(run_node('return U.windowOf("claude-sonnet-4-5[1m]");'), 1000000)
        self.assertEqual(run_node('return U.windowOf("claude-haiku-4-5[1m]");'), 200000)
        self.assertEqual(run_node('return U.windowOf("claude-3-5-sonnet-20241022[1m]");'), 200000)

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_no_turns_is_no_summary(self):
        self.assertIsNone(run_node("return U.summarize([]);"))

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_counts_are_grouped_by_thousands(self):
        self.assertEqual(run_node("return [U.fmtCount(0), U.fmtCount(999), U.fmtCount(1000), U.fmtCount(1234567)];"),
                         ["0", "999", "1,000", "1,234,567"])

    @unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
    def test_subagents_line_sums_their_output_tokens(self):
        agents = json.dumps([{"outTokens": 120}, {"outTokens": None}, {"outTokens": 30}])
        self.assertEqual(run_node(f"return U.subagentsLine({agents});"), "3 agents · 150 output tokens")
        self.assertIsNone(run_node("return U.subagentsLine([]);"))


@unittest.skipUnless(NODE, "node is not installed: the usage arithmetic test is skipped")
class Lines(unittest.TestCase):
    def test_a_missing_summary_gives_no_rows(self):
        self.assertEqual(run_node("return U.usageLines(null);"), [])


class Reader(unittest.TestCase):
    def test_claude_turns_are_counted_once_each(self):
        d = run_helper(CLAUDE)
        self.assertIsNone(d.get("error"))
        self.assertEqual(d["format"], "claude")
        self.assertEqual(d["turns"], CLAUDE_TURNS)

    def test_a_malformed_line_is_skipped(self):
        # the fixture has one cut-off line between two good turns; the turns on both sides still count
        d = run_helper(CLAUDE)
        self.assertEqual([t["id"] for t in d["turns"]], ["msg_fx01", "msg_fx02", "msg_fx04"])

    def test_pi_session_turns(self):
        d = run_helper(PI)
        self.assertEqual(d["format"], "pi-session")
        self.assertEqual(d["turns"], [
            {"id": "resp_fx1", "model": "claude-opus-5-5", "input": 12, "output": 30, "cacheRead": 800, "cacheWrite": 0},
            {"id": "resp_fx2", "model": "claude-opus-5-5", "input": 5, "output": 9, "cacheRead": 900, "cacheWrite": 40},
        ])

    def test_missing_file_is_an_error_with_no_turns(self):
        d = run_helper(Path(home_guard.TMP, "no-such-session.jsonl"))
        self.assertTrue(d.get("error"))
        self.assertEqual(d["turns"], [])

    def test_tail_cap_reads_only_the_end_of_a_long_file(self):
        folder = tempfile.mkdtemp(prefix="ob-props-tail-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = Path(folder, "long.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for i in range(300):
                f.write(json.dumps({"type": "assistant", "message": {"model": "claude-fable-5-2", "id": f"msg_{i:04d}",
                                    "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0}}}) + "\n")
        size = path.stat().st_size
        d = run_helper(path, 4096)
        self.assertTrue(d["truncated"])
        self.assertEqual(d["size"], size)
        self.assertLess(len(d["turns"]), 300)
        self.assertGreater(len(d["turns"]), 0)
        self.assertEqual(d["turns"][-1]["id"], "msg_0299")   # the newest turn is always read


def run_obc(body, feed=None, records=None):
    """Import a copy of obc.js in node with herdr and kit.js stubbed: feed() gives `feed`, liveRecords() gives
    `records` ({address: {id: record}}). Runs `body` (JS with H = herdr, O = the module) and returns its JSON."""
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory(prefix="ob-props-obc-") as folder:
        src = (MOD / "obc.js").read_text(encoding="utf-8").replace('from "herdr"', 'from "./herdr.js"')
        Path(folder, "obc.js").write_text(src, encoding="utf-8")
        Path(folder, "herdr.js").write_text(
            "const st = { terminals: [], agents: [], panes: [], spaces: [], focused: null, shared: {} };\n"
            "export const __set = (patch) => Object.assign(st, patch);\n"
            "export const terminals = () => st.terminals;\n"
            "export const agents = () => st.agents;\n"
            "export const panes = () => st.panes;\n"
            "export const spaces = () => st.spaces;\n"
            "export const focused = () => st.focused;\n"
            "export const shared = (k) => st.shared[k];\n"
            "export const setShared = (k, v) => { st.shared[k] = v; };\n"
            "export const run = () => null;\n"
            "export const openOverlay = () => null;\n"
            "export const notify = () => null;\n",
            encoding="utf-8",
        )
        kit = ["machineOf", "tabLabel", "paneName", "dur", "ago", "fmtTokens", "fmtCost", "normStatus", "copyText", "base", "hasMod",
               "parentAddrOf", "isChildTerminalOf", "getHidden", "updateHidden", "patchHidden", "normHidden", "isSpaceHidden", "isTabHidden"]
        Path(folder, "kit.js").write_text(
            'export const MOD = "ob-props";\n'
            f"export {{ followTarget }} from {json.dumps(FOLLOW.as_uri())};\n"
            + "".join(f"export const {n} = () => null;\n" for n in kit)
            + f"export const feed = () => ({json.dumps(feed)});\n"
            + f"export const liveRecords = () => new Map(Object.entries({json.dumps(records or {})}));\n",
            encoding="utf-8",
        )
        code = (
            f'import * as H from "{Path(folder, "herdr.js").as_uri()}";\n'
            f'import * as O from "{Path(folder, "obc.js").as_uri()}";\n'
            f'console.log(JSON.stringify((() => {{ {body} }})()));'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class ClaudeLiveness(unittest.TestCase):
    """claudeAll(): a sub-agent is live when the feed's scan says so or its terminal's live record does (the rule
    ob-outline uses, so the two panels agree)."""
    SUB = {"key": "local:a1", "machine": None, "parent": "t3c", "id": "a1", "type": "Explore", "desc": "look", "live": True}

    def test_a_feed_sub_agent_marked_live_without_a_record_is_live(self):
        out = run_obc("return O.claudeAll().map((c) => [c.id, c.live]);", {"claude": [self.SUB]}, {})
        self.assertEqual(out, [["a1", True]])

    def test_a_record_working_makes_it_live(self):
        sub = {**self.SUB, "live": False}
        out = run_obc("return O.claudeAll().map((c) => c.live);", {"claude": [sub]}, {"t3c": {"a1": {"state": "working"}}})
        self.assertEqual(out, [True])

    def test_neither_says_live_is_not_live(self):
        sub = {**self.SUB, "live": False}
        out = run_obc("return O.claudeAll().map((c) => c.live);", {"claude": [sub]}, {})
        self.assertEqual(out, [False])


@unittest.skipUnless(NODE, "node is not installed")
class PropsObcFollowSlot(unittest.TestCase):
    """ob-props uses ob.follow.props and follows any live terminal pane (wantAgent: false)."""

    def test_inspected_stores_props_slot_and_follows_non_agent_shell_pane(self):
        out = run_obc("""
            H.__set({
              agents: [{ address: "t2" }],
              terminals: [{ address: "t2", state: "live" }, { address: "t4", state: "live" }],
              focused: { pane: "p1", terminal: "t2" },
            });
            const agentPane = O.inspected();
            const followAfterAgent = H.shared("ob.follow") ?? null;
            H.__set({ focused: { pane: "p2", terminal: "t4" } });
            const shellPane = O.inspected();
            const followAfterShell = H.shared("ob.follow") ?? null;
            H.__set({ focused: { pane: "side", terminal: null } });
            const sidePanel = O.inspected();
            return { agentPane, followAfterAgent, shellPane, followAfterShell, sidePanel };
        """)
        self.assertEqual(out["agentPane"], {"address": "t2", "pinned": False})
        self.assertEqual(out["followAfterAgent"], {"props": "t2"})
        self.assertEqual(out["shellPane"], {"address": "t4", "pinned": False})
        self.assertEqual(out["followAfterShell"], {"props": "t4"})
        self.assertEqual(out["sidePanel"], {"address": "t4", "pinned": False})


class UsageUnchanged(unittest.TestCase):
    """fetchUsage runs every 10 s: when the transcript's size and mtime are what the last run saw, the reader answers
    {unchanged: true} without reading it, and main.js keeps the summary it has. The check runs where the file is, so it
    works for another machine's transcript too."""
    FILE = CLAUDE

    def test_a_first_run_reports_the_files_signature_with_its_turns(self):
        r = run_helper(self.FILE)
        self.assertRegex(r["sig"], r"^\d+:\d+$")
        self.assertEqual(len(r["turns"]), 3)

    def test_the_same_signature_is_unchanged_and_carries_no_turns(self):
        sig = run_helper(self.FILE)["sig"]
        r = run_helper(self.FILE, seen=sig)
        self.assertEqual(r, {"unchanged": True, "sig": sig})

    def test_a_different_signature_reads_the_file_again(self):
        r = run_helper(self.FILE, seen="1:1")
        self.assertNotIn("unchanged", r)
        self.assertEqual(len(r["turns"]), 3)

    def test_a_grown_file_is_read_again(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "s.jsonl"); shutil.copy(self.FILE, f)
            sig = run_helper(f)["sig"]
            with open(f, "ab") as h:
                h.write(b"\n")
            self.assertNotIn("unchanged", run_helper(f, seen=sig))

    def test_main_passes_the_last_signature_and_keeps_the_summary_when_unchanged(self):
        src = (MOD / "main.js").read_text(encoding="utf-8")
        self.assertIn("d.unchanged", src)
        self.assertIn("sig:", src)


class UsageScript(unittest.TestCase):
    """Weak (source only): fetchUsage runs every 10 s; the assembled usage reader is built once and kept."""
    def test_usage_py_is_read_once(self):
        src = (MOD / "main.js").read_text(encoding="utf-8")
        self.assertIn("this.usageScript ||= await this.loadUsageScript()", src)
        self.assertEqual(src.count("assembleReader("), 1)
        body = src[src.index("  fetchUsage("):]
        body = body[:body.index("\n  }\n")]
        self.assertNotIn("readTextFile", body)


if __name__ == "__main__":
    unittest.main()
