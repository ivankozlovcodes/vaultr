"""mods/ob-quotas: pure quota formatting/pool-matching (quotas.js under node) and generic panel wiring (main.js)."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import calendar
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MOD = Path(ROOT, "mods", "ob-quotas")
QUOTAS_JS = MOD / "quotas.js"
MAIN_JS = MOD / "main.js"
MOD_JSON = MOD / "mod.json"
NODE = shutil.which("node")


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_node(body, tz="UTC"):
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    src = (
        f'import * as Q from "{QUOTAS_JS.as_uri()}";\n'
        f'const r = (() => {{ {body} }})();\n'
        'console.log(JSON.stringify(r === undefined ? null : r));\n'
    )
    res = subprocess.run(
        [NODE, "--input-type=module", "-e", src],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TZ": tz},
        timeout=60,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def utc_ms(year, month, day, hour, minute=0):
    return calendar.timegm((year, month, day, hour, minute, 0)) * 1000


@unittest.skipUnless(NODE, "node is not installed: skipping quotas.js tests")
class QuotasJs(unittest.TestCase):
    def test_quota_level_thresholds(self):
        got = run_node("return [0, 10, 10.1, 25, 25.1, 100, null].map((x) => Q.quotaLevel(x));")
        self.assertEqual(got, ["over", "over", "busy", "busy", "ok", "ok", "ok"])

    def test_next_provider_read_preserves_last_ok_on_unknown(self):
        prev = {
            "id": "alpha",
            "state": "ok",
            "windows": [{"id": "5-hour", "label": "5-hour", "usedPct": 20, "remainingPct": 80}],
        }
        got = run_node(f"return Q.nextProviderRead({json.dumps(prev)}, {{state: 'unknown', error: 'timed out'}});")
        self.assertEqual(got["state"], "ok")
        self.assertEqual(got["windows"], prev["windows"])
        self.assertEqual(got["failed"], "timed out")

        recovered = run_node(f"return Q.nextProviderRead({json.dumps(got)}, {{id: 'alpha', state: 'ok', windows: []}});")
        self.assertNotIn("failed", recovered)

        signed_out = run_node(f"return Q.nextProviderRead({json.dumps(prev)}, {{state: 'signed-out'}});")
        self.assertEqual(signed_out, {"state": "signed-out"})

    def test_merge_machine_quotas_merges_by_id_and_handles_top_level_error(self):
        prev = {
            "at": 1000,
            "items": [
                {"id": "alpha", "name": "Alpha", "state": "ok", "windows": [{"id": "5-hour", "remainingPct": 70}]},
                {"id": "beta", "name": "Beta", "state": "ok", "windows": [{"id": "5-hour", "remainingPct": 90}]},
            ],
            "error": None,
        }
        fresh = {
            "at": 2000,
            "items": [
                {"id": "alpha", "name": "Alpha", "state": "unknown", "why": "bwrap error"},
                {"id": "beta", "name": "Beta", "state": "ok", "windows": [{"id": "5-hour", "remainingPct": 85}]},
            ],
        }
        merged = run_node(f"return Q.mergeMachineQuotas({json.dumps(prev)}, {json.dumps(fresh)});")
        self.assertEqual(merged["at"], 2000)
        self.assertEqual(merged["items"][0]["state"], "ok")
        self.assertEqual(merged["items"][0]["failed"], "bwrap error")
        self.assertEqual(merged["items"][1]["windows"][0]["remainingPct"], 85)

        errored = run_node(f"return Q.mergeMachineQuotas({json.dumps(prev)}, {{error: 'ssh down'}});")
        self.assertEqual(errored["at"], 1000)
        self.assertEqual(len(errored["items"]), 2)
        self.assertEqual(errored["error"], "ssh down")

    def test_format_span_and_when(self):
        spans = run_node(
            "return [18*3600000 + 2*60000, 5*3600000, 42*60000, (3*24+4)*3600000, 0].map((x) => Q.formatSpan(x));"
        )
        self.assertEqual(spans, ["18h 2m", "5h", "42m", "3d 4h", "0m"])

        wed = utc_ms(2026, 11, 18, 6, 39)
        thu = utc_ms(2026, 11, 19, 12, 0)
        whens = run_node(f"return [Q.formatWhen({wed}), Q.formatWhen({thu})];", tz="UTC")
        self.assertEqual(whens, ["Wed 6:39am", "Thu 12pm"])

    def test_format_window_live_expired_and_text(self):
        now = utc_ms(2026, 11, 18, 5, 0)
        live_at = utc_ms(2026, 11, 18, 6, 39)
        live = run_node(
            f"return Q.formatWindow({{label: '5-hour', usedPct: 22.6, remainingPct: 77.4, resetAt: {live_at}}}, {now});",
            tz="UTC",
        )
        self.assertEqual(live["pctLeft"], 77)
        self.assertEqual(live["pctUsed"], 23)
        self.assertEqual(live["level"], "ok")
        self.assertFalse(live["expired"])
        self.assertEqual(live["subLabel"], "Refills in 1h 39m · Wed 6:39am · 23% used")

        expired = run_node(
            f"return Q.formatWindow({{label: '5-hour', usedPct: 95, remainingPct: 5, resetAt: {now - 1000}}}, {now});",
            tz="UTC",
        )
        self.assertEqual(expired["pctLeft"], 5)
        self.assertEqual(expired["level"], "over")
        self.assertTrue(expired["expired"])
        self.assertEqual(expired["subLabel"], "Refilled · refresh to update")

        text_reset = run_node(
            f"return Q.formatWindow({{label: 'Weekly', usedPct: 80, remainingPct: 20, resets: 'soon'}}, {now});"
        )
        self.assertEqual(text_reset["level"], "busy")
        self.assertEqual(text_reset["subLabel"], "Resets soon · 80% used")

    def test_match_session_pool_uses_provider_and_generic_metadata(self):
        now = 1_700_000_000_000
        providers = [
            {
                "id": "other",
                "provider": "other",
                "name": "Other CLI",
                "state": "ok",
                "match": {"apps": ["other"], "bins": ["other"], "models": ["other-"]},
                "windows": [{"id": "5-hour", "label": "5-hour", "usedPct": 10, "remainingPct": 90, "resetAt": now + 3600_000}],
            },
            {
                "id": "alpha",
                "provider": "alpha",
                "name": "Alpha Runner",
                "state": "ok",
                "match": {"apps": ["alpha", "alpha-cli"], "bins": ["alpha"], "pkgTokens": ["@org/alpha"], "models": ["alpha-", "fast"]},
                "windows": [
                    {"id": "5-hour", "label": "5-hour", "usedPct": 20, "remainingPct": 80, "resetAt": now + 3600_000},
                    {"id": "weekly-all-models", "label": "Weekly (all models)", "usedPct": 45, "remainingPct": 55, "resetAt": now + 86400_000},
                    {"id": "weekly-fast", "label": "Weekly (Fast)", "usedPct": 15, "remainingPct": 85, "models": ["fast"], "resetAt": now + 86400_000},
                ],
            },
        ]
        # Match via provider.session().provider and model pool tag
        by_provider = run_node(
            f"const r = Q.matchSessionPool({json.dumps(providers)}, {{provider: 'alpha', model: 'alpha-fast-2'}}, {now});"
            "return { activeProviderId: r.activeProviderId, keys: [...r.activeWindowKeys], "
            "highlightWin: r.highlight?.window?.id, modelLabel: r.highlight?.modelLabel, "
            "providerOrder: r.orderedProviders.map(p => p.id), "
            "winOrder: r.orderedProviders[0].windows.map(w => w.id) };"
        )
        self.assertEqual(by_provider["activeProviderId"], "alpha")
        self.assertEqual(by_provider["keys"], ["alpha:weekly-fast"])
        self.assertEqual(by_provider["highlightWin"], "weekly-fast")
        self.assertEqual(by_provider["providerOrder"], ["alpha", "other"])
        self.assertEqual(by_provider["winOrder"], ["weekly-fast", "5-hour", "weekly-all-models"])

        # Match via match.models when session.provider is null, falling back to tightest live general window
        by_model = run_node(
            f"const r = Q.matchSessionPool({json.dumps(providers)}, {{model: 'alpha-pro-4'}}, {now});"
            "return { keys: [...r.activeWindowKeys], highlightWin: r.highlight?.window?.id };"
        )
        self.assertEqual(by_model["keys"], ["alpha:weekly-all-models"])
        self.assertEqual(by_model["highlightWin"], "weekly-all-models")

        # Match via argv wrapper unwrapping + pkgTokens
        by_argv = run_node(
            f"const r = Q.matchSessionPool({json.dumps(providers)}, {{argv: ['nice', '-n', '19', 'node', '/x/@org/alpha/cli.js']}}, {now});"
            "return { activeProviderId: r.activeProviderId, highlightWin: r.highlight?.window?.id };"
        )
        self.assertEqual(by_argv["activeProviderId"], "alpha")
        self.assertEqual(by_argv["highlightWin"], "weekly-all-models")

        # Non-agent shell session highlights nothing
        shell_res = run_node(
            f"const r = Q.matchSessionPool({json.dumps(providers)}, {{app: null, argv: ['zsh'], model: null}}, {now});"
            "return { activeProviderId: r.activeProviderId, highlight: r.highlight, providerOrder: r.orderedProviders.map(p => p.id) };"
        )
        self.assertIsNone(shell_res["activeProviderId"])
        self.assertIsNone(shell_res["highlight"])
        self.assertEqual(shell_res["providerOrder"], ["other", "alpha"])


class MainJsWiring(unittest.TestCase):
    def test_mod_manifest_and_gpui_safety(self):
        manifest = json.loads(_read_text(MOD_JSON))
        self.assertEqual(manifest, {"place": "none", "title": "Quotas", "focusable": True})

        src = _read_text(MAIN_JS)
        self.assertRegex(src, r'import\s*\{[^}]*\bScrollHandle\b[^}]*\}\s*from\s*"gpui-base"')
        self.assertIn("ScrollHandle.new()", src)
        self.assertIn(".track_scroll(this.scroll)", src)
        self.assertIn("lsGet", src)
        self.assertIn("lsSet", src)
        self.assertIn("provider.quota(", src)
        self.assertIn("provider.session(", src)
        self.assertNotIn('shared("ob.inspect")', src)
        self.assertNotIn('"ob.inspect"', src)
        self.assertNotIn("overflow_x_scrollbar", src)
        self.assertIn('from "./quotas.js"', src)
        self.assertIn("matchSessionPool(", src)
        self.assertIn("formatWindow(", src)
        self.assertIn("mergeMachineQuotas(", src)

        render_src = src[src.index("  render(cx) {"):]
        non_resize = "\n".join(line for line in render_src.splitlines() if "on_size_change(" not in line)
        self.assertNotIn("cx.notify()", non_resize)

    def test_resolve_target_follows_active_tab_without_sticky_inspect(self):
        src = _read_text(MAIN_JS)
        self.assertNotIn('shared("ob.inspect")', src)
        self.assertIn("pinned: null", src)
        body = src[src.index("  resolveTarget() {"):src.index("  shouldFetch(machine, now) {")]
        self.assertIn("tabAgent", body)
        self.assertIn("isAgentAddr", body)
        self.assertIn("provider.session(addr)", body)

    def test_ob_quotas_has_no_provider_names_or_python_runner(self):
        with open(Path(ROOT, "mods", "ob-feed", "providers", "index.json"), encoding="utf-8") as f:
            pids = json.load(f)
        tokens = set()
        for pid in pids:
            with open(Path(ROOT, "mods", "ob-feed", "providers", pid, "manifest.json"), encoding="utf-8") as f:
                m = json.load(f)
            for t in (m.get("id"), str(m.get("id", "")).capitalize(), m.get("name")):
                if t:
                    tokens.add(t)
        tok_re = re.compile("(?:" + "|".join(rf"(?<![A-Za-z]){re.escape(t)}(?![a-z])" for t in tokens) + ")")
        for p in (MAIN_JS, QUOTAS_JS):
            src = _read_text(p)
            self.assertIsNone(tok_re.search(src))
            self.assertNotRegex(src, r"\bpython3\b")
            self.assertNotIn("feed(", src)
            self.assertNotIn("ob.subagents", src)


if __name__ == "__main__":
    unittest.main()
