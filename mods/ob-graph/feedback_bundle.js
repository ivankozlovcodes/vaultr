// feedback_bundle.js: pure bundle, path, host file-op, layout annotation, and
// sanitization helpers for ob-feedback, ob-tabs, and ob-settings. Zero Herdr or UI
// imports so unit tests run directly under node.

const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;

export const SAFE_SHARED_KEYS = [
  "layout",
  "ob.zen",
  "ob.hidden",
  "ob.dismissed",
  "ob.inspect",
  "ob.focus",
  "ob.history",
  "ob.bookmarks",
  "ob.settings",
  "ob-settings.open",
  "ob-settings.tab",
];

function stripTrailing(path) {
  if (/^\/+$/.test(path)) return "/";
  if (/^[A-Za-z]:[\\/]+$/.test(path)) return path.slice(0, 3);
  if (/^\\\\+$/.test(path)) return "\\\\";
  return path.replace(/[\\/]+$/, "");
}

function deepClone(v) {
  if (v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(deepClone);
  const out = {};
  for (const [k, val] of Object.entries(v)) out[k] = deepClone(val);
  return out;
}

function safeCall(fn, fallback) {
  if (typeof fn !== "function") return fallback;
  try {
    const v = fn();
    return v === undefined ? fallback : v;
  } catch {
    return fallback;
  }
}

function safeLen(fn) {
  const v = safeCall(fn, []);
  return Array.isArray(v) ? v.length : 0;
}

function winPath(p) {
  return String(p ?? "").replace(/\//g, "\\");
}

export function isSafeStageRel(rel) {
  return typeof rel === "string"
    && rel.startsWith("data/ob-feedback/")
    && !rel.includes("..")
    && rel.endsWith(".png");
}

// Host filesystem helpers via Herdr's unrestricted exec grant: gpui-kit's fs/promises
// limits read_roots to [home()] and write_roots to [appHome()] and throws synchronously
// outside those roots, whereas user feedback bundles and non-HOME $HERDR_APP_HOME can sit
// anywhere on disk.
export async function ensureDir(dir, execFn, platform = "linux") {
  if (platform === "windows") {
    const winDir = winPath(dir);
    const r = await execFn("cmd", ["/d", "/c", "if", "not", "exist", winDir, "mkdir", winDir], { timeout: 5000 });
    if (r?.code !== 0) throw new Error(String(r?.stderr || r?.stdout || `mkdir exited ${r?.code ?? "?"}`).trim());
    return;
  }
  const r = await execFn("mkdir", ["-p", dir], { timeout: 5000 });
  if (r?.code !== 0) throw new Error(String(r?.stderr || r?.stdout || `mkdir exited ${r?.code ?? "?"}`).trim());
}

export async function dirExists(dir, execFn, platform = "linux") {
  const r = platform === "windows"
    ? await execFn("cmd", ["/d", "/c", "if", "exist", `"${winPath(dir)}\\"`, "(exit 0)", "else", "(exit 1)"], { timeout: 3000 }).catch(() => ({ code: 1 }))
    : await execFn("test", ["-d", dir], { timeout: 3000 }).catch(() => ({ code: 1 }));
  return r?.code === 0;
}

export async function nonEmptyFileExists(file, execFn, platform = "linux") {
  const r = platform === "windows"
    ? await execFn("cmd", ["/d", "/c", "if", "exist", `"${winPath(file)}"`, "(exit 0)", "else", "(exit 1)"], { timeout: 3000 }).catch(() => ({ code: 1 }))
    : await execFn("test", ["-s", file], { timeout: 3000 }).catch(() => ({ code: 1 }));
  return r?.code === 0;
}

export async function copyBinaryFile(src, dst, execFn, platform = "linux") {
  const r = platform === "windows"
    ? await execFn("cmd", ["/d", "/c", "copy", "/y", winPath(src), winPath(dst)], { timeout: 5000 }).catch(() => ({ code: 1 }))
    : await execFn("cp", [src, dst], { timeout: 5000 }).catch(() => ({ code: 1 }));
  return r?.code === 0;
}

export async function removeFile(file, fsApi, execFn, platform = "linux") {
  if (fsApi?.unlink) {
    try {
      await fsApi.unlink(file);
      return true;
    } catch (e) {
      if (e?.code === "ENOENT") return false;
    }
  }
  if (typeof execFn === "function") {
    const r = platform === "windows"
      ? await execFn("cmd", ["/d", "/c", "del", "/f", "/q", winPath(file)], { timeout: 3000 }).catch(() => ({ code: 1 }))
      : await execFn("rm", ["-f", file], { timeout: 3000 }).catch(() => ({ code: 1 }));
    return r?.code === 0;
  }
  return false;
}

export function expandFeedbackPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/") || s.startsWith("~\\")) {
    const h = String(home ?? "").trim();
    if (!h) return null;
    const base = stripTrailing(h);
    if (s === "~") return base;
    const tail = s.slice(1).replace(/^[/\\]+/, "");
    if (!tail) return base;
    const sep = base === "/" || base.endsWith("\\") || base.endsWith("/")
      ? ""
      : (base.includes("\\") && !base.includes("/") ? "\\" : "/");
    return stripTrailing(`${base}${sep}${tail}`);
  }
  if (ABSOLUTE.test(s)) return stripTrailing(s);
  return null;
}

