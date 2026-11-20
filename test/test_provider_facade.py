"""Unit tests for kit/provider.js makeProvider facade (every method, caching, error reasons)."""
import home_guard  # noqa: F401
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
PROVIDER_JS = Path(ROOT, "kit", "provider.js")
NODE = shutil.which("node")


def run_facade(js_body):
    code = (
        f'import {{ makeProvider }} from "{PROVIDER_JS.as_uri()}";\n'
        "const main = async () => {\n"
        f"{js_body}\n"
        "};\n"
        'main().then((out) => process.stdout.write(JSON.stringify(out))).catch((e) => {\n'
        '  process.stderr.write(String(e?.stack || e)); process.exit(1);\n'
        "});\n"
    )
    res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(res.stderr)
    return json.loads(res.stdout)


PROVIDERS_SETUP = """
const PROVIDERS = {
  alpha: { id: "alpha", name: "Alpha Agent", noun: "worker", caps: ["title", "prompts", "transcript", "usage", "search", "subagents"] },
  beta: { id: "beta", name: "Beta Runner", noun: "batch", caps: ["subagents", "search", "transcript"] },
  plain: { id: "plain", name: "Plain Tool", noun: "tool", caps: [] },
};
const FILES = {
  "/app/mods/ob-feed/providers/index.json": JSON.stringify(["alpha", "beta", "plain"]),
  "/app/mods/ob-feed/providers/scan_core.py": "def run_scanner_main(): pass\\n",
  "/app/mods/ob-feed/providers/reader_main.py": "def run_reader_main(m): pass\\n",
  "/app/mods/ob-feed/providers/alpha/manifest.json": JSON.stringify(PROVIDERS.alpha),
  "/app/mods/ob-feed/providers/alpha/reader.py": "def sniff(r): return True\\ndef events(r): return []\\n",
  "/app/mods/ob-feed/providers/alpha/scan.py": "pass\\n",
  "/app/mods/ob-feed/providers/beta/manifest.json": JSON.stringify(PROVIDERS.beta),
  "/app/mods/ob-feed/providers/beta/reader.py": "def sniff(r): return False\\ndef events(r): return []\\n",
  "/app/mods/ob-feed/providers/beta/scan.py": "pass\\n",
  "/app/mods/ob-feed/providers/plain/manifest.json": JSON.stringify(PROVIDERS.plain),
  "/app/mods/ob-feed/providers/plain/scan.py": "pass\\n",
};
const readCalls = [];
const execCalls = [];
const readTextFile = async (p) => {
  readCalls.push(p);
  if (Object.prototype.hasOwnProperty.call(FILES, p)) return FILES[p];
  throw new Error("ENOENT: " + p);
};
"""


