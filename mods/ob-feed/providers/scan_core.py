# Core scanner orchestration and generic helpers for assembled agent-process scans.
import datetime
import glob
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

T0 = time.time()
NOW = int(T0 * 1000)
try:
    OPT = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
except Exception:
    OPT = {}
MAX_AGE_MS = int(OPT.get("maxAgeH", 24)) * 3600 * 1000
LIMIT = int(OPT.get("limit", 40))
EXTRA = [str(x) for x in (OPT.get("extraRoots") or []) if isinstance(x, str) and x]
ARTIFACT_STORE = str(OPT.get("artifactStore")) if OPT.get("artifactStore") else None
TOUCHES = {}
HOME = os.path.expanduser("~")
FIXTURE_PROCS = OPT.get("procs") if isinstance(OPT.get("procs"), list) else None
PS_FIXTURE = OPT.get("psOutput") if isinstance(OPT.get("psOutput"), dict) else None
PROC_ROOT = str(OPT.get("procRoot") or "/proc")
ERRORS = []

TOUCH_CAP = 40
LIVE_MS = 90 * 1000
OP_RANK = {"read": 0, "edit": 1, "write": 2, "create": 3, "publish": 4}

READERS = {}
PROVIDERS = []
PROVIDER_BY_ID = {}
RUNS_ROOT = None


def register_reader(pid_id, sniff_fn, events_fn, find_subagent_fn=None):
    READERS[pid_id] = {
        "id": pid_id,
        "sniff": sniff_fn,
        "events": events_fn,
        "find_subagent": find_subagent_fn,
    }


def register(spec):
    if not isinstance(spec, dict) or not spec.get("id"):
        return
    pid_id = str(spec["id"])
    PROVIDER_BY_ID[pid_id] = spec
    for i, cur in enumerate(PROVIDERS):
        if cur.get("id") == pid_id:
            PROVIDERS[i] = spec
            break
    else:
        PROVIDERS.append(spec)
    if spec.get("runs_root"):
        global RUNS_ROOT
        RUNS_ROOT = spec["runs_root"]


def clip(s, n):
    if s is None:
        return None
    s = str(s).replace("\r", "").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def headline(text, limit=160):
    if not isinstance(text, str):
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("---") or s.startswith("```"):
            continue
        s = re.sub(r'^[#>*\-\s"]+', "", s).strip()
        if s:
            return clip(" ".join(s.split()), limit)
    return None


def short_model(m):
    if not m:
        return None
    return str(m).split("/")[-1]


def dget(d, k):
    return d.get(k) if isinstance(d, dict) else None


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def iso_ms(s):
    if not isinstance(s, str):
        return None
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def dangerous(path):
    return any(seg.lower() == "danger" for seg in str(path).split("/"))


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


def records_of(path, size=65536):
    recs = []
    for line in tail_lines(path, size):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if isinstance(r, dict):
            recs.append(r)
    return recs


def events_for(pid_id, recs):
    rd = READERS.get(pid_id)
    if rd is not None:
        return rd["events"](recs)
    for r in READERS.values():
        if r["sniff"](recs):
            return r["events"](recs)
    return []


def user_turns_from_events(ev_list):
    grouped = []
    cur_gid = None
    cur_parts = []
    cur_ts = None

    def flush():
        if not cur_parts:
            return
        cleaned = "\n".join(cur_parts).strip()
        if not cleaned or re.match(r"^\s*<hc\b", cleaned):
            return
        short_txt = headline(cleaned, 160)
        if short_txt:
            grouped.append({"text": short_txt, "full": clip(cleaned, 1600), "ts": cur_ts})

    for e in ev_list:
        if e.get("k") != "user" or e.get("is_prompt") is False:
            continue
        txt = e.get("text")
        if not isinstance(txt, str):
            continue
        gid = e.get("turn_group")
        if gid is not None and gid == cur_gid:
            cur_parts.append(txt)
        else:
            flush()
            cur_gid = gid
            cur_parts = [txt]
            cur_ts = e.get("ts")
    flush()
    return grouped[-12:]


def last_tool_from_events(ev_list):
    last = None
    for e in ev_list:
        if e.get("k") == "tool" and not e.get("orphan"):
            args = e.get("short_args") if "short_args" in e else e.get("args")
            last = {"tool": e.get("tool"), "args": args}
    return last


def merge_touch_dicts(*ds):
    out = {}
    for d in ds:
        for p, (o, a) in d.items():
            prev = out.get(p)
            out[p] = (o if prev is None or OP_RANK[o] > OP_RANK[prev[0]] else prev[0], max(a or 0, prev[1] if prev else 0))
    return out


