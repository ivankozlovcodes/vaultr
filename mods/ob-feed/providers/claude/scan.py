# Claude Code process matching, session discovery, and subagent inspection.
import glob
import os

CLAUDE_ENABLED = bool(OPT.get("claude", True))
CHOME = str(OPT.get("claudeHome") or HOME)
CLAUDE_MARKERS = ("claude-code", "@anthropic-ai/claude-code", ".claude/")


def match(comm, argv):
    if comm == "claude":
        return True
    for word in (argv or [])[:2]:
        w = str(word)
        if os.path.basename(w) == "claude":
            return True
        if comm == "node" and any(m in w for m in CLAUDE_MARKERS):
            return True
    return False


def confirm(proc):
    raw = proc.get("cmdline") or proc.get("args") or proc.get("exe") or ""
    text = " ".join(str(x) for x in raw) if isinstance(raw, (list, tuple)) else str(raw or "")
    exe = str(proc.get("exe") or "")
    if any(m in text or m in exe for m in CLAUDE_MARKERS):
        return True
    pid = proc.get("pid")
    if pid is not None and os.path.isfile(os.path.join(CHOME, ".claude", "sessions", f"{pid}.json")):
        return True
    return False


def claude_view(meta_path):
    meta = load(meta_path) or {}
    aid = os.path.basename(meta_path)[len("agent-"):-len(".meta.json")]
    jl = meta_path[: -len(".meta.json")] + ".jsonl"
    try:
        st = os.stat(jl)
        updated, size = int(st.st_mtime * 1000), st.st_size
    except Exception:
        updated, size = None, 0
    last_tool, out_tok, tool_n, model, ended = None, 0, 0, None, False
    seen_msg, seen_usage = set(), set()
    evs = events(records_of(jl))
    for ev in evs:
        mid = ev.get("id")
        if ev.get("model"):
            model = ev["model"]
        u = ev.get("usage")
        if isinstance(u, dict) and (mid is None or mid not in seen_usage):
            if mid is not None:
                seen_usage.add(mid)
            out_tok += int(u.get("output") or 0)
        elif mid is not None:
            seen_usage.add(mid)
        if mid is not None:
            seen_msg.add(mid)
        if ev.get("k") == "tool" and not ev.get("orphan"):
            args = ev.get("short_args") if "short_args" in ev else ev.get("args")
            last_tool = {"tool": ev.get("tool"), "args": args}
            tool_n += 1
        if "stop_end" in ev:
            ended = bool(ev["stop_end"])
    if meta.get("finished") is True:
        ended = True
    live = (not ended) and updated is not None and (NOW - updated) < LIVE_MS
    return {
        "id": aid,
        "type": meta.get("agentType"),
        "desc": clip(meta.get("description"), 120),
        "model": short_model(model) or meta.get("model"),
        "updatedAt": updated,
        "bytes": size,
        "lastTool": last_tool,
        "outTokens": out_tok or None,
        "toolCount": tool_n,
        "turns": len(seen_msg),
        "ended": ended,
        "live": live,
        "transcript": jl,
        "touches": touch_rows(touches_from_events(evs)),
    }


def subagents(entry):
    sid = entry.get("session") if isinstance(entry, dict) else None
    if not sid:
        return []
    dirs = glob.glob(os.path.join(CHOME, ".claude", "projects", "*", sid, "subagents"))
    metas = []
    for d in dirs:
        metas += glob.glob(os.path.join(d, "agent-*.meta.json"))
    metas.sort(key=lambda m: os.stat(m).st_mtime if os.path.exists(m) else 0, reverse=True)
    out = []
    for m in metas[:20]:
        a = claude_view(m)
        TOUCHES[f"a:{a['id']}"] = a.pop("touches")
        out.append(a)
    return out


def sessions(procs, _all_runs):
    if not CLAUDE_ENABLED:
        return {}
    out = {}
    for pid, p in procs.items():
        s = load(os.path.join(CHOME, ".claude", "sessions", f"{pid}.json")) or {}
        sid = s.get("sessionId")
        entry = {"pid": pid, "kind": "claude", "cwd": s.get("cwd") or p["cwd"], "session": sid, "name": s.get("name"), "agents": []}
        if sid:
            files = glob.glob(os.path.join(CHOME, ".claude", "projects", "*", sid + ".jsonl"))
            entry["transcript"] = files[0] if files else None
            try:
                entry["updatedAt"] = int(os.stat(files[0]).st_mtime * 1000) if files else None
            except OSError:
                entry["updatedAt"] = None
            evs = events(records_of(files[0])) if files else []
            entry["lastTool"] = last_tool_from_events(evs) if files else None
            TOUCHES[f"term:{p['term']}"] = touch_rows(touches_from_events(evs))
        out[p["term"]] = entry
    return out


register({
    "id": "claude",
    "match": match,
    "confirm": confirm,
    "sessions": sessions,
    "subagents": subagents,
    "runs": None,
})