@unittest.skipUnless(NODE, "node is not installed")
class ProviderFacadeSync(unittest.TestCase):
    def test_list_of_sessions_session_and_subagents(self):
        got = run_facade(PROVIDERS_SETUP + """
const feedData = {
  v: 2,
  providers: PROVIDERS,
  terms: {
    t1: { provider: "alpha", name: "Main alpha", pid: 101, cwd: "/srv/a", session: "s-1", transcript: "/tx/t1.jsonl", updatedAt: 500, lastTool: { tool: "Read", args: "a.py" } },
    "devbox/t2": { provider: "beta", title: "Remote beta", pid: 202, cwd: "/srv/b", session: "/tx/beta.jsonl", sessionGuess: true },
    t3: { provider: "plain", name: "Plain", session: "/ignored/tx.jsonl" },
  },
  runs: [
    { key: "local:r1", machine: null, parent: "t1", provider: "beta", id: "abcdef123456", short: "abcdef12", mode: "chain", state: "running", live: true, startedAt: 10, lastUpdate: 20,
      steps: [{ agent: "scout", label: "Scout step", status: "done", session: "/tx/s0.jsonl", tools: [] },
              { agent: "editor", status: "working", startedAt: 15, session: "/tx/s1.jsonl", tools: [{ tool: "Edit", args: "x.js" }] }] },
    { key: "devbox:r2", machine: "devbox", parent: "devbox/t2", provider: "beta", id: "999900001111", mode: "single", state: "done", live: false, startedAt: 1, endedAt: 9,
      steps: [{ status: "done", transcript: "/tx/r2.jsonl" }] },
  ],
  subagents: [
    { key: "local:a1", machine: null, parent: "t1", provider: "alpha", id: "a1", type: "Explore", desc: "Inspect", live: true, ended: false, updatedAt: 99, transcript: "/tx/a1.jsonl" },
    { key: "devbox:a2", machine: "devbox", parent: "devbox/t2", provider: "alpha", id: "a2", live: false, ended: true, updatedAt: 88 },
  ],
};
const p = makeProvider({ feed: () => feedData, exec: async () => ({ code: 0, stdout: "{}" }), readTextFile, appHome: () => "/app" });
const t1 = p.session("t1");
const t2 = p.session("devbox/t2");
const t3 = p.session("t3");
const ofAlpha = p.of("alpha");
const ofPlain = p.of(t3);
const allSubs = p.subagents();
const t1Subs = p.subagents({ parent: "t1" });
const localSubs = p.subagents({ machine: null });
const boxSubs = p.subagents({ machine: "devbox" });
return {
  ids: p.list().map((x) => x.id),
  canTxAlpha: ofAlpha.can("transcript"),
  canQuotaAlpha: ofAlpha.can("quota"),
  canTxPlain: ofPlain.can("transcript"),
  t1Machine: t1.machine,
  t2Tx: t2.transcript,
  t2Guess: t2.sessionGuess,
  t3Tx: t3.transcript,
  missingSess: p.session("nope"),
  missingOf: p.of("unknown"),
  allKinds: allSubs.map((x) => [x.kind, x.key, x.title, x.provider, x.live, x.ended, x.transcript]),
  t1Keys: t1Subs.map((x) => x.key),
  localKeys: localSubs.map((x) => x.key),
  boxKeys: boxSubs.map((x) => x.key),
  runTool: allSubs.find((x) => x.key === "local:r1").lastTool,
};
""")
        self.assertEqual(got["ids"], ["alpha", "beta", "plain"])
        self.assertTrue(got["canTxAlpha"])
        self.assertFalse(got["canQuotaAlpha"])
        self.assertFalse(got["canTxPlain"])
        self.assertIsNone(got["t1Machine"])
        self.assertEqual(got["t2Tx"], "/tx/beta.jsonl")
        self.assertTrue(got["t2Guess"])
        self.assertIsNone(got["t3Tx"])
        self.assertIsNone(got["missingSess"])
        self.assertIsNone(got["missingOf"])
        self.assertEqual(got["allKinds"], [
            ["run", "local:r1", "Scout step → editor", "beta", True, False, "/tx/s1.jsonl"],
            ["run", "devbox:r2", "batch", "beta", False, True, "/tx/r2.jsonl"],
            ["agent", "local:a1", "Inspect", "alpha", True, False, "/tx/a1.jsonl"],
            ["agent", "devbox:a2", "worker", "alpha", False, True, None],
        ])
        self.assertEqual(got["t1Keys"], ["local:r1", "local:a1"])
        self.assertEqual(got["localKeys"], ["local:r1", "local:a1"])
        self.assertEqual(got["boxKeys"], ["devbox:r2", "devbox:a2"])
        self.assertEqual(got["runTool"], {"tool": "Edit", "args": "x.js"})

    def test_ignores_legacy_kind_guess_and_claude_bucket_fields(self):
        got = run_facade(PROVIDERS_SETUP + """
const feedData = {
  v: 2,
  providers: PROVIDERS,
  terms: {
    t1: { kind: "alpha", guess: true, transcript: "/tx/t1.jsonl" },
  },
  claude: [
    { key: "local:a1", machine: null, parent: "t1", id: "a1", live: true },
  ],
  runs: [
    { key: "local:r1", machine: null, parent: "t1", live: true, steps: [] },
  ],
};
const p = makeProvider({ feed: () => feedData, exec: async () => ({ code: 0, stdout: "{}" }), readTextFile, appHome: () => "/app" });
const t1 = p.session("t1");
return {
  t1Provider: t1.provider,
  t1Guess: t1.sessionGuess,
  ofT1: p.of(t1),
  subs: p.subagents().map((x) => [x.key, x.provider]),
};
""")
        self.assertIsNone(got["t1Provider"])
        self.assertFalse(got["t1Guess"])
        self.assertIsNone(got["ofT1"])
        self.assertEqual(got["subs"], [["local:r1", None]])

    def test_session_prompts_gated_by_prompts_cap(self):
        got = run_facade(PROVIDERS_SETUP + """
const feedData = {
  v: 2,
  providers: PROVIDERS,
  terms: {
    t1: { provider: "alpha", name: "With prompts", turns: [{ text: "hello", full: "hello world", ts: 100, extra: "drop" }] },
    t2: { provider: "beta", name: "No prompts cap", turns: [{ text: "hidden", full: "hidden", ts: 200 }] },
    t3: { provider: "plain", name: "Plain", turns: [{ text: "also hidden" }] },
    t4: { name: "No provider", turns: [{ text: "unknown hidden" }] },
    t5: { provider: "alpha", name: "Empty turns" },
  },
};
const p = makeProvider({ feed: () => feedData, exec: async () => ({ code: 0, stdout: "{}" }), readTextFile, appHome: () => "/app" });
const s1 = p.session("t1");
return {
  canAlpha: p.of(s1)?.can("prompts"),
  canBeta: p.of(p.session("t2"))?.can("prompts"),
  t1Prompts: s1.prompts,
  t1ItemKeys: Object.keys(s1.prompts[0]).sort(),
  hasTurns: ["t1", "t2", "t3", "t4", "t5"].map((id) => Object.hasOwn(p.session(id), "turns")),
  t2Prompts: p.session("t2").prompts,
  t3Prompts: p.session("t3").prompts,
  t4Prompts: p.session("t4").prompts,
  t5Prompts: p.session("t5").prompts,
};
""")
        self.assertTrue(got["canAlpha"])
        self.assertFalse(got["canBeta"])
        self.assertEqual(got["t1Prompts"], [{"step": None, "text": "hello", "full": "hello world", "ts": 100}])
        self.assertEqual(got["t1ItemKeys"], ["full", "step", "text", "ts"])
        self.assertEqual(got["hasTurns"], [False, False, False, False, False])
        self.assertEqual(got["t2Prompts"], [])
        self.assertEqual(got["t3Prompts"], [])
        self.assertEqual(got["t4Prompts"], [])
        self.assertEqual(got["t5Prompts"], [])


