"""mods/ob-recent: the timeline records agent events (needs you, finished) only for main agents, the ones whose terminal
sits in a pane of a tab. A background agent (an hc run --bg worker, a sub-agent) never makes a timeline entry. The rule
is a pure function in mods/ob-recent/events.js, run here through node; main.js must use it."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest

ROOT = home_guard.ROOT
MOD = os.path.join(ROOT, "mods", "ob-recent")
EVENTS = os.path.join(MOD, "events.js")
MAIN = os.path.join(MOD, "main.js")

# Shaped like agents() entries (AgentInfo), trimmed to the fields used. t3c is in a pane; t3j is a background worker.
MAIN_AGENT = {"address": "t3c", "pane": "p1", "tab": "tb1", "status": "working"}
BG_AGENT = {"address": "t3j", "pane": "", "tab": "tb9", "status": "working"}
PLACED = ["t3c"]


def run_node(code, payload):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def step(prev, agents, placed=PLACED):
    """Run agentChanges once. prev is a dict (address -> status) or None; returns (changes, next) as plain data:
    changes as [address, status] pairs, next as a dict."""
    url = "file://" + EVENTS
    code = (f'import * as e from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'const prev = d.prev == null ? null : new Map(Object.entries(d.prev));\n'
            'const r = e.agentChanges(prev, d.agents, new Set(d.placed));\n'
            'process.stdout.write(JSON.stringify({ changes: r.changes.map((c) => [c.agent.address, c.status]), '
            'next: Object.fromEntries(r.next) }));\n')
    out = run_node(code, {"prev": prev, "agents": agents, "placed": placed})
    return [tuple(c) for c in out["changes"]], out["next"]


def with_status(agent, status):
    return {**agent, "status": status}


class BackgroundAgents(unittest.TestCase):
    def test_a_background_agent_finishing_records_nothing(self):
        prev = {"t3j": "working"}
        changes, _ = step(prev, [with_status(BG_AGENT, "idle")])
        self.assertEqual(changes, [])

    def test_a_background_agent_needing_you_records_nothing(self):
        prev = {"t3j": "working"}
        changes, _ = step(prev, [with_status(BG_AGENT, "blocked")])
        self.assertEqual(changes, [])

    def test_a_background_agent_still_updates_the_status_it_keeps(self):
        # Kept for later: if the agent is placed later, its next change is compared with what it was.
        _, nxt = step({"t3j": "working"}, [with_status(BG_AGENT, "idle")])
        self.assertEqual(nxt["t3j"], "idle")


class MainAgents(unittest.TestCase):
    def test_a_main_agent_finishing_records_done(self):
        changes, _ = step({"t3c": "working"}, [with_status(MAIN_AGENT, "idle")])
        self.assertEqual(changes, [("t3c", "done")])

    def test_a_main_agent_done_records_done(self):
        changes, _ = step({"t3c": "working"}, [with_status(MAIN_AGENT, "done")])
        self.assertEqual(changes, [("t3c", "done")])

    def test_a_main_agent_needing_you_records_blocked(self):
        changes, _ = step({"t3c": "working"}, [with_status(MAIN_AGENT, "blocked")])
        self.assertEqual(changes, [("t3c", "blocked")])

    def test_no_change_no_event(self):
        changes, _ = step({"t3c": "working"}, [MAIN_AGENT])
        self.assertEqual(changes, [])

    def test_the_first_call_only_seeds(self):
        changes, nxt = step(None, [with_status(MAIN_AGENT, "blocked")])
        self.assertEqual(changes, [])
        self.assertEqual(nxt["t3c"], "blocked")

    def test_a_main_agent_that_went_away_records_nothing(self):
        changes, nxt = step({"t3c": "working"}, [])
        self.assertEqual(changes, [])
        self.assertNotIn("t3c", nxt)

    def test_a_background_agent_is_placed_then_finishes_records_done(self):
        # Once its terminal is in a pane, its changes are main changes.
        _, nxt = step({"t3j": "working"}, [with_status(BG_AGENT, "working")], placed=[])
        changes, _ = step(nxt, [with_status(BG_AGENT, "idle")], placed=["t3j"])
        self.assertEqual(changes, [("t3j", "done")])


class Wiring(unittest.TestCase):
    def test_main_js_records_through_the_events_module_and_the_kit_filter(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertTrue('from "./events.js"' in src, "main.js must record through ./events.js")
        self.assertTrue("agentChanges(" in src, "main.js must call agentChanges")
        self.assertTrue("placedTerminals(" in src, "main.js must pass the placed terminals from the kit")
        self.assertFalse("agents().some((a) => a.address === e.address)" in src,
                         "a row's gone check must use the main agents, not every agent")


ROWS = os.path.join(MOD, "rows.js")


def rows_call(fn, *args):
    """Call an exported function of rows.js with JSON-shaped arguments; returns its JSON result."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    url = "file://" + ROWS
    code = (f'import * as r from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const a = JSON.parse(s);\n'
            f'const out = r.{fn}(...a);\n'
            'process.stdout.write(JSON.stringify(out === undefined ? null : out));\n')
    res = subprocess.run([node, "--input-type=module", "-e", code], input=json.dumps(list(args)),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


SPACE_HERE = {"id": "s1", "name": "Work", "machine": None, "tabs": [
    {"id": "t1", "name": "fix login", "named": True, "index": 1},
    {"id": "t2", "name": "2", "named": False, "index": 2},
]}
SPACE_REMOTE = {"id": "s2", "name": "Notes", "machine": "devbox", "tabs": [
    {"id": "t5", "name": "reading", "named": True, "index": 1},
]}
PANE_ZSH = {"pane": "p1", "tab": "t1", "terminal": "t1a", "title": "zsh", "program": {"name": "zsh"}}
PANE_CLAUDE = {"pane": "p2", "tab": "t2", "terminal": "t3c", "title": "Claude Code", "program": {"name": "Claude Code", "agent": True}}
AGENT_LIVE = {"address": "t3c", "pane": "p2", "space": "s1", "tab": "t2", "tab_name": "2", "space_name": "Work",
              "status": "blocked", "title": "Claude Code", "program": {"name": "Claude Code"}}


class RowLabels(unittest.TestCase):
    def test_a_visit_row_names_the_tab_and_its_space(self):
        entry = {"kind": "visit", "space": "s1", "tab": "t1", "pane": "p1", "at": 1}
        live = {"spaceName": "Work", "machine": None, "tabName": "fix login", "tabNamed": True, "paneTitle": "zsh"}
        row = rows_call("rowText", entry, live)
        self.assertEqual(row["main"], "fix login")
        self.assertEqual(row["sub"], "Work")
        self.assertEqual(row["trail"], "visited")
        self.assertFalse(row["closed"])

    def test_an_unnamed_tab_is_called_by_its_place(self):
        entry = {"kind": "visit", "space": "s1", "tab": "t2", "at": 1}
        live = {"spaceName": "Work", "machine": None, "tabName": "2", "tabNamed": False}
        self.assertEqual(rows_call("rowText", entry, live)["main"], "Tab 2")

    def test_the_machine_shows_only_when_it_is_not_this_computer(self):
        entry = {"kind": "visit", "space": "s2", "tab": "t5", "at": 1}
        remote = rows_call("rowText", entry, {"spaceName": "Notes", "machine": "devbox", "tabName": "reading", "tabNamed": True})
        self.assertEqual(remote["sub"], "Notes · devbox")
        local = rows_call("rowText", entry, {"spaceName": "Notes", "machine": None, "tabName": "reading", "tabNamed": True})
        self.assertEqual(local["sub"], "Notes")

    def test_an_agent_row_names_the_agent_title_when_it_differs_from_the_tab(self):
        entry = {"kind": "agent", "address": "t3c", "status": "blocked", "at": 1}
        live = {"spaceName": "Work", "machine": None, "tabName": "fix login", "tabNamed": True,
                "agentTitle": "Claude Code"}
        row = rows_call("rowText", entry, live)
        self.assertEqual(row["main"], "fix login")
        self.assertEqual(row["trail"], "Claude Code · needs you")

    def test_an_agent_row_leaves_the_title_out_when_it_is_the_tab_name(self):
        entry = {"kind": "agent", "address": "t3c", "status": "done", "at": 1}
        live = {"spaceName": "Work", "machine": None, "tabName": "fix login", "tabNamed": True,
                "agentTitle": "fix login"}
        self.assertEqual(rows_call("rowText", entry, live)["trail"], "finished")

    def test_a_finished_agent_says_finished(self):
        entry = {"kind": "agent", "address": "t3c", "status": "done", "at": 1}
        live = {"spaceName": "Work", "machine": None, "tabName": "fix login", "tabNamed": True}
        self.assertEqual(rows_call("rowText", entry, live)["trail"], "finished")

    def test_a_closed_tab_is_dimmed_and_says_closed(self):
        entry = {"kind": "visit", "space": "s1", "tab": "t1", "at": 1, "spaceName": "Work",
                 "tabName": "fix login", "tabNamed": True, "machine": None}
        row = rows_call("rowText", entry, None)
        self.assertTrue(row["closed"])
        self.assertEqual(row["main"], "fix login")
        self.assertEqual(row["sub"], "Work")
        self.assertEqual(row["trail"], "visited · closed")

    def test_old_entries_without_the_new_fields_still_render(self):
        visit = rows_call("rowText", {"kind": "visit", "space": "s1", "tab": "t1", "pane": "p1", "at": 1}, None)
        self.assertEqual(visit["main"], "Closed tab")
        self.assertTrue(visit["closed"])
        agent = rows_call("rowText", {"kind": "agent", "address": "t3c", "status": "blocked", "at": 1,
                                      "label": "Work · fix login"}, None)
        self.assertEqual(agent["main"], "Work · fix login")
        self.assertEqual(agent["trail"], "needs you · closed")

    def test_the_path_gives_space_tab_and_pane_for_a_tooltip(self):
        entry = {"kind": "visit", "space": "s2", "tab": "t5", "at": 1}
        live = {"spaceName": "Notes", "machine": "devbox", "tabName": "reading", "tabNamed": True, "paneTitle": "nvim"}
        self.assertEqual(rows_call("rowText", entry, live)["path"], "Notes › reading › nvim (devbox)")


class ClickTarget(unittest.TestCase):
    def test_a_visit_to_a_live_tab_focuses_the_tab_and_pane(self):
        entry = {"kind": "visit", "space": "s1", "tab": "t1", "pane": "p1", "at": 1}
        live = {"space": "s1", "tab": "t1", "pane": "p1", "tabName": "fix login", "tabNamed": True, "spaceName": "Work"}
        self.assertEqual(rows_call("clickPlan", entry, live), {"space": "s1", "tab": "t1", "pane": "p1"})

    def test_an_agent_event_focuses_its_terminal_when_it_is_still_a_main_agent(self):
        entry = {"kind": "agent", "address": "t3c", "status": "blocked", "at": 1}
        live = {"space": "s1", "tab": "t2", "terminal": "t3c"}
        self.assertEqual(rows_call("clickPlan", entry, live), {"space": "s1", "tab": "t2", "terminal": "t3c"})

    def test_an_agent_event_whose_agent_left_focuses_the_tab_only(self):
        entry = {"kind": "agent", "address": "t3c", "status": "done", "at": 1}
        live = {"space": "s1", "tab": "t2", "terminal": None}
        self.assertEqual(rows_call("clickPlan", entry, live), {"space": "s1", "tab": "t2", "terminal": None})

    def test_a_closed_tab_gives_a_notice_and_no_focus(self):
        entry = {"kind": "visit", "space": "s1", "tab": "t1", "at": 1}
        plan = rows_call("clickPlan", entry, None)
        self.assertIn("notice", plan)
        self.assertNotIn("tab", plan)


class LiveTargets(unittest.TestCase):
    def world(self, spaces=None, panes=None, agents=None, mains=None):
        return {"spaces": spaces if spaces is not None else [SPACE_HERE, SPACE_REMOTE],
                "panes": panes if panes is not None else [PANE_ZSH, PANE_CLAUDE],
                "agents": agents if agents is not None else [AGENT_LIVE],
                "mains": mains if mains is not None else ["t3c"]}

    def test_a_tab_is_found_by_id_after_it_moved_in_its_space(self):
        moved = {**SPACE_HERE, "tabs": [SPACE_HERE["tabs"][1], SPACE_HERE["tabs"][0]]}
        live = rows_call("liveOf", {"kind": "visit", "space": "s1", "tab": "t1", "pane": "p1", "at": 1},
                         self.world(spaces=[moved, SPACE_REMOTE]))
        self.assertEqual(live["tab"], "t1")
        self.assertEqual(live["tabName"], "fix login")

    def test_a_missing_tab_is_not_live(self):
        live = rows_call("liveOf", {"kind": "visit", "space": "s1", "tab": "gone", "at": 1}, self.world())
        self.assertIsNone(live)

    def test_a_missing_pane_still_leaves_the_tab_live(self):
        live = rows_call("liveOf", {"kind": "visit", "space": "s1", "tab": "t1", "pane": "p9", "at": 1}, self.world())
        self.assertEqual(live["tab"], "t1")
        self.assertIsNone(live["pane"])

    def test_an_old_agent_entry_resolves_through_the_agent_now(self):
        live = rows_call("liveOf", {"kind": "agent", "address": "t3c", "status": "blocked", "at": 1}, self.world())
        self.assertEqual(live["tab"], "t2")
        self.assertEqual(live["terminal"], "t3c")
        self.assertEqual(live["agentTitle"], "Claude Code")

    def test_an_agent_that_is_not_a_main_agent_gives_no_terminal(self):
        live = rows_call("liveOf", {"kind": "agent", "address": "t3c", "status": "blocked", "at": 1},
                         self.world(mains=[]))
        self.assertEqual(live["tab"], "t2")
        self.assertIsNone(live["terminal"])


class StoredRecords(unittest.TestCase):
    def test_a_visit_stores_its_ids_and_names(self):
        rec = rows_call("visitRecord", {"space": "s2", "tab": "t5", "pane": None, "terminal": None, "at": 7},
                        [SPACE_HERE, SPACE_REMOTE], [])
        self.assertEqual({k: rec[k] for k in ("kind", "space", "tab", "at")}, {"kind": "visit", "space": "s2", "tab": "t5", "at": 7})
        self.assertEqual(rec["spaceName"], "Notes")
        self.assertEqual(rec["machine"], "devbox")
        self.assertEqual(rec["tabName"], "reading")
        self.assertTrue(rec["tabNamed"])
        self.assertIsNone(rec["paneTitle"])

    def test_a_visit_to_a_pane_stores_the_pane_title(self):
        rec = rows_call("visitRecord", {"space": "s1", "tab": "t1", "pane": "p1", "terminal": "t1a", "at": 7},
                        [SPACE_HERE], [PANE_ZSH])
        self.assertEqual(rec["paneTitle"], "zsh")
        self.assertEqual(rec["pane"], "p1")

    def test_an_agent_event_stores_the_tab_space_and_agent_title(self):
        rec = rows_call("agentRecord", AGENT_LIVE, [SPACE_HERE], "blocked", 9)
        self.assertEqual(rec["kind"], "agent")
        self.assertEqual(rec["address"], "t3c")
        self.assertEqual(rec["space"], "s1")
        self.assertEqual(rec["tab"], "t2")
        self.assertEqual(rec["status"], "blocked")
        self.assertEqual(rec["spaceName"], "Work")
        self.assertEqual(rec["tabName"], "2")
        self.assertFalse(rec["tabNamed"])
        self.assertEqual(rec["agentTitle"], "Claude Code")
        self.assertIsNone(rec["machine"])


class Wiring2(unittest.TestCase):
    def test_main_js_uses_the_row_module(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertTrue('from "./rows.js"' in src, "main.js must build rows through ./rows.js")



EVENTS_FILE = EVENTS


def new_visits(entries, hist_seen, cleared_at):
    """Run newVisits(entries, histSeen, clearedAt) from events.js; returns (take, histSeen) as plain data."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    url = "file://" + EVENTS_FILE
    code = (f'import * as e from "{url}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'const r = e.newVisits(d.entries, d.histSeen, d.clearedAt);\n'
            'process.stdout.write(JSON.stringify(r));\n')
    res = subprocess.run([node, "--input-type=module", "-e", code],
                         input=json.dumps({"entries": entries, "histSeen": hist_seen, "clearedAt": cleared_at}),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out = json.loads(res.stdout)
    return [e["at"] for e in out["take"]], out["histSeen"]


def hist_entry(at, tab="tb1"):
    """A router entry in ob.history, shaped as ob-tabs writes it."""
    return {"space": "spf1", "tab": tab, "pane": "p1", "terminal": "t1a", "at": at}


class VisitsAfterClear(unittest.TestCase):
    # The failing shape: the store holds nothing (the clear emptied it), histSeen is missing, and the router still
    # holds visits from before the clear. Those must not be recorded again (the render would hide them anyway).
    def test_router_visits_from_before_a_clear_are_not_recorded_again(self):
        entries = [hist_entry(100), hist_entry(200)]
        take, hist_seen = new_visits(entries, None, 300)
        self.assertEqual(take, [])
        self.assertEqual(hist_seen, 200, "the newest router entry is seen, so it is not looked at again")

    def test_visits_after_the_clear_are_recorded(self):
        entries = [hist_entry(100), hist_entry(400)]
        take, hist_seen = new_visits(entries, 100, 300)
        self.assertEqual(take, [400])
        self.assertEqual(hist_seen, 400)

    def test_a_visit_already_recorded_is_not_recorded_again(self):
        entries = [hist_entry(100), hist_entry(200), hist_entry(300)]
        take, _ = new_visits(entries, 200, 0)
        self.assertEqual(take, [300])

    def test_no_clear_and_no_history_records_nothing_and_keeps_histSeen(self):
        take, hist_seen = new_visits([], 500, 0)
        self.assertEqual(take, [])
        self.assertEqual(hist_seen, 500)

    def test_main_js_records_router_visits_through_newVisits(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertTrue("newVisits(" in src, "main.js must take the router visits to record from newVisits")
        self.assertFalse("top !== this.histSeen" in src, "main.js must not keep its own histSeen loop")


def keep_newest(events, adds, cap):
    """Run keepNewest(events, adds, max) from events.js; returns the kept list."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    code = (f'import * as e from "file://{EVENTS_FILE}";\n'
            'let s = ""; process.stdin.setEncoding("utf8");\n'
            'for await (const c of process.stdin) s += c;\n'
            'const d = JSON.parse(s);\n'
            'process.stdout.write(JSON.stringify(e.keepNewest(d.events, d.adds, d.max)));\n')
    return run_node(code, {"events": events, "adds": adds, "max": cap})


def one_by_one(events, adds, cap):
    """What pushing each entry alone gave: append, then keep the newest `cap` visits and the newest `cap` others."""
    for ev in adds:
        events = events + [ev]
        events = [e for e in events if e["kind"] == "visit"][-cap:] + [e for e in events if e["kind"] != "visit"][-cap:]
    return events


class BatchedRecords(unittest.TestCase):
    """The router's history is copied in one batch: one filter and one save, not one per entry inside render()."""
    def test_a_batch_keeps_what_one_by_one_pushes_kept(self):
        old = [{"kind": "visit", "at": i} for i in range(1, 4)] + [{"kind": "agent", "at": i} for i in range(10, 13)]
        adds = [{"kind": "visit", "at": i} for i in range(20, 26)] + [{"kind": "agent", "at": 30}]
        for cap in (3, 5, 200):
            with self.subTest(cap=cap):
                self.assertEqual(keep_newest(old, adds, cap), one_by_one(old, adds, cap))

    def test_nothing_added_keeps_the_list(self):
        old = [{"kind": "visit", "at": 1}, {"kind": "agent", "at": 2}]
        self.assertEqual(keep_newest(old, [], 200), old)

    def test_main_js_pushes_the_router_visits_at_once_and_saves_once(self):
        with open(MAIN, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("for (const e of take) this.push(", src, "one push (one filter, one save) per router entry")
        self.assertIn("keepNewest(", src)
        push = src[src.index("  push("):src.index("  track(")]
        self.assertEqual(push.count("save("), 1)


if __name__ == "__main__":
    unittest.main()
