// ob-feedback: hotkey-bound Markdown feedback dialog (680 x 580).
// Pre-dialog capture stages shot-<timestamp>.png and capture.json under ${appHome()}/data/ob-feedback/.
// Saving writes a self-contained timestamped bundle folder inside the folder configured in
// ${appHome()}/feedback.json (`folder`).
//
// Commands (ob-feedback.<cmd>): close  retake  submit  submit-copy
import { View, div, image } from "gpui-kit";
import { h_flex, v_flex, TextareaState, Textarea } from "gpui-base";
import * as fs from "fs/promises";
import {
  agents, appHome, checking, closeOverlay, exec, focused, home, keys, layout, layouts,
  machines, nextCommand, notify, panes, pickFolder, props, readTextFile, run, settings,
  shared, spaces, terminals, updates, window as appWindow, writeTextFile,
} from "herdr";
import { S, tc, alpha, icon, iconButton, copyText, tilde, provider } from "./kit.js";
import {
  expandFeedbackPath, mergeFeedbackOwn, slugifyFeedback, formatBundleStamp,
  pickAvailableBundleDir, ensureDir, dirExists, nonEmptyFileExists, copyBinaryFile,
  isSafeStageRel, buildUiTreeDump, buildDiagnosticsLog, buildFeedbackMarkdown,
  runFeedbackCapture,
} from "./feedback_bundle.js";

const FEEDBACK_FILE = () => `${appHome()}/feedback.json`;
const STAGE_JSON = () => `${appHome()}/data/ob-feedback/capture.json`;
const FRESH_MS = 15000;

const shortPath = (p) => {
  const h = home();
  return h ? tilde(p) : p;
};

