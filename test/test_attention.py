"""kit/attention.js: who needs you, and dismissing a "Needs you" entry (pure, run under node).

An agent that ended with an error, or is blocked, is flagged "Needs you" until its status moves on. The person can
dismiss it: for attention (the Agents sections and counts, the Agents tab badge, the status bar counts, the Sessions
marks and pill) it then counts as idle. A dismissal holds for one status report only: it is keyed on a stamp of the
status word, the time of the terminal's last status change (status_ms) and its turn counter, so a new report flags the
agent again. The stored map keeps only entries whose stamp still matches a live terminal.

The mods draw from this one rule; the wiring checks below read their sources."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
KIT_DIR = Path(ROOT, "kit")
ATTENTION = KIT_DIR / "attention.js"
NODE = shutil.which("node")

# A terminal as terminals() gives it, trimmed to the fields the stamp uses.
FAILED = {"address": "t1", "status_ms": 1000, "turn": 4}
BLOCKED = {"address": "t2", "status_ms": 2000, "turn": 7}


def att(expr, payload=None):
    src = (f'import * as A from "{ATTENTION.as_uri()}";\n'
           f'const d = {json.dumps(payload)};\n'
           f'console.log(JSON.stringify({expr}));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class Dismiss(unittest.TestCase):
    def dismissed(self, status, term):
        return att("A.patchDismissed({}, d.t.address, A.dismissStamp(d.s, d.t))", {"s": status, "t": term})

    def test_dismissing_a_failed_agent_makes_its_attention_status_idle(self):
        dis = self.dismissed("failed", FAILED)
        got = att("A.attentionStatus(d.dis, 't1', 'failed', d.t)", {"dis": dis, "t": FAILED})
        self.assertEqual(got, "idle")

    def test_dismissing_a_blocked_agent_makes_its_attention_status_idle(self):
        dis = self.dismissed("blocked", BLOCKED)
        got = att("A.attentionStatus(d.dis, 't2', 'blocked', d.t)", {"dis": dis, "t": BLOCKED})
        self.assertEqual(got, "idle")

    def test_an_error_word_counts_as_needs_you_and_can_be_dismissed(self):
        dis = self.dismissed("error", FAILED)
        got = att("[A.isNeedsYou('error'), A.attentionStatus(d.dis, 't1', 'error', d.t)]", {"dis": dis, "t": FAILED})
        self.assertEqual(got, [True, "idle"])

    def test_is_dismissed_says_whether_the_current_report_is_dismissed(self):
        dis = self.dismissed("failed", FAILED)
        got = att("[A.isDismissed(d.dis, 't1', 'failed', d.t), A.isDismissed(d.dis, 't2', 'blocked', d.b)]",
                  {"dis": dis, "t": FAILED, "b": BLOCKED})
        self.assertEqual(got, [True, False])

    def test_a_later_status_change_ends_the_dismissal(self):
        dis = self.dismissed("failed", FAILED)
        later = {**FAILED, "status_ms": 5000}
        got = att("""[
            A.attentionStatus(d.dis, 't1', 'working', d.later),
            A.attentionStatus(d.dis, 't1', 'failed', d.later),
            A.attentionStatus(d.dis, 't1', 'blocked', d.t),
            A.attentionStatus(d.dis, 't1', 'failed', d.nextTurn),
        ]""", {"dis": dis, "t": FAILED, "later": later, "nextTurn": {**FAILED, "turn": 5}})
        # working again; failed again at a later time; blocked at the same time; failed again on the next turn
        self.assertEqual(got, ["working", "failed", "blocked", "failed"])

    def test_restore_ends_the_dismissal(self):
        dis = self.dismissed("failed", FAILED)
        got = att("""(() => {
            const back = A.patchDismissed(d.dis, 't1', null);
            return [back, A.attentionStatus(back, 't1', 'failed', d.t)];
        })()""", {"dis": dis, "t": FAILED})
        self.assertEqual(got, [{}, "failed"])

    def test_an_agent_never_dismissed_is_unchanged(self):
        dis = self.dismissed("failed", FAILED)
        got = att("""[
            A.attentionStatus(d.dis, 't2', 'blocked', d.b),
            A.attentionStatus({}, 't1', 'failed', d.t),
            A.attentionStatus(null, 't1', 'failed', d.t),
            A.attentionStatus(undefined, 't1', 'working', d.t),
            A.attentionStatus(d.dis, 't1', null, d.t),
        ]""", {"dis": dis, "t": FAILED, "b": BLOCKED})
        self.assertEqual(got, ["blocked", "failed", "failed", "working", None])

    def test_only_a_needs_you_status_is_ever_turned_idle(self):
        # A stored stamp that happens to match a working or done report changes nothing.
        got = att("""(() => {
            const dis = { t1: A.dismissStamp('working', d.t), t2: A.dismissStamp('done', d.b) };
            return [A.attentionStatus(dis, 't1', 'working', d.t), A.attentionStatus(dis, 't2', 'done', d.b)];
        })()""", {"t": FAILED, "b": BLOCKED})
        self.assertEqual(got, ["working", "done"])

    def test_a_terminal_without_a_time_or_turn_is_keyed_on_its_status_alone(self):
        bare = {"address": "devbox/t9"}
        got = att("""(() => {
            const dis = A.patchDismissed({}, 'devbox/t9', A.dismissStamp('failed', d.t));
            return [A.attentionStatus(dis, 'devbox/t9', 'failed', d.t), A.attentionStatus(dis, 'devbox/t9', 'blocked', d.t)];
        })()""", {"t": bare})
        self.assertEqual(got, ["idle", "blocked"])

    def test_norm_dismissed_keeps_only_string_entries(self):
        got = att("A.normDismissed(d)", {"t1": "failed@1#2", "t2": 5, "t3": None, "": "x"})
        self.assertEqual(got, {"t1": "failed@1#2"})
        self.assertEqual(att("[A.normDismissed(null), A.normDismissed([1, 2]), A.normDismissed('x')]"), [{}, {}, {}])


@unittest.skipUnless(NODE, "node is not installed")
class Prune(unittest.TestCase):
    def test_stale_entries_are_pruned(self):
        got = att("""(() => {
            const dis = {
                t1: A.dismissStamp('failed', d.t1),      // still the same report: kept
                t2: A.dismissStamp('blocked', d.t2),     // the terminal moved on: dropped
                gone: 'failed@1#1',                      // the terminal no longer exists: dropped
            };
            const now = new Map([
                ['t1', A.dismissStamp('failed', d.t1)],
                ['t2', A.dismissStamp('working', { ...d.t2, status_ms: 9000 })],
            ]);
            return A.pruneDismissed(dis, now);
        })()""", {"t1": FAILED, "t2": BLOCKED})
        self.assertEqual(list(got), ["t1"])

    def test_prune_takes_a_plain_object_too_and_tolerates_junk(self):
        got = att("A.pruneDismissed({ t1: 'a', t2: 'b' }, { t1: 'a' })")
        self.assertEqual(got, {"t1": "a"})
        self.assertEqual(att("[A.pruneDismissed(null, new Map()), A.pruneDismissed({ t1: 'a' }, null)]"), [{}, {}])


@unittest.skipUnless(NODE, "node is not installed")
class RankAndCounts(unittest.TestCase):
    """The Agents sections, the header counts, the Agents tab badge and the status bar counts share these."""

    def test_rank_puts_needs_you_first_then_done_working_idle(self):
        got = att("['blocked', 'failed', 'error', 'done', 'working', 'running', 'idle', 'ok', 'stopped', null].map(A.attentionRank)")
        self.assertEqual(got, [4, 4, 4, 3, 2, 2, 1, 0, 0, 0])

    def test_counts_bucket_failed_with_blocked(self):
        got = att("A.attentionCounts(['blocked', 'failed', 'error', 'done', 'working', 'idle', 'idle', 'ok', null])")
        self.assertEqual(got, {"blocked": 3, "done": 1, "working": 1, "idle": 2})

    def test_status_words_mirror_the_kit_status_map(self):
        # kit/kit.js STATUS_MAP is normStatus; attention.js cannot import kit.js (it imports the app), so it keeps a copy.
        src = Path(ROOT, "kit", "kit.js").read_text(encoding="utf-8")
        block = re.search(r"const STATUS_MAP = \{(.*?)\};", src, re.S).group(1)
        table = dict(re.findall(r'(\w+):\s*"(\w+)"', block))
        self.assertGreater(len(table), 10)
        got = att("d.map((k) => A.attentionWord(k))", list(table) + ["zzz-unknown"])
        self.assertEqual(got, list(table.values()) + ["idle"])


def read(*parts):
    with open(Path(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class KitWiring(unittest.TestCase):
    def setUp(self):
        self.kit = read("kit", "kit.js")

    def test_kit_reexports_the_rules_and_keeps_the_shared_state(self):
        self.assertIn('from "./attention.js"', self.kit)
        self.assertIn('shared("ob.dismissed")', self.kit)
        self.assertIn('setShared("ob.dismissed"', self.kit)
        self.assertIn("export function getDismissed(", self.kit)
        self.assertIn("export function updateDismissed(", self.kit)

    def test_sync_copies_the_module(self):
        want = read("kit", "attention.js")
        mods_root = Path(ROOT, "mods")
        targets = [d for d in sorted(mods_root.iterdir()) if d.is_dir() and d.name.startswith("ob-") and d.name != "ob-probe"]
        self.assertTrue(targets)
        for mod_dir in targets:
            self.assertEqual((mod_dir / "attention.js").read_text(encoding="utf-8"), want, mod_dir.name)
        with tempfile.TemporaryDirectory(prefix="att-sync-") as home:
            shutil.copytree(KIT_DIR, Path(home, "kit"))
            Path(home, "mods", "ob-sample").mkdir(parents=True)
            Path(home, "mods", "ob-stale").mkdir(parents=True)
            Path(home, "mods", "ob-stale", "attention.js").write_text("stale", encoding="utf-8")
            Path(home, "mods", "ob-probe").mkdir(parents=True)
            res = subprocess.run(["sh", Path(home, "kit", "sync.sh"), home], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(Path(home, "mods", "ob-sample", "attention.js").read_text(encoding="utf-8"), want)
            self.assertEqual(Path(home, "mods", "ob-stale", "attention.js").read_text(encoding="utf-8"), want)
            self.assertFalse(Path(home, "mods", "ob-probe", "attention.js").exists())

    def test_tab_and_space_attention_take_the_dismissals(self):
        self.assertIn("export function tabAttention(tab, ps, tmap = null, dis = null)", self.kit)
        self.assertIn("export function spaceAttention(space, ps, tmap = null, dis = null)", self.kit)


class AgentsWiring(unittest.TestCase):
    def setUp(self):
        self.src = read("mods", "ob-agents", "main.js")

    def test_sections_ranks_and_counts_come_from_the_shared_rule(self):
        self.assertNotRegex(self.src, r"const RANK = \{")
        self.assertIn("attentionRank(", self.src)
        self.assertIn("attentionCounts(", self.src)
        self.assertIn("agentAttention(a, tmap, dis)", self.src)

    def test_durations_follow_the_reported_status_not_the_dismissal(self):
        self.assertIn('const s = a.real === "done" ? "idle" : a.real;', self.src)

    def test_the_row_menu_and_a_hover_button_dismiss_and_restore(self):
        self.assertIn('"Dismiss"', self.src)
        self.assertIn('"Restore"', self.src)
        self.assertIn("ob-agents.dismiss:", self.src)
        self.assertIn("iconButton({ id: `dis-${a.address}`", self.src)

    def test_stale_dismissals_are_pruned(self):
        self.assertIn("pruneDismissedNow(", self.src)


class OtherPanelsWiring(unittest.TestCase):
    def test_status_bar_counts_come_from_the_shared_rule(self):
        src = read("mods", "ob-status", "main.js")
        self.assertIn("attentionCounts(", src)
        self.assertIn("agentAttention(a, tmap, dis)", src)

    def test_agents_tab_badge_comes_from_the_shared_rule(self):
        src = read("mods", "ob-strip", "main.js")
        self.assertIn("attentionCounts(", src)
        self.assertIn("agentAttention(a, tmap, dis)", src)

    def test_sessions_marks_and_pill_come_from_the_shared_rule(self):
        src = read("mods", "ob-sessions", "main.js")
        self.assertIn("paneAttention(", src)
        self.assertIn("this.dis = getDismissed()", src)
        self.assertIn("spaceAttention(n.space, ps, this.tmap, this.dis)", src)
        self.assertIn("tabAttention(tab, ps, this.tmap, this.dis)", src)

    def test_bookmarks_pill_comes_from_the_shared_rule(self):
        src = read("mods", "ob-bookmarks", "main.js")
        self.assertIn("paneAttention(", src)
        self.assertIn("attentionStatus(", src)

    def test_tab_bar_uses_tab_attention(self):
        src = read("mods", "ob-tabs", "main.js")
        self.assertIn("tabAttention(", src)

    def test_truth_panels_keep_the_reported_status(self):
        # The pane header, Properties and Outline say what the terminal reports.
        for mod in ("ob-pane", "ob-props", "ob-outline"):
            with self.subTest(mod=mod):
                src = read("mods", mod, "main.js")
                for name in ("attentionStatus(", "agentAttention(", "paneAttention(", "getDismissed(", "ob.dismissed"):
                    self.assertNotIn(name, src)


def run_kit(body, state=None):
    folder = tempfile.mkdtemp(prefix="kit-att-")
    try:
        for p in KIT_DIR.glob("*.js"):
            src = p.read_text(encoding="utf-8")
            if p.name == "kit.js":
                src = (src.replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                          .replace('from "gpui-base"', 'from "./gpui-base.js"')
                          .replace('from "herdr"', 'from "./herdr.js"'))
            (Path(folder) / p.name).write_text(src, encoding="utf-8")
        (Path(folder) / "gpui-kit.js").write_text(
            "const el = () => new Proxy(() => el(), { get: () => el }); export const div = el, svg = el, image = el;\n",
            encoding="utf-8",
        )
        (Path(folder) / "gpui-base.js").write_text(
            "const el = () => new Proxy(() => el(), { get: () => el }); export const h_flex = el, v_flex = el;\n",
            encoding="utf-8",
        )
        (Path(folder) / "herdr.js").write_text(
            f"const S = {json.dumps(state or {})};\n"
            "const sharedMap = new Map(Object.entries(S.shared || {}));\n"
            "export const theme = () => ({});\n"
            "export const run = () => {};\n"
            "export const exec = async () => ({ code: 0, stdout: '' });\n"
            "export const openOverlay = () => {};\n"
            "export const closeOverlay = () => {};\n"
            "export const layout = () => ({});\n"
            "export const shared = (k) => sharedMap.get(k);\n"
            "export const setShared = (k, v) => sharedMap.set(k, v);\n"
            "export const keys = () => [];\n"
            "export const spaces = () => S.spaces || [];\n"
            "export const agents = () => S.agents || [];\n"
            "export const terminals = () => S.terminals || [];\n"
            "export const panes = () => S.panes || [];\n"
            "export const focused = () => null;\n"
            "export const home = () => '/srv/home';\n"
            "export const appHome = () => '/app';\n"
            "export const readTextFile = async () => { throw new Error('ENOENT'); };\n"
            "export const window = () => ({ platform: 'linux' });\n",
            encoding="utf-8",
        )
        script = (
            f'import * as K from "{(Path(folder) / "kit.js").as_uri()}";\n'
            f'const r = (() => {{ {body} }})();\n'
            f'console.log(JSON.stringify(r));\n'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed")
class WorkingSubagentRecordRollup(unittest.TestCase):
    """An agent with a live working or blocked sub-agent record counts as working/blocked without module state."""

    def test_pure_is_record_live_and_effective_term_status(self):
        got = att("""(() => {
            const subs = [
                { parent: "t1", id: "ended1", ended: true },
                { parent: "t1", id: "abcdef1234567890", ended: true },
                { parent: "t2", id: "ended_other", ended: true },
            ];
            return {
                workIdle: A.effectiveTermStatus("idle", { address: "t1", state: "live", records: { a1: { state: "working" } } }, subs),
                workDone: A.effectiveTermStatus("done", { address: "t1", state: "live", records: { a1: { state: "working" } } }, subs),
                blockedOverWork: A.effectiveTermStatus("working", { address: "t1", state: "live", records: { a1: { state: "blocked" } } }, subs),
                failedBeatsRecWork: A.effectiveTermStatus("failed", { address: "t1", state: "live", records: { a1: { state: "working" } } }, subs),
                doneRecNoRaise: A.effectiveTermStatus("idle", { address: "t1", state: "live", records: { a1: { state: "done" } } }, subs),
                exitedIgnoresRec: A.effectiveTermStatus("idle", { address: "t1", state: "exited", records: { a1: { state: "working" } } }, subs),
                endedAgentSuppresses: A.effectiveTermStatus("idle", { address: "t1", state: "live", records: { ended1: { state: "working" } } }, subs),
                endedRunPrefixSuppresses: A.effectiveTermStatus("done", { address: "t1", state: "live", records: { "subagents/abcdef123456.0": { state: "working" } } }, subs),
                otherParentNoSuppress: A.effectiveTermStatus("idle", { address: "t1", state: "live", records: { ended_other: { state: "working" } } }, subs),
            };
        })()""")
        self.assertEqual(got, {
            "workIdle": "working",
            "workDone": "working",
            "blockedOverWork": "blocked",
            "failedBeatsRecWork": "failed",
            "doneRecNoRaise": "idle",
            "exitedIgnoresRec": "idle",
            "endedAgentSuppresses": "idle",
            "endedRunPrefixSuppresses": "done",
            "otherParentNoSuppress": "working",
        })

    def test_kit_attention_and_subagent_counts_suppress_ended_and_exited_records(self):
        state = {
            "terminals": [
                {"address": "t_idle", "state": "live", "status_ms": 100, "turn": 1, "records": {"a1": {"state": "working"}}},
                {"address": "t_blk", "state": "live", "status_ms": 200, "turn": 2, "records": {"b1": {"state": "blocked"}}},
                {"address": "t_end", "state": "live", "status_ms": 300, "turn": 3, "records": {"c1": {"state": "working"}}},
                {"address": "t_dead", "state": "exited", "status_ms": 400, "turn": 4, "records": {"d1": {"state": "working"}}},
            ],
            "panes": [
                {"pane": "p1", "tab": "tb1", "terminal": "t_idle", "status": "idle"},
                {"pane": "p2", "tab": "tb2", "terminal": "t_end", "status": "done"},
            ],
            "spaces": [
                {"id": "sp1", "status": "idle", "tabs": [{"id": "tb1", "status": "idle"}]},
                {"id": "sp2", "status": "done", "tabs": [{"id": "tb2", "status": "done"}]},
            ],
            "shared": {
                "ob.subagents": {
                    "v": 2,
                    "providers": {"alpha": {"id": "alpha", "name": "Alpha", "noun": "Alpha agent", "caps": ["subagents"]}},
                    "terms": {},
                    "subagents": [
                        {"key": "local:c1", "machine": None, "parent": "t_end", "provider": "alpha", "id": "c1", "live": False, "ended": True},
                    ],
                    "runs": [],
                },
            },
        }
        got = run_kit("""
            const tmap = K.terminalsByAddress();
            const ps = [
                { pane: "p1", tab: "tb1", terminal: "t_idle", status: "idle" },
                { pane: "p2", tab: "tb2", terminal: "t_end", status: "done" },
            ];
            const sp1 = { id: "sp1", status: "idle", tabs: [{ id: "tb1", status: "idle" }] };
            const sp2 = { id: "sp2", status: "done", tabs: [{ id: "tb2", status: "done" }] };
            const blkTerm = tmap.get("t_blk");
            const dis = K.patchDismissed({}, "t_blk", K.dismissStamp(K.effectiveStatus("done", "t_blk", tmap), blkTerm));
            const counts = K.subagentCounts();
            return {
                agIdleRecWork: K.agentAttention({ address: "t_idle", status: "idle" }, tmap, {}),
                agBlkRec: K.agentAttention({ address: "t_blk", status: "done" }, tmap, {}),
                agBlkDismissed: K.agentAttention({ address: "t_blk", status: "done" }, tmap, dis),
                agEndedSuppressed: K.agentAttention({ address: "t_end", status: "done" }, tmap, {}),
                agExitedIgnored: K.agentAttention({ address: "t_dead", status: "done" }, tmap, {}),
                tabWork: K.tabAttention(sp1.tabs[0], ps, tmap, {}),
                spaceWork: K.spaceAttention(sp1, ps, tmap, {}),
                tabSuppressed: K.tabAttention(sp2.tabs[0], ps, tmap, {}),
                spaceSuppressed: K.spaceAttention(sp2, ps, tmap, {}),
                subEndLive: K.subagentsOf("t_end").live,
                subDeadLive: K.subagentsOf("t_dead").live,
                countIdle: counts.byParent.get("t_idle"),
                countEnd: counts.byParent.get("t_end"),
                countDead: counts.byParent.get("t_dead") ?? null,
            };
        """, state)
        self.assertEqual(got, {
            "agIdleRecWork": "working",
            "agBlkRec": "blocked",
            "agBlkDismissed": "idle",
            "agEndedSuppressed": "done",
            "agExitedIgnored": "done",
            "tabWork": "working",
            "spaceWork": "working",
            "tabSuppressed": "done",
            "spaceSuppressed": "done",
            "subEndLive": 0,
            "subDeadLive": 0,
            "countIdle": {"live": 1, "total": 1},
            "countEnd": {"live": 0, "total": 1},
            "countDead": None,
        })

    def test_live_child_terminals_and_provider_subagents_raise_parent_attention(self):
        pure = att("""(() => {
            const liveWork = [{ address: "t1z", parent: "t1n", state: "live", status: "working" }];
            const liveBlk = [{ address: "t1z", parent: "t1n", state: "live", status: "blocked" }];
            const liveIdle = [{ address: "t1z", parent: "t1n", state: "live", status: "idle" }];
            const exitedWork = [{ address: "t1z", parent: "t1n", state: "exited", status: "working" }];
            const liveSub = [{ parent: "t1n", id: "s1", live: true, ended: false, state: "working" }];
            const blkSub = [{ parent: "t1n", id: "s1", live: true, ended: false, state: "blocked" }];
            const parent = { address: "t1n", state: "live" };
            return {
                childWorkRaisesIdle: A.effectiveTermStatus("idle", parent, null, A.attentionWord, liveWork),
                childWorkRaisesDone: A.effectiveTermStatus("done", parent, null, A.attentionWord, liveWork),
                childBlkRaisesWork: A.effectiveTermStatus("working", parent, null, A.attentionWord, liveBlk),
                childIdleNoRaise: A.effectiveTermStatus("idle", parent, null, A.attentionWord, liveIdle),
                childExitedNoRaise: A.effectiveTermStatus("idle", parent, null, A.attentionWord, exitedWork),
                liveSubNoRecsRaises: A.effectiveTermStatus("idle", parent, liveSub, A.attentionWord, null),
                blkSubNoRecsRaises: A.effectiveTermStatus("idle", parent, blkSub, A.attentionWord, null),
            };
        })()""")
        self.assertEqual(pure, {
            "childWorkRaisesIdle": "working",
            "childWorkRaisesDone": "working",
            "childBlkRaisesWork": "blocked",
            "childIdleNoRaise": "idle",
            "childExitedNoRaise": "idle",
            "liveSubNoRecsRaises": "working",
            "blkSubNoRecsRaises": "blocked",
        })

        state = {
            "terminals": [
                {"address": "t_parent", "parent": None, "state": "live", "status": "idle"},
                {"address": "t_child", "parent": "t_parent", "state": "live", "status": "working"},
                {"address": "t_grand_root", "parent": None, "state": "live", "status": "idle"},
                {"address": "t_mid", "parent": "t_grand_root", "state": "live", "status": "idle"},
                {"address": "t_leaf", "parent": "t_mid", "state": "live", "status": "working"},
                {"address": "t_done_parent", "parent": None, "state": "live", "status": "idle"},
                {"address": "t_done_child", "parent": "t_done_parent", "state": "live", "status": "done"},
                {"address": "t_sub_parent", "parent": None, "state": "live", "status": "idle"},
            ],
            "shared": {
                "ob.subagents": {
                    "v": 2,
                    "providers": {"alpha": {"id": "alpha", "name": "Alpha", "noun": "Alpha agent", "caps": ["subagents"]}},
                    "terms": {},
                    "subagents": [
                        {"key": "local:s1", "machine": None, "parent": "t_sub_parent", "provider": "alpha", "id": "s1", "live": True, "ended": False},
                    ],
                    "runs": [],
                },
            },
        }
        got = run_kit("""
            const tmap = K.terminalsByAddress();
            const ps = [
                { pane: "p1", tab: "tb1", terminal: "t_parent", status: "idle" },
                { pane: "p2", tab: "tb2", terminal: "t_grand_root", status: "idle" },
                { pane: "p3", tab: "tb3", terminal: "t_done_parent", status: "idle" },
                { pane: "p4", tab: "tb4", terminal: "t_sub_parent", status: "idle" },
            ];
            const sp1 = { id: "sp1", status: "idle", tabs: [{ id: "tb1", status: "idle" }] };
            const sp2 = { id: "sp2", status: "idle", tabs: [{ id: "tb2", status: "idle" }] };
            const sp3 = { id: "sp3", status: "idle", tabs: [{ id: "tb3", status: "idle" }] };
            const sp4 = { id: "sp4", status: "idle", tabs: [{ id: "tb4", status: "idle" }] };
            return {
                agChild: K.agentAttention({ address: "t_parent", status: "idle" }, tmap, {}),
                tabChild: K.tabAttention(sp1.tabs[0], ps, tmap, {}),
                spaceChild: K.spaceAttention(sp1, ps, tmap, {}),
                tabGrand: K.tabAttention(sp2.tabs[0], ps, tmap, {}),
                tabDoneChild: K.tabAttention(sp3.tabs[0], ps, tmap, {}),
                tabLiveSub: K.tabAttention(sp4.tabs[0], ps, tmap, {}),
                spaceLiveSub: K.spaceAttention(sp4, ps, tmap, {}),
            };
        """, state)
        self.assertEqual(got, {
            "agChild": "working",
            "tabChild": "working",
            "spaceChild": "working",
            "tabGrand": "working",
            "tabDoneChild": "idle",
            "tabLiveSub": "working",
            "spaceLiveSub": "working",
        })


if __name__ == "__main__":
    unittest.main()
