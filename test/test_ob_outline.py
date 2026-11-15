"""ob-outline (the former Subagents panel, folded in): a click (or Enter) on a subagent row expands it in place, a second
click collapses it. The decisions live in mods/ob-outline/rows.js, actions.js, terminals.js and tree.js (no Herdr or kit
imports), so they run here under node. Also: which agents sit under which pane, and that no file names the old panel."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
ROWS = Path(ROOT, "mods", "ob-outline", "rows.js")
MAIN = Path(ROOT, "mods", "ob-outline", "main.js")
NODE = shutil.which("node")


def run_js(body):
    """Import rows.js in node, run `body` (JS that uses `rowClick`), return the JSON it prints."""
    src = f'import {{ rowClick }} from "{ROWS.as_uri()}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed: the subagent click test is skipped")
class RowClick(unittest.TestCase):
    def test_first_click_expands_the_row(self):
        r = run_js('return { open: [...rowClick("run-a", new Set(), {}).expanded], notice: rowClick("run-a", new Set(), {}).notice };')
        self.assertEqual(r["open"], ["run-a"])
        self.assertIsNone(r["notice"])

    def test_second_click_collapses_it(self):
        r = run_js('return [...rowClick("run-a", new Set(["run-a"]), {}).expanded];')
        self.assertEqual(r, [])

    def test_other_rows_stay_as_they_were(self):
        r = run_js('return [...rowClick("cl-b", new Set(["run-a"]), {}).expanded].sort();')
        self.assertEqual(r, ["cl-b", "run-a"])

    def test_the_given_set_is_not_changed(self):
        r = run_js('const s = new Set(["x"]); rowClick("y", s, {}); return [...s];')
        self.assertEqual(r, ["x"])

    def test_a_starting_run_cannot_expand_and_says_why(self):
        r = run_js('const x = rowClick("rec:a#s", new Set(), { pending: true }); return { open: [...x.expanded], notice: x.notice };')
        self.assertEqual(r["open"], [])
        self.assertIn("next scan", r["notice"])

    def test_main_uses_the_shared_decision_for_card_heads_and_enter(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('from "./rows.js"', src)
        self.assertGreaterEqual(src.count("this.click("), 3)  # run head, Claude head, keyboard Enter



ACTIONS = Path(ROOT, "mods", "ob-outline", "actions.js")
VIEWER = Path(ROOT, "mods", "ob-outline", "viewer.js")
OBC = Path(ROOT, "mods", "ob-outline", "obc.js")


def run_actions(body):
    """Import actions.js in node, run `body` (JS using the exports), return the JSON it prints."""
    src = (f'import * as A from "{ACTIONS.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed: the action tests are skipped")
class ResolveKey(unittest.TestCase):
    def test_a_claude_key_with_a_hash_is_found_whole(self):
        # A Claude agent seen only through a live record has the key "<parent>#<id>": it is not a pi step.
        r = run_actions('return A.resolveKey("term1#a1b2", { runs: [], claude: ["term1#a1b2"] });')
        self.assertEqual(r, {"key": "term1#a1b2", "step": None})

    def test_a_pi_step_key_names_run_and_step(self):
        r = run_actions('return A.resolveKey("local:run1#2", { runs: ["local:run1"], claude: [] });')
        self.assertEqual(r, {"key": "local:run1", "step": 2})

    def test_an_unknown_key_resolves_to_nothing(self):
        r = run_actions('return A.resolveKey("nope", { runs: [], claude: [] });')
        self.assertIsNone(r)


@unittest.skipUnless(NODE, "node is not installed: the action tests are skipped")
class TranscriptPlan(unittest.TestCase):
    def test_a_claude_agent_with_a_transcript_opens_it(self):
        r = run_actions('return A.transcriptPlan({ transcript: "/data/sess/agent-a1.jsonl", live: true, desc: "Fix" });')
        self.assertEqual(r["open"], True)
        self.assertEqual(r["path"], "/data/sess/agent-a1.jsonl")
        self.assertEqual(r["title"], "Fix · transcript")

    def test_a_live_record_without_a_transcript_says_why(self):
        r = run_actions('return A.transcriptPlan({ transcript: null, live: true, desc: "Fix" });')
        self.assertEqual(r["open"], False)
        self.assertIn("No transcript", r["notice"])

    def test_a_pi_step_transcript_opens_with_its_title(self):
        r = run_actions('return A.transcriptPlan({ path: "/s/run.jsonl", title: "main · transcript" });')
        self.assertEqual(r["open"], True)
        self.assertEqual(r["path"], "/s/run.jsonl")


@unittest.skipUnless(NODE, "node is not installed: the action tests are skipped")
class AttachPlan(unittest.TestCase):
    def test_a_live_local_child_terminal_can_be_attached(self):
        r = run_actions('return A.attachPlan({ kind: "terminal", address: "t9", state: "live" });')
        self.assertEqual(r["show"], True)
        self.assertEqual(r["enabled"], True)

    def test_a_claude_agent_row_shows_attach_disabled_with_the_reason(self):
        r = run_actions('return A.attachPlan({ kind: "claude", live: true });')
        self.assertEqual(r["show"], True)
        self.assertEqual(r["enabled"], False)
        self.assertEqual(r["tip"], "No terminal: this agent runs inside its parent; open its transcript")

    def test_a_remote_terminal_shows_attach_disabled(self):
        r = run_actions('return A.attachPlan({ kind: "terminal", address: "devbox/t9", state: "live" });')
        self.assertEqual(r["show"], True)
        self.assertEqual(r["enabled"], False)
        self.assertIn("this computer", r["tip"])

    def test_an_exited_terminal_offers_no_attach(self):
        r = run_actions('return A.attachPlan({ kind: "terminal", address: "t9", state: "exited" });')
        self.assertEqual(r["show"], False)


@unittest.skipUnless(NODE, "node is not installed: the action tests are skipped")
@unittest.skipUnless(NODE, "node is not installed")
class AttachStep(unittest.TestCase):
    """attach() on a terminal that is not live yet (a child session just started) waits a few timer ticks, then
    says why it gave up, instead of returning silently."""

    def test_a_live_local_terminal_opens(self):
        self.assertEqual(run_actions('return A.attachStep("t9", { state: "live" }, 0, true);'), {"do": "open"})

    def test_a_missing_terminal_is_waited_for_a_few_ticks(self):
        self.assertEqual(run_actions('return A.attachStep("t9", undefined, 0, true);'), {"do": "retry"})
        r = run_actions('return A.attachStep("t9", undefined, A.ATTACH_TRIES, true);')
        self.assertEqual(r["do"], "fail")
        self.assertIn("t9", r["why"])
        self.assertLessEqual(run_actions("return A.ATTACH_TRIES * A.ATTACH_WAIT;"), 2000)

    def test_without_a_timer_it_fails_at_once_with_a_reason(self):
        r = run_actions('return A.attachStep("t9", { state: "exited" }, 0, false);')
        self.assertEqual(r["do"], "fail")
        self.assertIn("exited", r["why"])

    def test_a_remote_terminal_fails_with_the_reason(self):
        r = run_actions('return A.attachStep("box/t9", { state: "live" }, 0, true);')
        self.assertEqual(r["do"], "fail")
        self.assertIn("this computer only", r["why"])

    def test_main_attach_uses_the_step_and_notifies_on_failure(self):
        src = MAIN.read_text(encoding="utf-8")
        body = src[src.index("  attach(address, title, cx = null, tries = 0) {"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("attachStep(address, t, tries, Boolean(cx))", body)
        self.assertIn('this.notice("Couldn\'t attach", step.why, "error")', body)
        self.assertIn("cx.timer.after(ATTACH_WAIT", body)
        self.assertIn("this.attach(address, `${step.agent} ${r.short}`, cx)", src)


class PopupRules(unittest.TestCase):
    def test_escape_closes_a_transcript_or_log_popup(self):
        self.assertEqual(run_actions('return A.escapeOwner("transcript");'), "close")
        self.assertEqual(run_actions('return A.escapeOwner("log");'), "close")

    def test_escape_goes_to_the_terminal_in_an_attach_popup(self):
        self.assertEqual(run_actions('return A.escapeOwner("attach");'), "terminal")

    def test_move_to_main_splits_beside_a_focused_pane_else_new_tab(self):
        r = run_actions('return [A.moveTarget(true, {a: 1}), A.moveTarget(false, {a: 1})];')
        self.assertEqual(r[0]["verb"], "pane.split")
        self.assertEqual(r[0]["args"]["direction"], "right")
        self.assertEqual(r[0]["args"]["mod"], "ob-outline")
        self.assertEqual(r[1]["verb"], "tab.new")
        self.assertEqual(r[1]["args"]["mod"], "ob-outline")


class Wiring(unittest.TestCase):
    def test_transcript_lookup_uses_the_resolver(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('from "./actions.js"', src)
        self.assertIn("resolveKey(", src)
        self.assertNotIn("const [k, si] = key.split", src)

    def test_claude_rows_show_attach_disabled_with_a_tooltip(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("attachPlan(", src)
        self.assertIn("No terminal: this agent runs inside its parent; open its transcript", ACTIONS.read_text(encoding="utf-8"))

    def test_attach_popup_has_no_unsupported_placement(self):
        src = OBC.read_text(encoding="utf-8")
        self.assertNotIn('at: "top"', src)
        self.assertNotIn("offset: 48", src)

    def test_viewer_closes_on_escape_and_takes_the_keyboard(self):
        src = VIEWER.read_text(encoding="utf-8")
        self.assertIn("escapeOwner(", src)
        self.assertIn("on_key_down(", src)
        self.assertIn("track_focus(", src)


def run_terminals(body):
    """Import terminals.js in node, run `body` (JS using `listedTerminals`, `placedTerminals`), return its JSON."""
    mod = Path(ROOT, "mods", "ob-outline", "terminals.js").as_uri()
    src = f'import {{ listedTerminals, placedTerminals }} from "{mod}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


TERMS = ('const T = ['
         '{address:"t1", state:"live", parent:"p1"},'        # child, unplaced: listed
         '{address:"t2", state:"live"},'                     # background, no parent, unplaced: listed
         '{address:"t3", state:"live", parent:"p1"},'        # child, placed: not listed here
         '{address:"t4", state:"live"},'                     # no parent, placed: not listed here
         '{address:"t5", state:"exited"},'                   # not live: not listed
         '{address:"t2", state:"live"},'                     # same terminal twice: listed once
         '{address:"t6", state:"live", parent:"p2"}];')
PANES = 'const P = [{pane:"pa", terminal:"t3"}, {pane:"pb", terminal:"t4"}, {pane:"mod"}];'


@unittest.skipUnless(NODE, "node is not installed: the terminal list test is skipped")
class ListedTerminals(unittest.TestCase):
    def addresses(self):
        return [t["address"] for t in run_terminals(TERMS + PANES + "return listedTerminals(T, P);")]

    def test_unplaced_child_is_listed(self):
        self.assertIn("t1", self.addresses())

    def test_unplaced_without_parent_is_listed(self):
        self.assertIn("t2", self.addresses())

    def test_placed_terminals_are_not_listed(self):
        a = self.addresses()
        self.assertNotIn("t3", a)
        self.assertNotIn("t4", a)

    def test_not_live_is_not_listed(self):
        self.assertNotIn("t5", self.addresses())

    def test_a_terminal_is_listed_once(self):
        a = self.addresses()
        self.assertEqual(a.count("t2"), 1)

    def test_order_is_the_terminals_order(self):
        self.assertEqual(self.addresses(), ["t1", "t2", "t6"])

    def test_placed_set_follows_the_panes_rule(self):
        r = run_terminals(PANES + "return [...placedTerminals(P)].sort();")
        self.assertEqual(r, ["t3", "t4"])

    def test_main_builds_its_terminal_rows_from_the_list(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('from "./terminals.js"', src)
        self.assertIn("listedTerminals(", src)


TREE = Path(ROOT, "mods", "ob-outline", "tree.js")


def run_tree(body):
    """Import tree.js in node, run `body` (JS using `paneAgents`), return its JSON."""
    src = f'import {{ paneAgents, onMachine }} from "{TREE.as_uri()}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


DATA = ('const panes = [{pane:"pa", terminal:"t1"}, {pane:"pb", terminal:"t2"}, {pane:"mod"}];'
        'const data = { runs: [{key:"r1", parent:"t1"}, {key:"r2", parent:"t9"}], claude: [{key:"c1", parent:"t2"}],'
        ' kids: [{address:"k1", parent:"t1"}] };')


@unittest.skipUnless(NODE, "node is not installed: the outline tree test is skipped")
class PaneAgents(unittest.TestCase):
    """The Outline lists each pane of the tab with the agents that run in its terminal under it."""

    def test_each_agent_sits_under_the_pane_whose_terminal_runs_it(self):
        r = run_tree(DATA + "const g = paneAgents(panes, data).groups;"
                     "return g.map((x) => [x.pane, x.runs.map((r) => r.key), x.claude.map((c) => c.key), x.kids.map((k) => k.address)]);")
        self.assertEqual(r, [["pa", ["r1"], [], ["k1"]], ["pb", [], ["c1"], []], ["mod", [], [], []]])

    def test_panes_keep_the_tab_order_and_a_mod_pane_takes_nothing(self):
        r = run_tree(DATA + "return paneAgents(panes, data).groups.map((x) => x.pane);")
        self.assertEqual(r, ["pa", "pb", "mod"])

    def test_an_agent_outside_this_tab_is_not_dropped(self):
        # A pinned session in another tab: its agents come back apart, for the pinned section.
        r = run_tree(DATA + "return paneAgents(panes, data).outside.runs.map((r) => r.key);")
        self.assertEqual(r, ["r2"])

    def test_the_input_is_not_changed(self):
        r = run_tree(DATA + "paneAgents(panes, data); return [panes.length, data.runs.length, data.claude.length];")
        self.assertEqual(r, [3, 2, 1])


MIXED = ('const f = { f: 1, runs: [{key:"r-local", machine:null}, {key:"r-box", machine:"box"}],'
         ' claude: [{key:"c-local"}, {key:"c-box", machine:"box"}], kids: [{address:"t5"}, {address:"box/t6"}] };'
         'const keys = (d) => [d.runs.map((x) => x.key), d.claude.map((x) => x.key), d.kids.map((x) => x.address)];')


@unittest.skipUnless(NODE, "node is not installed: the machine filter test is skipped")
class MachineFilter(unittest.TestCase):
    """The machine filter applies to the tab view too (the header says both scopes), the same rule as "All"."""

    def test_no_filter_keeps_everything(self):
        self.assertEqual(run_tree(MIXED + "return keys(onMachine(f, null));"),
                         [["r-local", "r-box"], ["c-local", "c-box"], ["t5", "box/t6"]])

    def test_local_keeps_this_computer_only(self):
        self.assertEqual(run_tree(MIXED + 'return keys(onMachine(f, "local"));'), [["r-local"], ["c-local"], ["t5"]])

    def test_a_machine_keeps_only_its_own(self):
        self.assertEqual(run_tree(MIXED + 'return keys(onMachine(f, "box"));'), [["r-box"], ["c-box"], ["box/t6"]])

    def test_other_fields_are_kept(self):
        self.assertEqual(run_tree(MIXED + 'return onMachine(f, "box").f;'), 1)

    def test_tab_view_filters_its_data_by_the_machine(self):
        src = MAIN.read_text(encoding="utf-8")
        body = src[src.index("  tabView(t, rows, data0) {"):]
        body = body[:body.index("paneAgents(")]
        self.assertIn("const data = onMachine(data0, this.machine);", body)


OLD_NAME = "ob-" + "subagents"  # spelled in pieces: this file must not name the panel it checks for


class Wiring2(unittest.TestCase):
    def test_no_file_names_the_removed_panel(self):
        # The Subagents panel is gone: nothing in the repo still names it (history in git is fine).
        hits = []
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", OLD_NAME)]
            for name in files:
                if name.endswith((".d.ts", ".pyc")):
                    continue
                path = Path(dirpath, name)
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if OLD_NAME in text:
                    hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])

    def test_the_outline_renders_pane_agents_through_the_tree(self):
        src = Path(ROOT, "mods", "ob-outline", "main.js").read_text(encoding="utf-8")
        self.assertIn("paneAgents(", src)
        self.assertIn('from "./tree.js"', src)



class PaneNames(unittest.TestCase):
    """The Outline's pane rows are named by the kit's one rule (paneLabelOf), with the active tab's name passed in, so a
    pane does not repeat the tab's name. Wiring check on the source (the rows are built from live Herdr lists)."""

    def setUp(self):
        self.src = Path(ROOT, "mods", "ob-outline", "main.js").read_text(encoding="utf-8")

    def test_a_pane_row_is_named_by_the_kit_rule(self):
        self.assertIn("paneLabelOf(p, tabName)", self.src)

    def test_the_tab_name_is_passed_to_each_pane_row(self):
        self.assertIn("this.paneRow(t, p, Boolean(pinned) && pinnedAddr === addr && addr != null, tabLabel(curTab, ps))", self.src)

    def test_the_old_pane_name_is_no_longer_used_for_rows(self):
        self.assertNotIn("paneName(p) || p.title", self.src)


if __name__ == "__main__":
    unittest.main()
