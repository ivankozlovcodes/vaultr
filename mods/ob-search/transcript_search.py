# ob-search transcript scan: the user and assistant messages of some session transcripts, as one JSON line.
# Run by main.js through exec("python3", ["-c", <this file's text>, <options json>]). Read-only: it reads only the
# paths it is given. Formats: Claude Code transcripts (type "user"/"assistant"), pi sessions (type "message") and
# pi-subagents transcripts (recordType). The readers follow ob-outline' transcript.py. Tool calls and tool
# output are not searched.
# Options: terms (every term must match, by the rule in kit/fuzzy.js: a strict term, one with a non-letter or five letters
# or more, is a substring or word chunks; a short term is letters in order inside one word or a tight window;
# case-insensitive unless caseSensitive), files
# [{id, path}], maxFiles (60), maxPerFile (200 messages, newest kept), maxBytes (3 MiB read from each file's end),
# budgetMs (6000, then the rest is skipped and "partial" is set), maxText (2000 characters per message: a longer
# message is cut to a window around its hit).
# Output: { v, files: [{ id, path, format, size, truncated, matched, msgs: [{ i, role, ts, text }] } | { id, path,
# error }], skipped, partial, ms }. Never raises.
import json
import os
import re
import sys
import time

T0 = time.monotonic()
try:
    OPT = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
except Exception:
    OPT = {}
TERMS = [str(t) for t in (OPT.get("terms") or []) if str(t)]
CASE = bool(OPT.get("caseSensitive", False))
FILES = [f for f in (OPT.get("files") or []) if isinstance(f, dict) and f.get("path")]
MAX_FILES = int(OPT.get("maxFiles", 60))
MAX_PER_FILE = int(OPT.get("maxPerFile", 200))
MAX_BYTES = int(OPT.get("maxBytes", 3 * 1024 * 1024))
BUDGET = float(OPT.get("budgetMs", 6000)) / 1000.0
MAX_TEXT = int(OPT.get("maxText", 2000))
WORD_RE = re.compile(r"[^\W_]+")  # a word: letters and digits (kit/fuzzy.js: \p{L}\p{N})


# The matching rule of kit/fuzzy.js, term by term (a boolean: the prefilter needs no spans or scores). Keep the two in step:
# test/fixtures/ob-search/match-cases.json is checked by both test files.
def words_of(h):
    return [(m.start(), m.end()) for m in WORD_RE.finditer(h)]


def word_at(words, i):
    for s, e in words:
        if s <= i < e:
            return (s, e)
    return None


def is_strict(t):
    return len(t) >= 5 or any(not c.isalpha() for c in t)


def substring_hit(t, h):
    return t in h


def chunk_in_word(chunk, h, w):
    s, e = w
    if h[s] != chunk[0]:
        return None
    idx, at = [s], s + 1
    for ch in chunk[1:]:
        i = at
        while i < e and h[i] != ch:
            i += 1
        if i >= e:
            return None
        idx.append(i)
        at = i + 1
    return idx


def chunk_chain(chunks, h, words, limit):
    def step(k, prev_end):
        if k == len(chunks):
            return []
        for w in words:
            if prev_end is not None:
                if w[0] <= prev_end:
                    continue
                if w[0] - prev_end - 1 > limit:
                    break
            idx = chunk_in_word(chunks[k], h, w)
            if idx is None:
                continue
            rest = step(k + 1, idx[-1])
            if rest is not None:
                return idx + rest
        return None

    return step(0, None)


def tight_subsequence(t, h, words):
    """-> the start of the first tight match, or -1."""
    for s in range(len(h)):
        if h[s] != t[0]:
            continue
        idx, at, ok = [s], s + 1, True
        for ch in t[1:]:
            i = h.find(ch, at)
            if i < 0:
                ok = False
                break
            idx.append(i)
            at = i + 1
        if not ok:
            return -1  # a letter is missing after here: no later start can find it either
        span = idx[-1] - s + 1
        w = word_at(words, s)
        in_one_word = w is not None and all(i < w[1] for i in idx)
        if in_one_word or span <= 2 * len(t):
            return s
    return -1


def term_at(t, h, cs=False):
    """-> where term t first matches h (an index into h), or -1."""
    if not cs:
        t, h = t.lower(), h.lower()
    if not t:
        return -1
    if substring_hit(t, h):
        return h.find(t)
    if is_strict(t):
        chunks = WORD_RE.findall(t)
        if len(chunks) < 2:
            return -1
        idx = chunk_chain(chunks, h, words_of(h), 2 * len(t))
        return idx[0] if idx else -1
    return tight_subsequence(t, h, words_of(h))


