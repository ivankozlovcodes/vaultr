# Core transcript reader driver for assembled entries, usage, and search scripts.
import json
import os
import re
import sys
import time

READERS = []
READER_BY_ID = {}
WORD_RE = re.compile(r"[^\W_]+")
TERMS = []
CASE = False


def register_reader(pid_id, sniff_fn, events_fn, find_subagent_fn=None):
    spec = {
        "id": pid_id,
        "sniff": sniff_fn,
        "events": events_fn,
        "find_subagent": find_subagent_fn,
    }
    READER_BY_ID[pid_id] = spec
    for i, cur in enumerate(READERS):
        if cur["id"] == pid_id:
            READERS[i] = spec
            break
    else:
        READERS.append(spec)


def clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _read_rows(path, cap):
    size = os.path.getsize(path)
    truncated = size > cap
    with open(path, "rb") as f:
        if truncated:
            f.seek(size - cap)
        data = f.read().decode("utf-8", "replace")
    lines = data.split("\n")
    if truncated:
        lines = lines[1:]
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return size, truncated, rows


def _decode_rows(rows, provider_id=""):
    if provider_id and provider_id in READER_BY_ID:
        rd = READER_BY_ID[provider_id]
        fmt = rd["sniff"](rows) or provider_id
        return fmt, rd["events"](rows)
    for rd in READERS:
        fmt = rd["sniff"](rows)
        if fmt:
            return fmt, rd["events"](rows)
    return None, []


def _find_subagent(agent_id, provider_id=""):
    if not agent_id or not str(agent_id).isalnum():
        return {"path": None}
    if provider_id and provider_id in READER_BY_ID:
        fn = READER_BY_ID[provider_id].get("find_subagent")
        if callable(fn):
            return {"path": fn(agent_id)}
    for rd in READERS:
        fn = rd.get("find_subagent")
        if callable(fn):
            path = fn(agent_id)
            if path is not None:
                return {"path": path}
    return {"path": None}


def _entries_mode():
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    if len(sys.argv) > 2 and path == "--find":
        pid_id = sys.argv[3] if len(sys.argv) > 3 else ""
        try:
            res = _find_subagent(sys.argv[2], pid_id)
        except Exception as e:
            res = {"path": None, "error": f"{e.__class__.__name__}: {e}"}
        print(json.dumps(res, separators=(",", ":")))
        return

    max_entries = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 250
    pid_id = sys.argv[3] if len(sys.argv) > 3 else ""
    cap = 3 * 1024 * 1024
    out = {"path": path, "entries": [], "format": None, "truncated": False, "size": 0}
    try:
        try:
            size, truncated, rows = _read_rows(path, cap)
        except Exception as e:
            out["error"] = f"can't read: {e.__class__.__name__}"
            print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
            return
        out["size"] = size
        out["truncated"] = truncated
        fmt, evs = _decode_rows(rows, pid_id)
        out["format"] = fmt
        entries = []
        for ev in evs:
            k = ev.get("k")
            ts = ev.get("ts")
            if k == "user":
                entries.append({"k": "user", "text": clip(ev.get("text"), 6000), "ts": ts})
            elif k == "assistant":
                entries.append({"k": "assistant", "text": clip(ev.get("text"), 8000), "ts": ts})
            elif k == "meta":
                if ev.get("text"):
                    entries.append({"k": "meta", "text": ev.get("text"), "ts": ts})
            elif k == "tool":
                entry = {"k": "tool", "tool": ev.get("tool"), "args": clip(ev.get("args") or "", 300), "ts": ts}
                if "result" in ev and ev["result"] is not None:
                    entry["result"] = clip(ev["result"], 1500)
                if "error" in ev:
                    entry["error"] = bool(ev["error"])
                entries.append(entry)
        if len(entries) > max_entries:
            out["truncated"] = True
        out["entries"] = entries[-max_entries:]
    except Exception as e:
        out = {"path": path, "entries": [], "error": f"{e.__class__.__name__}: {e}"}
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


def _usage_mode():
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    cap = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 32 * 1024 * 1024
    seen_sig = sys.argv[3] if len(sys.argv) > 3 else ""
    pid_id = sys.argv[4] if len(sys.argv) > 4 else ""
    out = {"format": None, "size": 0, "truncated": False, "turns": []}
    try:
        try:
            st = os.stat(path)
        except Exception as e:
            out["error"] = f"can't read: {e.__class__.__name__}"
            print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
            return
        size = st.st_size
        out["size"] = size
        out["sig"] = f"{size}:{st.st_mtime_ns}"
        if seen_sig and seen_sig == out["sig"]:
            print(json.dumps({"unchanged": True, "sig": out["sig"]}, ensure_ascii=False, separators=(",", ":")))
            return
        try:
            with open(path, "rb") as f:
                if size > cap:
                    f.seek(size - cap)
                    out["truncated"] = True
                data = f.read().decode("utf-8", "replace")
        except Exception as e:
            out["error"] = f"can't read: {e.__class__.__name__}"
            print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
            return
        lines = data.split("\n")
        if out["truncated"]:
            lines = lines[1:]
        rows = []
        for line in lines:
            if '"usage"' not in line and '"type":"session"' not in line and '"type": "session"' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                rows.append(r)
        _, evs = _decode_rows(rows, pid_id)
        seen = set()
        turns = []
        usage_fmt = None
        for ev in evs:
            u = ev.get("usage")
            if not isinstance(u, dict):
                continue
            model = ev.get("model")
            if model == "<synthetic>":
                continue
            usage_fmt = usage_fmt or ev.get("usage_format")
            tid = ev.get("usage_id") if "usage_id" in ev else ev.get("id")
            if tid is None or tid in seen:
                continue
            seen.add(tid)
            turns.append({
                "id": tid,
                "model": model,
                "input": _num(u.get("input")),
                "output": _num(u.get("output")),
                "cacheRead": _num(u.get("cacheRead")),
                "cacheWrite": _num(u.get("cacheWrite")),
            })
        out["format"] = usage_fmt
        out["turns"] = turns
    except Exception as e:
        out = {"format": None, "size": 0, "truncated": False, "turns": [], "error": f"{e.__class__.__name__}: {e}"}
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


