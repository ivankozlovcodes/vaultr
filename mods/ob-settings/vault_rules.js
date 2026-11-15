// vault_rules.js: the decisions behind the Vault tab, as pure functions (no Herdr imports) so
// test/test_ob_settings.py can run them through node. vault.js does the file reads and writes.
//
// The tab sets one key, the vault folder. Null means "remove this key" (an empty field clears it).
// Everything returns new objects. expandPath is the rule of mods/obsidian/config.js, copied here:
// mods do not import each other.
const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;
export function expandPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/")) return (home + s.slice(1)).replace(/\/+$/, "");
  if (ABSOLUTE.test(s)) return s.replace(/(.)[\\/]+$/, "$1");
  return null;
}

// The value to store for a typed vault folder: { value } (null removes the key) or { error } (not saved).
// The folder must be a full path; the obsidian mod refuses a relative one.
export function parseVault(s, home = "/") {
  const t = String(s ?? "").trim();
  if (!t) return { value: null };
  return expandPath(t, home) ? { value: t } : { error: "The vault folder must be a full path: ~/... or /..." };
}

// obsidian.json with one key set (or removed when value is null). Other keys are kept.
export function mergeOwn(own, key, value) {
  const next = { ...own };
  if (value === null || value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

// Whether the folder a vault path names exists. `isDir` is what the check found. Null when fine.
export function vaultProblem(path, isDir) {
  return isDir ? null : `No folder at ${path}. Create it first, or give another folder; nothing was saved.`;
}