def touches_from_events(ev_list):
    out = {}
    for e in ev_list:
        t = e.get("touch")
        if not t:
            continue
        op, path, at = t
        prev = {path: out[path]} if path in out else {}
        out[path] = merge_touch_dicts(prev, {path: (op, at or 0)})[path]
    return out


def touch_rows(d, cap=TOUCH_CAP):
    rows = [{"path": p, "op": o, "at": a or None} for p, (o, a) in d.items()]
    rows.sort(key=lambda r: -(r["at"] or 0))
    return rows[:cap]


def artifact_store():
    if ARTIFACT_STORE:
        return ARTIFACT_STORE if os.path.isdir(ARTIFACT_STORE) else None
    for d in (os.path.join(HOME, ".herdr", "artifacts"), os.path.join(HOME, ".local", "share", "shepherdr", "artifacts")):
        if os.path.isdir(d):
            return d
    return None


def artifact_touches():
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


def _match_providers(comm, argv):
    matches = []
    for p in PROVIDERS:
        m = p.get("match")
        if m and m(comm, argv):
            matches.append(p)
    return matches


def _confirm_provider(candidates, comm, argv, extra=None):
    text = " ".join(str(x) for x in argv) if isinstance(argv, (list, tuple)) else str(argv or "")
    proc = {"comm": comm, "args": list(argv), "cmdline": text}
    if extra:
        proc.update(extra)
    for p in candidates:
        c = p.get("confirm")
        if c is None or c(proc):
            return p["id"]
    return None


def _match_and_confirm(comm, argv, extra=None):
    return _confirm_provider(_match_providers(comm, argv), comm, argv, extra)


def _boot_ms():
    try:
        with open(os.path.join(PROC_ROOT, "stat")) as f:
            for line in f:
                if line.startswith("btime "):
                    return int(line.split()[1]) * 1000
    except Exception:
        pass
    return 0


BOOT = _boot_ms()
HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _proc_start(pid):
    try:
        with open(os.path.join(PROC_ROOT, str(pid), "stat")) as f:
            rest = f.read().rsplit(")", 1)[1].split()
        return BOOT + int(rest[19]) * 1000 // HZ
    except Exception:
        return None


def _proc_cmdline_info(pid):
    argv = []
    parts = []
    exe = ""
    pdir = os.path.join(PROC_ROOT, str(pid))
    try:
        with open(os.path.join(pdir, "cmdline"), "rb") as f:
            raw = f.read().decode("utf-8", "replace")
        argv = [x for x in raw.split("\0") if x]
        parts.append(" ".join(argv))
    except Exception:
        pass
    try:
        exe = os.readlink(os.path.join(pdir, "exe"))
        parts.append(exe)
        if not argv:
            argv = [exe]
    except Exception:
        pass
    return argv, " ".join(parts), exe


def _processes_proc():
    out = {}
    try:
        pids = [p for p in os.listdir(PROC_ROOT) if p.isdigit()]
    except Exception:
        return out
    for pid in pids:
        try:
            pdir = os.path.join(PROC_ROOT, pid)
            with open(os.path.join(pdir, "comm")) as f:
                comm = f.read().strip()
            if comm != "node" and not _match_providers(comm, [comm]):
                continue
            argv, cmdline_text, exe = _proc_cmdline_info(pid)
            candidates = _match_providers(comm, argv)
            if not candidates:
                continue
            with open(os.path.join(pdir, "environ"), "rb") as f:
                env = f.read().split(b"\0")
            term = None
            for kv in env:
                if kv.startswith(b"HC_TERMINAL_ID="):
                    term = kv.split(b"=", 1)[1].decode()
            if not term:
                continue
            try:
                cwd = os.readlink(os.path.join(pdir, "cwd"))
            except Exception:
                cwd = ""
            pid_id = _confirm_provider(candidates, comm, argv, {
                "pid": int(pid),
                "cmdline": cmdline_text,
                "exe": exe,
                "cwd": cwd,
            })
            if not pid_id:
                continue
            out[int(pid)] = {"term": term, "comm": pid_id, "provider": pid_id, "cwd": cwd, "start": _proc_start(pid)}
        except Exception:
            continue
    return out


def _ps_out(key, args):
    if PS_FIXTURE is not None:
        return str(PS_FIXTURE.get(key) or "")
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        ERRORS.append(f"{args[0]}: {e}")
        return ""


