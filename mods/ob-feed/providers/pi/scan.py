# pi process matching, session discovery, and pi-subagents async runs.
import os
import tempfile

PHOME = str(OPT.get("piHome") or HOME)
PI_READS = 30
PI_MARKERS = ("@mariozechner/pi", "pi-coding-agent", ".pi/", "/node_modules/pi/")
ROOT = os.path.join(
    os.environ.get("PI_SUBAGENTS_TEMP_ROOT") or os.path.join(tempfile.gettempdir(), f"pi-subagents-uid-{os.getuid()}"),
    "async-subagent-runs",
)


def match(comm, argv):
    if comm == "pi":
        return True
    for word in (argv or [])[:2]:
        w = str(word)
        if os.path.basename(w) == "pi":
            return True
        if comm == "node" and ("/pi/" in w or any(m in w for m in PI_MARKERS)):
            return True
    return False


def confirm(proc):
    raw = proc.get("cmdline") or proc.get("args") or proc.get("exe") or ""
    text = " ".join(str(x) for x in raw) if isinstance(raw, (list, tuple)) else str(raw or "")
    exe = str(proc.get("exe") or "")
    if any(m in text or m in exe for m in PI_MARKERS):
        return True
    cwd = proc.get("cwd")
    if isinstance(cwd, str) and cwd:
        slug = "--" + cwd.strip("/").replace("/", "-") + "--"
        if os.path.isdir(os.path.join(PHOME, ".pi", "agent", "sessions", slug)):
            return True
        return False
    return os.path.isdir(os.path.join(PHOME, ".pi", "agent", "sessions"))


def _step_view(s, full=None):
    full = full if isinstance(full, dict) else {}
    pick = lambda k: full.get(k) if full.get(k) is not None else s.get(k)
    name = s.get("sessionName") or ""
    task = name.split(": ", 1)[1] if ": " in name else (s.get("description") if s.get("description") != "[prompt redacted]" else None)
    tools = pick("recentTools")
    tools = tools[-3:] if isinstance(tools, list) else []
    outl = pick("recentOutput")
    out = [clip(l, 160) for l in (outl[-4:] if isinstance(outl, list) else []) if l and str(l).strip()]
    tok = pick("tokens")
    cost = pick("totalCost")
    return {
        "agent": s.get("agent"),
        "label": s.get("label") or s.get("workflowKey"),
        "task": clip(task, 160),
        "status": pick("status"),
        "model": short_model(pick("model")),
        "startedAt": num(pick("startedAt")),
        "endedAt": num(pick("endedAt")),
        "tokens": num(dget(tok, "total")),
        "cost": num(dget(cost, "costUsd")),
        "turns": num(pick("turnCount")),
        "toolCount": num(pick("toolCount")),
        "tools": [{"tool": t.get("tool"), "args": clip(t.get("args"), 40), "at": t.get("endMs")} for t in tools if isinstance(t, dict)],
        "out": out,
        "error": clip(pick("error"), 200),
        "session": pick("sessionFile"),
        "transcript": pick("transcriptPath"),
        "runId": s.get("runId"),
    }


