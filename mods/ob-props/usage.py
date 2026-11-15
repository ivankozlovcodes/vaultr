# ob-props usage reader: the per-turn token counts of one agent session transcript, as one JSON line.
# Run by main.js through exec("python3", ["-c", <this file's text>, <path>, <cap bytes>]). Read-only: it reads only
# the path it is given. Formats: Claude Code transcripts (type "assistant", message.usage, message.model) and pi
# sessions (type "message", message.role "assistant", message.usage with input/output/cacheRead/cacheWrite).
# Reads at most the last <cap> bytes (default 32 MiB; the first partial line is dropped when the file is longer).
# A Claude turn is one API response: its content blocks are written as separate entries that repeat its usage, so
# entries are counted once per message id. "<synthetic>" entries (no model call) are not turns.
# Output: { format, size, truncated, turns: [{ id, model, input, output, cacheRead, cacheWrite }], error? }.
# Turns are in file order; the arithmetic (sums, context, share) is in usage.js. Never raises.
import json
import os
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else ""
CAP = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 32 * 1024 * 1024


def num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def main():
    out = {"format": None, "size": 0, "truncated": False, "turns": []}
    try:
        size = os.path.getsize(PATH)
    except Exception as e:
        out["error"] = f"can't read: {e.__class__.__name__}"
        return out
    out["size"] = size
    try:
        with open(PATH, "rb") as f:
            if size > CAP:
                f.seek(size - CAP)
                out["truncated"] = True
            data = f.read().decode("utf-8", "replace")
    except Exception as e:
        out["error"] = f"can't read: {e.__class__.__name__}"
        return out
    rows = data.split("\n")
    if out["truncated"]:
        rows = rows[1:]
    seen = set()
    turns = []
    for line in rows:
        if '"usage"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        u = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
        if u is None:
            continue
        if r.get("type") == "message" and msg.get("role") == "assistant":
            # pi session
            out["format"] = out["format"] or "pi-session"
            tid = msg.get("responseId") or r.get("id")
            t = {"id": tid, "model": msg.get("model"), "input": num(u.get("input")), "output": num(u.get("output")),
                 "cacheRead": num(u.get("cacheRead")), "cacheWrite": num(u.get("cacheWrite"))}
        elif r.get("type") == "assistant":
            # Claude Code
            if msg.get("model") == "<synthetic>":
                continue
            out["format"] = out["format"] or "claude"
            tid = msg.get("id") or r.get("uuid")
            t = {"id": tid, "model": msg.get("model"), "input": num(u.get("input_tokens")), "output": num(u.get("output_tokens")),
                 "cacheRead": num(u.get("cache_read_input_tokens")), "cacheWrite": num(u.get("cache_creation_input_tokens"))}
        else:
            continue
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        turns.append(t)
    out["turns"] = turns
    return out


try:
    res = main()
except Exception as e:
    res = {"format": None, "size": 0, "truncated": False, "turns": [], "error": f"{e.__class__.__name__}: {e}"}
print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
