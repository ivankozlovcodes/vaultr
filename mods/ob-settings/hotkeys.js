// hotkeys.js: the Hotkeys tab of ob-settings. Obsidian's Settings > Hotkeys for Herdr. Every command
// of the Vaultr layout, the Sessions panel, Herdr itself and terminals, with its keys in the chosen
// keys.json section ("scope"): add (+, then press the keys), remove (x on a key), restore default,
// conflicts in red, keys a terminal treats differently in amber, inherited keys dimmed.
// A second sub-tab ("Layout") holds the window buttons and the plain-Ctrl keys this layout takes from
// terminal programs, each with a button to give it back.
//
// keys.json is edited through keysfile.js: read, change only the scope's section, verify, write
// atomically against the text just read (re-read and retry once if it changed), then check
// keys.error and put the old text back if Herdr rejects it. An invalid file is never written.
//
// ob-settings passes this tab its commands (ob-settings.<cmd>; also the test path, there is no
// keyboard in tests):
//   scope:<section>  filter:<text>  assigned:<all|assigned|unassigned>  section:<hotkeys|layout>
//   capture:<action>[@<chord>]   start "+" capture for that row (with a chord: also press it)
//   key:<chord>                  a key press during capture (the same path as on_key_down)
//   bind:<action>@<chord>  remove:<action>@<chord>  restore:<action>
//   reassign  cancel             answer a conflict ("Ctrl+B is already X")
//   window-buttons:<auto|always|never>   give-back:<chord>   focus
//   dump[:<section>]             log keys() for a section (what Herdr really uses) to stdout

import { div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, ScrollHandle, Scrollbar } from "gpui-base";
import { keys, appHome, readTextFile, writeTextFile, shared, setShared, settings, window as appWindow } from "herdr";
import { S, tc, alpha, icon, iconButton, chordParts, openMenu, tilde } from "./kit.js";
import { menuAnchor } from "./menu_anchor.js";
import { parseKeys, applyEdit, moveKey, effectivePairs, canon, writeForm, captureKeystroke, boundElsewhere, DEFAULT_SCOPE, scopeInfo, scopeWarning, listedIn, panelOnlyTag } from "./keysfile.js";
import { registry, GROUPS, LAYOUT_SCOPE, SESSIONS_SCOPE, defaultsIn, chainOf, scopeTitle, scopeShort, scopeWhere, titleFor } from "./registry.js";

const FIXED_SCOPES = [LAYOUT_SCOPE, "global", "terminal", SESSIONS_SCOPE];
const SCOPE_ABOUT = {
  [LAYOUT_SCOPE]: "Keys set here work while the Vaultr layout shows and win over All layouts. Dim keys are inherited from All layouts.",
  global: "Herdr's keys in every layout. A layout or a terminal may use the same key for something else.",
  terminal: "Keys while a terminal has focus; they win over the layout's and Herdr's. Dim keys are inherited.",
  [SESSIONS_SCOPE]: "Keys while the Sessions panel has the keyboard. Dim keys are inherited from the layout and Herdr.",
};
const ASSIGNED = [["all", "All"], ["assigned", "Assigned"], ["unassigned", "Unassigned"]];
const WINDOW_BUTTONS = [["auto", "Automatic"], ["always", "Always"], ["never", "Never"]];
const VERBS = new Set(["focus", "section", "scope", "filter", "assigned", "capture", "key", "bind", "remove", "restore",
  "reassign", "cancel", "window-buttons", "give-back", "dump"]);
// Keys programs rely on (AGENTS.md "Keys"), named so a warning can say what is lost.
const PROGRAM_CTRL = {
  a: "start of line", b: "cursor back / tmux prefix", c: "interrupt", d: "end of input", e: "end of line",
  f: "cursor forward", k: "kill to end of line", l: "clear screen", n: "next history", p: "previous history",
  r: "history search", t: "transpose", u: "kill line", w: "delete word", z: "suspend", "\\": "quit (SIGQUIT)", "[": "Escape",
};

const KEYS_PATH = () => `${appHome()}/keys.json`;
const ERROR_PATH = () => `${appHome()}/keys.error`;

// "ob-tabs.open:ob-sessions@reveal@ctrl-alt-r" -> ["ob-tabs.open:ob-sessions@reveal", "ctrl-alt-r"].
// The chord is after the last "@" (a chord whose key is "@" keeps it: "x@ctrl-@").
function splitAt(arg) {
  let i = arg.lastIndexOf("@");
  if (i > 0 && (i === arg.length - 1 || arg[i - 1] === "-")) i = arg.lastIndexOf("@", i - 1);
  return i < 0 ? [arg, ""] : [arg.slice(0, i), arg.slice(i + 1)];
}
const label = (chord) => String(chord ?? "").split(/\s+/).map((s) => chordParts(s).join(" + ")).join(", ");
const ls = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } };
async function readSafe(path) { try { return await readTextFile(path); } catch { return null; } }
// A plain Ctrl+<char> chord: terminal programs lose it while it is bound outside `terminal`.
function plainCtrl(chord) {
  const c = canon(chord);
  const m = /^ctrl-(.)$/.exec(c);
  return m ? m[1] : null;
}
const isModScope = (s) => s.startsWith("mod:");
// effectivePairs of a section, kept while its pair list is the same array (until keys.json is read
// again). Every row asks for the same few sections on each render, staying within the 50 ms render budget.
const EFFECTIVE = new WeakMap();
const NO_PAIRS = [];
function effectiveOf(pairs) {
  if (!pairs) return NO_PAIRS;
  let out = EFFECTIVE.get(pairs);
  if (!out) { out = effectivePairs(pairs); EFFECTIVE.set(pairs, out); }
  return out;
}
// One edit of the file text: a move of a key between two sections, or a change to one section.
function applyOp(text, scope, op) {
  if (op.kind === "move") return moveKey(text, scope, op.to, op.chord, op.action);
  return applyEdit(text, scope, op);
}

// The tab's state lives on the settings dialog: host.state.hotkeys.
export function init(host, cx) {
  host.state.hotkeys = new Hotkeys(host, cx);
}

