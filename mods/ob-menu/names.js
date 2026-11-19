// One naming rule for panes (copied into each mod by kit/sync.sh; kit.js re-exports it). Pure: no Herdr or gpui
// imports, so test/test_kit_names.py runs it under node.
//
// A pane is named for what it runs: an agent by its session title (else its program's name or folder), a shell by its
// folder, a mod by its panel's name, any other program by its name. A tab keeps its own name; a pane's label never
// repeats the tab's name when another candidate exists (a tab is often named after its first program, so the pane
// would read the same).
//
// paneLabel(pane, ctx): pane = { kind?, program?: { name, agent?, shell? }, title?, cwd?, mod? }, where kind is
//   "agent" | "shell" | "mod" | "program" (worked out from program, ctx.sessionTitle, and mod when absent).
//   ctx = { sessionTitle?, folder?, home?, panelName?, tabName? }: the agent's session title (feed terms name, or the
//   agent's title), the folder (else the pane's cwd), the home directory, the mod's panel name, the tab's name.

const LONG_FOLDER = 24;   // characters: a longer folder keeps only its last two parts

// Trims whitespace and drops leading non-alphanumeric symbols/emoji (preserving leading ~ or / paths).
export function cleanTitle(s) {
  return String(s ?? "").trim().replace(/^[^\p{L}\p{N}~/]+/u, "").trim();
}

// The folder as people write it: home as "~", and a long path cut to its last two parts ("…/2 Projects/vaultr").
export function shortFolder(folder, home) {
  let s = String(folder ?? "").trim();
  if (!s) return "";
  if (s.length > 1) s = s.replace(/\/+$/, "");
  const h = String(home ?? "").replace(/\/+$/, "");
  if (h && s === h) s = "~";
  else if (h && s.startsWith(h + "/")) s = "~" + s.slice(h.length);
  const parts = s.split("/");
  if (s.length > LONG_FOLDER && parts.length > 2) return "…/" + parts.slice(-2).join("/");
  return s;
}

// The label a tab row shows under its own name when the tab holds one pane: the pane's label, unless it is empty or
// is the tab's name already.
export function paneSecondary(tabName, label) {
  const l = typeof label === "string" ? label.trim() : "";
  if (!l) return null;
  const t = typeof tabName === "string" ? tabName.trim() : "";
  return l === t ? null : l;
}

function kindOf(pane, ctx) {
  if (pane.kind) return pane.kind;
  if (pane.mod) return "mod";
  if (pane.program?.agent || (typeof ctx?.sessionTitle === "string" && ctx.sessionTitle.trim())) return "agent";
  if (pane.program?.shell) return "shell";
  return "program";
}

export function paneLabel(pane = {}, ctx = {}) {
  const p = pane ?? {};
  const c = ctx ?? {};
  const prog = p.program?.name ?? "";
  const folder = shortFolder(c.folder ?? p.cwd, c.home);
  let candidates;
  switch (kindOf(p, c)) {
    case "agent": candidates = [cleanTitle(c.sessionTitle), prog, folder]; break;
    case "shell": candidates = [folder, cleanTitle(p.title), prog]; break;
    case "mod": candidates = [c.panelName, p.mod, cleanTitle(p.title)]; break;
    default: candidates = [prog, cleanTitle(p.title)];
  }
  const texts = candidates.map((x) => (typeof x === "string" ? x.trim() : "")).filter(Boolean);
  if (!texts.length) return "Terminal";
  const tab = typeof c.tabName === "string" ? c.tabName.trim() : "";
  return texts.find((t) => t !== tab) ?? texts[0];
}
