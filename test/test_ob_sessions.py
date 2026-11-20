"""mods/ob-sessions (the Sessions tree) names panes for what they run, through the kit's one rule (paneLabelOf). A tab
keeps its own name. A tab that holds exactly one pane and shows as that pane's row shows the pane's label under its
name when the two differ. The tree is built from live Herdr lists, so these are wiring checks on the source."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MAIN = Path(ROOT, "mods", "ob-sessions", "main.js")


class PaneNames(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def test_a_pane_row_is_named_by_the_kit_rule_with_its_tab_name_passed_in(self):
        self.assertIn('paneLabelOf(p, tab ? tabLabel(tab, ps) : "")', self.src)

    def test_the_old_pane_name_is_no_longer_used_for_rows(self):
        self.assertNotIn("paneName(p)", self.src)

    def test_a_tab_row_still_shows_the_tab_name(self):
        self.assertRegex(self.src, r'kind: "tab", label, text: label')

    def test_a_single_pane_tab_row_gets_the_pane_label_as_secondary_text_when_it_differs(self):
        self.assertIn("paneSecondary(label, paneLabelOf(mine[0], label))", self.src)

    def test_the_secondary_text_is_drawn_in_the_tab_row(self):
        self.assertRegex(self.src, r"n\.secondary[\s\S]{0,200}text_color\(t\.dim\)")


class MacKeys(unittest.TestCase):
    def test_cmd_enter_opens_to_the_right_like_ctrl_enter(self):
        # On macOS install.sh binds cmd-enter where keys/ says ctrl-enter; the tree's own key handler takes both.
        src = MAIN.read_text(encoding="utf-8")
        self.assertRegex(src, r'case "ctrl-enter": case "cmd-enter": if \(this\.once\("open-right"\)\)')

    def test_cmd_backspace_closes_selected_row_like_delete(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertRegex(src, r'case "delete": case "cmd-backspace": if \(this\.once\("close"\)\)')


MATCH = Path(ROOT, "mods", "ob-sessions", "match.js")
NODE = shutil.which("node")


def match_q(q, text):
    src = (f'import {{ matchQ }} from "{MATCH.as_uri()}";\n'
           f'console.log(JSON.stringify(matchQ({json.dumps(q)}, {json.dumps(text)})));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class Filter(unittest.TestCase):
    """The tree's filter: the kit's fuzzy() (every space-separated term, anywhere, in any order), but a term's own
    letters may not spread over the whole label. The spread is checked per term, not from the first term's hit to
    the last one's."""

    def test_two_terms_far_apart_match(self):
        self.assertIsNotNone(match_q("vault test", "vaultr · ~/src/projects/foo/test"))
        self.assertIsNotNone(match_q("test vault", "vaultr · ~/src/projects/foo/test"))

    def test_a_single_term_still_may_not_spread(self):
        # fuzzy() lets a short term's letters spread inside one long word; the filter does not.
        self.assertIsNone(match_q("vrst", "v" + "a" * 20 + "rst"))
        self.assertIsNotNone(match_q("vrst", "vxrst"))
        self.assertIsNone(match_q("vault vrst", "vault " + "v" + "a" * 20 + "rst"))

    def test_a_missing_term_fails(self):
        self.assertIsNone(match_q("vault zebra", "vaultr · ~/src/projects/foo/test"))

    def test_empty_query_matches_with_no_hits(self):
        self.assertEqual(match_q("", "anything"), {"score": 0, "hits": []})

    def test_main_uses_the_module(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('import { matchQ } from "./match.js";', src)
        self.assertNotIn("function matchQ(", src)


HIDDEN_JS = Path(ROOT, "kit", "hidden.js")


def hidden_eval(expr, payload=None):
    src = (f'import * as H from "{HIDDEN_JS.as_uri()}";\n'
           f'const d = {json.dumps(payload)};\n'
           f'console.log(JSON.stringify({expr}));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class HiddenRules(unittest.TestCase):
    """Pure hidden rules in kit/hidden.js: machine keys, normalization, inheritance, and patch."""

    def test_m_key_of_normalizes_local_and_remotes(self):
        got = hidden_eval("[H.mKeyOf(null), H.mKeyOf(undefined), H.mKeyOf(''), H.mKeyOf('devbox')]")
        self.assertEqual(got, ["local", "local", "local", "devbox"])

    def test_norm_hidden_creates_sets(self):
        raw = {"machines": ["local"], "spaces": ["s1"], "tabs": ["t1"]}
        got = hidden_eval("(() => { const h = H.normHidden(d); return { m: [...h.machines], s: [...h.spaces], t: [...h.tabs] }; })()", raw)
        self.assertEqual(got, {"m": ["local"], "s": ["s1"], "t": ["t1"]})

    def test_is_machine_hidden_for_local_and_remote(self):
        raw = {"machines": ["local", "box1"], "spaces": [], "tabs": []}
        got = hidden_eval("(() => { const h = H.normHidden(d); return [H.isMachineHidden(h, null), H.isMachineHidden(h, ''), H.isMachineHidden(h, 'box1'), H.isMachineHidden(h, 'box2')]; })()", raw)
        self.assertEqual(got, [True, True, True, False])

    def test_is_space_hidden_inherits_from_machine(self):
        raw = {"machines": ["local"], "spaces": ["s-remote"], "tabs": []}
        got = hidden_eval("""(() => {
            const h = H.normHidden(d);
            return [
                H.isSpaceHidden(h, { id: 's-local', machine: null }),
                H.isSpaceHidden(h, { id: 's-remote', machine: 'devbox' }),
                H.isSpaceHidden(h, { id: 's-visible', machine: 'devbox' }),
            ];
        })()""", raw)
        self.assertEqual(got, [True, True, False])

    def test_is_tab_hidden_inherits_from_space_and_machine_and_settled(self):
        raw = {"machines": ["local"], "spaces": ["s-hidden"], "tabs": ["t-hidden"]}
        got = hidden_eval("""(() => {
            const h = H.normHidden(d);
            const spLocal = { id: 's1', machine: null };
            const spHidden = { id: 's-hidden', machine: 'devbox' };
            const spVisible = { id: 's-vis', machine: 'devbox' };
            return [
                H.isTabHidden(h, { id: 't1' }, spLocal),
                H.isTabHidden(h, { id: 't2' }, spHidden),
                H.isTabHidden(h, { id: 't-hidden' }, spVisible),
                H.isTabHidden(h, { id: 't-settled', settled: true }, spVisible),
                H.isTabHidden(h, { id: 't-normal' }, spVisible),
            ];
        })()""", raw)
        self.assertEqual(got, [True, True, True, True, False])

    def test_patch_hidden_toggles_entries(self):
        raw = {"machines": ["box1"], "spaces": [], "tabs": []}
        got = hidden_eval("""(() => {
            let cur = H.patchHidden(d, 'machine', 'local', true);
            cur = H.patchHidden(cur, 'space', 'sp1', true);
            cur = H.patchHidden(cur, 'tab', 'tb1', true);
            cur = H.patchHidden(cur, 'machine', 'box1', false);
            return cur;
        })()""", raw)
        self.assertEqual(set(got["machines"]), {"local"})
        self.assertEqual(set(got["spaces"]), {"sp1"})
        self.assertEqual(set(got["tabs"]), {"tb1"})


class SessionsHideWiring(unittest.TestCase):
    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")
        self.agents_src = Path(ROOT, "mods", "ob-agents", "main.js").read_text(encoding="utf-8")
        self.tabs_src = Path(ROOT, "mods", "ob-tabs", "main.js").read_text(encoding="utf-8")
        self.switcher_src = Path(ROOT, "mods", "ob-switcher", "main.js").read_text(encoding="utf-8")

    def test_settle_wording_is_retired_in_sessions_menu(self):
        self.assertNotIn('"Settle"', self.src)
        self.assertNotIn('"Unsettle"', self.src)
        self.assertIn('"Hide space"', self.src)
        self.assertIn('"Hide machine"', self.src)
        self.assertIn('"Hide tab"', self.src)
        self.assertIn('"Show tab"', self.src)

    def test_hidden_drawer_replaces_old_shelf(self):
        self.assertIn('"row-hidden-hdr"', self.src)
        self.assertIn('Hidden (${r.count})', self.src)
        self.assertNotIn('"row-shelf"', self.src)

    def test_agents_panel_preserves_blocked_agents_when_hidden(self):
        self.assertIn('normStatus(a.status) === "blocked"', self.agents_src)
        self.assertIn("isMachineHidden", self.agents_src)
        self.assertIn("isSpaceHidden", self.agents_src)
        self.assertIn("isTabHidden", self.agents_src)

    def test_tabs_bar_filters_hidden_tabs_unless_active(self):
        self.assertIn('!isTabHidden(h, x, space) || x.active', self.tabs_src)

    def test_quick_switcher_auto_unhides_selected_hidden_items(self):
        self.assertIn('updateHidden', self.switcher_src)
        self.assertIn('patchHidden', self.switcher_src)

    def test_node_row_and_space_node_variables_defined(self):
        # Regression test for runtime crash: label was undefined in spaceNode, hovered and isSub undefined in nodeRow
        space_node = re.search(r'const spaceNode = \([\s\S]*?\n    \};', self.src)
        self.assertIsNotNone(space_node)
        self.assertNotIn("paneSecondary(label", space_node.group(0))

        node_row = re.search(r'nodeRow\(r, t, sel, now\) \{[\s\S]*?\n  \}', self.src)
        self.assertIsNotNone(node_row)
        self.assertIn("const isSub = SUB_KINDS.has(n.kind);", node_row.group(0))
        self.assertIn("const hovered = this.hover === r.key || cur;", node_row.group(0))

    def test_sessions_imports_ls_helpers_used_by_init(self):
        # Regression test: init() calls lsGet("hidden") and lsSet("hidden"), which must be imported from ./kit.js,
        # and kit.js keeps plain unprefixed localStorage JSON helpers (Herdr gives each mod copy its own store).
        m = re.search(r'import\s*\{([^}]*)\}\s*from\s*"\./kit\.js"', self.src)
        self.assertIsNotNone(m)
        imported = {tok.strip() for tok in m.group(1).split(",") if tok.strip()}
        for sym in ("lsGet", "lsSet"):
            if f"{sym}(" in self.src:
                self.assertIn(sym, imported)
        kit_src = Path(ROOT, "kit", "kit.js").read_text(encoding="utf-8")
        self.assertNotIn("lsKey", kit_src)
        self.assertIn("localStorage.getItem(k)", kit_src)
        self.assertIn("localStorage.setItem(k, JSON.stringify(v))", kit_src)


@unittest.skipUnless(NODE, "node is not installed")
class WorktreeModGate(unittest.TestCase):
    def test_hasMod_checks_mod_json_or_main_js_under_appHome(self):
        with tempfile.TemporaryDirectory(prefix="kit-hasmod-") as folder:
            for path in glob.glob(os.path.join(ROOT, "kit", "*.js")):
                shutil.copy(path, os.path.join(folder, os.path.basename(path)))
            kit_src = Path(folder, "kit.js").read_text(encoding="utf-8")
            kit_src = (kit_src
                       .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
                       .replace('from "gpui-base"', 'from "./gpui-base.js"')
                       .replace('from "herdr"', 'from "./herdr.js"'))
            Path(folder, "kit.js").write_text(kit_src, encoding="utf-8")
            Path(folder, "gpui-kit.js").write_text("export const div = () => null; export const svg = () => null; export const image = () => null;\n", encoding="utf-8")
            Path(folder, "gpui-base.js").write_text("export const h_flex = () => null; export const v_flex = () => null;\n", encoding="utf-8")
            herdr_fns = ["theme", "run", "openOverlay", "closeOverlay", "layout", "shared", "setShared", "keys", "spaces", "agents", "terminals", "panes", "focused", "home", "window"]
            Path(folder, "herdr.js").write_text(
                "".join(f"export const {n} = () => [];\n" for n in herdr_fns)
                + 'const FILES = new Map([\n'
                + '  ["/app/mods/worktree/mod.json", "{}"],\n'
                + '  ["/app/mods/only-main/main.js", "export default class {}"],\n'
                + ']);\n'
                + 'export const appHome = () => "/app";\n'
                + 'export const readTextFile = async (p) => {\n'
                + '  if (p.includes("/boom/")) throw new Error("read fail");\n'
                + '  return FILES.get(p) ?? null;\n'
                + '};\n',
                encoding="utf-8",
            )
            code = (
                f'import {{ hasMod }} from "{Path(folder, "kit.js").as_uri()}";\n'
                'const out = await Promise.all(['
                'hasMod("worktree"), hasMod("only-main"), hasMod("missing"), hasMod("boom")'
                ']);\n'
                'console.log(JSON.stringify(out));'
            )
            res = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout), [True, True, False, False])

    def test_sessions_probes_worktree_mod_and_gates_worktree_menu_items(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('hasMod', src.split('from "./kit.js"')[0])
        self.assertIn('this.hasWorktreeMod = false;', src)
        self.assertIn('hasMod("worktree")', src)
        self.assertIn('if (g && this.hasWorktreeMod)', src)
        block = src[src.index('if (g && this.hasWorktreeMod)'):src.index('items.push({ label: "Move up"', src.index('if (g && this.hasWorktreeMod)'))]
        self.assertIn('New worktree…', block)
        self.assertIn('Open worktree…', block)
        self.assertIn('Remove worktree…', block)


if __name__ == "__main__":
    unittest.main()
