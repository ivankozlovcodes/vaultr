# ob-subagents transcript reader: one JSONL transcript -> compact turns, as one JSON line.
# Run through exec("python3", ["-c", <this text>, <path>, <max entries>], { on: machine }). Read-only.
# Formats: pi session.jsonl (type "message"), pi-subagents *_transcript.jsonl (recordType), and Claude
# Code transcripts (type "user"/"assistant"). Reads at most the last 3 MiB (first partial line dropped).
import json, os, sys

PATH = sys.argv[1] if len(sys.argv) > 1 else ""
MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 250
CAP = 3 * 1024 * 1024


def clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def summ(args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return clip(args, 300)
    if isinstance(args, dict):
        for k in ("command", "file_path", "path", "pattern", "query", "url", "description", "prompt"):
            if isinstance(args.get(k), str):
                return clip(args[k].replace("\n", " "), 300)
        return clip(json.dumps(args, ensure_ascii=False), 300)
    return clip(args, 300)


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def main():
    out = {"path": PATH, "entries": [], "format": None, "truncated": False, "size": 0}
    try:
        size = os.path.getsize(PATH)
    except Exception as e:
        out["error"] = f"can't read: {e.__class__.__name__}"
        return out
    out["size"] = size
    with open(PATH, "rb") as f:
        if size > CAP:
            f.seek(size - CAP)
            out["truncated"] = True
        data = f.read().decode("utf-8", "replace")
    rows = data.split("\n")
    if out["truncated"]:
        rows = rows[1:]
    E = []
    tools = {}

    def add(kind, **kw):
        e = {"k": kind, **kw}
        E.append(e)
        return e

    for line in rows:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        ts = r.get("ts") or r.get("timestamp")
        # pi-subagents artifact transcript
        if r.get("recordType"):
            out["format"] = out["format"] or "pi-transcript"
            rt = r["recordType"]
            if rt == "message":
                role = r.get("role")
                t = r.get("text") or text_of((r.get("message") or {}).get("content"))
                if role == "user" and t:
                    add("user", text=clip(t, 6000), ts=ts)
                elif role == "assistant" and t:
                    add("assistant", text=clip(t, 8000), ts=ts)
            elif rt == "tool_start":
                tools[r.get("toolCallId")] = add("tool", tool=r.get("toolName"), args=clip(r.get("argsPreview") or summ(r.get("argsPayload")), 300), ts=ts)
            elif rt == "tool_end":
                e = tools.get(r.get("toolCallId"))
                if e is not None:
                    e["error"] = bool(r.get("isError"))
            continue
        typ = r.get("type")
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        # pi session
        if typ == "message":
            out["format"] = out["format"] or "pi-session"
            role = msg.get("role")
            c = msg.get("content")
            if role == "user":
                t = text_of(c)
                if t.strip():
                    add("user", text=clip(t, 6000), ts=ts)
            elif role == "assistant" and isinstance(c, list):
                for x in c:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "text" and x.get("text", "").strip():
                        add("assistant", text=clip(x["text"], 8000), ts=ts)
                    elif x.get("type") == "toolCall":
                        tools[x.get("id")] = add("tool", tool=x.get("name"), args=summ(x.get("arguments")), ts=ts)
            elif role == "toolResult":
                e = tools.get(msg.get("toolCallId"))
                if e is None:
                    e = add("tool", tool=msg.get("toolName"), args="", ts=ts)
                e["result"] = clip(text_of(c), 1500)
                e["error"] = bool(msg.get("isError"))
            continue
        if typ == "session":
            out["format"] = "pi-session"
            add("meta", text=f"session in {r.get('cwd') or '?'}", ts=ts)
            continue
        # Claude Code
        if typ in ("user", "assistant") and msg:
            out["format"] = out["format"] or "claude"
            c = msg.get("content")
            if typ == "user":
                if r.get("isMeta"):
                    continue
                if isinstance(c, list):
                    for x in c:
                        if not isinstance(x, dict):
                            continue
                        if x.get("type") == "tool_result":
                            e = tools.get(x.get("tool_use_id"))
                            if e is not None:
                                e["result"] = clip(text_of(x.get("content")), 1500)
                                e["error"] = bool(x.get("is_error"))
                        elif x.get("type") == "text" and x.get("text", "").strip():
                            t = x["text"]
                            if not t.lstrip().startswith("<system-reminder>"):
                                add("user", text=clip(t, 6000), ts=ts)
                elif isinstance(c, str) and c.strip():
                    if c.lstrip().startswith(("<local-command", "<command-", "Caveat:")):
                        continue
                    add("user", text=clip(c, 6000), ts=ts)
            else:
                for x in c if isinstance(c, list) else []:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "text" and x.get("text", "").strip():
                        add("assistant", text=clip(x["text"], 8000), ts=ts)
                    elif x.get("type") == "tool_use":
                        tools[x.get("id")] = add("tool", tool=x.get("name"), args=summ(x.get("input")), ts=ts)
    if len(E) > MAX:
        out["truncated"] = True
    out["entries"] = E[-MAX:]
    return out


try:
    res = main()
except Exception as e:
    res = {"path": PATH, "entries": [], "error": f"{e.__class__.__name__}: {e}"}
print(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