export function parseFeedbackFolder(s, home = "/") {
  const t = String(s ?? "").trim();
  if (!t) return { value: null };
  return expandFeedbackPath(t, home)
    ? { value: t }
    : { error: "The feedback folder must be a full path: ~/... or /..." };
}

export function mergeFeedbackOwn(own, value) {
  const base = own && typeof own === "object" && !Array.isArray(own) ? own : {};
  const next = { ...base };
  if (value === null || value === undefined) delete next.folder;
  else next.folder = value;
  return next;
}

export function slugifyFeedback(text, fallback = "feedback") {
  const lines = String(text ?? "").split(/\r?\n/);
  for (const raw of lines) {
    const cleaned = raw.trim().replace(/^[#>*_`~\s\-.:;!?/\\]+/, "");
    if (!cleaned) continue;
    const words = cleaned.toLowerCase().match(/[a-z0-9]+/g);
    if (!words || !words.length) continue;
    const slug = words.join("-").slice(0, 36).replace(/^-+|-+$/g, "");
    if (slug) return slug;
  }
  return fallback;
}

export function formatBundleStamp(ms) {
  const pad = (n, w = 2) => String(Math.trunc(Number(n) || 0)).padStart(w, "0");
  if (ms && typeof ms === "object" && !(ms instanceof Date) && typeof ms.year === "number") {
    return `${pad(ms.year, 4)}-${pad(ms.month)}-${pad(ms.day)}_${pad(ms.hours)}-${pad(ms.minutes)}-${pad(ms.seconds)}`;
  }
  const d = ms instanceof Date ? ms : new Date(ms ?? Date.now());
  const valid = Number.isNaN(d.getTime()) ? new Date() : d;
  return `${pad(valid.getFullYear(), 4)}-${pad(valid.getMonth() + 1)}-${pad(valid.getDate())}_${pad(valid.getHours())}-${pad(valid.getMinutes())}-${pad(valid.getSeconds())}`;
}

export function pickBundleDirName(stamp, slug, existingNames = []) {
  const cleanSlug = String(slug ?? "").trim() || "feedback";
  const base = `${stamp}-${cleanSlug}`;
  const taken = new Set(Array.isArray(existingNames) ? existingNames : []);
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

export async function pickAvailableBundleDir(rootDir, stamp, slug, existsFn) {
  const cleanSlug = String(slug ?? "").trim() || "feedback";
  const base = `${stamp}-${cleanSlug}`;
  if (!await existsFn(`${rootDir}/${base}`)) return base;
  let n = 2;
  while (await existsFn(`${rootDir}/${base}-${n}`)) n++;
  return `${base}-${n}`;
}

export function herdrAppCandidates(homeDir, platform = "linux") {
  const h = String(homeDir ?? "").trim().replace(/[\\/]+$/, "");
  const out = ["herdr-app"];
  if (h) out.push(`${h}/.local/bin/herdr-app`);
  if (platform === "macos") {
    out.push("/Applications/Herdr.app/Contents/MacOS/Herdr");
    if (h) out.push(`${h}/Applications/Herdr.app/Contents/MacOS/Herdr`);
  }
  return [...new Set(out)];
}

export function annotateLayoutTree(root) {
  if (!root || typeof root !== "object") return null;
  const walk = (node, parentShown) => {
    if (!node || typeof node !== "object") return null;
    if (Array.isArray(node)) return node.map((x) => walk(x, parentShown));
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "children" || k === "floating") continue;
      out[k] = deepClone(v);
    }
    const selfShown = Boolean(parentShown) && !node.hidden;
    out.effectiveShown = selfShown;
    if (Array.isArray(node.children)) {
      const activeId = node.type === "stack" ? (node.active ?? node.children[0]?.id ?? null) : null;
      out.children = node.children.map((child) => {
        const childAllowed = node.type === "stack" ? (selfShown && child?.id === activeId) : selfShown;
        return walk(child, childAllowed);
      });
    }
    if (Array.isArray(node.floating)) {
      out.floating = node.floating.map((f) => walk(f, selfShown));
    }
    return out;
  };
  return walk(root, true);
}

export function sanitizeSharedState(rawShared, counts = null) {
  const src = rawShared && typeof rawShared === "object" ? rawShared : {};
  const out = {};
  for (const k of SAFE_SHARED_KEYS) {
    if (src[k] !== undefined) out[k] = deepClone(src[k]);
  }
  const intOr0 = (v) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.trunc(v) : 0);
  out.providerSessionsCount = intOr0(counts?.sessions ?? src.providerSessionsCount);
  out.providerSubagentsCount = intOr0(counts?.subagents ?? src.providerSubagentsCount);
  return out;
}