// ob-settings sends the tab's commands here; true when this tab handled one.
export function command(host, verb, arg, cx) {
  const h = host.state.hotkeys;
  if (!h || !VERBS.has(verb)) return false;
  h.command(verb, arg, cx);
  return true;
}

// Called when the person opens this tab: the filter takes the keyboard.
export function focus(host) {
  host.state.hotkeys?.focusFilter();
}

export function render(host, t, cx) {
  return host.state.hotkeys.body(t, cx);
}

class Hotkeys {
  constructor(host, cx) {
    this.host = host;
    this.section = "hotkeys"; // "hotkeys" | "layout" (sub-tabs)
    this.scope = DEFAULT_SCOPE; // every opening starts on the Vaultr layout, never on a remembered panel
    this.filter = ls("filter", "");
    this.assigned = "all";
    this.showAll = false;   // a panel scope lists every command (not remembered)
    this.text = null;       // keys.json as last read
    this.parsed = null;     // parseKeys(text) or null
    this.parseError = null; // why keys.json can't be parsed
    this.keysError = null;  // keys.error contents (Herdr rejected the file)
    this.loaded = false;
    this.capture = null;    // action whose "+" is waiting for keys
    this.liveMods = null;
    this.pending = null;    // { action, chord, others: [action] } conflict waiting for an answer
    this.banner = null;     // { level: "error"|"warn", text }
    this.notice = null;     // { text, at } after a save
    this.inflight = 0;      // edits queued or running (the footer says "Saving…")
    this.chain = Promise.resolve();
    this.keysSig = "";
    this.width = 0;
    this.scroll = ScrollHandle.new();
    this.handle = cx.focus_handle();
    this.input = InputState.new({ placeholder: "Filter…", value: this.filter });
    this.input.on("change", (_e, cx) => { this.filter = this.input.value(); lsSet("filter", this.filter); cx.notify(); });
    this.inputFocused = true;
    this.input.on("focus", (_e, cx) => { this.inputFocused = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.inputFocused = false; cx.notify(); });
    this.input.focus();
    cx.timer.after(120, () => { if (!this.capture) this.input.focus(); });
    cx.spawn(async (cx) => { await this.load(); cx.notify(); });
  }

  focusFilter() {
    if (!this.capture) this.input.focus();
  }

  // ---------------------------------------------------------------- data
  async load() {
    const [text, err] = await Promise.all([readSafe(KEYS_PATH()), readSafe(ERROR_PATH())]);
    this.text = text;
    this.keysError = err && err.trim() ? err.trim() : null;
    try { this.parsed = parseKeys(text ?? "{}"); this.parseError = null; } catch (e) { this.parsed = null; this.parseError = String(e?.message ?? e); }
    this.loaded = true;
  }

  // Every section's pairs in file order (duplicates kept). From the file when it parses, else
  // from keys() (what Herdr still uses), read-only.
  sections() {
    const out = {};
    if (this.parsed) {
      for (const [name, s] of Object.entries(this.parsed.sections)) out[name] = s.pairs ?? [];
      return out;
    }
    let all = [];
    try { all = keys() ?? []; } catch { all = []; }
    for (const k of all) (out[k.section] ??= []).push({ key: k.keys, action: k.action });
    return out;
  }
  get busy() { return this.inflight > 0; }
  // Edits queue (one at a time), so saving never disables the controls.
  canEdit() { return Boolean(this.parsed) && !this.keysError; }

  scopes(secs) {
    const extra = Object.keys(secs).filter((s) => !FIXED_SCOPES.includes(s) && (s.startsWith("mod:") || s.startsWith("layout:"))).sort();
    if (this.scope && !FIXED_SCOPES.includes(this.scope) && !extra.includes(this.scope)) extra.push(this.scope);
    return [...FIXED_SCOPES, ...extra];
  }

  titleOf(action, rows) {
    return rows.find((r) => r.action === action)?.title ?? titleFor(action);
  }

  // The chips of one row in scope S.
  chips(row, S, secs, rows) {
    const out = [];
    const eff = (name) => effectiveOf(secs[name]);
    const effS = eff(S);
    const term = S === "terminal" ? [] : eff("terminal");
    const termOf = (chord) => term.find((q) => canon(q.key) === canon(chord) && q.action !== row.action)?.action ?? null;
    for (const p of secs[S] ?? []) {
      if (p.action !== row.action) continue;
      const c = canon(p.key);
      const others = new Set();
      for (const q of secs[S] ?? []) if (q !== p && canon(q.key) === c && q.action !== row.action) others.add(q.action);
      if (this.pending && this.pending.others.includes(row.action) && canon(this.pending.chord) === c) others.add(this.pending.action);
      out.push({ kind: "own", chord: p.key, conflict: [...others], term: termOf(p.key), shadowed: !effS.includes(p) });
    }
    const chain = chainOf(S);
    chain.forEach((F, idx) => {
      for (const p of eff(F)) {
        if (p.action !== row.action) continue;
        const c = canon(p.key);
        let dup = false, over = null;
        for (const M of [S, ...chain.slice(0, idx)]) {
          const q = eff(M).find((x) => canon(x.key) === c);
          if (!q) continue;
          if (q.action === row.action) dup = true; else over = { action: q.action, section: M };
          break;
        }
        if (dup || out.some((o) => canon(o.chord) === c)) continue;
        out.push({ kind: "inherited", from: F, chord: p.key, over, term: over ? null : termOf(p.key) });
      }
    });
    if (this.pending?.action === row.action) out.push({ kind: "pending", chord: this.pending.chord, conflict: this.pending.others });
    for (const o of out) {
      o.overTitle = o.over ? this.titleOf(o.over.action, rows) : null;
      o.termTitle = o.term ? this.titleOf(o.term, rows) : null;
      o.conflictTitles = (o.conflict ?? []).map((a) => this.titleOf(a, rows));
      o.takes = o.kind !== "pending" && !o.over && S !== "terminal" && !isModScope(S) ? plainCtrl(o.chord) : null;
      if (o.kind === "inherited" && o.from === "terminal") o.takes = null;
    }
    return out;
  }

