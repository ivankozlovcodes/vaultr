// The Vault tab: the vault folder the obsidian mod reads from ${appHome()}/obsidian.json. Only that key is
// written here. Unset means no vault: the Notes panel and daily notes are off until one is set. Other keys in
// the file are kept (the obsidian mod still honours its daily-note and editor keys if they are there by hand).
// Removing the last key deletes the file. The rules (what a value is, what a merge does, when a folder is
// refused) are in ./vault_rules.js. The obsidian mod re-reads the file within a few seconds, so nothing needs
// restarting.
//
// A save shows the saved value at once, and the banner says what happened.
import { div } from "gpui-kit";
import { h_flex, v_flex, InputState, Input } from "gpui-base";
import * as fs from "fs/promises";
import { appHome, exec, home, readTextFile, writeTextFile, window as appWindow } from "herdr";
import { S, alpha, tilde } from "./kit.js";
import { expandPath, parseVault, mergeOwn, vaultProblem } from "./vault_rules.js";

const FILE = () => `${appHome()}/obsidian.json`;
const KEY = "vault";
const FIELD = { label: "Vault folder", placeholder: "e.g. ~/Notes",
  about: "The folder of your vault. The Notes panel and daily notes use this folder and no other." };
const SOON = " The Notes panel switches within a few seconds.";
const INTRO = "Set your vault folder once. Daily notes follow Obsidian's own daily-notes settings in that vault. " +
  "The editor is $VISUAL, then $EDITOR, then vi.";

const shown = (v) => (typeof v === "string" ? v : "");
const isSet = (v) => shown(v).trim() !== "";
const platformOf = () => appWindow()?.platform ?? "macos";

// Whether a folder exists. Asks the system: the app has no stat call.
async function isDir(path) {
  const r = platformOf() === "windows"
    ? await exec("cmd", ["/c", "if", "exist", `"${path}\\"`, "(exit 0)", "else", "(exit 1)"]).catch(() => ({ code: 1 }))
    : await exec("test", ["-d", path]).catch(() => ({ code: 1 }));
  return r.code === 0;
}

// Reads obsidian.json into st.own (what the file holds) and st.effective (the vault in use).
// Does not touch the input: the person's typing stays as it is.
async function readOwn(host) {
  const st = host.state.vault;
  const file = FILE();
  let own = {}, error = null;
  try {
    const text = await readTextFile(file);
    if (text != null) {
      own = JSON.parse(text);
      if (!own || typeof own !== "object" || Array.isArray(own)) throw new Error("not a JSON object");
    }
  } catch (e) {
    own = {};
    error = `${tilde(file)} can't be read (${e?.message ?? e}). Fix it by hand; nothing is written until then.`;
  }
  const root = typeof own[KEY] === "string" ? expandPath(own[KEY], home()) : null;
  st.own = own;
  st.error = error;
  st.root = root;
  st.effective = { [KEY]: root ? tilde(root) : "" };
}

// Fills the input from the file. Only at open: after that the field is changed by its own Save.
async function fillInput(host) {
  const st = host.state.vault;
  st.input.set_value(shown(st.own[KEY]));
}

// Writes the vault key (null removes it). Re-reads the file first and writes against that text.
async function write(host, value) {
  const st = host.state.vault;
  const file = FILE();
  if (st.error) { st.notice = { level: "error", text: st.error }; return; }
  if (value !== null) {
    const abs = expandPath(value, home());
    const problem = vaultProblem(tilde(abs), await isDir(abs));
    if (problem) { st.notice = { level: "error", text: problem }; return; }
  }
  try {
    const text = await readTextFile(file);
    const own = text == null ? {} : JSON.parse(text);
    const next = mergeOwn(own, KEY, value);
    if (Object.keys(next).length === 0 && Object.keys(own).length > 0) await fs.unlink(file);
    else await writeTextFile(file, JSON.stringify(next, null, 2) + "\n", text);
    // Shown at once: the file's content and the input.
    st.own = next;
    st.input.set_value(shown(value ?? ""));
    st.notice = { level: "ok", text: value === null
      ? `Cleared the vault folder: the Notes panel and daily notes are off until you set it.${SOON}`
      : `Saved the vault folder.${SOON}` };
  } catch (e) {
    st.notice = { level: "error", text: `Could not save the vault folder to ${tilde(file)}: ${e?.message ?? e}` };
  }
  await readOwn(host);
}

