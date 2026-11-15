"""kit/feed_age.js: when the feed counts as paused, what to say, and when the scanner publishes a heartbeat.
Pure functions, run under node (the kit copies are byte-equal, see test_repo)."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
FEED_AGE = Path(ROOT, "kit", "feed_age.js")
NODE = shutil.which("node")


def run_node(body):
    src = (f'import * as F from "{FEED_AGE.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class FeedAge(unittest.TestCase):
    def test_fresh_within_two_minutes(self):
        self.assertIsNone(run_node("return F.feedLine(1000000, 1000000 + 120000);"))
        self.assertIsNone(run_node("return F.feedLine(1000000, 1000000 + 5000);"))

    def test_stale_after_two_minutes_and_says_so(self):
        self.assertEqual(run_node("return F.feedLine(1000000, 1000000 + 120001);"), "feed paused · last scan 2m ago")
        self.assertEqual(run_node("return F.feedLine(1000000, 1000000 + 9 * 60000 + 30000);"), "feed paused · last scan 9m ago")

    def test_hours_past_an_hour(self):
        self.assertEqual(run_node("return F.feedLine(1000, 1000 + 3 * 3600000 + 1);"), "feed paused · last scan 3h ago")

    def test_no_payload_says_nothing(self):
        self.assertIsNone(run_node("return F.feedLine(undefined, 1000);"))
        self.assertIsNone(run_node("return F.feedLine(0, 1000);"))

    def test_heartbeat_publishes_when_content_is_unchanged_for_a_minute(self):
        # A quiet system must still say "fresh": publish a same-content heartbeat once a minute, never more often.
        self.assertTrue(run_node("return F.publishDue({ same: false, now: 5, beatAt: 5 });"))
        self.assertFalse(run_node("return F.publishDue({ same: true, now: 30000, beatAt: 0 });"))
        self.assertTrue(run_node("return F.publishDue({ same: true, now: 60000, beatAt: 0 });"))

    def test_beat_and_stale_thresholds_agree(self):
        # The heartbeat (a minute) must land inside the stale window (two minutes), with room to spare.
        self.assertLess(run_node("return F.FEED_BEAT_MS;"), run_node("return F.FEED_STALE_MS;"))


class Consumers(unittest.TestCase):
    """The panels that show feed data say when it is paused (they call kit feedLine on the payload's `at`)."""

    def test_subagents_and_usage_say_when_the_feed_is_paused(self):
        for mod, marker in (("ob-outline", 'id("feed-paused")'), ("ob-props", 'id("u-paused")')):
            with self.subTest(mod=mod):
                src = Path(ROOT, "mods", mod, "main.js").read_text(encoding="utf-8")
                self.assertIn("feedLine(", src)
                self.assertIn(marker, src)


    def test_a_feed_is_paused_only_past_the_stale_threshold_and_only_with_a_payload(self):
        self.assertEqual(run_node("return [F.feedPaused(1000, 1000 + 120000), F.feedPaused(1000, 1000 + 120001), F.feedPaused(undefined, 5), F.feedPaused(0, 5)];"),
                         [False, True, False, False])

if __name__ == "__main__":
    unittest.main()
