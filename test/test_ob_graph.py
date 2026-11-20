"""mods/ob-graph Graph panel, pinned to Quartz's graph (jackyzha0/quartz v4 commit d25a6eab: components/Graph.tsx and
components/scripts/graph.inline.ts) on the vendored d3-force 3.0.0. sim.js runs under node with every timer removed, as
Herdr has none: the mod ticks the simulation itself. Covers: Quartz's default config, its forces, node radius by degree,
the exact local (BFS to depth) and hover neighbourhoods, the label fade with zoom, the zoom extent, positions kept across
refreshes, drag with alphaTarget, settling, and the vendored files' pinned headers."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
MOD = Path(ROOT, "mods", "ob-graph")
SIM = Path(MOD, "sim.js")
FILTER = Path(MOD, "filter.js")
TOUCH = Path(MOD, "touch_shape.js")
MAIN = Path(MOD, "main.js")
SHAPE = Path(MOD, "shape.js")
OBC = Path(MOD, "obc.js")
FOLLOW = Path(ROOT, "kit", "follow_target.js")
VENDOR = Path(MOD, "vendor")
NODE = shutil.which("node")
W, H = 480, 400
PINS = {"d3-force": "3.0.0", "d3-quadtree": "3.0.1", "d3-dispatch": "3.0.1"}   # Quartz v4.5.2 package-lock.json
NO_TIMERS = ('for (const k of ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "requestAnimationFrame"]) '
             'delete globalThis[k];')


def run(body, payload, module=SIM):
    """Runs body in node as a module with no timers (Herdr's runtime), with S = the module (sim.js) and P = payload."""
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    code = (f'{NO_TIMERS}\n'
            f'const S = await import({json.dumps(module.as_uri())});\n'
            f'const P = {json.dumps(payload)};\n'
            f'{body}\n')
    out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or "node failed")
    return json.loads(out.stdout)


def cluster(machine, tag, spaces=2, tabs=2, panes=2):
    """A machine's tree: spaces under the machine, tabs under spaces, panes under tabs."""
    nodes, edges = [], []
    mk = f"m:{machine}"
    for i in range(spaces):
        s = f"s:{tag}{i}"
        nodes.append({"key": s, "kind": "s", "parent": mk})
        edges.append([mk, s, "contain"])
        for j in range(tabs):
            t = f"t:{tag}{i}{j}"
            nodes.append({"key": t, "kind": "t", "parent": s})
            edges.append([s, t, "contain"])
            for k in range(panes):
                p = f"p:{tag}{i}{j}{k}"
                nodes.append({"key": p, "kind": "p", "parent": t})
                edges.append([t, p, "contain"])
    return nodes, edges


def graph(*parts, machines=()):
    nodes = [{"key": f"m:{m}", "kind": "m"} for m in machines]
    edges = []
    for ns, es in parts:
        nodes += ns
        edges += es
    return {"nodes": nodes, "edges": edges}


def world():
    """Two machines with trees and one isolated machine."""
    return graph(cluster("laptop", "a"), cluster("pi", "b", spaces=1, tabs=2, panes=2),
                 machines=["laptop", "pi", "spare"])


QUARTZ_LOCAL = {"drag": True, "zoom": True, "depth": 1, "scale": 1.1, "repelForce": 0.5, "centerForce": 0.3,
                "linkDistance": 30, "fontSize": 0.6, "opacityScale": 1, "showTags": True, "removeTags": [],
                "focusOnHover": False, "enableRadial": False}          # Graph.tsx lines 30-44
QUARTZ_GLOBAL = {"drag": True, "zoom": True, "depth": -1, "scale": 0.9, "repelForce": 0.5, "centerForce": 0.2,
                 "linkDistance": 30, "fontSize": 0.6, "opacityScale": 1, "showTags": True, "removeTags": [],
                 "focusOnHover": True, "enableRadial": True}           # Graph.tsx lines 45-59


class QuartzModel(unittest.TestCase):
    def test_default_config_is_quartz_v4s_local_and_global_graph(self):
        r = run('console.log(JSON.stringify(S.QUARTZ));', {})
        self.assertEqual(r["local"], QUARTZ_LOCAL)
        self.assertEqual(r["global"], QUARTZ_GLOBAL)

    def test_forces_and_simulation_defaults_are_quartz_v4s(self):
        r = run('''
            const sim = S.createSim();
            console.log(JSON.stringify({
              local: S.forceSettings(S.QUARTZ.local, P.W, P.H),
              global: S.forceSettings(S.QUARTZ.global, P.W, P.H),
              alphaMin: sim.d3.alphaMin(), alphaDecay: sim.d3.alphaDecay(), velocityDecay: sim.d3.velocityDecay(),
              extent: S.SCALE_EXTENT,
            }));
        ''', {"W": W, "H": H})
        # charge -100 * repelForce; centre strength; linkDistance 30; collide iterations 3 (graph.inline.ts 169-172)
        # Machines and spaces push less (-40 x repelForce) and their push stops at 250; concentric rings replace outer-rim radial.
        self.assertEqual(r["local"], {"charge": -50, "broadCharge": -20, "maxChargeDistance": 250,
                                      "center": 0.3, "linkDistance": 30, "collideIterations": 3,
                                      "ringStrength": 0.14, "sectorStrength": 0.03})
        self.assertEqual(r["global"], {"charge": -50, "broadCharge": -20, "maxChargeDistance": 250,
                                       "center": 0.2, "linkDistance": 30, "collideIterations": 3,
                                       "ringStrength": 0.14, "sectorStrength": 0.03})
        # Quartz keeps d3-force's alphaMin; the damping is Vaultr's: heavier than d3's (0.4, 0.0228) so the graph is not floaty
        self.assertEqual(r["alphaMin"], 0.001)
        self.assertEqual(r["alphaDecay"], 0.06)
        self.assertEqual(r["velocityDecay"], 0.8)
        self.assertEqual(r["extent"], [0.25, 4])                # zoom scaleExtent (graph.inline.ts 506)

    def test_node_radius_grows_with_the_nodes_that_reference_it(self):
        r = run('''
            const radii = [0, 1, 2, 4, 9, 16, 100].map((d) => S.radiusOf(d, "p"));
            const sim = S.createSim();
            S.sync(sim, P.star, S.QUARTZ.local, P.W, P.H);
            console.log(JSON.stringify({ radii, centre: sim.pos.get("c").r, leaf: sim.pos.get("l0").r }));
        ''', {"star": {"nodes": [{"key": "c", "kind": "p"}] + [{"key": f"l{i}", "kind": "p"} for i in range(4)],
                       "edges": [["c", f"l{i}", "contain"] for i in range(4)]}, "W": W, "H": H})
        radii = r["radii"]
        self.assertEqual(radii[:2], [3, 3], "no link, or just its parent: the base size, so a leaf stays small")
        self.assertEqual(radii, sorted(radii), "never smaller with more links")
        self.assertGreater(radii[3], radii[1] + 2, "a session with a few sub-agents is clearly bigger than a leaf")
        self.assertLessEqual(radii[6], 11, "capped")
        self.assertEqual(r["leaf"], 3)
        self.assertGreater(r["centre"], r["leaf"] + 2, "the hub of four links is bigger than its leaves")


class LocalGraph(unittest.TestCase):
    EDGES = [["a", "b", "contain"], ["b", "c", "link"], ["c", "d", "contain"], ["b", "e", "contain"]]
    KEYS = ["a", "b", "c", "d", "e", "z"]

    def bfs(self, depth):
        g = {"nodes": [{"key": k, "kind": "s"} for k in self.KEYS], "edges": self.EDGES}
        return run('console.log(JSON.stringify(S.localGraph(P.g, "a", P.depth).nodes.map((n) => n.key).sort()));',
                   {"g": g, "depth": depth}, FILTER)

    def test_local_graph_is_exactly_the_breadth_first_neighbourhood_to_depth(self):
        # Quartz walks links both ways (graph.inline.ts 125-140); depth 1 = the focus and its direct links
        self.assertEqual(self.bfs(0), ["a"])
        self.assertEqual(self.bfs(1), ["a", "b"])
        self.assertEqual(self.bfs(2), ["a", "b", "c", "e"])
        self.assertEqual(self.bfs(3), ["a", "b", "c", "d", "e"])

    def test_hover_highlights_the_node_and_its_neighbours_and_nothing_else(self):
        r = run('''
            console.log(JSON.stringify({
              b: [...S.hoverSet(P.edges, "b")].sort(),
              d: [...S.hoverSet(P.edges, "d")].sort(),
              z: [...S.hoverSet(P.edges, "z")].sort(),
            }));
        ''', {"edges": self.EDGES})
        self.assertEqual(r["b"], ["a", "b", "c", "e"], "the node and every node one link away")
        self.assertEqual(r["d"], ["c", "d"])
        self.assertEqual(r["z"], ["z"], "an isolated node is its own neighbourhood")


class Labels(unittest.TestCase):
    def test_label_opacity_follows_quartz_zoom_formula(self):
        # graph.inline.ts 513-514: scale = k * opacityScale; alpha = max((scale - 1) / 3.75, 0)
        r = run('''
            console.log(JSON.stringify([
              S.labelOpacity(0.5, 1), S.labelOpacity(1, 1), S.labelOpacity(2, 1),
              S.labelOpacity(4.75, 1), S.labelOpacity(1.5, 2),
            ]));
        ''', {})
        want = [0, 0, 1 / 3.75, 1, 2 / 3.75]
        for got, exp in zip(r, want):
            self.assertAlmostEqual(got, exp, places=12)

    def test_label_alpha_is_clamped_to_zero_one(self):
        r = run('console.log(JSON.stringify([S.labelOpacity(40, 1), S.labelOpacity(-3, 1)]));', {})
        self.assertEqual(r, [1, 0])


class Hover(unittest.TestCase):
    def test_hover_levels_are_one_inside_the_neighbourhood_and_point_two_outside(self):
        r = run('''
            console.log(JSON.stringify({
              none: S.hoverAlpha(false, false), inNbr: S.hoverAlpha(true, true), out: S.hoverAlpha(false, true),
              dim: S.DIM_ALPHA,
            }));
        ''', {})
        self.assertEqual(r, {"none": 1, "inNbr": 1, "out": 0.2, "dim": 0.2})

    def test_fades_dim_in_100ms_and_restore_in_200ms_with_ease_out(self):
        r = run('''
            console.log(JSON.stringify({
              dimMs: S.fadeMs(1, 0.2), restoreMs: S.fadeMs(0.2, 1),
              start: S.animateAlpha(1, 0.2, 0, 100), end: S.animateAlpha(1, 0.2, 100, 100),
              past: S.animateAlpha(1, 0.2, 500, 100),
              restoreMid: S.animateAlpha(0.2, 1, 100, 200),
              half: S.animateAlpha(1, 0.2, 50, 100),
            }));
        ''', {})
        self.assertEqual((r["dimMs"], r["restoreMs"]), (100, 200))
        self.assertEqual(r["start"], 1)
        self.assertAlmostEqual(r["end"], 0.2, places=12)
        self.assertAlmostEqual(r["past"], 0.2, places=12, msg="a finished fade stays at its target")
        self.assertAlmostEqual(r["restoreMid"], 1 - 0.8 * (1 - 0.5) ** 3, places=12, msg="ease-out cubic")
        self.assertTrue(0.2 < r["half"] < 1)

    def test_zoom_is_clamped_to_quartz_scale_extent(self):
        r = run('''
            const v = S.viewFrom(null);
            console.log(JSON.stringify({ up: S.zoomAt(v, 1000, 0, 0).scale, down: S.zoomAt(v, 0.0001, 0, 0).scale }));
        ''', {})
        self.assertEqual(r, {"up": 4, "down": 0.25})


