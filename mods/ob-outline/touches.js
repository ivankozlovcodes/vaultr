// kit/touches.js: what the files the agents touch mean for the graph. Pure: no Herdr imports, so
// test/test_touches.py runs it under node. The scanner (providers/scan_core.py) gives touches per agent key: {path, op, at}, op read |
// edit | write | create | publish, and for a herdr-artifact publication `artifact` {id, title, v}. classifyTouch says what
// each one is:
//   note      a .md file inside the vault: title = its file name without .md, rel = its vault-relative path
//   artifact  a herdr-artifact publication, or a file written or created outside the vault (not the agents' own state,
//             which includes per-user scratch folders in /tmp)
//   null      nothing to show: reads and edits outside the vault, attachments in the vault, a vault path in a danger
//             or hidden folder (the vault's rule: danger/ holds credentials; .obsidian, .git, .trash are the app's),
//             and any note of a remote machine (its paths are not this vault's)
// Notes need a vault (cfg.root, a full path, from obsidian.json); with none, notes are off.

const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;
export const OP_LIST = ["read", "edit", "write", "create", "publish"];
const WRITES = new Set(["write", "create"]);
// The agents' and Herdr's own state under home: dot-directories (~/.<dir>/...) and Herdr paths are never project artifacts.
const OWN_STATE = [".herdr", ".config/herdr-app", ".local/share/shepherdr"];
// Agent per-user scratch folders (/tmp/<name>-<uid>/, /private/tmp on macOS): agent state too.
const OWN_TMP = /^(\/private)?\/tmp\/[a-z0-9_-]+-\d+\//i;

// A full path with ~ expanded and trailing slashes dropped; null for a relative or empty one (obsidian/config.js's rule).
export function expandPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/")) return (home + s.slice(1)).replace(/\/+$/, "");
  if (ABSOLUTE.test(s)) return s.replace(/(.)[\\/]+$/, "$1");
  return null;
}

// The vault-relative path of an absolute path inside root, or null (outside it, the root itself, or a ".." escape).
export function vaultRel(abs, root) {
  if (!root || typeof abs !== "string") return null;
  const r = root.replace(/\/+$/, "");
  if (!abs.startsWith(`${r}/`)) return null;
  const rel = abs.slice(r.length + 1);
  if (!rel || rel.split("/").includes("..")) return null;
  return rel;
}

// True for a vault path with a danger folder at any depth, or a hidden folder or file (a dot name).
export function hiddenOrDanger(rel) {
  return String(rel).split("/").some((seg) => seg.startsWith(".") || seg.toLowerCase() === "danger");
}

function ownState(path, home) {
  if (OWN_TMP.test(path)) return true;
  if (!home) return false;
  if (path.startsWith(`${home}/.`)) return true;
  return OWN_STATE.some((d) => path === `${home}/${d}` || path.startsWith(`${home}/${d}/`));
}

// cfg: { root (the vault's full path or null), home, machine (null for this computer) }.
export function classifyTouch(t, cfg = {}) {
  if (!t || typeof t.path !== "string" || !t.path || !OP_LIST.includes(t.op)) return null;
  const at = typeof t.at === "number" ? t.at : null;
  const base = t.path.split("/").pop() || t.path;
  if (t.artifact && typeof t.artifact === "object") {
    return { kind: "artifact", path: t.path, title: t.artifact.title || base, op: t.op, at, artifact: t.artifact };
  }
  const rel = cfg.machine == null ? vaultRel(t.path, cfg.root) : null;
  if (rel !== null) {
    if (hiddenOrDanger(rel) || !/\.md$/i.test(rel)) return null;   // attachments are skipped in this version
    return { kind: "note", path: t.path, rel, title: rel.split("/").pop().replace(/\.md$/i, ""), op: t.op, at };
  }
  if (WRITES.has(t.op) && !ownState(t.path, cfg.home)) return { kind: "artifact", path: t.path, title: base, op: t.op, at };
  return null;
}

// Every shown touch of every agent: [{ agent, kind, path, ... }] in the order given.
export function classifyAll(byKey, cfg = {}) {
  const out = [];
  for (const [agent, list] of Object.entries(byKey ?? {})) {
    for (const t of Array.isArray(list) ? list : []) {
      const c = classifyTouch(t, cfg);
      if (c) out.push({ agent, ...c });
    }
  }
  return out;
}
