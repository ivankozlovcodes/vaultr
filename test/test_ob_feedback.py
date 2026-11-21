"""kit/feedback_bundle.js, mods/ob-tabs/feedback_capture.js, and mods/ob-feedback/main.js tests."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(home_guard.ROOT)
KIT_BUNDLE = ROOT / "kit" / "feedback_bundle.js"
CAPTURE_MOD = ROOT / "mods" / "ob-tabs" / "feedback_capture.js"
FEEDBACK_MOD = ROOT / "mods" / "ob-feedback"
NODE = shutil.which("node")

PNG_BYTES = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52])
PNG_BYTES_ALT = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x53])


def run_bundle(body, arg=None):
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    code = (
        f'import * as B from "{KIT_BUNDLE.as_uri()}";\n'
        'const A = JSON.parse(process.env.A || "null");\n'
        f'const r = await (async () => {{ {body} }})();\n'
        'process.stdout.write(JSON.stringify(r === undefined ? null : r));\n'
    )
    res = subprocess.run(
        [NODE, "--input-type=module", "-e", code],
        env={**os.environ, "A": json.dumps(arg)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def _el_stub():
    return (
        "const proxyEl = () => {\n"
        "  const rec = { keyContext: null, actions: {}, images: [] };\n"
        "  const p = new Proxy(() => p, {\n"
        "    get(_t, prop) {\n"
        '      if (prop === "__rec") return rec;\n'
        '      if (prop === "when") return (cond, fn) => { if (cond) fn(p); return p; };\n'
        '      if (prop === "key_context") return (ctx) => { rec.keyContext = ctx; return p; };\n'
        '      if (prop === "on_action") return (name, fn) => { rec.actions[name] = fn; return p; };\n'
        "      return () => p;\n"
        "    },\n"
        "  });\n"
        "  return p;\n"
        "};\n"
    )


def _stage_e2e_env(folder, app_dir, home_dir, cfg):
    (folder / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    bundle_src = KIT_BUNDLE.read_text(encoding="utf-8")
    (folder / "feedback_bundle.js").write_text(bundle_src, encoding="utf-8")
    for name in ("agents.js", "attention.js", "feed_age.js", "follow_target.js", "fuzzy.js", "hidden.js", "lights.js", "names.js", "ticker.js", "touches.js"):
        src = ROOT / "kit" / name
        if src.exists():
            shutil.copy(src, folder / name)

    cap_src = (
        CAPTURE_MOD.read_text(encoding="utf-8")
        .replace('from "fs/promises"', 'from "./fs-sandbox.js"')
        .replace('from "herdr"', 'from "./herdr.js"')
    )
    (folder / "feedback_capture.js").write_text(cap_src, encoding="utf-8")

    fb_src = (
        (FEEDBACK_MOD / "main.js")
        .read_text(encoding="utf-8")
        .replace('from "gpui-kit"', 'from "./gpui-kit.js"')
        .replace('from "gpui-base"', 'from "./gpui-base.js"')
        .replace('from "fs/promises"', 'from "./fs-sandbox.js"')
        .replace('from "herdr"', 'from "./herdr.js"')
    )
    (folder / "feedback_main.js").write_text(fb_src, encoding="utf-8")

    # Enforce Herdr's real gpui-kit fs/promises capability sandbox:
    # read_roots=[home_dir], write_roots=[app_dir], throwing synchronously BEFORE returning a Promise.
    (folder / "fs-sandbox.js").write_text(
        'import * as nodeFs from "node:fs/promises";\n'
        'import * as nodePath from "node:path";\n'
        f"const READ_ROOTS = [{json.dumps(str(home_dir))}];\n"
        f"const WRITE_ROOTS = [{json.dumps(str(app_dir))}];\n"
        "function assertUnder(roots, p, op) {\n"
        "  const norm = nodePath.resolve(String(p));\n"
        "  for (const r of roots) {\n"
        "    const base = nodePath.resolve(String(r));\n"
        "    if (norm === base || norm.startsWith(base + nodePath.sep)) return;\n"
        "  }\n"
        "  throw new Error(`OutsideRoots (${op}): ${norm}`);\n"
        "}\n"
        "export function mkdir(p, opts) { assertUnder(WRITE_ROOTS, p, 'mkdir'); return nodeFs.mkdir(p, opts); }\n"
        "export function readFile(p, opts) { assertUnder(READ_ROOTS, p, 'readFile'); return nodeFs.readFile(p, opts); }\n"
        "export function writeFile(p, data, opts) { assertUnder(WRITE_ROOTS, p, 'writeFile'); return nodeFs.writeFile(p, data, opts); }\n"
        "export function readdir(p, opts) { assertUnder(READ_ROOTS, p, 'readdir'); return nodeFs.readdir(p, opts); }\n"
        "export function unlink(p) { assertUnder(WRITE_ROOTS, p, 'unlink'); return nodeFs.unlink(p); }\n",
        encoding="utf-8",
    )

    (folder / "gpui-kit.js").write_text(
        _el_stub()
        + "export class View {}\n"
        + "export const renderedImages = [];\n"
        + "export const div = () => proxyEl();\n"
        + "export const image = (p) => { renderedImages.push(p); return proxyEl(); };\n",
        encoding="utf-8",
    )
    (folder / "gpui-base.js").write_text(
        _el_stub()
        + "export const h_flex = () => proxyEl();\n"
        + "export const v_flex = () => proxyEl();\n"
        + "export const TextareaState = {\n"
        + "  new: (o = {}) => {\n"
        + "    let val = String(o.value ?? '');\n"
        + "    const handlers = {};\n"
        + "    return {\n"
        + "      handlers,\n"
        + "      focused: false,\n"
        + "      value: () => val,\n"
        + "      set_value: (v) => { val = String(v ?? ''); },\n"
        + "      focus: function () { this.focused = true; },\n"
        + "      on: (ev, fn) => { handlers[ev] = fn; return true; },\n"
        + "    };\n"
        + "  },\n"
        + "};\n"
        + "export const Textarea = { new: () => proxyEl() };\n",
        encoding="utf-8",
    )
    (folder / "kit.js").write_text(
        _el_stub()
        + "export const S = { text: 13, textSm: 12, textXs: 11, textLg: 15, icon: 16, iconSm: 14, iconXs: 12, radius: 4, radiusLg: 6 };\n"
        + "export const tc = () => ({ background: '#111', popover: '#222', chrome: '#181818', raised: '#242424', border: '#333', input: '#444', foreground: '#eee', muted: '#aaa', dim: '#777', accent: '#58f', accent_foreground: '#fff', working: '#ea0', blocked: '#e44', ansi2: '#3a6', hover: '#2a2a2a' });\n"
        + "export const alpha = (c) => c;\n"
        + "export const icon = () => proxyEl();\n"
        + "export const iconButton = () => proxyEl();\n"
        + "export const copyText = (cx, text) => cx.write_to_clipboard(String(text ?? ''));\n"
        + f"export const tilde = (p) => p.startsWith({json.dumps(str(home_dir))} + '/') ? '~' + p.slice({len(str(home_dir))}) : p;\n"
        + f"export const provider = {{ sessions: () => new Array({cfg.get('sessionsCount', 2)}).fill({{}}), subagents: () => new Array({cfg.get('subagentsCount', 3)}).fill({{}}) }};\n",
        encoding="utf-8",
    )

    png_hex = PNG_BYTES.hex()
    png_alt_hex = PNG_BYTES_ALT.hex()
    (folder / "herdr.js").write_text(
        'import * as fs from "node:fs/promises";\n'
        'import * as fsSync from "node:fs";\n'
        'import * as nodePath from "node:path";\n'
        f"const CFG = {json.dumps(cfg)};\n"
        f"const PNG = Buffer.from({json.dumps(png_hex)}, 'hex');\n"
        f"const PNG_ALT = Buffer.from({json.dumps(png_alt_hex)}, 'hex');\n"
        "let shotSeq = 0;\n"
        "export const events = { order: [], overlays: [], closed: [], notifies: [], ran: [], clipboard: [], cmds: [] };\n"
        "let currentProps = CFG.props ?? {};\n"
        "export const setProps = (p) => { currentProps = p; };\n"
        "export const props = () => currentProps;\n"
        f"export const home = () => {json.dumps(str(home_dir))};\n"
        f"export const appHome = () => {json.dumps(str(app_dir))};\n"
        "export const checking = () => Boolean(CFG.checking);\n"
        "export const layout = () => CFG.layoutTree;\n"
        "export const layouts = () => ['vaultr', 'main'];\n"
        "export const focused = () => CFG.focused;\n"
        "export const spaces = () => CFG.spaces;\n"
        "export const panes = () => CFG.panes;\n"
        "export const agents = () => CFG.agents;\n"
        "export const terminals = () => CFG.terminals;\n"
        "export const machines = () => [{ name: null, layout: 'ready' }];\n"
        "export const window = () => ({ platform: CFG.platform ?? 'linux', titlebar: 'none', buttons: false, maximized: false, fullscreen: false, active: true });\n"
        "export const settings = () => ({ zoom: 1, theme: 'graphite' });\n"
        "export const updates = () => ({ app: { version: '0.1.16', ready: null, updates: false }, core: { version: '0.1.16', managed: null, ready: null, updating: false, error: null }, notes: [], checked: 100, checks: false, checking: false });\n"
        "export const keys = () => CFG.keys;\n"
        "export const shared = (k) => CFG.shared[k];\n"
        "export const run = (name, args) => { events.ran.push([name, args ?? null]); return null; };\n"
        "export const openOverlay = (spec) => { events.order.push('openOverlay'); events.overlays.push(spec); setProps({ ...(spec.props ?? {}), overlay: 'fb-ov-1' }); return 'fb-ov-1'; };\n"
        "export const closeOverlay = (id) => { events.closed.push(id); return null; };\n"
        "export const notify = (n) => { events.notifies.push(n); return 'n-1'; };\n"
        "export const pickFolder = async () => CFG.pickedFolder ?? null;\n"
        "export const nextCommand = () => new Promise((resolve) => events.cmds.push(resolve));\n"
        "export const readTextFile = async (p) => { try { return await fs.readFile(p, 'utf8'); } catch (e) { if (e.code === 'ENOENT') return null; throw e; } };\n"
        "export const writeTextFile = async (p, text, expected) => { await fs.mkdir(nodePath.dirname(p), { recursive: true }); const cur = await readTextFile(p); if (cur !== expected) throw new Error('stale'); await fs.writeFile(p, text, 'utf8'); return null; };\n"
        "export const exec = async (cmd, args = []) => {\n"
        "  if (cmd === 'mkdir' && args[0] === '-p' && args[1]) {\n"
        "    fsSync.mkdirSync(args[1], { recursive: true });\n"
        "    return { code: 0, stdout: '', stderr: '' };\n"
        "  }\n"
        "  if (cmd === 'test' && args[0] === '-d' && args[1]) {\n"
        "    try { return { code: fsSync.statSync(args[1]).isDirectory() ? 0 : 1, stdout: '', stderr: '' }; }\n"
        "    catch { return { code: 1, stdout: '', stderr: '' }; }\n"
        "  }\n"
        "  if (cmd === 'test' && args[0] === '-s' && args[1]) {\n"
        "    try { const st = fsSync.statSync(args[1]); return { code: st.isFile() && st.size > 0 ? 0 : 1, stdout: '', stderr: '' }; }\n"
        "    catch { return { code: 1, stdout: '', stderr: '' }; }\n"
        "  }\n"
        "  if (cmd === 'cp' && args.length >= 2) {\n"
        "    try { fsSync.copyFileSync(args[0], args[1]); return { code: 0, stdout: '', stderr: '' }; }\n"
        "    catch (e) { return { code: 1, stdout: '', stderr: String(e?.message ?? e) }; }\n"
        "  }\n"
        "  if (cmd === 'rm' && args[0] === '-f' && args[1]) {\n"
        "    fsSync.rmSync(args[1], { force: true });\n"
        "    return { code: 0, stdout: '', stderr: '' };\n"
        "  }\n"
        "  const sub = args[0];\n"
        "  events.order.push(`exec:${sub}`);\n"
        "  if (sub === 'shot') {\n"
        "    if (CFG.failShot) return { code: 1, stdout: '', stderr: 'no window running' };\n"
        "    shotSeq += 1;\n"
        "    await fs.mkdir(nodePath.dirname(args[1]), { recursive: true });\n"
        "    await fs.writeFile(args[1], shotSeq % 2 === 1 ? PNG : PNG_ALT);\n"
        "    return { code: 0, stdout: args[1] + '\\n', stderr: '' };\n"
        "  }\n"
        "  if (sub === 'status') return { code: 0, stdout: JSON.stringify(CFG.appStatus ?? { layout: 'vaultr', errors: [] }), stderr: '' };\n"
        "  if (sub === 'ls') return { code: 0, stdout: JSON.stringify(CFG.appWorld ?? { spaces: [] }), stderr: '' };\n"
        "  return { code: 1, stdout: '', stderr: `unknown ${cmd}` };\n"
        "};\n",
        encoding="utf-8",
    )


@unittest.skipUnless(NODE, "node is not installed")
class FeedbackBundleUnitTests(unittest.TestCase):
    def test_slugify_feedback_strips_markdown_caps_length_and_falls_back(self):
        cases = [
            ("# Bug: Sidebar collapsed on split!", "bug-sidebar-collapsed-on-split"),
            ("   \n##   First real line!\nMore text", "first-real-line"),
            ("This feedback title is definitely much longer than thirty six characters total", "this-feedback-title-is-definitely-mu"),
            ("### --- !!!", "feedback"),
            ("", "feedback"),
        ]
        for text, want in cases:
            self.assertEqual(run_bundle("return B.slugifyFeedback(A.t);", {"t": text}), want)

    def test_format_bundle_stamp_and_collision_suffixes(self):
        stamp = run_bundle(
            "return B.formatBundleStamp({ year: 2026, month: 11, day: 20, hours: 8, minutes: 5, seconds: 9 });"
        )
        self.assertEqual(stamp, "2026-11-20_08-05-09")
        d1 = run_bundle("return B.pickBundleDirName(A.s, 'bug', []);", {"s": stamp})
        d2 = run_bundle("return B.pickBundleDirName(A.s, 'bug', [A.b]);", {"s": stamp, "b": d1})
        d3 = run_bundle("return B.pickBundleDirName(A.s, 'bug', [A.b, A.b2]);", {"s": stamp, "b": d1, "b2": d2})
        self.assertEqual((d1, d2, d3), ("2026-11-20_08-05-09-bug", "2026-11-20_08-05-09-bug-2", "2026-11-20_08-05-09-bug-3"))
        avail = run_bundle("""
            const taken = new Set(['/out/2026-11-20_08-05-09-bug', '/out/2026-11-20_08-05-09-bug-2']);
            return await B.pickAvailableBundleDir('/out', A.s, 'bug', async (p) => taken.has(p));
        """, {"s": stamp})
        self.assertEqual(avail, "2026-11-20_08-05-09-bug-3")

    def test_host_file_helpers_build_unix_and_windows_commands(self):
        got = run_bundle("""
            const calls = [];
            const exec = async (cmd, args) => {
              calls.push([cmd, args]);
              if (cmd === 'test' && args[0] === '-d') return { code: args[1].endsWith('/taken') ? 0 : 1, stdout: '', stderr: '' };
              return { code: 0, stdout: '', stderr: '' };
            };
            await B.ensureDir('/tmp/a/b', exec, 'linux');
            await B.ensureDir('C:/Feedback/vaultr', exec, 'windows');
            const dYes = await B.dirExists('/tmp/taken', exec, 'linux');
            const dNo = await B.dirExists('/tmp/free', exec, 'linux');
            const sOk = await B.nonEmptyFileExists('/tmp/a/shot.png', exec, 'linux');
            const cOk = await B.copyBinaryFile('/tmp/a/shot.png', '/tmp/b/screenshot.png', exec, 'linux');
            await B.copyBinaryFile('C:/a/shot.png', 'C:/b/screenshot.png', exec, 'windows');
            await B.removeFile('/outside/old.png', { unlink: () => { throw new Error('OutsideRoots'); } }, exec, 'linux');
            return { calls, dYes, dNo, sOk, cOk };
        """)
        self.assertTrue(got["dYes"])
        self.assertFalse(got["dNo"])
        self.assertTrue(got["sOk"])
        self.assertTrue(got["cOk"])
        self.assertEqual(got["calls"][0], ["mkdir", ["-p", "/tmp/a/b"]])
        self.assertEqual(got["calls"][1], ["cmd", ["/d", "/c", "if", "not", "exist", "C:\\Feedback\\vaultr", "mkdir", "C:\\Feedback\\vaultr"]])
        self.assertEqual(got["calls"][5], ["cp", ["/tmp/a/shot.png", "/tmp/b/screenshot.png"]])
        self.assertEqual(got["calls"][6], ["cmd", ["/d", "/c", "copy", "/y", "C:\\a\\shot.png", "C:\\b\\screenshot.png"]])
        self.assertEqual(got["calls"][7], ["rm", ["-f", "/outside/old.png"]])

    def test_herdr_app_candidates_by_platform(self):
        lin = run_bundle("return B.herdrAppCandidates('/srv/u/', 'linux');")
        self.assertEqual(lin, ["herdr-app", "/srv/u/.local/bin/herdr-app"])
        mac_home = "/Users" + "/tester"
        mac = run_bundle("return B.herdrAppCandidates(A.h, 'macos');", {"h": mac_home})
        self.assertEqual(mac, [
            "herdr-app",
            f"{mac_home}/.local/bin/herdr-app",
            "/Applications/Herdr.app/Contents/MacOS/Herdr",
            f"{mac_home}/Applications/Herdr.app/Contents/MacOS/Herdr",
        ])

    def test_annotate_layout_tree_across_hidden_and_rearranged_stacks(self):
        tree = {
            "id": "root",
            "type": "row",
            "children": [
                {
                    "id": "ob-left",
                    "type": "column",
                    "hidden": True,
                    "children": [
                        {
                            "id": "ob-lt-stack",
                            "type": "stack",
                            "active": "ob-sessions",
                            "children": [
                                {"id": "ob-sessions", "type": "block"},
                                {"id": "ob-search", "type": "block"},
                            ],
                        },
                    ],
                },
                {
                    "id": "ob-right",
                    "type": "column",
                    "children": [
                        {
                            "id": "ob-rb-stack",
                            "type": "stack",
                            "active": "ob-outline",
                            "children": [
                                {"id": "ob-graph", "type": "block"},
                                {"id": "ob-outline", "type": "block"},
                            ],
                        },
                    ],
                },
            ],
        }
        got = run_bundle("const out = B.annotateLayoutTree(A); return { out, origHasField: 'effectiveShown' in A };", tree)
        self.assertFalse(got["origHasField"])
        out = got["out"]
        self.assertTrue(out["effectiveShown"])
        left, right = out["children"]
        self.assertFalse(left["effectiveShown"])
        self.assertFalse(left["children"][0]["effectiveShown"])
        self.assertFalse(left["children"][0]["children"][0]["effectiveShown"])
        self.assertTrue(right["effectiveShown"])
        rb = right["children"][0]
        self.assertFalse(rb["children"][0]["effectiveShown"])
        self.assertTrue(rb["children"][1]["effectiveShown"])

    def test_sanitize_shared_and_terminals_strip_secrets_and_raw_prompts(self):
        raw_shared = {
            "layout": "vaultr",
            "ob.zen": {"active": False},
            "ob.quotas": {"email": "secret@example.invalid"},
            "secretPrompts": ["private prompt"],
        }
        s = run_bundle("return B.sanitizeSharedState(A, { sessions: 4, subagents: 7 });", raw_shared)
        self.assertEqual(s["layout"], "vaultr")
        self.assertEqual(s["ob.zen"], {"active": False})
        self.assertEqual(s["providerSessionsCount"], 4)
        self.assertEqual(s["providerSubagentsCount"], 7)
        self.assertNotIn("ob.quotas", s)
        self.assertNotIn("secretPrompts", s)

        raw_terms = [
            {
                "address": "t1",
                "parent": None,
                "name": "shell",
                "template": "default",
                "state": "live",
                "status": "idle",
                "program": {"key": "zsh", "name": "zsh", "agent": False, "shell": True, "icon": "x"},
                "records": {"r1": {}, "r2": {}},
                "argv": ["/bin/zsh", "--token=SECRET"],
                "env": {"API_KEY": "SECRET_VAL"},
                "labels": {"private": "SECRET_LABEL"},
                "screen": "terminal text",
            }
        ]
        terms = run_bundle("return B.sanitizeTerminals(A);", raw_terms)
        self.assertEqual(terms, [{
            "address": "t1",
            "parent": None,
            "name": "shell",
            "template": "default",
            "state": "live",
            "status": "idle",
            "program": {"key": "zsh", "name": "zsh", "agent": False, "shell": True},
            "recordsCount": 2,
        }])

    def test_dump_diagnostics_and_markdown_builders(self):
        capture = {
            "capturedAt": 1700000000000,
            "isoTime": "2026-11-20T08:00:00.000Z",
            "layoutName": "vaultr",
            "layouts": ["vaultr", "main"],
            "window": {"platform": "linux"},
            "appSettings": {"zoom": 1},
            "updates": {"app": {"version": "0.1.16"}, "core": {"version": "0.1.16"}},
            "focused": {"space": "sp1", "tab": "tb1", "pane": "pn1", "terminal": "t1"},
            "layoutTree": {"id": "root", "type": "row", "children": []},
            "spaces": [{"id": "sp1", "name": "work", "active": True, "tabs": [{"id": "tb1", "name": "dev", "active": True}]}],
            "terminals": [{"address": "t1", "state": "live", "argv": ["SECRET"], "env": {"K": "V"}}],
            "keys": [{"section": "layout:vaultr", "keys": "ctrl-alt-shift-f", "action": "ob-tabs.feedback"}],
            "appStatus": {"layout": "vaultr", "errors": []},
            "errorFiles": [{"name": "keys.error", "text": "bad chord"}],
            "hasScreenshot": True,
            "screenshotPath": "data/ob-feedback/shot-1700000000000.png",
            "shotError": None,
        }
        dump = run_bundle("return B.buildUiTreeDump(A);", capture)
        self.assertTrue(dump["layoutTree"]["effectiveShown"])
        self.assertEqual(dump["layoutName"], "vaultr")

        log = run_bundle("return B.buildDiagnosticsLog(A);", capture)
        for sec in ("[summary]", "[app-status]", "[error-files]", "[terminals]", "[keybindings]", "[warnings]"):
            self.assertIn(sec, log)
        self.assertIn("shot-1700000000000.png", log)
        self.assertIn("bad chord", log)
        self.assertIn("ctrl-alt-shift-f", log)
        self.assertNotIn("SECRET", log)

        md = run_bundle("return B.buildFeedbackMarkdown({ ...A, hasScreenshot: true, message: 'Line 1\\nLine 2' });", {
            "created": "2026-11-20T08:00:00.000Z",
            "platform": "linux",
            "herdrApp": "0.1.16",
            "herdrCore": "0.1.16",
            "layout": "vaultr",
            "space": "work",
            "tab": "dev",
            "pane": "pn1",
        })
        self.assertTrue(md.startswith("---\n"))
        self.assertIn('screenshot: "screenshot.png"', md)
        self.assertIn('- "screenshot.png"', md)
        self.assertIn("# Feedback\n\nLine 1\nLine 2", md)

        md_no_shot = run_bundle("return B.buildFeedbackMarkdown({ hasScreenshot: false, message: 'No shot' });")
        self.assertIn("screenshot: null", md_no_shot)
        self.assertNotIn("screenshot.png", md_no_shot)


@unittest.skipUnless(NODE, "node is not installed")
class FeedbackEndToEndTests(unittest.TestCase):
    def _base_cfg(self, out_dir, **extra):
        return {
            "platform": "linux",
            "layoutTree": {
                "id": "root",
                "type": "row",
                "children": [
                    {
                        "id": "ob-lt-stack",
                        "type": "stack",
                        "active": "ob-sessions",
                        "children": [
                            {"id": "ob-sessions", "type": "block"},
                            {"id": "ob-search", "type": "block"},
                        ],
                    }
                ],
            },
            "focused": {"space": "sp1", "tab": "tb1", "pane": "pn1", "terminal": "t1"},
            "spaces": [{"id": "sp1", "name": "dev", "active": True, "tabs": [{"id": "tb1", "name": "main", "active": True}]}],
            "panes": [{"pane": "pn1", "tab": "tb1", "terminal": "t1"}],
            "agents": [],
            "terminals": [{"address": "t1", "name": "zsh", "state": "live", "status": "idle", "argv": ["zsh", "--secret-arg"], "env": {"TOKEN": "PRIVATE_ENV"}, "labels": {"secret": "PRIVATE_LABEL"}}],
            "keys": [{"section": "layout:vaultr", "keys": "ctrl-alt-shift-f", "action": "ob-tabs.feedback"}],
            "shared": {"layout": "vaultr", "ob.zen": {"active": False}, "ob.quotas": {"email": "private@example.invalid"}},
            "pickedFolder": str(out_dir),
            **extra,
        }

    def _run_script(self, tmp_root, cfg, script_body):
        home_dir = tmp_root / "userdir"
        app_dir = tmp_root / "app"
        mod_dir = tmp_root / "mod"
        home_dir.mkdir(exist_ok=True)
        app_dir.mkdir(exist_ok=True)
        mod_dir.mkdir(exist_ok=True)
        _stage_e2e_env(mod_dir, app_dir, home_dir, cfg)
        full = (
            f'import {{ captureFeedbackState }} from "{(mod_dir / "feedback_capture.js").as_uri()}";\n'
            f'import FeedbackDialog from "{(mod_dir / "feedback_main.js").as_uri()}";\n'
            f'import {{ events, openOverlay }} from "{(mod_dir / "herdr.js").as_uri()}";\n'
            f'import {{ renderedImages }} from "{(mod_dir / "gpui-kit.js").as_uri()}";\n'
            "const binds = [];\n"
            "const timers = [];\n"
            "const cx = {\n"
            "  focus_handle: () => ({ focus() {} }),\n"
            "  bind_keys: (list) => binds.push(list),\n"
            "  timer: { after: (_ms, fn) => timers.push(fn) },\n"
            "  spawn: (fn) => fn(cx),\n"
            "  notify: () => {},\n"
            "  stop_propagation: () => {},\n"
            "  write_to_clipboard: (txt) => events.clipboard.push(txt),\n"
            "};\n"
            + script_body
        )
        res = subprocess.run([NODE, "--input-type=module", "-e", full], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_capture_runs_shot_before_open_overlay_and_submit_copy_writes_full_bundle(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            out_dir = t / "feedback-out"
            app_dir.mkdir()
            (app_dir / "feedback.json").write_text(json.dumps({"folder": str(out_dir)}) + "\n", encoding="utf-8")
            (app_dir / "settings.error").write_text("bad setting at line 2\n", encoding="utf-8")
            (app_dir / "layouts" / ".state").mkdir(parents=True)
            (app_dir / "layouts" / ".state" / "vaultr.json").write_text('{"ob-left":{"hidden":false}}\n', encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir), """
                const cap = await captureFeedbackState({ now: () => 1763625900000 });
                openOverlay({ mod: 'ob-feedback', kind: 'dialog', width: 680, height: 580, props: { capturedAt: cap.capturedAt } });
                const dlg = new FeedbackDialog();
                dlg.init({}, cx);
                await dlg.loadInitial();
                dlg.message.set_value('# Bug: Sidebar collapsed\\n\\nExpected sidebar open.');
                const rootRec = dlg.render(cx).__rec;
                const res = await dlg.submit(true, cx);
                console.log(JSON.stringify({
                  order: events.order,
                  res,
                  notifies: events.notifies,
                  clipboard: events.clipboard,
                  closed: events.closed,
                  renderedImages,
                  keyContext: rootRec.keyContext,
                  actions: Object.keys(rootRec.actions),
                  shotPath: cap.screenshotPath,
                }));
            """)

            self.assertEqual(got["order"][0], "exec:shot")
            self.assertLess(got["order"].index("exec:shot"), got["order"].index("openOverlay"))
            self.assertEqual(got["shotPath"], "data/ob-feedback/shot-1763625900000.png")
            self.assertTrue((app_dir / "data/ob-feedback/shot-1763625900000.png").is_file())
            self.assertTrue(got["res"]["ok"])
            bundle = Path(got["res"]["bundleDir"])
            self.assertTrue(bundle.is_dir())
            self.assertIn("-bug-sidebar-collapsed", bundle.name)
            self.assertEqual((bundle / "screenshot.png").read_bytes(), PNG_BYTES)
            md = (bundle / "feedback.md").read_text(encoding="utf-8")
            self.assertIn('screenshot: "screenshot.png"', md)
            self.assertIn("# Bug: Sidebar collapsed", md)
            tree = json.loads((bundle / "ui-tree.json").read_text(encoding="utf-8"))
            self.assertEqual(tree["layoutClickState"], {"ob-left": {"hidden": False}})
            self.assertEqual(tree["sharedState"]["providerSessionsCount"], 2)
            self.assertEqual(tree["sharedState"]["providerSubagentsCount"], 3)
            self.assertNotIn("ob.quotas", tree["sharedState"])
            stack = tree["layoutTree"]["children"][0]
            self.assertTrue(stack["children"][0]["effectiveShown"])
            self.assertFalse(stack["children"][1]["effectiveShown"])
            diag = (bundle / "diagnostics.log").read_text(encoding="utf-8")
            self.assertIn("bad setting at line 2", diag)
            self.assertIn("shot-1700000000000.png" if False else "shot-1763625900000.png", diag)
            self.assertNotIn("PRIVATE_ENV", diag)
            self.assertNotIn("PRIVATE_LABEL", diag)
            self.assertNotIn("--secret-arg", diag)
            self.assertEqual(got["clipboard"], [str(bundle)])
            self.assertEqual(got["notifies"][0]["title"], "Feedback saved (path copied)")
            self.assertEqual(got["closed"], ["fb-ov-1"])
            self.assertEqual(got["renderedImages"], ["data/ob-feedback/shot-1763625900000.png"])
            self.assertEqual(got["keyContext"], "ObFeedback")
            self.assertIn("ob_feedback.close", got["actions"])
            self.assertIn("ob_feedback.submit", got["actions"])

    def test_retake_updates_image_cache_key_and_cleans_previous_staged_png(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            home_dir = t / "userdir"
            out_dir = home_dir / "Feedback" / "in-home"
            app_dir.mkdir()
            home_dir.mkdir()
            (app_dir / "feedback.json").write_text(json.dumps({"folder": "~/Feedback/in-home"}) + "\n", encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir), """
                const cap1 = await captureFeedbackState({ now: () => 1763625900100 });
                openOverlay({ mod: 'ob-feedback', kind: 'dialog', width: 680, height: 580, props: { capturedAt: cap1.capturedAt } });
                const dlg = new FeedbackDialog();
                dlg.init({}, cx);
                await dlg.loadInitial();
                dlg.render(cx);
                await dlg.retake({ now: () => 1763625905200 });
                dlg.render(cx);
                dlg.message.set_value('Retake worked inside home');
                const res = await dlg.submit(false, cx);
                console.log(JSON.stringify({ renderedImages, shot2: dlg.capture.screenshotPath, res }));
            """)
            self.assertEqual(got["renderedImages"], [
                "data/ob-feedback/shot-1763625900100.png",
                "data/ob-feedback/shot-1763625905200.png",
            ])
            self.assertFalse((app_dir / "data/ob-feedback/shot-1763625900100.png").exists())
            self.assertTrue((app_dir / "data/ob-feedback/shot-1763625905200.png").is_file())
            bundle = Path(got["res"]["bundleDir"])
            self.assertTrue(str(bundle).startswith(str(out_dir)))
            self.assertEqual((bundle / "screenshot.png").read_bytes(), PNG_BYTES_ALT)

    def test_colliding_bundle_timestamps_get_numeric_suffix(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            out_dir = t / "feedback-out"
            app_dir.mkdir()
            (app_dir / "feedback.json").write_text(json.dumps({"folder": str(out_dir)}) + "\n", encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir), """
                const cap = await captureFeedbackState({ now: () => 1763625900000 });
                openOverlay({ mod: 'ob-feedback', kind: 'dialog', width: 680, height: 580, props: { capturedAt: cap.capturedAt } });
                const d1 = new FeedbackDialog();
                d1.init({}, cx);
                await d1.loadInitial();
                d1.message.set_value('Same title');
                const r1 = await d1.submit(false, cx);

                const d2 = new FeedbackDialog();
                d2.init({}, cx);
                await d2.loadInitial();
                d2.message.set_value('Same title');
                const r2 = await d2.submit(false, cx);
                console.log(JSON.stringify({ r1, r2 }));
            """)
            self.assertTrue(got["r1"]["ok"])
            self.assertTrue(got["r2"]["ok"])
            self.assertEqual(Path(got["r2"]["bundleDir"]).name, Path(got["r1"]["bundleDir"]).name + "-2")
            self.assertTrue(Path(got["r1"]["bundleDir"], "feedback.md").is_file())
            self.assertTrue(Path(got["r2"]["bundleDir"], "feedback.md").is_file())

    def test_missing_shot_degrades_gracefully_and_writes_remaining_files(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            out_dir = t / "feedback-out"
            app_dir.mkdir()
            (app_dir / "feedback.json").write_text(json.dumps({"folder": str(out_dir)}) + "\n", encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir, failShot=True), """
                const cap = await captureFeedbackState({ now: () => 1763625900000 });
                openOverlay({ mod: 'ob-feedback', kind: 'dialog', width: 680, height: 580, props: { capturedAt: cap.capturedAt } });
                const dlg = new FeedbackDialog();
                dlg.init({}, cx);
                await dlg.loadInitial();
                dlg.message.set_value('Window not running');
                const res = await dlg.submit(false, cx);
                console.log(JSON.stringify({ capHasShot: cap.hasScreenshot, res, renderedImages }));
            """)
            self.assertFalse(got["capHasShot"])
            self.assertTrue(got["res"]["ok"])
            self.assertEqual(got["renderedImages"], [])
            bundle = Path(got["res"]["bundleDir"])
            self.assertFalse((bundle / "screenshot.png").exists())
            self.assertTrue((bundle / "feedback.md").is_file())
            self.assertTrue((bundle / "ui-tree.json").is_file())
            diag = (bundle / "diagnostics.log").read_text(encoding="utf-8")
            self.assertIn("no window running", diag)

    def test_empty_message_validation_and_inline_pick_folder_saves_feedback_json(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            out_dir = t / "picked-out"
            app_dir.mkdir()
            (app_dir / "feedback.json").write_text('{"keepKey": true}\n', encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir), """
                const dlg = new FeedbackDialog();
                dlg.init({}, cx);
                await dlg.loadInitial();
                const emptyRes = await dlg.submit(false, cx);
                const emptyErr = dlg.error;
                dlg.message.set_value('Picked inline');
                const noFolderRes = await dlg.submit(false, cx);
                const noFolderErr = dlg.error;
                await dlg.browseFolder();
                const savedRes = await dlg.submit(false, cx);
                console.log(JSON.stringify({ emptyRes, emptyErr, noFolderRes, noFolderErr, savedRes }));
            """)
            self.assertFalse(got["emptyRes"]["ok"])
            self.assertIn("Write a feedback message", got["emptyErr"])
            self.assertFalse(got["noFolderRes"]["ok"])
            self.assertIn("Choose a feedback folder", got["noFolderErr"])
            self.assertTrue(got["savedRes"]["ok"])
            saved_json = json.loads((app_dir / "feedback.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_json, {"keepKey": True, "folder": str(out_dir)})
            self.assertTrue(Path(got["savedRes"]["bundleDir"], "feedback.md").is_file())

    def test_input_key_context_bindings_and_secondary_submit(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            t = Path(tmp)
            app_dir = t / "app"
            out_dir = t / "feedback-out"
            app_dir.mkdir()
            (app_dir / "feedback.json").write_text(json.dumps({"folder": str(out_dir)}) + "\n", encoding="utf-8")

            got = self._run_script(t, self._base_cfg(out_dir), """
                const cap = await captureFeedbackState({ now: () => 1763625900000 });
                openOverlay({ mod: 'ob-feedback', kind: 'dialog', width: 680, height: 580, props: { capturedAt: cap.capturedAt } });
                const dlg = new FeedbackDialog();
                dlg.init({}, cx);
                await dlg.loadInitial();
                const spawned = [];
                const spawnCx = { ...cx, spawn: (fn) => { const p = fn(spawnCx); spawned.push(p); return p; } };
                dlg.message.set_value('Submitted via secondary enter');
                dlg.message.handlers.submit({ secondary: false }, spawnCx);
                await Promise.all(spawned.splice(0));
                const closedAfterPrimary = events.closed.length;
                dlg.message.handlers.submit({ secondary: true }, spawnCx);
                await Promise.all(spawned.splice(0));
                console.log(JSON.stringify({
                  binds: binds[0] ?? [],
                  closedAfterPrimary,
                  closedFinal: events.closed,
                  notifies: events.notifies,
                }));
            """)

            want_binds = [
                {"keystroke": "escape", "action": "ob_feedback.close", "context": "ObFeedback"},
                {"keystroke": "escape", "action": "ob_feedback.close", "context": "ObFeedback > Input"},
                {"keystroke": "ctrl-enter", "action": "ob_feedback.submit", "context": "ObFeedback"},
                {"keystroke": "ctrl-enter", "action": "ob_feedback.submit", "context": "ObFeedback > Input"},
                {"keystroke": "cmd-enter", "action": "ob_feedback.submit", "context": "ObFeedback"},
                {"keystroke": "cmd-enter", "action": "ob_feedback.submit", "context": "ObFeedback > Input"},
            ]
            for wb in want_binds:
                self.assertIn(wb, got["binds"])
            self.assertEqual(got["closedAfterPrimary"], 0)
            self.assertEqual(got["closedFinal"], ["fb-ov-1"])
            self.assertEqual(got["notifies"][0]["title"], "Feedback saved")
            bundles = list(out_dir.iterdir())
            self.assertEqual(len(bundles), 1)
            self.assertIn("Submitted via secondary enter", (bundles[0] / "feedback.md").read_text(encoding="utf-8"))

    def test_registrations_and_command_wiring(self):
        keys = json.loads((ROOT / "keys" / "vaultr-keys.json").read_text(encoding="utf-8"))
        self.assertEqual(keys["layout:vaultr"].get("ctrl-alt-shift-f"), "ob-tabs.feedback")

        reg = (ROOT / "mods" / "ob-settings" / "registry.js").read_text(encoding="utf-8")
        self.assertIn('["ob-tabs.feedback", "Submit feedback", ["ctrl-alt-shift-f"], null]', reg)
        self.assertIn('["ob-tabs.settings:feedback", "Open feedback settings", [], null]', reg)

        cmds = (ROOT / "mods" / "ob-switcher" / "commands.js").read_text(encoding="utf-8")
        self.assertIn('route: "ob-tabs.feedback"', cmds)
        self.assertIn('route: "ob-tabs.settings:feedback"', cmds)

        footer = (ROOT / "mods" / "ob-footer" / "main.js").read_text(encoding="utf-8")
        self.assertIn('id: "feedback"', footer)
        self.assertIn('run("ob-tabs.feedback")', footer)
        self.assertLess(footer.index('id: "feedback"'), footer.index('id: "help"'))

        manifest = json.loads((FEEDBACK_MOD / "mod.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, {"place": "none", "title": "Submit feedback", "overlay": {"kind": "dialog", "width": 680, "height": 580}})


if __name__ == "__main__":
    unittest.main()
