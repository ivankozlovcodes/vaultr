# Standalone read-only Claude Code plan-quota collector.
# Portions adapted from Shepherdr (mods/tasks/bin/herdr_task/machine.py),
# Copyright (c) 2026 Elias Stravik, MIT License (see LICENSE-shepherdr).
# Checks Claude Code state directory and binary/package evidence BEFORE invoking any CLI.

import calendar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

MAC = sys.platform == "darwin"
HOME = os.path.expanduser("~")

SOON = 3600 * 1000
DUE = {"state": "unknown", "why": "Its sign-in is due for renewal: the next agent here will do it"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PATHS = [
    os.path.join(HOME, ".local", "bin"),
    "/usr/local/bin",
    "/opt/homebrew/bin",
    os.path.join(HOME, ".npm-global", "bin"),
    os.path.join(HOME, ".bun", "bin"),
    os.path.join(HOME, ".claude", "local"),
]
ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")

MAC_PROFILE = "\n".join([
    "(version 1)",
    "(allow default)",
    "(deny file-write*)",
    "(deny user-preference-write)",
    '(deny process-exec (literal "/usr/bin/security"))',
    '(deny mach-lookup (global-name "com.apple.SecurityServer") (global-name "com.apple.securityd.xpc"))',
    '(allow file-write* (subpath (param "OPEN")))',
    '(allow file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty"))',
])
SANDBOX = "/usr/bin/sandbox-exec"

_CLAUDE_PATH_TOKENS = ("@anthropic-ai/claude-code", ".claude/local", ".local/share/claude")
_CLAUDE_BYTE_MARKERS = (
    b"CLAUDE_CONFIG_DIR",
    b"claudeAiOauth",
    b"@anthropic-ai/claude-code",
    b".claude/local",
    b".local/share/claude",
)
_CLAUDE_MATCH = {
    "apps": ["claude", "claude-code"],
    "bins": ["claude", "claude-code"],
    "pkgTokens": ["claude-code", "@anthropic-ai/claude-code"],
    "models": ["claude-", "sonnet", "opus", "haiku"],
}

_BWRAP_OK = None


def now_ms():
    return int(time.time() * 1000)


def _run(argv, timeout=10):
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=timeout,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def which(name):
    path = os.pathsep.join([os.environ.get("PATH", "")] + PATHS)
    found = shutil.which(name, path=path)
    if found and "/mise/" in found and ("/shims/" in found or "/command-wrappers/" in found):
        mise = shutil.which("mise", path=path)
        real = _run([mise, "which", name]).strip() if mise else ""
        found = real if real and os.path.exists(real) else found
    return found


def _quiet(argv):
    return (["nice", "-n", "19"] if shutil.which("nice") else []) + argv


def _bwrap_bin():
    return shutil.which("bwrap") or ("/usr/bin/bwrap" if os.path.exists("/usr/bin/bwrap") else None)


def _can_bwrap():
    global _BWRAP_OK
    if MAC:
        return False
    if _BWRAP_OK is not None:
        return _BWRAP_OK
    bwrap = _bwrap_bin()
    if not bwrap:
        _BWRAP_OK = False
        return False
    true_bin = (
        "/bin/true"
        if os.path.exists("/bin/true")
        else ("/usr/bin/true" if os.path.exists("/usr/bin/true") else shutil.which("true"))
    )
    if not true_bin:
        _BWRAP_OK = False
        return False
    try:
        r = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--", true_bin],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        _BWRAP_OK = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _BWRAP_OK = False
    return _BWRAP_OK


def _seal(argv):
    return [
        _bwrap_bin() or "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--share-net",
        "--die-with-parent",
        "--chdir", "/tmp",
        "--",
    ] + argv


def _mac_seal():
    if not os.path.exists(SANDBOX):
        return None
    folder = os.path.realpath(tempfile.mkdtemp(prefix="herdr-limits-"))
    opened, shut = os.path.join(folder, "open"), os.path.join(folder, "shut")
    os.mkdir(opened)
    os.mkdir(shut)

    def wrap(argv):
        return [SANDBOX, "-p", MAC_PROFILE, "-DOPEN=" + opened, "--"] + argv

    def close():
        shutil.rmtree(folder, ignore_errors=True)

    proof = '/usr/bin/touch "$1/proof" && ! /usr/bin/touch "$2/proof" 2>/dev/null && ! /usr/bin/security list-keychains >/dev/null 2>&1'
    try:
        code = subprocess.run(
            wrap(["/bin/sh", "-c", proof, "proof", opened, shut]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        code = 1
    if code == 0 and os.path.exists(os.path.join(opened, "proof")) and not os.path.exists(os.path.join(shut, "proof")):
        return opened, wrap, close
    close()
    return None


def _json_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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


def _looks_like_claude(binary, depth=0):
    if not binary:
        return False
    try:
        real = os.path.realpath(binary)
    except OSError:
        real = binary
    if any(tok in real for tok in _CLAUDE_PATH_TOKENS):
        return True
    if _file_has_marker(real, _CLAUDE_BYTE_MARKERS):
        return True
    if depth == 0:
        text = _read_small_shebang_text(real)
        if text:
            for raw_tok in re.findall(r'["\']?(/[^"\'\s]+)["\']?', text):
                if raw_tok.startswith(("/bin/", "/usr/bin/")) and os.path.basename(raw_tok) in ("sh", "bash", "zsh", "env"):
                    continue
                if os.path.isfile(raw_tok) and _looks_like_claude(raw_tok, depth=1):
                    return True
    return False


def claude_reset(words, at):
    s = str(words or "").strip()
    m = re.match(
        r"^(?:([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?(?:,| at)? )?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?: \(UTC\))?$",
        s,
        re.I,
    )
    if not m:
        return None
    if m.group(1) and m.group(1) not in MONTHS:
        return None
    ampm = (m.group(6) or "").lower()
    hour = int(m.group(4)) % (12 if ampm else 24) + (12 if ampm == "pm" else 0)
    minute = int(m.group(5) or 0)
    today = time.gmtime(at / 1000)
    if not m.group(1):
        t = calendar.timegm((today.tm_year, today.tm_mon, today.tm_mday, hour, minute, 0)) * 1000
        return t + 86400000 if t + 60000 <= at else t

    def on(year):
        return calendar.timegm((year, MONTHS.index(m.group(1)) + 1, int(m.group(2)), hour, minute, 0)) * 1000

    if m.group(3):
        return on(int(m.group(3)))
    return on(today.tm_year + 1) if on(today.tm_year) < at - 86400000 else on(today.tm_year)


def parse_claude(text, at):
    clean = ANSI_RE.sub("", str(text or "")).replace("\r", "")
    windows = []
    for line in clean.split("\n"):
        m = re.match(r"^(.+?): (\d+(?:\.\d+)?)% used(?: · resets (.+))?$", line.strip())
        if not m:
            continue
        label = re.sub(r"^Current week\b", "Weekly", re.sub(r"^Current session\b", "5-hour", m.group(1)))[:60]
        wid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"w{len(windows)}"
        used = round(max(0.0, min(100.0, float(m.group(2)))), 1)
        remaining = round(max(0.0, min(100.0, 100.0 - used)), 1)
        w = {"id": wid, "label": label, "usedPct": used, "remainingPct": remaining}
        if m.group(3):
            resets_raw = m.group(3).strip()
            r = claude_reset(resets_raw, at)
            if r is not None:
                w["resetAt"] = r
            else:
                w["resets"] = resets_raw[:60]
        paren = re.search(r"\(([^)]+)\)", label)
        if paren:
            inner = paren.group(1).strip().lower()
            if "all models" not in inner:
                models = [
                    tok
                    for tok in re.findall(r"[a-z0-9][a-z0-9._-]*", inner)
                    if tok not in ("only", "model", "models", "and")
                ]
                if models:
                    w["models"] = models
        windows.append(w)
    if windows:
        return {"state": "ok", "windows": windows}
    if re.search(r"not logged in|/login", clean, re.I):
        return {"state": "signed-out"}
    if re.search(r"^Total cost:", clean, re.M):
        return {"state": "no-plan"}
    return {"state": "unknown", "why": "Claude Code's answer had no limits in it"}


def _claude_due(login, at):
    end = ((login or {}).get("claudeAiOauth") or {}).get("expiresAt")
    return end is not None and not (end - SOON > at)


def _ask_claude_raw(argv, env, cwd=None):
    try:
        r = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            env=env,
            cwd=cwd,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"state": "unknown", "why": "Claude Code took too long to answer"}, 1, False
    except OSError:
        return {"state": "unknown", "why": "Couldn't run Claude Code"}, 1, False
    try:
        data = json.loads(r.stdout)
        is_json = isinstance(data, dict)
        result = data.get("result") if is_json else None
    except (ValueError, AttributeError):
        is_json = False
        result = None
    if not isinstance(result, str):
        return {"state": "unknown", "why": "Couldn't read Claude Code's answer"}, r.returncode, is_json
    return parse_claude(result, now_ms()), r.returncode, is_json


def _ask_claude(argv, env, cwd=None):
    return _ask_claude_raw(argv, env, cwd=cwd)[0]


def claude():
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
    if not os.path.isdir(config):
        return None
    binary = which("claude")
    if not binary or not _looks_like_claude(binary):
        return None
    login = _json_file(os.path.join(config, ".credentials.json"))
    oauth = (login or {}).get("claudeAiOauth") or {}
    extra = {}
    if oauth.get("subscriptionType"):
        extra["plan"] = str(oauth["subscriptionType"])[:30]
    claude_json = _json_file(os.path.join(HOME, ".claude.json")) or _json_file(os.path.join(config, ".claude.json")) or {}
    account = (claude_json.get("oauthAccount") or {}).get("emailAddress")
    if account:
        extra["account"] = str(account)[:80]
    command = _quiet([
        binary,
        "-p", "/usage",
        "--output-format", "json",
        "--no-session-persistence",
        "--setting-sources", "",
        "--strict-mcp-config",
    ])
    if not MAC:
        if login is not None and _claude_due(login, now_ms()):
            return DUE
        if _can_bwrap():
            got, rc, is_json = _ask_claude_raw(_seal(command), dict(os.environ, TZ="UTC", TMPDIR="/tmp"))
            if rc == 0 or is_json:
                return dict(got, **extra) if got["state"] == "ok" else got
        tmpdir = tempfile.mkdtemp(prefix="herdr-limits-")
        try:
            got = _ask_claude(command, dict(os.environ, TZ="UTC", TMPDIR=tmpdir))
            return dict(got, **extra) if got["state"] == "ok" else got
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if not os.path.exists(SANDBOX):
        return {"state": "unknown", "why": "Can't read it safely here: sandbox-exec is missing"}
    keychain = None
    user = os.environ.get("USER") or "claude-code-user"
    try:
        r = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", user, "-w", "-s", "Claude Code-credentials"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=5,
        )
        if r.returncode == 0:
            keychain = json.loads(r.stdout.strip())
        elif r.returncode != 44:
            return {"state": "unknown", "why": "Couldn't check its sign-in in the Keychain, so it wasn't run"}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"state": "unknown", "why": "Couldn't check its sign-in in the Keychain, so it wasn't run"}
    held = keychain if keychain and keychain.get("claudeAiOauth") else login
    if held is not None and _claude_due(held, now_ms()):
        return DUE
    seal = _mac_seal()
    if not seal:
        return {"state": "unknown", "why": "Can't read it safely here: the Mac seal wouldn't hold"}
    opened, wrap, close = seal
    try:
        state, bin_dir = os.path.join(opened, "claude"), os.path.join(opened, "bin")
        os.mkdir(state, 0o700)
        os.mkdir(bin_dir, 0o700)
        sec_stub = os.path.join(bin_dir, "security")
        with open(sec_stub, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 44\n")
        os.chmod(sec_stub, 0o700)
        if held and held.get("claudeAiOauth"):
            sealed = {k: v for k, v in held["claudeAiOauth"].items() if k != "refreshToken"}
            fd = os.open(os.path.join(state, ".credentials.json"), os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"claudeAiOauth": sealed}, f)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=state, PATH=bin_dir + ":" + os.environ.get("PATH", ""), TZ="UTC", TMPDIR=opened)
        env.pop("CLAUDE_SECURESTORAGE_CONFIG_DIR", None)
        got = _ask_claude(wrap(command), env, cwd=opened)
        return dict(got, **extra) if got["state"] == "ok" else got
    finally:
        close()


def collect_quota(opts=None):
    at = now_ms()
    try:
        got = claude()
    except Exception as e:
        msg = str(e)[:120] or "Couldn't run it"
        return {
            "provider": "claude",
            "id": "claude",
            "name": "Claude Code",
            "installed": True,
            "state": "unknown",
            "status": "unknown",
            "windows": [],
            "why": msg,
            "error": msg,
            "match": _CLAUDE_MATCH,
            "at": at,
        }
    if got is None:
        return {
            "provider": "claude",
            "id": "claude",
            "name": "Claude Code",
            "installed": False,
            "state": "absent",
            "status": "absent",
            "windows": [],
            "at": at,
        }
    state = got.get("state") or "unknown"
    entry = {
        "provider": "claude",
        "id": "claude",
        "name": "Claude Code",
        "installed": True,
        "state": state,
        "status": state,
        "windows": got.get("windows") or [],
        "match": _CLAUDE_MATCH,
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
            "provider": "claude",
            "id": "claude",
            "name": "Claude Code",
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