export default class FeedbackDialog extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.keysSig = "";
    this.folder = null;
    this.folderAbs = null;
    this.folderError = null;
    this.capture = null;
    this.hasScreenshot = false;
    this.loading = false;
    this.saving = false;
    this.error = null;
    this.message = TextareaState.new({
      placeholder: "What happened? What did you expect? (Markdown)",
      value: props()?.message ?? "",
      rows: 6,
    });
    this.message.on("change", (_e, cx) => {
      if (this.error) {
        this.error = null;
        cx.notify();
      }
    });
    this.message.on("submit", (e, cx) => {
      if (e?.secondary) this.startSubmit(false, cx);
    });
    this.bindKeys(cx);
    this.message.focus();
    cx.timer.after(60, () => { try { this.message.focus(); } catch {} });
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { await this.command(c, cx); } catch (e) { console.log(`ob-feedback: ${c} failed: ${e?.stack ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
    if (!checking()) {
      cx.spawn(async (cx) => {
        await this.loadInitial();
        cx.notify();
      });
    }
  }

  bindKeys(cx) {
    if (typeof cx.bind_keys !== "function") return;
    cx.bind_keys([
      { keystroke: "escape", action: "ob_feedback.close", context: "ObFeedback" },
      { keystroke: "escape", action: "ob_feedback.close", context: "ObFeedback > Input" },
      { keystroke: "ctrl-enter", action: "ob_feedback.submit", context: "ObFeedback" },
      { keystroke: "ctrl-enter", action: "ob_feedback.submit", context: "ObFeedback > Input" },
      { keystroke: "cmd-enter", action: "ob_feedback.submit", context: "ObFeedback" },
      { keystroke: "cmd-enter", action: "ob_feedback.submit", context: "ObFeedback > Input" },
    ]);
  }

  dismiss() {
    closeOverlay(props()?.overlay);
  }

  async command(c, cx) {
    if (c === "close") { this.dismiss(); return; }
    if (c === "retake") { await this.retake(); return; }
    if (c === "submit") { await this.submit(false, cx); return; }
    if (c === "submit-copy") { await this.submit(true, cx); return; }
  }

  async loadFolder() {
    this.folder = null;
    this.folderAbs = null;
    this.folderError = null;
    try {
      const text = await readTextFile(FEEDBACK_FILE());
      if (text == null) return;
      const own = JSON.parse(text);
      if (!own || typeof own !== "object" || Array.isArray(own)) throw new Error("not a JSON object");
      if (typeof own.folder === "string" && own.folder.trim()) {
        this.folder = own.folder.trim();
        this.folderAbs = expandFeedbackPath(this.folder, home());
        if (!this.folderAbs) this.folderError = `Feedback folder must be a full path (~/... or /...): ${this.folder}`;
      }
    } catch (e) {
      this.folderError = `${tilde(FEEDBACK_FILE())} can't be read (${e?.message ?? e}).`;
    }
  }

  async captureFresh(opts = {}) {
    const cap = await runFeedbackCapture({
      appHome, home, layout, layouts, focused, spaces, panes, agents, terminals,
      machines, window: appWindow, settings, updates, keys, shared, provider,
      exec, readTextFile, writeTextFile, fs, ...opts,
    });
    this.capture = cap;
    this.hasScreenshot = Boolean(cap?.hasScreenshot);
    return cap;
  }

  async loadInitial() {
    this.loading = true;
    await this.loadFolder();
    let cap = null;
    try {
      const raw = await readTextFile(STAGE_JSON());
      if (raw != null) cap = JSON.parse(raw);
    } catch {
      cap = null;
    }
    const passedAt = props()?.capturedAt;
    const stale = !cap || !cap.capturedAt || (!passedAt && Date.now() - cap.capturedAt > FRESH_MS);
    if (stale) {
      cap = await this.captureFresh();
    } else {
      this.capture = cap;
      const plat = cap.window?.platform ?? appWindow()?.platform ?? "linux";
      if (cap.hasScreenshot && isSafeStageRel(cap.screenshotPath)) {
        this.hasScreenshot = await nonEmptyFileExists(`${appHome()}/${cap.screenshotPath}`, exec, plat);
        if (!this.hasScreenshot) cap.hasScreenshot = false;
      } else {
        this.hasScreenshot = false;
      }
    }
    this.loading = false;
  }

  async retake(opts = {}) {
    this.loading = true;
    this.error = null;
    await this.captureFresh(opts);
    this.loading = false;
  }

  async browseFolder() {
    const picked = await pickFolder({ prompt: "Choose" });
    if (!picked) return null;
    const val = shortPath(picked);
    const abs = expandFeedbackPath(val, home());
    if (!abs) {
      this.error = "The feedback folder must be a full path: ~/... or /...";
      return null;
    }
    try {
      const plat = appWindow()?.platform ?? "linux";
      await ensureDir(abs, exec, plat);
      const file = FEEDBACK_FILE();
      const text = await readTextFile(file);
      let own = {};
      if (text != null) {
        own = JSON.parse(text);
        if (!own || typeof own !== "object" || Array.isArray(own)) throw new Error("not a JSON object");
      }
      const next = mergeFeedbackOwn(own, val);
      await writeTextFile(file, JSON.stringify(next, null, 2) + "\n", text);
      this.folder = val;
      this.folderAbs = abs;
      this.folderError = null;
      this.error = null;
      return abs;
    } catch (e) {
      this.error = `Could not save feedback folder: ${e?.message ?? e}`;
      return null;
    }
  }

  async submit(copyPath, cx) {
    if (this.saving) return { ok: false, error: "Already saving." };
    const msg = String(this.message.value() ?? "").trim();
    if (!msg) {
      this.error = "Write a feedback message first.";
      return { ok: false, error: this.error };
    }
    await this.loadFolder();
    if (this.folderError) {
      this.error = this.folderError;
      return { ok: false, error: this.error };
    }
    if (!this.folderAbs) {
      this.error = "Choose a feedback folder first (Browse… or Settings).";
      return { ok: false, error: this.error };
    }
    this.saving = true;
    this.error = null;
    try {
      const cap = this.capture ?? (await this.captureFresh());
      const plat = cap.window?.platform ?? appWindow()?.platform ?? "linux";
      const rootDir = this.folderAbs;
      await ensureDir(rootDir, exec, plat);
      const stamp = formatBundleStamp(cap.capturedAt || Date.now());
      const dirName = await pickAvailableBundleDir(
        rootDir,
        stamp,
        slugifyFeedback(msg),
        (d) => dirExists(d, exec, plat),
      );
      const bundleDir = `${rootDir}/${dirName}`;
      await ensureDir(bundleDir, exec, plat);

      let wroteShot = false;
      if (cap.hasScreenshot && isSafeStageRel(cap.screenshotPath)) {
        const srcShot = `${appHome()}/${cap.screenshotPath}`;
        if (await nonEmptyFileExists(srcShot, exec, plat)) {
          wroteShot = await copyBinaryFile(srcShot, `${bundleDir}/screenshot.png`, exec, plat);
        }
      }

      const dump = buildUiTreeDump(cap);
      const spacesList = Array.isArray(cap.spaces) ? cap.spaces : [];
      const curSpace = spacesList.find((s) => s?.id === cap.focused?.space) ?? spacesList.find((s) => s?.active) ?? null;
      const curTab = curSpace?.tabs?.find((tb) => tb?.id === cap.focused?.tab) ?? curSpace?.tabs?.find((tb) => tb?.active) ?? null;
      const md = buildFeedbackMarkdown({
        created: cap.isoTime ?? new Date(cap.capturedAt || Date.now()).toISOString(),
        platform: plat,
        herdrApp: cap.updates?.app?.version ?? null,
        herdrCore: cap.updates?.core?.version ?? null,
        layout: cap.layoutName ?? "vaultr",
        space: curSpace?.name ?? cap.focused?.space ?? null,
        tab: curTab?.name ?? cap.focused?.tab ?? null,
        pane: cap.focused?.pane ?? null,
        hasScreenshot: wroteShot,
        message: msg,
      });
      const log = buildDiagnosticsLog({ ...cap, hasScreenshot: wroteShot });

      await writeTextFile(`${bundleDir}/feedback.md`, md, null);
      await writeTextFile(`${bundleDir}/ui-tree.json`, JSON.stringify(dump, null, 2) + "\n", null);
      await writeTextFile(`${bundleDir}/diagnostics.log`, log, null);

      if (copyPath) copyText(cx, bundleDir);
      this.dismiss();
      notify({
        title: copyPath ? "Feedback saved (path copied)" : "Feedback saved",
        body: shortPath(bundleDir),
        level: "success",
        timeout: 3500,
      });
      return {
        ok: true,
        bundleDir,
        files: ["feedback.md", ...(wroteShot ? ["screenshot.png"] : []), "ui-tree.json", "diagnostics.log"],
      };
    } catch (e) {
      this.error = `Could not save feedback bundle: ${e?.message ?? e}`;
      return { ok: false, error: this.error };
    } finally {
      this.saving = false;
    }
  }

  startSubmit(copyPath, cx) {
    cx.spawn(async (cx) => {
      await this.submit(copyPath, cx);
      try { cx.notify(); } catch {}
    });
  }

  startRetake(cx) {
    if (this.loading) return;
    this.loading = true;
    this.error = null;
    cx.notify();
    cx.spawn(async (cx) => {
      await this.retake();
      try { cx.notify(); } catch {}
    });
  }

  startBrowse(cx) {
    cx.spawn(async (cx) => {
      await this.browseFolder();
      try { cx.notify(); } catch {}
    });
  }

  render(cx) {
    const t = tc();
    let sig = "";
    try { sig = JSON.stringify(keys()); } catch { sig = ""; }
    if (sig !== this.keysSig) {
      const first = this.keysSig === "";
      this.keysSig = sig;
      if (!first) cx.timer.after(0, (cx) => this.bindKeys(cx));
    }

    const btn = (id, label, opts, onClick) => {
      const { primary = false, disabled = false, ic = null } = opts ?? {};
      const el = h_flex().id(id).h(28).px(11).gap(6).flex_none().items_center().rounded(S.radius)
        .text_size(S.textSm).font_medium()
        .when(Boolean(ic), (e) => e.child(icon(ic, S.iconSm, primary && !disabled ? t.accent_foreground : disabled ? t.dim : t.muted)))
        .child(label);
      if (disabled) return el.border_1().border_color(t.border).text_color(t.dim);
      el.cursor_pointer().on_mouse_down("left", (_e, cx) => cx.stop_propagation()).on_click((_e, cx) => onClick(cx));
      return primary
        ? el.bg(t.accent).text_color(t.accent_foreground).hover((s) => s.opacity(0.88))
        : el.border_1().border_color(t.input).bg(t.background).text_color(t.foreground).hover((s) => s.bg(t.hover));
    };

    const chip = (id, text, ok, tipText) => h_flex().id(id).h(22).px(7).gap(5).flex_none().items_center().rounded(5)
      .bg(ok ? alpha(t.ansi2, 0.14) : alpha(t.working, 0.14))
      .border_1().border_color(ok ? alpha(t.ansi2, 0.45) : alpha(t.working, 0.45))
      .text_size(S.textXs).text_color(ok ? t.foreground : t.working)
      .when(Boolean(tipText), (e) => e.tooltip(tipText))
      .child(icon(ok ? "check" : "alert", S.iconXs, ok ? t.ansi2 : t.working))
      .child(text);

    const header = h_flex().h(46).flex_none().px(18).gap(10).items_center().border_b(1).border_color(t.border)
      .child(icon("square-pen", 17, t.accent))
      .child(div().text_size(S.textLg).font_semibold().child("Submit feedback"))
      .child(div().flex_1())
      .child(iconButton({ id: "fb-close", icon: "x", tip: "Close (Esc)", onClick: () => this.dismiss() }));

    const folderLabel = this.folderAbs ? shortPath(this.folderAbs) : "not set";
    const destBar = h_flex().id("fb-dest").flex_none().px(18).py(9).gap(8).items_center().border_b(1).border_color(t.border).bg(alpha(t.chrome, 0.5))
      .child(icon(this.folderAbs ? "folder-open" : "folder", S.iconSm, this.folderAbs ? t.muted : t.working))
      .child(div().text_size(S.textSm).text_color(t.muted).child("Folder:"))
      .child(div().flex_1().min_w(0).truncate().text_size(S.textSm).text_color(this.folderAbs ? t.foreground : t.working).child(folderLabel))
      .child(btn("fb-browse", "Browse…", {}, (cx) => this.startBrowse(cx)))
      .child(btn("fb-settings", "Settings", { ic: "settings" }, () => { this.dismiss(); run("ob-tabs.settings:feedback"); }));

    const shotWarn = this.capture?.shotError || (this.loading ? "Capturing…" : "No screenshot");
    const shotRel = this.capture?.screenshotPath;
    const previewCard = h_flex().id("fb-preview").w_full().p(10).gap(12).items_center().rounded(S.radiusLg).bg(t.raised).border_1().border_color(t.border)
      .child(this.hasScreenshot && isSafeStageRel(shotRel) && !checking()
        ? div().id("fb-shot").h(84).flex_none().rounded(S.radius).overflow_hidden().border_1().border_color(t.border)
          .child(image(shotRel).h(84))
        : v_flex().id("fb-no-shot").w(120).h(84).flex_none().rounded(S.radius).border_1().border_color(t.border).bg(t.background)
          .items_center().justify_center().gap(4).px(6)
          .child(icon(this.loading ? "info" : "alert", S.icon, this.loading ? t.muted : t.working))
          .child(div().text_size(S.textXs).text_color(t.dim).text_center().truncate().w_full().child(this.loading ? "Capturing…" : "No screenshot")))
      .child(v_flex().flex_1().min_w(0).gap(8)
        .child(h_flex().w_full().items_center().justify_between().gap(8)
          .child(div().text_size(S.textSm).font_medium().text_color(t.foreground).child("Bundle contents"))
          .child(btn("fb-retake", this.loading ? "Capturing…" : "Retake", { ic: "refresh", disabled: this.loading || this.saving }, (cx) => this.startRetake(cx))))
        .child(h_flex().w_full().flex_wrap().gap(6)
          .child(chip("fb-chip-md", "feedback.md", true))
          .child(chip("fb-chip-shot", this.hasScreenshot ? "screenshot.png" : "screenshot missing", this.hasScreenshot, this.hasScreenshot ? "Unobstructed window screenshot" : shotWarn))
          .child(chip("fb-chip-tree", "ui-tree.json", Boolean(this.capture)))
          .child(chip("fb-chip-log", "diagnostics.log", Boolean(this.capture)))));

    const errText = this.error || this.folderError;
    const body = v_flex().id("fb-body").flex_1().min_h(0).px(18).py(12).gap(10).overflow_y_scrollbar()
      .child(div().text_size(S.textSm).text_color(t.muted).child("Note (Markdown)"))
      .child(Textarea.new(this.message).w_full().h(160).p(10).rounded(S.radiusLg).border_1().border_color(t.input)
        .bg(t.background).text_color(t.foreground).text_size(S.text))
      .child(previewCard)
      .when(Boolean(errText), (e) => e.child(h_flex().id("fb-error").px(10).py(7).gap(8).items_center().rounded(S.radiusLg)
        .bg(alpha(t.blocked, 0.12)).border_1().border_color(alpha(t.blocked, 0.5)).text_size(S.textSm).text_color(t.foreground)
        .child(icon("alert", S.iconSm, t.blocked))
        .child(div().flex_1().min_w(0).child(errText))));

    const canSave = !this.saving && !this.loading;
    const footer = h_flex().h(50).flex_none().px(18).gap(8).items_center().border_t(1).border_color(t.border).bg(alpha(t.chrome, 0.35))
      .child(btn("fb-cancel", "Cancel", {}, () => this.dismiss()))
      .child(div().flex_1())
      .child(btn("fb-save-copy", "Save & copy path", { ic: "copy", disabled: !canSave }, (cx) => this.startSubmit(true, cx)))
      .child(btn("fb-save", this.saving ? "Saving…" : "Save feedback", { primary: true, disabled: !canSave }, (cx) => this.startSubmit(false, cx)));

    return v_flex().id("root").key_context("ObFeedback").track_focus(this.handle).size_full().min_h(0)
      .bg(t.popover).text_color(t.foreground)
      .on_action("ob_feedback.close", (_e, cx) => { cx.stop_propagation(); this.dismiss(); })
      .on_action("ob_feedback.submit", (_e, cx) => { cx.stop_propagation(); this.startSubmit(false, cx); })
      .on_key_down((e, cx) => {
        const m = e.modifiers ?? {};
        if (e.key === "escape") { cx.stop_propagation(); this.dismiss(); return; }
        if (e.key === "enter" && (m.control || m.platform)) { cx.stop_propagation(); this.startSubmit(false, cx); }
      })
      .child(header)
      .child(destBar)
      .child(body)
      .child(footer);
  }
}
