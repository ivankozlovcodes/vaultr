# ob scan: pi-subagents runs + Claude Code subagents on THIS machine, as one JSON line.
# Run by ob-feed through exec("python3", ["-c", <this file's text>, <options json>], { on: machine }).
# Read-only: it only reads /proc (on macOS: ps and lsof), ~/.pi, ~/.claude and the pi-subagents temp folder.
# Output: one JSON object {v,host,uid,now,root,runs,terms,touches,errors,ms} (consumed by mods/ob-feed/main.js). Never raises: errors go into "errors".
import json, os, re, sys, time, glob, tempfile, socket, datetime, subprocess

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
# Test hook (test/test_scan_pi.py): a fixture herdr-artifact store folder instead of ~/.herdr/artifacts.
ARTIFACT_STORE = str(OPT.get("artifactStore")) if OPT.get("artifactStore") else None
TOUCHES = {}                                    # agent key -> [touch rows]: term:<terminal> main, a:<id> sub-agent, r:<id> run
HOME = os.path.expanduser("~")
# Test hooks (test/test_scan_pi.py): a fixture home for ~/.claude, and fixed processes instead of /proc.
CHOME = str(OPT.get("claudeHome") or HOME)
PHOME = str(OPT.get("piHome") or HOME)          # test hook: a fixture home for ~/.pi
FIXTURE_PROCS = OPT.get("procs") if isinstance(OPT.get("procs"), list) else None
# Test hook (test/test_scan_pi.py): the output of the macOS process commands ({list, env, cwd}), forcing that path.
PS_FIXTURE = OPT.get("psOutput") if isinstance(OPT.get("psOutput"), dict) else None
ERRORS = []


def clip(s, n):
    if s is None:
        return None
    s = str(s).replace("\r", "").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def short_arg(inp):
    """What a tool touched, briefly: a file's basename, or the first 40 characters of its command or pattern.
    Never tool output: only the tool's input is read."""
    inp = inp if isinstance(inp, dict) else {}
    fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
    if fp:
        return clip(os.path.basename(str(fp)), 40)
    cmd = inp.get("command") or inp.get("pattern") or inp.get("description") or ""
    return clip(str(cmd).strip().split("\n")[0], 40) if cmd else ""


def last_tool_in(recs):
    """The last tool a session transcript called (in its tail), as {tool, args}; None when there is none."""
    last = None
    for r in recs:
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                last = {"tool": c.get("name"), "args": short_arg(c.get("input"))}
    return last


# ---- files the agents touch (paths and ops only: never contents) ----
# A transcript tail gives {path, op, at}: Read -> read, Edit/MultiEdit/NotebookEdit -> edit, Write -> create when the
# path has not been touched before in this tail, else write. pi's lowercase read/edit/write are the same. Per agent at
# most TOUCH_CAP distinct paths (the newest); one path once, with its strongest op and its newest time. A path with a
# `danger` folder in it is never collected (the vault's rule: it holds credentials). Artifact publications come from the
# herdr-artifact store (publisher = the terminal that published it), not from the transcripts.
TOUCH_CAP = 40
PI_READS = 30                                   # pi transcripts read for touches per scan (the time budget)
OP_RANK = {"read": 0, "edit": 1, "write": 2, "create": 3, "publish": 4}
CLAUDE_FILE_TOOLS = {"Read": "read", "Edit": "edit", "MultiEdit": "edit", "NotebookEdit": "edit", "Write": "write"}
PI_FILE_TOOLS = {"read": "read", "edit": "edit", "write": "write"}


def iso_ms(s):
    if not isinstance(s, str):
        return None
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def dangerous(path):
    return any(seg.lower() == "danger" for seg in str(path).split("/"))


def records_of(path, size=65536):
    """A transcript tail's parsed lines (dicts only), oldest first. A malformed line is skipped."""
    recs = []
    for line in tail_lines(path, size):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict):
            recs.append(r)
    return recs


def merge_touch_dicts(*ds):
    """{path: (op, at)} dicts -> one: the strongest op and the newest time per path."""
    out = {}
    for d in ds:
        for p, (o, a) in d.items():
            prev = out.get(p)
            out[p] = (o if prev is None or OP_RANK[o] > OP_RANK[prev[0]] else prev[0], max(a or 0, prev[1] if prev else 0))
    return out


def file_touches(recs):
    """recs: one transcript tail's parsed lines, oldest first. Returns {path: (op, at)}. Tool inputs only: no result
    text and no file content."""
    out, seen = {}, set()
    for r in recs:
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        at = iso_ms(r.get("timestamp"))
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") in CLAUDE_FILE_TOOLS:
                inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                path, op = inp.get("file_path") or inp.get("notebook_path"), CLAUDE_FILE_TOOLS[c["name"]]
            elif c.get("type") == "toolCall" and str(c.get("name", "")).lower() in PI_FILE_TOOLS:
                args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
                path, op = args.get("path") or args.get("file_path"), PI_FILE_TOOLS[str(c["name"]).lower()]
            else:
                continue
            if not isinstance(path, str) or not path or dangerous(path):
                continue
            if op == "write":
                op = "write" if path in seen else "create"
            seen.add(path)
            prev = {path: out[path]} if path in out else {}
            out[path] = merge_touch_dicts(prev, {path: (op, at or 0)})[path]
    return out