// Runs a write after any earlier one, then redraws the dialog.
function queue(host, cx, value) {
  const st = host.state.vault;
  const job = st.chain.then(() => write(host, value));
  st.chain = job.catch(() => {});
  cx.spawn(async (cx) => {
    try { await job; } catch (e) { st.notice = { level: "error", text: String(e?.message ?? e) }; }
    cx.notify();
  });
}

// The typed folder, checked. A refused one is shown as an error and nothing is written.
function save(host, cx) {
  const st = host.state.vault;
  const parsed = parseVault(st.input.value(), home());
  if (parsed.error) { st.notice = { level: "error", text: parsed.error }; return cx.notify(); }
  queue(host, cx, parsed.value);
}

export function init(host, cx) {
  const st = { own: {}, effective: {}, error: null, notice: null, chain: Promise.resolve() };
  st.input = InputState.new({ placeholder: FIELD.placeholder, value: "" });
  st.input.on("submit", (_e, cx) => save(host, cx));
  host.state.vault = st;
  cx.spawn(async (cx) => { await readOwn(host); await fillInput(host); cx.notify(); });
}

export function render(host, t) {
  const st = host.state.vault;
  const kids = [div().pb(10).text_size(S.textSm).text_color(t.dim).child(INTRO)];
  if (st.error) kids.push(banner(t, st.error, "error"));
  if (st.notice) kids.push(banner(t, st.notice.text, st.notice.level));
  kids.push(row(host, t));
  kids.push(div().pt(12).text_size(S.textXs).text_color(t.dim).child(`Other keys in ${tilde(FILE())} are kept as they are.`));
  return v_flex().w_full().justify_start().children(kids);
}

function banner(t, text, level) {
  const c = level === "ok" ? t.ansi2 : t.blocked;
  return h_flex().mb(10).px(10).py(7).rounded(S.radiusLg).bg(alpha(c, 0.12)).border_1().border_color(alpha(c, 0.5))
    .text_size(S.textSm).text_color(t.foreground)
    .child(div().min_w(0).child(text));
}

function row(host, t) {
  const st = host.state.vault;
  const set = isSet(st.own[KEY]);
  const eff = st.effective[KEY] ?? "";
  const status = !set ? "Not set: the Notes panel and daily notes are off until you set it."
    : st.root ? `Set in obsidian.json. Clear it to use: ${eff}`
    : "Set in obsidian.json, but not a full path (~/... or /...): the Notes panel and daily notes are off until you fix it.";
  const btn = (id, text, primary, onClick) => {
    const el = h_flex().id(id).h(26).px(10).rounded(S.radius).items_center().text_size(S.textSm).font_medium();
    if (!onClick) return el.border_1().border_color(t.border).text_color(t.dim).child(text);
    el.cursor_pointer().on_click((_e, cx) => onClick(cx));
    return primary
      ? el.bg(t.accent).text_color(t.accent_foreground).hover((s) => s.opacity(0.88)).child(text)
      : el.border_1().border_color(t.input).text_color(t.foreground).hover((s) => s.bg(t.hover)).child(text);
  };
  return v_flex().id(`vt-${KEY}`).w_full().gap(6).py(14).border_b(1).border_color(t.border)
    .child(div().text_size(S.text + 1).text_color(t.foreground).child(FIELD.label))
    .child(div().text_size(S.textSm).text_color(t.dim).child(FIELD.about))
    .child(h_flex().w_full().gap(8).items_center()
      .child(h_flex().flex_1().min_w(0).h(28).px(8).rounded(S.radiusLg).bg(t.background).border_1().border_color(t.input).items_center()
        .child(div().flex_1().min_w(0).child(Input.new(st.input).h_full().text_size(S.text).text_color(t.foreground))))
      .child(btn(`vt-save-${KEY}`, "Save", true, (cx) => save(host, cx)))
      .child(btn(`vt-clear-${KEY}`, "Clear", false, set ? (cx) => queue(host, cx, null) : null)))
    .child(div().text_size(S.textXs).text_color(t.dim).child(status));
}
