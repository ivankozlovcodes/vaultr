// keysfile.js: safe, minimal edits of keys.json text. Pure (no herdr imports) so it runs under node
// for the offline tests ($S/obsidian-layout/test-keysfile.mjs).
//
// The rule: only the one section being edited is re-rendered; every other byte of the file stays as
// it was (other sections, unknown top-level content, key order, escapes like "send:\u0017").
// Inside the edited section each untouched entry keeps its exact text ("ctrl-p":"x" stays spaced as
// written); only separators and the new/removed entries change. Every result is re-parsed and
// compared with the intended meaning before it is returned: on any mismatch the edit throws.

// ------------------------------------------------------------------ chords
const MOD_WORDS = {
  ctrl: "ctrl", control: "ctrl", secondary: "ctrl",
  alt: "alt", option: "alt", opt: "alt",
  shift: "shift",
  cmd: "cmd", super: "cmd", win: "cmd", meta: "cmd", platform: "cmd", command: "cmd",
  fn: "fn", function: "fn",
};
const MOD_ORDER = ["ctrl", "alt", "shift", "cmd", "fn"];
const KEY_ALIAS = { esc: "escape", return: "enter", del: "delete", pgup: "pageup", pgdn: "pagedown", " ": "space", ins: "insert" };
// US layout: a shifted symbol is the same physical chord as shift + its base key ("ctrl-|" = "ctrl-shift-\").
const SHIFTED = {
  "?": "/", "|": "\\", "+": "=", "_": "-", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
  "&": "7", "*": "8", "(": "9", ")": "0", "~": "`", ":": ";", "\"": "'", "<": ",", ">": ".", "{": "[", "}": "]",
};

// "ctrl-shift-p" -> { mods: ["ctrl","shift"], words: ["ctrl","shift"], key: "p" } (one stroke).
export function parseStroke(stroke) {
  const s = String(stroke ?? "");
  let raw;
  if (s === "-") raw = ["-"];
  else if (s.endsWith("--")) raw = [...s.slice(0, -2).split("-").filter((x) => x !== ""), "-"];
  else raw = s.split("-");
  const key = raw.pop() ?? "";
  const mods = [];
  const words = [];
  for (const w of raw) {
    const m = MOD_WORDS[w.toLowerCase()];
    if (!m) return null; // not a chord we understand
    if (!mods.includes(m)) { mods.push(m); words.push(w.toLowerCase()); }
  }
  if (!key) return null;
  return { mods, words, key };
}

// Canonical form for comparing chords: modifiers in a fixed order, key lowercased, aliases and
// US shifted symbols folded. Sequences ("ctrl-k ctrl-s") are canonicalized stroke by stroke.
export function canon(chord) {
  return String(chord ?? "").trim().split(/\s+/).map((stroke) => {
    const p = parseStroke(stroke);
    if (!p) return stroke.toLowerCase();
    let key = p.key.length === 1 ? p.key.toLowerCase() : p.key.toLowerCase();
    key = KEY_ALIAS[key] ?? key;
    const mods = new Set(p.mods);
    if (SHIFTED[key]) { key = SHIFTED[key]; mods.add("shift"); }
    return [...MOD_ORDER.filter((m) => mods.has(m)), key].join("-");
  }).join(" ");
}

// The spelling we write for a new binding: modifiers ctrl, alt, shift, cmd, fn (the order the
// person's file uses: "ctrl-alt-c", "alt-shift-h"), the platform word kept as given, key lowercased
// when it is a letter. Returns null for something that isn't a chord (a lone modifier, empty).
export function writeForm(chord) {
  const strokes = String(chord ?? "").trim().split(/\s+/).filter(Boolean);
  if (!strokes.length) return null;
  const out = [];
  for (const stroke of strokes) {
    const p = parseStroke(stroke);
    if (!p) return null;
    if (MOD_WORDS[p.key.toLowerCase()]) return null; // "ctrl-shift" alone
    // The platform modifier keeps the word it was given ("super", "cmd"); others use our words.
    const word = (m) => {
      if (m !== "cmd") return m;
      const w = p.words[p.mods.indexOf(m)];
      return ["super", "win", "cmd"].includes(w) ? w : "cmd";
    };
    const mods = MOD_ORDER.filter((m) => p.mods.includes(m)).map(word);
    const key = /^[A-Za-z]$/.test(p.key) ? p.key.toLowerCase() : (KEY_ALIAS[p.key.toLowerCase()] ?? (p.key.length > 1 ? p.key.toLowerCase() : p.key));
    out.push([...mods, key].join("-"));
  }
  return out.join(" ");
}

