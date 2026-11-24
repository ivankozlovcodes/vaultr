"""ob-outline (the former Subagents panel, folded in): a click (or Enter) on a subagent row expands it in place, a second
click collapses it. The decisions live in mods/ob-outline/rows.js, actions.js, terminals.js and tree.js (no Herdr or kit
imports), so they run here under node. Also: which agents sit under which pane, and that no file names the old panel."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
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
        # A sub-agent seen only through a live record has the key "<parent>#<id>": it is not a step key.
        r = run_actions('return A.resolveKey("term1#a1b2", { runs: [], agents: ["term1#a1b2"] });')
        self.assertEqual(r, {"key": "term1#a1b2", "step": None})

    def test_a_pi_step_key_names_run_and_step(self):
        r = run_actions('return A.resolveKey("local:run1#2", { runs: ["local:run1"], agents: [] });')
        self.assertEqual(r, {"key": "local:run1", "step": 2})

    def test_an_unknown_key_resolves_to_nothing(self):
        r = run_actions('return A.resolveKey("nope", { runs: [], agents: [] });')
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
        r = run_actions('return A.attachPlan({ kind: "agent", live: true });')
        self.assertEqual(r["show"], True)
        self.assertEqual(r["enabled"], False)
        self.assertEqual(r["tip"], "No terminal: this agent runs inside its parent; open its transcript")

    def test_a_remote_child_terminal_can_be_attached(self):
        r = run_actions('return A.attachPlan({ kind: "terminal", address: "devbox/t9", state: "live" });')
        self.assertEqual(r["show"], True)
        self.assertEqual(r["enabled"], True)
        self.assertIn("Attach:", r["tip"])

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

    def test_a_live_remote_terminal_opens(self):
        self.assertEqual(run_actions('return A.attachStep("box/t9", { state: "live" }, 0, true);'), {"do": "open"})

    def test_main_attach_uses_the_step_and_notifies_on_failure(self):
        src = MAIN.read_text(encoding="utf-8")
        body = src[src.index("  attach(address, title, cx = null, tries = 0) {"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn("attachStep(address, t, tries, Boolean(cx))", body)
        self.assertIn('this.notice("Couldn\'t attach", step.why, "error")', body)
        self.assertIn("cx.timer.after(ATTACH_WAIT", body)
        self.assertIn("machine: machineOf(address)", body)
        self.assertIn("this.attach(address, `${step.agent} ${r.short}`, cx)", src)

    def test_child_terminal_rows_and_attach_header_handle_remote_status_and_transcripts(self):
        main_src = MAIN.read_text(encoding="utf-8")
        viewer_src = VIEWER.read_text(encoding="utf-8")
        self.assertIn("cleanTitle(raw)", main_src)
        self.assertIn('startsWith("h:")', main_src)
        self.assertIn("ob-outline.transcript:h:${k.address}", main_src)
        self.assertIn("terminals().find((x) => x.address === p.terminal)", viewer_src)
        self.assertNotIn(".labels", main_src)
        self.assertNotIn(".labels", viewer_src)


class PopupRules(unittest.TestCase):
    def test_escape_closes_a_transcript_or_log_popup(self):
        self.assertEqual(run_actions('return A.escapeOwner("transcript");'), "close")
        self.assertEqual(run_actions('return A.escapeOwner("log");'), "close")

    def test_escape_goes_to_the_terminal_in_an_attach_popup(self):
        self.assertEqual(run_actions('return A.escapeOwner("attach");'), "close")
        self.assertEqual(run_actions('return A.escapeOwner("attach", false);'), "close")
        self.assertEqual(run_actions('return A.escapeOwner("attach", true);'), "terminal")

    def test_move_to_main_splits_beside_a_focused_pane_else_new_tab(self):
        r = run_actions('return [A.moveTarget(true, {a: 1}), A.moveTarget(false, {a: 1})];')
        self.assertEqual(r[0]["verb"], "pane.split")
        self.assertEqual(r[0]["args"]["direction"], "right")
        self.assertEqual(r[0]["args"]["mod"], "ob-outline")
        self.assertEqual(r[1]["verb"], "tab.new")
        self.assertEqual(r[1]["args"]["mod"], "ob-outline")


TAIL = Path(ROOT, "mods", "ob-outline", "tail.js")


def run_tail(body):
    """Import tail.js in node, run `body` (JS using the exports as T), return the JSON it prints."""
    src = (f'import * as T from "{TAIL.as_uri()}";\n'
           f'console.log(JSON.stringify((() => {{ {body} }})()));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed: the transcript scroll tests are skipped")
class TranscriptEnd(unittest.TestCase):
    """The transcript opens at its end. A plain scroll area cannot be scrolled from a mod, so the transcript is a
    virtual list whose row heights are measured after layout; a jump to the end is repeated until they are."""

    def test_a_jump_repeats_while_rows_wait_to_be_measured(self):
        self.assertEqual(run_tail("return T.endStep({ follow: true, want: true, unmeasured: 40 });"),
                         {"scroll": True, "want": True})

    def test_a_jump_lands_once_every_row_is_measured(self):
        self.assertEqual(run_tail("return T.endStep({ follow: true, want: true, unmeasured: 0 });"),
                         {"scroll": True, "want": False})

    def test_nothing_moves_when_no_jump_was_asked_for(self):
        # Expanding a tool row remeasures it, but asks for no jump: the view stays where the user put it.
        self.assertEqual(run_tail("return T.endStep({ follow: true, want: false, unmeasured: 1 });"),
                         {"scroll": False, "want": False})

    def test_scrolling_up_cancels_a_pending_jump(self):
        self.assertEqual(run_tail("return T.endStep({ follow: false, want: true, unmeasured: 5 });"),
                         {"scroll": False, "want": False})

    def test_rows_use_measured_heights_a_guess_and_a_trailing_spacer(self):
        r = run_tail("return T.rowHeights(3, (i) => (i === 1 ? 120 : undefined));")
        g = run_tail("return [T.GUESS_H, T.END_H];")
        self.assertEqual(r, [g[0], 120, g[0], g[1]])

    def test_viewer_draws_the_transcript_as_a_virtual_list_it_scrolls_to_the_bottom(self):
        src = VIEWER.read_text(encoding="utf-8")
        body = src[src.index("  transcriptBody(t"):]
        body = body[:body.index("\n  }\n")]
        self.assertIn('v_virtual_list("vtx"', body)
        self.assertIn(".track_scroll(this.tscroll)", body)
        self.assertIn("on_item_click(", body)
        self.assertIn("on_size_change(", body)
        self.assertIn("endStep(", src)
        self.assertIn("this.tscroll.scroll_to_bottom()", src)
        self.assertNotIn(", ScrollHandle", src)
        self.assertNotIn("this.scroll =", src)
        self.assertNotIn("needEnd", src)


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
        self.assertIn('key_context("ObAttach")', src)
        self.assertIn("ob_outline.attach_detach", src)
        self.assertIn("Esc detaches · click terminal to type", src)
        self.assertIn("this.handle.focus()", src)


def run_terminals(body):
    """Import terminals.js in node, run `body` (JS using `listedTerminals`, `placedTerminals`, `parentAddr`, `parentMap`), return its JSON."""
    mod = Path(ROOT, "mods", "ob-outline", "terminals.js").as_uri()
    src = f'import {{ listedTerminals, placedTerminals, parentAddr, parentMap }} from "{mod}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
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

    def test_parent_addr_normalizes_and_ignores_self_loops(self):
        r = run_terminals(
            'const T = ['
            '{address:"box/t2", state:"live", parent:"box/t1"},'
            '{address:"t2", state:"live", parent:"t1"},'
            '{address:"box/t3", state:"live", parent:"other/t1"},'
            '{address:"box/t4", state:"live", parent:"box/t4"},'
            '{address:"t5", state:"live", parent:"t5"}'
            '];'
            'return listedTerminals(T, []).map((t) => [t.address, t.parent ?? null]);'
        )
        self.assertEqual(r, [
            ["box/t2", "box/t1"],
            ["t2", "t1"],
            ["box/t3", "other/t1"],
            ["box/t4", None],
            ["t5", None],
        ])

    def test_parent_map_includes_exited_terminals(self):
        r = run_terminals(
            'const T = ['
            '{address:"box/k1", state:"exited", parent:"box/t1"},'
            '{address:"box/k2", state:"live", parent:"box/k1"},'
            '{address:"t9", state:"live", parent:"t9"}'
            '];'
            'return Object.fromEntries(parentMap(T));'
        )
        self.assertEqual(r, {"box/k1": "box/t1", "box/k2": "box/k1"})


TREE = Path(ROOT, "mods", "ob-outline", "tree.js")


def run_tree(body):
    """Import tree.js in node, run `body`, return its JSON."""
    src = f'import {{ paneAgents, onMachine, liveCount, sessionGroups, resolveRoot, keepLiveAncestors, nestItems }} from "{TREE.as_uri()}";\nconsole.log(JSON.stringify((() => {{ {body} }})()));'
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "node failed")
    return json.loads(out.stdout)


DATA = ('const panes = [{pane:"pa", terminal:"t1"}, {pane:"pb", terminal:"t2"}, {pane:"mod"}];'
        'const data = { runs: [{key:"r1", parent:"t1"}, {key:"r2", parent:"t9"}], agents: [{key:"c1", parent:"t2"}],'
        ' kids: [{address:"k1", parent:"t1"}] };')


@unittest.skipUnless(NODE, "node is not installed: the outline tree test is skipped")
class PaneAgents(unittest.TestCase):
    """The Outline lists each pane of the tab with the agents that run in its terminal under it."""

    def test_each_agent_sits_under_the_pane_whose_terminal_runs_it(self):
        r = run_tree(DATA + "const g = paneAgents(panes, data).groups;"
                     "return g.map((x) => [x.pane, x.runs.map((r) => r.key), x.agents.map((c) => c.key), x.kids.map((k) => k.address)]);")
        self.assertEqual(r, [["pa", ["r1"], [], ["k1"]], ["pb", [], ["c1"], []], ["mod", [], [], []]])

    def test_panes_keep_the_tab_order_and_a_mod_pane_takes_nothing(self):
        r = run_tree(DATA + "return paneAgents(panes, data).groups.map((x) => x.pane);")
        self.assertEqual(r, ["pa", "pb", "mod"])

    def test_an_agent_outside_this_tab_is_not_dropped(self):
        # A pinned session in another tab: its agents come back apart, for the pinned section.
        r = run_tree(DATA + "return paneAgents(panes, data).outside.runs.map((r) => r.key);")
        self.assertEqual(r, ["r2"])

    def test_the_input_is_not_changed(self):
        r = run_tree(DATA + "paneAgents(panes, data); return [panes.length, data.runs.length, data.agents.length];")
        self.assertEqual(r, [3, 2, 1])

    def test_nested_runs_claude_and_grandkids_roll_up_to_ancestor_pane(self):
        r = run_tree(
            'const panes = [{pane:"pa", terminal:"t1"}, {pane:"pb", terminal:"t2"}];'
            'const data = {'
            '  runs: [{key:"r1", parent:"k1"}, {key:"r0", parent:"k0"}],'
            '  agents: [{key:"c1", parent:"k2"}],'
            '  kids: [{address:"k1", parent:"t1"}, {address:"k2", parent:"k1"}]'
            '};'
            'const g = paneAgents(panes, data, { parents: { k0: "t1" } }).groups;'
            'return g.map((x) => [x.pane, x.runs.map((r) => r.key), x.agents.map((c) => c.key), x.kids.map((k) => k.address)]);'
        )
        self.assertEqual(r, [
            ["pa", ["r1", "r0"], ["c1"], ["k1", "k2"]],
            ["pb", [], [], []],
        ])

    def test_nest_items_builds_recursive_subtrees_and_conserves_cycles_and_orphans(self):
        r = run_tree(
            'const t1 = nestItems({'
            '  runs: [{key:"r0", parent:"t1"}, {key:"r1", parent:"k1"}, {key:"r2", parent:"k2"}],'
            '  agents: [{key:"c1", parent:"k1"}],'
            '  kids: [{address:"k2", parent:"k1"}, {address:"k1", parent:"t1"}]'
            '});'
            'const cyc = nestItems({'
            '  runs: [{key:"ra", parent:"a"}, {key:"rb", parent:"b"}],'
            '  agents: [],'
            '  kids: [{address:"a", parent:"b"}, {address:"b", parent:"a"}]'
            '});'
            'const countKids = (n) => (n.kids || []).reduce((s, k) => s + 1 + countKids(k.sub || {}), 0);'
            'const countRuns = (n) => (n.runs || []).length + (n.kids || []).reduce((s, k) => s + countRuns(k.sub || {}), 0);'
            'const orph = nestItems({'
            '  runs: [{key:"r_ex", parent:"exited_k1"}],'
            '  agents: [],'
            '  kids: [{address:"k2", parent:"exited_k1"}]'
            '});'
            'return {'
            '  topRuns: t1.runs.map((x) => x.key),'
            '  topKids: t1.kids.map((k) => k.address),'
            '  k1Runs: t1.kids[0].sub.runs.map((x) => x.key),'
            '  k1Agents: t1.kids[0].sub.agents.map((x) => x.key),'
            '  k1Kids: t1.kids[0].sub.kids.map((k) => k.address),'
            '  k2Runs: t1.kids[0].sub.kids[0].sub.runs.map((x) => x.key),'
            '  cycCounts: [countKids(cyc), countRuns(cyc)],'
            '  orphTop: [orph.runs.map((x) => x.key), orph.kids.map((k) => k.address)]'
            '};'
        )
        self.assertEqual(r, {
            "topRuns": ["r0"],
            "topKids": ["k1"],
            "k1Runs": ["r1"],
            "k1Agents": ["c1"],
            "k1Kids": ["k2"],
            "k2Runs": ["r2"],
            "cycCounts": [2, 2],
            "orphTop": [["r_ex"], ["k2"]],
        })


MIXED = ('const f = { f: 1, runs: [{key:"r-local", machine:null}, {key:"r-box", machine:"box"}],'
         ' agents: [{key:"c-local"}, {key:"c-box", machine:"box"}], kids: [{address:"t5"}, {address:"box/t6"}] };'
         'const keys = (d) => [d.runs.map((x) => x.key), d.agents.map((x) => x.key), d.kids.map((x) => x.address)];')


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


GROUPS = ('const active = (k) => k.status === "working" || k.status === "blocked";'
          'const sessions = [{address:"s1", active:false, at:5}, {address:"s2", active:true, at:1}, {address:"s3", active:false, at:9}];'
          'const data = { runs: [{key:"r1", parent:"s1", live:false, lastUpdate:2}], agents: [{key:"c1", parent:"s9", live:true, updatedAt:3}],'
          ' kids: [{address:"k1", parent:"s1", status:"done"}, {address:"k2", parent:"s3", status:"working"}, {address:"k3", status:"idle"}] };'
          'const shape = (l) => l.map(([a, x]) => [a, x.live, x.sessActive, x.runs.length + x.agents.length + x.kids.length]);')


@unittest.skipUnless(NODE, "node is not installed: the live count test is skipped")
class LiveCounts(unittest.TestCase):
    """What is "live": a run or an agent that runs, a child terminal that is working or blocked. A child terminal
    that finished its turn is listed, not counted. "All" lists every session that has a pane, also one that
    started nothing, and "Live only" keeps the sessions that work or own something that does."""

    def test_a_done_or_idle_child_terminal_is_not_counted_as_live(self):
        r = run_tree('const act = (k) => k.status === "working" || k.status === "blocked";'
                     'return liveCount({ runs: [{live:true}, {live:false}], agents: [{live:true}],'
                     ' kids: [{status:"done"}, {status:"idle"}, {status:"working"}, {status:"blocked"}] }, act);')
        self.assertEqual(r, 4)

    def test_nothing_under_a_session_is_zero(self):
        self.assertEqual(run_tree("return liveCount({}, () => true);"), 0)

    def test_all_lists_a_session_that_started_nothing(self):
        r = run_tree(GROUPS + "return shape(sessionGroups(sessions, { runs: [], agents: [], kids: [] }, { kidActive: active }));")
        self.assertEqual(r, [["s2", 0, True, 0], ["s3", 0, False, 0], ["s1", 0, False, 0]])

    def test_all_groups_items_by_session_active_first_unattached_last(self):
        r = run_tree(GROUPS + "return shape(sessionGroups(sessions, data, { kidActive: active }));")
        # s3 and s9 own something live, s2 works itself; s1 owns a finished run and a done child (not live).
        self.assertEqual(r, [["s3", 1, False, 1], ["s9", 1, False, 1], ["s2", 0, True, 0], ["s1", 0, False, 2], [None, 0, False, 1]])

    def test_a_parent_without_a_pane_is_asked_whether_it_works(self):
        r = run_tree(GROUPS + 'return shape(sessionGroups([], { runs: [], agents: [], kids: [{address:"k1", parent:"bg", status:"done"}] },'
                              ' { kidActive: active, sessionActive: (a) => a === "bg" }));')
        self.assertEqual(r, [["bg", 0, True, 1]])

    def test_live_only_drops_idle_sessions_but_keeps_one_that_owns_something_live(self):
        r = run_tree(GROUPS + "const live = { runs: [], agents: data.agents, kids: data.kids.filter(active) };"
                              "return shape(sessionGroups(sessions, live, { kidActive: active, liveOnly: true }));")
        self.assertEqual(r, [["s3", 1, False, 1], ["s9", 1, False, 1], ["s2", 0, True, 0]])

    def test_session_groups_rolls_nested_children_and_subagents_into_placed_root(self):
        r = run_tree(
            'const active = (k) => k.status === "working" || k.status === "blocked";'
            'const sessions = [{address:"s1", active:false, at:5}];'
            'const data = {'
            '  runs: [],'
            '  agents: [{key:"c1", parent:"k1", live:true, updatedAt:10}],'
            '  kids: [{address:"k1", parent:"s1", status:"done"}, {address:"k2", parent:"k1", status:"working"}]'
            '};'
            'return sessionGroups(sessions, data, { kidActive: active }).map(([a, x]) => ['
            '  a, x.live, x.kids.map((k) => k.address), x.agents.map((c) => c.key)'
            ']);'
        )
        self.assertEqual(r, [["s1", 2, ["k1", "k2"], ["c1"]]])

    def test_session_groups_resolves_exited_intermediate_child_via_opts_parents(self):
        r = run_tree(
            'const active = (k) => k.status === "working" || k.status === "blocked";'
            'const sessions = [{address:"s1", active:false, at:5}];'
            'const data = { runs: [{key:"r1", parent:"k1", live:true, lastUpdate:12}], agents: [], kids: [] };'
            'return sessionGroups(sessions, data, { kidActive: active, liveOnly: true, parents: { k1: "s1" } })'
            '  .map(([a, x]) => [a, x.live, x.runs.map((u) => u.key)]);'
        )
        self.assertEqual(r, [["s1", 1, ["r1"]]])

    def test_session_groups_keeps_standalone_unplaced_root_with_grandkids(self):
        r = run_tree(
            'const active = (k) => k.status === "working" || k.status === "blocked";'
            'const data = { runs: [], agents: [], kids: [{address:"k1", parent:"bg", status:"done"}, {address:"k2", parent:"k1", status:"working"}] };'
            'return sessionGroups([], data, { kidActive: active, sessionActive: (a) => a === "bg" })'
            '  .map(([a, x]) => [a, x.live, x.sessActive, x.kids.map((k) => k.address)]);'
        )
        self.assertEqual(r, [["bg", 1, True, ["k1", "k2"]]])

    def test_keep_live_ancestors_preserves_idle_parent_of_live_descendant(self):
        r = run_tree(
            'const active = (k) => k.status === "working" || k.status === "blocked";'
            'const allKids = ['
            '  {address:"k1", parent:"s1", status:"idle"},'
            '  {address:"k2", parent:"k1", status:"done"},'
            '  {address:"k3", parent:"k2", status:"working"},'
            '  {address:"k4", parent:"s1", status:"idle"},'
            '  {address:"k5", parent:"s1", status:"idle"}'
            '];'
            'const kept = keepLiveAncestors(allKids, { runs: [{key:"r1", parent:"k5", live:true}], agents: [] }, active);'
            'return kept.map((k) => k.address);'
        )
        self.assertEqual(r, ["k1", "k2", "k3", "k5"])

    def test_main_counts_and_groups_through_the_tree(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("keepLiveAncestors(", src)
        self.assertEqual(src.count("liveCount("), 1)   # the tab view
        self.assertIn("sessionGroups(placed, { runs, agents, kids }, { kidActive: (k) => this.kidActive(k), sessionActive: isOn, liveOnly: this.liveOnly, parents: data.parents })", src)
        self.assertNotIn("kids.length;\n      rows.push([`m:${mk}`", src)   # the machine badge no longer counts every child as live


@unittest.skipUnless(NODE, "node is not installed: the detach test is skipped")
class Detach(unittest.TestCase):
    """Detach leaves the terminal running. In the attach popup it closes the popup (so does a click outside: the
    dialog is not modal); for a terminal that has a pane it is Herdr's terminal.park."""

    def test_the_menu_item_parks_the_terminal(self):
        r = run_actions('return A.detachItem("box/t9");')
        self.assertEqual(r, {"label": "Detach to background", "icon": "win-min", "command": "terminal.park", "args": {"terminal": "box/t9"}})

    def test_a_pane_without_a_terminal_has_no_detach(self):
        self.assertIsNone(run_actions("return A.detachItem(null);"))

    def test_the_detach_icon_is_shipped(self):
        self.assertTrue(Path(ROOT, "kit", "icons", run_actions("return A.DETACH_ICON;") + ".svg").is_file())

    def test_the_attach_dialog_is_not_modal_in_any_copy(self):
        opener = "export function openAttach(p) {"
        copies = [p for p in sorted(Path(ROOT, "mods").glob("*/obc.js")) if opener in p.read_text(encoding="utf-8")]
        self.assertIn(OBC, copies)
        for path in copies:
            src = path.read_text(encoding="utf-8")
            body = src[src.index(opener):]
            body = body[:body.index("\n}\n")]
            self.assertIn('kind: "dialog"', body)
            self.assertNotIn("modal", body, path.parent.name)

    def test_the_attach_header_says_detach_and_only_closes_the_popup(self):
        src = VIEWER.read_text(encoding="utf-8")
        head = src[src.index("  attachHeader(t) {"):src.index("  // ---------------------------------------------------------------- render")]
        self.assertIn(".child(this.detachButton(t))", head)
        self.assertNotIn('icon: "x"', head)                    # no bare x beside a live terminal
        self.assertIn('id("v-detach")', head)
        self.assertIn('.child("Detach")', head)
        self.assertIn(".tooltip(DETACH_POPUP_TIP)", head)
        self.assertIn("this.close();", head)
        self.assertNotIn("terminal.kill", src)
        self.assertEqual(run_actions("return A.DETACH_POPUP_TIP;"), "Detach: close popup and leave terminal running in background")

    def test_a_pane_row_of_the_outline_offers_detach(self):
        src = MAIN.read_text(encoding="utf-8")
        row = src[src.index("  paneRow(t, p, pinnedHere, tabName) {"):src.index("  focusPane(paneId) {")]
        self.assertIn("detachItem(p.terminal),", row)


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
        self.assertIn('this.paneRow(t, p, Boolean(pinned) && pinnedAddr === addr && addr != null, curTab.named ? tabLabel(curTab, ps) : "")', self.src)

    def test_the_old_pane_name_is_no_longer_used_for_rows(self):
        self.assertNotIn("paneName(p) || p.title", self.src)

    def test_pane_row_uses_kit_tilde_without_process_env_home(self):
        self.assertIn("tilde(p.cwd)", self.src)
        self.assertRegex(self.src, r'import\s*\{[^}]*\btilde\b[^}]*\}\s*from\s*"\./kit\.js"')
        self.assertNotIn("shortenPath", self.src)
        self.assertNotIn("process.env", self.src)
        self.assertNotIn("process?.env", self.src)


