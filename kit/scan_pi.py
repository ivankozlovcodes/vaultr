# ob scan: pi-subagents runs + Claude Code subagents on THIS machine, as one JSON line.
# Run by ob-feed through exec("python3", ["-c", <this file's text>, <options json>], { on: machine }).
# Read-only: it only reads /proc, ~/.pi, ~/.claude and the pi-subagents temp folder.
# Output: see SPEC.md section 7 ("scan JSON"). Never raises: errors go into "errors".
import json, os, sys, time, glob, tempfile, socket

T0 = time.time()
NOW = int(T0 * 1000)
try:
    OPT = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
except Exception:
    OPT = {}
MAX_AGE_MS = int(OPT.get("maxAgeH", 24)) * 3600 * 1000
LIMIT = int(OPT.get("limit", 40))
CLAUDE = bool(OPT.get("claude", True))
# Test hook (ob-feed `fixture:<dir>`): extra folders laid out like async-subagent-runs/ (one run dir each).
EXTRA = [str(x) for x in (OPT.get("extraRoots") or []) if isinstance(x, str) and x]
HOME = os.path.expanduser("~")
ERRORS = []


def clip(s, n):
    if s is None:
        return None
    s = str(s).replace("\r", "").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def load(path):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8", "replace"))
    except Exception:
        return None


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


# ---- processes: pid -> {term, comm, cwd, start} for pi and claude with HC_TERMINAL_ID ----
def boot_ms():
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1]) * 1000
    except Exception:
        pass
    return 0


BOOT = boot_ms()
HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def proc_start(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            rest = f.read().rsplit(")", 1)[1].split()
        return BOOT + int(rest[19]) * 1000 // HZ
    except Exception:
        return None


def processes():
    out = {}
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except Exception:
        return out
    for pid in pids:
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm not in ("pi", "claude"):
                continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b"\0")
            term = None
            for kv in env:
                if kv.startswith(b"HC_TERMINAL_ID="):
                    term = kv.split(b"=", 1)[1].decode()
            if not term:
                continue
            out[int(pid)] = {"term": term, "comm": comm, "cwd": os.readlink(f"/proc/{pid}/cwd"), "start": proc_start(pid)}
        except Exception:
            continue
    return out


PROCS = processes()

# ---- pi-subagents async runs ----
ROOT = os.path.join(os.environ.get("PI_SUBAGENTS_TEMP_ROOT") or os.path.join(tempfile.gettempdir(), f"pi-subagents-uid-{os.getuid()}"), "async-subagent-runs")


def short_model(m):
    if not m:
        return None
    return str(m).split("/")[-1]


def dget(d, k):
    """d[k] if d is a dict, else None: status.json fields are trusted to nothing."""
    return d.get(k) if isinstance(d, dict) else None


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def step_view(s, full=None):
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
        "tools": [{"tool": t.get("tool"), "args": clip(t.get("args"), 90), "at": t.get("endMs")} for t in tools if isinstance(t, dict)],
        "out": out,
        "error": clip(pick("error"), 200),
        "session": pick("sessionFile"),
        "transcript": pick("transcriptPath"),
        "runId": s.get("runId"),
    }


def runs():
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
            r = one_run(m, n, p, root)
        except Exception as e:
            ERRORS.append(f"run {n[:8]}: {e}")
            continue
        if r:
            out.append(r)
            if len(out) >= LIMIT:
                break
    # Same parent session, owner gone: borrow the terminal another run of that session maps to.
    by_session = {r["parentSession"]: r["term"] for r in out if r["term"] and r["parentSession"]}
    for r in out:
        if not r["term"] and r["parentSession"] in by_session:
            r["term"] = by_session[r["parentSession"]]
            r["termGuess"] = True
    out.sort(key=lambda r: (not r["live"], -(r["lastUpdate"] or 0)))
    return out


def one_run(m, n, p, root):
    if True:
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
            steps.append(step_view(s, full))
        owner = num(dget(st.get("completionOwnerProcess"), "pid"))
        proc = PROCS.get(owner) if owner else None
        if not proc and st.get("pid") in PROCS:
            proc = PROCS[st["pid"]]
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