def touch_rows(d, cap=TOUCH_CAP):
    """{path: (op, at)} -> the newest `cap` rows, as the payload lists them."""
    rows = [{"path": p, "op": o, "at": a or None} for p, (o, a) in d.items()]
    rows.sort(key=lambda r: -(r["at"] or 0))
    return rows[:cap]


def artifact_store():
    """herdr-artifact's store folder (one <folder>.json per project, each with its artifacts), or None."""
    if ARTIFACT_STORE:
        return ARTIFACT_STORE if os.path.isdir(ARTIFACT_STORE) else None
    for d in (os.path.join(HOME, ".herdr", "artifacts"), os.path.join(HOME, ".local", "share", "shepherdr", "artifacts")):
        if os.path.isdir(d):
            return d
    return None


def artifact_touches():
    """{terminal address: [row]}: the newest version of each artifact a terminal published (its publisher), as op
    "publish" with the artifact's id, title and version. Its path is the version's folder in the store."""
    d = artifact_store()
    out = {}
    if not d:
        return out
    try:
        names = sorted(os.listdir(d))
    except Exception as e:
        ERRORS.append(f"artifacts: {e}")
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        data = load(os.path.join(d, n))
        arts = data.get("artifacts") if isinstance(data, dict) else None
        for a in arts if isinstance(arts, list) else []:
            if not isinstance(a, dict) or not isinstance(a.get("id"), str):
                continue
            for v in a.get("versions") if isinstance(a.get("versions"), list) else []:
                if not isinstance(v, dict) or not isinstance(v.get("publisher"), str) or not v["publisher"]:
                    continue
                vv = v.get("v") if isinstance(v.get("v"), int) else 0
                row = {"path": os.path.join(d, "files", a["id"][:80], f"v{vv}"), "op": "publish", "at": num(v.get("at")) or None,
                       "artifact": {"id": a["id"][:80], "title": clip(a.get("title"), 120), "v": vv}}
                by = out.setdefault(v["publisher"], {})
                if a["id"] not in by or (row["at"] or 0) > (by[a["id"]]["at"] or 0):
                    by[a["id"]] = row
    return {k: sorted(v.values(), key=lambda r: -(r["at"] or 0))[:TOUCH_CAP] for k, v in out.items()}


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


# ---- the same on macOS (no /proc): ps for start time, name and arguments, ps -E for the environment, lsof for cwd ----
AGENT_NAMES = ("pi", "claude")


def ps_out(key, args):
    if PS_FIXTURE is not None:
        return str(PS_FIXTURE.get(key) or "")
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        ERRORS.append(f"{args[0]}: {e}")
        return ""


def agent_name(ucomm, argv):
    """pi or claude, from the accounting name, else the program a node process runs (pi is a node script)."""
    if ucomm in AGENT_NAMES:
        return ucomm
    for word in argv[:2]:
        base = os.path.basename(word)
        if base in AGENT_NAMES:
            return base
        if ucomm == "node" and "/pi/" in word:
            return "pi"
    return None


def processes_ps():
    found = {}
    for line in ps_out("list", ["ps", "-axww", "-o", "pid=,lstart=,ucomm=,args="]).splitlines():
        f = line.split()
        if len(f) < 7 or not f[0].isdigit():
            continue
        name = agent_name(f[6], f[7:])
        if not name:
            continue
        try:
            start = int(time.mktime(time.strptime(" ".join(f[1:6]), "%a %b %d %H:%M:%S %Y")) * 1000)
        except Exception:
            start = None
        found[int(f[0])] = {"comm": name, "start": start}
    if not found:
        return {}
    pids = ",".join(str(p) for p in found)
    terms = {}
    for line in ps_out("env", ["ps", "-E", "-ww", "-o", "pid=,command=", "-p", pids]).splitlines():
        f = line.split(None, 1)
        m = re.search(r"(?:^|\s)HC_TERMINAL_ID=(\S+)", f[1]) if len(f) == 2 and f[0].isdigit() else None
        if m:
            terms[int(f[0])] = m.group(1)
    cwds, cur = {}, None
    for line in ps_out("cwd", ["lsof", "-a", "-d", "cwd", "-Fn", "-p", pids]).splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = int(line[1:])
        elif line.startswith("n") and cur is not None:
            cwds[cur] = line[1:]
    out = {}
    for pid, p in found.items():
        if pid in terms:
            out[pid] = {"term": terms[pid], "comm": p["comm"], "cwd": cwds.get(pid, ""), "start": p["start"]}
    return out


