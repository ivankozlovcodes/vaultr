"""Boundary rules for the provider facade: no mod (outside kit copies and ob-feed/providers/) names a provider
program, runs a provider script or python3 runner, or reads a feed bucket; kit/*.js names no program either."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import re
import unittest
from pathlib import Path

ROOT = Path(home_guard.ROOT)
PROVIDERS_DIR = ROOT / "mods" / "ob-feed" / "providers"
KIT_DIR = ROOT / "kit"
MODS_DIR = ROOT / "mods"

KIT_NAMES = {p.name for p in KIT_DIR.glob("*.js")}
BUCKETS = ("runs", "subagents", "claude", "terms", "providers")
OB_FEED_MAIN = "mods/ob-feed/main.js"


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_provider_tokens():
    with open(PROVIDERS_DIR / "index.json", encoding="utf-8") as f:
        ids = json.load(f)
    tokens = set()
    for pid in ids:
        with open(PROVIDERS_DIR / pid / "manifest.json", encoding="utf-8") as f:
            m = json.load(f)
        for t in (m.get("id"), str(m.get("id", "")).capitalize(), m.get("name")):
            if t:
                tokens.add(t)
    return sorted(tokens, key=len, reverse=True)


def build_token_re(tokens):
    # Case-sensitive word/camelCase match (so "pi" flags "piRun" and "pi", not "api" or "pipe"; "Pi" flags "Pi", not "Pipe").
    parts = [rf"(?<![A-Za-z]){re.escape(t)}(?![a-z])" for t in tokens]
    return re.compile("(?:" + "|".join(parts) + ")")


def iter_ob_mod_js():
    for mod in sorted(MODS_DIR.glob("ob-*")):
        if not mod.is_dir():
            continue
        for p in sorted(mod.rglob("*")):
            if p.suffix not in (".js", ".mjs") or not p.is_file():
                continue
            rel = p.relative_to(ROOT).as_posix()
            if p.name in KIT_NAMES or "/providers/" in rel:
                continue
            yield rel, read_text(p)


TOKEN_RE = build_token_re(load_provider_tokens())
RUNNER_RE = re.compile(
    r"\b(?:python3|scan_core|reader_main|assembleScanner|assembleReader|loadProviders)\b|providers/"
)
EXEC_CALL_RE = re.compile(r"""\bexec\(\s*(["'])(.*?)\1""")
FORBIDDEN_EXEC_PROGS = {"python", "python3", "bash", "sh", "node"}

SHARED_SUBAGENTS_RE = re.compile(r"""["']ob\.subagents["']""")
ALWAYS_FORBIDDEN_PROP_RE = re.compile(
    r"(?:\?\.|\.)(?:claude|terms|providers)\b"
    r"|(?<!provider)(?:\?\.|\.)subagents\b"
    r'|\[["\'](?:' + "|".join(BUCKETS) + r')["\']\]'
)
FEED_VAR_BUCKET_RE = re.compile(
    r"(?:feed\(\)|(?<![A-Za-z0-9_.])(?:f|body|d|feed)|\.data)\s*(?:\?\.|\.)\s*(?:"
    + "|".join(BUCKETS)
    + r")\b"
    + r"|\{[^}]*\b(?:"
    + "|".join(BUCKETS)
    + r")\b[^}]*\}\s*=\s*(?:feed\(\)|f\b)"
)


class ProviderBoundaries(unittest.TestCase):
    def test_manifest_tokens_non_empty(self):
        tokens = load_provider_tokens()
        self.assertGreaterEqual(len(tokens), 2)
        # Sanity check positive & negative token boundary matches.
        self.assertIsNotNone(TOKEN_RE.search("const x = 'Claude';"))
        self.assertIsNotNone(TOKEN_RE.search("// fallback pi run"))
        self.assertIsNotNone(TOKEN_RE.search("piRun"))
        self.assertIsNone(TOKEN_RE.search("api pipe Pixel"))

    def test_mods_name_no_program(self):
        hits = []
        for rel, text in iter_ob_mod_js():
            for lineno, line in enumerate(text.splitlines(), 1):
                m = TOKEN_RE.search(line)
                if m:
                    hits.append(f"{rel}:{lineno}: {m.group(0)!r} in {line.strip()}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_kit_names_no_program(self):
        hits = []
        for p in sorted(KIT_DIR.glob("*.js")):
            rel = p.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(read_text(p).splitlines(), 1):
                m = TOKEN_RE.search(line)
                if m:
                    hits.append(f"{rel}:{lineno}: {m.group(0)!r} in {line.strip()}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_mods_run_nothing(self):
        hits = []
        for rel, text in iter_ob_mod_js():
            for lineno, line in enumerate(text.splitlines(), 1):
                m = RUNNER_RE.search(line)
                if m:
                    hits.append(f"{rel}:{lineno}: {m.group(0)!r} in {line.strip()}")
                for em in EXEC_CALL_RE.finditer(line):
                    prog = em.group(2)
                    if prog in FORBIDDEN_EXEC_PROGS or "providers/" in prog or TOKEN_RE.search(prog):
                        hits.append(f"{rel}:{lineno}: exec({prog!r}) in {line.strip()}")
        # Within kit/, only provider.js executes provider runners or imports reader/scanner helpers.
        kit_runner_re = re.compile(r"\b(?:python3|assembleScanner|assembleReader|loadProviders)\b")
        for p in sorted(KIT_DIR.glob("*.js")):
            if p.name == "provider.js":
                continue
            rel = p.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(read_text(p).splitlines(), 1):
                code = line.split("//", 1)[0]
                m = kit_runner_re.search(code) or RUNNER_RE.search(code)
                if m:
                    hits.append(f"{rel}:{lineno}: {m.group(0)!r} in {line.strip()}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_mods_read_no_feed_bucket(self):
        hits = []
        for rel, text in iter_ob_mod_js():
            if rel == OB_FEED_MAIN:
                # Publisher methods live before tickerItems(); tickerItems() and everything after it must use provider.*.
                split_marker = "  tickerItems() {"
                self.assertIn(split_marker, text)
                check_text = text[text.index(split_marker):]
                line_offset = text[:text.index(split_marker)].count("\n")
                self.assertIn("provider.subagents(", check_text)
                self.assertIn("provider.sessions(", check_text)
                for pat in (SHARED_SUBAGENTS_RE, ALWAYS_FORBIDDEN_PROP_RE, FEED_VAR_BUCKET_RE):
                    for m in pat.finditer(check_text):
                        lineno = line_offset + check_text.count("\n", 0, m.start()) + 1
                        hits.append(f"{rel}:{lineno}: {m.group(0)!r}")
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for pat in (SHARED_SUBAGENTS_RE, ALWAYS_FORBIDDEN_PROP_RE, FEED_VAR_BUCKET_RE):
                    m = pat.search(line)
                    if m:
                        hits.append(f"{rel}:{lineno}: {m.group(0)!r} in {line.strip()}")
        self.assertEqual(hits, [], "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
