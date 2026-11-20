// Provider helpers & unified facade; zero program names in kit/.

import { matchQuery, snippet as snippetOf } from "./fuzzy.js";

function indentBlock(code) {
  return String(code ?? "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => (line.length > 0 ? `    ${line}` : ""))
    .join("\n");
}

export function parseProviderIndex(indexText) {
  if (typeof indexText !== "string" || !indexText.trim()) {
    throw new Error("providers/index.json is missing or empty");
  }
  let parsed;
  try {
    parsed = JSON.parse(indexText);
  } catch (e) {
    throw new Error(`providers/index.json is invalid JSON: ${e?.message ?? e}`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error("providers/index.json must be a JSON array");
  }
  const seen = new Set();
  const ids = [];
  for (const item of parsed) {
    if (typeof item !== "string" || !/^[a-z0-9][a-z0-9_-]*$/.test(item) || seen.has(item)) {
      throw new Error(`invalid provider id in index.json: ${JSON.stringify(item)}`);
    }
    seen.add(item);
    ids.push(item);
  }
  return ids;
}

export function assembleScanner(scanCore, providers) {
  const parts = [String(scanCore ?? "").trimEnd()];
  (providers || []).forEach((p, idx) => {
    if (!p || !p.id) return;
    const idJson = JSON.stringify(String(p.id));
    parts.push(`def _load_provider_${idx}():`);
    if (p.reader) {
      parts.push(indentBlock(p.reader));
      parts.push(`    register_reader(${idJson}, sniff, events, locals().get("find_subagent"))`);
    }
    if (p.scan) parts.push(indentBlock(p.scan));
    parts.push(`_load_provider_${idx}()`);
  });
  parts.push("run_scanner_main()");
  return `${parts.join("\n\n")}\n`;
}

export function assembleReader(readerMain, providers, mode = "entries") {
  const m = mode === "viewer" ? "entries" : (mode || "entries");
  const parts = [String(readerMain ?? "").trimEnd()];
  (providers || []).forEach((p, idx) => {
    if (!p || !p.id || !p.reader) return;
    const idJson = JSON.stringify(String(p.id));
    parts.push(`def _load_reader_${idx}():`);
    parts.push(indentBlock(p.reader));
    parts.push(`    register_reader(${idJson}, sniff, events, locals().get("find_subagent"))`);
    parts.push(`_load_reader_${idx}()`);
  });
  parts.push(`run_reader_main(${JSON.stringify(String(m))})`);
  return `${parts.join("\n\n")}\n`;
}

export async function loadProviders({ readTextFile, providersDir, needScan = false, needManifest = false }) {
  if (typeof readTextFile !== "function") throw new Error("readTextFile is required");
  const indexText = await readTextFile(`${providersDir}/index.json`);
  const ids = parseProviderIndex(indexText);
  const loaded = [];
  for (const id of ids) {
    const base = `${providersDir}/${id}`;
    const manifestText = await readTextFile(`${base}/manifest.json`).catch(() => null);
    if (!manifestText) continue;
    let manifest = null;
    if (needManifest) {
      manifest = JSON.parse(manifestText);
    }
    const reader = await readTextFile(`${base}/reader.py`).catch(() => null);
    let scan = null;
    if (needScan) {
      scan = await readTextFile(`${base}/scan.py`).catch(() => null);
      if (!scan) continue;
    } else if (!reader) {
      continue;
    }
    loaded.push({ id, manifest, reader, scan });
  }
  return loaded;
}

const looksLikePath = (s) => typeof s === "string" && (s.includes("/") || s.includes("\\") || s.endsWith(".jsonl"));
const baseName = (p) => String(p ?? "").replace(/\/+$/, "").split("/").pop();
const machineOfAddr = (addr) => {
  const s = String(addr ?? "");
  const i = s.indexOf("/");
  return i >= 0 ? s.slice(0, i) : null;
};
const normMachine = (m) => (!m || m === "local" ? null : m);

function parseJsonLine(r) {
  const line = String(r?.stdout ?? "").trim().split("\n").pop() ?? "";
  if (!line.startsWith("{")) {
    const err = (r?.stderr || `python3 exited ${r?.code ?? "?"}`).trim().split("\n").pop();
    return { ok: false, error: err || "reader produced no JSON" };
  }
  try {
    return { ok: true, data: JSON.parse(line) };
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) };
  }
}

