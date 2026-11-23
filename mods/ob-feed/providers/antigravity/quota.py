# Standalone read-only Antigravity CLI plan-quota collector.
# Verifies state directory and binary evidence BEFORE invoking any CLI.

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PATHS = [
    os.path.join(HOME, ".local", "bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
    os.path.join(HOME, ".npm-global", "bin"),
    os.path.join(HOME, ".bun", "bin"),
]
ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
ISO_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}:?\d{2})?"
)

_AGY_PATH_TOKENS = ("antigravity", "antigravity-cli")
_AGY_BYTE_MARKERS = (
    b"antigravity",
    b"antigravity-cli",
    b"conversation_summaries",
    b"cloud_code_endpoint",
    b"remaining_fraction",
)
_AGY_MATCH = {
    "apps": ["antigravity", "agy"],
    "bins": ["agy", "antigravity"],
    "pkgTokens": ["antigravity", "antigravity-cli"],
    "models": ["gemini-"],
}


def now_ms():
    return int(time.time() * 1000)


def _expand(path):
    s = str(path or "").strip()
    if not s:
        return None
    if s == "~":
        return HOME
    if s.startswith("~/") or s.startswith("~\\"):
        return os.path.join(HOME, s[2:])
    return s


def _json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _load_config():
    app_home = _expand(os.environ.get("HERDR_APP_HOME")) or os.path.join(HOME, ".config", "herdr-app")
    cfg = _json_file(os.path.join(app_home, "antigravity.json")) or {}
    state_dir = _expand(os.environ.get("ANTIGRAVITY_CLI_DIR")) or _expand(cfg.get("dir")) or os.path.join(HOME, ".gemini", "antigravity-cli")
    bin_override = _expand(os.environ.get("ANTIGRAVITY_BIN")) or _expand(cfg.get("bin"))
    name = str(cfg.get("name") or "").strip()[:40] or "Antigravity"
    extra_apps = [str(x).strip() for x in (cfg.get("apps") or []) if isinstance(x, str) and x.strip()]
    extra_bins = [str(x).strip() for x in (cfg.get("bins") or []) if isinstance(x, str) and x.strip()]
    return {
        "dir": state_dir,
        "bin": bin_override,
        "name": name,
        "apps": extra_apps,
        "bins": extra_bins,
    }


def which(name):
    if not name:
        return None
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return name if os.path.isfile(name) and os.access(name, os.X_OK) else None
    path = os.pathsep.join([os.environ.get("PATH", "")] + PATHS)
    return shutil.which(name, path=path)


def _quiet(argv):
    return (["nice", "-n", "19"] if shutil.which("nice") else []) + argv


def _file_has_marker(path, markers, chunk_size=65536, overlap=128):
    try:
        with open(path, "rb") as f:
            tail = b""
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    return False
                buf = tail + chunk
                for marker in markers:
                    if marker in buf:
                        return True
                tail = buf[-overlap:] if len(buf) >= overlap else buf
    except OSError:
        return False


def _read_small_shebang_text(path, max_bytes=16384):
    try:
        size = os.path.getsize(path)
        if size < 2 or size > max_bytes:
            return None
        with open(path, "rb") as f:
            data = f.read(max_bytes)
    except OSError:
        return None
    if not data.startswith(b"#!") or b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _looks_like_antigravity(binary, depth=0):
    if not binary:
        return False
    try:
        real = os.path.realpath(binary)
    except OSError:
        real = binary
    low = real.lower()
    if any(tok in low for tok in _AGY_PATH_TOKENS):
        return True
    if _file_has_marker(real, _AGY_BYTE_MARKERS):
        return True
    if depth == 0:
        text = _read_small_shebang_text(real)
        if text:
            for raw_tok in re.findall(r'["\']?(/[^"\'\s]+)["\']?', text):
                if raw_tok.startswith(("/bin/", "/usr/bin/")) and os.path.basename(raw_tok) in ("sh", "bash", "zsh", "env"):
                    continue
                if os.path.isfile(raw_tok) and _looks_like_antigravity(raw_tok, depth=1):
                    return True
    return False