# ---- which session file a pi terminal is writing (best effort) ----
def pi_sessions(run_list):
    terms = {}
    for pid, p in PROCS.items():
        if p["comm"] != "pi":
            continue
        t = {"pid": pid, "kind": "pi", "cwd": p["cwd"], "session": None, "guess": True}
        owned = [r for r in run_list if r.get("ownerPid") == pid and r.get("parentSession")]
        if owned:
            t["session"], t["guess"] = owned[0]["parentSession"], False
        else:
            d = os.path.join(HOME, ".pi", "agent", "sessions", "--" + p["cwd"].strip("/").replace("/", "-") + "--")
            try:
                files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
                files = [f for f in files if os.stat(f).st_mtime * 1000 >= (p["start"] or 0) - 5000]
                if files:
                    t["session"] = max(files, key=lambda f: os.stat(f).st_mtime)
            except Exception:
                pass
        terms[p["term"]] = t
    return terms


# ---- Claude Code subagents ----
def tail_lines(path, size=65536):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - size))
            data = f.read().decode("utf-8", "replace")
        lines = data.splitlines()
        return lines[1:] if n > size else lines
    except Exception:
        return []


def claude_view(meta_path):
    meta = load(meta_path) or {}
    aid = os.path.basename(meta_path)[len("agent-"):-len(".meta.json")]
    jl = meta_path[: -len(".meta.json")] + ".jsonl"
    try:
        st = os.stat(jl)
        updated, size = int(st.st_mtime * 1000), st.st_size
    except Exception:
        updated, size = None, 0
    last_tool, out_tok, started, model, ended = None, 0, None, None, False
    for line in tail_lines(jl):
        try:
            r = json.loads(line)
        except Exception:
            continue
        msg = r.get("message") or {}
        if isinstance(msg, dict):
            if msg.get("model"):
                model = msg["model"]
            u = msg.get("usage") or {}
            out_tok += int(u.get("output_tokens") or 0)
            for c in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    arg = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("description") or ""
                    last_tool = {"tool": c.get("name"), "args": clip(arg, 90)}
            if msg.get("stop_reason") == "end_turn" and msg.get("role") == "assistant":
                ended = True
            elif msg.get("role") == "assistant":
                ended = False
    if meta.get("finished") is True:
        ended = True
    return {
        "id": aid,
        "type": meta.get("agentType"),
        "desc": clip(meta.get("description"), 120),
        "model": short_model(model) or meta.get("model"),
        "updatedAt": updated,
        "bytes": size,
        "lastTool": last_tool,
        "outTokens": out_tok or None,
        "ended": ended,
        "transcript": jl,
    }


def claude():
    out = {}
    for pid, p in PROCS.items():
        if p["comm"] != "claude":
            continue
        s = load(os.path.join(HOME, ".claude", "sessions", f"{pid}.json")) or {}
        sid = s.get("sessionId")
        entry = {"pid": pid, "kind": "claude", "cwd": s.get("cwd") or p["cwd"], "session": sid, "name": s.get("name"), "agents": []}
        if sid:
            dirs = glob.glob(os.path.join(HOME, ".claude", "projects", "*", sid, "subagents"))
            metas = []
            for d in dirs:
                metas += glob.glob(os.path.join(d, "agent-*.meta.json"))
            metas.sort(key=lambda m: os.stat(m).st_mtime if os.path.exists(m) else 0, reverse=True)
            entry["agents"] = [claude_view(m) for m in metas[:20]]
            files = glob.glob(os.path.join(HOME, ".claude", "projects", "*", sid + ".jsonl"))
            entry["transcript"] = files[0] if files else None
        out[p["term"]] = entry
    return out


R = []
try:
    R = runs()
except Exception as e:
    ERRORS.append(f"runs: {e}")
terms = {}
try:
    terms.update(pi_sessions(R))
except Exception as e:
    ERRORS.append(f"pi: {e}")
if CLAUDE:
    try:
        terms.update(claude())
    except Exception as e:
        ERRORS.append(f"claude: {e}")

print(json.dumps({
    "v": 1,
    "host": socket.gethostname(),
    "uid": os.getuid(),
    "now": NOW,
    "root": ROOT,
    "runs": R,
    "terms": terms,
    "errors": ERRORS,
    "ms": int((time.time() - T0) * 1000),
}, separators=(",", ":")))