// ------------------------------------------------------------------ scanning
const WS = new Set([" ", "\t", "\n", "\r"]);
function skipWs(t, i) { while (i < t.length && WS.has(t[i])) i++; return i; }
function scanString(t, i) {
  // t[i] === '"'; returns index just after the closing quote.
  i++;
  while (i < t.length) {
    const c = t[i];
    if (c === "\\") { i += 2; continue; }
    if (c === "\"") return i + 1;
    i++;
  }
  throw new Error("unterminated string");
}
function scanValue(t, i) {
  const c = t[i];
  if (c === "\"") return scanString(t, i);
  if (c === "{" || c === "[") {
    let depth = 0;
    while (i < t.length) {
      const d = t[i];
      if (d === "\"") { i = scanString(t, i); continue; }
      if (d === "{" || d === "[") depth++;
      else if (d === "}" || d === "]") { depth--; if (depth === 0) return i + 1; }
      i++;
    }
    throw new Error("unterminated object");
  }
  // number, true, false, null
  while (i < t.length && !WS.has(t[i]) && t[i] !== "," && t[i] !== "}" && t[i] !== "]") i++;
  return i;
}
// The members of the object whose "{" is at `open`: [{key, keyStart, valueStart, valueEnd}], close.
function members(t, open) {
  const out = [];
  let i = skipWs(t, open + 1);
  if (t[i] === "}") return { list: out, close: i };
  for (;;) {
    if (t[i] !== "\"") throw new Error(`expected a key at ${i}`);
    const keyStart = i;
    const keyEnd = scanString(t, i);
    const key = JSON.parse(t.slice(keyStart, keyEnd));
    i = skipWs(t, keyEnd);
    if (t[i] !== ":") throw new Error(`expected ':' at ${i}`);
    const valueStart = skipWs(t, i + 1);
    const valueEnd = scanValue(t, valueStart);
    out.push({ key, keyStart, keyEnd, valueStart, valueEnd });
    i = skipWs(t, valueEnd);
    if (t[i] === ",") { i = skipWs(t, i + 1); continue; }
    if (t[i] === "}") return { list: out, close: i };
    throw new Error(`expected ',' or '}' at ${i}`);
  }
}
function lineIndent(t, at) {
  const ls = t.lastIndexOf("\n", at - 1) + 1;
  const ws = t.slice(ls, at);
  return /^[ \t]*$/.test(ws) ? ws : null; // null: not first thing on its line
}