export function sanitizeTerminals(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter((t) => t && typeof t === "object")
    .map((t) => ({
      address: t.address ?? null,
      parent: t.parent ?? null,
      name: t.name ?? null,
      template: t.template ?? null,
      state: t.state ?? null,
      status: t.status ?? null,
      program: t.program && typeof t.program === "object"
        ? {
            key: t.program.key ?? null,
            name: t.program.name ?? null,
            agent: Boolean(t.program.agent),
            shell: Boolean(t.program.shell),
          }
        : null,
      recordsCount: typeof t.recordsCount === "number"
        ? t.recordsCount
        : (t.records && typeof t.records === "object" ? Object.keys(t.records).length : 0),
    }));
}

export function buildUiTreeDump(capture) {
  const c = capture && typeof capture === "object" ? capture : {};
  const capturedAt = c.capturedAt ?? null;
  return {
    version: 1,
    capturedAt,
    isoTime: c.isoTime ?? (capturedAt != null ? new Date(capturedAt).toISOString() : null),
    layoutName: c.layoutName ?? null,
    layouts: Array.isArray(c.layouts) ? deepClone(c.layouts) : [],
    window: deepClone(c.window ?? null),
    appSettings: deepClone(c.appSettings ?? null),
    focused: deepClone(c.focused ?? null),
    layoutTree: annotateLayoutTree(c.layoutTree ?? null),
    layoutClickState: deepClone(c.layoutClickState ?? null),
    spaces: Array.isArray(c.spaces) ? deepClone(c.spaces) : [],
    panes: Array.isArray(c.panes) ? deepClone(c.panes) : [],
    agents: Array.isArray(c.agents) ? deepClone(c.agents) : [],
    machines: Array.isArray(c.machines) ? deepClone(c.machines) : [],
    appWorld: deepClone(c.appWorld ?? null),
    sharedState: sanitizeSharedState(c.sharedState ?? {}, c.providerCounts),
  };
}