def _one_run(m, n, p, root, procs):
    st = load(p)
    if not isinstance(st, dict) or st.get("parentWorkflowRunId"):
        return None
    state = st.get("state") if isinstance(st.get("state"), str) else "unknown"
    live = state in ("running", "queued")
    if live and num(st.get("pid")) and not alive(st["pid"]):
        state, live = "lost", False
    last = num(st.get("lastUpdate")) or int(m)
    if not live and NOW - last > MAX_AGE_MS:
        return None
    steps = []
    raw_steps = st.get("steps") if isinstance(st.get("steps"), list) else []
    for s in raw_steps:
        if not isinstance(s, dict):
            continue
        full = None
        if isinstance(s.get("runId"), str) and s.get("runId") != st.get("runId") and "/" not in s["runId"]:
            full = load(os.path.join(root, s["runId"], "status.json"))
            # A workflow child's own step carries the per-step numbers (tokens, model, tools).
            if isinstance(full, dict) and isinstance(full.get("steps"), list) and full["steps"] and isinstance(full["steps"][0], dict):
                full = {**full, **{k: v for k, v in full["steps"][0].items() if v is not None}}
        steps.append(_step_view(s, full))
    owner = num(dget(st.get("completionOwnerProcess"), "pid"))
    proc = procs.get(owner) if owner else None
    if not proc and st.get("pid") in procs:
        proc = procs[st["pid"]]
    log = st.get("outputFile") if isinstance(st.get("outputFile"), str) else os.path.join(root, n, "output-0.log")
    tok = st.get("totalTokens")
    cost = st.get("totalCost")
    cur = num(st.get("currentStep"))
    return {
        "id": st.get("runId") if isinstance(st.get("runId"), str) and st.get("runId") else n,
        "mode": st.get("mode"),
        "state": state,
        "live": live,
        "startedAt": num(st.get("startedAt")),
        "endedAt": num(st.get("endedAt")),
        "lastUpdate": last,
        "cwd": st.get("cwd") if isinstance(st.get("cwd"), str) else None,
        "parentSession": st.get("sessionId") if isinstance(st.get("sessionId"), str) else None,
        "ownerPid": owner,
        "term": proc["term"] if proc else None,
        "currentStep": cur,
        "tokens": num(dget(tok, "total")),
        "cost": num(dget(cost, "costUsd")),
        "turns": num(st.get("turnCount")),
        "toolCount": num(st.get("toolCount")),
        "error": clip(st.get("error"), 200),
        "log": log if os.path.exists(log) else None,
        "dir": os.path.join(root, n),
        "steps": steps,
    }


def runs(procs):
    found = []
    for root in [ROOT] + EXTRA:
        try:
            names = os.listdir(root)
        except FileNotFoundError:
            continue
        except Exception as e:
            ERRORS.append(f"runs: {e}")
            continue
        for n in names:
            p = os.path.join(root, n, "status.json")
            try:
                m = os.stat(p).st_mtime * 1000
            except Exception:
                continue
            found.append((m, n, p, root))
    found.sort(reverse=True)
    out = []
    for m, n, p, root in found:
        try:
            r = _one_run(m, n, p, root, procs)
        except Exception as e:
            ERRORS.append(f"run {n[:8]}: {e}")
            continue
        if r:
            out.append(r)
            if len(out) >= LIMIT:
                break
    by_session = {r["parentSession"]: r["term"] for r in out if r["term"] and r["parentSession"]}
    for r in out:
        if not r["term"] and r["parentSession"] in by_session:
            r["term"] = by_session[r["parentSession"]]
            r["termGuess"] = True
    out.sort(key=lambda r: (not r["live"], -(r["lastUpdate"] or 0)))
    return out


def sessions(procs, all_runs):
    terms = {}
    for pid, p in procs.items():
        t = {"pid": pid, "kind": "pi", "cwd": p["cwd"], "session": None, "guess": True, "turns": []}
        owned = [r for r in all_runs if r.get("ownerPid") == pid and r.get("parentSession")]
        if owned:
            t["session"], t["guess"] = owned[0]["parentSession"], False
        else:
            d = os.path.join(PHOME, ".pi", "agent", "sessions", "--" + p["cwd"].strip("/").replace("/", "-") + "--")
            try:
                files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
                files = [f for f in files if os.stat(f).st_mtime * 1000 >= (p["start"] or 0) - 5000]
                if files:
                    t["session"] = max(files, key=lambda f: os.stat(f).st_mtime)
            except Exception:
                pass
        terms[p["term"]] = t

    jobs = []
    for key, t in terms.items():
        if isinstance(t.get("session"), str) and t["session"].endswith(".jsonl"):
            jobs.append((f"term:{key}", t["session"]))
    for r in all_runs:
        for st in r.get("steps") or []:
            for k in ("session", "transcript"):
                if isinstance(st.get(k), str) and st[k].endswith(".jsonl"):
                    jobs.append((f"r:{r['id']}", st[k]))
    pi_acc = {}
    for key, path in jobs[:PI_READS]:
        try:
            evs = events(records_of(path))
            pi_acc[key] = merge_touch_dicts(pi_acc.get(key, {}), touches_from_events(evs))
            if key.startswith("term:") and key[5:] in terms:
                terms[key[5:]]["turns"] = user_turns_from_events(evs)
        except Exception as e:
            ERRORS.append(f"touches: {e}")
    for key, d in pi_acc.items():
        TOUCHES[key] = touch_rows(d)
    return terms


register({
    "id": "pi",
    "match": match,
    "confirm": confirm,
    "sessions": sessions,
    "subagents": None,
    "runs": runs,
    "runs_root": ROOT,
})