def parse_iso_ms(val):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if val <= 0:
            return None
        return int(val * 1000) if val < 1e11 else int(val)
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    m = ISO_TS_RE.match(s)
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


def _models_from_description(desc):
    s = str(desc or "").strip()
    if not s:
        return []
    m = re.search(r"models?\s+within\s+this\s+group\s*:\s*(.+)$", s, re.I)
    if not m:
        return []
    out = []
    seen = set()
    for part in m.group(1).split(","):
        raw = re.sub(r"\([^)]*\)", "", part).strip().lower()
        if not raw:
            continue
        for cand in (raw, re.sub(r"\s+", "-", raw)):
            if cand and cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def _slug(text, fallback):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s or fallback


def _parse_groups(groups):
    windows = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        g_name = str(g.get("name") or "").strip()
        buckets = g.get("buckets")
        if not isinstance(buckets, list):
            continue
        models = _models_from_description(g.get("description"))
        multi = len(buckets) > 1
        for b in buckets:
            if not isinstance(b, dict):
                continue
            frac = b.get("remaining_fraction")
            if frac is None or isinstance(frac, bool):
                continue
            try:
                rem = round(max(0.0, min(100.0, float(frac) * 100.0)), 1)
            except (TypeError, ValueError):
                continue
            used = round(max(0.0, min(100.0, 100.0 - rem)), 1)
            win = str(b.get("window") or "").strip()
            b_name = str(b.get("name") or "").strip()
            if g_name:
                if win:
                    label = f"{g_name} ({win})"
                elif multi and b_name:
                    label = f"{g_name} · {b_name}"
                else:
                    label = g_name
            else:
                label = b_name or win or f"Pool {len(windows) + 1}"
            label = label[:60]
            wid = str(b.get("id") or "").strip() or _slug(label, f"w{len(windows)}")
            w = {
                "id": wid,
                "label": label,
                "usedPct": used,
                "remainingPct": rem,
            }
            reset_raw = b.get("reset_time")
            reset_at = parse_iso_ms(reset_raw)
            if reset_at is not None:
                w["resetAt"] = reset_at
            elif isinstance(reset_raw, str) and reset_raw.strip():
                w["resets"] = reset_raw.strip()[:60]
            if models:
                w["models"] = models
            windows.append(w)
    return windows


def _parse_tsv_response(text):
    clean = ANSI_RE.sub("", str(text or "")).replace("\r", "")
    windows = []
    for line in clean.split("\n"):
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3:
            continue
        m_pct = re.match(r"^(\d+(?:\.\d+)?)%$", parts[2])
        if not m_pct:
            continue
        rem = round(max(0.0, min(100.0, float(m_pct.group(1)))), 1)
        used = round(max(0.0, min(100.0, 100.0 - rem)), 1)
        g_name = parts[0] or parts[1] or f"Pool {len(windows) + 1}"
        label = g_name[:60]
        w = {
            "id": _slug(label, f"w{len(windows)}"),
            "label": label,
            "usedPct": used,
            "remainingPct": rem,
        }
        if len(parts) >= 4 and parts[3]:
            reset_at = parse_iso_ms(parts[3])
            if reset_at is not None:
                w["resetAt"] = reset_at
            else:
                w["resets"] = parts[3][:60]
        windows.append(w)
    return windows


