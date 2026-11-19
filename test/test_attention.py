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
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
ATTENTION = Path(ROOT, "kit", "attention.js")
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
    return Path(ROOT, *parts).read_text(encoding="utf-8")


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
        self.assertIn('"$KIT/attention.js"', read("kit", "sync.sh"))

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


if __name__ == "__main__":
    unittest.main()
