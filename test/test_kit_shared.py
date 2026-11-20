"""Shared state (ob.hidden, ob.dismissed, ob.history) lives in shared only, with no localStorage mirrors."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
KIT_DIR = Path(ROOT, "kit")
NODE = shutil.which("node")


def _write_ui_stubs(folder):
    (folder / "gpui-kit.js").write_text(
        "export class View {}\n"
        "const el = () => new Proxy(() => el(), { get: () => el });\n"
        "export const div = el, svg = el, image = el;\n",
        encoding="utf-8",
    )
    (folder / "gpui-base.js").write_text(
        "const el = () => new Proxy(() => el(), { get: () => el });\n"
        "export const h_flex = el, v_flex = el;\n"
        "export const InputState = { new: () => ({ on: () => {}, value: () => '', set_value: () => {}, focus: () => {} }) };\n"
        "export const Input = { new: () => el() };\n"
        "export const ScrollHandle = { new: () => ({ scroll_to_item: () => {} }) };\n"
        "export const Scrollbar = { vertical: () => el() };\n",
        encoding="utf-8",
    )


def _ls_preamble(ls_mode, map_init=None):
    if ls_mode == "throw":
        return (
            "let lsAccess = 0;\n"
            "Object.defineProperty(globalThis, 'localStorage', {\n"
            "  configurable: true,\n"
            "  get() { lsAccess += 1; throw new Error('localStorage must not be accessed'); },\n"
            "});\n"
            "const lsGets = [], lsSets = [];\n"
        )
    return (
        f"const lsMap = new Map(Object.entries({json.dumps(map_init or {})}));\n"
        "let lsAccess = 0;\n"
        "const lsGets = [], lsSets = [];\n"
        "globalThis.localStorage = {\n"
        "  getItem(k) { lsAccess += 1; lsGets.push(k); return lsMap.has(k) ? lsMap.get(k) : null; },\n"
        "  setItem(k, v) { lsAccess += 1; lsSets.push(k); lsMap.set(k, String(v)); },\n"
        "};\n"
    )


def _rewrite_mod_imports(src):
    return (
        src.replace('from "gpui-kit"', 'from "./gpui-kit.js"')
           .replace('from "gpui-base"', 'from "./gpui-base.js"')
           .replace('from "herdr"', 'from "./herdr.js"')
    )


def run_kit(body, shared_state=None, ls_mode="throw", map_init=None):
    folder = Path(tempfile.mkdtemp(prefix="kit-shared-"))
    try:
        for p in KIT_DIR.glob("*.js"):
            text = _rewrite_mod_imports(p.read_text(encoding="utf-8")) if p.name == "kit.js" else p.read_text(encoding="utf-8")
            (folder / p.name).write_text(text, encoding="utf-8")
        _write_ui_stubs(folder)
        (folder / "herdr.js").write_text(
            f"const sharedMap = new Map(Object.entries({json.dumps(shared_state or {})}));\n"
            "export const writes = [];\n"
            "export const shared = (k) => sharedMap.get(k);\n"
            "export const setShared = (k, v) => { writes.push([k, v]); sharedMap.set(k, v); };\n"
            "export const snapshotShared = () => Object.fromEntries(sharedMap);\n"
            + "".join(
                f"export const {n} = () => [];\n"
                for n in ("keys", "spaces", "agents", "terminals", "panes")
            )
            + "export const theme = () => ({});\n"
            "export const run = () => {};\n"
            "export const exec = async () => ({ code: 0, stdout: '' });\n"
            "export const openOverlay = () => {};\n"
            "export const closeOverlay = () => {};\n"
            "export const layout = () => ({});\n"
            "export const focused = () => null;\n"
            "export const home = () => '/srv/home';\n"
            "export const appHome = () => '/app';\n"
            "export const readTextFile = async () => null;\n"
            "export const window = () => ({ platform: 'linux' });\n",
            encoding="utf-8",
        )
        script = (
            _ls_preamble(ls_mode, map_init)
            + f'import * as K from "{(folder / "kit.js").as_uri()}";\n'
            + f'import {{ writes, snapshotShared }} from "{(folder / "herdr.js").as_uri()}";\n'
            + f"const result = (() => {{ {body} }})();\n"
            + "console.log(JSON.stringify({ result, shared: snapshotShared(), writes, lsAccess, lsGets, lsSets }));\n"
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_mod(mod_name, body, shared_state=None, spaces_list=None, ls_mode="throw", map_init=None):
    folder = Path(tempfile.mkdtemp(prefix=f"mod-{mod_name}-"))
    try:
        for p in KIT_DIR.glob("*.js"):
            text = _rewrite_mod_imports(p.read_text(encoding="utf-8")) if p.name == "kit.js" else p.read_text(encoding="utf-8")
            (folder / p.name).write_text(text, encoding="utf-8")
        for p in Path(ROOT, "mods", mod_name).glob("*.js"):
            if (KIT_DIR / p.name).exists():
                continue
            (folder / p.name).write_text(_rewrite_mod_imports(p.read_text(encoding="utf-8")), encoding="utf-8")
        _write_ui_stubs(folder)
        (folder / "herdr.js").write_text(
            f"const sharedMap = new Map(Object.entries({json.dumps(shared_state or {})}));\n"
            f"const SPACES = {json.dumps(spaces_list or [])};\n"
            "export const writes = [];\n"
            "export const shared = (k) => sharedMap.get(k);\n"
            "export const setShared = (k, v) => { writes.push([k, v]); sharedMap.set(k, v); };\n"
            "export const snapshotShared = () => Object.fromEntries(sharedMap);\n"
            "export const spaces = () => SPACES;\n"
            "export const machines = () => [];\n"
            "export const panes = () => [];\n"
            "export const terminals = () => [];\n"
            "export const agents = () => [];\n"
            "export const keys = () => [];\n"
            "export const focused = () => null;\n"
            "export const run = () => {};\n"
            f"export const hc = async () => ({{ code: 0, stdout: {json.dumps(json.dumps({'machines': []}))} }});\n"
            "export const exec = async () => ({ code: 0, stdout: '' });\n"
            "export const theme = () => ({});\n"
            "export const props = () => ({});\n"
            "export const nextCommand = () => new Promise(() => {});\n"
            "export const settings = () => ({ zoom: 1 });\n"
            "export const layout = () => ({});\n"
            "export const openOverlay = () => {};\n"
            "export const closeOverlay = () => {};\n"
            "export const notify = () => {};\n"
            "export const readTextFile = async () => null;\n"
            "export const writeTextFile = async () => null;\n"
            "export const watchFolder = () => ({ cancel() {} });\n"
            "export const home = () => '/srv/home';\n"
            "export const appHome = () => '/app';\n"
            "export const window = () => ({ platform: 'linux' });\n",
            encoding="utf-8",
        )
        script = (
            _ls_preamble(ls_mode, map_init)
            + f'import Mod from "{(folder / "main.js").as_uri()}";\n'
            + f'import {{ writes, snapshotShared }} from "{(folder / "herdr.js").as_uri()}";\n'
            + "const cx = { focus_handle: () => ({ focus() {} }), timer: { every: () => {}, after: () => {} }, spawn: () => {}, notify: () => {} };\n"
            + f"const result = (() => {{ {body} }})();\n"
            + "console.log(JSON.stringify({ result, shared: snapshotShared(), writes, lsAccess, lsGets, lsSets }));\n"
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed")
class SharedOnlyKitTests(unittest.TestCase):
    def test_getters_return_empty_defaults_without_localStorage_or_setShared(self):
        got = run_kit("return { hidden: K.getHidden(), dismissed: K.getDismissed() };")
        self.assertEqual(got["result"], {"hidden": {"machines": [], "spaces": [], "tabs": []}, "dismissed": {}})
        self.assertEqual(got["writes"], [])
        self.assertEqual(got["lsAccess"], 0)

    def test_getters_return_shared_values_without_localStorage_or_setShared(self):
        shared_state = {
            "ob.hidden": {"machines": ["box1"], "spaces": ["sp1"], "tabs": ["tb1"]},
            "ob.dismissed": {"t1": "failed@100#2", "bad": 99},
        }
        got = run_kit("return { hidden: K.getHidden(), dismissed: K.getDismissed() };", shared_state=shared_state)
        self.assertEqual(got["result"]["hidden"], shared_state["ob.hidden"])
        self.assertEqual(got["result"]["dismissed"], {"t1": "failed@100#2"})
        self.assertEqual(got["writes"], [])
        self.assertEqual(got["lsAccess"], 0)

    def test_mutators_write_through_setShared_only_with_throwing_localStorage(self):
        got = run_kit("""
            const h1 = K.updateHidden((cur) => ({ ...cur, spaces: ["sp2"] }));
            const d1 = K.updateDismissed((cur) => ({ ...cur, t1: "blocked@20#3" }));
            const d2 = K.setDismissed("t2", true, "failed", { status_ms: 30, turn: 4 });
            const d3 = K.setDismissed("t1", false);
            const d4 = K.pruneDismissedNow(new Map([["t2", "working@40#5"]]));
            const d5 = K.pruneDismissedNow(new Map([["t2", "working@40#5"]]));
            return { h1, d1, d2, d3, d4, d5 };
        """)
        self.assertEqual(got["lsAccess"], 0)
        self.assertEqual(got["result"]["h1"], {"machines": [], "spaces": ["sp2"], "tabs": []})
        self.assertEqual(got["result"]["d1"], {"t1": "blocked@20#3"})
        self.assertEqual(got["result"]["d2"], {"t1": "blocked@20#3", "t2": "failed@30#4"})
        self.assertEqual(got["result"]["d3"], {"t2": "failed@30#4"})
        self.assertEqual(got["result"]["d4"], {})
        self.assertEqual(got["result"]["d5"], {})
        self.assertEqual(got["writes"], [
            ["ob.hidden", {"machines": [], "spaces": ["sp2"], "tabs": []}],
            ["ob.dismissed", {"t1": "blocked@20#3"}],
            ["ob.dismissed", {"t1": "blocked@20#3", "t2": "failed@30#4"}],
            ["ob.dismissed", {"t2": "failed@30#4"}],
            ["ob.dismissed", {}],
        ])

    def test_throwing_standin_throws_and_ls_helpers_stay_exported(self):
        threw = run_kit("try { void localStorage; return false; } catch { return true; }")
        self.assertTrue(threw["result"])
        self.assertEqual(threw["lsAccess"], 1)

        panel = run_kit(
            'K.lsSet("view.sort", "name"); return K.lsGet("view.sort", "manual");',
            ls_mode="map",
        )
        self.assertEqual(panel["result"], "name")
        self.assertEqual(panel["writes"], [])


@unittest.skipUnless(NODE, "node is not installed")
class ModSharedStateTests(unittest.TestCase):
    def test_ob_tabs_init_and_writeHistory_use_shared_only(self):
        got = run_mod(
            "ob-tabs",
            """
            const view = new Mod();
            view.init(null, cx);
            const initial = view.history();
            const entry = { space: "s1", tab: "t1", pane: "p1", terminal: null, at: 100 };
            view.writeHistory({ entries: [entry], index: 0 });
            return { hasRestore: typeof view.restoreHistory, initial, after: view.history() };
            """,
        )
        self.assertEqual(got["lsAccess"], 0)
        self.assertEqual(got["result"]["hasRestore"], "undefined")
        self.assertEqual(got["result"]["initial"], {"entries": [], "index": -1})
        self.assertEqual(got["result"]["after"], {"entries": [{"space": "s1", "tab": "t1", "pane": "p1", "terminal": None, "at": 100}], "index": 0})
        self.assertEqual(got["writes"], [["ob.history", got["result"]["after"]]])

    def test_ob_sessions_init_keeps_only_legacy_machines_and_settled_migration(self):
        spaces = [{"id": "s1", "tabs": [{"id": "t1", "settled": True}, {"id": "t2", "settled": False}]}]
        stale_map = {
            "hidden": json.dumps({"machines": ["stale"], "spaces": ["stale-sp"], "tabs": ["stale-tb"]}),
            "machines.hidden": json.dumps(["legacy-box"]),
        }
        migrated = run_mod(
            "ob-sessions",
            "const view = new Mod(); view.init(null, cx); return view.hiddenState();",
            spaces_list=spaces,
            ls_mode="map",
            map_init=stale_map,
        )
        self.assertEqual(migrated["shared"]["ob.hidden"], {"machines": ["legacy-box"], "spaces": [], "tabs": ["t1"]})
        self.assertEqual(migrated["writes"], [["ob.hidden", {"machines": ["legacy-box"], "spaces": [], "tabs": ["t1"]}]])
        self.assertNotIn("hidden", migrated["lsGets"])
        self.assertNotIn("hidden", migrated["lsSets"])
        self.assertIn("machines.hidden", migrated["lsGets"])

        existing = {"machines": ["kept"], "spaces": [], "tabs": []}
        untouched = run_mod(
            "ob-sessions",
            "const view = new Mod(); view.init(null, cx); return view.hiddenState();",
            shared_state={"ob.hidden": existing},
            spaces_list=spaces,
            ls_mode="map",
            map_init=stale_map,
        )
        self.assertEqual(untouched["shared"]["ob.hidden"], existing)
        self.assertEqual(untouched["writes"], [])
        self.assertNotIn("hidden", untouched["lsGets"])
        self.assertNotIn("machines.hidden", untouched["lsGets"])


if __name__ == "__main__":
    unittest.main()
