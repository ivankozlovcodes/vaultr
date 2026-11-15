// vault_rules.js: the vault rule the daily-note command uses, as pure functions (no Herdr imports) so
// test/test_obsidian.py can run them through node. main.js reads obsidian.json and passes it in.
//
// The same rule as mods/obsidian/config.js, copied here because mods do not import each other: the vault is the
// `vault` key in obsidian.json and nothing else. Unset means no vault, with no fallback to Obsidian's own vault list.
// A relative path is refused, since it would be resolved against the process's folder, not the person's.

const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;

// A full path with ~ expanded and trailing slashes dropped; null for a relative path.
export function expandPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/")) return (home + s.slice(1)).replace(/\/+$/, "");
  if (ABSOLUTE.test(s)) return s.replace(/(.)[\\/]+$/, "$1");
  return null;
}

// { root } for the vault in obsidian.json; otherwise { error } with what to tell the person. `unset` is true
// when the key is missing or empty, so the caller can point at Settings.
export function vaultFor(own, home) {
  const set = typeof own?.vault === "string" && own.vault.trim() ? own.vault : null;
  if (!set) return { unset: true, error: "Set your vault in Settings first." };
  const root = expandPath(set, home);
  if (!root) return { error: `The vault in obsidian.json must be a full path (~/... or /...), not "${set}".` };
  return { root };
}