  // ---------------------------------------------------------------- commands
  command(verb, arg, cx) {
    if (verb === "focus") { if (this.capture) this.handle.focus(); else this.input.focus(); return; }
    if (verb === "section") { if (arg === "hotkeys" || arg === "layout") this.section = arg; return; }
    if (verb === "scope") { if (arg) this.setScope(arg); return; }
    if (verb === "filter") { this.filter = arg; this.input.set_value(arg); lsSet("filter", arg); return; }
    if (verb === "assigned") { if (ASSIGNED.some(([k]) => k === arg)) this.assigned = arg; return; }
    if (verb === "capture") {
      const [action, chord] = arg.includes("@") ? splitAt(arg) : [arg, ""];
      if (!registry().some((r) => r.action === action)) { this.banner = { level: "warn", text: `No command "${action}" in the list.` }; return; }
      this.startCapture(action);
      if (chord) this.press(chord, cx);
      return;
    }
    if (verb === "key") { if (this.capture) this.press(arg, cx); return; }
    if (verb === "bind") { const [action, chord] = splitAt(arg); if (action && chord) this.bind(action, chord, false, cx); return; }
    if (verb === "remove") { const [action, chord] = splitAt(arg); if (action && chord) this.edit({ kind: "unbind", action, chord }, cx); return; }
    if (verb === "restore") { if (arg) this.restore(arg, cx); return; }
    if (verb === "reassign") { this.reassign(cx); return; }
    if (verb === "cancel") { this.cancel(); return; }
    if (verb === "window-buttons") { this.setWindowButtons(arg); return; }
    if (verb === "give-back") { this.giveBack(arg, cx); return; }
    if (verb === "dump") {
      // Test hook: what Herdr itself uses for a section (keys()), to the stdout log.
      const sec = arg || this.scope;
      let all = [];
      try { all = keys() ?? []; } catch { all = []; }
      console.log(`ob-settings: keys() ${sec}: ${JSON.stringify(all.filter((k) => k.section === sec).map((k) => [k.keys, k.action]))}`);
    }
  }

  setScope(s) {
    this.scope = s;
    this.capture = null;
    this.pending = null;
  }

  startCapture(action) {
    this.pending = null;
    this.capture = action;
    this.liveMods = null;
    this.section = "hotkeys";
    this.handle.focus();
    const idx = this.listIndexOf(action);
    if (idx >= 0) this.scroll.scroll_to_item(idx);
  }
  endCapture() {
    this.capture = null;
    this.liveMods = null;
    this.input.focus();
  }
  cancel() {
    if (this.pending) this.pending = null;
    else if (this.capture) this.endCapture();
  }

  // A key press while capturing (on_key_down and the key:/capture: commands both land here).
  press(chord, cx) {
    const action = this.capture;
    if (!action) return;
    const p = String(chord ?? "").trim().toLowerCase();
    if (p === "escape") return this.endCapture();
    if (p === "backspace") {
      this.endCapture();
      return this.edit({ kind: "clear", action }, cx);
    }
    const form = writeForm(chord);
    if (!form) return; // a lone modifier: keep waiting
    if (!isModScope(this.scope)) {
      // Outside a panel, a key without Ctrl/Alt/Super would stop typing it in terminals (F-keys are fine).
      const parts = form.split(" ")[0].split("-");
      const key = form.endsWith("--") ? "-" : parts[parts.length - 1];
      const strong = parts.slice(0, -1).some((m) => ["ctrl", "alt", "cmd", "super", "win", "fn"].includes(m));
      if (!strong && !/^f\d+$/.test(key)) {
        this.banner = { level: "warn", text: `${label(form)} alone would stop typing it in terminals. Hold Ctrl, Alt or Super with it.` };
        return;
      }
    }
    this.endCapture();
    this.bind(action, form, false, cx);
  }

  bind(action, chord, force, cx) {
    const form = writeForm(chord);
    if (!form) { this.banner = { level: "error", text: `"${chord}" is not a key chord.` }; return; }
    this.edit({ kind: "bind", action, chord: form, force }, cx);
  }
  reassign(cx) {
    const p = this.pending;
    if (!p) return;
    this.pending = null;
    this.edit({ kind: "bind", action: p.action, chord: p.chord, force: true }, cx);
  }
  // A key of a panel section moves to the Vaultr layout (queued like any edit).
  moveToLayout(from, chord, action, cx) {
    this.edit({ kind: "move", scope: from, to: LAYOUT_SCOPE, chord, action }, cx);
  }
  restore(action, cx) {
    const row = registry().find((r) => r.action === action);
    const d = row ? defaultsIn(row, this.scope) : undefined;
    if (d === undefined) { this.banner = { level: "warn", text: `${row?.title ?? action} has no default ${scopeWhere(this.scope)}.` }; return; }
    const order = registry().filter((r) => r.home === this.scope).map((r) => r.action);
    this.edit({ kind: "restore", action, defaults: d, order }, cx);
  }
  giveBack(chord, cx) {
    const pairs = effectivePairs(this.sections()[LAYOUT_SCOPE] ?? []);
    const p = pairs.find((q) => canon(q.key) === canon(chord));
    if (!p) { this.banner = { level: "warn", text: `${label(chord)} is not bound in the Vaultr layout.` }; return; }
    this.edit({ kind: "unbind", action: p.action, chord: p.key, scope: LAYOUT_SCOPE }, cx);
  }
  setWindowButtons(v) {
    if (!WINDOW_BUTTONS.some(([k]) => k === v)) return;
    const cur = shared("ob.settings");
    setShared("ob.settings", { ...(cur && typeof cur === "object" ? cur : {}), windowButtons: v });
  }

  // ---------------------------------------------------------------- writing keys.json
  // Serialized: one edit at a time, each against the file as it is when its turn comes.
  edit(op, cx) {
    const scope = op.scope ?? this.scope;
    const prior = this.chain;
    let done;
    this.chain = new Promise((r) => { done = r; });
    this.inflight++;
    cx.spawn(async (cx) => {
      try {
        await prior;
        await this.write(op, scope, cx);
      } catch (e) {
        this.banner = { level: "error", text: String(e?.message ?? e) };
        console.log(`ob-settings: edit failed: ${e?.stack ?? e}`);
      } finally {
        this.inflight--;
        done();
        try { await this.load(); } catch { /* keep the old view */ }
        cx.notify();
      }
    });
  }