class TabViewScope(unittest.TestCase):
    """Outline 'This tab' scope stays strictly within the active tab's panes."""

    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_active_space_and_tab_fall_back_to_active_before_first(self):
        self.assertIn("sp.find((x) => x.id === f?.space) ?? sp.find((x) => x.active) ?? sp[0] ?? null", self.src)
        self.assertIn("curSpace?.tabs?.find((x) => x.id === f?.tab) ?? curSpace?.tabs?.find((x) => x.active) ?? curSpace?.tabs?.[0] ?? null", self.src)

    def test_tab_view_never_calls_pinned_view_or_renders_outside_sessions(self):
        body = self.src[self.src.index("  tabView(t, rows, data0) {"):self.src.index("  paneRow(t, p, pinnedHere, tabName) {")]
        self.assertNotIn("pinnedView", body)
        self.assertNotIn("outside", body)
        self.assertNotIn("this.pinnedView", self.src)
        self.assertIn("pinnedInTab", body)
        self.assertIn("const shownPanes = pinnedInTab ? tabPanes.filter((p) => p.terminal === pinnedAddr) : tabPanes;", body)

    def test_intent_routes_term_outside_tab_to_all_scope(self):
        body = self.src[self.src.index("  intent(intent) {"):self.src.index("  reveal(key) {")]
        self.assertIn('intent.startsWith("term:")', body)
        self.assertIn('this.scope = "all"', body)
        self.assertIn('this.scope = "tab"', body)


