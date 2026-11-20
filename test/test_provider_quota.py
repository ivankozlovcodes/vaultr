"""Unit tests for mods/ob-feed/providers/claude/quota.py: evidence before execution, parsing, and JSON output."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import calendar
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = home_guard.ROOT
QUOTA_PY = Path(ROOT, "mods", "ob-feed", "providers", "claude", "quota.py")


def load_quota_py():
    spec = importlib.util.spec_from_file_location("claude_quota_py", QUOTA_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QPY = load_quota_py()


def utc_ms(year, month, day, hour, minute=0):
    return calendar.timegm((year, month, day, hour, minute, 0)) * 1000


class ClaudeQuotaParsing(unittest.TestCase):
    def test_claude_reset_parses_date_and_time(self):
        at = utc_ms(2026, 11, 5, 10, 0)
        self.assertEqual(QPY.claude_reset("Nov 6, 11:59am (UTC)", at), utc_ms(2026, 11, 6, 11, 59))
        self.assertEqual(QPY.claude_reset("3pm (UTC)", at), utc_ms(2026, 11, 5, 15, 0))
        self.assertEqual(QPY.claude_reset("9am (UTC)", at), utc_ms(2026, 11, 6, 9, 0))
        self.assertEqual(QPY.claude_reset("12pm (UTC)", at), utc_ms(2026, 11, 5, 12, 0))
        self.assertEqual(QPY.claude_reset("12am (UTC)", at), utc_ms(2026, 11, 6, 0, 0))
        self.assertIsNone(QPY.claude_reset("sometime soon", at))

    def test_parse_claude_ok_states_and_fallback_reset(self):
        at = utc_ms(2026, 11, 5, 10, 0)
        text = (
            "\x1b[1mCurrent session: 23.4% used · resets 3pm (UTC)\x1b[0m\n"
            "Current week (all models): 10% used · resets Nov 6, 11:59am (UTC)\n"
            "Current week (Sonnet): 42% used · resets Nov 6, 11:59am (UTC)\n"
            "Current week (Opus only): 5% used\n"
        )
        got = QPY.parse_claude(text, at)
        self.assertEqual(got["state"], "ok")
        wins = got["windows"]
        self.assertEqual([w["id"] for w in wins], ["5-hour", "weekly-all-models", "weekly-sonnet", "weekly-opus-only"])
        self.assertEqual([w["label"] for w in wins], ["5-hour", "Weekly (all models)", "Weekly (Sonnet)", "Weekly (Opus only)"])
        self.assertEqual(wins[0]["usedPct"], 23.4)
        self.assertEqual(wins[0]["remainingPct"], 76.6)
        self.assertEqual(wins[0]["resetAt"], utc_ms(2026, 11, 5, 15, 0))
        self.assertNotIn("models", wins[0])
        self.assertNotIn("models", wins[1])
        self.assertEqual(wins[2]["models"], ["sonnet"])
        self.assertEqual(wins[3]["models"], ["opus"])

        self.assertEqual(QPY.parse_claude("Not logged in. Run /login", at), {"state": "signed-out"})
        self.assertEqual(QPY.parse_claude("Total cost: $1.23", at), {"state": "no-plan"})
        self.assertEqual(QPY.parse_claude("Nothing here", at)["state"], "unknown")

        unparsed = QPY.parse_claude("Current session: 12% used · resets tomorrow morning", at)
        self.assertEqual(unparsed["windows"][0]["resets"], "tomorrow morning")
        self.assertNotIn("resetAt", unparsed["windows"][0])


class ClaudeEvidenceAndExecution(unittest.TestCase):
    def _make_exec(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def _quota_env(self, tmp, bin_dir):
        env = dict(os.environ, PATH=str(bin_dir), HOME=str(tmp))
        env.pop("CLAUDE_CONFIG_DIR", None)
        return env

    def test_missing_state_dir_never_opens_or_runs_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            claude_bin = self._make_exec(bin_dir / "claude", "#!/bin/sh\necho ran\n")
            bin_real = os.path.realpath(str(bin_dir))
            opened = []
            real_open = open

            def spy_open(file, *args, **kwargs):
                try:
                    p = os.path.realpath(os.fspath(file))
                except (TypeError, ValueError, OSError):
                    p = ""
                if p == bin_real or p.startswith(bin_real + os.sep):
                    opened.append(p)
                return real_open(file, *args, **kwargs)

            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []), \
                 mock.patch("builtins.open", side_effect=spy_open):
                self.assertIsNone(QPY.claude())
                out = QPY.collect_quota({})
                self.assertEqual(out["provider"], "claude")
                self.assertFalse(out["installed"])
                self.assertEqual(out["state"], "absent")
            self.assertEqual(opened, [])
            self.assertTrue(os.path.exists(claude_bin))

    def test_fake_claude_binaries_without_evidence_are_never_executed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            sentinel = tmp / "claude_ran"
            self._make_exec(bin_dir / "claude", f"#!/bin/sh\ntouch {sentinel}\nexit 0\n")

            # Case A: config dir absent
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []):
                self.assertIsNone(QPY.claude())
            self.assertFalse(sentinel.exists(), "fake claude script must never run when config dir is missing")

            # Case B: config dir and credentials exist, script lacks Claude markers
            (tmp / ".claude").mkdir()
            with open(tmp / ".claude" / ".credentials.json", "w", encoding="utf-8") as f:
                json.dump({"claudeAiOauth": {"subscriptionType": "max", "expiresAt": QPY.now_ms() + 86400_000}}, f)
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []):
                self.assertIsNone(QPY.claude())
            self.assertFalse(sentinel.exists(), "fake claude script without evidence must never run even when .claude exists")

            # Case C: unrelated non-text ELF binary with .claude dir existing
            elf_bin = bin_dir / "claude"
            elf_bin.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 4096)
            elf_bin.chmod(0o755)
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []), \
                 mock.patch.object(QPY.subprocess, "run") as mock_run:
                self.assertIsNone(QPY.claude())
                mock_run.assert_not_called()

    def test_genuine_binary_never_runs_when_config_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            sentinel = tmp / "claude_ran"
            self._make_exec(
                bin_dir / "claude",
                f"#!/bin/sh\n# @anthropic-ai/claude-code\ntouch {sentinel}\nexit 0\n",
            )
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []):
                self.assertIsNone(QPY.claude())
                self.assertFalse(QPY.collect_quota({})["installed"])
            self.assertFalse(sentinel.exists())

    def test_genuine_evidence_parses_oauth_and_usage_response_into_generic_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Chunk boundary marker check (> 64 KiB binary with marker split across 65536 boundary)
            boundary_claude = tmp / "boundary_claude"
            boundary_claude.write_bytes(b"\x00" * (65536 - 6) + b"CLAUDE_CONFIG_DIR" + b"\x00" * 1024)
            self.assertTrue(QPY._looks_like_claude(str(boundary_claude)))

            # Path token check via symlink realpath
            pkg_claude = tmp / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
            self._make_exec(pkg_claude, "#!/bin/sh\nexit 0\n")
            sym_claude = tmp / "sym_claude"
            sym_claude.symlink_to(pkg_claude)
            self.assertTrue(QPY._looks_like_claude(str(sym_claude)))

            # Verified stub with OAuth credentials and account email
            bin_dir = tmp / "bin"
            (tmp / ".claude").mkdir()
            with open(tmp / ".claude" / ".credentials.json", "w", encoding="utf-8") as f:
                json.dump({"claudeAiOauth": {"subscriptionType": "max", "expiresAt": QPY.now_ms() + 86400_000}}, f)
            with open(tmp / ".claude.json", "w", encoding="utf-8") as f:
                json.dump({"oauthAccount": {"emailAddress": "dev@example.com"}}, f)
            self._make_exec(
                bin_dir / "claude",
                "#!/bin/sh\n# @anthropic-ai/claude-code\n"
                "printf '%s\\n' '{\"result\":\"Current session: 20% used · resets 3pm (UTC)\\n"
                "Current week (Sonnet): 45% used · resets Nov 6, 11:59am (UTC)\"}'\n",
            )
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []), \
                 mock.patch.object(QPY, "MAC", False), \
                 mock.patch.object(QPY, "_can_bwrap", return_value=False):
                out = QPY.collect_quota({})
            self.assertTrue(out["installed"])
            self.assertEqual(out["provider"], "claude")
            self.assertEqual(out["id"], "claude")
            self.assertEqual(out["name"], "Claude Code")
            self.assertEqual(out["plan"], "max")
            self.assertEqual(out["account"], "dev@example.com")
            self.assertEqual(out["state"], "ok")
            self.assertEqual(out["status"], "ok")
            self.assertEqual(len(out["windows"]), 2)
            self.assertEqual(out["windows"][0]["id"], "5-hour")
            self.assertEqual(out["windows"][0]["usedPct"], 20.0)
            self.assertEqual(out["windows"][0]["remainingPct"], 80.0)
            self.assertIn("resetAt", out["windows"][0])
            self.assertEqual(out["windows"][1]["models"], ["sonnet"])
            self.assertIn("apps", out["match"])

    def test_due_oauth_token_skips_running_claude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            sentinel = tmp / "claude_ran"
            (tmp / ".claude").mkdir()
            with open(tmp / ".claude" / ".credentials.json", "w", encoding="utf-8") as f:
                json.dump({"claudeAiOauth": {"subscriptionType": "pro", "expiresAt": QPY.now_ms() - 1000}}, f)
            self._make_exec(
                bin_dir / "claude",
                f"#!/bin/sh\n# @anthropic-ai/claude-code\ntouch {sentinel}\nexit 0\n",
            )
            with mock.patch.dict(os.environ, self._quota_env(tmp, bin_dir), clear=True), \
                 mock.patch.object(QPY, "HOME", str(tmp)), \
                 mock.patch.object(QPY, "PATHS", []), \
                 mock.patch.object(QPY, "MAC", False):
                out = QPY.collect_quota({})
            self.assertEqual(out["state"], "unknown")
            self.assertIn("renewal", out["error"])
            self.assertFalse(sentinel.exists())

    def test_cli_script_prints_one_json_line_when_uninstalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PATH=tmp, HOME=tmp, CLAUDE_CONFIG_DIR=os.path.join(tmp, ".claude"))
            with open(QUOTA_PY, encoding="utf-8") as f:
                script = f.read()
            p = subprocess.run([sys.executable, "-I", "-c", script, "{}"], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1)
            out = json.loads(lines[0])
            self.assertEqual(out["provider"], "claude")
            self.assertFalse(out["installed"])
            self.assertEqual(out["state"], "absent")


if __name__ == "__main__":
    unittest.main()