  async write(op, scope, cx) {
    const path = KEYS_PATH();
    const errBefore = await readSafe(ERROR_PATH());
    if (errBefore && errBefore.trim()) {
      this.banner = { level: "error", text: `Herdr can't use keys.json right now (${errBefore.trim()}). Fix it first; nothing was changed.` };
      return;
    }
    let attempt = 0;
    let prev, res;
    for (;;) {
      prev = await readTextFile(path);
      try {
        res = applyOp(prev ?? "{}\n", scope, op);
      } catch (e) {
        if (/internal:/.test(String(e?.message))) throw e;
        this.banner = { level: "error", text: `keys.json has an error; fix it first (${e?.message ?? e}). Nothing was changed.` };
        return;
      }
      if (res.conflict && op.kind === "move") {
        const rows = registry();
        this.banner = { level: "error", text: `${label(op.chord)} is already ${res.conflict.map((a) => this.titleOf(a, rows)).join(", ")} ${scopeWhere(op.to)}; nothing was moved.` };
        return;
      }
      if (res.conflict) {
        this.pending = { action: op.action, chord: op.chord, others: res.conflict };
        this.banner = null;
        return;
      }
      if (!res.changed) { this.notice = { text: "Nothing to change", at: Date.now() }; return; }
      try {
        await writeTextFile(path, res.text, prev ?? null);
        break;
      } catch (e) {
        if (++attempt > 1) {
          this.banner = { level: "error", text: `keys.json kept changing while saving; nothing was written (${e?.message ?? e}).` };
          return;
        }
      }
    }
    // Did Herdr accept it? If it wrote keys.error, put the old text back.
    await cx.sleep(800);
    const err = await readSafe(ERROR_PATH());
    if (err && err.trim()) {
      try {
        await writeTextFile(path, prev ?? "{}\n", res.text);
        this.banner = { level: "error", text: `Herdr rejected the change (${err.trim()}). keys.json was put back as it was.` };
      } catch {
        this.banner = { level: "error", text: `Herdr rejected the change (${err.trim()}) and keys.json changed meanwhile; check it.` };
      }
      return;
    }
    this.banner = null;
    this.notice = { text: this.describe(op, scope, res.took ?? []), at: Date.now() };
  }

  describe(op, scope, took) {
    const rows = registry();
    const t = this.titleOf(op.action, rows);
    const where = scopeTitle(scope);
    const tookText = took.length ? ` (taken from ${took.map((a) => this.titleOf(a, rows)).join(", ")})` : "";
    if (op.kind === "move") return `Moved ${label(op.chord)} (${t}) from ${where} to ${scopeTitle(op.to)}`;
    if (op.kind === "bind") return `Saved: ${label(op.chord)} → ${t} · ${where}${tookText}`;
    if (op.kind === "unbind") return `Removed ${label(op.chord)} from ${t} · ${where}`;
    if (op.kind === "clear") return `Cleared the keys of ${t} · ${where}`;
    return `Restored the default keys of ${t} · ${where}${tookText}`;
  }

  // ---------------------------------------------------------------- view model
  rows(secs) {
    const S = this.scope;
    const all = registry();
    const q = this.filter.trim().toLowerCase();
    const words = q ? q.split(/\s+/) : [];
    const out = [];
    for (const r of all) {
      const chips = this.chips(r, S, secs, all);
      // Where else the command really runs (another section): shown under the row, unless this scope lists it.
      const elsewhere = boundElsewhere(secs, r.action, S)
        .filter((e) => !chips.some((c) => c.kind === "inherited" && c.from === e.section && canon(c.chord) === canon(e.chord)));
      // The row being captured or asked about stays listed whatever the filters say.
      if (r.action === this.capture || r.action === this.pending?.action) { out.push({ ...r, chips, elsewhere }); continue; }
      // A panel lists its own commands (and any that already have a key here) unless "show all" is on.
      if (!listedIn(S, r.action, chips.some((c) => c.kind === "own"), this.showAll)) continue;
      const assigned = chips.some((c) => c.kind === "own" || (c.kind === "inherited" && !c.over));
      if (this.assigned === "assigned" && !assigned) continue;
      if (this.assigned === "unassigned" && assigned) continue;
      if (words.length) {
        const hay = [r.title, r.action, r.group, ...chips.flatMap((c) => [c.chord, canon(c.chord), label(c.chord).replace(/ /g, "")])].join(" ").toLowerCase();
        if (!words.every((w) => hay.includes(w))) continue;
      }
      out.push({ ...r, chips, elsewhere });
    }
    return { rows: out, total: all.length, all };
  }

  // The list's children: [group header, rows...] per group (index = ScrollHandle item).
  listItems(rows) {
    const items = [];
    for (const g of GROUPS) {
      const mine = rows.filter((r) => r.group === g);
      if (!mine.length) continue;
      items.push({ head: g, count: mine.length });
      for (const r of mine) items.push({ row: r });
    }
    return items;
  }
  listIndexOf(action) {
    const { rows } = this.rows(this.sections());
    return this.listItems(rows).findIndex((it) => it.row?.action === action);
  }

