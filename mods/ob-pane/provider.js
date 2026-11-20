// Pure assembly helpers for per-program provider snippets; keep program names out of kit/.

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
