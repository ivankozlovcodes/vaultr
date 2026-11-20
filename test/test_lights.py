"""kit/lights.js: macOS traffic-light clearance for top-left bars (pure, run under node).

When Herdr draws a borderless window (`titlebar: "none"`) on macOS outside fullscreen, the system traffic-light buttons
sit at `root.traffic_lights` (`[x, y]` in window pixels). Top-left bars (`ob-strip` on the left side's top/stand-in
strip, `ob-tabs` when `ob-left` is hidden or narrow, and the top-left `ob-pane` header when `ob-tabbar` is collapsed in
Zen mode) inset their left padding so controls do not sit under them."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
LIGHTS = Path(ROOT, "kit", "lights.js")
NODE = shutil.which("node")

MAC_WIN = {"platform": "macos", "titlebar": "none", "fullscreen": False}
ROOT_TL = {"traffic_lights": [12, 14]}


def run_lights(expr, payload=None):
    src = (f'import * as L from "{LIGHTS.as_uri()}";\n'
           f'const d = {json.dumps(payload)};\n'
           f'console.log(JSON.stringify({expr}));')
    out = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(NODE, "node is not installed")
class LightsLeftPad(unittest.TestCase):
    def test_macos_borderless_window_insets_for_traffic_lights(self):
        got = run_lights(
            "[L.lightsLeftPad(8, d.win, d.root, 1, 0), L.lightsLeftPad(8, d.win, { traffic_lights: [20, 14] }, 1, 0)]",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [76, 84])

    def test_macos_fullscreen_keeps_base_pad(self):
        win = {**MAC_WIN, "fullscreen": True}
        got = run_lights("L.lightsLeftPad(8, d.win, d.root, 1, 0)", {"win": win, "root": ROOT_TL})
        self.assertEqual(got, 8)

    def test_non_macos_and_system_titlebar_keep_base_pad(self):
        cases = [
            {"platform": "linux", "titlebar": "none", "fullscreen": False},
            {"platform": "windows", "titlebar": "none", "fullscreen": False},
            {"platform": "macos", "titlebar": "system", "fullscreen": False},
            {},
            None,
        ]
        got = run_lights("d.cases.map((w) => L.lightsLeftPad(8, w, d.root, 1, 0))", {"cases": cases, "root": ROOT_TL})
        self.assertEqual(got, [8, 8, 8, 8, 8])

    def test_missing_traffic_lights_keeps_base_pad(self):
        roots = [{}, {"traffic_lights": None}, {"traffic_lights": "12,14"}, None]
        got = run_lights("d.roots.map((r) => L.lightsLeftPad(8, d.win, r, 1, 0))", {"win": MAC_WIN, "roots": roots})
        self.assertEqual(got, [8, 8, 8, 8])

    def test_left_offset_open_hidden_and_narrow(self):
        # ob-left open (300px) clears the lights; hidden (0px) needs full 76px; narrow (44px) needs 32px; 72px clamps to basePad.
        got = run_lights(
            "[300, 0, 44, 72].map((off) => L.lightsLeftPad(8, d.win, d.root, 1, off))",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [8, 76, 32, 8])

    def test_zoom_scales_traffic_light_clearance(self):
        got = run_lights(
            "[0.5, 1, 1.25, 2.0, 0, -1].map((z) => L.lightsLeftPad(8, d.win, d.root, z, 0))",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [152, 76, 61, 38, 76, 76])

    def test_empty_traffic_lights_array_uses_default_x(self):
        got = run_lights("L.lightsLeftPad(8, d.win, { traffic_lights: [] }, 1, 0)", {"win": MAC_WIN})
        self.assertEqual(got, 76)


@unittest.skipUnless(NODE, "node is not installed")
class PaneLightsLeftPad(unittest.TestCase):
    def test_normal_mode_keeps_base_pad_even_when_left_hidden(self):
        got = run_lights(
            "[L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: false, leftHidden: false, tabbarHeight: 40, mainPad: 6, isTopLeft: true }),"
            " L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: false, leftHidden: true, tabbarHeight: 40, mainPad: 6, isTopLeft: true })]",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [6, 6])

    def test_zen_mode_macos_borderless_insets_top_left_pane(self):
        got = run_lights(
            "L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: true })",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, 69)

    def test_non_zen_collapsed_tabbar_respects_left_sidebar(self):
        got = run_lights(
            "[L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: false, leftHidden: false, leftWidth: 300, tabbarHeight: 0, mainPad: 6, isTopLeft: true }),"
            " L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: false, leftHidden: true, leftWidth: 300, tabbarHeight: 0, mainPad: 6, isTopLeft: true })]",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [6, 69])

    def test_split_panes_and_zoomed_secondary_pane_in_zen_mode(self):
        got = run_lights(
            "[L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: false }),"
            " L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 1, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: true })]",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [6, 69])

    def test_fullscreen_linux_and_zoom_scaling_in_zen_mode(self):
        got = run_lights(
            "[L.paneLightsLeftPad(6, { win: { ...d.win, fullscreen: true }, root: d.root, zoom: 1, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: true }),"
            " L.paneLightsLeftPad(6, { win: { platform: 'linux', titlebar: 'none', fullscreen: false }, root: d.root, zoom: 1, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: true }),"
            " L.paneLightsLeftPad(6, { win: d.win, root: d.root, zoom: 2, zen: true, leftHidden: true, tabbarHeight: 0, mainPad: 6, isTopLeft: true })]",
            {"win": MAC_WIN, "root": ROOT_TL},
        )
        self.assertEqual(got, [6, 6, 31])


class LightsWiring(unittest.TestCase):
    def test_kit_reexports_and_syncs_lights_module(self):
        self.assertIn('export { lightsLeftPad, paneLightsLeftPad } from "./lights.js";', read("kit", "kit.js"))
        self.assertIn('"$KIT/lights.js"', read("kit", "sync.sh"))

    def test_ob_strip_insets_top_left_bar(self):
        src = read("mods", "ob-strip", "main.js")
        self.assertIn("lightsLeftPad", src)
        self.assertIn('const topLeft = p.side === "left" && (top || Boolean(lent));', src)
        self.assertIn("const leftPad = topLeft ? lightsLeftPad(S.pad, w, root, zoom, 0) : S.pad;", src)
        self.assertIn("const fixed = leftPad + S.pad +", src)
        self.assertIn(".pl(leftPad).pr(S.pad)", src)

    def test_ob_tabs_insets_bar_for_left_sidebar(self):
        src = read("mods", "ob-tabs", "main.js")
        self.assertIn("lightsLeftPad", src)
        self.assertIn("const leftWidth = leftHidden ? 0 : (leftNode?.size?.px ?? 300);", src)
        self.assertIn("const leftPad = lightsLeftPad(8, w, root, zoom, leftWidth);", src)
        self.assertIn("const fixed = leftPad + 6 +", src)
        self.assertIn(".pl(leftPad).pr(6)", src)

    def test_ob_pane_insets_top_left_bar_in_zen_mode(self):
        src = read("mods", "ob-pane", "main.js")
        self.assertIn("paneLightsLeftPad", src)
        self.assertIn("const zoomedPane = mine.find((q) => q.zoomed) ?? null;", src)
        self.assertIn("const isTopLeftPane = zoomedPane ? zoomedPane.pane === p.pane : (mine[0]?.pane ?? p.pane) === p.pane;", src)
        self.assertIn("const extraLeft = leftPad - 6;", src)
        self.assertIn("const leftW = (addr ? 52 : 0) + extraLeft;", src)
        self.assertIn(".pl(leftPad).pr(6)", src)


if __name__ == "__main__":
    unittest.main()