  // ---------------------------------------------------------------- render
  // The tab's content, drawn inside ob-settings' content area (which gives it the full height).
  body(t, cx) {
    // keys() changed (Herdr reloaded keys.json, maybe edited by hand): read the file again.
    let sig = "";
    try { sig = JSON.stringify(keys()); } catch { sig = ""; }
    if (sig !== this.keysSig) {
      const first = this.keysSig === "";
      this.keysSig = sig;
      if (!first && !this.busy) cx.timer.after(0, (cx) => { cx.spawn(async (cx) => { await this.load(); cx.notify(); }); });
    }
    return v_flex().id("hk-body").flex_1().min_h(0).track_focus(this.handle).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.width) > 1) { this.width = w; cx.notify(); } })
      .on_key_down((e, cx) => this.onKey(e, cx))
      .on_modifiers_changed((e, cx) => { if (this.capture) { this.liveMods = e.modifiers; cx.notify(); } })
      .child(this.subnav(t))
      .child(this.section === "hotkeys" ? this.hotkeysTab(t) : this.layoutTab(t));
  }

  onKey(e, cx) {
    if (this.capture) {
      cx.stop_propagation();
      this.press(captureKeystroke(e), cx);
      cx.notify();
      return;
    }
    if (captureKeystroke(e) === "escape") {
      cx.stop_propagation();
      if (this.pending) { this.pending = null; cx.notify(); return; }
      this.host.dismiss();
    }
  }

  subnav(t) {
    const seg = (id, items, cur, onPick) => h_flex().flex_none().h(26).p(2).gap(2).rounded(S.radiusLg).bg(t.background).border_1().border_color(t.input)
      .children(items.map(([k, text]) => h_flex().id(`${id}-${k}`).h_full().px(10).rounded(S.radius).items_center().text_size(S.textSm).cursor_pointer()
        .text_color(k === cur ? t.foreground : t.muted).when(k === cur, (el) => el.bg(t.selected).font_medium())
        .when(k !== cur, (el) => el.hover((s) => s.bg(t.hover).text_color(t.foreground)))
        .on_click((_e, cx) => onPick(k, cx)).child(text)));
    return h_flex().flex_none().px(20).pt(12).items_center()
      .child(seg("hk-sub", [["hotkeys", "Hotkeys"], ["layout", "Layout"]], this.section, (k, cx) => {
        this.section = k; this.capture = null; this.pending = null; cx.notify();
      }));
  }

  bannerRow(t) {
    let level = "error", text = "";
    if (this.parseError) text = `keys.json has an error; fix it first. Showing the keys Herdr still uses, read-only. (${this.parseError})`;
    else if (this.keysError) text = `Herdr can't use keys.json: ${this.keysError}. Editing is off until it is fixed.`;
    else { level = this.banner.level; text = this.banner.text; }
    const c = level === "warn" ? t.working : t.blocked;
    return h_flex().id("hk-banner").flex_none().mx(20).mb(10).px(10).py(7).gap(8).items_start().rounded(S.radiusLg)
      .bg(alpha(c, 0.12)).border_1().border_color(alpha(c, 0.5)).text_size(S.textSm).text_color(t.foreground)
      .child(icon(level === "warn" ? "alert" : "circle-x", S.iconSm, c))
      .child(div().flex_1().min_w(0).child(text))
      .when(Boolean(this.banner) && !this.parseError && !this.keysError, (el) => el.child(iconButton({ id: "hk-banner-x", icon: "x", size: 20, iconSize: S.iconXs, tip: "Dismiss",
        onClick: (_e, cx) => { this.banner = null; cx.notify(); } })));
  }

  groupHead(t, it) {
    return h_flex().id(`hk-g-${it.head}`).flex_none().h(34).px(20).pt(10).gap(8).items_center()
      .text_size(S.textXs).font_semibold().text_color(t.dim)
      .child(div().child(it.head.toUpperCase()))
      .child(div().font_normal().child(String(it.count)));
  }

  empty(t) {
    const hint = isModScope(this.scope) && !this.showAll
      ? "This panel has no commands of its own in the list. Show all commands to bind one here; it works only while the panel has focus."
      : this.assigned !== "all" ? `Try All instead of ${this.assigned === "assigned" ? "Assigned" : "Unassigned"}, or another filter.` : "Try a shorter filter, a key like ctrl+b, or another scope.";
    return v_flex().w_full().py(48).gap(8).items_center()
      .child(icon("search", 28, t.dim))
      .child(div().text_size(S.text).font_medium().text_color(t.muted).child("No commands match"))
      .child(div().text_size(S.textSm).text_color(t.dim).child(hint));
  }

  // ---------------------------------------------------------------- the Hotkeys sub-tab
  hotkeysTab(t) {
    const secs = this.sections();
    const { rows, total, all } = this.rows(secs);
    const items = this.listItems(rows);
    const scopes = this.scopes(secs);
    const seg = h_flex().flex_none().h(28).p(2).gap(2).rounded(S.radiusLg).bg(t.background).border_1().border_color(t.input)
      .children(ASSIGNED.map(([k, text]) => h_flex().id(`as-${k}`).h_full().px(9).rounded(S.radius).items_center().text_size(S.textSm).cursor_pointer()
        .text_color(k === this.assigned ? t.foreground : t.muted).when(k === this.assigned, (el) => el.bg(t.selected).font_medium())
        .when(k !== this.assigned, (el) => el.hover((s) => s.bg(t.hover).text_color(t.foreground)))
        .on_click((_e, cx) => { this.assigned = k; cx.notify(); }).child(text)));
    const scopeBtn = h_flex().id("hk-scope").flex_none().h(28).px(10).gap(6).items_center().rounded(S.radiusLg).border_1().border_color(t.input)
      .bg(t.background).text_size(S.textSm).cursor_pointer().hover((s) => s.bg(t.hover))
      .tooltip("Which keys.json section you see and edit")
      // The menu opens under this button (its bounds, taken on press), not at the pointer.
      .on_mouse_down("left", (e) => { this.scopeBounds = e.bounds ?? null; })
      .on_click(() => openMenu(scopes.map((s) => ({ label: scopeInfo(s).line, hint: s, checked: s === this.scope, command: `ob-settings.scope:${s}` })), { width: 380, title: "Keys for", at: menuAnchor(this.scopeBounds) }))
      .child(icon("layers", S.iconSm, t.muted))
      .child(div().text_color(t.foreground).child(scopeTitle(this.scope)))
      .child(icon("chevron-down", S.iconXs, t.dim));
    const filterBox = h_flex().id("hk-filter").flex_1().min_w(120).h(28).px(8).gap(6).items_center().rounded(S.radiusLg).bg(t.background)
      .border_1().border_color(this.inputFocused && !this.capture ? alpha(t.accent, 0.8) : t.input)
      .child(icon("search", S.iconSm, t.dim))
      .child(div().flex_1().min_w(0).child(Input.new(this.input).h_full().text_size(S.text).text_color(t.foreground)))
      .when(Boolean(this.filter), (el) => el.child(iconButton({ id: "hk-filter-clear", icon: "x", size: 20, iconSize: S.iconXs, tip: "Clear filter",
        onClick: (_e, cx) => { this.filter = ""; this.input.set_value(""); lsSet("filter", ""); this.input.focus(); cx.notify(); } })));
    const info = scopeInfo(this.scope);
    const note = isModScope(this.scope)
      ? (this.showAll ? "Every command is listed. A key for a command that isn't this panel's works only while the panel has focus."
        : "Only this panel's own commands are listed. Show all commands to find others.")
      : SCOPE_ABOUT[this.scope] ?? `Keys of the ${this.scope} section of keys.json. Dim keys are inherited.`;
    return v_flex().flex_1().min_h(0)
      .child(h_flex().flex_none().px(20).pt(10).pb(8).gap(8).items_center().child(filterBox).child(seg).child(scopeBtn))
      .child(h_flex().flex_none().px(20).pb(10).gap(10).items_center().text_size(S.textSm).text_color(t.dim)
        .child(div().flex_1().min_w(0).truncate().child(`${info.line}. ${note}`))
        .when(isModScope(this.scope), (el) => el.child(this.smallButton(t, "hk-showall", this.showAll ? "Panel's own only" : "Show all commands", false,
          (_e, cx) => { this.showAll = !this.showAll; cx.notify(); })))
        .child(div().flex_none().text_color(t.muted).child(rows.length === total ? `${total} commands` : `Showing ${rows.length} of ${total}`)))
      .when(Boolean(this.parseError || this.keysError || this.banner), (el) => el.child(this.bannerRow(t)))
      .child(div().flex_none().h(1).bg(t.border))
      .child(div().flex_1().min_h(0).relative()
        .child(v_flex().id("hk-list").size_full().overflow_y_scroll().track_scroll(this.scroll).pb(8)
          .children(items.length ? items.map((it) => (it.head ? this.groupHead(t, it) : this.row(t, it.row, all))) : [this.empty(t)]))
        .child(Scrollbar.vertical("hk-list").absolute().inset_0()))
      .child(this.footer(t));
  }

  row(t, r, all) {
    const S_ = this.scope;
    const capturing = this.capture === r.action;
    const editable = this.canEdit();
    const own = r.chips.filter((c) => c.kind === "own");
    const d = defaultsIn(r, S_);
    const sorted = (list) => list.map(canon).sort().join("|");
    const sameAsDefault = d !== undefined && sorted(own.map((c) => c.chord)) === sorted(d);
    const showRestore = d !== undefined && !sameAsDefault;
    const warns = [];
    if (r.missingArg && own.length) {
      warns.push({ tone: "blocked", text: `Requires "${r.missingArg}" argument (cannot run as written). Remove this key or bind a specific command.` });
    }
    for (const c of r.chips) {
      if (c.kind === "pending") warns.push({ tone: "blocked", text: `${label(c.chord)} is already ${c.conflictTitles.join(", ")} ${scopeWhere(S_)}.`, pending: true });
      else if (c.conflict?.length) {
        const asked = this.pending && c.conflict.includes(this.pending.action) && canon(this.pending.chord) === canon(c.chord);
        warns.push({ tone: "blocked", text: asked ? `${label(c.chord)} is being assigned to ${c.conflictTitles.join(", ")}` : `${label(c.chord)} is also ${c.conflictTitles.join(", ")}` });
      }
      else if (c.shadowed) warns.push({ tone: "blocked", text: `${label(c.chord)} is listed twice in keys.json; the later entry wins` });
      else if (c.over) warns.push({ tone: "dim", text: `${label(c.chord)} (${scopeShort(c.from)}) is used by ${c.overTitle} ${scopeWhere(c.over.section)}` });
    }
    // A key of another command that only lives in a panel: tagged, with a move to the Vaultr layout.
    if (scopeWarning(S_, r.action) && (own.length || capturing || this.pending?.action === r.action)) {
      warns.push({ tone: "warn", text: scopeWarning(S_, r.action).text, moveAll: editable ? own.map((c) => c.chord) : [], button: "Add to Vaultr layout" });
    }
    for (const e of r.elsewhere ?? []) {
      const tag = panelOnlyTag(e.section, r.action);
      if (tag) warns.push({ tone: "warn", text: `${label(e.chord)} · ${tag.text}`, moveFrom: editable ? { section: e.section, chord: e.chord } : null, button: "Move to Vaultr layout" });
      else warns.push({ tone: "dim", text: `${label(e.chord)} also runs it ${scopeWhere(e.section)}` });
    }
    const narrow = this.width > 0 && this.width < 640;
    const shown = JSON.stringify(r.action).slice(1, -1); // control chars as \u0017, like keys.json
    const sub = [shown, r.when ? `when ${r.when} is shown` : null].filter(Boolean).join("  ·  ");
    return v_flex().id(`hk-r-${r.action}`).flex_none().px(20).py(7).gap(4).border_b(1).border_color(alpha(t.border, 0.6))
      .when(capturing || Boolean(this.pending?.action === r.action), (el) => el.bg(alpha(t.accent, 0.07)))
      .when(!capturing, (el) => el.hover((s) => s.bg(alpha(t.hover, 0.5))))
      .child(h_flex().gap(12).items_center().min_h(30)
        .child(v_flex().flex_1().min_w(0).gap(2)
          .child(h_flex().gap(8).items_center().min_w(0)
            .child(div().min_w(0).truncate().text_size(S.text).text_color(t.foreground).child(r.title))
            .when(Boolean(r.obsidian) && /yours/.test(r.obsidian) && !narrow, (el) => el.child(h_flex().id(`hk-ob-${r.action}`).flex_none().h(16).px(5).rounded(4).items_center()
              .bg(alpha(t.accent, 0.12)).text_size(10).font_medium().text_color(t.accent).tooltip(`Same key as your Obsidian: ${r.obsidian}`).child("Obsidian"))))
          .child(div().min_w(0).truncate().text_size(S.textXs).text_color(t.dim).child(sub)))
        .child(h_flex().flex_none().max_w(narrow ? 260 : 440).flex_wrap().justify_end().gap(6).items_center()
          .children(r.chips.filter((c) => c.kind !== "pending").map((c, i) => this.chip(t, r, c, i, editable)))
          .when(capturing, (el) => el.child(this.captureChip(t)))
          .when(Boolean(this.pending?.action === r.action), (el) => el.child(this.chip(t, r, r.chips.find((c) => c.kind === "pending"), 99, false))))
        .child(h_flex().flex_none().gap(2).items_center()
          .child(showRestore && editable
            ? iconButton({ id: `hk-restore-${r.action}`, icon: "rotate-ccw", size: 24, iconSize: S.iconSm,
              tip: d.length ? `Restore default: ${d.map(label).join(", ")}` : "Restore default (no key in this scope)",
              onClick: (_e, cx) => { this.restore(r.action, cx); cx.notify(); } })
            : div().size(24).flex_none())
          .child(capturing
            ? iconButton({ id: `hk-cancel-${r.action}`, icon: "x", size: 24, iconSize: S.iconSm, tip: "Cancel (Esc)", onClick: (_e, cx) => { this.endCapture(); cx.notify(); } })
            : iconButton({ id: `hk-add-${r.action}`, icon: "plus", size: 24, iconSize: S.iconSm, disabled: !editable,
              tip: editable ? `Add a key ${scopeWhere(S_)}` : "keys.json can't be edited right now",
              onClick: (_e, cx) => { this.startCapture(r.action); cx.notify(); } }))))
      .children(warns.map((w, i) => h_flex().id(`hk-w-${r.action}-${i}`).gap(8).items_center().pl(0).text_size(S.textXs)
        .text_color(w.tone === "blocked" ? t.blocked : w.tone === "warn" ? t.working : t.dim)
        .child(icon(w.tone === "dim" ? "info" : "alert", S.iconXs, w.tone === "blocked" ? t.blocked : w.tone === "warn" ? t.working : t.dim))
        .child(div().min_w(0).truncate().child(w.text))
        .when(Boolean(w.pending), (el) => el
          .child(this.smallButton(t, `hk-reassign-${r.action}`, "Reassign", true, (_e, cx) => { this.reassign(cx); cx.notify(); }))
          .child(this.smallButton(t, `hk-keep-${r.action}`, "Cancel", false, (_e, cx) => { this.pending = null; cx.notify(); })))
        .when(Boolean(w.moveAll?.length), (el) => el.child(this.smallButton(t, `hk-wm-${r.action}-${i}`, w.button, false, (_e, cx) => {
          for (const c of w.moveAll) this.moveToLayout(S_, c, r.action, cx);
          cx.notify();
        })))
        .when(Boolean(w.moveFrom), (el) => el.child(this.smallButton(t, `hk-wm-${r.action}-${i}`, w.button, false, (_e, cx) => {
          this.moveToLayout(w.moveFrom.section, w.moveFrom.chord, r.action, cx);
          cx.notify();
        })))));
  }

  smallButton(t, id, text, primary, onClick) {
    return h_flex().id(id).flex_none().h(22).px(9).rounded(S.radius).items_center().text_size(S.textXs).font_medium().cursor_pointer()
      .when(primary, (el) => el.bg(t.blocked).text_color(t.accent_foreground).hover((s) => s.opacity(0.88)))
      .when(!primary, (el) => el.border_1().border_color(t.input).text_color(t.foreground).hover((s) => s.bg(t.hover)))
      .on_click(onClick).child(text);
  }

  // A key chip: "Ctrl + B" pill; its x removes it (own keys only).
  chip(t, r, c, i, editable) {
    const id = `hk-c-${r.action}-${i}`;
    const conflict = c.kind === "pending" || (c.conflict?.length ?? 0) > 0 || c.shadowed || (c.kind === "own" && Boolean(r.missingArg));
    const amber = !conflict && (c.term || c.takes);
    const inherited = c.kind === "inherited";
    const fg = conflict ? t.blocked : amber ? t.working : inherited ? t.dim : t.foreground;
    const border = conflict ? alpha(t.blocked, 0.7) : amber ? alpha(t.working, 0.6) : inherited ? t.border : t.input;
    const bg = conflict ? alpha(t.blocked, 0.14) : amber ? alpha(t.working, 0.1) : inherited ? alpha(t.raised, 0) : t.raised;
    const tips = [];
    if (c.kind === "own" && r.missingArg) tips.push(`Needs "${r.missingArg}" argument (cannot run as written)`);
    if (c.kind === "pending") tips.push(`Already ${c.conflictTitles.join(", ")}: Reassign or Cancel`);
    if (c.conflict?.length && c.kind !== "pending") tips.push(`Also bound to ${c.conflictTitles.join(", ")} ${scopeWhere(this.scope)}`);
    if (c.shadowed) tips.push("keys.json lists this key twice; the later entry wins");
    if (inherited) tips.push(c.over ? `From ${scopeTitle(c.from)}; overridden: ${scopeWhere(c.over.section)} it does ${c.overTitle}` : `From ${scopeTitle(c.from)}. Switch the scope to edit it there.`);
    if (c.term) tips.push(`In a terminal this key does ${c.termTitle}`);
    if (c.takes) tips.push(`Terminal programs don't get Ctrl+${c.takes.toUpperCase()} (${PROGRAM_CTRL[c.takes] ?? "their own use"}) while this is bound`);
    const removable = c.kind === "own" && editable;
    return h_flex().id(id).flex_none().h(22).pl(7).pr(removable ? 3 : 7).gap(4).rounded(5).items_center()
      .border_1().border_color(border).bg(bg).text_size(S.textXs).font_medium().text_color(fg)
      .when(Boolean(c.over), (el) => el.opacity(0.7))
      .when(tips.length > 0, (el) => el.tooltip(tips.join("\n")))
      .child(div().when(Boolean(c.over), (el) => el.line_through()).child(label(c.chord)))
      .when(inherited, (el) => el.child(div().text_size(10).font_normal().text_color(t.dim).child(scopeShort(c.from))))
      .when(removable, (el) => el.child(h_flex().id(`${id}-x`).size(16).rounded(3).items_center().justify_center().cursor_pointer()
        .text_color(alpha(fg, 0.55)).hover((s) => s.bg(t.hover).text_color(t.foreground))
        .tooltip("Remove this key")
        .on_click((_e, cx) => { cx.stop_propagation(); this.edit({ kind: "unbind", action: r.action, chord: c.chord }, cx); cx.notify(); })
        .child(icon("x", 11))));
  }

  captureChip(t) {
    const m = this.liveMods;
    const held = m ? [m.control && "Ctrl", m.alt && "Alt", m.shift && "Shift", m.platform && "Super"].filter(Boolean) : [];
    return h_flex().id("hk-capture").flex_none().h(22).px(8).gap(6).rounded(5).items_center()
      .border_1().border_color(alpha(t.accent, 0.9)).bg(alpha(t.accent, 0.12)).text_size(S.textXs).font_medium().text_color(t.accent)
      .tooltip("Esc cancels · Backspace clears this command's keys")
      .child(div().size(6).rounded_full().bg(t.accent).loop("opacity", { from: 0.25, to: 1, period: 900 }))
      .child(held.length ? `${held.join(" + ")} + …` : "Press a key…");
  }

  footer(t) {
    const n = this.notice;
    const fresh = n && Date.now() - n.at < 60000;
    const where = tilde(KEYS_PATH());
    return h_flex().flex_none().h(32).px(20).gap(10).items_center().border_t(1).border_color(t.border).text_size(S.textXs).text_color(t.dim)
      .child(this.busy ? icon("spinner", S.iconXs, t.working).spin(900) : icon(fresh ? "check" : "file-text", S.iconXs, fresh ? t.ansi2 : t.dim))
      .child(div().flex_1().min_w(0).truncate().text_color(fresh ? t.muted : t.dim)
        .child(this.busy ? "Saving…" : this.capture ? `Press the keys for ${this.titleOf(this.capture, registry())} · Esc cancels · Backspace clears` : fresh ? n.text : `Changes are saved to ${where} at once`))
      .child(div().flex_none().child("Esc to close"));
  }

  // ---------------------------------------------------------------- the Layout sub-tab
  layoutTab(t) {
    const cur = shared("ob.settings");
    const wb = (cur && typeof cur === "object" && cur.windowButtons) || "auto";
    const w = appWindow();
    const rowEl = (title, about, control) => h_flex().w_full().gap(16).py(14).items_center().border_b(1).border_color(t.border)
      .child(v_flex().flex_1().min_w(0).gap(3)
        .child(div().text_size(S.text + 1).text_color(t.foreground).child(title))
        .child(div().text_size(S.textSm).text_color(t.dim).child(about)))
      .child(div().flex_none().child(control));
    const seg = h_flex().h(28).p(2).gap(2).rounded(S.radiusLg).bg(t.background).border_1().border_color(t.input)
      .children(WINDOW_BUTTONS.map(([k, text]) => h_flex().id(`wb-${k}`).h_full().px(10).rounded(S.radius).items_center().text_size(S.textSm).cursor_pointer()
        .text_color(k === wb ? t.foreground : t.muted).when(k === wb, (el) => el.bg(t.selected).font_medium())
        .when(k !== wb, (el) => el.hover((s) => s.bg(t.hover).text_color(t.foreground)))
        .on_click(() => this.setWindowButtons(k)).child(text)));
    const taken = effectivePairs(this.sections()[LAYOUT_SCOPE] ?? []).filter((p) => plainCtrl(p.key));
    const rows = registry();
    const kbdChip = (chord) => h_flex().flex_none().h(22).px(7).rounded(5).items_center().border_1().border_color(alpha(t.working, 0.6))
      .bg(alpha(t.working, 0.1)).text_size(S.textXs).font_medium().text_color(t.working).child(label(chord));
    const layoutSwitch = rows.find((r) => r.action === "layout.switch");
    const nextLayout = effectivePairs(this.sections().global ?? []).find((p) => p.action === "layout.switch")?.key;
    return v_flex().id("lt-body").flex_1().min_h(0).px(20).py(8).overflow_y_scroll()
      .child(div().pt(10).pb(4).text_size(S.textXs).font_semibold().text_color(t.dim).child("WINDOW"))
      .child(rowEl("Window buttons", `Minimize, maximize and close in the top-right strip. Automatic follows Herdr: ${w?.buttons ? "shown" : "hidden"} on this computer${w?.buttons ? "" : " (the window manager draws none)"}.`, seg))
      .child(div().pt(18).pb(4).text_size(S.textXs).font_semibold().text_color(t.dim).child("KEYS TAKEN FROM TERMINAL PROGRAMS"))
      .child(div().pb(6).text_size(S.textSm).text_color(t.dim).child("Plain Ctrl keys this layout uses. While they are bound, shells and editors in a terminal don't get them. Give one back to let programs have it again."))
      .children(taken.length ? taken.map((p) => {
        const ch = plainCtrl(p.key);
        return h_flex().id(`lt-take-${p.key}`).w_full().gap(12).py(8).items_center().border_b(1).border_color(alpha(t.border, 0.6))
          .child(kbdChip(p.key))
          .child(v_flex().flex_1().min_w(0).gap(2)
            .child(div().text_size(S.text).text_color(t.foreground).truncate().child(this.titleOf(p.action, rows)))
            .child(div().text_size(S.textXs).text_color(t.dim).truncate().child(`Programs use it for: ${PROGRAM_CTRL[ch] ?? "their own shortcuts"}`)))
          .child(this.canEdit()
            ? h_flex().id(`lt-give-${p.key}`).flex_none().h(26).px(10).rounded(S.radius).items_center().border_1().border_color(t.input)
              .text_size(S.textSm).text_color(t.foreground).cursor_pointer().hover((s) => s.bg(t.hover))
              .on_click((_e, cx) => { this.giveBack(p.key, cx); cx.notify(); }).child("Give back")
            : div());
      }) : [div().py(10).text_size(S.textSm).text_color(t.muted).child("None: every plain Ctrl key goes to terminal programs.")])
      .child(div().pt(18).pb(4).text_size(S.textXs).font_semibold().text_color(t.dim).child("LAYOUTS"))
      .child(rowEl("Switch layout", `${nextLayout ? label(nextLayout) : "The command palette's Next layout"} goes to the next layout (${layoutSwitch ? "Next layout" : "layout.switch"}); Settings > Look picks one.`, div()))
      .child(rowEl("Escape hatch", "Ctrl + Alt + Shift + Escape always works: it sets this layout and keys.json aside and goes back to Herdr's main layout. Nothing can rebind it.", div()));
  }
}
