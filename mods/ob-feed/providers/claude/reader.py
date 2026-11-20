# Claude Code transcript format decoder and background subagent locator.
import datetime
import glob
import json
import os

_FILE_TOOLS = {
    "Read": "read",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
}


def _clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _clip_line(s, n):
    if s is None:
        return None
    s = str(s).replace("\r", "").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _iso_ms(s):
    if not isinstance(s, str):
        return None
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def _dangerous(path):
    return any(seg.lower() == "danger" for seg in str(path).split("/"))


def _text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _summ(args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return _clip(args, 300)
    if isinstance(args, dict):
        for k in ("command", "file_path", "path", "pattern", "query", "url", "description", "prompt"):
            if isinstance(args.get(k), str):
                return _clip(args[k].replace("\n", " "), 300)
        return _clip(json.dumps(args, ensure_ascii=False), 300)
    return _clip(args, 300)


def _short_arg(inp):
    inp = inp if isinstance(inp, dict) else {}
    fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
    if fp:
        return _clip_line(os.path.basename(str(fp)), 40)
    cmd = inp.get("command") or inp.get("pattern") or inp.get("description") or ""
    return _clip_line(str(cmd).strip().split("\n")[0], 40) if cmd else ""


def sniff(first_records):
    for r in first_records or []:
        if not isinstance(r, dict) or r.get("recordType"):
            continue
        typ = r.get("type")
        msg = r.get("message") if isinstance(r.get("message"), dict) else None
        if typ in ("user", "assistant") and msg:
            return "claude"
    return None


def events(records):
    out = []
    tools = {}
    seen_touch = set()
    for rec_i, r in enumerate(records or []):
        if not isinstance(r, dict):
            continue
        typ = r.get("type")
        msg = r.get("message") if isinstance(r.get("message"), dict) else None
        if typ not in ("user", "assistant") or not msg:
            continue
        ts = r.get("ts") or r.get("timestamp")
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
                            e["result"] = _text_of(x.get("content"))
                            e["error"] = bool(x.get("is_error"))
                    elif x.get("type") == "text":
                        raw = x.get("text", "")
                        if isinstance(raw, str) and raw.strip() and not raw.lstrip().startswith("<system-reminder>"):
                            out.append({"k": "user", "text": raw, "ts": ts, "turn_group": rec_i})
            elif isinstance(c, str) and c.strip():
                if c.lstrip().startswith(("<local-command", "<command-", "Caveat:")):
                    continue
                out.append({
                    "k": "user",
                    "text": c,
                    "ts": ts,
                    "turn_group": rec_i,
                    "is_prompt": not c.strip().startswith("<system-reminder>"),
                })
            continue

        mid = msg.get("id")
        usage_id = mid or r.get("uuid")
        model = msg.get("model")
        u = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
        usage = None
        if u is not None:
            usage = {
                "input": _num(u.get("input_tokens")),
                "output": _num(u.get("output_tokens")),
                "cacheRead": _num(u.get("cache_read_input_tokens")),
                "cacheWrite": _num(u.get("cache_creation_input_tokens")),
            }
        stop_end = (msg.get("stop_reason") == "end_turn") if msg.get("role") == "assistant" else None
        at = _iso_ms(r.get("timestamp"))
        emitted = []
        for x in c if isinstance(c, list) else []:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "text" and isinstance(x.get("text"), str) and x["text"].strip():
                emitted.append({"k": "assistant", "text": x["text"], "ts": ts, "id": mid, "model": model})
            elif x.get("type") == "tool_use":
                inp = x.get("input") if isinstance(x.get("input"), dict) else {}
                name = x.get("name")
                ev = {
                    "k": "tool",
                    "tool": name,
                    "args": _summ(inp),
                    "short_args": _short_arg(inp),
                    "ts": ts,
                    "id": mid,
                    "model": model,
                }
                op = _FILE_TOOLS.get(name)
                if op:
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(fp, str) and fp and not _dangerous(fp):
                        if op == "write":
                            op = "write" if fp in seen_touch else "create"
                        seen_touch.add(fp)
                        ev["touch"] = (op, fp, at or 0)
                tools[x.get("id")] = ev
                emitted.append(ev)
        if not emitted:
            emitted.append({"k": "meta", "ts": ts, "id": mid, "model": model})
        if stop_end is not None:
            for ev in emitted:
                ev["stop_end"] = stop_end
        emitted[0]["usage_id"] = usage_id
        if usage is not None:
            emitted[0]["usage"] = usage
            emitted[0]["usage_format"] = "claude"
        out.extend(emitted)
    return out


def find_subagent(agent_id):
    hits = sorted(
        glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", "*", "subagents", "agent-" + str(agent_id) + ".jsonl")),
        key=lambda x: os.path.getmtime(x),
        reverse=True,
    )
    return hits[0] if hits else None