function runTitleFor(r, noun) {
  if (r?.title) return r.title;
  const steps = Array.isArray(r?.steps) ? r.steps : [];
  if (steps.length > 1 && r?.mode === "chain") {
    const s = steps.map((x) => x?.label || x?.agent).filter(Boolean).join(" → ");
    if (s) return s;
  }
  if (steps.length > 1 && r?.mode === "parallel") {
    const names = [...new Set(steps.map((x) => x?.label || x?.agent).filter(Boolean))];
    if (names.length === 1) return `${names[0]} ×${steps.length}`;
    if (names.length > 1) return names.join(" ∥ ");
  }
  const first = steps[0];
  return first?.label || first?.agent || first?.task || noun || r?.mode || "run";
}

function activeRunStep(r) {
  const steps = Array.isArray(r?.steps) ? r.steps : [];
  return steps.find((x) => (x?.status === "running" || x?.status === "working") && x?.startedAt)
    ?? steps.find((x) => x?.status === "running" || x?.status === "working")
    ?? steps[steps.length - 1]
    ?? null;
}

function buildSearchGroups(sources, results, query, opts = {}) {
  const perGroup = opts.perGroup ?? 5, total = opts.total ?? 200;
  const byId = new Map((sources ?? []).map((s) => [s.id, s]));
  const groups = [];
  for (const r of results ?? []) {
    const src = r && byId.get(r.id);
    if (!src || !Array.isArray(r.msgs)) continue;
    const hits = [];
    for (const msg of r.msgs) {
      const m = matchQuery(query, msg.text, { caseSensitive: opts.caseSensitive });
      if (!m) continue;
      hits.push({ role: msg.role, ts: msg.ts ?? null, i: msg.i, text: msg.text, score: m.score, snippet: snippetOf(msg.text, m.spans) });
    }
    if (!hits.length) continue;
    hits.sort((a, b) => (b.score - a.score) || (Number(b.ts) || 0) - (Number(a.ts) || 0) || (b.i - a.i));
    groups.push({ id: src.id, path: src.path, label: src.label, kind: src.kind, parent: src.parent, count: hits.length, best: hits[0].score, hits });
  }
  groups.sort((a, b) => b.best - a.best);
  let left = total;
  const out = [];
  for (const g of groups) {
    if (left <= 0) break;
    const shown = g.hits.slice(0, Math.min(perGroup, left));
    left -= shown.length;
    out.push({ ...g, hits: shown });
  }
  return out;
}