@unittest.skipUnless(NODE, "node is not installed")
class ProviderFacadeAsync(unittest.TestCase):
    def test_transcript_entries_find_caching_and_errors(self):
        got = run_facade(PROVIDERS_SETUP + """
const feedData = {
  v: 2,
  providers: PROVIDERS,
  terms: {
    t1: { provider: "alpha", transcript: "/tx/t1.jsonl" },
    "box/t2": { provider: "plain", session: "/tx/p.jsonl" },
    t4: { provider: "alpha" },
  },
  subagents: [
    { key: "box:a1", machine: "box", parent: "box/t9", provider: "alpha", id: "abc123", transcript: null },
  ],
};
const exec = async (cmd, args, opts) => {
  execCalls.push({ cmd, args, opts });
  if (args.includes("--find")) {
    return { code: 0, stdout: JSON.stringify({ path: "/tx/found-abc123.jsonl" }) };
  }
  if (args.includes("/tx/missing.jsonl")) {
    return { code: 0, stdout: JSON.stringify({ path: "/tx/missing.jsonl", entries: [], error: "can't read: FileNotFoundError" }) };
  }
  if (args.includes("/tx/boom.jsonl")) {
    return { code: 1, stdout: "", stderr: "trace\\nSyntaxError: bad" };
  }
  return { code: 0, stdout: JSON.stringify({ path: args[2], entries: [{ k: "user", text: "hi" }], format: "alpha", truncated: false, size: 12 }) };
};
const p = makeProvider({ feed: () => feedData, exec, readTextFile, appHome: () => "/app" });
const ok1 = await p.transcript("t1", { limit: 100 });
const ok2 = await p.transcript("t1", { limit: 50 });
const found = await p.transcript({ id: "abc123", machine: "box", provider: "alpha" });
const unsup = await p.transcript("box/t2");
const noPath = await p.transcript("t4");
const cantRead = await p.transcript("/tx/missing.jsonl");
const crashed = await p.transcript("/tx/boom.jsonl");
const readsBeforeDrop = readCalls.filter((x) => x.endsWith("/reader_main.py")).length;
p.dropCache();
const ok3 = await p.transcript("t1");
const readsAfterDrop = readCalls.filter((x) => x.endsWith("/reader_main.py")).length;
return {
  ok1, ok2, found, unsup, noPath, cantRead, crashed,
  readsBeforeDrop, readsAfterDrop,
  findOn: execCalls[2].opts.on,
  findArgs: execCalls[2].args.slice(2),
  execArgs1: execCalls[0].args.slice(2),
};
""")
        self.assertTrue(got["ok1"]["ok"])
        self.assertEqual(got["ok1"]["entries"], [{"k": "user", "text": "hi"}])
        self.assertTrue(got["ok2"]["ok"])
        self.assertEqual(got["found"], {"ok": True, "path": "/tx/found-abc123.jsonl", "found": True})
        self.assertEqual(got["findOn"], "box")
        self.assertEqual(got["findArgs"], ["--find", "abc123", "alpha"])
        self.assertEqual(got["execArgs1"], ["/tx/t1.jsonl", "100", "alpha"])
        self.assertEqual(got["unsup"]["reason"], "unsupported")
        self.assertEqual(got["noPath"]["reason"], "missing")
        self.assertEqual(got["cantRead"]["reason"], "missing")
        self.assertEqual(got["crashed"]["reason"], "failed")
        self.assertEqual(got["readsBeforeDrop"], 1, "assembled reader script should be cached")
        self.assertEqual(got["readsAfterDrop"], 2, "dropCache clears assembled reader cache")

    def test_usage_search_quota_and_scan(self):
        got = run_facade(PROVIDERS_SETUP + """
const feedData = {
  v: 2,
  providers: PROVIDERS,
  terms: {
    t1: { provider: "alpha", name: "Alpha 1", transcript: "/tx/t1.jsonl" },
    "box/t2": { provider: "alpha", name: "Remote", transcript: "/tx/rem.jsonl" },
    t3: { provider: "plain", name: "Plain", transcript: "/tx/plain.jsonl" },
  },
  runs: [
    { key: "local:r1", machine: null, parent: "t1", provider: "beta", id: "r1", steps: [{ agent: "scout", session: "/tx/r1s0.jsonl" }] },
  ],
};
const exec = async (cmd, args, opts) => {
  execCalls.push({ cmd, args, opts });
  const script = args[1];
  if (script.includes('run_reader_main("usage")')) {
    if (args[4] === "sig1") return { code: 0, stdout: JSON.stringify({ unchanged: true, sig: "sig1" }) };
    return { code: 0, stdout: JSON.stringify({ turns: [{ id: "m1", input: 5, output: 10 }], format: "alpha", truncated: false, size: 9, sig: "sig1" }) };
  }
  if (script.includes('run_reader_main("search")')) {
    const req = JSON.parse(args[2]);
    return { code: 0, stdout: JSON.stringify({ v: 1, partial: false, skipped: 0, files: req.files.map((f) => ({ id: f.id, path: f.path, msgs: [{ i: 0, role: "assistant", ts: 10, text: "found secret token here" }] })) }) };
  }
  if (script.includes("run_scanner_main()")) {
    return { code: 0, stdout: JSON.stringify({ runs: [], terms: {}, touches: {} }) };
  }
  return { code: 1, stdout: "", stderr: "unexpected" };
};
const p = makeProvider({ feed: () => feedData, exec, readTextFile, appHome: () => "/app" });
const u1 = await p.usage("t1");
const u2 = await p.usage("t1", { seen: "sig1" });
const uUnsup = await p.usage({ provider: "beta", path: "/tx/beta.jsonl" });
const srch = await p.search("secret");
const qt = await p.quota();
const sc1 = await p.scan(null, { maxAgeH: 12 });
const sc2 = await p.scan("devbox", { maxAgeH: 12 });
const scanCoreReadsBefore = readCalls.filter((x) => x.endsWith("/scan_core.py")).length;
p.dropCache();
const sc3 = await p.scan(null, {});
const scanCoreReadsAfter = readCalls.filter((x) => x.endsWith("/scan_core.py")).length;
return { u1, u2, uUnsup, srch, qt, sc1, sc2, scanCoreReadsBefore, scanCoreReadsAfter, lastScanOn: execCalls[execCalls.length - 2].opts.on };
""")
        self.assertTrue(got["u1"]["ok"])
        self.assertEqual(got["u1"]["sig"], "sig1")
        self.assertTrue(got["u2"]["unchanged"])
        self.assertEqual(got["uUnsup"]["reason"], "unsupported")
        self.assertTrue(got["srch"]["ok"])
        self.assertEqual([g["path"] for g in got["srch"]["groups"]], ["/tx/t1.jsonl", "/tx/r1s0.jsonl"])
        self.assertEqual(got["srch"]["groups"][0]["hits"][0]["role"], "assistant")
        self.assertEqual(got["qt"]["reason"], "unsupported")
        self.assertTrue(got["sc1"]["ok"])
        self.assertEqual(sorted(got["sc1"]["providers"].keys()), ["alpha", "beta", "plain"])
        self.assertEqual(got["lastScanOn"], "devbox")
        self.assertEqual(got["scanCoreReadsBefore"], 1)
        self.assertEqual(got["scanCoreReadsAfter"], 2)

    def test_search_unsupported_and_missing_scripts(self):
        got = run_facade("""
const feedNoSearch = { v: 2, providers: { a: { id: "a", name: "A", noun: "a", caps: ["runs"] } }, terms: {} };
const p1 = makeProvider({ feed: () => feedNoSearch, exec: async () => ({ code: 0, stdout: "{}" }), readTextFile: async () => { throw new Error("ENOENT"); }, appHome: () => "/missing" });
const p2 = makeProvider({ feed: () => ({ v: 2, providers: { q: { id: "q", name: "Q", noun: "q", caps: ["quota", "search", "transcript", "usage"] } }, terms: { t1: { provider: "q", transcript: "/x.jsonl" } } }), exec: async () => { throw new Error("boom"); }, readTextFile: async () => null, appHome: () => "/missing" });
return {
  searchUnsup: await p1.search("hello"),
  quotaMissing: await p2.quota(),
  scanMissing: await p1.scan(),
  txMissingReader: await p2.transcript({ path: "/x.jsonl", provider: "q" }),
  usageMissingReader: await p2.usage({ path: "/x.jsonl", provider: "q" }),
  searchMissingReader: await p2.search("hello"),
};
""")
        self.assertEqual(got["searchUnsup"]["reason"], "unsupported")
        self.assertEqual(got["quotaMissing"]["reason"], "missing")
        self.assertEqual(got["scanMissing"]["reason"], "missing")
        self.assertEqual(got["txMissingReader"]["reason"], "missing")
        self.assertEqual(got["usageMissingReader"]["reason"], "missing")
        self.assertEqual(got["searchMissingReader"]["reason"], "missing")


if __name__ == "__main__":
    unittest.main()