class Positions(unittest.TestCase):
    def test_a_refresh_with_the_same_nodes_keeps_every_position_and_does_not_reheat(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const snap = JSON.stringify([...sim.pos].map(([k, n]) => [k, n.x, n.y, n.vx, n.vy]));
            const alpha = sim.d3.alpha();
            const changed = S.sync(sim, { nodes: P.g.nodes.map((n) => ({ ...n })), edges: P.g.edges.map((e) => [...e]) }, S.QUARTZ.global, P.W, P.H);
            const reordered = S.sync(sim, { nodes: [...P.g.nodes].reverse(), edges: [...P.g.edges].reverse() }, S.QUARTZ.global, P.W, P.H);
            console.log(JSON.stringify({
              changed, reordered, alphaSame: sim.d3.alpha() === alpha,
              same: JSON.stringify([...sim.pos].map(([k, n]) => [k, n.x, n.y, n.vx, n.vy])) === snap,
            }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertFalse(r["changed"], "a refresh with the same nodes is not a structure change")
        self.assertFalse(r["reordered"])
        self.assertTrue(r["alphaSame"], "no reheat on a refresh")
        self.assertTrue(r["same"], "positions must not change on a refresh")

    def test_a_new_node_starts_one_link_distance_from_its_parent(self):
        base = world()
        leaf = {"key": "p:new", "kind": "p", "parent": "t:a00"}
        nxt = {"nodes": base["nodes"] + [leaf], "edges": base["edges"] + [["t:a00", "p:new", "contain"]]}
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.base, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            S.sync(sim, P.next, S.QUARTZ.global, P.W, P.H);
            const par = sim.pos.get("t:a00"), me = sim.pos.get("p:new");
            console.log(JSON.stringify({ placed: Math.hypot(me.x - par.x, me.y - par.y) }));
        ''', {"base": base, "next": nxt, "W": W, "H": H})
        self.assertAlmostEqual(r["placed"], QUARTZ_GLOBAL["linkDistance"], places=6)

    def test_sibling_keys_seed_at_well_spread_angles(self):
        """A new node's seed angle is hash01(key): keys that differ only in the last character (p:1, p:2, p:3) must
        not land a degree or so apart, stacked on each other."""
        r = run('console.log(JSON.stringify(Array.from({ length: 12 }, (_, i) => S.hash01(`p:${i + 1}`) * 360)));', {})
        gap = lambda x, y: min(abs(x - y) % 360, 360 - abs(x - y) % 360)
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertGreater(gap(r[i], r[j]), 20, f"p:{i + 1} and p:{j + 1}")
        self.assertGreaterEqual(len({int(a // 60) for a in r}), 4, "twelve siblings cover most of the circle")

    def test_old_nodes_move_little_when_a_node_is_added_or_removed(self):
        base = world()
        leaf = {"key": "p:new", "kind": "p", "parent": "t:a00"}
        nxt = {"nodes": base["nodes"] + [leaf], "edges": base["edges"] + [["t:a00", "p:new", "contain"]]}
        gone = "p:a000"
        less = {"nodes": [n for n in base["nodes"] if n["key"] != gone],
                "edges": [e for e in base["edges"] if gone not in (e[0], e[1])]}
        r = run('''
            const out = {};
            for (const [name, next] of Object.entries({ added: P.next, removed: P.less })) {
              const sim = S.createSim(); S.sync(sim, P.base, S.QUARTZ.global, P.W, P.H); S.settle(sim);
              const old = new Map([...sim.pos].map(([k, n]) => [k, [n.x, n.y]]));
              S.sync(sim, next, S.QUARTZ.global, P.W, P.H); S.settle(sim);
              let sum = 0, n = 0, worst = 0;
              for (const [k, [x, y]] of old) {
                if (!sim.pos.has(k) || !next.nodes.some((m) => m.key === k)) continue;
                const q = sim.pos.get(k), d = Math.hypot(q.x - x, q.y - y);
                sum += d; n++; worst = Math.max(worst, d);
              }
              out[name] = { mean: sum / n, worst };
            }
            console.log(JSON.stringify(out));
        ''', {"base": base, "next": nxt, "less": less, "W": W, "H": H})
        for name in ("added", "removed"):
            self.assertLess(r[name]["mean"], 25, f"{name}: the drawing does not jump")


class Settling(unittest.TestCase):
    def test_simulation_settles_below_alpha_min_within_a_bounded_number_of_ticks_then_stops(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            const ticks = S.settle(sim, 2000);
            console.log(JSON.stringify({ ticks, alpha: sim.d3.alpha(), min: sim.d3.alphaMin(), after: S.tick(sim) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertLess(r["ticks"], 150, "alpha 1 decays to 0.001 in about 115 ticks (d3's own 0.0228 took about 300)")
        self.assertLess(r["alpha"], r["min"])
        self.assertFalse(r["after"], "a settled graph does not tick")

    def test_a_dragged_node_pulls_the_rest_less_than_d3_defaults_would(self):
        # "Floaty": dragging one node used to swing the others about. Same graph, same drag, with d3's own settings
        # (velocityDecay 0.4, alphaTarget 1) as the yardstick: the others now move well under 70% as far.
        r = run('''
            const mean = (sim) => {
              S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
              const before = new Map([...sim.pos].map(([k, o]) => [k, [o.x, o.y]]));
              const p = sim.pos.get("p:a000"), tx = p.x + 150, ty = p.y;
              for (let i = 0; i < 60; i++) { S.drag(sim, "p:a000", tx, ty); if (sim.heat != null) sim.d3.alphaTarget(sim.heat); S.tick(sim); }
              let sum = 0, n = 0;
              for (const [k, o] of sim.pos) { if (k === "p:a000") continue; sum += Math.hypot(o.x - before.get(k)[0], o.y - before.get(k)[1]); n++; }
              return sum / n;
            };
            const ours = S.createSim();
            const d3 = S.createSim(); d3.d3.velocityDecay(0.4).alphaDecay(1 - 0.001 ** (1 / 300)); d3.heat = 1;
            console.log(JSON.stringify({ ours: mean(ours), d3: mean(d3) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertLess(r["ours"], 0.7 * r["d3"], r)

    def test_drag_sets_alphaTarget_pins_the_node_and_release_clears_it(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const ok = S.drag(sim, "p:a000", 300, -200);
            const target = sim.d3.alphaTarget(), fx = sim.pos.get("p:a000").fx, fy = sim.pos.get("p:a000").fy;
            for (let i = 0; i < 20; i++) S.tick(sim);
            const p = sim.pos.get("p:a000");
            const at = { x: p.x, y: p.y };
            const whileDragging = S.tick(sim);
            S.release(sim);
            const released = { target: sim.d3.alphaTarget(), fx: sim.pos.get("p:a000").fx, fy: sim.pos.get("p:a000").fy };
            const ticks = S.settle(sim, 2000);
            console.log(JSON.stringify({ ok, target, fx, fy, x: at.x, y: at.y, whileDragging, released, ticks, after: S.tick(sim) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertTrue(r["ok"])
        self.assertEqual(r["target"], 0.2, "dragging reheats, but only to 0.2 (Quartz's 1 made the rest follow too freely)")
        self.assertEqual((r["fx"], r["fy"]), (300, -200))
        self.assertEqual((r["x"], r["y"]), (300, -200), "the dragged node stays where it is put")
        self.assertTrue(r["whileDragging"], "a drag keeps the simulation running after it has settled")
        self.assertEqual(r["released"], {"target": 0, "fx": None, "fy": None}, "release: alphaTarget 0 (line 477)")
        self.assertLess(r["ticks"], 2000)
        self.assertFalse(r["after"])


class Frames(unittest.TestCase):
    """Live physics: the frame loop ticks the simulation; render never does (the coordinator's finding: settle()
    inside render made Herdr interrupt the render on a view switch)."""

    def test_a_structural_change_moves_nothing_in_sync_and_the_loop_runs_until_alpha_min(self):
        base = world()
        leaf = {"key": "p:new", "kind": "p", "parent": "t:a00"}
        nxt = {"nodes": base["nodes"] + [leaf], "edges": base["edges"] + [["t:a00", "p:new", "contain"]]}
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.base, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const pos = () => new Map([...sim.pos].map(([k, n]) => [k, [n.x, n.y]]));
            const p0 = pos();
            const changed = S.sync(sim, P.next, S.QUARTZ.global, P.W, P.H);
            const p1 = pos();
            const moved = [...p0].filter(([k, [x, y]]) => p1.get(k)[0] !== x || p1.get(k)[1] !== y).length;
            const during = S.wantsFrames(sim, {});
            let ticks = 0;
            while (S.wantsFrames(sim, {}) && ticks < 2000) { S.tick(sim); ticks++; }
            console.log(JSON.stringify({ changed, moved, during, alpha: sim.d3.alpha(), min: sim.d3.alphaMin(),
                                        ticks, after: S.wantsFrames(sim, {}) }));
        ''', {"base": base, "next": nxt, "W": W, "H": H})
        self.assertTrue(r["changed"])
        self.assertEqual(r["moved"], 0, "sync (the render path) moves no node: only the frame loop ticks")
        self.assertTrue(r["during"], "after a structural change the loop keeps running")
        self.assertGreater(r["ticks"], 0)
        self.assertLess(r["ticks"], 2000)
        self.assertLess(r["alpha"], r["min"])
        self.assertFalse(r["after"], "once alpha is below alphaMin and nothing is dragged or fading, the loop stops")

    def test_nodes_that_arrive_in_a_cooled_empty_graph_are_laid_out(self):
        """Active only with no agent working: the graph is empty and the simulation cools. When an agent starts, its
        nodes must be laid out (a full reheat), not frozen at their seed points."""
        r = run('''
            const sim = S.createSim(); S.sync(sim, { nodes: [], edges: [] }, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const cooled = S.wantsFrames(sim, {});
            const changed = S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            console.log(JSON.stringify({ cooled, changed, alpha: sim.d3.alpha(), running: S.wantsFrames(sim, {}) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertFalse(r["cooled"])
        self.assertTrue(r["changed"])
        self.assertTrue(r["running"], "the frame loop must run to lay the new nodes out")
        self.assertEqual(r["alpha"], 1, "a graph built from nothing is a fresh layout: full heat")

    def test_a_view_switch_that_removes_nodes_reheats_without_ticking(self):
        full = world()
        keep = {"nodes": [n for n in full["nodes"] if not n["key"].startswith("m:spare") and not n["key"].startswith("s:b")],
                "edges": [e for e in full["edges"] if not (e[0].startswith("s:b") or e[1].startswith("s:b"))]}
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.full, S.QUARTZ.local, P.W, P.H); S.settle(sim);
            const pos = () => new Map([...sim.pos].map(([k, n]) => [k, [n.x, n.y]]));
            const p0 = pos();
            const changed = S.sync(sim, P.keep, S.QUARTZ.global, P.W, P.H);
            const p1 = pos();
            const moved = [...p0].filter(([k]) => p1.has(k)).filter(([k, [x, y]]) => p1.get(k)[0] !== x || p1.get(k)[1] !== y).length;
            console.log(JSON.stringify({ changed, moved, running: S.wantsFrames(sim, {}) }));
        ''', {"full": full, "keep": keep, "W": W, "H": H})
        self.assertTrue(r["changed"])
        self.assertEqual(r["moved"], 0, "a view switch does not tick: the frame loop moves the nodes")
        self.assertTrue(r["running"])

    def test_a_drag_keeps_the_loop_running_until_release_then_it_stops(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const idle = S.wantsFrames(sim, {});
            S.drag(sim, "p:a000", 300, -200);
            for (let i = 0; i < 300; i++) S.tick(sim);
            const dragging = S.wantsFrames(sim, { dragging: true });
            S.release(sim);
            const ticks = S.settle(sim, 2000);
            console.log(JSON.stringify({ idle, dragging, ticks, after: S.wantsFrames(sim, {}) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertFalse(r["idle"], "a settled graph with nothing going on does not run the loop")
        self.assertTrue(r["dragging"], "during a drag the predicate stays true")
        self.assertLess(r["ticks"], 2000)
        self.assertFalse(r["after"], "released: it cools and stops")

    def test_a_hover_fade_keeps_the_loop_running(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            console.log(JSON.stringify({ fading: S.wantsFrames(sim, { fading: true }), still: S.wantsFrames(sim, {}) }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertTrue(r["fading"])
        self.assertFalse(r["still"])

    def test_dragging_a_node_pulls_its_linked_neighbour_after_it(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const a = sim.pos.get("p:a000"), b = sim.pos.get("t:a00");
            S.drag(sim, "p:a000", a.x + 400, a.y);
            const bx0 = b.x, by0 = b.y;
            const d0 = Math.hypot(b.x - a.x, b.y - a.y);
            for (let i = 0; i < 200; i++) S.tick(sim);
            const d1 = Math.hypot(b.x - a.x, b.y - a.y);
            console.log(JSON.stringify({ moved: Math.hypot(b.x - bx0, b.y - by0), d0, d1 }));
        ''', {"g": world(), "W": W, "H": H})
        self.assertGreater(r["moved"], 50, "the neighbour follows the dragged node")
        self.assertLess(r["d1"], r["d0"], "the link pulls the neighbour closer over ticks")

    def test_render_does_not_tick_or_settle_the_simulation(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertNotIn("settle(", src, "no synchronous settle anywhere: a view switch was interrupted by it")
        render = src[src.index("  render(cx) {"):]              # render is the class's last method
        self.assertNotIn("tick(", render, "render draws positions only; the frame loop ticks")


class ActiveOnly(unittest.TestCase):
    """The "Active only" filter (filter.js, pure). Node fields: kind, parent, status, live, foreground (a pane whose terminal
    is a main agent). A pane is active by its agent's status (kit/agents.js), as the Agents panel shows it. There are no tab
    nodes: a pane hangs off its space, and the two panes of one tab are joined by an invisible sibling link."""

    def graph(self):
        N = [
            {"key": "m:laptop", "kind": "m"}, {"key": "m:pi", "kind": "m"}, {"key": "m:spare", "kind": "m"},
            {"key": "s:A", "kind": "s", "parent": "m:laptop"}, {"key": "s:B", "kind": "s", "parent": "m:pi"},
            {"key": "p:A1a", "kind": "p", "parent": "s:A", "status": "working", "foreground": True},
            {"key": "p:A1b", "kind": "p", "parent": "s:A", "live": False, "foreground": False},
            {"key": "p:A2a", "kind": "p", "parent": "s:A", "live": False, "foreground": False},
            {"key": "p:B1a", "kind": "p", "parent": "s:B", "live": False, "foreground": False},
            {"key": "r:sub", "kind": "r", "parent": "p:A1a", "status": "working", "live": True},
            {"key": "r:done", "kind": "r", "parent": "p:A1a", "live": False},
            {"key": "c:sub", "kind": "c", "parent": "p:A1a", "status": "working", "live": True},
            {"key": "h:bg", "kind": "h", "parent": "c:sub", "status": "working", "live": True},
            {"key": "h:orphan", "kind": "h", "parent": "m:pi", "status": "working", "live": True},
            {"key": "r:stray", "kind": "r", "parent": "p:B1a", "status": "working", "live": True},
        ]
        E = [["m:laptop", "s:A", "contain"], ["m:pi", "s:B", "contain"], ["s:A", "p:A1a", "contain"],
             ["s:A", "p:A1b", "contain"], ["s:A", "p:A2a", "contain"], ["s:B", "p:B1a", "contain"],
             ["p:A1a", "p:A1b", "sibling"],
             ["p:A1a", "r:sub", "link"], ["p:A1a", "r:done", "link"], ["p:A1a", "c:sub", "link"],
             ["c:sub", "h:bg", "link"], ["m:pi", "h:orphan", "contain"], ["p:B1a", "r:stray", "link"]]
        return {"nodes": N, "edges": E}

    def filtered(self, on):
        r = run('console.log(JSON.stringify(S.filterGraph(P.g, P.on)));', {"g": self.graph(), "on": on}, FILTER)
        return r

    def test_on_keeps_every_machine_and_space_the_foreground_agent_and_its_live_subagents(self):
        keys = {n["key"] for n in self.filtered(True)["nodes"]}
        self.assertEqual(keys, {"m:laptop", "m:pi", "m:spare", "s:A", "s:B", "p:A1a", "r:sub", "c:sub", "h:bg"})

    def test_finished_subagents_are_hidden_and_live_ones_kept(self):
        keys = {n["key"] for n in self.filtered(True)["nodes"]}
        self.assertNotIn("r:done", keys, "a finished subagent is hidden")
        self.assertIn("r:sub", keys, "a live subagent is kept")

    def test_an_idle_pane_with_no_agent_is_hidden(self):
        keys = {n["key"] for n in self.filtered(True)["nodes"]}
        self.assertNotIn("p:A2a", keys)
        self.assertNotIn("p:A1b", keys)

    def test_machines_and_spaces_are_always_kept_even_with_nothing_active_under_them(self):
        keys = {n["key"] for n in self.filtered(True)["nodes"]}
        self.assertIn("m:spare", keys, "no agent under it")
        self.assertIn("m:pi", keys)
        self.assertIn("s:B", keys, "a space with only idle panes")
        self.assertNotIn("h:orphan", keys, "its only live subagent hangs off no agent, so it is still dropped")

    def test_with_no_agent_active_the_frame_is_still_drawn(self):
        r = run('console.log(JSON.stringify(S.filterGraph(P.g, true, null, 0).nodes.map((n) => n.key).sort()));',
                {"g": {"nodes": [{"key": "m:a", "kind": "m"}, {"key": "s:1", "kind": "s", "parent": "m:a"},
                                 {"key": "p:x", "kind": "p", "parent": "s:1", "status": "idle", "foreground": True}],
                       "edges": [["m:a", "s:1", "contain"], ["s:1", "p:x", "contain"]]}}, FILTER)
        self.assertEqual(r, ["m:a", "s:1"])

    def test_a_live_subagent_of_a_plain_terminal_is_hidden(self):
        keys = {n["key"] for n in self.filtered(True)["nodes"]}
        self.assertNotIn("r:stray", keys, "only foreground agents anchor subagents")

    def test_off_keeps_everything(self):
        r = self.filtered(False)
        self.assertEqual(len(r["nodes"]), len(self.graph()["nodes"]))
        self.assertEqual(len(r["edges"]), len(self.graph()["edges"]))

    def test_edges_are_kept_only_between_kept_nodes(self):
        r = self.filtered(True)
        keys = {n["key"] for n in r["nodes"]}
        for a, b, _k in r["edges"]:
            self.assertTrue(a in keys and b in keys)
        self.assertIn(["p:A1a", "r:sub", "link"], r["edges"])
        self.assertNotIn(["p:A1a", "p:A1b", "sibling"], r["edges"], "a sibling whose pane is hidden goes with it")


class Vendored(unittest.TestCase):
    def test_vendored_d3_files_carry_their_pinned_versions_and_licences(self):
        for pkg, ver in PINS.items():
            with self.subTest(pkg=pkg):
                folder = Path(VENDOR, pkg)
                licence = Path(folder, "LICENSE").read_text(encoding="utf-8")
                self.assertIn("Permission to use, copy, modify, and/or distribute", licence, "ISC licence text")
                srcs = sorted(Path(folder, "src").glob("*.js"))
                self.assertTrue(srcs)
                for src in srcs:
                    first = src.read_text(encoding="utf-8").splitlines()[0]
                    self.assertTrue(first.startswith(f"// {pkg} {ver} (ISC, "), f"{src.name}: {first}")

    def test_vendored_code_schedules_nothing_and_imports_only_relative_paths(self):
        bad_call = re.compile(r"\b(setTimeout|setInterval|requestAnimationFrame)\s*\(")
        bare_import = re.compile(r'^\s*(import|export)[^;]*from\s+"(?!\.)', re.M)
        for src in VENDOR.rglob("*.js"):
            text = src.read_text(encoding="utf-8")
            with self.subTest(file=str(src.relative_to(MOD))):
                self.assertIsNone(bad_call.search(text), "Herdr has no timers: nothing may call them")
                self.assertIsNone(bare_import.search(text), "imports must be relative paths")


class View(unittest.TestCase):
    def test_fit_puts_every_node_inside_the_view_with_padding(self):
        g = graph(cluster("laptop", "a"), cluster("pi", "b"), cluster("desk", "c"),
                  machines=["laptop", "pi", "desk", "spare"])
        r = run('''
            const sim = S.createSim(); S.sync(sim, P, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const keys = P.nodes.map((n) => n.key);
            const v = S.fitView(S.boundsOf(sim, keys), P.W, P.H);
            const xs = keys.map((k) => { const p = sim.pos.get(k); return [p.x * v.scale + v.x, p.y * v.scale + v.y]; });
            console.log(JSON.stringify({ pad: S.FIT_PAD, scale: v.scale, xs }));
        ''', {**g, "W": W, "H": H})
        pad = r["pad"]
        self.assertGreater(r["scale"], 0)
        for x, y in r["xs"]:
            self.assertGreaterEqual(x, pad["x"] - 1e-9)     # the fit maps the box onto the padded view: float error only
            self.assertLessEqual(x, W - pad["x"] + 1e-9)
            self.assertGreaterEqual(y, pad["top"] - 1e-9)
            self.assertLessEqual(y, H - pad["bottom"] + 1e-9)

    def test_a_hand_pan_or_zoom_stops_the_auto_fit_until_fit_is_pressed(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            const keys = P.nodes.map((n) => n.key);
            const box = S.boundsOf(sim, keys);
            const auto = S.autoFit(S.viewFrom(null), box, P.W, P.H);
            const panned = S.panTo(auto, auto.x + 50, auto.y);
            const bigger = { x0: box.x0 * 3, y0: box.y0 * 3, x1: box.x1 * 3, y1: box.y1 * 3 };
            const kept = S.autoFit(panned, bigger, P.W, P.H);
            const zoomed = S.zoomAt(auto, 1.25, 240, 200);
            const keptZoom = S.autoFit(zoomed, bigger, P.W, P.H);
            const pressed = S.fitNow(bigger, P.W, P.H);
            console.log(JSON.stringify({
              autoManual: auto.manual, pannedManual: panned.manual, keptSame: kept.x === panned.x && kept.scale === panned.scale,
              zoomManual: zoomed.manual, keptZoomSame: keptZoom.scale === zoomed.scale,
              pressedManual: pressed.manual,
            }));
        ''', {**world(), "W": W, "H": H})
        self.assertFalse(r["autoManual"])
        self.assertTrue(r["pannedManual"])
        self.assertTrue(r["keptSame"], "a panned view is not refitted by a size or structure change")
        self.assertTrue(r["zoomManual"])
        self.assertTrue(r["keptZoomSame"])
        self.assertFalse(r["pressedManual"], "fit clears the manual flag")


SHAPE = Path(MOD, "shape.js")


def local_world(dead=20):
    """A machine and a space; one foreground agent pane with one live and `dead` finished subagents, and an idle pane."""
    N = [{"key": "m:laptop", "kind": "m"}, {"key": "s:A", "kind": "s", "parent": "m:laptop"},
         {"key": "p:A1a", "kind": "p", "parent": "s:A", "status": "working", "foreground": True},
         {"key": "p:A2a", "kind": "p", "parent": "s:A", "live": False, "foreground": False},
         {"key": "r:live", "kind": "r", "parent": "p:A1a", "status": "working", "live": True}]
    E = [["m:laptop", "s:A", "contain"], ["s:A", "p:A1a", "contain"], ["s:A", "p:A2a", "contain"], ["p:A1a", "r:live", "link"]]
    for i in range(dead):
        N.append({"key": f"r:dead{i}", "kind": "r", "parent": "p:A1a", "status": "done", "live": False})
        E.append(["p:A1a", f"r:dead{i}", "link"])
    return {"nodes": N, "edges": E}


class LocalView(unittest.TestCase):
    """The Local view and the one "Active only" switch (filter.js, pure). A pane's subagent tree is one hop; Active off
    shows finished subagents too; Active on shows live ones only."""

    def keys(self, r):
        return {n["key"] for n in r["nodes"]}

    def test_local_depth_one_from_a_pane_still_includes_every_subagent_of_its_agent(self):
        r = run('console.log(JSON.stringify(S.localGraph(P.g, "p:A1a", 1)));', {"g": local_world()}, FILTER)
        ks = self.keys(r)
        self.assertIn("p:A1a", ks)
        self.assertEqual(len([k for k in ks if k.startswith("r:")]), 21, "live and finished subagents both in the neighbourhood")

    def test_local_depth_one_keeps_the_focus_parent_chain_up_to_its_machine(self):
        """The local graph says where it is: the focus's space and machine are always in it, Active only off too."""
        r = run('console.log(JSON.stringify(S.filterGraph(S.localGraph(P.g, "p:A1a", 1), false, "p:A1a")));', {"g": local_world()}, FILTER)
        self.assertTrue({"s:A", "m:laptop"} <= self.keys(r))

    def test_local_does_not_expand_through_a_machine(self):
        """A machine is kept when reached but not walked through: depth 3 must not swallow the machine's other spaces."""
        g = local_world(dead=0)
        g["nodes"] += [{"key": "s:B", "kind": "s", "parent": "m:laptop"}, {"key": "p:B1a", "kind": "p", "parent": "s:B"}]
        g["edges"] += [["m:laptop", "s:B", "contain"], ["s:B", "p:B1a", "contain"]]
        r = run('console.log(JSON.stringify(S.localGraph(P.g, "p:A1a", 3)));', {"g": g}, FILTER)
        ks = self.keys(r)
        self.assertIn("m:laptop", ks)
        self.assertNotIn("s:B", ks)
        self.assertNotIn("p:B1a", ks)

    def test_active_off_local_shows_the_dead_subagents_of_the_focused_agent(self):
        r = run('''
            const local = S.localGraph(P.g, "p:A1a", 2);
            console.log(JSON.stringify(S.filterGraph(local, false, "p:A1a")));
        ''', {"g": local_world()}, FILTER)
        self.assertEqual(len([k for k in self.keys(r) if k.startswith("r:dead")]), 20)

    def test_active_on_local_shows_only_the_live_subagents_of_the_focused_agent(self):
        r = run('''
            const local = S.localGraph(P.g, "p:A1a", 2);
            console.log(JSON.stringify(S.filterGraph(local, true, "p:A1a")));
        ''', {"g": local_world()}, FILTER)
        ks = self.keys(r)
        self.assertIn("r:live", ks)
        self.assertFalse([k for k in ks if k.startswith("r:dead")])
        self.assertIn("m:laptop", ks)

    def test_active_on_keeps_an_idle_focus_and_its_live_subagents(self):
        g = local_world()
        g["nodes"].append({"key": "r:idleLive", "kind": "r", "parent": "p:A2a", "status": "working", "live": True})
        g["edges"].append(["p:A2a", "r:idleLive", "link"])
        r = run('''
            const local = S.localGraph(P.g, "p:A2a", 1);
            console.log(JSON.stringify(S.filterGraph(local, true, "p:A2a")));
        ''', {"g": g}, FILTER)
        self.assertIn("p:A2a", self.keys(r), "the focus anchors the view even when it is not an active agent")
        self.assertIn("r:idleLive", self.keys(r))

    def test_the_toggle_flips_only_the_current_views_state(self):
        r = run('''
            const s0 = { local: true, global: true };
            const s1 = S.setActive(s0, "local", false);
            console.log(JSON.stringify({ s0, s1, localNow: S.activeOf(s1, "local"), globalNow: S.activeOf(s1, "global"),
              missing: S.activeOf({}, "local") }));
        ''', {}, FILTER)
        self.assertEqual(r["s0"], {"local": True, "global": True}, "the input is not mutated")
        self.assertEqual(r["s1"], {"local": False, "global": True})
        self.assertFalse(r["localNow"])
        self.assertTrue(r["globalNow"])
        self.assertTrue(r["missing"], "Active only is on by default")


class OneSwitch(unittest.TestCase):
    """The old "show finished sub-agents" control and its state are gone; Active only is the one switch."""

    def test_the_old_finished_control_and_its_storage_key_are_gone_from_main(self):
        # The one read of the old "show" key is the migration (activeState); nothing writes it any more.
        src = MAIN.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
        for needle in ["g-finished", 'save("show"', "this.finished", 'verb === "finished"', "finished:"]:
            self.assertNotIn(needle, code, f"main.js still has {needle!r}")

    def test_only_filter_js_hides_finished_subagents(self):
        src = MAIN.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
        self.assertNotIn("if (!live", code, "the model no longer drops subagents by liveness; filter.js does")
        self.assertIn("shownGraph", code)  # which calls filterGraph

    def test_a_saved_show_finished_setting_migrates_to_active_only_off_in_both_views(self):
        r = run('''console.log(JSON.stringify({
          legacyOn: S.activeState(null, { finished: true }),
          legacyOff: S.activeState(null, { finished: false }),
          savedWins: S.activeState({ local: false }, { finished: false }),
          fresh: S.activeState(null, null),
        }));''', {}, FILTER)
        self.assertEqual(r["legacyOn"], {"local": False, "global": False})
        self.assertEqual(r["legacyOff"], {"local": True, "global": True})
        self.assertEqual(r["savedWins"], {"local": False, "global": True})
        self.assertEqual(r["fresh"], {"local": True, "global": True})


class SubParents(unittest.TestCase):
    """shape.js placeSubs: a sub-agent hangs off its parent session. The parent is a placed pane, or an unplaced hc child
    (h:<address>, itself a sub-agent, in any order); only with neither does it hang off its machine (and Active only
    then drops it)."""

    def place(self, subs, panes):
        return run('console.log(JSON.stringify(S.placeSubs(P.subs, new Map(P.panes)).map((x) => [x.key, x.parent, x.edge])));',
                   {"subs": subs, "panes": panes}, SHAPE)

    def test_a_run_of_an_unplaced_hc_child_hangs_off_that_child(self):
        r = self.place([{"key": "r:x", "parentAddr": "local/hc1", "machine": None},
                        {"key": "h:local/hc1", "parentAddr": "local/t1", "machine": None}], [["local/t1", "p:1"]])
        self.assertEqual(sorted(r), [["h:local/hc1", "p:1", "link"], ["r:x", "h:local/hc1", "link"]])

    def test_a_nested_hc_child_hangs_off_its_hc_parent_whatever_the_order(self):
        r = self.place([{"key": "h:local/c", "parentAddr": "local/b", "machine": None},
                        {"key": "h:local/b", "parentAddr": "local/a", "machine": None},
                        {"key": "h:local/a", "parentAddr": "local/t1", "machine": None}], [["local/t1", "p:1"]])
        self.assertEqual(dict((k, p) for k, p, _ in r), {"h:local/a": "p:1", "h:local/b": "h:local/a", "h:local/c": "h:local/b"})

    def test_with_no_known_parent_it_hangs_off_its_machine(self):
        r = self.place([{"key": "r:y", "parentAddr": "pi/gone", "machine": "pi"}, {"key": "r:z", "parentAddr": None, "machine": None}], [])
        self.assertEqual(r, [["r:y", "m:pi", "contain"], ["r:z", "m:local", "contain"]])

    def test_main_places_sub_agents_through_placeSubs(self):
        self.assertIn("placeSubs(", MAIN.read_text(encoding="utf-8"))


class LabelBox(unittest.TestCase):
    """A label's box is tall enough for its text at every zoom, so nothing is clipped (sim.js labelLayout, pure)."""

    def test_label_box_is_at_least_1_3_times_the_font_size_for_zoom_0_25_to_4(self):
        r = run('''
            const out = [];
            for (const scale of [0.9, 1.1]) for (const k of [0.25, 0.5, 0.8, 1, 1.25, 1.6, 2, 3, 4]) {
              out.push({ k, scale, ...S.labelLayout(k, scale) });
            }
            console.log(JSON.stringify(out));
        ''', {})
        for row in r:
            self.assertGreaterEqual(row["height"], row["size"] * 1.3, f"zoom {row['k']} scale {row['scale']}: {row}")
            self.assertGreaterEqual(row["lineHeight"], row["size"] * 1.3, f"zoom {row['k']}: {row}")
            self.assertLessEqual(row["lineHeight"], row["height"], "the line fits the box, so nothing overflows it")


class Shape(unittest.TestCase):
    """shape.js (pure): a tab's panes are nodes (no tab node). The panes of one tab are joined in a chain by sibling links,
    which the simulation pulls with a spring and nothing draws. Labels come in from the caller (paneLabel)."""

    def shape(self, panes):
        return run(f"console.log(JSON.stringify(S.paneShape('t1', {json.dumps(panes)})));", {}, SHAPE)

    def test_one_pane_is_one_node_and_no_link(self):
        r = self.shape([{"pane": "p1", "label": "herdr-trials"}])
        self.assertEqual([(n["key"], n["kind"], n["label"]) for n in r["nodes"]], [("p:p1", "p", "herdr-trials")])
        self.assertEqual(r["edges"], [])

    def test_two_panes_are_two_nodes_and_one_sibling_link_and_no_tab_node(self):
        r = self.shape([{"pane": "p1", "label": "herdr-trials"}, {"pane": "p2", "label": "~/git/vaultr"}])
        self.assertEqual({n["key"] for n in r["nodes"]}, {"p:p1", "p:p2"})
        self.assertEqual(r["edges"], [["p:p1", "p:p2", "sibling"]])

    def test_three_panes_are_chained_so_the_tab_is_one_cluster(self):
        r = self.shape([{"pane": "p1", "label": "a"}, {"pane": "p2", "label": "b"}, {"pane": "p3", "label": "c"}])
        self.assertEqual(r["edges"], [["p:p1", "p:p2", "sibling"], ["p:p2", "p:p3", "sibling"]])

    def test_panes_with_the_same_label_still_get_distinct_labels(self):
        r = self.shape([{"pane": "p1", "label": "Claude Code"}, {"pane": "p2", "label": "Claude Code"}])
        labels = [n["label"] for n in r["nodes"]]
        self.assertEqual(len(set(labels)), 2, labels)

    def test_adding_a_second_pane_keeps_the_existing_pane_node_key(self):
        one = self.shape([{"pane": "p1", "label": "zsh"}])
        two = self.shape([{"pane": "p1", "label": "zsh"}, {"pane": "p2", "label": "htop"}])
        self.assertIn("p:p1", {n["key"] for n in one["nodes"]})
        self.assertIn("p:p1", {n["key"] for n in two["nodes"]}, "the pane keeps its node, so its position is kept")

    def test_no_tab_node_is_ever_made(self):
        r = self.shape([{"pane": "p1", "label": "a"}, {"pane": "p2", "label": "b"}])
        self.assertFalse([n for n in r["nodes"] if n["kind"] == "t"])


class Halo(unittest.TestCase):
    """The halo for active agents (sim.js, pure): a working agent pulses, a blocked one ("needs you") has a steady halo,
    idle and finished agents have none. The pulse runs at 15 fps and only while an active agent is visible."""

    def test_only_working_and_blocked_agents_get_a_halo_and_of_those_working_pulses(self):
        r = run('''console.log(JSON.stringify({
          working: S.haloKind({ state: "working" }), blocked: S.haloKind({ state: "blocked" }),
          idle: S.haloKind({ state: "idle" }), unknown: S.haloKind({}), none: S.haloKind(null),
        }));''', {})
        self.assertEqual(r, {"working": "pulse", "blocked": "steady", "idle": None, "unknown": None, "none": None})

    def test_the_pulse_eases_between_0_15_and_0_35_over_1_6_seconds(self):
        r = run('''
            const xs = []; for (let t = 0; t <= 3200; t += 50) xs.push(S.haloAlpha(t));
            console.log(JSON.stringify({ xs, t0: S.haloAlpha(0), tHalf: S.haloAlpha(800), tFull: S.haloAlpha(1600) }));
        ''', {})
        self.assertAlmostEqual(r["t0"], 0.15, places=9)
        self.assertAlmostEqual(r["tHalf"], 0.35, places=9)
        self.assertAlmostEqual(r["tFull"], 0.15, places=9, msg="one period is 1.6 s")
        for a in r["xs"]:
            self.assertGreaterEqual(a, 0.15 - 1e-9)
            self.assertLessEqual(a, 0.35 + 1e-9)
        # ease in-out: slow at the ends, fastest in the middle (the first step is smaller than the middle one)
        self.assertLess(r["xs"][1] - r["xs"][0], r["xs"][9] - r["xs"][8])

    def test_a_blocked_agent_has_a_steady_halo_at_0_25_and_an_idle_one_none(self):
        r = run('''console.log(JSON.stringify([
          S.haloFor({ state: "blocked" }, 0), S.haloFor({ state: "blocked" }, 777),
          S.haloFor({ state: "idle" }, 500), S.haloFor({ state: "working" }, 800)]));''', {})
        self.assertEqual(r[0], 0.25)
        self.assertEqual(r[1], 0.25, "steady: it does not pulse")
        self.assertIsNone(r[2])
        self.assertAlmostEqual(r[3], 0.35, places=9)

    def test_the_halo_dims_with_its_node_when_something_else_is_hovered(self):
        r = run('''console.log(JSON.stringify({
          full: S.haloDrawAlpha({ state: "working" }, 800, 1),
          dimmed: S.haloDrawAlpha({ state: "working" }, 800, 0.2),
          none: S.haloDrawAlpha({ state: "idle" }, 800, 1) }));''', {})
        self.assertAlmostEqual(r["full"], 0.35, places=9)
        self.assertAlmostEqual(r["dimmed"], 0.07, places=9, msg="0.35 x the node's 0.2 hover alpha")
        self.assertIsNone(r["none"])

    def test_a_parent_link_of_an_active_agent_is_stronger(self):
        r = run('''console.log(JSON.stringify({
          active: S.linkRestAlpha(true), rest: S.linkRestAlpha(false) }));''', {})
        self.assertEqual(r["active"], 0.6)
        self.assertEqual(r["rest"], 0.35)

    def test_pulse_only_runs_the_loop_at_15_fps_and_stops_with_no_active_agent(self):
        r = run('''
            const sim = S.createSim(); S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H); S.settle(sim);
            console.log(JSON.stringify({
              settledNoPulse: S.frameIntervalMs(sim, { pulsing: false }),
              settledPulse: S.frameIntervalMs(sim, { pulsing: true }),
              wantsNo: S.wantsFrames(sim, { pulsing: false }),
              wantsPulse: S.wantsFrames(sim, { pulsing: true }),
              dragging: S.frameIntervalMs(sim, { dragging: true }),
              fading: S.frameIntervalMs(sim, { fading: true }),
            }));
        ''', {"g": world()})
        self.assertIsNone(r["settledNoPulse"], "a settled graph with no active agent runs no loop")
        self.assertEqual(r["settledPulse"], 67, "pulse-only runs at 15 fps")
        self.assertFalse(r["wantsNo"])
        self.assertTrue(r["wantsPulse"])
        self.assertEqual(r["dragging"], 16, "motion keeps the 60 fps rate")
        self.assertEqual(r["fading"], 16)

    def test_the_active_agent_predicate_ignores_nodes_that_are_not_visible(self):
        r = run('''console.log(JSON.stringify({
          visible: S.anyPulsing([{ state: "idle" }, { state: "working" }]),
          none: S.anyPulsing([{ state: "idle" }, { state: "blocked" }]),
          empty: S.anyPulsing([]) }));''', {})
        self.assertTrue(r["visible"])
        self.assertFalse(r["none"], "blocked does not pulse; only working does")
        self.assertFalse(r["empty"])


ACTIVITY = Path(ROOT, "kit", "agents.js")
NOW = 1794651186963   # a realistic epoch-ms "now"; the node shapes below are invented data


class ActivityRule(unittest.TestCase):
    """What counts as active, for the halo and for Active only (kit/agents.js, pure). The same answer as the Agents panel:
    a main agent is active when Herdr reports it working or blocked ("needs you"); a sub-agent or run is active when
    the feed says it is live and the feed is not paused. Shape: hc ls reports devbox/t28 with state "live" and status
    "idle" (a pi terminal placed in a tab, so it is a foreground node)."""

    def act(self, nodes, now=NOW):
        return run('console.log(JSON.stringify(P.nodes.map((n) => S.activityOf(n, P.now))));',
                   {"nodes": nodes, "now": now}, ACTIVITY)

    def test_an_idle_or_done_pi_on_a_remote_machine_is_not_active(self):
        idle = {"key": "p:devbox-t28", "kind": "p", "foreground": True, "status": "idle", "live": True, "machine": "devbox"}
        done = {"key": "p:devbox-t22", "kind": "p", "foreground": True, "status": "done", "live": True, "machine": "devbox"}
        self.assertEqual(self.act([idle, done]), [None, None])

    def test_a_pane_that_is_not_a_main_agent_gets_no_halo_whatever_its_status(self):
        self.assertEqual(self.act([{"key": "p:x", "kind": "p", "foreground": False, "status": "working"}]), [None])

    def test_a_placed_pi_reported_working_is_working_and_blocked_needs_you(self):
        working = {"key": "p:a", "kind": "p", "foreground": True, "status": "working"}
        blocked = {"key": "p:b", "kind": "p", "foreground": True, "status": "blocked"}
        self.assertEqual(self.act([working, blocked]), ["working", "blocked"])

    def test_a_stale_live_flag_on_a_pane_is_not_activity(self):
        # The old rule set live = "placed in a pane" and read it as working. The flag alone is nothing now.
        self.assertEqual(self.act([{"key": "p:a", "kind": "p", "foreground": True, "status": "idle", "live": True}]), [None])

    def test_unknown_or_missing_status_is_not_active(self):
        nodes = [{"key": "p:u", "kind": "p", "foreground": True, "status": "settled"},
                 {"key": "p:n", "kind": "p", "foreground": True}]
        self.assertEqual(self.act(nodes), [None, None])

    def test_a_live_run_or_claude_agent_is_working_and_a_blocked_one_needs_you(self):
        nodes = [{"key": "r:1", "kind": "r", "live": True, "status": "running"},
                 {"key": "c:1", "kind": "c", "live": True, "status": "working"},
                 {"key": "c:2", "kind": "c", "live": True, "status": "blocked"}]
        self.assertEqual(self.act(nodes), ["working", "working", "blocked"])

    def test_a_finished_run_is_not_active(self):
        self.assertEqual(self.act([{"key": "r:d", "kind": "r", "live": False, "status": "done"}]), [None])

    def test_a_live_sub_agent_that_reports_done_or_idle_is_not_active(self):
        # `live` says the terminal or run exists; the status says whether it works. done and idle are never active.
        nodes = [{"key": "r:d", "kind": "r", "live": True, "status": "done", "feedAt": NOW},
                 {"key": "c:i", "kind": "c", "live": True, "status": "idle", "feedAt": NOW},
                 {"key": "h:d", "kind": "h", "live": True, "status": "done", "feedAt": NOW},
                 {"key": "h:n", "kind": "h", "live": True, "status": None, "feedAt": NOW}]
        self.assertEqual(self.act(nodes), [None, None, None, None])

    def test_a_live_flag_from_a_paused_feed_is_not_active(self):
        # The feed's `at` is when the scanner last published; more than FEED_STALE_MS (120 s) old, the feed is paused.
        paused = {"key": "r:s", "kind": "r", "live": True, "status": "running", "feedAt": NOW - 300000}
        fresh = {"key": "r:f", "kind": "r", "live": True, "status": "running", "feedAt": NOW - 60000}
        edge_ok = {"key": "r:e", "kind": "r", "live": True, "status": "running", "feedAt": NOW - 120000}
        edge_no = {"key": "r:x", "kind": "r", "live": True, "status": "running", "feedAt": NOW - 120001}
        no_feed = {"key": "r:l", "kind": "r", "live": True, "status": "running"}
        self.assertEqual(self.act([paused, fresh, edge_ok, edge_no, no_feed]),
                         [None, "working", "working", None, "working"])

    def test_the_filter_and_the_halo_use_the_same_rule(self):
        # Active only drops the idle remote pi; it keeps the working one, which pulses.
        g = {"nodes": [
                {"key": "m:devbox", "kind": "m"}, {"key": "s:M", "kind": "s", "parent": "m:devbox"},
                {"key": "p:M1", "kind": "p", "parent": "s:M", "foreground": True, "status": "idle", "live": True},
                {"key": "p:M2", "kind": "p", "parent": "s:M", "foreground": True, "status": "working"}],
             "edges": [["m:devbox", "s:M", "contain"], ["s:M", "p:M1", "contain"], ["s:M", "p:M2", "contain"]]}
        keys = run("console.log(JSON.stringify(S.filterGraph(P.g, true, null, P.now).nodes.map((n) => n.key)));",
                   {"g": g, "now": NOW}, FILTER)
        self.assertNotIn("p:M1", keys, "an idle pi is hidden by Active only")
        self.assertIn("p:M2", keys)
        # The halo state is this same rule: null (no halo) for the idle pane, "working" (a pulse) for the working one.
        states = run("console.log(JSON.stringify(P.g.nodes.filter((n) => n.kind === \"p\").map((n) => S.activityOf(n, P.now))));",
                     {"g": g, "now": NOW}, ACTIVITY)
        self.assertEqual(states, [None, "working"])

    def test_the_model_no_longer_marks_a_placed_pane_live(self):
        # The old model set live = "placed in a pane" on every foreground pane, and the halo read it as working.
        code = "\n".join(line.split("//", 1)[0] for line in MAIN.read_text(encoding="utf-8").splitlines())
        self.assertNotIn("live: fg", code)
        self.assertNotIn("live: Boolean(p", code)
        self.assertIn("activityOf", code)

    def test_the_status_rule_is_the_agents_panel_rule_for_every_status_kit_knows(self):
        # kit/kit.js STATUS_MAP is what the Agents panel uses (normStatus). Active = normStatus working or blocked.
        src = Path(ROOT, "kit", "kit.js").read_text(encoding="utf-8")
        block = re.search(r"const STATUS_MAP = \{(.*?)\};", src, re.S).group(1)
        table = dict(re.findall(r'(\w+):\s*"(\w+)"', block))
        self.assertGreater(len(table), 10)
        r = run("console.log(JSON.stringify(P.keys.map((k) => S.activeStatus(k))));",
                {"keys": list(table) + ["zzz-unknown"]}, ACTIVITY)
        want = [table[k] if table[k] in ("working", "blocked") else None for k in table] + [None]
        self.assertEqual(r, want)



class SiblingLinks(unittest.TestCase):
    """The invisible spring between the panes of one tab (sim.js, filter.js, pure). A sibling link pulls its two panes
    closer than an ordinary link would, it does not count toward a node's degree or size, a hover never reaches across
    it, and Local counts a pane's siblings as neighbours. main.js does not draw it."""

    def settled_distance(self, edges):
        nodes = [{"key": "s:A", "kind": "s"}, {"key": "p:1", "kind": "p", "parent": "s:A"}, {"key": "p:2", "kind": "p", "parent": "s:A"}]
        return run("""
            const sim = S.createSim();
            S.sync(sim, { nodes: P.nodes, edges: P.edges }, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            const a = sim.pos.get("p:1"), b = sim.pos.get("p:2");
            console.log(JSON.stringify({ d: Math.hypot(a.x - b.x, a.y - b.y), r: a.r }));""",
                   {"nodes": nodes, "edges": edges, "W": W, "H": H}, SIM)

    def test_a_sibling_link_pulls_its_two_panes_closer_than_a_plain_link_would(self):
        pair = [{"key": "p:1", "kind": "p"}, {"key": "p:2", "kind": "p"}]
        def dist(kind):
            return run("""
                const sim = S.createSim();
                S.sync(sim, { nodes: P.nodes, edges: [["p:1", "p:2", P.kind]] }, S.QUARTZ.global, P.W, P.H);
                S.settle(sim, 5000);
                const a = sim.pos.get("p:1"), b = sim.pos.get("p:2");
                console.log(JSON.stringify(Math.hypot(a.x - b.x, a.y - b.y)));""",
                       {"nodes": pair, "kind": kind, "W": W, "H": H}, SIM)
        self.assertLess(dist("sibling"), dist("link"), "the sibling spring is the shorter one")

    def test_a_sibling_link_is_not_counted_in_a_nodes_degree_or_size(self):
        r = self.settled_distance([["s:A", "p:1", "contain"], ["s:A", "p:2", "contain"], ["p:1", "p:2", "sibling"]])
        self.assertAlmostEqual(r["r"], 2 + 1 ** 0.5, places=6, msg="degree 1 (the contain link only)")

    def test_a_hover_does_not_reach_across_a_sibling_link(self):
        out = run('console.log(JSON.stringify([...S.hoverSet([["p:1", "p:2", "sibling"], ["s:A", "p:1", "contain"]], "p:1")].sort()));', {}, SIM)
        self.assertEqual(out, ["p:1", "s:A"])

    def test_local_counts_a_pane_s_siblings_as_neighbours(self):
        g = {"nodes": [{"key": "s:A", "kind": "s"}, {"key": "p:1", "kind": "p", "parent": "s:A"},
                       {"key": "p:2", "kind": "p", "parent": "s:A"}, {"key": "p:3", "kind": "p", "parent": "s:A"}],
             "edges": [["s:A", "p:1", "contain"], ["s:A", "p:2", "contain"], ["s:A", "p:3", "contain"], ["p:1", "p:2", "sibling"]]}
        r = run('console.log(JSON.stringify(S.localGraph(P.g, "p:1", 1).nodes.map((n) => n.key).sort()));', {"g": g}, FILTER)
        self.assertIn("p:2", r)

    def test_the_sibling_link_is_not_drawn(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('"sibling"', src, "main.js must name the sibling links it leaves out of the drawing")




def three_machines():
    """Three machines with two spaces of two panes each, and two machines with nothing under them (spare, sandbox-vm)."""
    nodes, edges = [], []
    for m in ["laptop", "pi", "devbox"]:
        nodes.append({"key": f"m:{m}", "kind": "m"})
        for i in range(2):
            s = f"s:{m}{i}"
            nodes.append({"key": s, "kind": "s", "parent": f"m:{m}"}); edges.append([f"m:{m}", s, "contain"])
            for k in range(2):
                p = f"p:{m}{i}{k}"
                nodes.append({"key": p, "kind": "p", "parent": s}); edges.append([s, p, "contain"])
    for m in ["spare", "sandbox-vm"]:
        nodes.append({"key": f"m:{m}", "kind": "m"})
    return {"nodes": nodes, "edges": edges}


class MachineSpacing(unittest.TestCase):
    """The push between machines (sim.js): machines and spaces repel less than panes, a weak pull keeps the disconnected
    machines near the middle. Bounds from the Quartz-default graph before this change: machines averaged 296 px apart
    (link distance 30); the isolated machines sat 180 px out, the connected drawing's radius was 201 px."""

    def settled(self):
        return run("""
            const sim = S.createSim();
            S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            const pos = (k) => sim.pos.get(k);
            const machines = P.g.nodes.filter((n) => n.kind === "m").map((n) => n.key);
            const iso = ["m:spare", "m:sandbox-vm"];
            const conn = machines.filter((k) => !iso.includes(k));
            let sum = 0, c = 0;
            for (let i = 0; i < conn.length; i++) for (let j = i + 1; j < conn.length; j++) {
              const a = pos(conn[i]), b = pos(conn[j]); sum += Math.hypot(a.x - b.x, a.y - b.y); c++;
            }
            // The drawing: every connected node (machines, spaces, panes), not only the machines.
            const all = P.g.nodes.filter((n) => !iso.includes(n.key) && !n.key.startsWith("m:spare") && !n.key.startsWith("m:sandbox")).map((n) => pos(n.key));
            const mx = all.reduce((s, p) => s + p.x, 0) / all.length, my = all.reduce((s, p) => s + p.y, 0) / all.length;
            const R = Math.max(...all.map((p) => Math.hypot(p.x - mx, p.y - my)));
            const isoD = iso.map((k) => Math.hypot(pos(k).x - mx, pos(k).y - my));
            console.log(JSON.stringify({ meanMachine: sum / c, R, isoD }));""",
                   {"g": three_machines(), "W": W, "H": H}, SIM)

    def test_machines_average_under_60_percent_of_the_old_290_px_apart(self):
        self.assertLess(self.settled()["meanMachine"], 0.6 * 296)

    def test_isolated_machines_sit_inside_the_drawing_radius_nearer_the_middle(self):
        r = self.settled()
        for d in r["isoD"]:
            self.assertLess(d, 0.75 * r["R"], "an isolated machine sits near the middle, not at the rim")


# ---------------------------------------------------------------- notes and artifacts (touch_shape.js, filter.js)
def touch(path, op="read", at=1000, **extra):
    return {"path": path, "op": op, "at": at, **extra}


VAULT = "/srv/people/vault"
HOME = "/srv/people"


def shape(touches, **opts):
    """touchShape over the touches given, with the graph's agent nodes resolved as the mod does (term -> its pane)."""
    o = {"vault": VAULT, "home": HOME, "notes": True, "artifacts": True, "resolve": {"term:t1": "p:A1a", "term:t2": "p:B1a",
         "c:local:a1": "c:local:a1"}, **opts}
    return run('console.log(JSON.stringify(S.touchShape(P.t, P.o)));', {"t": touches, "o": o}, TOUCH)


class TouchSwitches(unittest.TestCase):
    """Notes and Artifacts: two switches per view, off by default, saved per view like Active only."""

    def test_both_switches_are_off_in_both_views_with_nothing_saved(self):
        r = run('console.log(JSON.stringify(["local","global"].map((v) => [S.touchOn(S.touchState(null), v, "notes"), S.touchOn(S.touchState(null), v, "artifacts")])));', {}, FILTER)
        self.assertEqual(r, [[False, False], [False, False]])

    def test_setting_one_view_one_switch_leaves_the_others_alone(self):
        r = run('const s = S.setTouch(S.touchState(null), "local", "notes", true); console.log(JSON.stringify([S.touchOn(s, "local", "notes"), S.touchOn(s, "local", "artifacts"), S.touchOn(s, "global", "notes"), s]));', {}, FILTER)
        self.assertEqual(r[:3], [True, False, False])
        self.assertEqual(r[3], {"local": {"notes": True, "artifacts": False}, "global": {"notes": False, "artifacts": False}})

    def test_a_saved_state_is_read_back_and_a_bad_one_is_off(self):
        r = run('console.log(JSON.stringify([S.touchOn(S.touchState({local:{notes:true}, global:"x"}), "local", "notes"), S.touchOn(S.touchState({global:{artifacts:true}}), "global", "artifacts"), S.touchOn(S.touchState("junk"), "global", "notes")]));', {}, FILTER)
        self.assertEqual(r, [True, True, False])


class TouchShape(unittest.TestCase):
    """touchShape: the notes and artifacts an agent touched, as graph nodes linked to the agents' nodes."""

    def test_switches_off_add_no_nodes_and_no_links(self):
        r = shape({"term:t1": [touch(f"{VAULT}/n.md", "read")], "c:local:a1": [touch("/srv/out.txt", "create")]}, notes=False, artifacts=False)
        self.assertEqual(r, {"nodes": [], "edges": []})

    def test_notes_on_shows_a_note_node_linked_to_the_agent_by_its_op(self):
        r = shape({"term:t1": [touch(f"{VAULT}/notes/Idea.md", "read"), touch(f"{VAULT}/notes/Plan.md", "edit")]}, artifacts=False)
        self.assertEqual(sorted(n["label"] for n in r["nodes"]), ["Idea", "Plan"])
        self.assertTrue(all(n["kind"] == "n" for n in r["nodes"]))
        ops = {e[1]: e[3] for e in r["edges"]}
        self.assertEqual(ops[f"note:{VAULT}/notes/Idea.md"], "read")
        self.assertEqual(ops[f"note:{VAULT}/notes/Plan.md"], "edit")
        self.assertTrue(all(e[0] == "p:A1a" and e[2] == "touch" for e in r["edges"]))

    def test_a_shared_note_is_one_node_with_a_link_from_each_agent(self):
        r = shape({"term:t1": [touch(f"{VAULT}/shared.md", "read")], "term:t2": [touch(f"{VAULT}/shared.md", "edit")]}, artifacts=False)
        self.assertEqual(len(r["nodes"]), 1)
        self.assertEqual(sorted([e[0], e[3]] for e in r["edges"]), [["p:A1a", "read"], ["p:B1a", "edit"]])

    def test_an_artifact_publication_is_one_node_keyed_by_its_artifact_id(self):
        pub = touch("/store/files/cov-ab12/v2", "publish", 9, artifact={"id": "cov-ab12", "title": "Coverage", "v": 2})
        r = shape({"term:t1": [pub], "term:t2": [pub]})
        self.assertEqual([n["key"] for n in r["nodes"]], ["art:cov-ab12"])
        self.assertEqual(r["nodes"][0]["kind"], "a")
        self.assertEqual(r["nodes"][0]["label"], "Coverage")
        self.assertEqual(len(r["edges"]), 2)

    def test_an_artifact_publication_node_keeps_its_artifact_so_a_click_opens_it_not_an_editor(self):
        pub = touch("/store/files/cov-ab12/v2", "publish", 9, artifact={"id": "cov-ab12", "title": "Coverage", "v": 2})
        node = shape({"term:t1": [pub]})["nodes"][0]
        self.assertEqual(node["artifact"]["id"], "cov-ab12")

    def test_a_plain_file_node_has_no_artifact(self):
        node = shape({"c:local:a1": [touch("/srv/out.txt", "create")]}, notes=False)["nodes"][0]
        self.assertIsNone(node.get("artifact"))

    def test_a_written_file_outside_the_vault_is_an_artifact_node(self):
        r = shape({"c:local:a1": [touch("/srv/out/chart.svg", "write")]}, notes=False)
        self.assertEqual([(n["kind"], n["label"]) for n in r["nodes"]], [("a", "chart.svg")])
        self.assertEqual(r["edges"][0][:2], ["c:local:a1", "file:/srv/out/chart.svg"])

    def test_with_home_but_no_vault_the_agents_own_state_is_not_an_artifact(self):
        r = shape({"c:local:a1": [touch(f"{HOME}/.claude/todo.json", "write"), touch(f"{HOME}/.pi/s.json", "write"),
                                  touch(f"{HOME}/.herdr/x", "create"), touch("/srv/out/chart.svg", "write")]}, vault=None)
        self.assertEqual([n["label"] for n in r["nodes"]], ["chart.svg"])

    def test_a_remote_agents_plain_file_is_dropped_but_its_publication_kept(self):
        """A remote file's path is not this computer's: keyed by path alone it would merge with a local file and a click
        would open the local one. Publications are keyed by artifact id, so they stay."""
        pub = touch("/store/files/cov-ab12/v2", "publish", 9, artifact={"id": "cov-ab12", "title": "Coverage", "v": 2})
        r = shape({"c:pi:r1": [touch("/srv/out/chart.svg", "write"), pub], "term:pi/t9": [touch("/srv/out/b.txt", "create")]},
                  resolve={"c:pi:r1": "c:pi:r1", "term:pi/t9": "p:R1a"})
        self.assertEqual([n["key"] for n in r["nodes"]], ["art:cov-ab12"])

    def test_notes_are_off_with_no_vault_even_when_switched_on(self):
        r = shape({"term:t1": [touch(f"{VAULT}/n.md", "read")]}, vault=None, artifacts=False)
        self.assertEqual(r["nodes"], [])

    def test_a_danger_note_never_becomes_a_node(self):
        r = shape({"term:t1": [touch(f"{VAULT}/danger/keys.md", "write"), touch(f"{VAULT}/.obsidian/app.json", "write")]})
        self.assertEqual(r, {"nodes": [], "edges": []})

    def test_an_agent_that_is_not_in_the_graph_links_nothing(self):
        r = shape({"term:gone": [touch(f"{VAULT}/n.md", "read")]})
        self.assertEqual(r, {"nodes": [], "edges": []})

    def test_node_ids_are_stable_whatever_the_order_of_the_rows(self):
        a = shape({"term:t1": [touch(f"{VAULT}/a.md"), touch(f"{VAULT}/b.md")], "term:t2": [touch(f"{VAULT}/b.md")]})
        b = shape({"term:t2": [touch(f"{VAULT}/b.md")], "term:t1": [touch(f"{VAULT}/b.md"), touch(f"{VAULT}/a.md")]})
        self.assertEqual(sorted(n["key"] for n in a["nodes"]), sorted(n["key"] for n in b["nodes"]))
        self.assertEqual(sorted(n["key"] for n in a["nodes"]), [f"note:{VAULT}/a.md", f"note:{VAULT}/b.md"])

    def test_one_agent_touching_one_note_twice_is_one_link_with_the_stronger_op(self):
        r = shape({"term:t1": [touch(f"{VAULT}/a.md", "read"), touch(f"{VAULT}/a.md", "edit")]})
        self.assertEqual([e[3] for e in r["edges"]], ["edit"])


class TouchLinks(unittest.TestCase):
    def test_a_read_link_is_fainter_than_an_edit_link(self):
        r = run('console.log(JSON.stringify([S.touchAlpha("read"), S.touchAlpha("edit"), S.touchAlpha("create"), S.touchAlpha("publish")]));', {}, SIM)
        self.assertLess(r[0], r[1])
        self.assertEqual(r[1], r[2])
        self.assertEqual(r[2], r[3])
        self.assertTrue(all(0 < x < 1 for x in r))


class EditorArgv(unittest.TestCase):
    """shape.js editorArgv: the command that opens a plain-file artifact in an editor pane. The `editor` list in
    obsidian.json (the same one the Notes mod honours: a command and its arguments) wins; without one, $VISUAL, then
    $EDITOR, then the first of nvim, vim, nano, vi that is installed."""

    def argv(self, editor, path="/work/out.txt"):
        return run("console.log(JSON.stringify(S.editorArgv(P.editor, P.path)));", {"editor": editor, "path": path}, SHAPE)

    def test_the_configured_editor_gets_the_path_last(self):
        self.assertEqual(self.argv(["code", "--wait"]), ["code", "--wait", "/work/out.txt"])

    def test_without_one_the_shell_picks_visual_editor_then_what_is_installed(self):
        a = self.argv(None)
        self.assertEqual(a[:2], ["sh", "-c"])
        self.assertIn("VISUAL", a[2])
        self.assertIn("nvim vim nano vi", a[2])
        self.assertEqual(a[-2:], ["editor", "/work/out.txt"])

    def test_an_empty_or_malformed_list_is_not_an_editor(self):
        for bad in ([], "code", [1, 2], ["code", 3], {"a": 1}):
            self.assertEqual(self.argv(bad)[:2], ["sh", "-c"], repr(bad))

    def test_main_reads_the_editor_with_the_vault_and_uses_editorArgv(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("editorArgv(this.editor, n.path)", src)
        self.assertIn("own.editor", src)


class FrameShapes(unittest.TestCase):
    """Machines and spaces are the graph's fixed-size anchors: round accent dots like every other node (no polygon
    shapes), with stronger accent tones (0.92 and 0.78) and always-shown labels."""

    def radius(self, degree, kind):
        return run("console.log(JSON.stringify(S.radiusOf(P.d, P.kind)));", {"d": degree, "kind": kind}, SIM)

    def test_machines_and_spaces_have_a_fixed_size_whatever_hangs_off_them(self):
        for kind in ("m", "s"):
            self.assertEqual(self.radius(1, kind), self.radius(40, kind), kind)
        self.assertLess(self.radius(1, "s"), 6)
        self.assertLessEqual(self.radius(1, "m"), 6)

    def paint(self, kind):
        return run("console.log(JSON.stringify(S.framePaint(P.kind)));", {"kind": kind}, SHAPE)

    def test_every_kind_is_a_unit_scale_round_dot_with_no_polygon_shape(self):
        for kind in ("m", "s", "p", "r", "c", "h", "n", "a"):
            fp = self.paint(kind)
            self.assertIsNone(fp.get("shape"), kind)
            self.assertEqual(fp["scale"], 1, kind)
        has_points = run('console.log(JSON.stringify("shapePoints" in S));', {}, SHAPE)
        self.assertFalse(has_points, "polygon helpers are gone from shape.js")

    def test_machines_and_spaces_are_drawn_stronger_and_always_labelled(self):
        m, s, p = self.paint("m"), self.paint("s"), self.paint("p")
        self.assertTrue(m["label"] and s["label"])
        self.assertFalse(p["label"])
        self.assertEqual(m["tone"], 0.92)
        self.assertEqual(s["tone"], 0.78)
        for kind in ("p", "r", "c", "h", "n", "a"):
            self.assertIsNone(self.paint(kind)["tone"], kind)

    def test_every_node_renders_as_a_round_dot_with_no_polygons_or_squares(self):
        src = MAIN.read_text(encoding="utf-8")
        render = src[src.index("  render(cx) {"):]
        self.assertIn("framePaint(n.kind)", render)
        self.assertIn(".rounded_full()", render)
        self.assertNotIn("add_polygon(", src)
        self.assertNotIn("shapePoints", src)
        self.assertNotIn('n.kind === "a" ? dot', render)


class AccentPaletteAndHoverStyle(unittest.TestCase):
    """Obsidian-style graph presentation: clean theme-accent opacity palette (no per-program rainbow hues), 1 px canvas
    cutout borders (foreground on hover/selection), status-coloured halos (working/blocked), 1.5 px accent-lit incident
    links on hover, and chrome pill-backed hover/selection labels."""

    def tone(self, r):
        return run("console.log(JSON.stringify(S.dotTone(P.r)));", {"r": r}, SHAPE)

    def test_dot_tone_steps_across_leaf_connected_and_hub_radii(self):
        self.assertEqual(self.tone(3), 0.55, "base leaf radius")
        self.assertEqual(self.tone(3.5), 0.55, "up to 3.5 stays at leaf opacity")
        self.assertEqual(self.tone(4.8), 0.75, "connected node above 3.5")
        self.assertEqual(self.tone(6.9), 0.75)
        self.assertEqual(self.tone(7), 0.95, "hub radius >= 7")
        self.assertEqual(self.tone(11), 0.95, "capped hub radius")

    def test_per_program_agent_hues_are_gone(self):
        has_hue = run('console.log(JSON.stringify("agentHue" in S));', {}, SHAPE)
        self.assertFalse(has_hue)
        self.assertNotIn("AGENT_HUES", SHAPE.read_text(encoding="utf-8"))
        self.assertNotIn("agentHue", MAIN.read_text(encoding="utf-8"))

    def test_node_color_uses_accent_opacity_ramp_and_dim_offline_machines(self):
        src = MAIN.read_text(encoding="utf-8")
        body = re.search(r"\n  nodeColor\(t, n, focusKey\) \{([\s\S]*?)\n  \}", src).group(1)
        self.assertIn("n.key === focusKey", body)
        self.assertIn('n.kind === "m" && n.down', body)
        self.assertIn("t.dim", body)
        self.assertIn("activityOf(n, Date.now())", body)
        self.assertIn("framePaint(n.kind)", body)
        self.assertIn("dotTone(", body)
        self.assertIn("alpha(t.accent,", body)
        self.assertNotIn("t.done", body)

    def test_dots_carry_one_pixel_cutout_borders_that_highlight_on_hover_or_selection(self):
        render = MAIN.read_text(encoding="utf-8")[MAIN.read_text(encoding="utf-8").index("  render(cx) {"):]
        self.assertIn(".border_1()", render)
        self.assertRegex(render, r"border_color\([^)]*this\.hover === n\.key[^)]*this\.selected === n\.key[^)]*\?\s*t\.foreground\s*:\s*t\.canvas\)")

    def test_status_halos_use_working_and_blocked_theme_colours(self):
        render = MAIN.read_text(encoding="utf-8")[MAIN.read_text(encoding="utf-8").index("  render(cx) {"):]
        self.assertIn("haloDrawAlpha(", render)
        self.assertRegex(render, r'st === "blocked"\s*\?\s*t\.blocked\s*:\s*t\.working')
        self.assertIn("alpha(haloColor, ha)", render)

    def test_hovered_incident_links_draw_at_1_5px_in_accent_above_1px_muted_links(self):
        render = MAIN.read_text(encoding="utf-8")[MAIN.read_text(encoding="utf-8").index("  render(cx) {"):]
        muted_idx = render.index("alpha(t.muted, b.alpha)")
        accent_idx = render.index("alpha(t.accent, b.alpha)")
        nodes_idx = render.index(".children(nodes)")
        self.assertLess(muted_idx, accent_idx, "1.5 px accent hover links are batched after 1 px muted links")
        self.assertLess(accent_idx, nodes_idx, "links stay under the nodes")
        self.assertRegex(render, r"layer\([^,]+,\s*b\.segs,\s*1,\s*alpha\(t\.muted,\s*b\.alpha\)\)")
        self.assertRegex(render, r"layer\([^,]+,\s*b\.segs,\s*1\.5,\s*alpha\(t\.accent,\s*b\.alpha\)\)")

    def test_hovered_and_selected_labels_render_in_a_centered_chrome_pill(self):
        render = MAIN.read_text(encoding="utf-8")[MAIN.read_text(encoding="utf-8").index("  render(cx) {"):]
        self.assertRegex(render, r"\(this\.hover != null && this\.near\.has\(n\.key\)\)\s*\|\|\s*this\.selected === n\.key")
        self.assertIn(".justify_center()", render)
        self.assertIn(".max_w(lw).truncate().px(4).rounded(3).bg(alpha(t.chrome, 0.9))", render)


class ToolbarRows(unittest.TestCase):
    """shape.js toolbarRows: the toolbar is Local/Global/Active only, Notes/Artifacts and the zoom buttons, about 415 px in
    one row. A narrower panel (the right sidebar is about 320 px) puts the zoom buttons on a second row instead of
    cutting them off."""

    def rows(self, w):
        return run("console.log(JSON.stringify([S.toolbarRows(P.w), S.toolbarBottom(S.toolbarRows(P.w))]));", {"w": w}, SHAPE)

    def test_a_wide_panel_keeps_one_row(self):
        self.assertEqual(self.rows(800)[0], 1)
        self.assertEqual(self.rows(430)[0], 1)

    def test_a_narrow_panel_uses_two_rows(self):
        self.assertEqual(self.rows(320)[0], 2)
        self.assertEqual(self.rows(429)[0], 2)

    def test_the_bottom_edge_clears_every_row_of_buttons(self):
        one, two = self.rows(800)[1], self.rows(320)[1]
        self.assertGreaterEqual(one, 32)        # top 6 + 26 high
        self.assertGreaterEqual(two, one + 26)  # a second row of the same height
        self.assertEqual(self.rows(0)[0], 1, "before the first layout the width is 0: no second row")

    def test_main_uses_them_for_the_layout_and_for_hit_testing(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("toolbarRows(this.W)", src)
        self.assertIn("toolbarBottom(toolbarRows(this.W))", src)


class ShownGraph(unittest.TestCase):
    """What a view shows (filter.js shownGraph). Global with Active only shows what is active, whichever pane has focus:
    clicking something that opens a pane moves focus, and the graph must not change with it. Local is built around the
    focus, so there it stays."""

    def graph(self):
        N = [
            {"key": "m:laptop", "kind": "m"}, {"key": "s:A", "kind": "s", "parent": "m:laptop"},
            {"key": "p:A1a", "kind": "p", "parent": "s:A", "status": "working", "foreground": True},
            {"key": "p:A1b", "kind": "p", "parent": "s:A", "status": "idle", "foreground": True},
            {"key": "art:x", "kind": "a", "label": "x"},
        ]
        E = [["m:laptop", "s:A", "contain"], ["s:A", "p:A1a", "contain"], ["s:A", "p:A1b", "contain"],
             ["p:A1b", "art:x", "touch", "create"]]
        return {"nodes": N, "edges": E}

    def shown(self, mode, active, focus):
        return run('const r = S.shownGraph(P.g, { mode: P.mode, focus: P.focus, depth: 1, active: P.active, now: 0 });'
                   'console.log(JSON.stringify({n: r.nodes.map((x) => x.key), focus: r.focus}));',
                   {"g": self.graph(), "mode": mode, "active": active, "focus": focus}, FILTER)

    def test_global_active_only_ignores_an_idle_focus_and_its_artifact(self):
        r = self.shown("global", True, "p:A1b")
        self.assertNotIn("p:A1b", r["n"])
        self.assertNotIn("art:x", r["n"])
        self.assertIn("p:A1a", r["n"])

    def test_global_active_only_is_the_same_whichever_pane_has_focus(self):
        self.assertEqual(self.shown("global", True, "p:A1b")["n"], self.shown("global", True, "p:A1a")["n"])
        self.assertEqual(self.shown("global", True, "p:A1b")["n"], self.shown("global", True, None)["n"])

    def test_global_has_no_focus_node_so_nothing_is_tinted_or_redrawn_when_focus_moves(self):
        for active in (True, False):
            for focus in ("p:A1a", "p:A1b", None):
                self.assertIsNone(self.shown("global", active, focus)["focus"], (active, focus))

    def test_local_marks_the_focus_when_it_is_drawn(self):
        self.assertEqual(self.shown("local", True, "p:A1a")["focus"], "p:A1a")
        self.assertIsNone(self.shown("local", True, "p:Z")["focus"])

    def test_local_active_only_keeps_an_idle_focus_and_its_artifact(self):
        r = self.shown("local", True, "p:A1b")
        self.assertIn("p:A1b", r["n"])
        self.assertIn("art:x", r["n"])
        self.assertEqual(r["focus"], "p:A1b")

    def copy(self, mode):
        return run("console.log(JSON.stringify(S.emptyCopy(P.mode)));", {"mode": mode}, FILTER)

    def test_the_empty_graphs_say_what_they_are_waiting_for(self):
        self.assertEqual(self.copy("global"), {"title": "Nothing to draw", "body": "Machines, spaces, panes and agents appear here."})
        r = self.copy("local")
        self.assertEqual(r["title"], "No session focused")
        self.assertIn("Switch to Global", r["body"])

    def test_main_builds_the_view_through_shownGraph(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("shownGraph(", src)
        self.assertNotIn("filterGraph(", src)
        self.assertIn("emptyCopy(this.mode)", src)


class TouchActiveOnly(unittest.TestCase):
    """Active only keeps the notes and artifacts of the agents it keeps, and drops the links to the rest."""

    def graph(self):
        N = [
            {"key": "m:laptop", "kind": "m"}, {"key": "s:A", "kind": "s", "parent": "m:laptop"},
            {"key": "p:A1a", "kind": "p", "parent": "s:A", "status": "working", "foreground": True},
            {"key": "p:A1b", "kind": "p", "parent": "s:A", "status": "idle", "foreground": True},
            {"key": "note:n", "kind": "n", "label": "n"}, {"key": "note:idle", "kind": "n", "label": "idle"},
            {"key": "art:x", "kind": "a", "label": "x"},
        ]
        E = [["m:laptop", "s:A", "contain"], ["s:A", "p:A1a", "contain"], ["s:A", "p:A1b", "contain"],
             ["p:A1a", "note:n", "touch", "read"], ["p:A1b", "note:n", "touch", "edit"],
             ["p:A1b", "note:idle", "touch", "read"], ["p:A1b", "art:x", "touch", "create"]]
        return {"nodes": N, "edges": E}

    def keep(self, on):
        return run('const r = S.filterGraph(P.g, P.on, "p:A1a", 0); console.log(JSON.stringify({n: r.nodes.map((x) => x.key), e: r.edges}));',
                   {"g": self.graph(), "on": on}, FILTER)

    def test_active_on_keeps_a_note_an_active_agent_touches_and_drops_the_idle_ones(self):
        r = self.keep(True)
        self.assertIn("note:n", r["n"])
        self.assertNotIn("note:idle", r["n"])
        self.assertNotIn("art:x", r["n"])

    def test_the_link_from_an_idle_agent_to_a_kept_note_is_dropped(self):
        r = self.keep(True)
        self.assertEqual([e for e in r["e"] if e[1] == "note:n"], [["p:A1a", "note:n", "touch", "read"]])

    def test_active_off_keeps_every_note_and_artifact(self):
        r = self.keep(False)
        self.assertEqual(sorted(r["n"]), sorted(["m:laptop", "s:A", "p:A1a", "p:A1b", "note:n", "note:idle", "art:x"]))


class TouchMain(unittest.TestCase):
    def test_main_wires_the_two_switches_the_vault_gate_and_the_clicks(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn('"Notes"', src)
        self.assertIn('"Artifacts"', src)
        self.assertIn("Set your vault in Settings", src)
        self.assertIn('from "./touch_shape.js"', src)
        self.assertIn('"obsidian.show"', src)
        self.assertIn('"herdr-artifact", ["open"', src)

    def test_home_is_known_even_when_obsidian_json_cannot_be_read(self):
        """homeDir filters the agents' own state (~/.claude, ~/.pi, ~/.herdr) out of the artifacts; it must not hang on
        the vault file being readable."""
        src = MAIN.read_text(encoding="utf-8")
        init = src[src.index("  init(_p, cx) {"):src.index("\n  }\n", src.index("  init(_p, cx) {"))]
        self.assertIn("this.homeDir = userHome()", init)
        vault = src[src.index("  readVault(cx) {"):src.index("\n  }\n", src.index("  readVault(cx) {"))]
        self.assertNotIn("this.homeDir = ", vault)

    def test_the_mod_reads_the_vault_setting_and_never_writes_it(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("obsidian.json", src)
        self.assertNotIn("writeTextFile", src)


class TouchLocal(unittest.TestCase):
    """Local: a note is one hop from the agent that touches it, so a shared note brings its other agent in at depth 2."""

    def graph(self):
        N = [{"key": "s:A", "kind": "s"}, {"key": "p:A1a", "kind": "p", "parent": "s:A"}, {"key": "p:B1a", "kind": "p", "parent": "s:A"},
             {"key": "note:shared", "kind": "n", "label": "shared"}]
        E = [["s:A", "p:A1a", "contain"], ["s:A", "p:B1a", "contain"],
             ["p:A1a", "note:shared", "touch", "read"], ["p:B1a", "note:shared", "touch", "edit"]]
        return {"nodes": N, "edges": E}

    def keys(self, depth):
        r = run('console.log(JSON.stringify(S.localGraph(P.g, "p:A1a", P.d)));', {"g": self.graph(), "d": depth}, FILTER)
        return {n["key"] for n in r["nodes"]}

    def test_the_focus_note_is_one_hop_away(self):
        self.assertIn("note:shared", self.keys(1))
        self.assertNotIn("p:B1a", self.keys(1))

    def test_the_other_agent_of_a_shared_note_is_two_hops_away(self):
        self.assertIn("p:B1a", self.keys(2))


class NodeColors(unittest.TestCase):
    """Every colour a node is drawn in is a Herdr theme colour (herdr.d.ts theme()): a name it lacks is nil, and the
    render fails with "expected a string, got nil"."""
    THEME = set("background surface canvas chrome popover raised hover selected border input foreground muted dim accent "
                "accent_foreground solid solid_foreground selection working blocked done idle unknown".split()) | {
                f"ansi{i}" for i in range(16)}

    def test_node_colors_are_theme_colors(self):
        src = Path(ROOT, "mods", "ob-graph", "main.js").read_text(encoding="utf-8")
        body = re.search(r"\n  nodeColor\(t, n, focusKey\) \{([\s\S]*?)\n  \}", src).group(1)
        names = set(re.findall(r"\bt\.([a-z_0-9]+)", body))
        self.assertTrue(names)
        self.assertEqual(names - self.THEME, set())


class AsyncModel(unittest.TestCase):
    """Herdr's way: render draws what is cached. The model (spaces, panes, sub-agents, touched files) is rebuilt by a
    timer at most every REBUILD_MS when render has seen a change, and redraws only when the graph changed; a command
    (switch, mode, depth) rebuilds at once. Nodes may appear up to REBUILD_MS late."""

    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")
        self.render = self.src[self.src.index("  render(cx) {"):]

    def test_render_never_builds_the_model_or_syncs_the_simulation(self):
        self.assertNotIn("this.model()", self.render)
        self.assertNotIn("sync(this.sim", self.render)
        self.assertNotIn("filterGraph(", self.render)

    def test_render_only_marks_the_model_stale(self):
        self.assertIn("this.stale = true", self.render)

    def test_a_timer_rebuilds_a_stale_model_and_redraws_only_on_a_change(self):
        self.assertRegex(self.src, r"cx\.timer\.every\(REBUILD_MS, \(cx\) => \{[^}]*this\.stale[^}]*this\.rebuild\(\)[^}]*cx\.notify\(\)")

    def test_a_command_rebuilds_at_once(self):
        self.assertRegex(self.src, r"command\(c, cx\) \{\s*this\.dirty = true;")


class LinkBatches(unittest.TestCase):
    """Links are drawn as a few paths, one per alpha step, not one full-size layer per link."""

    def test_links_with_close_alpha_share_one_batch(self):
        r = run("console.log(JSON.stringify(S.linkBatches(P)));", [
            {"seg": [[0, 0], [1, 1]], "alpha": 0.35}, {"seg": [[1, 1], [2, 2]], "alpha": 0.36},
            {"seg": [[2, 2], [3, 3]], "alpha": 1}, {"seg": [[3, 3], [4, 4]], "alpha": 0}])
        self.assertEqual(len(r), 2, "0.35 and 0.36 share a step; alpha 0 is not drawn")
        self.assertEqual(sorted(len(b["segs"]) for b in r), [1, 2])

    def test_render_draws_link_batches(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("linkBatches(", src)


class EdgeLookup(unittest.TestCase):
    """A link's rest alpha is read per link per frame: a lookup by link id built once per rebuild, not a scan of every
    edge (that is O(E^2) a frame)."""

    def setUp(self):
        self.src = MAIN.read_text(encoding="utf-8")

    def body(self, head):
        i = self.src.index(head)
        return self.src[i:self.src.index("\n  }\n", i)]

    def test_rest_alpha_looks_the_edge_up_in_a_map_and_never_scans_the_edges(self):
        body = self.body("  restAlpha(id) {")
        self.assertNotIn("edges.find", body)
        self.assertIn("edgeOf.get(", body)

    def test_rebuild_builds_the_lookup_once_keyed_by_link_id(self):
        body = self.body("  rebuild() {")
        self.assertRegex(body, r"edgeOf[^;]*new Map\(")
        self.assertIn("linkId(", body)


class DragOutside(unittest.TestCase):
    """A node drag released outside the panel gets no mouse up: the pointer leaving the panel ends it (release, so
    alphaTarget drops and the loop cools and stops), as a pan does."""

    def setUp(self):
        src = MAIN.read_text(encoding="utf-8")
        i = src.index(".on_hover((h, cx) => {")
        self.hover = src[i:src.index("\n      })", i)]
        i = src.index("  endDrag(cx) {")
        self.end = src[i:src.index("\n  }\n", i)]

    def test_leaving_the_panel_ends_a_node_drag_or_pan(self):
        self.assertIn("this.endDrag(cx)", self.hover)

    def test_ending_a_drag_releases_the_node_and_restarts_the_loop(self):
        self.assertIn("this.nodeDrag = null", self.end)
        self.assertIn("this.drag = null", self.end)
        self.assertIn("release(this.sim)", self.end)
        self.assertIn("this.startLoop()", self.end)


class MenuCopy(unittest.TestCase):
    def test_a_sub_agent_opens_in_outline_the_panel_that_replaced_subagents(self):
        src = MAIN.read_text(encoding="utf-8")
        i = src.index("  menu(key) {")
        body = src[i:src.index("\n  }\n", i)]
        self.assertIn('"Open in Outline"', body)
        self.assertNotIn("Subagents", body)


class EmptyCopy(unittest.TestCase):
    def test_the_empty_state_names_only_node_kinds_the_graph_has(self):
        """There is no tab node any more (shape.js): the empty graph must not promise tabs."""
        for mode in ("global", "local"):
            body = run("console.log(JSON.stringify(S.emptyCopy(P.mode).body));", {"mode": mode}, FILTER)
            self.assertNotIn("tab", body.lower(), mode)
            self.assertIn("agent", body, mode) if mode == "global" else None


def run_obc(body):
    """Import mods/ob-graph/obc.js in node with real followTarget and mutable herdr/kit stubs, run `body`, return JSON."""
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory(prefix="ob-graph-obc-") as folder:
        src = OBC.read_text(encoding="utf-8").replace('from "herdr"', 'from "./herdr.js"')
        Path(folder, "obc.js").write_text(src, encoding="utf-8")
        for kname in ("provider.js", "fuzzy.js"):
            shutil.copy(Path(ROOT, "kit", kname), Path(folder, kname))
        Path(folder, "herdr.js").write_text(
            "const st = { terminals: [], agents: [], panes: [], spaces: [], focused: null, shared: {} };\n"
            "export const __set = (patch) => Object.assign(st, patch);\n"
            "export const terminals = () => st.terminals;\n"
            "export const agents = () => st.agents;\n"
            "export const panes = () => st.panes;\n"
            "export const spaces = () => st.spaces;\n"
            "export const focused = () => st.focused;\n"
            "export const shared = (k) => st.shared[k];\n"
            "export const setShared = (k, v) => { st.shared[k] = v; };\n"
            "export const run = () => null;\n"
            "export const openOverlay = () => null;\n"
            "export const notify = () => null;\n",
            encoding="utf-8",
        )
        kit = ["machineOf", "tabLabel", "paneName", "dur", "ago", "fmtTokens", "fmtCost", "normStatus", "copyText", "base", "hasMod",
               "parentAddrOf", "isChildTerminalOf", "getHidden", "updateHidden", "patchHidden", "normHidden", "isSpaceHidden", "isTabHidden"]
        Path(folder, "kit.js").write_text(
            f"export {{ followTarget }} from {json.dumps(FOLLOW.as_uri())};\n"
            'import { makeProvider } from "./provider.js";\n'
            'export const MOD = "ob-graph";\n'
            "const st = { feed: null, records: {} };\n"
            "export const __setKit = (patch) => Object.assign(st, patch);\n"
            + "".join(f"export const {n} = () => null;\n" for n in kit)
            + "export const feed = () => st.feed;\n"
            + "export const liveRecords = () => new Map(Object.entries(st.records));\n"
            + 'export const provider = makeProvider({ feed, exec: async () => ({ code: 1 }), readTextFile: async () => null, appHome: () => "/tmp" });\n',
            encoding="utf-8",
        )
        code = (
            f"{NO_TIMERS}\n"
            f'import * as H from "{Path(folder, "herdr.js").as_uri()}";\n'
            f'import * as K from "{Path(folder, "kit.js").as_uri()}";\n'
            f'import * as O from "{Path(folder, "obc.js").as_uri()}";\n'
            f"console.log(JSON.stringify((() => {{ {body} }})()));"
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr.strip() or "node failed")
        return json.loads(out.stdout)


class GraphObc(unittest.TestCase):
    """mods/ob-graph/obc.js follow and sub-agent liveness rules match ob-outline."""

    def test_inspected_keeps_last_agent_when_focus_moves_to_side_panel(self):
        r = run_obc("""
            H.__set({
              agents: [{ address: "t2" }],
              terminals: [{ address: "t2", state: "live" }, { address: "t4", state: "live" }],
              focused: { pane: "p1", terminal: "t2" },
            });
            const first = O.inspected();
            const follow = H.shared("ob.follow") ?? null;
            H.__set({ focused: { pane: "side", terminal: null } });
            const sidePanel = O.inspected();
            H.__set({ focused: { pane: "p2", terminal: "t4" } });
            const shellPane = O.inspected();
            return { first, follow, sidePanel, shellPane };
        """)
        self.assertEqual(r["first"], {"address": "t2", "pinned": False})
        self.assertEqual(r["follow"], {"subagents": "t2"})
        self.assertEqual(r["sidePanel"], {"address": "t2", "pinned": False})
        self.assertEqual(r["shellPane"], {"address": "t2", "pinned": False})

    def test_claude_all_keeps_live_scan_entry_when_record_is_not_working(self):
        r = run_obc("""
            K.__setKit({
              feed: {
                v: 2,
                providers: { claude: { id: "claude", name: "Claude Code", noun: "Claude agent", caps: ["title", "subagents"] } },
                subagents: [{ key: "local:a1", machine: null, parent: "t2", provider: "claude", id: "a1", type: "Explore", desc: "look", live: true }],
              },
              records: { t2: { a1: { state: "done" } } },
            });
            return O.allSubagents().agents.map((c) => ({ id: c.id, live: c.live, state: c.state }));
        """)
        self.assertEqual(r, [{"id": "a1", "live": True, "state": "done"}])


class OpenArtifact(unittest.TestCase):
    """Clicking an artifact: a herdr-artifact publication runs `herdr-artifact open` (a failed run is shown as a toast,
    since exec resolves on failure too). A plain file opens in an editor pane that finds one even when $VISUAL and
    $EDITOR don't reach the pane and vi isn't installed."""

    def setUp(self):
        src = MAIN.read_text(encoding="utf-8")
        i = src.index("  openArtifact(n) {")
        self.body = src[i:src.index("\n  }\n", i)]
        self.src = src

    def test_publication_runs_herdr_artifact_open_and_reports_a_failed_run(self):
        self.assertIn('exec("herdr-artifact", ["open", n.artifact.id])', self.body)
        self.assertIn("r.code !== 0", self.body)
        self.assertIn("notify(", self.body)
        self.assertNotIn("this.cx", self.body)

    def test_the_editor_falls_back_through_installed_editors(self):
        shape = SHAPE.read_text(encoding="utf-8")
        for e in ("nvim", "vim", "nano", "vi"):
            self.assertIn(e, shape)
        self.assertIn("command -v", shape)
        self.assertIn("editorArgv(", self.body)


def single_machine_radial_graph(extra_machines=()):
    """One active machine with three spaces, panes (including a sibling pair), sub-agents, and a touched note."""
    nodes = [
        {"key": "m:laptop", "kind": "m"},
        {"key": "s:a0", "kind": "s", "parent": "m:laptop"},
        {"key": "s:a1", "kind": "s", "parent": "m:laptop"},
        {"key": "s:a2", "kind": "s", "parent": "m:laptop"},
        {"key": "p:a00", "kind": "p", "parent": "s:a0"},
        {"key": "p:a01", "kind": "p", "parent": "s:a0"},
        {"key": "p:a10", "kind": "p", "parent": "s:a1"},
        {"key": "p:a11", "kind": "p", "parent": "s:a1"},
        {"key": "p:a20", "kind": "p", "parent": "s:a2"},
        {"key": "r:s0", "kind": "r", "parent": "p:a00"},
        {"key": "c:s1", "kind": "c", "parent": "p:a10"},
        {"key": "h:s2", "kind": "h", "parent": "p:a20"},
        {"key": "note:/srv/people/vault/plan.md", "kind": "n"},
    ] + [{"key": f"m:{m}", "kind": "m"} for m in extra_machines]
    edges = [
        ["m:laptop", "s:a0", "contain"],
        ["m:laptop", "s:a1", "contain"],
        ["m:laptop", "s:a2", "contain"],
        ["s:a0", "p:a00", "contain"],
        ["s:a0", "p:a01", "contain"],
        ["p:a00", "p:a01", "sibling"],
        ["s:a1", "p:a10", "contain"],
        ["s:a1", "p:a11", "contain"],
        ["s:a2", "p:a20", "contain"],
        ["p:a00", "r:s0", "link"],
        ["p:a10", "c:s1", "link"],
        ["p:a20", "h:s2", "link"],
        ["p:a10", "note:/srv/people/vault/plan.md", "touch", "edit"],
    ]
    return {"nodes": nodes, "edges": edges}


class CenteredRadialLayout(unittest.TestCase):
    """Concentric radial-center layout (sim.js, main.js): single roots sit at (0, 0) and children radiate outward in
    depth rings; multi-machine roots share an inner hub ring; Local anchors the focused session at (0, 0) and spreads
    BFS hops outward, clearing stale positions on mode or focus switches."""

    def test_single_machine_global_graph_spreads_outward_in_concentric_rings_from_origin(self):
        g = single_machine_radial_graph()
        r = run("""
            const sim = S.createSim();
            S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            const rOf = (k) => { const p = sim.pos.get(k); return Math.hypot(p.x, p.y); };
            const mean = (ks) => ks.reduce((s, k) => s + rOf(k), 0) / ks.length;
            console.log(JSON.stringify({
              machine: rOf("m:laptop"),
              spaces: mean(["s:a0", "s:a1", "s:a2"]),
              panes: mean(["p:a00", "p:a01", "p:a10", "p:a11", "p:a20"]),
              subagents: mean(["r:s0", "c:s1", "h:s2"]),
              note: rOf("note:/srv/people/vault/plan.md"),
            }));
        """, {"g": g, "W": W, "H": H})
        self.assertLess(r["machine"], 15, r)
        self.assertLess(r["machine"], r["spaces"], r)
        self.assertLess(r["spaces"], r["panes"], r)
        self.assertLess(r["panes"], r["subagents"], r)
        self.assertLess(r["panes"], r["note"], r)

    def test_single_active_machine_with_isolated_machines_keeps_center_and_tucks_isolated_inside(self):
        g = single_machine_radial_graph(extra_machines=["spare", "sandbox-vm"])
        r = run("""
            const sim = S.createSim();
            S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            const rOf = (k) => { const p = sim.pos.get(k); return Math.hypot(p.x, p.y); };
            const mean = (ks) => ks.reduce((s, k) => s + rOf(k), 0) / ks.length;
            const iso = ["m:spare", "m:sandbox-vm"];
            const conn = P.g.nodes.filter((n) => !iso.includes(n.key)).map((n) => rOf(n.key));
            console.log(JSON.stringify({
              machine: rOf("m:laptop"),
              spaces: mean(["s:a0", "s:a1", "s:a2"]),
              panes: mean(["p:a00", "p:a01", "p:a10", "p:a11", "p:a20"]),
              R: Math.max(...conn),
              isoR: iso.map(rOf),
            }));
        """, {"g": g, "W": W, "H": H})
        self.assertLess(r["machine"], 18, r)
        self.assertLess(r["machine"], r["spaces"], r)
        self.assertLess(r["spaces"], r["panes"], r)
        for d in r["isoR"]:
            self.assertLess(d, 0.75 * r["R"], r)

    def test_multi_machine_global_graph_places_every_parent_closer_to_origin_than_its_children(self):
        g = three_machines()
        r = run("""
            const sim = S.createSim();
            S.sync(sim, P.g, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            const rOf = (k) => { const p = sim.pos.get(k); return Math.hypot(p.x, p.y); };
            const iso = ["m:spare", "m:sandbox-vm"];
            const pairs = P.g.edges
              .filter(([, , k]) => k === "contain")
              .map(([a, b]) => ({ a, b, ra: rOf(a), rb: rOf(b) }));
            const R = Math.max(...P.g.nodes.filter((n) => !iso.includes(n.key)).map((n) => rOf(n.key)));
            console.log(JSON.stringify({ pairs, R, isoR: iso.map(rOf) }));
        """, {"g": g, "W": W, "H": H})
        for pair in r["pairs"]:
            self.assertLess(pair["ra"], pair["rb"], pair)
        for d in r["isoR"]:
            self.assertLess(d, 0.75 * r["R"], r)

    def test_local_graph_anchors_focus_at_origin_and_spreads_hops_outward(self):
        g = {
            "nodes": [
                {"key": "m:laptop", "kind": "m"},
                {"key": "s:A", "kind": "s", "parent": "m:laptop"},
                {"key": "p:focus", "kind": "p", "parent": "s:A"},
                {"key": "p:sib", "kind": "p", "parent": "s:A"},
                {"key": "p:peer0", "kind": "p", "parent": "s:A"},
                {"key": "p:peer1", "kind": "p", "parent": "s:A"},
                {"key": "r:sub0", "kind": "r", "parent": "p:focus"},
                {"key": "r:sub1", "kind": "r", "parent": "p:focus"},
                {"key": "h:child0", "kind": "h", "parent": "r:sub0"},
                {"key": "r:peerSub0", "kind": "r", "parent": "p:peer0"},
                {"key": "note:/srv/people/vault/doc.md", "kind": "n"},
            ],
            "edges": [
                ["m:laptop", "s:A", "contain"],
                ["s:A", "p:focus", "contain"],
                ["s:A", "p:sib", "contain"],
                ["s:A", "p:peer0", "contain"],
                ["s:A", "p:peer1", "contain"],
                ["p:focus", "p:sib", "sibling"],
                ["p:focus", "r:sub0", "link"],
                ["p:focus", "r:sub1", "link"],
                ["r:sub0", "h:child0", "link"],
                ["p:peer0", "r:peerSub0", "link"],
                ["p:peer1", "note:/srv/people/vault/doc.md", "touch", "edit"],
            ],
        }
        r = run("""
            const sim = S.createSim();
            S.sync(sim, { ...P.g, focus: "p:focus" }, S.QUARTZ.local, P.W, P.H);
            S.settle(sim, 5000);
            const rOf = (k) => { const p = sim.pos.get(k); return Math.hypot(p.x, p.y); };
            const mean = (ks) => ks.reduce((s, k) => s + rOf(k), 0) / ks.length;
            const adj = new Map();
            for (const [a, b, kind] of P.g.edges) {
              if (kind === "sibling") continue;
              (adj.get(a) ?? adj.set(a, []).get(a)).push(b);
              (adj.get(b) ?? adj.set(b, []).get(b)).push(a);
            }
            const dist = new Map([["p:focus", 0]]);
            const q = ["p:focus"];
            while (q.length) {
              const cur = q.shift();
              for (const nxt of adj.get(cur) ?? []) {
                if (!dist.has(nxt)) { dist.set(nxt, dist.get(cur) + 1); q.push(nxt); }
              }
            }
            const hops = [1, 2, 3].map((d) => [...dist.entries()].filter(([, v]) => v === d).map(([k]) => k));
            console.log(JSON.stringify({
              focus: rOf("p:focus"),
              hops,
              means: hops.map(mean),
            }));
        """, {"g": g, "W": W, "H": H})
        self.assertLess(r["focus"], 12, r)
        self.assertLess(r["means"][0], r["means"][1], r)
        self.assertLess(r["means"][1], r["means"][2], r)

    def test_radial_targets_ignore_sibling_edges_and_mode_switch_clears_positions(self):
        r = run("""
            const nodes = [
              { key: "m:laptop", kind: "m" },
              { key: "s:A", kind: "s", parent: "m:laptop" },
              { key: "p:1", kind: "p", parent: "s:A" },
              { key: "p:2", kind: "p", parent: "s:A" },
            ];
            const edges = [
              ["m:laptop", "s:A", "contain"],
              ["s:A", "p:1", "contain"],
              ["s:A", "p:2", "contain"],
              ["p:1", "p:2", "sibling"],
            ];
            const t1 = S.radialTargets(nodes, edges, { linkDistance: 30 });
            const t2 = S.radialTargets([...nodes].reverse(), [...edges].reverse(), { linkDistance: 30 });
            const sameTargets = [...t1].every(([k, v]) => {
              const w = t2.get(k);
              return w && v.x === w.x && v.y === w.y && v.rRing === w.rRing && v.angle === w.angle;
            });
            const sim = S.createSim();
            S.sync(sim, P.world, S.QUARTZ.global, P.W, P.H);
            S.settle(sim, 5000);
            sim.pos.clear();
            S.sync(sim, { ...P.world, focus: "p:a000" }, S.QUARTZ.local, P.W, P.H);
            const alphaOnClear = sim.d3.alpha();
            S.settle(sim, 5000);
            const fp = sim.pos.get("p:a000");
            console.log(JSON.stringify({
              sRing: t1.get("s:A").rRing,
              p1Ring: t1.get("p:1").rRing,
              p2Ring: t1.get("p:2").rRing,
              sameTargets,
              alphaOnClear,
              focusR: Math.hypot(fp.x, fp.y),
            }));
        """, {"world": world(), "W": W, "H": H})
        self.assertEqual(r["p1Ring"], r["p2Ring"], r)
        self.assertGreater(r["p1Ring"], r["sRing"], r)
        self.assertTrue(r["sameTargets"], "radialTargets must be deterministic across node/edge reordering")
        self.assertEqual(r["alphaOnClear"], 1)
        self.assertLess(r["focusR"], 12, r)

        src = MAIN.read_text(encoding="utf-8")
        self.assertRegex(src, r"sync\(this\.sim,\s*\{[^}]*focus:\s*g\.focus[^}]*\}", "main.js passes focus: g.focus into sync")
        mode_line = re.search(r'else if \(verb === "mode"\)\s*\{([^\n]+)\}', src)
        focus_line = re.search(r'else if \(verb === "focus-on"\)\s*\{([^\n]+)\}', src)
        self.assertIsNotNone(mode_line)
        self.assertIsNotNone(focus_line)
        self.assertIn("this.sim.pos.clear()", mode_line.group(1))
        self.assertIn("this.sim.pos.clear()", focus_line.group(1))


class LabelPlacementAndDepth(unittest.TestCase):
    """Non-overlapping label culling (placeLabels) and interactive Local depth cycling (nextDepth)."""

    def test_overlapping_unpinned_labels_cull_lower_priority_while_pinned_and_labelsAll_keep_all(self):
        r = run("""
            const items = [
              { key: "m:hub", kind: "m", label: "server", x: 100, top: 80, maxW: 120, size: 9, height: 14, r: 5, pinned: false },
              { key: "p:leaf", kind: "p", label: "worker-pane", x: 104, top: 82, maxW: 120, size: 9, height: 14, r: 3, pinned: false },
              { key: "p:far", kind: "p", label: "distant", x: 260, top: 82, maxW: 120, size: 9, height: 14, r: 3, pinned: false },
            ];
            const culled = [...S.placeLabels(items, false)].sort();
            const forced = [...S.placeLabels(items, true)].sort();
            const pinned = [...S.placeLabels(items.map((x) => x.key === "p:leaf" ? { ...x, pinned: true } : x), false)].sort();
            console.log(JSON.stringify({ culled, forced, pinned, d: [1, 2, 3].map((x) => S.nextDepth(x, 1)) }));
        """, {}, SHAPE)
        self.assertEqual(r["culled"], ["m:hub", "p:far"], "colliding lower-priority leaf label is culled")
        self.assertEqual(r["forced"], ["m:hub", "p:far", "p:leaf"], "labelsAll keeps every label")
        self.assertIn("p:leaf", r["pinned"], "pinned hover/selection label always shows")
        self.assertEqual(r["d"], [2, 3, 1])

    def test_main_wires_placeLabels_depth_button_and_empty_local_pruning(self):
        src = MAIN.read_text(encoding="utf-8")
        self.assertIn("placeLabels(", src)
        self.assertIn('"g-depth"', src)
        self.assertIn('"g-foot-depth"', src)
        self.assertIn('nodes.delete("m:local")', src)


if __name__ == "__main__":
    unittest.main()
