// The Feedback tab: configures the folder where feedback bundles are saved
// (`${appHome()}/feedback.json`, key "folder"). Unset means the feedback dialog
// asks the user to choose a folder before writing a bundle. Other keys in
// feedback.json are preserved, and clearing the last key removes the file.
import { div } from "gpui-kit";
import { h_flex, v_flex, InputState, Input } from "gpui-base";
import * as fs from "fs/promises";
import { appHome, checking, exec, home, pickFolder, readTextFile, window as appWindow, writeTextFile } from "herdr";
import { S, alpha, tilde } from "./kit.js";
import { expandFeedbackPath, parseFeedbackFolder, mergeFeedbackOwn } from "./feedback_rules.js";
import { ensureDir } from "./feedback_bundle.js";

const FILE = () => `${appHome()}/feedback.json`;
const KEY = "folder";
const FIELD = {
  label: "Feedback folder",
  placeholder: "e.g. ~/Feedback/vaultr",
  about: "Each feedback submission creates a timestamped subfolder here with feedback.md, screenshot.png, ui-tree.json, and diagnostics.log.",
};
const INTRO = "Choose where Vaultr saves feedback bundles. Each submission writes a self-contained folder you can inspect or share.";

const shown = (v) => (typeof v === "string" ? v : "");
const isSet = (v) => shown(v).trim() !== "";
const platformOf = () => appWindow()?.platform ?? "linux";
const shortPath = (p) => {
  const h = home();
  return h ? tilde(p) : p;
};

// Reads feedback.json into st.own and st.root without overwriting what the user is typing.
async function readOwn(host) {
  const st = host.state.feedback;
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
  const root = typeof own[KEY] === "string" ? expandFeedbackPath(own[KEY], home()) : null;
  st.own = own;
  st.error = error;
  st.root = root;
}

function fillInput(host) {
  const st = host.state.feedback;
  st.input.set_value(shown(st.own[KEY]));
}

// Writes the folder key (null removes it). Creates the target directory first when setting a folder.
async function write(host, value) {
  const st = host.state.feedback;
  const file = FILE();
  if (st.error) {
    st.notice = { level: "error", text: st.error };
    return;
  }
  let abs = null;
  if (value !== null) {
    abs = expandFeedbackPath(value, home());
    if (!abs) {
      st.notice = { level: "error", text: "The feedback folder must be a full path: ~/... or /..." };
      return;
    }
    try {
      await ensureDir(abs, exec, platformOf());
    } catch (e) {
      st.notice = { level: "error", text: `Could not create ${shortPath(abs)}: ${e?.message ?? e}` };
      return;
    }
  }
  try {
    const text = await readTextFile(file);
    let own = {};
    if (text != null) {
      own = JSON.parse(text);
      if (!own || typeof own !== "object" || Array.isArray(own)) throw new Error("not a JSON object");
    }
    const next = mergeFeedbackOwn(own, value);
    if (Object.keys(next).length === 0) {
      if (text != null) {
        try { await fs.unlink(file); } catch {}
      }
    } else {
      await writeTextFile(file, JSON.stringify(next, null, 2) + "\n", text);
    }
    st.own = next;
    st.input.set_value(shown(value ?? ""));
    st.notice = {
      level: "ok",
      text: value === null
        ? "Cleared the feedback folder."
        : `Saved feedback folder: ${shortPath(abs)}.`,
    };
  } catch (e) {
    st.notice = { level: "error", text: `Could not save the feedback folder to ${tilde(file)}: ${e?.message ?? e}` };
  }
  await readOwn(host);
}

// Runs a write after any earlier one, then redraws the dialog.
function queue(host, cx, value) {
  const st = host.state.feedback;
  const job = st.chain.then(() => write(host, value));
  st.chain = job.catch(() => {});
  cx.spawn(async (cx) => {
    try { await job; } catch (e) { st.notice = { level: "error", text: String(e?.message ?? e) }; }
    cx.notify();
  });
}

function save(host, cx) {
  const st = host.state.feedback;
  const parsed = parseFeedbackFolder(st.input.value(), home());
  if (parsed.error) {
    st.notice = { level: "error", text: parsed.error };
    cx.notify();
    return;
  }
  queue(host, cx, parsed.value);
}

function browse(host, cx) {
  const st = host.state.feedback;
  cx.spawn(async (cx) => {
    const picked = await pickFolder({ prompt: "Choose" });
    if (!picked) return;
    const val = shortPath(picked);
    st.input.set_value(val);
    const parsed = parseFeedbackFolder(val, home());
    if (parsed.error) {
      st.notice = { level: "error", text: parsed.error };
      cx.notify();
      return;
    }
    const job = st.chain.then(() => write(host, parsed.value));
    st.chain = job.catch(() => {});
    try { await job; } catch (e) { st.notice = { level: "error", text: String(e?.message ?? e) }; }
    cx.notify();
  });
}

export function init(host, cx) {
  const st = { own: {}, root: null, error: null, notice: null, chain: Promise.resolve() };
  st.input = InputState.new({ placeholder: FIELD.placeholder, value: "" });
  st.input.on("submit", (_e, cx) => save(host, cx));
  host.state.feedback = st;
  if (!checking()) {
    cx.spawn(async (cx) => {
      await readOwn(host);
      fillInput(host);
      cx.notify();
    });
  }
}

export function focus(host) {
  host.state.feedback?.input?.focus?.();
}

export function command(host, verb, _arg, cx) {
  if (verb === "feedback-browse") { browse(host, cx); return true; }
  if (verb === "feedback-clear") { queue(host, cx, null); return true; }
  return false;
}

export function render(host, t) {
  const st = host.state.feedback;
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
  const st = host.state.feedback;
  const set = isSet(st.own[KEY]);
  const status = !set
    ? "Not set: choose a folder here (or when submitting feedback) to save feedback bundles."
    : st.root
      ? `Saving feedback bundles to ${shortPath(st.root)}.`
      : "Set in feedback.json, but not a full path (~/... or /...): fix it before saving feedback.";
  const btn = (id, text, primary, onClick) => {
    const el = h_flex().id(id).h(26).px(10).rounded(S.radius).items_center().text_size(S.textSm).font_medium();
    if (!onClick) return el.border_1().border_color(t.border).text_color(t.dim).child(text);
    el.cursor_pointer().on_click((_e, cx) => onClick(cx));
    return primary
      ? el.bg(t.accent).text_color(t.accent_foreground).hover((s) => s.opacity(0.88)).child(text)
      : el.border_1().border_color(t.input).text_color(t.foreground).hover((s) => s.bg(t.hover)).child(text);
  };
  return v_flex().id("fb-folder").w_full().gap(6).py(14).border_b(1).border_color(t.border)
    .child(div().text_size(S.text + 1).text_color(t.foreground).child(FIELD.label))
    .child(div().text_size(S.textSm).text_color(t.dim).child(FIELD.about))
    .child(h_flex().w_full().gap(8).items_center()
      .child(h_flex().flex_1().min_w(0).h(28).px(8).rounded(S.radiusLg).bg(t.background).border_1().border_color(t.input).items_center()
        .child(div().flex_1().min_w(0).child(Input.new(st.input).h_full().text_size(S.text).text_color(t.foreground))))
      .child(btn("fb-browse", "Browse…", false, (cx) => browse(host, cx)))
      .child(btn("fb-save", "Save", true, (cx) => save(host, cx)))
      .child(btn("fb-clear", "Clear", false, set ? (cx) => queue(host, cx, null) : null)))
    .child(div().text_size(S.textXs).text_color(t.dim).child(status));
}