# Fuzzy prefilter matching rule (kept in step with kit/fuzzy.js).
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
            return -1
        span = idx[-1] - s + 1
        w = word_at(words, s)
        in_one_word = w is not None and all(i < w[1] for i in idx)
        if in_one_word or span <= 2 * len(t):
            return s
    return -1


def term_at(t, h, cs=False):
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


def matches(text, terms=None, case=None):
    use_terms = TERMS if terms is None else terms
    use_case = CASE if case is None else case
    return all(term_matches(t, text, use_case) for t in use_terms)


def window(text, n, terms=None, case=None):
    use_terms = TERMS if terms is None else terms
    use_case = CASE if case is None else case
    if len(text) <= n:
        return text
    starts = sorted(p for p in (term_at(t, text, use_case) for t in use_terms) if p >= 0) or [0]
    body = max(1, n - 2)
    out = None
    for p in starts:
        a = max(0, min(p - body // 4, len(text) - body))
        w = ("…" if a > 0 else "") + text[a:a + body] + ("…" if a + body < len(text) else "")
        if out is None:
            out = w
        if matches(w, use_terms, use_case):
            return w
    if len(starts) > 1:
        each = max(1, (n - 2 - 3 * len(starts)) // len(starts))
        pieces = [("…" if p > each // 4 else "") + text[max(0, p - each // 4):max(0, p - each // 4) + each] for p in starts]
        joined = " … ".join(pieces)
        if len(joined) <= n and matches(joined, use_terms, use_case):
            return joined
    return out


def _search_mode():
    global TERMS, CASE
    t0 = time.monotonic()
    try:
        opt = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except Exception:
        opt = {}
    TERMS = [str(t) for t in (opt.get("terms") or []) if str(t)]
    CASE = bool(opt.get("caseSensitive", False))
    files = [f for f in (opt.get("files") or []) if isinstance(f, dict) and f.get("path")]
    max_files = int(opt.get("maxFiles", 60))
    max_per_file = int(opt.get("maxPerFile", 200))
    max_bytes = int(opt.get("maxBytes", 3 * 1024 * 1024))
    budget = float(opt.get("budgetMs", 6000)) / 1000.0
    max_text = int(opt.get("maxText", 2000))

    def scan_file(entry):
        out = {"id": entry.get("id"), "path": entry["path"]}
        try:
            size, truncated, rows = _read_rows(entry["path"], max_bytes)
        except Exception as e:
            out["error"] = f"can't read: {e.__class__.__name__}"
            return out
        out["size"] = size
        fmt, evs = _decode_rows(rows, str(entry.get("providerId") or opt.get("providerId") or ""))
        out.update({"format": fmt, "truncated": truncated})
        msgs = [
            {"role": ev["k"], "ts": ev.get("ts"), "text": ev["text"]}
            for ev in evs
            if ev.get("k") in ("user", "assistant") and ev.get("text") and str(ev["text"]).strip()
        ]
        hits = []
        matched = 0
        for i, m in enumerate(msgs):
            if time.monotonic() - t0 >= budget:
                out["partial"] = True
                break
            if not TERMS or not matches(m["text"], TERMS, CASE):
                continue
            matched += 1
            hits.append({"i": i, "role": m["role"], "ts": m["ts"], "text": window(m["text"], max_text, TERMS, CASE)})
        out["matched"] = matched
        out["msgs"] = hits[::-1][:max_per_file]
        return out

    try:
        res = {"v": 1, "files": [], "skipped": 0, "partial": False}
        todo = files[:max_files]
        res["skipped"] = len(files) - len(todo)
        for k, entry in enumerate(todo):
            if time.monotonic() - t0 >= budget:
                res["partial"] = True
                res["skipped"] += len(todo) - k
                break
            res["files"].append(scan_file(entry))
        if any(f.get("partial") for f in res["files"]):
            res["partial"] = True
        res["ms"] = int((time.monotonic() - t0) * 1000)
    except Exception as e:
        res = {"v": 1, "files": [], "skipped": 0, "partial": False, "error": f"{e.__class__.__name__}: {e}"}
    print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))


def run_reader_main(mode="entries"):
    if mode in ("entries", "viewer"):
        _entries_mode()
    elif mode == "usage":
        _usage_mode()
    elif mode == "search":
        _search_mode()
    else:
        raise ValueError(f"unknown reader mode: {mode}")