if FIXTURE_PROCS is not None:
    PROCS = {int(p["pid"]): p for p in FIXTURE_PROCS if isinstance(p, dict) and "pid" in p and "term" in p}
elif PS_FIXTURE is not None or not os.path.isdir("/proc"):
    PROCS = processes_ps()
else:
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
        "tools": [{"tool": t.get("tool"), "args": clip(t.get("args"), 40), "at": t.get("endMs")} for t in tools if isinstance(t, dict)],
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
            d = os.path.join(PHOME, ".pi", "agent", "sessions", "--" + p["cwd"].strip("/").replace("/", "-") + "--")
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


# A Claude Code subagent whose transcript was written this recently is running (live), unless its last
# assistant message ended the turn. A running agent that is silent longer than this shows as not live.
LIVE_MS = 90 * 1000


def claude_view(meta_path):
    """One Claude Code subagent: its meta and its transcript tail (the last 64 KiB). Read-only; a malformed line is
    skipped. Finished and live agents get the same fields; `live` is set from the file's age and `ended`."""
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
    recs = records_of(jl)
    for r in recs:
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        if not msg:
            continue
        mid = msg.get("id")
        if msg.get("model"):
            model = msg["model"]
        # One message is written as several lines (one per content block) with the same usage: count it once.
        if mid is None or mid not in seen_usage:
            if mid is not None:
                seen_usage.add(mid)
            u = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            out_tok += int(u.get("output_tokens") or 0)
        if mid is not None:
            seen_msg.add(mid)
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                last_tool = {"tool": c.get("name"), "args": short_arg(c.get("input"))}
                tool_n += 1
        if msg.get("role") == "assistant":
            if msg.get("stop_reason") == "end_turn":
                ended = True
            else:
                ended = False
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
        "touches": touch_rows(file_touches(recs)),
    }


def claude():
    out = {}
    for pid, p in PROCS.items():
        if p["comm"] != "claude":
            continue
        s = load(os.path.join(CHOME, ".claude", "sessions", f"{pid}.json")) or {}
        sid = s.get("sessionId")
        entry = {"pid": pid, "kind": "claude", "cwd": s.get("cwd") or p["cwd"], "session": sid, "name": s.get("name"), "agents": []}
        if sid:
            dirs = glob.glob(os.path.join(CHOME, ".claude", "projects", "*", sid, "subagents"))
            metas = []
            for d in dirs:
                metas += glob.glob(os.path.join(d, "agent-*.meta.json"))
            metas.sort(key=lambda m: os.stat(m).st_mtime if os.path.exists(m) else 0, reverse=True)
            entry["agents"] = [claude_view(m) for m in metas[:20]]
            for a in entry["agents"]:
                TOUCHES[f"a:{a['id']}"] = a.pop("touches")
            files = glob.glob(os.path.join(CHOME, ".claude", "projects", "*", sid + ".jsonl"))
            entry["transcript"] = files[0] if files else None
            try:
                entry["updatedAt"] = int(os.stat(files[0]).st_mtime * 1000) if files else None
            except OSError:
                entry["updatedAt"] = None
            recs = records_of(files[0]) if files else []
            entry["lastTool"] = last_tool_in(recs) if files else None
            TOUCHES[f"term:{p['term']}"] = touch_rows(file_touches(recs))
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

# pi transcripts: the session file of each pi terminal, and the step transcripts of each run (at most PI_READS).
jobs = []
for key, t in terms.items():
    if t.get("kind") == "pi" and isinstance(t.get("session"), str) and t["session"].endswith(".jsonl"):
        jobs.append((f"term:{key}", t["session"]))
for r in R:
    for st in r.get("steps") or []:
        for k in ("session", "transcript"):
            if isinstance(st.get(k), str) and st[k].endswith(".jsonl"):
                jobs.append((f"r:{r['id']}", st[k]))
pi_acc = {}
for key, path in jobs[:PI_READS]:
    try:
        pi_acc[key] = merge_touch_dicts(pi_acc.get(key, {}), file_touches(records_of(path)))
    except Exception as e:
        ERRORS.append(f"touches: {e}")
for key, d in pi_acc.items():
    TOUCHES[key] = touch_rows(d)
# herdr-artifact publications: listed under the terminal that published them (its address is the terminal's id).
for term_id, rows in artifact_touches().items():
    key = f"term:{term_id}"
    TOUCHES[key] = sorted(TOUCHES.get(key, []) + rows, key=lambda r: -(r["at"] or 0))[:TOUCH_CAP]

print(json.dumps({
    "v": 1,
    "host": socket.gethostname(),
    "uid": os.getuid(),
    "now": NOW,
    "root": ROOT,
    "runs": R,
    "terms": terms,
    "touches": {k: v for k, v in TOUCHES.items() if v},
    "errors": ERRORS,
    "ms": int((time.time() - T0) * 1000),
}, separators=(",", ":")))