export function buildDiagnosticsLog(capture) {
  const c = capture && typeof capture === "object" ? capture : {};
  const iso = c.isoTime ?? (c.capturedAt != null ? new Date(c.capturedAt).toISOString() : "unknown");
  const platform = c.window?.platform ?? "unknown";
  const appVer = c.updates?.app?.version ?? "unknown";
  const coreVer = c.updates?.core?.version ?? "unknown";
  const spacesList = Array.isArray(c.spaces) ? c.spaces : [];
  const activeSpace = spacesList.find((s) => s?.id === c.focused?.space) ?? spacesList.find((s) => s?.active) ?? null;
  const activeTab = activeSpace?.tabs?.find((tb) => tb?.id === c.focused?.tab) ?? activeSpace?.tabs?.find((tb) => tb?.active) ?? null;

  const summary = [
    "[summary]",
    `capturedAt: ${c.capturedAt ?? "unknown"}`,
    `isoTime: ${iso}`,
    `platform: ${platform}`,
    `herdrApp: ${appVer}`,
    `herdrCore: ${coreVer}`,
    `layoutName: ${c.layoutName ?? "unknown"}`,
    `space: ${activeSpace?.name ?? c.focused?.space ?? "none"}`,
    `tab: ${activeTab?.name ?? c.focused?.tab ?? "none"}`,
    `pane: ${c.focused?.pane ?? "none"}`,
    `terminal: ${c.focused?.terminal ?? "none"}`,
    `hasScreenshot: ${Boolean(c.hasScreenshot)}`,
    `screenshotPath: ${c.hasScreenshot ? (c.screenshotPath ?? "none") : "none"}`,
    `shotError: ${c.shotError ?? "none"}`,
  ].join("\n");

  const statusBody = c.appStatus
    ? JSON.stringify(c.appStatus, null, 2)
    : `unavailable (${c.statusError ?? "no status captured"})`;

  const errFiles = Array.isArray(c.errorFiles) ? c.errorFiles.filter((e) => e && e.name) : [];
  const errorFilesBody = errFiles.length
    ? errFiles.map((e) => `--- ${e.name} ---\n${String(e.text ?? "").trimEnd()}`).join("\n")
    : "none";

  const termRows = sanitizeTerminals(c.terminals);
  const terminalsBody = termRows.length ? termRows.map((t) => JSON.stringify(t)).join("\n") : "none";

  const bindings = (Array.isArray(c.keys) ? c.keys : [])
    .filter((k) => k && typeof k.section === "string" && (k.section.startsWith("layout:") || k.section.startsWith("mod:")));
  const keysBody = bindings.length
    ? bindings.map((k) => `${k.section}\t${k.keys}\t${k.action}`).join("\n")
    : "none";

  const warnings = [];
  for (const w of [c.shotError, c.statusError, c.lsError, c.layoutStateError, ...(Array.isArray(c.warnings) ? c.warnings : [])]) {
    if (typeof w === "string" && w.trim()) warnings.push(w.trim());
  }
  const warningsBody = warnings.length ? warnings.join("\n") : "none";

  return [
    summary,
    `[app-status]\n${statusBody}`,
    `[error-files]\n${errorFilesBody}`,
    `[terminals]\n${terminalsBody}`,
    `[keybindings]\n${keysBody}`,
    `[warnings]\n${warningsBody}`,
    "",
  ].join("\n\n");
}

export function buildFeedbackMarkdown(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const hasShot = Boolean(o.hasScreenshot);
  const files = ["feedback.md", ...(hasShot ? ["screenshot.png"] : []), "ui-tree.json", "diagnostics.log"];
  const val = (v) => (v === undefined || v === null || v === "" ? "null" : JSON.stringify(String(v)));
  const msg = String(o.message ?? "").trim();
  const lines = [
    "---",
    `created: ${val(o.created ?? new Date().toISOString())}`,
    `platform: ${val(o.platform ?? "linux")}`,
    `herdr_app: ${val(o.herdrApp)}`,
    `herdr_core: ${val(o.herdrCore)}`,
    `layout: ${val(o.layout ?? "vaultr")}`,
    `space: ${val(o.space)}`,
    `tab: ${val(o.tab)}`,
    `pane: ${val(o.pane)}`,
    `screenshot: ${hasShot ? '"screenshot.png"' : "null"}`,
    "files:",
    ...files.map((f) => `  - ${JSON.stringify(f)}`),
    "---",
    "",
    "# Feedback",
    "",
    msg,
    "",
  ];
  return lines.join("\n");
}