def _processes_ps():
    found = {}
    for line in _ps_out("list", ["ps", "-axww", "-o", "pid=,lstart=,ucomm=,args="]).splitlines():
        f = line.split()
        if len(f) < 7 or not f[0].isdigit():
            continue
        candidates = _match_providers(f[6], f[7:])
        if not candidates:
            continue
        try:
            start = int(time.mktime(time.strptime(" ".join(f[1:6]), "%a %b %d %H:%M:%S %Y")) * 1000)
        except Exception:
            start = None
        found[int(f[0])] = {"comm": f[6], "args": f[7:], "candidates": candidates, "start": start}
    if not found:
        return {}
    pids = ",".join(str(p) for p in found)
    terms = {}
    for line in _ps_out("env", ["ps", "-E", "-ww", "-o", "pid=,command=", "-p", pids]).splitlines():
        f = line.split(None, 1)
        m = re.search(r"(?:^|\s)HC_TERMINAL_ID=(\S+)", f[1]) if len(f) == 2 and f[0].isdigit() else None
        if m:
            terms[int(f[0])] = m.group(1)
    cwds, cur = {}, None
    for line in _ps_out("cwd", ["lsof", "-a", "-d", "cwd", "-Fn", "-p", pids]).splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = int(line[1:])
        elif line.startswith("n") and cur is not None:
            cwds[cur] = line[1:]
    out = {}
    for pid, c in found.items():
        if pid not in terms:
            continue
        cwd = cwds.get(pid, "")
        pid_id = _confirm_provider(c["candidates"], c["comm"], c["args"], {"pid": pid, "cwd": cwd})
        if not pid_id:
            continue
        out[pid] = {"term": terms[pid], "comm": pid_id, "provider": pid_id, "cwd": cwd, "start": c["start"]}
    return out


def discover_procs():
    if FIXTURE_PROCS is not None:
        procs = {}
        for p in FIXTURE_PROCS:
            if not (isinstance(p, dict) and "pid" in p and "term" in p):
                continue
            raw_args = p.get("args") or p.get("cmdline") or p.get("exe") or ""
            argv = list(raw_args) if isinstance(raw_args, (list, tuple)) else str(raw_args).split()
            pid_id = _match_and_confirm(str(p.get("comm") or ""), argv, p)
            if pid_id:
                procs[int(p["pid"])] = {**p, "provider": pid_id}
        return procs
    if PS_FIXTURE is not None or not os.path.isdir(PROC_ROOT):
        return _processes_ps()
    return _processes_proc()


def run_scanner_main():
    procs = discover_procs()
    all_runs = []
    for p in PROVIDERS:
        pid_id = p["id"]
        fn = p.get("runs")
        if fn:
            try:
                res = fn(procs)
                if isinstance(res, list):
                    for r in res:
                        if isinstance(r, dict):
                            r.setdefault("provider", pid_id)
                            all_runs.append(r)
            except Exception as e:
                ERRORS.append(f"runs: {e}")

    terms = {}
    for p in PROVIDERS:
        pid_id = p["id"]
        fn = p.get("sessions")
        if not fn:
            continue
        my_procs = {pid: pr for pid, pr in procs.items() if pr.get("provider") == pid_id or pr.get("comm") == pid_id}
        try:
            res = fn(my_procs, all_runs)
            if isinstance(res, dict):
                sub_fn = p.get("subagents")
                if callable(sub_fn):
                    for entry in res.values():
                        if isinstance(entry, dict) and entry.get("session") and not entry.get("agents"):
                            entry["agents"] = sub_fn(entry)
                for entry in res.values():
                    if isinstance(entry, dict):
                        entry.setdefault("provider", pid_id)
                        for a in entry.get("agents") or []:
                            if isinstance(a, dict):
                                a.setdefault("provider", pid_id)
                terms.update(res)
        except Exception as e:
            ERRORS.append(f"{pid_id}: {e}")

    for term_id, rows in artifact_touches().items():
        key = f"term:{term_id}"
        TOUCHES[key] = sorted(TOUCHES.get(key, []) + rows, key=lambda r: -(r["at"] or 0))[:TOUCH_CAP]

    print(json.dumps({
        "v": 1,
        "host": socket.gethostname(),
        "uid": os.getuid(),
        "now": NOW,
        "root": RUNS_ROOT,
        "runs": all_runs,
        "terms": terms,
        "touches": {k: v for k, v in TOUCHES.items() if v},
        "errors": ERRORS,
        "ms": int((time.time() - T0) * 1000),
    }, separators=(",", ":")))