def run_outline_obc(body, state):
    """Import ob-outline/obc.js in node with stubbed herdr and kit.js (using real kit/hidden.js and kit/provider.js)."""
    folder = tempfile.mkdtemp(prefix="ob-outline-obc-")
    try:
        src = OBC.read_text(encoding="utf-8").replace('from "herdr"', 'from "./herdr.js"')
        Path(folder, "obc.js").write_text(src, encoding="utf-8")
        for kname in ("hidden.js", "provider.js", "fuzzy.js"):
            shutil.copy(Path(ROOT, "kit", kname), Path(folder, kname))
        herdr_js = (
            f"const S = {json.dumps(state)};\n"
            "export const calls = [];\n"
            "export const sharedState = { ...(S.shared || {}) };\n"
            "export const terminals = () => S.terminals || [];\n"
            "export const agents = () => S.agents || [];\n"
            "export const panes = () => S.panes || [];\n"
            "export const spaces = () => S.spaces || [];\n"
            "export const run = (verb, args) => { calls.push([verb, args]); };\n"
            "export const openOverlay = (o) => { calls.push(['openOverlay', o]); };\n"
            "export const shared = (k) => sharedState[k];\n"
            "export const setShared = (k, v) => { sharedState[k] = v; };\n"
            "export const focused = () => S.focused || null;\n"
            "export const notify = () => {};\n"
        )
        Path(folder, "herdr.js").write_text(herdr_js, encoding="utf-8")
        kit_js = (
            'import { shared, setShared } from "./herdr.js";\n'
            'import { makeProvider } from "./provider.js";\n'
            'export const MOD = "ob-outline";\n'
            'export { mKeyOf, normHidden, isMachineHidden, isSpaceHidden, isTabHidden, patchHidden } from "./hidden.js";\n'
            'export const machineOf = (a) => (String(a ?? "").includes("/") ? String(a).split("/")[0] : null);\n'
            'export const localId = (a) => String(a ?? "").split("/").pop();\n'
            'export const addrOn = (m, id) => (m ? `${m}/${id}` : id);\n'
            'export function parentAddrOf(t) {\n'
            '  return t?.parent && t.parent !== t.address ? t.parent : null;\n'
            '}\n'
            'export function isChildTerminalOf(t, parentAddr) {\n'
            '  if (!t || t.state !== "live" || !parentAddr || t.address === parentAddr) return false;\n'
            '  return parentAddrOf(t) === parentAddr;\n'
            '}\n'
            'export const getHidden = () => shared("ob.hidden") ?? { machines: [], spaces: [], tabs: [] };\n'
            'export const updateHidden = (mut) => { const next = typeof mut === "function" ? mut(getHidden()) : mut; setShared("ob.hidden", next); return next; };\n'
            'export const tabLabel = (tab) => tab?.name ?? "";\n'
            'export const paneName = () => "";\n'
            'export const dur = () => "";\n'
            'export const ago = () => "";\n'
            'export const fmtTokens = () => "";\n'
            'export const fmtCost = () => "";\n'
            'export const normStatus = (s) => s ?? null;\n'
            'export const copyText = () => {};\n'
            f'export const feed = () => ({json.dumps(state.get("feed"))});\n'
            f'export const liveRecords = () => new Map(Object.entries({json.dumps(state.get("records") or {})}));\n'
            'export const provider = makeProvider({ feed, exec: async () => ({ code: 1 }), readTextFile: async () => null, appHome: () => "/tmp" });\n'
            'export const base = (p) => String(p ?? "").split("/").pop();\n'
            'export const followTarget = () => ({ terminal: null, last: null });\n'
            'export const termStatus = (t, fb = null) => fb ?? (typeof t?.status === "string" ? t.status : t?.status?.state) ?? null;\n'
            'export const matchRecordId = (a, b) => Boolean(a && b) && a === b;\n'
        )
        Path(folder, "kit.js").write_text(kit_js, encoding="utf-8")
        code = (
            f'import * as O from "{Path(folder, "obc.js").as_uri()}";\n'
            f'import {{ calls, sharedState }} from "{Path(folder, "herdr.js").as_uri()}";\n'
            f'console.log(JSON.stringify((() => {{ {body} }})()));'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed: ancestor navigation tests are skipped")
class AncestorNav(unittest.TestCase):
    """Ancestor resolution, unhiding, and main-tab navigation across obc.js, main.js, and viewer.js."""

    STATE = {
        "spaces": [
            {"id": "box/sp1", "name": "alpha", "machine": "box", "tabs": [
                {"id": "box/tb1", "name": "main", "named": True, "settled": True},
            ]},
        ],
        "panes": [
            {"pane": "box/p1", "tab": "box/tb1", "terminal": "box/t1"},
        ],
        "terminals": [
            {"address": "box/t1", "state": "live", "status": "idle"},
            {"address": "box/t2", "state": "exited", "parent": "box/t1"},
            {"address": "box/t3", "state": "live", "parent": "box/t2", "status": "working"},
            {"address": "box/bg1", "state": "live", "status": "working"},
        ],
        "agents": [
            {"address": "box/t3", "tab": None, "status": "working"},
            {"address": "box/bg1", "tab": None, "status": "working"},
        ],
        "shared": {
            "ob.hidden": {"machines": ["box"], "spaces": ["box/sp1"], "tabs": ["box/tb1"]},
        },
    }

    def test_placed_session_of_walks_parent_chain_through_exited_child(self):
        r = run_outline_obc('const s = O.placedSessionOf("box/t3"); return s ? { address: s.address, label: s.label, pane: s.pane?.pane } : null;', self.STATE)
        self.assertEqual(r, {"address": "box/t1", "label": "alpha / main", "pane": "box/p1"})

    def test_reveal_terminal_focuses_ancestor_pane_and_unhides_hidden_tab(self):
        r = run_outline_obc('const ok = O.revealTerminal("box/t3"); return { ok, calls, hidden: sharedState["ob.hidden"] };', self.STATE)
        self.assertTrue(r["ok"])
        self.assertEqual(r["hidden"], {"machines": [], "spaces": [], "tabs": []})
        self.assertEqual(r["calls"], [
            ["tab.unsettle", {"id": "box/tb1"}],
            ["space.select", {"id": "box/sp1"}],
            ["tab.select", {"id": "box/tb1"}],
            ["pane.focus", {"pane": "box/p1"}],
        ])

    def test_reveal_terminal_peeks_standalone_headless_terminal_without_noop_agent_focus(self):
        r = run_outline_obc('const ok = O.revealTerminal("box/bg1"); return { ok, calls };', self.STATE)
        self.assertTrue(r["ok"])
        self.assertEqual(r["calls"], [["terminal.peek", {"terminal": "box/bg1"}]])

    def test_main_routes_session_navigation_through_reveal_session_and_nests_subtrees(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('case "reveal-session": revealTerminal(arg); break;', src)
        self.assertNotIn('command: "agent.focus"', src)
        self.assertGreaterEqual(src.count("ob-outline.reveal-session:"), 4)
        self.assertIn("nestItems(", src)
        self.assertIn("keepLiveAncestors(", src)
        self.assertIn("placedSessionOf(", src)
        self.assertIn("parentMap(", src)
        self.assertIn("hc-${k.address}-go", src)
        self.assertIn("Go to main tab", src)

    def test_viewer_attach_header_offers_main_tab_jump(self):
        src = VIEWER.read_text(encoding="utf-8")
        self.assertIn("placedSessionOf", src)
        self.assertIn("revealTerminal", src)
        self.assertIn('id("v-main-tab")', src)
        self.assertIn('.child("Main tab")', src)

    def test_all_three_obc_copies_stay_identical_and_export_placed_session_of(self):
        outline = Path(ROOT, "mods", "ob-outline", "obc.js").read_text(encoding="utf-8")
        graph = Path(ROOT, "mods", "ob-graph", "obc.js").read_text(encoding="utf-8")
        props = Path(ROOT, "mods", "ob-props", "obc.js").read_text(encoding="utf-8")
        self.assertIn("export function placedSessionOf(", outline)
        self.assertEqual(outline, graph)
        self.assertEqual(outline, props)


@unittest.skipUnless(NODE, "node is not installed: record card tests are skipped")
class RecordCards(unittest.TestCase):
    """allSubagents() maps live record msgs and agentCard/menu clean up non-provider record cards."""

    def test_claude_all_maps_live_record_msg_to_last_tool_and_preserves_feed_tool(self):
        state = {
            "feed": {
                "v": 2,
                "providers": {
                    "claude": {"id": "claude", "name": "Claude Code", "noun": "Claude agent", "caps": ["title", "subagents"]},
                },
                "subagents": [
                    {"key": "local:a1", "machine": None, "parent": "t1", "provider": "claude", "id": "a1", "type": "Explore", "desc": "scan", "live": True,
                     "lastTool": {"tool": "Read", "args": "README.md"}},
                    {"key": "local:a2", "machine": None, "parent": "t1", "provider": "claude", "id": "a2", "type": "Plan", "desc": "plan", "live": True,
                     "lastTool": None},
                ],
            },
            "records": {
                "t1": {
                    "a1": {"app": "claude", "state": "working", "msg": "Bash"},
                    "a2": {"app": "claude", "state": "working", "msg": "Grep"},
                    "sub/9f8e7d6c-5b4a": {"app": "custom-agent", "state": "working", "title": "sub", "msg": "exec_cmd"},
                    "sub/00112233-4455": {"app": "custom-agent", "state": "working", "title": "sub", "msg": "   "},
                },
            },
        }
        r = run_outline_obc(
            "return Object.fromEntries(O.allSubagents().agents.map((c) => [c.id, c.lastTool]));",
            state,
        )
        self.assertEqual(r, {
            "a1": {"tool": "Read", "args": "README.md"},
            "a2": {"tool": "Grep", "args": ""},
            "sub/9f8e7d6c-5b4a": {"tool": "exec_cmd", "args": ""},
            "sub/00112233-4455": None,
        })

    def test_claude_card_omits_dead_attach_strips_prefix_for_8char_id_and_guards_transcript(self):
        src = MAIN.read_text(encoding="utf-8")
        card = src[src.index("  agentCard(t, c, depth) {"):src.index("  childMenu(k, name, plan, tx) {")]
        self.assertNotIn("${id}-attach", card)
        self.assertIn('String(c.id ?? "").split("/").pop().slice(0, 8)', card)
        self.assertNotIn("c.id.slice(0, 10)", card)
        self.assertIn('can("transcript")', card)
        menu = src[src.index("  menu(key, cx) {"):src.index("  async command(c, cx) {")]
        self.assertIn('can("transcript")', menu)


def run_outline_panel(body, state):
    """Run ob-outline/main.js in node with stubbed gpui/herdr/kit to inspect rendered Panel rows."""
    folder = tempfile.mkdtemp(prefix="ob-outline-main-")
    try:
        src = MAIN.read_text(encoding="utf-8")
        src = src.replace('from "gpui-kit"', 'from "./gpui-kit.js"')
        src = src.replace('from "gpui-base"', 'from "./gpui-base.js"')
        src = src.replace('from "herdr"', 'from "./herdr.js"')
        Path(folder, "main.js").write_text(src, encoding="utf-8")
        for name in ("rows.js", "terminals.js", "tree.js", "actions.js", "provider.js", "fuzzy.js"):
            shutil.copy(Path(ROOT, "mods", "ob-outline", name), Path(folder, name))
        Path(folder, "viewer.js").write_text("export class Viewer { init() {} render() { return null; } command() {} }\n", encoding="utf-8")
        Path(folder, "gpui-kit.js").write_text(
            "const el = (tag) => {\n"
            "  const n = { tag, children: [], props: {} };\n"
            "  return new Proxy((...a) => n, {\n"
            "    get: (_t, k) => {\n"
            "      if (k === '_node') return n;\n"
            "      if (k === 'child') return (c) => { if (c != null) n.children.push(c?._node ?? c); return elProxy(n); };\n"
            "      if (k === 'children') return (cs) => { for (const c of cs || []) if (c != null) n.children.push(c?._node ?? c); return elProxy(n); };\n"
            "      return (...args) => { n.props[k] = args.length === 1 ? args[0] : args; return elProxy(n); };\n"
            "    },\n"
            "  });\n"
            "};\n"
            "const elProxy = (n) => new Proxy(() => n, {\n"
            "  get: (_t, k) => {\n"
            "    if (k === '_node') return n;\n"
            "    if (k === 'child') return (c) => { if (c != null) n.children.push(c?._node ?? c); return elProxy(n); };\n"
            "    if (k === 'children') return (cs) => { for (const c of cs || []) if (c != null) n.children.push(c?._node ?? c); return elProxy(n); };\n"
            "    return (...args) => { n.props[k] = args.length === 1 ? args[0] : args; return elProxy(n); };\n"
            "  },\n"
            "});\n"
            "export class View {}\n"
            "export const div = () => el('div');\n",
            encoding="utf-8",
        )
        Path(folder, "gpui-base.js").write_text(
            "import { div } from './gpui-kit.js';\n"
            "export const v_flex = () => div();\n"
            "export const h_flex = () => div();\n"
            "export const ScrollHandle = { new: () => ({ scroll_to_item() {} }) };\n"
            "export const Scrollbar = { vertical: () => div() };\n",
            encoding="utf-8",
        )
        Path(folder, "herdr.js").write_text(
            "export const props = () => ({});\n"
            "export const run = () => {};\n"
            "export const nextCommand = () => new Promise(() => {});\n"
            "export const settings = () => ({ zoom: 1 });\n"
            "export const exec = async () => ({ code: 0, stdout: '' });\n"
            "export const hc = async () => ({});\n"
            "export const machines = () => [];\n"
            "export const spaces = () => [];\n"
            "export const panes = () => [];\n"
            "export const layout = () => ({});\n"
            "export const focused = () => null;\n"
            "export const terminals = () => [];\n"
            "export const notify = () => {};\n"
            "export const readTextFile = async () => null;\n"
            "export const appHome = () => '/tmp';\n",
            encoding="utf-8",
        )
        Path(folder, "kit.js").write_text(
            f"const S_DATA = {json.dumps(state)};\n"
            'import { makeProvider } from "./provider.js";\n'
            'import { exec, readTextFile, appHome } from "./herdr.js";\n'
            "export const S = { rowSm: 24, iconXs: 12, iconSm: 14, textXs: 11, pad: 8, toolbar: 30, radius: 4, radiusLg: 6 };\n"
            "export const tc = () => ({ muted: '#888', dim: '#666', blocked: '#f00', chrome: '#111', foreground: '#eee', border: '#333', accent: '#0af', raised: '#222', selected: '#333', hover: '#2a2a2a' });\n"
            "export const alpha = (c) => c;\n"
            "export const icon = (name) => ({ kind: 'icon', name });\n"
            "export const iconButton = (opts) => ({ kind: 'iconButton', id: opts.id, tip: opts.tip });\n"
            "export const badge = (label, tone) => ({ kind: 'badge', label, tone });\n"
            "export const statusMark = (s) => ({ kind: 'statusMark', s });\n"
            "export const normStatus = (s) => s === 'error' ? 'blocked' : s === 'done' ? 'idle' : (s ?? null);\n"
            "export const sectionHeader = (o) => ({ kind: 'sectionHeader', ...o });\n"
            "export const treeRow = (o) => ({ kind: 'treeRow', id: o.id, depth: o.depth, label: o.label, dim: o.dim, after: (o.after || []).filter(Boolean).map((x) => x?._node ?? x), right: (o.right || []).filter(Boolean).map((x) => x?._node ?? x) });\n"
            "export const emptyState = (o) => ({ kind: 'emptyState', ...o });\n"
            "export const openMenu = () => {};\n"
            "export const programIcon = () => ({ kind: 'programIcon' });\n"
            'export const feed = () => (S_DATA.feed?.v === 2 ? S_DATA.feed : null);\n'
            f"export const liveRecords = () => new Map(Object.entries({json.dumps(state.get('records') or {})}));\n"
            "export const provider = makeProvider({ feed, exec, readTextFile, appHome });\n"
            "export const machineLabel = (m) => m ?? 'local';\n"
            "export const machineOf = (a) => (String(a ?? '').includes('/') ? String(a).split('/')[0] : null);\n"
            "export const ago = () => '';\n"
            "export const dur = () => '';\n"
            "export const fmtTokens = () => '';\n"
            "export const fmtCost = () => '';\n"
            "export const takeFocus = () => {};\n"
            "export const isBookmarked = () => false;\n"
            "export const toggleBookmark = () => {};\n"
            "export const isShown = () => true;\n"
            "export const base = (p) => String(p ?? '').split('/').pop();\n"
            "export const stop = () => {};\n"
            "export const kbd = () => null;\n"
            "export const feedLine = () => null;\n"
            "export const paneLabelOf = (p) => p?.title ?? '';\n"
            "export const tabLabel = (t) => t?.name ?? '';\n"
            "export const cleanTitle = (s) => String(s ?? '').trim();\n"
            "export const sessionTitleOf = (a) => S_DATA.sessionTitles?.[a] ?? null;\n"
            "export const tilde = (p) => String(p ?? '');\n",
            encoding="utf-8",
        )
        Path(folder, "obc.js").write_text(
            f"const S_DATA = {json.dumps(state)};\n"
            "export const MONO = 'monospace';\n"
            "export const splitCmd = (c) => [c, ''];\n"
            "export const sessionOf = (a) => S_DATA.sessions?.[a] ?? null;\n"
            "export const placedSessionOf = (a) => S_DATA.placed?.[a] ?? null;\n"
            "export const inspected = () => ({ address: null, pinned: false });\n"
            "export const inspect = () => {};\n"
            "export const revealTerminal = () => {};\n"
            "export const runTitle = () => '';\n"
            "export const runModels = () => [];\n"
            "export const shortModel = (m) => m;\n"
            "export const runWhen = () => '';\n"
            "export const currentStep = () => null;\n"
            "export const lastTool = () => null;\n"
            "export const runMeta = () => '';\n"
            "export const stepTranscript = () => null;\n"
            "export const allSubagents = () => ({ runs: [], agents: [] });\n"
            "export const openViewer = () => {};\n"
            "export const openAttach = () => {};\n"
            "export const copied = () => false;\n"
            "export const lines = () => [];\n",
            encoding="utf-8",
        )
        code = (
            "globalThis.localStorage = { getItem: () => null, setItem: () => {} };\n"
            f'import Outline from "{Path(folder, "main.js").as_uri()}";\n'
            f'import {{ tc }} from "{Path(folder, "kit.js").as_uri()}";\n'
            "const o = new Outline();\n"
            "o.init(null, { focus_handle: () => ({}), timer: { every: () => {} }, spawn: () => {} });\n"
            "const panel = o.view;\n"
            "panel.w = 320;\n"
            f"console.log(JSON.stringify((() => {{ {body} }})()));"
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed: childRow tests are skipped")
class ChildRowToolAndGoButton(unittest.TestCase):
    """Working child rows show their latest feed tool, and All view hides a redundant Go button under the child's own main session."""

    def test_working_child_shows_latest_feed_tool_while_idle_child_shows_slug_or_address(self):
        state = {
            "feed": {
                "v": 2,
                "terms": {
                    "t_work": {"provider": "claude", "lastTool": {"tool": "Read", "args": "kit/kit.js"}},
                    "t_idle": {"provider": "claude", "lastTool": {"tool": "Bash", "args": "ls"}},
                },
            },
        }
        r = run_outline_panel(
            """
            const rWork = panel.childRow(tc(), { address: "t_work", name: "worker-a", title: "Build PR", status: "working", state: "live" }, 1);
            const rIdle = panel.childRow(tc(), { address: "t_idle", name: "worker-b", title: "Done PR", status: "idle", state: "live" }, 1);
            return { workAfter: rWork.after, idleAfter: rIdle.after };
            """,
            state,
        )
        self.assertEqual(len(r["workAfter"]), 1)
        self.assertEqual(r["workAfter"][0]["children"], ["· Read kit/kit.js"])
        self.assertEqual(r["workAfter"][0]["props"]["text_color"], "#888")
        self.assertEqual(r["workAfter"][0]["props"]["flex_shrink"], 2)
        self.assertEqual(len(r["idleAfter"]), 1)
        self.assertEqual(r["idleAfter"][0]["children"], ["t_idle"])

    def test_go_to_main_tab_button_hidden_when_child_is_already_nested_under_its_main_session(self):
        state = {
            "placed": {
                "t_kid": {"address": "t_root", "label": "vaultr / main"},
                "t_grand": {"address": "t_root", "label": "vaultr / main"},
            },
        }
        r = run_outline_panel(
            """
            panel.scope = "all";
            const kids = [
              { address: "t_kid", parent: "t_root", status: "working", state: "live" },
              { address: "t_grand", parent: "t_kid", status: "working", state: "live" },
            ];
            const underOwnRoot = [];
            panel.items(tc(), underOwnRoot, [], [], kids, 0, "t_root");
            const unattached = [];
            panel.items(tc(), unattached, [], [], kids, 0, null);
            return {
              underOwnRightIds: underOwnRoot.map(([, row]) => row.right.map((b) => b.id ?? b.props?.id)),
              unattachedRightIds: unattached.map(([, row]) => row.right.map((b) => b.id ?? b.props?.id)),
            };
            """,
            state,
        )
        for right_ids in r["underOwnRightIds"]:
            self.assertFalse(any((i or "").endswith("-go") for i in right_ids), right_ids)
        self.assertIn("hc-t_kid-go", r["unattachedRightIds"][0])
        self.assertIn("hc-t_grand-go", r["unattachedRightIds"][1])
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("this.items(t, rows, x.runs, x.agents, x.kids, 0, p);", src)


if __name__ == "__main__":
    unittest.main()
