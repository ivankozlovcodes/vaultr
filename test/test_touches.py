"""kit/touches.js: what the scanner's touches mean for the graph. Pure rules (no Herdr imports), run here through node.
A path inside the vault is a note (a .md file), never a danger/ or hidden (.obsidian, .git, .trash) one; attachments in
the vault are skipped; a herdr-artifact publication is an artifact; a file written or created outside the vault is an
artifact (reads and edits outside are not); with no vault, notes are off; a remote machine's paths are never notes."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = home_guard.ROOT
TOUCHES = Path(ROOT, "kit", "touches.js")
NODE = shutil.which("node")
HOME = "/srv/people"
VAULT = "/srv/people/vault"


def call(fn, *args):
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    code = (f"import * as m from {json.dumps(TOUCHES.as_uri())};\n"
            "import { readFileSync } from 'node:fs';\n"
            "const i = JSON.parse(readFileSync(0, 'utf8'));\n"
            "const r = m[i.fn](...i.args);\n"
            "process.stdout.write(JSON.stringify(r === undefined ? null : r));\n")
    res = subprocess.run([NODE, "--input-type=module", "-e", code], input=json.dumps({"fn": fn, "args": list(args)}),
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    return json.loads(res.stdout)


def touch(path, op="read", at=1000, **extra):
    return {"path": path, "op": op, "at": at, **extra}


CFG = {"root": VAULT, "home": HOME, "machine": None}


class ExpandAndVault(unittest.TestCase):
    def test_tilde_becomes_home_and_a_relative_path_is_refused(self):
        self.assertEqual(call("expandPath", "~/vault/", HOME), "/srv/people/vault")
        self.assertIsNone(call("expandPath", "vault", HOME))

    def test_a_path_inside_the_vault_is_relative_and_a_sibling_folder_is_not(self):
        self.assertEqual(call("vaultRel", f"{VAULT}/notes/Idea.md", VAULT), "notes/Idea.md")
        self.assertIsNone(call("vaultRel", f"{VAULT}2/notes/Idea.md", VAULT))
        self.assertIsNone(call("vaultRel", f"{VAULT}", VAULT))
        self.assertIsNone(call("vaultRel", "/srv/other/a.md", VAULT))

    def test_danger_and_hidden_folders_are_recognised_at_any_depth(self):
        for rel in ["danger/keys.md", "notes/danger/x.md", "Danger/Keys.md", ".obsidian/app.json", ".trash/old.md",
                    "notes/.git/config", ".hidden/x.md"]:
            self.assertTrue(call("hiddenOrDanger", rel), rel)
        self.assertFalse(call("hiddenOrDanger", "notes/Idea.md"))


class Notes(unittest.TestCase):
    def test_a_markdown_file_in_the_vault_is_a_note_titled_by_its_name(self):
        got = call("classifyTouch", touch(f"{VAULT}/notes/Idea.md", "edit", 5), CFG)
        self.assertEqual(got, {"kind": "note", "path": f"{VAULT}/notes/Idea.md", "rel": "notes/Idea.md", "title": "Idea", "op": "edit", "at": 5})

    def test_a_note_in_the_danger_folder_is_dropped_entirely(self):
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/danger/keys.md", "write"), CFG))
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/danger/keys.md", "read"), CFG))

    def test_a_note_in_a_hidden_folder_is_dropped_and_is_not_an_artifact_either(self):
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/.obsidian/app.json", "write"), CFG))
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/.trash/old.md", "create"), CFG))

    def test_attachments_in_the_vault_are_skipped_in_this_version(self):
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/img/pic.png", "read"), CFG))
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/img/pic.png", "create"), CFG))

    def test_with_no_vault_no_path_is_a_note(self):
        cfg = {"root": None, "home": HOME, "machine": None}
        self.assertIsNone(call("classifyTouch", touch(f"{VAULT}/notes/Idea.md", "read"), cfg))

    def test_a_remote_machines_path_is_never_a_note_even_under_the_same_name(self):
        cfg = {"root": VAULT, "home": HOME, "machine": "spare"}
        got = call("classifyTouch", touch(f"{VAULT}/notes/Idea.md", "read"), cfg)
        self.assertIsNone(got)


class Artifacts(unittest.TestCase):
    def test_a_herdr_artifact_publication_is_an_artifact_with_its_title(self):
        t = touch("/srv/store/files/cov-ab12/v2", "publish", 9, artifact={"id": "cov-ab12", "title": "Coverage by package", "v": 2})
        got = call("classifyTouch", t, CFG)
        self.assertEqual(got["kind"], "artifact")
        self.assertEqual(got["title"], "Coverage by package")
        self.assertEqual(got["artifact"]["id"], "cov-ab12")
        self.assertEqual(got["op"], "publish")

    def test_a_publication_is_an_artifact_even_inside_the_vault(self):
        t = touch(f"{VAULT}/out/report", "publish", 9, artifact={"id": "r-1", "title": "Report", "v": 1})
        self.assertEqual(call("classifyTouch", t, CFG)["kind"], "artifact")

    def test_a_file_written_or_created_outside_the_vault_is_an_artifact(self):
        for op in ["create", "write"]:
            got = call("classifyTouch", touch("/srv/project/out/chart.svg", op), CFG)
            self.assertEqual(got["kind"], "artifact", op)
            self.assertEqual(got["title"], "chart.svg")

    def test_reads_and_edits_outside_the_vault_are_not_artifacts(self):
        self.assertIsNone(call("classifyTouch", touch("/srv/project/src/x.js", "read"), CFG))
        self.assertIsNone(call("classifyTouch", touch("/srv/project/src/x.js", "edit"), CFG))

    def test_the_agents_own_state_folders_are_never_artifacts(self):
        for p in [f"{HOME}/.claude/projects/x/memory/a.md", f"{HOME}/.pi/agent/x.json", f"{HOME}/.config/herdr-app/keys.json",
                  f"{HOME}/.herdr/artifacts/x.json"]:
            self.assertIsNone(call("classifyTouch", touch(p, "create"), CFG), p)

    def test_claude_scratchpad_writes_are_agent_state_not_artifacts(self):
        for p in ["/tmp/claude-1000/-srv-project/0f3a/scratchpad/page.html", "/private/tmp/claude-501/x/scratchpad/a.py"]:
            self.assertIsNone(call("classifyTouch", touch(p, "write"), CFG), p)
        for p in ["/tmp/report.html", "/tmp/claude-notes.txt", "/srv/project/tmp/claude-1/x.txt", "/tmp/claude-notes/x.md"]:
            self.assertEqual(call("classifyTouch", touch(p, "write"), CFG)["kind"], "artifact", p)

    def test_with_no_vault_a_write_outside_is_still_an_artifact(self):
        cfg = {"root": None, "home": HOME, "machine": None}
        self.assertEqual(call("classifyTouch", touch(f"{VAULT}/a.md", "create"), cfg)["kind"], "artifact")

    def test_a_remote_machines_written_file_is_an_artifact(self):
        cfg = {"root": VAULT, "home": HOME, "machine": "spare"}
        self.assertEqual(call("classifyTouch", touch("/srv/project/out.txt", "write"), cfg)["kind"], "artifact")


class Collect(unittest.TestCase):
    def test_collect_keeps_each_agent_key_and_drops_what_is_not_shown(self):
        byKey = {
            "term:t1": [touch(f"{VAULT}/notes/A.md", "read", 3), touch(f"{VAULT}/danger/k.md", "write", 4),
                        touch("/srv/x.js", "read", 5), touch("/srv/out.txt", "create", 6)],
            "c:local:a1": [touch(f"{VAULT}/notes/A.md", "edit", 7)],
        }
        rows = call("classifyAll", byKey, CFG)
        keys = sorted((r["agent"], r["kind"], r["path"]) for r in rows)
        self.assertEqual(keys, [
            ("c:local:a1", "note", f"{VAULT}/notes/A.md"),
            ("term:t1", "artifact", "/srv/out.txt"),
            ("term:t1", "note", f"{VAULT}/notes/A.md"),
        ])

    def test_the_same_path_read_by_two_agents_is_two_rows_one_per_agent(self):
        rows = call("classifyAll", {"term:a": [touch(f"{VAULT}/n.md", "read")], "term:b": [touch(f"{VAULT}/n.md", "edit")]}, CFG)
        self.assertEqual(sorted(r["agent"] for r in rows), ["term:a", "term:b"])


if __name__ == "__main__":
    unittest.main()
