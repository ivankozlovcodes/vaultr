"""Every test runs on a throwaway home. Each test file imports this first.

On import: HOME and HERDR_APP_HOME point into one temp folder for the run, so nothing reads or writes the person's
~/.config/herdr-app. A stub `herdr-app` goes first on PATH and only logs its arguments to LOG, so no test reaches a
running Herdr window. An audit hook fails a test at once if it opens a file in the real Herdr app folder.
"""
import atexit
import os
import pwd
import shutil
import stat
import sys
import tempfile

sys.dont_write_bytecode = True  # no __pycache__ folders appear in the repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    _REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
except KeyError:
    _REAL_HOME = os.path.expanduser("~")
REAL_APP = os.path.realpath(os.path.join(_REAL_HOME, ".config", "herdr-app"))

TMP = tempfile.mkdtemp(prefix="vaultr-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
HOME = os.path.join(TMP, "home")
APP = os.path.join(HOME, ".config", "herdr-app")
BIN = os.path.join(TMP, "bin")
LOG = os.path.join(TMP, "herdr-app.log")
for d in (APP, BIN):
    os.makedirs(d)

with open(os.path.join(BIN, "herdr-app"), "w") as f:
    f.write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{LOG}"\nexit 0\n')
os.chmod(os.path.join(BIN, "herdr-app"), stat.S_IRWXU)

os.environ["HOME"] = HOME
os.environ["HERDR_APP_HOME"] = APP
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")
os.environ.pop("VAULTR_FALLBACK_LAYOUT", None)


def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        p = os.path.realpath(os.fsdecode(args[0]))
        if p == REAL_APP or p.startswith(REAL_APP + os.sep):
            raise AssertionError(f"a test opened {p}: use a throwaway folder (test/home_guard.py)")


sys.addaudithook(_audit)
