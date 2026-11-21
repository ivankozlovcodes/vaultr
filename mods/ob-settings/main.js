// ob-settings: Vaultr's settings dialog (a dialog, 900 x 0.86). Tabs down the left, the chosen tab on
// the right, Esc closes. Herdr's own settings sit under the tabs, apart from them.
//
// It opens on the tab ob-tabs asked for (shared "ob-settings.tab", cleared once read; ob-tabs sends
// `ob-tabs.settings:<tab>`), else on the tab used last (Vault the first time). Shared "ob-settings.open"
// says whether the dialog is up, so ob-tabs knows to move an open dialog rather than open a second one.
//
// To add a tab: write a module (./name.js) exporting `init(host, cx)` (runs once per open) and
// `render(host, t, cx)` (returns the content), optionally `command(host, verb, arg, cx)` for commands
// aimed at it (return true when handled) and `focus(host)` (the tab takes the keyboard when opened),
// then add one entry to TABS below. `fill: true` lets the tab take the whole height and scroll itself.
// host.state[<tab id>] is that tab's own state.
//
// Commands (ob-settings.<cmd>): tab:<id>  close  herdr, and the tabs' own (hotkeys.js, feedback.js).
import { View, div } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { props, closeOverlay, nextCommand, run, shared, setShared, keys } from "herdr";
import { S, tc, icon, iconButton } from "./kit.js";
import * as vault from "./vault.js";
import * as feedback from "./feedback.js";
import * as hotkeys from "./hotkeys.js";

const REQUEST = "ob-settings.tab";
const OPEN = "ob-settings.open";
// While open, the dialog keeps shared OPEN at the time of its last beat; ob-tabs reads a beat older than twice this as closed
// (mods/ob-tabs/settings_open.js). Not so often: setShared re-renders every mod.
const BEAT_MS = 5000;
const LAST_KEY = "tab";

const TABS = [
  { id: "vault", title: "Vault", icon: "folder", mod: vault,
    about: "The Obsidian vault the notes panels use. Saved to obsidian.json in the Herdr app folder; the Notes panels pick it up within a few seconds." },
  { id: "feedback", title: "Feedback", icon: "square-pen", mod: feedback,
    about: "Where feedback bundles (Markdown note, window screenshot, UI tree, and diagnostic logs) are saved. Saved to feedback.json in the Herdr app folder." },
  { id: "hotkeys", title: "Hotkeys", icon: "keyboard", mod: hotkeys, fill: true,
    about: "Every command with its keys. Add a key with +, remove one with x. Changes are saved to keys.json at once." },
];
// Herdr's own settings: not a tab. Listed last, apart from the tabs.
const HERDR = { id: "herdr", title: "Herdr settings…", icon: "external",
  action: (host) => { host.dismiss(); run("app.settings"); } };

const tabExists = (id) => TABS.some((t) => t.id === id);
function lastTab() {
  try { const v = localStorage.getItem(LAST_KEY); return tabExists(v) ? v : "vault"; } catch { return "vault"; }
}
function saveLast(id) {
  try { localStorage.setItem(LAST_KEY, id); } catch { /* storage unavailable */ }
}

