# pi session and pi-subagents transcript decoder.
import datetime
import json
import os

_FILE_TOOLS = {"read": "read", "edit": "edit", "write": "write"}


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
    recs = first_records or []
    for r in recs:
        if isinstance(r, dict) and r.get("type") == "session":
            return "pi-session"
    for r in recs:
        if not isinstance(r, dict):
            continue
        if r.get("recordType"):
            return "pi-transcript"
        if r.get("type") == "message" and isinstance(r.get("message"), dict):
            return "pi-session"
    return None


def events(records):
    out = []
    tools = {}
    seen_touch = set()
    for rec_i, r in enumerate(records or []):
        if not isinstance(r, dict):
            continue
        ts = r.get("ts") or r.get("timestamp")
        at = _iso_ms(r.get("timestamp"))
        if r.get("recordType"):
            rt = r["recordType"]
            if rt == "message":
                role = r.get("role")
                msg_d = r.get("message") if isinstance(r.get("message"), dict) else {}
                t = r.get("text") or _text_of(msg_d.get("content"))
                if role == "user" and t:
                    out.append({"k": "user", "text": t, "ts": ts, "turn_group": rec_i})
                elif role == "assistant" and t:
                    out.append({"k": "assistant", "text": t, "ts": ts})
            elif rt == "tool_start":
                payload = r.get("argsPayload")
                ev = {
                    "k": "tool",
                    "tool": r.get("toolName"),
                    "args": _clip(r.get("argsPreview") or _summ(payload), 300),
                    "short_args": _short_arg(payload),
                    "ts": ts,
                }
                tools[r.get("toolCallId")] = ev
                out.append(ev)
            elif rt == "tool_end":
                e = tools.get(r.get("toolCallId"))
                if e is not None:
                    e["error"] = bool(r.get("isError"))
            continue

        typ = r.get("type")
        if typ == "session":
            out.append({"k": "meta", "text": f"session in {r.get('cwd') or '?'}", "ts": ts})
            continue
        if typ != "message":
            continue
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        role = msg.get("role")
        c = msg.get("content")
        if role == "user":
            t = _text_of(c)
            if t.strip():
                out.append({"k": "user", "text": t, "ts": ts, "turn_group": rec_i})
        elif role == "assistant":
            u = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
            tid = msg.get("responseId") or r.get("id")
            model = msg.get("model")
            usage = None
            if u is not None:
                usage = {
                    "input": _num(u.get("input")),
                    "output": _num(u.get("output")),
                    "cacheRead": _num(u.get("cacheRead")),
                    "cacheWrite": _num(u.get("cacheWrite")),
                }
            emitted = []
            for x in c if isinstance(c, list) else []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "text" and isinstance(x.get("text"), str) and x["text"].strip():
                    emitted.append({"k": "assistant", "text": x["text"], "ts": ts, "id": tid, "model": model})
                elif x.get("type") == "toolCall":
                    name = x.get("name")
                    args_obj = x.get("arguments")
                    ev = {
                        "k": "tool",
                        "tool": name,
                        "args": _summ(args_obj),
                        "short_args": _short_arg(args_obj),
                        "ts": ts,
                        "id": tid,
                        "model": model,
                    }
                    op = _FILE_TOOLS.get(str(name or "").lower())
                    if op:
                        a = args_obj if isinstance(args_obj, dict) else {}
                        fp = a.get("path") or a.get("file_path")
                        if isinstance(fp, str) and fp and not _dangerous(fp):
                            if op == "write":
                                op = "write" if fp in seen_touch else "create"
                            seen_touch.add(fp)
                            ev["touch"] = (op, fp, at or 0)
                    tools[x.get("id")] = ev
                    emitted.append(ev)
            if not emitted and usage is not None:
                emitted.append({"k": "meta", "ts": ts, "id": tid, "model": model})
            if emitted and usage is not None:
                emitted[0]["usage_id"] = tid
                emitted[0]["usage"] = usage
                emitted[0]["usage_format"] = "pi-session"
            out.extend(emitted)
        elif role == "toolResult":
            e = tools.get(msg.get("toolCallId"))
            if e is None:
                e = {"k": "tool", "tool": msg.get("toolName"), "args": "", "ts": ts, "orphan": True}
                out.append(e)
            e["result"] = _text_of(c)
            e["error"] = bool(msg.get("isError"))
    return out