def _extract_json(stdout):
    raw = str(stdout or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                continue
    return None


def parse_antigravity(stdout):
    data = _extract_json(stdout)
    if isinstance(data, dict):
        cmd = data.get("command") if isinstance(data.get("command"), dict) else {}
        cmd_data = cmd.get("data") if isinstance(cmd.get("data"), dict) else {}
        groups = cmd_data.get("groups")
        if isinstance(groups, list):
            windows = _parse_groups(groups)
            if windows:
                out = {"state": "ok", "windows": windows}
                plan = cmd_data.get("plan") or data.get("plan")
                if isinstance(plan, str) and plan.strip():
                    out["plan"] = plan.strip()[:30]
                account = cmd_data.get("account") or data.get("account")
                if isinstance(account, str) and account.strip():
                    out["account"] = account.strip()[:80]
                return out
        resp = data.get("response")
        if isinstance(resp, str) and resp.strip():
            windows = _parse_tsv_response(resp)
            if windows:
                return {"state": "ok", "windows": windows}
            text = resp
        else:
            text = str(data.get("error") or data.get("message") or "")
    else:
        text = str(stdout or "")
    clean = ANSI_RE.sub("", text)
    if re.search(r"not logged in|unauthenticated|sign in|/login", clean, re.I):
        return {"state": "signed-out"}
    if re.search(r"no plan|api key billing", clean, re.I):
        return {"state": "no-plan"}
    return {"state": "unknown", "why": "Antigravity's answer had no limits in it"}


def _resolve_binary(cfg):
    if cfg.get("bin"):
        return which(cfg["bin"])
    return which("agy") or which("antigravity")


def antigravity():
    cfg = _load_config()
    if not os.path.isdir(cfg["dir"]):
        return None, cfg
    binary = _resolve_binary(cfg)
    if not binary or not _looks_like_antigravity(binary):
        return None, cfg
    command = _quiet([binary, "-p", "/usage", "--output-format", "json"])
    env = dict(os.environ, TZ="UTC")
    try:
        r = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=env,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "why": "Antigravity took too long to answer"}, cfg
    except OSError:
        return {"state": "unknown", "why": "Couldn't run Antigravity"}, cfg
    got = parse_antigravity(r.stdout)
    if got["state"] == "unknown" and r.returncode != 0 and r.stderr:
        err_check = parse_antigravity(r.stderr)
        if err_check["state"] != "unknown":
            return err_check, cfg
    return got, cfg


def _build_match(cfg):
    apps = list(_AGY_MATCH["apps"])
    bins = list(_AGY_MATCH["bins"])
    for a in cfg.get("apps") or []:
        if a not in apps:
            apps.append(a)
    for b in cfg.get("bins") or []:
        if b not in bins:
            bins.append(b)
    if cfg.get("bin"):
        base = os.path.basename(cfg["bin"])
        if base and base not in bins:
            bins.append(base)
        if base and base not in apps:
            apps.append(base)
    return {
        "apps": apps,
        "bins": bins,
        "pkgTokens": list(_AGY_MATCH["pkgTokens"]),
        "models": list(_AGY_MATCH["models"]),
    }


def collect_quota(opts=None):
    at = now_ms()
    try:
        got, cfg = antigravity()
    except Exception as e:
        msg = str(e)[:120] or "Couldn't run it"
        return {
            "provider": "antigravity",
            "id": "antigravity",
            "name": "Antigravity",
            "installed": True,
            "state": "unknown",
            "status": "unknown",
            "windows": [],
            "why": msg,
            "error": msg,
            "match": _AGY_MATCH,
            "at": at,
        }
    name = (cfg or {}).get("name") or "Antigravity"
    if got is None:
        return {
            "provider": "antigravity",
            "id": "antigravity",
            "name": name,
            "installed": False,
            "state": "absent",
            "status": "absent",
            "windows": [],
            "at": at,
        }
    state = got.get("state") or "unknown"
    entry = {
        "provider": "antigravity",
        "id": "antigravity",
        "name": name,
        "installed": True,
        "state": state,
        "status": state,
        "windows": got.get("windows") or [],
        "match": _build_match(cfg),
        "at": now_ms(),
    }
    if got.get("plan"):
        entry["plan"] = got["plan"]
    if got.get("account"):
        entry["account"] = got["account"]
    if got.get("why"):
        entry["why"] = got["why"]
        entry["error"] = got["why"]
    return entry


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    opts = {}
    if args and args[0]:
        try:
            parsed = json.loads(args[0])
            if isinstance(parsed, dict):
                opts = parsed
        except Exception:
            opts = {}
    try:
        out = collect_quota(opts)
    except Exception as e:
        msg = str(e)[:200] or "Couldn't read quota"
        out = {
            "provider": "antigravity",
            "id": "antigravity",
            "name": "Antigravity",
            "installed": True,
            "state": "unknown",
            "status": "unknown",
            "windows": [],
            "why": msg,
            "error": msg,
            "at": now_ms(),
        }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