export default class Settings extends View {
  init(_p, cx) {
    this.tabId = lastTab();
    this.state = {};
    this.keysSig = "";
    this.handle = cx.focus_handle();
    this.bindKeys(cx);
    this.takeRequest(cx);
    for (const t of TABS) t.mod?.init?.(this, cx);
    // Deferred: setShared re-renders every mod, so not inside init.
    cx.timer.after(0, () => setShared(OPEN, Date.now()));
    this.beat = cx.timer.every(BEAT_MS, () => { if (this.closed) return; setShared(OPEN, Date.now()); });
    cx.timer.after(60, () => this.handle.focus());
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-settings: ${c} failed: ${e?.stack ?? e}`); }
        cx.notify();
      }
    });
  }

  // The View's cleanup hook: the dialog is going, so ob-tabs must stop treating it as open.
  close() { this.closed = true; try { this.beat?.cancel(); } catch { /* already gone */ } setShared(OPEN, false); }

  bindKeys(cx) {
    if (typeof cx.bind_keys !== "function") return;
    cx.bind_keys([
      { keystroke: "escape", action: "ob_settings.escape", context: "ObSettings" },
    ]);
  }

  escape(cx) {
    const hk = this.tabId === "hotkeys" ? this.state.hotkeys : null;
    if (hk?.capture) { hk.press("escape", cx); cx.notify(); return; }
    if (hk?.pending) { hk.pending = null; cx.notify(); return; }
    this.dismiss();
  }

  // A request from ob-tabs: show that tab, then clear the request (deferred, see init).
  takeRequest(cx) {
    const req = shared(REQUEST);
    if (!req) return;
    if (tabExists(String(req))) this.open(String(req));
    cx.timer.after(0, () => setShared(REQUEST, null));
  }

  open(id) {
    this.tabId = id;
    saveLast(id);
  }

  command(c, cx) {
    const i = c.indexOf(":");
    const verb = i < 0 ? c : c.slice(0, i), arg = i < 0 ? "" : c.slice(i + 1);
    if (verb === "close") return this.dismiss();
    for (const t of TABS) if (t.mod?.command?.(this, verb, arg, cx)) return;
    if (verb === "herdr") return HERDR.action(this);
    if (verb === "tab" && tabExists(arg)) this.open(arg);
  }

  dismiss() { closeOverlay(props()?.overlay); }

  pick(entry, cx) {
    if (entry.action) return entry.action(this, cx);
    this.open(entry.id);
    entry.mod?.focus?.(this);
    cx.notify();
  }

  render(cx) {
    const t = tc();
    this.takeRequest(cx);
    let sig = "";
    try { sig = JSON.stringify(keys()); } catch { sig = ""; }
    if (sig !== this.keysSig) {
      const first = this.keysSig === "";
      this.keysSig = sig;
      if (!first) cx.timer.after(0, (cx) => this.bindKeys(cx));
    }
    return v_flex().id("root").key_context("ObSettings").track_focus(this.handle).size_full().min_h(0).bg(t.popover).text_color(t.foreground)
      .on_action("ob_settings.escape", (_e, cx) => this.escape(cx))
      .on_key_down((e, cx) => { if (e.key === "escape") { cx.stop_propagation(); this.escape(cx); } })
      .child(this.header(t))
      .child(h_flex().flex_1().min_h(0).items_start()
        .child(this.nav(t, cx))
        .child(div().w(1).h_full().bg(t.border))
        .child(this.content(t, cx)));
  }

  header(t) {
    return h_flex().h(52).flex_none().px(20).gap(12).items_center().border_b(1).border_color(t.border)
      .child(icon("settings", 18, t.muted))
      .child(div().text_size(S.textLg + 1).font_semibold().child("Settings"))
      .child(div().flex_1())
      .child(iconButton({ id: "st-close", icon: "x", tip: "Close (Esc)", onClick: () => this.dismiss() }));
  }

  nav(t, cx) {
    const item = (e) => {
      const on = !e.action && this.tabId === e.id;
      return h_flex().id(`st-${e.id}`).h(30).flex_none().px(10).gap(8).items_center().rounded(S.radiusLg).cursor_pointer()
        .text_size(S.text).text_color(on ? t.foreground : t.muted)
        .when(on, (el) => el.bg(t.selected).font_medium())
        .when(!on, (el) => el.hover((s) => s.bg(t.hover).text_color(t.foreground)))
        .on_click((_ev, cx) => this.pick(e, cx))
        .child(icon(e.icon, S.iconSm, on ? t.foreground : t.dim))
        .child(div().min_w(0).truncate().child(e.title));
    };
    return v_flex().id("st-nav").w(180).h_full().flex_none().p(10).bg(t.chrome)
      .children([v_flex().w_full().justify_start().gap(2).children([...TABS.map(item), div().h(1).my(6).bg(t.border), item(HERDR)])]);
  }

  content(t, cx) {
    const tab = TABS.find((x) => x.id === this.tabId) ?? TABS[0];
    let body;
    try { body = tab.mod ? tab.mod.render(this, t, cx) : div(); } catch (e) {
      // A tab that fails to draw says why, instead of leaving the dialog empty.
      console.log(`ob-settings: ${tab.id} tab failed: ${e?.stack ?? e}`);
      body = div().text_color(t.blocked).child(`This tab failed to draw: ${e?.message ?? e}`);
    }
    const head = v_flex().w_full().justify_start()
      .child(div().text_size(S.textLg).font_semibold().child(tab.title))
      .child(div().pt(4).pb(10).text_size(S.textSm).text_color(t.dim).child(tab.about));
    if (tab.fill) {
      // The tab fills the height and scrolls its own list.
      return v_flex().id("st-content").flex_1().min_w(0).h_full().min_h(0).pt(20).px(20).justify_start()
        .child(head)
        .child(v_flex().id("st-fill").flex_1().min_h(0).w_full().child(body));
    }
    return v_flex().id("st-content").flex_1().min_w(0).h_full().min_h(0).overflow_y_scroll().px(28).py(20).justify_start()
      .child(head.child(body));
  }
}