export function makeProvider({ feed, exec, readTextFile, appHome }) {
  const cache = { scan: null, scanProviders: null, readers: new Map() };
  const rawFeed = () => (typeof feed === "function" ? feed() : null);
  const providersDir = () => `${typeof appHome === "function" ? appHome() : ""}/mods/ob-feed/providers`;

  function list() {
    const raw = rawFeed()?.providers;
    if (!raw) return [];
    const items = Array.isArray(raw)
      ? raw.filter((m) => m && typeof m === "object" && m.id)
      : Object.entries(raw)
          .filter(([, m]) => m && typeof m === "object")
          .map(([id, m]) => ({ id, ...m }));
    return items.map((m) => ({
      id: m.id,
      name: m.name ?? m.id,
      noun: m.noun ?? m.name ?? m.id,
      caps: Array.isArray(m.caps) ? [...m.caps] : [],
    }));
  }

  function of(x) {
    if (!x) return null;
    const id = typeof x === "string" ? x : (x.provider ?? null);
    if (!id) return null;
    const m = list().find((p) => p.id === id) ?? null;
    if (!m) return null;
    return { ...m, can: (cap) => m.caps.includes(cap) };
  }

  function sessions() {
    const terms = rawFeed()?.terms;
    if (!terms || typeof terms !== "object") return [];
    const out = [];
    for (const [address, info] of Object.entries(terms)) {
      if (!info || typeof info !== "object") continue;
      const pid = info.provider ?? null;
      const p = of(pid);
      const sess = info.session ?? null;
      const txRaw = info.transcript ?? (looksLikePath(sess) ? sess : null);
      const transcript = p && !p.can("transcript") ? null : txRaw;
      const title = info.title ?? info.name ?? null;
      out.push({
        address,
        machine: info.machine !== undefined ? normMachine(info.machine) : machineOfAddr(address),
        provider: pid,
        title,
        name: title,
        session: sess,
        transcript,
        lastTool: info.lastTool ?? null,
        pid: info.pid ?? null,
        cwd: info.cwd ?? null,
        sessionGuess: Boolean(info.sessionGuess),
        updatedAt: info.updatedAt ?? null,
      });
    }
    return out;
  }

  function session(address) {
    if (!address) return null;
    return sessions().find((s) => s.address === address) ?? null;
  }

  function subagents(filter = {}) {
    const f = rawFeed();
    if (!f) return [];
    const hasParent = filter && Object.prototype.hasOwnProperty.call(filter, "parent") && filter.parent !== undefined;
    const hasMachine = filter && Object.prototype.hasOwnProperty.call(filter, "machine") && filter.machine !== undefined;
    const wantMachine = hasMachine ? normMachine(filter.machine) : undefined;
    const out = [];

    for (const r of f.runs ?? []) {
      if (!r || typeof r !== "object") continue;
      const machine = normMachine(r.machine);
      const parent = r.parent ?? null;
      if (hasParent && parent !== filter.parent) continue;
      if (hasMachine && machine !== wantMachine) continue;
      const pid = r.provider ?? null;
      const p = of(pid);
      const steps = Array.isArray(r.steps) ? r.steps : [];
      const cur = activeRunStep(r);
      const lt = cur?.tools?.[cur.tools.length - 1];
      const txRaw = cur?.session || cur?.transcript || steps.map((s) => s?.session || s?.transcript).find(Boolean) || null;
      const live = Boolean(r.live);
      const ended = r.ended !== undefined ? Boolean(r.ended) : Boolean(!live && r.state !== "running" && r.state !== "queued");
      const at = live ? (r.lastUpdate ?? r.startedAt ?? 0) : (r.endedAt ?? r.lastUpdate ?? r.startedAt ?? 0);
      out.push({
        kind: "run",
        key: r.key,
        machine,
        parent,
        provider: pid,
        id: r.id ?? r.key,
        short: r.short ?? String(r.id ?? "").slice(0, 8),
        mode: r.mode ?? null,
        title: runTitleFor(r, p?.noun),
        state: r.state ?? (live ? "running" : "done"),
        live,
        ended,
        at,
        startedAt: r.startedAt ?? null,
        endedAt: r.endedAt ?? null,
        lastUpdate: r.lastUpdate ?? null,
        transcript: p && !p.can("transcript") ? null : txRaw,
        lastTool: lt ? { tool: lt.tool, args: lt.args ?? "" } : null,
        cwd: r.cwd ?? null,
        parentGuess: r.parentGuess ?? null,
        parentSession: r.parentSession ?? null,
        tokens: r.tokens ?? null,
        cost: r.cost ?? null,
        turns: r.turns ?? null,
        toolCount: r.toolCount ?? null,
        error: r.error ?? null,
        log: r.log ?? null,
        dir: r.dir ?? null,
        currentStep: r.currentStep ?? null,
        steps,
      });
    }

    for (const c of f.subagents ?? []) {
      if (!c || typeof c !== "object") continue;
      const machine = normMachine(c.machine);
      const parent = c.parent ?? null;
      if (hasParent && parent !== filter.parent) continue;
      if (hasMachine && machine !== wantMachine) continue;
      const pid = c.provider ?? null;
      const p = of(pid);
      const live = Boolean(c.live);
      const ended = Boolean(c.ended);
      out.push({
        kind: "agent",
        key: c.key,
        machine,
        parent,
        provider: pid,
        id: c.id,
        title: c.title || c.desc || c.type || p?.noun || "agent",
        type: c.type ?? null,
        desc: c.desc ?? null,
        model: c.model ?? null,
        state: c.state ?? (live ? "working" : (ended ? "ok" : null)),
        live,
        ended,
        at: c.at ?? c.updatedAt ?? 0,
        updatedAt: c.updatedAt ?? null,
        transcript: p && !p.can("transcript") ? null : (c.transcript ?? null),
        lastTool: c.lastTool ?? null,
        outTokens: c.outTokens ?? null,
        toolCount: c.toolCount ?? null,
        turns: c.turns ?? null,
      });
    }
    return out;
  }

  async function loadReaderScript(mode) {
    const m = mode === "viewer" ? "entries" : (mode || "entries");
    if (cache.readers.has(m)) return { ok: true, script: cache.readers.get(m) };
    if (typeof readTextFile !== "function") return { ok: false, reason: "missing", error: "readTextFile unavailable" };
    const dir = providersDir();
    const indexText = await readTextFile(`${dir}/index.json`).catch(() => null);
    if (!indexText) return { ok: false, reason: "missing", error: "providers/index.json is missing" };
    try {
      const [readerMain, readers] = await Promise.all([
        readTextFile(`${dir}/reader_main.py`).catch(() => null),
        loadProviders({ readTextFile, providersDir: dir }),
      ]);
      if (!readerMain || !readers.length) {
        return { ok: false, reason: "missing", error: !readerMain ? "reader_main.py is missing" : "no readers found" };
      }
      const script = assembleReader(readerMain, readers, m);
      cache.readers.set(m, script);
      return { ok: true, script };
    } catch (e) {
      return { ok: false, reason: "failed", error: String(e?.message ?? e) };
    }
  }

  async function loadScannerScript() {
    if (cache.scan && cache.scanProviders) {
      return { ok: true, script: cache.scan, providers: cache.scanProviders };
    }
    if (typeof readTextFile !== "function") return { ok: false, reason: "missing", error: "readTextFile unavailable" };
    const dir = providersDir();
    const indexText = await readTextFile(`${dir}/index.json`).catch(() => null);
    if (!indexText) return { ok: false, reason: "missing", error: "providers/index.json is missing" };
    try {
      const [scanCore, providers] = await Promise.all([
        readTextFile(`${dir}/scan_core.py`).catch(() => null),
        loadProviders({ readTextFile, providersDir: dir, needScan: true, needManifest: true }),
      ]);
      if (!scanCore) return { ok: false, reason: "missing", error: "scan_core.py is missing" };
      if (!providers.length) return { ok: false, reason: "missing", error: "no agent providers found" };
      const providerMap = Object.fromEntries(providers.map((p) => [p.id, p.manifest]));
      const script = assembleScanner(scanCore, providers);
      cache.scan = script;
      cache.scanProviders = providerMap;
      return { ok: true, script, providers: providerMap };
    } catch (e) {
      const msg = String(e?.message ?? e);
      return { ok: false, reason: msg.includes("missing") ? "missing" : "failed", error: msg };
    }
  }

  function resolveTarget(x) {
    if (typeof x === "string") {
      const s = session(x);
      if (s) return { p: of(s), providerId: s.provider, path: s.transcript, machine: s.machine, id: null };
      if (looksLikePath(x)) return { p: null, providerId: null, path: x, machine: null, id: null };
      const sub = subagents().find((a) => a.key === x || a.id === x) ?? null;
      if (sub) return { p: of(sub), providerId: sub.provider, path: sub.transcript, machine: sub.machine, id: sub.id };
      return { p: null, providerId: null, path: null, machine: machineOfAddr(x), id: null };
    }
    if (x && typeof x === "object") {
      const p = of(x);
      const pid = p?.id ?? x.provider ?? null;
      const path = x.path ?? x.transcript ?? (looksLikePath(x.session) ? x.session : null);
      const machine = x.machine !== undefined ? normMachine(x.machine) : machineOfAddr(x.address ?? x.parent);
      return { p, providerId: pid, path, machine, id: x.id ?? null };
    }
    return { p: null, providerId: null, path: null, machine: null, id: null };
  }

  async function runReader(mode, args, machine, timeout) {
    if (typeof exec !== "function") return { ok: false, reason: "failed", error: "exec unavailable" };
    const loaded = await loadReaderScript(mode);
    if (!loaded.ok) return loaded;
    try {
      const r = await exec("python3", ["-c", loaded.script, ...args], { ...(machine ? { on: machine } : {}), timeout });
      const parsed = parseJsonLine(r);
      if (!parsed.ok) return { ok: false, reason: "failed", error: parsed.error };
      return { ok: true, data: parsed.data };
    } catch (e) {
      return { ok: false, reason: "failed", error: String(e?.message ?? e) };
    }
  }

  async function transcript(x, opts = {}) {
    const t = resolveTarget(x);
    if (t.p && !t.p.can("transcript")) {
      return { ok: false, reason: "unsupported", error: `${t.p.name} does not support transcripts` };
    }
    const wantFind = Boolean(opts?.find) || (!t.path && Boolean(t.id));
    if (wantFind) {
      if (!t.id) return { ok: false, reason: "missing", error: "no transcript path" };
      const res = await runReader("entries", ["--find", String(t.id), ...(t.providerId ? [String(t.providerId)] : [])], t.machine, opts?.timeout ?? 15000);
      if (!res.ok) return res;
      if (res.data?.error) return { ok: false, reason: "failed", error: res.data.error };
      if (!res.data?.path) return { ok: false, reason: "missing", error: "transcript not found" };
      return { ok: true, path: res.data.path, found: true };
    }
    if (!t.path) return { ok: false, reason: "missing", error: "no transcript path" };
    const args = [t.path, String(opts?.limit ?? 250), ...(t.providerId ? [String(t.providerId)] : [])];
    const res = await runReader("entries", args, t.machine, opts?.timeout ?? 20000);
    if (!res.ok) return res;
    const d = res.data;
    if (d.error) {
      const reason = String(d.error).startsWith("can't read") ? "missing" : "failed";
      return { ok: false, reason, error: d.error, path: d.path ?? t.path };
    }
    return {
      ok: true,
      path: d.path ?? t.path,
      entries: Array.isArray(d.entries) ? d.entries : [],
      format: d.format ?? null,
      truncated: Boolean(d.truncated),
      size: d.size ?? 0,
    };
  }

  async function usage(x, opts = {}) {
    const t = resolveTarget(x);
    if (t.p && !t.p.can("usage")) {
      return { ok: false, reason: "unsupported", error: `${t.p.name} does not support usage` };
    }
    if (!t.path) return { ok: false, reason: "missing", error: "no transcript path" };
    const args = [t.path, opts?.cap ? String(opts.cap) : "", opts?.seen ? String(opts.seen) : "", ...(t.providerId ? [String(t.providerId)] : [])];
    const res = await runReader("usage", args, t.machine, opts?.timeout ?? 8000);
    if (!res.ok) return res;
    const d = res.data;
    if (d.error) {
      const reason = String(d.error).startsWith("can't read") ? "missing" : "failed";
      return { ok: false, reason, error: d.error };
    }
    if (d.unchanged) return { ok: true, unchanged: true, sig: d.sig ?? opts?.seen ?? null };
    return {
      ok: true,
      unchanged: false,
      turns: Array.isArray(d.turns) ? d.turns : [],
      format: d.format ?? null,
      truncated: Boolean(d.truncated),
      size: d.size ?? 0,
      sig: d.sig ?? null,
      path: t.path,
    };
  }

  function searchSources(parentsSet) {
    const out = [];
    const seen = new Set();
    const add = (path, kind, label, parent, providerId) => {
      if (typeof path !== "string" || !path || seen.has(path)) return;
      if (parentsSet && !parentsSet.has(parent)) return;
      seen.add(path);
      out.push({ id: `s${out.length}`, path, kind, label: String(label || "agent"), parent: parent ?? null, providerId: providerId ?? null });
    };
    for (const s of sessions()) {
      if (s.machine) continue;
      const p = of(s);
      if (p && !p.can("search")) continue;
      add(s.transcript || (looksLikePath(s.session) ? s.session : null), "main", s.title || baseName(s.cwd) || p?.name || "agent", s.address, s.provider);
    }
    for (const item of subagents({ machine: null })) {
      const p = of(item);
      if (p && !p.can("search")) continue;
      if (item.kind === "run") {
        const steps = item.steps ?? [];
        if (steps.length) {
          for (const st of steps) {
            if (!st || typeof st !== "object") continue;
            add(st.session || st.transcript, "subagent", st.task || st.agent || item.title || "sub-agent", item.parent, item.provider);
          }
        } else {
          add(item.transcript, "subagent", item.title || "sub-agent", item.parent, item.provider);
        }
      } else {
        add(item.transcript, "subagent", item.desc || item.type || item.title || "sub-agent", item.parent, item.provider);
      }
    }
    return out;
  }

  async function search(query, opts = {}) {
    const allProviders = list();
    if (allProviders.length && !allProviders.some((p) => p.caps.includes("search"))) {
      return { ok: false, reason: "unsupported", error: "no provider supports search" };
    }
    const parentsSet = opts?.parents ? (opts.parents instanceof Set ? opts.parents : new Set(opts.parents)) : null;
    const sources = searchSources(parentsSet);
    if (!sources.length) {
      return { ok: true, groups: [], files: [], sources: [], partial: false, skipped: 0, none: true };
    }
    const terms = String(query ?? "").split(/\s+/).filter(Boolean);
    const payload = {
      terms,
      caseSensitive: Boolean(opts?.caseSensitive),
      files: sources.map((s) => ({ id: s.id, path: s.path, ...(s.providerId ? { providerId: s.providerId } : {}) })),
    };
    const res = await runReader("search", [JSON.stringify(payload)], null, opts?.timeout ?? 15000);
    if (!res.ok) return res;
    const d = res.data;
    if (d.error) return { ok: false, reason: "failed", error: d.error };
    const files = Array.isArray(d.files) ? d.files : [];
    const groups = buildSearchGroups(sources, files, query, opts);
    return {
      ok: true,
      groups,
      files,
      sources,
      partial: Boolean(d.partial),
      skipped: d.skipped ?? 0,
      none: false,
    };
  }

  async function quota(opts = {}) {
    const targets = opts?.provider
      ? [of(opts.provider)].filter(Boolean)
      : list().map((m) => of(m.id)).filter(Boolean);
    const capable = targets.filter((p) => p.can("quota"));
    if (!capable.length) {
      return { ok: false, reason: "unsupported", error: "no provider supports quota" };
    }
    return { ok: false, reason: "missing", error: "quota reader is missing" };
  }

  async function scan(machine = null, opts = {}) {
    if (typeof exec !== "function") return { ok: false, reason: "failed", error: "exec unavailable" };
    const loaded = await loadScannerScript();
    if (!loaded.ok) return loaded;
    const { timeout, ...scanOpts } = (opts && typeof opts === "object") ? opts : {};
    const on = normMachine(machine);
    const started = Date.now();
    try {
      const r = await exec("python3", ["-c", loaded.script, JSON.stringify(scanOpts)], { ...(on ? { on } : {}), timeout: timeout ?? 20000 });
      const parsed = parseJsonLine(r);
      if (!parsed.ok) return { ok: false, reason: "failed", error: parsed.error };
      if (parsed.data?.error) return { ok: false, reason: "failed", error: parsed.data.error };
      return { ok: true, data: parsed.data, providers: loaded.providers, ms: Date.now() - started };
    } catch (e) {
      return { ok: false, reason: "failed", error: String(e?.message ?? e) };
    }
  }

  function dropCache() {
    cache.scan = null;
    cache.scanProviders = null;
    cache.readers.clear();
  }

  return { list, of, sessions, session, subagents, transcript, usage, search, quota, scan, dropCache };
}
