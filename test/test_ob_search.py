"""mods/ob-search: fuzzy matching (node, pure), transcript sources and grouping (node, pure), and the
transcript scan helper (python, run the way ob-search runs it: `python3 -c <text> <options json>`).
Fixtures live in test/fixtures/ob-search and are invented."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import importlib.util
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
MOD = Path(ROOT, "mods", "ob-search")
FUZZY = Path(ROOT, "kit", "fuzzy.js")  # the kit matcher (kit/sync.sh copies it into each mod)
TRANSCRIPTS = MOD / "transcripts.js"
PROVIDERS_DIR = Path(ROOT, "mods", "ob-feed", "providers")
PROVIDER_JS = Path(ROOT, "kit", "provider.js")
HELPER = PROVIDERS_DIR / "reader_main.py"
MAIN = MOD / "main.js"
FIX = Path(ROOT, "test", "fixtures", "ob-search")
CLAUDE_MAIN = FIX / "claude-main.jsonl"
PI_SESSION = FIX / "pi-session.jsonl"
NODE = shutil.which("node")
_SEARCH_CACHE = None


def _assembled_search():
    global _SEARCH_CACHE
    if _SEARCH_CACHE is not None:
        return _SEARCH_CACHE
    if not NODE:
        raise unittest.SkipTest("node is not installed: cannot assemble search reader")
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
        'process.stdout.write(P.assembleReader(read(path.join(cfg.providersDir, "reader_main.py")), readers, "search"));\n'
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", js], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "provider.js failed")
    _SEARCH_CACHE = out.stdout
    return _SEARCH_CACHE


def run_node(body, module=FUZZY):
    """Import a pure mod module in node, run `body` (JS, returns a value), return its JSON."""
    src = (f'import * as M from "{module.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def run_helper(opts):
    """Run assembled search reader the way ob-search does: python3 -c <text> <options json>."""
    text = _assembled_search()
    out = subprocess.run(["python3", "-c", text, json.dumps(opts)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "helper failed")
    return json.loads(out.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node is not installed: the fuzzy matcher test is skipped")
class Fuzzy(unittest.TestCase):
    def test_every_term_is_required(self):
        self.assertIsNone(run_node('return M.matchQuery("deploy zebra", "deploy the site");'))
        self.assertIsNotNone(run_node('return M.matchQuery("site deploy", "deploy the site");'))

    def test_terms_are_split_on_spaces_and_empty_terms_dropped(self):
        self.assertEqual(run_node('return M.terms("  Sync   NOW ");'), ["sync", "now"])

    def test_matching_is_case_insensitive_unless_asked(self):
        self.assertIsNotNone(run_node('return M.matchQuery("DEPLOY", "run deploy script");'))
        self.assertIsNone(run_node('return M.matchQuery("DEPLOY", "run deploy script", { caseSensitive: true });'))

    def test_a_short_term_may_match_letters_in_order_inside_one_word(self):
        self.assertIsNotNone(run_node('return M.matchQuery("nbj", "nightlybackupjob");'))
        self.assertIsNone(run_node('return M.matchQuery("jbn", "nightlybackupjob");'))

    def test_a_short_term_may_not_scatter_letters_across_far_apart_words(self):
        self.assertIsNone(run_node('return M.matchQuery("nbj", "nightly backup job");'))
        self.assertIsNone(run_node('return M.matchQuery("tpc", "The two panels code merges");'))

    def test_contiguous_beats_scattered(self):
        contiguous = run_node('return M.matchQuery("abc", "zzabczz").score;')
        scattered = run_node('return M.matchQuery("abc", "zazbzcz").score;')
        self.assertGreater(contiguous, scattered)

    def test_word_start_beats_mid_word(self):
        word = run_node('return M.matchQuery("sync", "sync now").score;')
        mid = run_node('return M.matchQuery("sync", "resync now").score;')
        self.assertGreater(word, mid)

    def test_empty_query_matches_nothing(self):
        self.assertIsNone(run_node('return M.matchQuery("", "anything at all");'))
        self.assertIsNone(run_node('return M.matchQuery("   ", "anything at all");'))
        self.assertEqual(run_node('return M.terms("");'), [])

    def test_spans_cover_the_matched_letters(self):
        self.assertEqual(run_node('return M.matchQuery("sync", "resync now").spans;'), [[2, 6]])

    def test_ranking_is_by_score_then_recency_and_stable(self):
        items = [
            {"id": "mid", "text": "resync now", "time": 9},     # mid-word hit: lower score, however new
            {"id": "word-old", "text": "sync", "time": 1},      # word start
            {"id": "word-new", "text": "sync", "time": 7},      # same score, newer: first among equals
            {"id": "tie-a", "text": "sync", "time": 3},
            {"id": "tie-b", "text": "sync", "time": 3},         # same score and time as tie-a: input order kept
            {"id": "miss", "text": "nothing here", "time": 99},
        ]
        r = run_node('return M.rankItems(%s, "sync", { text: (x) => x.text, time: (x) => x.time }).map((h) => h.item.id);'
                     % json.dumps(items))
        self.assertNotIn("miss", r)
        self.assertEqual(r[-1], "mid")
        # Equal scores: newer first (7, then 3, 3 in input order, then 1).
        self.assertEqual(r[:4], ["word-new", "tie-a", "tie-b", "word-old"])

    def test_snippet_keeps_the_match_in_view(self):
        text = "x" * 200 + "the release notes" + "y" * 200
        r = run_node('return M.snippet(%s, [[%d, %d]], 40);' % (json.dumps(text), 204, 211))  # "release" at 204
        self.assertIn("release", r["text"])
        self.assertLess(len(r["text"]), 120)
        s, e = r["spans"][0]
        self.assertEqual(r["text"][s:e], "release")


@unittest.skipUnless(NODE, "node is not installed: the transcript source test is skipped")
class Sources(unittest.TestCase):
    def run_search(self, query, feed_data, opts_js="{}", results_fn="() => []"):
        js = (
            f'import {{ makeProvider }} from {json.dumps(PROVIDER_JS.as_uri())};\n'
            'const FILES = {\n'
            '  "/app/mods/ob-feed/providers/index.json": JSON.stringify(["claude", "pi"]),\n'
            '  "/app/mods/ob-feed/providers/reader_main.py": "def run_reader_main(m): pass\\n",\n'
            '  "/app/mods/ob-feed/providers/claude/manifest.json": JSON.stringify({ id: "claude", name: "Claude Code", noun: "Claude agent", caps: ["title", "transcript", "usage", "search", "touches", "subagents"] }),\n'
            '  "/app/mods/ob-feed/providers/claude/reader.py": "def sniff(r): return True\\ndef events(r): return []\\n",\n'
            '  "/app/mods/ob-feed/providers/pi/manifest.json": JSON.stringify({ id: "pi", name: "pi", noun: "pi run", caps: ["transcript", "usage", "search", "touches", "subagents"] }),\n'
            '  "/app/mods/ob-feed/providers/pi/reader.py": "def sniff(r): return False\\ndef events(r): return []\\n",\n'
            '};\n'
            'const seenReq = [];\n'
            'const p = makeProvider({\n'
            f'  feed: () => ({json.dumps(feed_data)}),\n'
            '  readTextFile: async (f) => { if (f in FILES) return FILES[f]; throw new Error("ENOENT"); },\n'
            '  appHome: () => "/app",\n'
            '  exec: async (_cmd, args) => {\n'
            '    const req = JSON.parse(args[2]);\n'
            '    seenReq.push(req);\n'
            f'    const files = ({results_fn})(req.files);\n'
            '    return { code: 0, stdout: JSON.stringify({ v: 1, files, partial: false, skipped: 0 }) };\n'
            '  },\n'
            '});\n'
            f'const out = await p.search({json.dumps(query)}, {opts_js});\n'
            'console.log(JSON.stringify({ out, seenReq }));\n'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)

    FEED = {
        "v": 2,
        "providers": {
            "claude": {"id": "claude", "name": "Claude Code", "noun": "Claude agent", "caps": ["title", "transcript", "usage", "search", "touches", "subagents"]},
            "pi": {"id": "pi", "name": "pi", "noun": "pi run", "caps": ["transcript", "usage", "search", "touches", "subagents"]},
        },
        "terms": {
            "t1": {"provider": "claude", "transcript": "/t/main.jsonl", "name": "Main", "cwd": "/srv/a"},
            "box/t9": {"provider": "pi", "session": "/t/remote.jsonl", "name": "Remote", "cwd": "/srv/b"},
        },
        "subagents": [
            {"key": "k:a1", "machine": None, "parent": "t1", "provider": "claude", "id": "a1", "desc": "Look at the archive", "type": "Explore", "transcript": "/t/sub.jsonl"},
            {"key": "k:a2", "machine": None, "parent": "t1", "provider": "claude", "id": "a2", "desc": "", "type": "general", "transcript": "/t/main.jsonl"},
        ],
        "runs": [
            {"machine": None, "parent": "t1", "provider": "pi", "steps": [{"agent": "scout", "label": "step", "task": "find notes", "session": "/t/pi-child.jsonl", "transcript": None}]},
        ],
    }

    def test_sources_are_local_main_and_subagents_deduplicated(self):
        res = self.run_search("x", self.FEED)
        paths = sorted(s["path"] for s in res["out"]["sources"])
        self.assertEqual(paths, ["/t/main.jsonl", "/t/pi-child.jsonl", "/t/sub.jsonl"])
        main = next(s for s in res["out"]["sources"] if s["path"] == "/t/main.jsonl")
        self.assertEqual(main["kind"], "main")
        self.assertEqual(main["label"], "Main")

    def test_remote_sessions_are_left_out(self):
        res = self.run_search("x", self.FEED)
        self.assertNotIn("/t/remote.jsonl", [s["path"] for s in res["out"]["sources"]])

    def test_scope_keeps_only_the_given_parents(self):
        res = self.run_search("x", self.FEED, '{ parents: new Set(["t2"]) }')
        self.assertEqual(res["out"]["sources"], [])
        self.assertTrue(res["out"]["none"])

    def test_groups_rank_hits_and_apply_the_caps(self):
        results_fn = """(files) => {
          const sub = files.find((f) => f.path === "/t/sub.jsonl");
          return [{
            id: sub.id, path: sub.path,
            msgs: [
              {i: 0, role: "user", ts: 1, text: "look at the archive folder"},
              {i: 1, role: "assistant", ts: 2, text: "The archive has three folders for archive copies."},
              {i: 2, role: "assistant", ts: 3, text: "nothing relevant"},
              {i: 3, role: "user", ts: 4, text: "archive"},
            ],
          }];
        }"""
        res = self.run_search("archive", self.FEED, "{ perGroup: 2, total: 5 }", results_fn)
        r = res["out"]["groups"]
        self.assertEqual(len(r), 1)
        g = r[0]
        self.assertEqual(g["label"], "Look at the archive")
        self.assertEqual(len(g["hits"]), 2)  # per-group cap
        self.assertEqual(g["count"], 3)      # all matches counted
        self.assertIn("archive", g["hits"][0]["snippet"]["text"])
        self.assertIn(g["hits"][0]["role"], ("user", "assistant"))
        capped = self.run_search("archive", self.FEED, "{ perGroup: 2, total: 1 }", results_fn)
        self.assertEqual(sum(len(x["hits"]) for x in capped["out"]["groups"]), 1)  # total cap


class Helper(unittest.TestCase):
    def test_finds_a_hit_in_a_user_message(self):
        r = run_helper({"terms": ["nightly", "backup"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        msgs = r["files"][0]["msgs"]
        self.assertTrue(any(m["role"] == "user" and "nightly backup job" in m["text"] for m in msgs))

    def test_finds_a_hit_in_an_assistant_message(self):
        r = run_helper({"terms": ["archive", "folder"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        msgs = r["files"][0]["msgs"]
        self.assertTrue(any(m["role"] == "assistant" and "archive folder" in m["text"] for m in msgs))

    def test_terms_match_case_insensitively(self):
        r = run_helper({"terms": ["NIGHTLY"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertTrue(r["files"][0]["msgs"])

    def test_scattered_letters_across_words_are_not_hits(self):
        r = run_helper({"terms": ["nbj"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertEqual(r["files"][0]["msgs"], [])

    def test_every_term_must_appear(self):
        r = run_helper({"terms": ["backup", "zebra"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertEqual(r["files"][0]["msgs"], [])

    def test_tool_output_and_system_reminders_are_not_messages(self):
        r = run_helper({"terms": ["backup.tar"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertEqual(r["files"][0]["msgs"], [])
        r = run_helper({"terms": ["reminder"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertEqual(r["files"][0]["msgs"], [])

    def test_survives_a_malformed_line(self):
        r = run_helper({"terms": ["archive"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        f = r["files"][0]
        self.assertNotIn("error", f)
        self.assertGreaterEqual(len(f["msgs"]), 2)

    def test_pi_session_messages_are_found(self):
        r = run_helper({"terms": ["release", "notes"], "files": [{"id": "p", "path": str(PI_SESSION)}]})
        f = r["files"][0]
        self.assertEqual(f["format"], "pi-session")
        self.assertEqual(sorted(m["role"] for m in f["msgs"]), ["assistant", "user"])

    def test_missing_file_is_reported_not_raised(self):
        r = run_helper({"terms": ["x"], "files": [{"id": "gone", "path": os.path.join(tempfile.gettempdir(), "no-such-transcript.jsonl")}]})
        self.assertIn("error", r["files"][0])

    def test_newest_matches_are_kept_per_file_cap(self):
        d = tempfile.mkdtemp(prefix="ob-search-fixture-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "many.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for n in range(10):
                f.write(json.dumps({"type": "user", "timestamp": n, "message": {"role": "user", "content": f"ping number {n}"}}) + "\n")
        r = run_helper({"terms": ["ping"], "maxPerFile": 3, "files": [{"id": "m", "path": p}]})
        f = r["files"][0]
        self.assertEqual(len(f["msgs"]), 3)
        self.assertEqual(f["matched"], 10)
        self.assertIn("number 9", f["msgs"][0]["text"])  # newest first

    def test_file_cap_skips_the_rest(self):
        r = run_helper({"terms": ["archive"], "maxFiles": 1, "files": [{"id": "a", "path": str(CLAUDE_MAIN)}, {"id": "b", "path": str(PI_SESSION)}]})
        self.assertEqual([f["id"] for f in r["files"]], ["a"])
        self.assertEqual(r["skipped"], 1)

    def test_big_file_is_read_from_its_tail_only(self):
        d = tempfile.mkdtemp(prefix="ob-search-fixture-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "big.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "old ping at the start"}}) + "\n")
            filler = json.dumps({"type": "user", "message": {"role": "user", "content": "filler " * 40}}) + "\n"
            for _ in range(2000):
                f.write(filler)
        r = run_helper({"terms": ["ping"], "maxBytes": 64 * 1024, "files": [{"id": "big", "path": p}]})
        f = r["files"][0]
        self.assertTrue(f["truncated"])
        self.assertEqual(f["msgs"], [])  # the old line is outside the tail

    def test_a_hit_past_the_text_cap_is_kept_in_the_returned_window(self):
        # The helper matches the whole message but returns at most maxText characters; ob-search matches that text
        # again (buildGroups), so the window must hold the hit, not just the message's start.
        d = tempfile.mkdtemp(prefix="ob-search-fixture-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "long.jsonl")
        text = "filler " * 600 + "the zanzibar ledger is here" + " tail" * 50
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": 1, "message": {"role": "user", "content": text}}) + "\n")
        r = run_helper({"terms": ["zanzibar", "ledger"], "files": [{"id": "s0", "path": p}]})
        msgs = r["files"][0]["msgs"]
        self.assertEqual(len(msgs), 1)
        self.assertLessEqual(len(msgs[0]["text"]), 2000)
        self.assertIn("zanzibar ledger", msgs[0]["text"])
        if NODE:
            self.assertIsNotNone(run_node("return M.matchQuery('zanzibar ledger', %s);" % json.dumps(msgs[0]["text"])))

    def test_terms_far_apart_in_one_long_message_are_both_kept_in_the_returned_text(self):
        # No single 2000-character window holds both terms: the text is cut around each one and joined, so the
        # re-match in buildGroups still finds the message.
        d = tempfile.mkdtemp(prefix="ob-search-fixture-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "far.jsonl")
        text = "alpha zanzibar here " + "filler " * 700 + "much later the ledger appears " + "tail " * 100
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": 1, "message": {"role": "user", "content": text}}) + "\n")
        r = run_helper({"terms": ["zanzibar", "ledger"], "files": [{"id": "s0", "path": p}]})
        msgs = r["files"][0]["msgs"]
        self.assertEqual(len(msgs), 1)
        self.assertLessEqual(len(msgs[0]["text"]), 2000)
        self.assertIn("zanzibar", msgs[0]["text"])
        self.assertIn("ledger", msgs[0]["text"])
        if NODE:
            self.assertIsNotNone(run_node("return M.matchQuery('zanzibar ledger', %s);" % json.dumps(msgs[0]["text"])))

    def test_a_short_text_is_returned_whole(self):
        r = run_helper({"terms": ["nightly", "backup"], "files": [{"id": "c", "path": str(CLAUDE_MAIN)}]})
        self.assertFalse(any(m["text"].startswith("…") for m in r["files"][0]["msgs"]))

    def test_time_budget_marks_the_result_partial(self):
        r = run_helper({"terms": ["archive"], "budgetMs": 0, "files": [{"id": "a", "path": str(CLAUDE_MAIN)}]})
        self.assertTrue(r["partial"])


CASES = json.loads((FIX / "match-cases.json").read_text(encoding="utf-8"))
HERDR_LINES = ["the herdr-trials session is running", "The two panels' code merges into Outline",
               "it now records which keys it wrote", "I'm explaining why the socket fails"]


@unittest.skipUnless(NODE, "node is not installed: the kit fuzzy test is skipped")
class KitFuzzy(unittest.TestCase):
    """The kit's fuzzy(q, text), which every mod calls (kit.js re-exports it): one matcher, returned as { score, hits }
    (hits: the matched letter indexes, for highlight) or null. An empty query matches with no hits."""

    def test_herdr_trials_does_not_match_letters_scattered_over_unrelated_words(self):
        self.assertIsNone(run_node('return M.fuzzy("herdr-trials", "The two panels\' code merges into Outline");'))

    def test_herdr_trials_matches_its_substring_in_a_switcher_label(self):
        r = run_node('return M.fuzzy("herdr-trials", "Claude Code · herdr-trials");')
        self.assertEqual(r["hits"], list(range(14, 26)))
        self.assertIsInstance(r["score"], (int, float))

    def test_a_short_term_does_not_scatter_over_words(self):
        self.assertIsNone(run_node('return M.fuzzy("nbj", "nightly backup job");'))
        self.assertIsNone(run_node('return M.fuzzy("tpc", "The two panels code merges");'))

    def test_word_chunks_give_the_letters_they_matched(self):
        self.assertEqual(run_node('return M.fuzzy("hd-tr", "herdr-trials").hits;'), [0, 3, 6, 7])

    def test_an_empty_query_matches_with_no_hits(self):
        self.assertEqual(run_node('return M.fuzzy("  ", "anything");'), {"score": 0, "hits": []})


@unittest.skipUnless(NODE, "node is not installed: the fzf-style matcher test is skipped")
class FzfStyle(unittest.TestCase):
    """Long, or non-letter, terms match as a substring or word-prefix chunks; short terms may scatter only
    inside one word or a tight window (span at most twice the term)."""

    def test_a_long_term_with_a_dash_matches_its_substring(self):
        self.assertIsNotNone(run_node('return M.matchQuery("herdr-trials", "the herdr-trials session");'))

    def test_scattered_letters_across_words_do_not_match_a_long_term(self):
        self.assertIsNone(run_node('return M.matchQuery("herdr-trials", "The two panels\' code merges into Outline");'))
        self.assertIsNone(run_node('return M.matchQuery("herdr-trials", "it now records which keys it wrote");'))

    def test_word_prefix_chunks_match(self):
        self.assertIsNotNone(run_node('return M.matchQuery("hd-tr", "herdr-trials");'))
        self.assertIsNone(run_node('return M.matchQuery("hd-tr", "The two panels code");'))

    def test_chunks_keep_their_order(self):
        self.assertIsNone(run_node('return M.matchQuery("trials-herdr", "herdr-trials");'))

    def test_ranking_is_substring_then_chunks_then_tight_subsequence(self):
        sub = run_node('return M.matchQuery("herdr-trials", "herdr-trials").score;')
        chunks = run_node('return M.matchQuery("hd-tr", "herdr-trials").score;')
        tight = run_node('return M.matchQuery("abc", "zazbzcz").score;')
        self.assertGreater(sub, chunks)
        self.assertGreater(chunks, tight)

    def test_spans_are_only_the_matched_letters(self):
        self.assertEqual(run_node('return M.matchQuery("hd-tr", "herdr-trials").spans;'), [[0, 1], [3, 4], [6, 8]])
        self.assertEqual(run_node('return M.matchQuery("herdr-trials", "x herdr-trials y").spans;'), [[2, 14]])

    def test_shared_case_table(self):
        for term, text, want in CASES:
            got = run_node(f'return M.matchQuery({json.dumps(term)}, {json.dumps(text)}) !== null;')
            self.assertEqual(got, want, f"{term!r} in {text!r}")


@unittest.skipUnless(NODE, "node is not installed")
class FzfStyleSwitcherLines(unittest.TestCase):
    def test_only_the_real_line_is_a_hit_for_herdr_trials(self):
        hits = run_node('return %s.filter((t) => M.matchQuery("herdr-trials", t) !== null);' % json.dumps(HERDR_LINES))
        self.assertEqual(hits, [HERDR_LINES[0]])


class TightSubsequenceStopsEarly(unittest.TestCase):
    """A short term whose letter is missing from the text fails at once: a later start cannot find that letter
    either. Searching from every start made a long text quadratic (seconds for a megabyte)."""
    HAY = "ab" * 1000000  # no "z": "abz" can never match

    def test_kit_matcher_gives_up_on_the_first_missing_letter(self):
        if not NODE:
            self.skipTest("node is not installed")
        t0 = time.monotonic()
        self.assertIsNone(run_node('return M.matchQuery("abz", "ab".repeat(1000000));'))
        self.assertLess(time.monotonic() - t0, 3.0)

    def test_python_prefilter_gives_up_on_the_first_missing_letter(self):
        mod = load_helper()
        t0 = time.monotonic()
        self.assertFalse(mod.term_matches("abz", self.HAY))
        self.assertLess(time.monotonic() - t0, 3.0)

    def test_an_earlier_tight_match_still_wins(self):
        mod = load_helper()
        self.assertTrue(mod.term_matches("abz", "xx abz " + "ab" * 50))
        if NODE:
            self.assertIsNotNone(run_node('return M.matchQuery("abz", "xx abz " + "ab".repeat(50));'))


def load_helper():
    spec = importlib.util.spec_from_file_location("transcript_search_under_test", HELPER)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = [saved[0]]  # the helper reads its options from argv at import; none here
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = saved
    return mod


class PrefilterAgreesWithJs(unittest.TestCase):
    def test_python_prefilter_agrees_with_the_shared_table(self):
        spec = importlib.util.spec_from_file_location("transcript_search_under_test", HELPER)
        mod = importlib.util.module_from_spec(spec)
        saved = sys.argv
        sys.argv = [saved[0]]  # the helper reads its options from argv at import; none here
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.argv = saved
        for term, text, want in CASES:
            self.assertEqual(mod.term_matches(term.lower(), text.lower(), False), want, f"{term!r} in {text!r}")

    def test_prefilter_counts_only_real_hits(self):
        d = tempfile.mkdtemp(prefix="ob-search-fixture-")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "herdr.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for n, line in enumerate(HERDR_LINES):
                f.write(json.dumps({"type": "user", "timestamp": n, "message": {"role": "user", "content": line}}) + "\n")
        r = run_helper({"terms": ["herdr-trials"], "files": [{"id": "h", "path": p}]})
        self.assertEqual(r["files"][0]["matched"], 1)
        self.assertEqual(r["files"][0]["msgs"][0]["text"], HERDR_LINES[0])



class RegexAndTranscripts(unittest.TestCase):
    """Transcripts are matched fuzzily only (the helper and buildGroups know no regex). With regex on, the transcript
    search is skipped and the section says so, instead of listing fuzzy hits under a regex query."""

    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_the_transcript_search_is_skipped_while_regex_is_on(self):
        body = self.src[self.src.index("  searchTranscripts(cx, q, gen) {"):]
        body = body[:body.index("cx.spawn(")]
        self.assertRegex(body, r"if \(this\.opts\.regex\) \{ this\.tx = \{[^}]*regex: true")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_only_one_transcript_scan_runs_at_a_time_and_only_the_newest_query_follows_it(self):
        # Typing with pauses used to start a python3 scan per pause, all running at once (exec cannot be cancelled).
        src = (f'import {{ latestOnly }} from "{TRANSCRIPTS.as_uri()}";\n'
               'const log = []; let running = 0, most = 0;\n'
               'const scan = latestOnly(async (cx, job) => { running++; most = Math.max(most, running); log.push(cx + ":" + job);\n'
               '  await new Promise((r) => setTimeout(r, 20)); running--; });\n'
               'const first = scan("a", "q1"); scan("b", "q2"); scan("c", "q3"); scan("d", "q4");\n'
               'await first; await new Promise((r) => setTimeout(r, 80));\n'
               'await scan("e", "q5");\n'
               'console.log(JSON.stringify({ log, most }));')
        out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout)
        self.assertEqual(r["most"], 1)
        # the first query runs, the two in between are dropped, the newest follows (with the first call's context); a later one runs again
        self.assertEqual(r["log"], ["a:q1", "a:q4", "e:q5"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_a_scan_that_throws_does_not_lose_the_waiting_query(self):
        src = (f'import {{ latestOnly }} from "{TRANSCRIPTS.as_uri()}";\n'
               'const log = [];\n'
               'const scan = latestOnly(async (cx, job) => { log.push(job); await new Promise((r) => setTimeout(r, 10)); if (job === "q1") throw new Error("boom"); });\n'
               'const first = scan("a", "q1"); scan("b", "q2");\n'
               'await first; await scan("c", "q3");\n'
               'console.log(JSON.stringify(log));')
        out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), ["q1", "q2", "q3"], "the waiting query runs after a failure, and later ones still run")

    def test_main_runs_the_transcript_scan_through_latestOnly(self):
        self.assertIn("latestOnly(", self.src)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_section_says_transcripts_are_fuzzy_only(self):
        r = run_node('return M.txStatus({ status: "done", groups: [], regex: true });', TRANSCRIPTS)
        self.assertEqual(r, "fuzzy only: regex is on")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_other_states_keep_their_words(self):
        self.assertEqual(run_node('return M.txStatus({ status: "searching", groups: [] });', TRANSCRIPTS), "searching…")
        self.assertEqual(run_node('return M.txStatus({ status: "done", groups: [], none: true });', TRANSCRIPTS),
                         "no agent sessions on this computer")
        self.assertEqual(run_node('return M.txStatus({ status: "done", groups: [], error: "x" });', TRANSCRIPTS), "couldn't search")
        self.assertEqual(run_node('return M.txStatus({ status: "done", groups: [] });', TRANSCRIPTS), "no matches")
        self.assertEqual(run_node('return M.txStatus({ status: "done", groups: [{ count: 2 }, { count: 1 }] });', TRANSCRIPTS),
                         "3 in 2 sessions")

    def test_main_draws_the_status_from_txStatus(self):
        self.assertIn("const status = txStatus(tx);", self.src)


class HelperReadOnce(unittest.TestCase):
    """Transcript search delegates through provider.search() and runs no reader script directly in ob-search."""

    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_the_search_uses_provider_facade(self):
        body = self.src[self.src.index("  async scanTranscripts("):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("await provider.search(", body)
        self.assertNotIn("readTextFile", body)
        self.assertNotIn("exec(", body)

    def test_no_reader_assembly_remains_in_search(self):
        self.assertNotIn("assembleReader", self.src)
        self.assertNotIn("loadProviders", self.src)


class PaneNames(unittest.TestCase):
    """A search group is named by its pane through the kit's one rule (paneLabelOf), like the Sessions and Outline rows."""

    def setUp(self):
        self.src = Path(ROOT, "mods", "ob-search", "main.js").read_text(encoding="utf-8")

    def test_a_group_label_names_its_pane_by_the_kit_rule(self):
        self.assertIn("paneLabelOf(g.pane, tabLabel(g.tab, ps))", self.src)
        self.assertNotIn("paneName(g.pane)", self.src)


if __name__ == "__main__":
    unittest.main()