def term_matches(t, h, cs=False):
    return term_at(t, h, cs) >= 0


# A matched message longer than n characters: a window of at most n around a hit, "…" where it was cut, so the
# text ob-search matches again (buildGroups) still holds the hit. The first window that holds every term wins.
def window(text, n):
    if len(text) <= n:
        return text
    starts = sorted(p for p in (term_at(t, text, CASE) for t in TERMS) if p >= 0) or [0]
    body = max(1, n - 2)
    out = None
    for p in starts:
        a = max(0, min(p - body // 4, len(text) - body))
        w = ("…" if a > 0 else "") + text[a:a + body] + ("…" if a + body < len(text) else "")
        if out is None:
            out = w
        if matches(w):
            return w
    return out


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def messages(rows):
    """-> (format, [{role, ts, text}]) in file order. Only user and assistant text."""
    fmt, out = None, []

    def add(role, ts, text):
        if text and text.strip():
            out.append({"role": role, "ts": ts, "text": text})

    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if r.get("recordType"):
            fmt = fmt or "pi-transcript"
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            if r.get("recordType") == "message" and r.get("role") in ("user", "assistant"):
                add(r["role"], ts, r.get("text") or text_of(msg.get("content")))
            continue
        typ = r.get("type")
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        if typ == "session":
            fmt = "pi-session"
            continue
        if typ == "message":
            fmt = fmt or "pi-session"
            role, c = msg.get("role"), msg.get("content")
            if role == "user":
                add("user", ts, text_of(c))
            elif role == "assistant" and isinstance(c, list):
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "text":
                        add("assistant", ts, x.get("text", ""))
            continue
        if typ in ("user", "assistant") and msg:
            fmt = fmt or "claude"
            c = msg.get("content")
            if typ == "user":
                if r.get("isMeta"):
                    continue
                if isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "text" and not x.get("text", "").lstrip().startswith("<system-reminder>"):
                            add("user", ts, x.get("text", ""))
                elif isinstance(c, str) and not c.lstrip().startswith(("<local-command", "<command-", "Caveat:")):
                    add("user", ts, c)
            else:
                for x in c if isinstance(c, list) else []:
                    if isinstance(x, dict) and x.get("type") == "text":
                        add("assistant", ts, x.get("text", ""))
    return fmt, out


def matches(text):
    return all(term_matches(t, text, CASE) for t in TERMS)


def read_rows(path, size):
    with open(path, "rb") as f:
        truncated = size > MAX_BYTES
        if truncated:
            f.seek(size - MAX_BYTES)
        data = f.read().decode("utf-8", "replace")
    lines = data.split("\n")
    if truncated:
        lines = lines[1:]  # the first line is cut
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue  # a malformed line is skipped
        if isinstance(r, dict):
            rows.append(r)
    return truncated, rows


def scan(entry):
    out = {"id": entry.get("id"), "path": entry["path"]}
    try:
        size = os.path.getsize(entry["path"])
    except Exception as e:
        out["error"] = f"can't read: {e.__class__.__name__}"
        return out
    out["size"] = size
    try:
        truncated, rows = read_rows(entry["path"], size)
    except Exception as e:
        out["error"] = f"can't read: {e.__class__.__name__}"
        return out
    fmt, msgs = messages(rows)
    out.update({"format": fmt, "truncated": truncated})
    hits = []
    matched = 0
    for i, m in enumerate(msgs):
        if time.monotonic() - T0 >= BUDGET:
            out["partial"] = True
            break
        if not TERMS or not matches(m["text"]):
            continue
        matched += 1
        hits.append({"i": i, "role": m["role"], "ts": m["ts"], "text": window(m["text"], MAX_TEXT)})
    out["matched"] = matched
    out["msgs"] = hits[::-1][:MAX_PER_FILE]  # newest first
    return out


def main():
    res = {"v": 1, "files": [], "skipped": 0, "partial": False}
    todo = FILES[:MAX_FILES]
    res["skipped"] = len(FILES) - len(todo)
    for k, entry in enumerate(todo):
        if time.monotonic() - T0 >= BUDGET:
            res["partial"] = True
            res["skipped"] += len(todo) - k
            break
        res["files"].append(scan(entry))
    if any(f.get("partial") for f in res["files"]):
        res["partial"] = True
    res["ms"] = int((time.monotonic() - T0) * 1000)
    return res


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        result = {"v": 1, "files": [], "skipped": 0, "partial": False, "error": f"{e.__class__.__name__}: {e}"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