// An action's identity: the string itself, or a stable JSON text for {command, args} objects.
export function actionId(value) {
  if (typeof value === "string") return value;
  return stableJson(value);
}
export function stableJson(v) {
  if (Array.isArray(v)) return `[${v.map(stableJson).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${stableJson(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}

// Parse keys.json text. Throws (with JSON.parse's message) when it isn't valid JSON or isn't an object.
// -> { text, data, bom, eol, top: [{key, keyStart, valueStart, valueEnd}], rootOpen, rootClose,
//      sections: { name: { pairs: [{key, chord (=key), action, entry, valueRaw}], inline, member } } }
export function parseKeys(text) {
  const src = String(text ?? "");
  const bom = src.startsWith("\uFEFF") ? 1 : 0;
  const data = JSON.parse(src.slice(bom));
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("keys.json is not a JSON object");
  const rootOpen = skipWs(src, bom);
  const { list: top, close: rootClose } = members(src, rootOpen);
  const sections = {};
  for (const m of top) {
    // Duplicate top-level names: JSON.parse keeps the last one, so do we.
    if (src[m.valueStart] !== "{") { sections[m.key] = { notObject: true, member: m, pairs: [] }; continue; }
    const { list } = members(src, m.valueStart);
    const pairs = list.map((p) => {
      const valueRaw = src.slice(p.valueStart, p.valueEnd);
      const value = JSON.parse(valueRaw);
      return { key: p.key, action: actionId(value), value, entry: src.slice(p.keyStart, p.valueEnd), valueRaw };
    });
    const inline = !src.slice(m.valueStart, m.valueEnd).includes("\n");
    const innerIndent = list.length ? lineIndent(src, list[0].keyStart) : null;
    sections[m.key] = { pairs, inline, member: m, innerIndent };
  }
  return { text: src, data, bom, eol: src.includes("\r\n") ? "\r\n" : "\n", top, rootOpen, rootClose, sections };
}

// The bindings of one section as the app sees them (last duplicate wins), in file order.
export function effectivePairs(pairs) {
  const last = new Map();
  pairs.forEach((p, i) => last.set(p.key, i));
  return pairs.filter((p, i) => last.get(p.key) === i);
}

// ------------------------------------------------------------------ edits on a pair list
function newPair(chord, action) {
  const keyRaw = JSON.stringify(chord);
  const valueRaw = JSON.stringify(action);
  return { key: chord, action, value: action, entry: `${keyRaw}: ${valueRaw}`, valueRaw };
}

// bind: give `action` the chord. If another action holds the same chord (any spelling) in this
// section, returns { conflict: [actions] } unless `force`. Same action already there: unchanged.
export function bindPairs(pairs, chord, action, force = false) {
  const c = canon(chord);
  const same = pairs.filter((p) => canon(p.key) === c);
  if (same.length && same.every((p) => p.action === action)) return { pairs, changed: false };
  const others = same.filter((p) => p.action !== action);
  if (others.length && !force) return { pairs, changed: false, conflict: [...new Set(others.map((p) => p.action))] };
  const kept = pairs.filter((p) => canon(p.key) !== c);
  const lastMine = kept.map((p) => p.action).lastIndexOf(action);
  const next = [...kept];
  next.splice(lastMine >= 0 ? lastMine + 1 : next.length, 0, newPair(chord, action));
  return { pairs: next, changed: true, took: [...new Set(others.map((p) => p.action))] };
}
export function unbindPairs(pairs, chord, action) {
  const c = canon(chord);
  const next = pairs.filter((p) => !(canon(p.key) === c && (action == null || p.action === action)));
  return { pairs: next, changed: next.length !== pairs.length };
}
export function clearPairs(pairs, action) {
  const next = pairs.filter((p) => p.action !== action);
  return { pairs: next, changed: next.length !== pairs.length };
}
// restore: the action gets exactly `defaults` (in that order), at the place its first binding was.
// A default chord another action holds is taken back (reported in `took`).
// `order` (optional): actions in their home order; an action with no binding left goes back after
// the last pair of an action that comes before it there (so a restore lands where it was).
export function restorePairs(pairs, action, defaults, order) {
  const want = defaults.map(canon);
  const at = pairs.findIndex((p) => p.action === action);
  const took = new Set();
  const next = [];
  let insertAt = -1;
  pairs.forEach((p, i) => {
    if (i === at) insertAt = next.length;
    if (p.action === action) return;
    if (want.includes(canon(p.key))) { took.add(p.action); return; }
    next.push(p);
  });
  if (insertAt < 0) {
    insertAt = next.length;
    const rank = order ? order.indexOf(action) : -1;
    if (rank >= 0) {
      let after = -1;
      next.forEach((p, i) => { const r = order.indexOf(p.action); if (r >= 0 && r < rank) after = i; });
      const firstLater = next.findIndex((p) => { const r = order.indexOf(p.action); return r > rank; });
      insertAt = after >= 0 ? after + 1 : firstLater >= 0 ? firstLater : next.length;
    }
  }
  // Keep the exact original text of default chords the action already had.
  const mine = pairs.filter((p) => p.action === action);
  const fresh = defaults.map((d) => mine.find((p) => canon(p.key) === canon(d) && p.key === d) ?? newPair(d, action));
  next.splice(insertAt, 0, ...fresh);
  const changed = next.length !== pairs.length || next.some((p, i) => p !== pairs[i]);
  return { pairs: next, changed, took: [...took] };
}

// ------------------------------------------------------------------ rendering one section back
function renderSection(parsed, name, pairs) {
  const sec = parsed.sections[name];
  const eol = parsed.eol;
  if (sec?.inline) {
    if (!pairs.length) return "{}";
    return `{ ${pairs.map((p) => p.entry).join(", ")} }`;
  }
  const t = parsed.text;
  const outer = sec ? (lineIndent(t, sec.member.keyStart) ?? "  ") : topIndent(parsed);
  const unit = outer.length ? outer : "  ";
  const inner = sec?.innerIndent ?? outer + unit;
  if (!pairs.length) return "{}";
  return `{${eol}${pairs.map((p) => inner + p.entry).join(`,${eol}`)}${eol}${outer}}`;
}
function topIndent(parsed) {
  for (const m of parsed.top) { const ind = lineIndent(parsed.text, m.keyStart); if (ind != null) return ind; }
  return "  ";
}

// The new file text with section `name` holding `pairs` (removed when empty). Throws on a section
// that isn't an object (we never rewrite what we don't understand).
export function withSection(parsed, name, pairs) {
  const t = parsed.text;
  const sec = parsed.sections[name];
  if (sec?.notObject) throw new Error(`"${name}" in keys.json is not an object; fix it by hand first`);
  const eol = parsed.eol;
  if (sec) {
    const m = sec.member;
    if (pairs.length) return t.slice(0, m.valueStart) + renderSection(parsed, name, pairs) + t.slice(m.valueEnd);
    // Remove the whole member, with one adjoining comma. Duplicate earlier members of the same name
    // are left alone (JSON.parse ignored them before and still does).
    const idx = parsed.top.indexOf(m);
    if (parsed.top.length === 1) return t.slice(0, parsed.rootOpen + 1) + eol + t.slice(parsed.rootClose);
    if (idx > 0) return t.slice(0, parsed.top[idx - 1].valueEnd) + t.slice(m.valueEnd);
    return t.slice(0, m.keyStart) + t.slice(parsed.top[1].keyStart);
  }
  if (!pairs.length) return t;
  const indent = topIndent(parsed);
  const body = `${JSON.stringify(name)}: ${renderSection(parsed, name, pairs)}`;
  if (!parsed.top.length) return t.slice(0, parsed.rootOpen + 1) + eol + indent + body + eol + t.slice(parsed.rootClose);
  const last = parsed.top[parsed.top.length - 1];
  return t.slice(0, last.valueEnd) + `,${eol}${indent}${body}` + t.slice(last.valueEnd);
}

// ------------------------------------------------------------------ the one entry point
export function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
}

// op: { kind: "bind", chord, action, force } | { kind: "unbind", chord, action } |
//     { kind: "clear", action } | { kind: "restore", action, defaults, order? }
// -> { text (new file text, === input when nothing changed), changed, conflict?, took? }
// Throws when the input isn't valid JSON, the section isn't an object, or the result would not
// mean exactly "the same file with this one section changed".
export function applyEdit(text, scope, op) {
  const parsed = parseKeys(text);
  const sec = parsed.sections[scope];
  if (sec?.notObject) throw new Error(`"${scope}" in keys.json is not an object; fix it by hand first`);
  const pairs = sec?.pairs ?? [];
  let r;
  if (op.kind === "bind") {
    const chord = writeForm(op.chord);
    if (!chord) throw new Error(`"${op.chord}" is not a key chord`);
    r = bindPairs(pairs, chord, op.action, op.force);
  } else if (op.kind === "unbind") r = unbindPairs(pairs, op.chord, op.action);
  else if (op.kind === "clear") r = clearPairs(pairs, op.action);
  else if (op.kind === "restore") r = restorePairs(pairs, op.action, op.defaults ?? [], op.order);
  else throw new Error(`unknown edit ${op.kind}`);
  if (r.conflict || !r.changed) return { text: parsed.text, changed: false, conflict: r.conflict };
  const next = withSection(parsed, scope, r.pairs);
  verify(parsed, next, scope, r.pairs);
  return { text: next, changed: next !== parsed.text, took: r.took ?? [] };
}

// The new text must parse, keep every other top-level member identical in meaning, and hold
// exactly `pairs` (last duplicate wins) in `scope`.
export function verify(parsed, next, scope, pairs) {
  let after;
  try { after = JSON.parse(next.startsWith("\uFEFF") ? next.slice(1) : next); } catch (e) { throw new Error(`internal: the edit produced invalid JSON (${e.message}); nothing was written`); }
  const before = parsed.data;
  const names = new Set([...Object.keys(before), ...Object.keys(after)]);
  for (const k of names) {
    if (k === scope) continue;
    if (!deepEqual(before[k], after[k])) throw new Error(`internal: the edit would change "${k}"; nothing was written`);
  }
  if (!pairs.length) {
    if (Object.prototype.hasOwnProperty.call(after, scope)) {
      // Only an earlier duplicate of the same name can remain.
      const dups = parsed.top.filter((m) => m.key === scope).length;
      if (dups < 2) throw new Error("internal: the emptied section is still there; nothing was written");
    }
    return;
  }
  const want = {};
  for (const p of pairs) want[p.key] = p.value;
  if (!deepEqual(after[scope], want)) throw new Error(`internal: "${scope}" would not hold the intended keys; nothing was written`);
  // Key order inside the section must be what we rendered. (JS objects list integer-like keys
  // first; a chord is never one, but don't fail on it.)
  const intLike = Object.keys(want).some((k) => /^\d+$/.test(k));
  if (!intLike && Object.keys(after[scope]).join("\n") !== Object.keys(want).join("\n")) {
    throw new Error("internal: key order changed; nothing was written");
  }
}