// Runs the pre-dialog capture pipeline using injected host/fs dependencies so
// both ob-tabs and ob-feedback share one path and Node tests run without Herdr.
export async function runFeedbackCapture(deps) {
  const capturedAt = typeof deps.now === "function" ? deps.now() : Date.now();
  const isoTime = new Date(capturedAt).toISOString();
  const layoutTree = safeCall(deps.layout, null);
  const layouts = safeCall(deps.layouts, []);
  const focused = safeCall(deps.focused, null);
  const spaces = safeCall(deps.spaces, []);
  const panes = safeCall(deps.panes, []);
  const agents = safeCall(deps.agents, []);
  const rawTerms = safeCall(deps.terminals, []);
  const machines = safeCall(deps.machines, []);
  const win = safeCall(deps.window, null);
  const platform = win?.platform ?? "linux";
  const appSettings = safeCall(deps.settings, null);
  const appUpdates = safeCall(deps.updates, null);
  const keyList = safeCall(deps.keys, []);
  const sharedRaw = {};
  for (const k of SAFE_SHARED_KEYS) {
    const v = safeCall(() => deps.shared(k), undefined);
    if (v !== undefined) sharedRaw[k] = v;
  }
  const providerCounts = {
    sessions: safeLen(() => deps.provider?.sessions?.()),
    subagents: safeLen(() => deps.provider?.subagents?.()),
  };
  const sharedState = sanitizeSharedState(sharedRaw, providerCounts);
  const layoutName = typeof sharedState.layout === "string" && sharedState.layout ? sharedState.layout : "vaultr";
  const sanitizedTerminals = sanitizeTerminals(rawTerms);

  const appDir = deps.appHome();
  const homeDir = deps.home();
  const stageDir = `${appDir}/data/ob-feedback`;
  // Unique path per capture busts GPUI AppAssets' path-keyed image cache across retakes.
  const stageRel = `data/ob-feedback/shot-${capturedAt}.png`;
  const stagePng = `${appDir}/${stageRel}`;
  const stageJson = `${stageDir}/capture.json`;
  const fsApi = deps.fs;

  await ensureDir(stageDir, deps.exec, platform);

  // Remove the previous staged screenshot recorded in capture.json (works even when appDir sits outside home()).
  let prevRaw = null;
  try { prevRaw = await deps.readTextFile(stageJson); } catch { prevRaw = null; }
  let prevCap = null;
  try { if (prevRaw != null) prevCap = JSON.parse(prevRaw); } catch { prevCap = null; }
  if (isSafeStageRel(prevCap?.screenshotPath) && `${appDir}/${prevCap.screenshotPath}` !== stagePng) {
    await removeFile(`${appDir}/${prevCap.screenshotPath}`, fsApi, deps.exec, platform);
  }
  await removeFile(`${stageDir}/capture.png`, fsApi, deps.exec, platform);
  if (fsApi?.readdir) {
    try {
      const staleFiles = await fsApi.readdir(stageDir);
      for (const name of staleFiles) {
        if (typeof name === "string" && /^shot-.*\.png$/.test(name) && `${stageDir}/${name}` !== stagePng) {
          await removeFile(`${stageDir}/${name}`, fsApi, deps.exec, platform);
        }
      }
    } catch {}
  }

  const candidates = herdrAppCandidates(homeDir, platform);
  let hasScreenshot = false;
  let shotError = null;
  let workingCmd = null;

  for (const cmd of candidates) {
    try {
      const res = await deps.exec(cmd, ["shot", stagePng], { timeout: 2500 });
      if (res?.code === 0) {
        if (await nonEmptyFileExists(stagePng, deps.exec, platform)) {
          hasScreenshot = true;
          workingCmd = cmd;
          shotError = null;
          break;
        }
        shotError = `${cmd} shot exited 0 without writing a non-empty PNG`;
      } else {
        const detail = String(res?.stderr || res?.stdout || "").trim();
        shotError = detail ? `${cmd} shot: ${detail}` : `${cmd} shot exited ${res?.code ?? "?"}`;
      }
    } catch (e) {
      shotError = `${cmd} shot failed: ${e?.message ?? e}`;
    }
  }
  if (!hasScreenshot) await removeFile(stagePng, fsApi, deps.exec, platform);

  const runHerdrJson = async (subarg, timeout) => {
    const list = workingCmd ? [workingCmd] : candidates;
    let lastErr = null;
    for (const cmd of list) {
      try {
        const res = await deps.exec(cmd, [subarg], { timeout });
        if (res?.code === 0) {
          try {
            return { data: JSON.parse(String(res.stdout ?? "")), error: null };
          } catch (e) {
            return { data: null, error: `${cmd} ${subarg} invalid JSON: ${e?.message ?? e}` };
          }
        }
        const detail = String(res?.stderr || res?.stdout || "").trim();
        return { data: null, error: detail ? `${cmd} ${subarg}: ${detail}` : `${cmd} ${subarg} exited ${res?.code ?? "?"}` };
      } catch (e) {
        lastErr = `${cmd} ${subarg} failed: ${e?.message ?? e}`;
      }
    }
    return { data: null, error: lastErr ?? `${subarg} unavailable` };
  };

  const readLayoutState = async () => {
    try {
      const text = await deps.readTextFile(`${appDir}/layouts/.state/${layoutName}.json`);
      if (text == null) return { data: null, error: null };
      return { data: JSON.parse(text), error: null };
    } catch (e) {
      return { data: null, error: `layout click state error: ${e?.message ?? e}` };
    }
  };

  const readErrorFiles = async () => {
    const names = new Set([
      "keys.error",
      "settings.error",
      "programs.error",
      `layouts/${layoutName}.error`,
      "mods/ob-feedback.error",
      "mods/ob-settings.error",
      "mods/ob-tabs.error",
    ]);
    if (fsApi?.readdir) {
      try {
        const extra = await fsApi.readdir(appDir);
        for (const n of extra) {
          if (typeof n === "string" && n.endsWith(".error")) names.add(n);
        }
      } catch {
        // Ignore synchronous OutsideRoots throws when appDir sits outside home().
      }
    }
    const out = [];
    for (const name of [...names].sort()) {
      try {
        const text = await deps.readTextFile(`${appDir}/${name}`);
        if (text != null && String(text).trim()) out.push({ name, text: String(text) });
      } catch {}
    }
    return out;
  };

  const [statusRes, lsRes, stateRes, errorFiles] = await Promise.all([
    runHerdrJson("status", 2000),
    runHerdrJson("ls", 2000),
    readLayoutState(),
    readErrorFiles(),
  ]);

  const capture = {
    version: 1,
    capturedAt,
    isoTime,
    layoutName,
    layouts,
    window: win,
    appSettings,
    updates: appUpdates,
    focused,
    layoutTree,
    layoutClickState: stateRes.data,
    spaces,
    panes,
    agents,
    terminals: sanitizedTerminals,
    machines,
    keys: keyList,
    sharedState,
    providerCounts,
    hasScreenshot,
    screenshotPath: hasScreenshot ? stageRel : null,
    shotError,
    appStatus: statusRes.data,
    statusError: statusRes.error,
    appWorld: lsRes.data,
    lsError: lsRes.error,
    layoutStateError: stateRes.error,
    errorFiles,
  };

  const stageText = JSON.stringify(capture, null, 2) + "\n";
  let curStageText = null;
  try { curStageText = await deps.readTextFile(stageJson); } catch { curStageText = null; }
  await deps.writeTextFile(stageJson, stageText, curStageText);
  return capture;
}
