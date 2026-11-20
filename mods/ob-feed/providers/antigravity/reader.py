# Antigravity transcript format decoder for entries viewer mode.
# Format notes consulted from tokscale#713 and openusage#1139; written fresh, no code copied.
import json

_SNIFF_SOURCES = ("USER_EXPLICIT", "MODEL", "SYSTEM")
_SNIFF_TYPES = (
    "USER_INPUT",
    "PLANNER_RESPONSE",
    "GENERIC",
    "SYSTEM_MESSAGE",
    "ERROR_MESSAGE",
    "CHECKPOINT",
)
_ARG_KEYS = (
    "CommandLine",
    "command",
    "Path",
    "path",
    "file_path",
    "TargetFile",
    "AbsolutePath",
    "Query",
    "query",
    "pattern",
    "url",
    "Prompt",
    "prompt",
    "description",
    "Message",
)


def _clip(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        for k in ("text", "content", "output", "message", "details"):
            v = c.get(k)
            if isinstance(v, str):
                return v
        if isinstance(c.get("parts"), list):
            return _text_of(c["parts"])
        return ""
    if isinstance(c, list):
        parts = []
        for x in c:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                t = x.get("text") if isinstance(x.get("text"), str) else _text_of(x.get("content"))
                if t:
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _err_text(r):
    err = r.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    if isinstance(err, dict):
        t = _text_of(err).strip()
        return t or json.dumps(err, ensure_ascii=False)
    return ""


def _summ(args):
    if args is None or args == "":
        return ""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return _clip(args.replace("\n", " "), 300)
    if isinstance(args, dict):
        for k in _ARG_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v:
                return _clip(v.replace("\n", " "), 300)
        return _clip(json.dumps(args, ensure_ascii=False), 300)
    return _clip(args, 300)


def _result_of(obj):
    for k in ("result", "output", "response"):
        if k in obj and obj[k] is not None:
            v = obj[k]
            if isinstance(v, str):
                return v
            t = _text_of(v)
            if t:
                return t
            return json.dumps(v, ensure_ascii=False)
    return None


def _tool_info(tc):
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    name = tc.get("name") or tc.get("tool") or tc.get("tool_name") or fn.get("name") or "tool"
    args = tc.get("args")
    if args is None:
        args = tc.get("arguments")
    if args is None:
        args = tc.get("input")
    if args is None:
        args = tc.get("parameters")
    if args is None:
        args = fn.get("arguments")
    tc_id = tc.get("id") or tc.get("call_id") or tc.get("tool_call_id")
    res = _result_of(tc)
    err = bool(tc.get("error") or tc.get("is_error") or tc.get("status") == "ERROR")
    return str(name), _summ(args), tc_id, res, err


def sniff(first_records):
    for r in first_records or []:
        if not isinstance(r, dict):
            continue
        si = r.get("step_index")
        has_step = isinstance(si, int) and not isinstance(si, bool) and si >= 0
        if (has_step and r.get("source") in _SNIFF_SOURCES) or r.get("type") in _SNIFF_TYPES:
            return "antigravity"
    return None


def events(records):
    out = []
    tools_by_id = {}
    pending_tools = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        ts = r.get("created_at") or r.get("ts") or r.get("timestamp")
        src = r.get("source")
        typ = r.get("type")
        has_err = bool(r.get("error") or r.get("is_error") or r.get("status") == "ERROR")

        if typ == "CHECKPOINT":
            continue

        if typ == "USER_INPUT" or (typ is None and src == "USER_EXPLICIT"):
            pending_tools = []
            text = _text_of(r.get("content"))
            if text.strip():
                out.append({"k": "user", "text": text, "ts": ts})
            continue

        if typ == "PLANNER_RESPONSE":
            pending_tools = []
            text = _text_of(r.get("content"))
            if text.strip():
                out.append({"k": "assistant", "text": text, "ts": ts})
            tcs = r.get("tool_calls")
            if isinstance(tcs, list):
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    name, args_s, tc_id, res, tc_err = _tool_info(tc)
                    ev = {"k": "tool", "tool": name, "args": args_s, "ts": ts}
                    if res is not None:
                        ev["result"] = res
                        ev["error"] = bool(tc_err or has_err)
                    else:
                        pending_tools.append(ev)
                    if tc_id is not None:
                        tools_by_id[tc_id] = ev
                    out.append(ev)
            continue

        tc_id = r.get("tool_call_id") or r.get("call_id") or r.get("tool_use_id")
        if tc_id is not None and tc_id in tools_by_id:
            res = _text_of(r.get("content")) if r.get("content") is not None else None
            if not res:
                res = _result_of(r)
            if not res:
                res = _err_text(r)
            ev = tools_by_id[tc_id]
            ev["result"] = res if res is not None else ""
            ev["error"] = has_err
            if ev in pending_tools:
                pending_tools.remove(ev)
            continue

        if src == "MODEL":
            res = _text_of(r.get("content")) if r.get("content") is not None else None
            if not res:
                res = _result_of(r)
            if not res:
                res = _err_text(r)
            if pending_tools:
                ev = pending_tools.pop(0)
                ev["result"] = res if res is not None else ""
                ev["error"] = has_err
            elif isinstance(res, str) and res.strip():
                meta = {"k": "meta", "text": _clip(res.strip(), 200), "ts": ts}
                if has_err:
                    meta["error"] = True
                out.append(meta)
            continue

        if typ == "SYSTEM_MESSAGE":
            text = _text_of(r.get("content")) or _text_of(r.get("message"))
            if text.strip():
                out.append({"k": "meta", "text": _clip(text.strip(), 200), "ts": ts})
            continue

        if typ == "ERROR_MESSAGE":
            text = _err_text(r) or _text_of(r.get("content")).strip() or "error"
            out.append({"k": "meta", "text": _clip(text, 200), "ts": ts, "error": True})
            continue
    return out
