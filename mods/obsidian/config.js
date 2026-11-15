// config.js: the vault settings the obsidian mod uses, as pure rules (no Herdr imports) so
// test/test_obsidian.py can run them through node. vault.js reads the files and passes the texts in.
//
// Precedence: appHome()/obsidian.json (own keys) beats the vault's .obsidian/daily-notes.json and app.json,
// which beat the defaults. The vault is the `vault` key in obsidian.json and nothing else: unset means no vault,
// with no fallback to Obsidian's own open or last vault. A vault path must be a full path: "~/..." or absolute.
// A relative one is refused, since it would be resolved against the process's folder, not the person's.

const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;

// A full path with ~ expanded and trailing slashes dropped; null for a relative path.
export function expandPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/")) return (home + s.slice(1)).replace(/\/+$/, "");
  if (ABSOLUTE.test(s)) return s.replace(/(.)[\\/]+$/, "$1");
  return null;
}

const trim = (p) => String(p ?? "").replace(/^\/+|\/+$/g, "");

// The settings in effect. `own` is obsidian.json parsed; `daily` and `app` are the vault's .obsidian JSON,
// parsed (or {}). Throws "No vault set." when obsidian.json has no vault: there is no other source for one.
export function buildConfig({ own = {}, daily = {}, app = {}, home }) {
  const ownVault = typeof own.vault === "string" && own.vault.trim() ? own.vault : null;
  if (!ownVault) throw noVault();
  const root = expandPath(ownVault, home);
  if (!root) throw new Error(`The vault in obsidian.json must be a full path (~/... or /...), not "${ownVault}".`);
  return {
    root,
    name: root.split(/[\\/]/).pop(),
    editor: Array.isArray(own.editor) && own.editor.length ? own.editor : null,
    daily: {
      folder: trim(own.dailyFolder ?? daily.folder),
      format: own.dailyFormat ?? daily.format ?? "YYYY-MM-DD",
      template: trim(own.dailyTemplate ?? daily.template),
    },
    newFolder: app.newFileLocation === "folder" ? trim(app.newFileFolderPath) : "",
  };
}

// The error for an unset vault. The Notes panel recognises it (`noVault`) and shows its empty state instead.
export const NO_VAULT = "No vault set.";
export function noVault() {
  const e = new Error(NO_VAULT);
  e.noVault = true;
  return e;
}

// What the Notes panel compares between checks: when this changes, the panel reloads its config and its list.
// The texts are the raw files (null when a file is missing), so an edit of any kind shows up.
export function settingsStamp(ownText, dailyText) {
  return JSON.stringify([ownText ?? null, dailyText ?? null]);
}
