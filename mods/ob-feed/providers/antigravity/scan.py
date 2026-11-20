# Antigravity process confirmation, session titles, and transcript paths.
# Discovery pattern consulted from herunan/herdr-over9k (MIT, agy-info.py); written fresh, no code copied.
import datetime
from pathlib import Path
import re
import sqlite3

AGY_NAMES = ("agy", "antigravity")
AGY_DIR = os.path.join(HOME, ".gemini", "antigravity-cli")
PRESENCE_DIR = os.path.join(AGY_DIR, "presence")
SUMMARIES_DB = os.path.join(AGY_DIR, "conversation_summaries.db")
BRAIN_DIR = os.path.join(AGY_DIR, "brain")

_UUID_LOCK_RE = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.lock$"
)
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}:?\d{2})?"
)
_LOCK_CACHE = {}


def match(comm, argv):
    if comm in AGY_NAMES:
        return True
    for word in (argv or [])[:2]:
        if os.path.basename(str(word)) in AGY_NAMES:
            return True
    return False


def _lock_uuid(path):
    if not isinstance(path, str) or not path:
        return None
    m = _UUID_LOCK_RE.match(os.path.basename(path))
    if not m:
        return None
    parent = os.path.dirname(path)
    if os.path.normpath(parent) != os.path.normpath(PRESENCE_DIR):
        try:
            if os.path.realpath(parent) != os.path.realpath(PRESENCE_DIR):
                return None
        except OSError:
            return None
    return m.group(1)


def _lsof_paths(pid):
    if PS_FIXTURE is not None and f"lsof:{pid}" in PS_FIXTURE:
        out = str(PS_FIXTURE.get(f"lsof:{pid}") or "")
    else:
        out = _ps_out("lsof", ["lsof", "-p", str(pid), "-Fn"])
    paths = []
    cur = None
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = int(line[1:])
        elif line.startswith("n") and (cur is None or cur == pid):
            paths.append(line[1:])
    return paths


def _fd_paths(pid, proc=None):
    if isinstance(proc, dict) and proc.get("fds") is not None:
        fds = proc.get("fds")
        return [str(x) for x in fds if x] if isinstance(fds, (list, tuple)) else []
    opt_fds = OPT.get("fds")
    if isinstance(opt_fds, dict):
        key = str(pid) if str(pid) in opt_fds else (pid if pid in opt_fds else None)
        if key is not None:
            fds = opt_fds.get(key)
            return [str(x) for x in fds if x] if isinstance(fds, (list, tuple)) else []
    if pid is None:
        return []
    if PS_FIXTURE is not None or not os.path.isdir(PROC_ROOT):
        return _lsof_paths(pid)
    fd_dir = os.path.join(PROC_ROOT, str(pid), "fd")
    try:
        names = sorted(os.listdir(fd_dir))
    except OSError:
        return []
    paths = []
    for name in names:
        try:
            paths.append(os.readlink(os.path.join(fd_dir, name)))
        except OSError:
            continue
    return paths


def _scan_lock(pid, proc=None):
    for path in _fd_paths(pid, proc):
        cid = _lock_uuid(path)
        if cid:
            return cid
    return None


def confirm(proc):
    if not isinstance(proc, dict):
        return False
    pid = proc.get("pid")
    cid = _scan_lock(pid, proc)
    if pid is not None:
        if cid:
            _LOCK_CACHE[pid] = cid
        else:
            _LOCK_CACHE.pop(pid, None)
    return bool(cid)


def _ts_ms(val):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if val <= 0:
            return None
        return int(val * 1000) if val < 1e11 else int(val)
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    m = _TS_RE.match(s)
    if not m:
        return None
    date_part, time_part, frac, tz = m.groups()
    frac_us = (frac or "")[:6].ljust(6, "0")
    if not tz or tz == "Z":
        tz_norm = "+00:00"
    elif ":" not in tz:
        tz_norm = tz[:3] + ":" + tz[3:]
    else:
        tz_norm = tz
    try:
        dt = datetime.datetime.fromisoformat(f"{date_part}T{time_part}.{frac_us}{tz_norm}")
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _summary_of(cid):
    if not cid or not os.path.isfile(SUMMARIES_DB):
        return None, None
    db = None
    try:
        uri = f"{Path(os.path.abspath(SUMMARIES_DB)).as_uri()}?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=1)
        row = db.execute(
            "SELECT title, last_modified_time FROM conversation_summaries WHERE conversation_id = ?",
            (cid,),
        ).fetchone()
    except sqlite3.Error:
        return None, None
    finally:
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass
    if not row:
        return None, None
    raw_title, raw_time = row[0], row[1]
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None
    return title, _ts_ms(raw_time)


def _transcript_of(cid):
    if not cid:
        return None
    p = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
    return p if os.path.isfile(p) else None


def sessions(procs, _all_runs):
    out = {}
    for pid, p in procs.items():
        if isinstance(p, dict) and p.get("fds") is not None:
            cid = _scan_lock(pid, p)
        elif pid in _LOCK_CACHE:
            cid = _LOCK_CACHE[pid]
        else:
            cid = _scan_lock(pid, p)
        if not cid:
            continue
        title, updated_at = _summary_of(cid)
        tx = _transcript_of(cid)
        if updated_at is None and tx:
            try:
                updated_at = int(os.stat(tx).st_mtime * 1000)
            except OSError:
                updated_at = None
        out[p["term"]] = {
            "pid": pid,
            "kind": "antigravity",
            "cwd": p.get("cwd") or "",
            "session": cid,
            "name": title,
            "transcript": tx,
            "updatedAt": updated_at,
            "agents": [],
            "turns": [],
        }
    return out


register({
    "id": "antigravity",
    "match": match,
    "confirm": confirm,
    "sessions": sessions,
    "subagents": None,
    "runs": None,
})
