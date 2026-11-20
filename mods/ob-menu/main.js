// ob-menu: the context menu every ob-* mod opens with kit.openMenu(items). A popup at the pointer.
// props: { items: Item[], title?: string, overlay }  (Item: see openMenu in kit/kit.js)
// Item extras understood here (additive): header: "Section" (a small section title row),
// dot: "<theme color>" (a status dot in place of the icon), indent: true (one step in).
// ↑/↓ move, Home/End jump, Enter runs, Esc closes. Disabled items, headers and separators are skipped.
// Commands (for tests without a mouse): ob-menu.pick:<item index>, ob-menu.close

import { View, div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { props, run, closeOverlay, openOverlay, nextCommand, keys } from "herdr";
import { S, icon, kbd, tc, alpha } from "./kit.js";

export default class Menu extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.handle.focus();
    this.at = -1; // keyboard cursor in pickable(); none until an arrow key or the pointer moves
    this.keysSig = "";
    this.bindKeys(cx);
    cx.timer.after(60, () => this.handle.focus());
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try {
          if (c.startsWith("pick:")) this.choose(Number(c.slice(5)), cx);
          else if (c === "close") closeOverlay(props()?.overlay);
        } catch (e) { console.log(`ob-menu: ${c} failed: ${e?.message ?? e}`); }
      }
    });
  }

  bindKeys(cx) {
    if (typeof cx.bind_keys !== "function") return;
    cx.bind_keys([
      { keystroke: "escape", action: "ob_menu.escape", context: "ObMenu" },
      { keystroke: "down", action: "ob_menu.down", context: "ObMenu" },
      { keystroke: "up", action: "ob_menu.up", context: "ObMenu" },
      { keystroke: "tab", action: "ob_menu.down", context: "ObMenu" },
      { keystroke: "shift-tab", action: "ob_menu.up", context: "ObMenu" },
      { keystroke: "home", action: "ob_menu.home", context: "ObMenu" },
      { keystroke: "end", action: "ob_menu.end", context: "ObMenu" },
      { keystroke: "enter", action: "ob_menu.enter", context: "ObMenu" },
    ]);
  }

  items() { return Array.isArray(props()?.items) ? props().items.filter(Boolean) : []; }
  pickable() { return this.items().map((it, i) => [it, i]).filter(([it]) => !it.separator && !it.header && !it.disabled); }

  choose(i, cx) {
    const it = this.items()[i];
    if (!it || it.separator || it.header || it.disabled) return;
    closeOverlay(props()?.overlay);
    if (it.copy != null) cx.write_to_clipboard(String(it.copy));
    if (it.overlay) openOverlay(it.overlay);
    if (it.command) run(it.command, it.args ?? {});
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
    const list = this.items();
    const pick = this.pickable();
    if (this.at >= pick.length) this.at = pick.length - 1;
    const cur = pick[this.at]?.[1];
    const title = props()?.title;
    return v_flex().id("ob-menu").key_context("ObMenu").track_focus(this.handle).w_full().min_h(0).p(5).bg(t.popover).text_size(S.text)
      .on_action("ob_menu.escape", () => closeOverlay(props()?.overlay))
      .on_action("ob_menu.down", (_e, cx) => { if (!pick.length) return; this.at = (this.at + 1) % pick.length; cx.notify(); })
      .on_action("ob_menu.up", (_e, cx) => { if (!pick.length) return; this.at = this.at <= 0 ? pick.length - 1 : this.at - 1; cx.notify(); })
      .on_action("ob_menu.home", (_e, cx) => { if (!pick.length) return; this.at = 0; cx.notify(); })
      .on_action("ob_menu.end", (_e, cx) => { if (!pick.length) return; this.at = pick.length - 1; cx.notify(); })
      .on_action("ob_menu.enter", (_e, cx) => { if (pick[this.at]) this.choose(pick[this.at][1], cx); })
      .on_key_down((e, cx) => {
        if (e.key === "escape") { closeOverlay(props()?.overlay); return; }
        if (!pick.length) return;
        if (e.key === "down" || (e.key === "tab" && !e.modifiers?.shift)) this.at = (this.at + 1) % pick.length;
        else if (e.key === "up" || e.key === "tab") this.at = this.at <= 0 ? pick.length - 1 : this.at - 1;
        else if (e.key === "home") this.at = 0;
        else if (e.key === "end") this.at = pick.length - 1;
        else if (e.key === "enter") { if (pick[this.at]) this.choose(pick[this.at][1], cx); return; }
        else return;
        cx.stop_propagation();
        cx.notify();
      })
      .when(Boolean(title), (e) => e.child(div().h(22).px(8).flex().flex_none().items_center().text_size(S.textXs).font_semibold().text_color(t.dim).border_b(1).border_color(t.border).mb(4)
        .child(div().min_w(0).truncate().child(String(title)))))
      .children(list.map((it, i) => {
        if (it.separator) return div().mx(6).my(4).h(1).flex_none().bg(t.border);
        if (it.header) return div().h(24).px(8).pt(4).flex().flex_none().items_center().text_size(S.textXs).font_semibold().text_color(t.dim).child(div().min_w(0).truncate().child(String(it.header)));
        const fg = it.disabled ? alpha(t.dim, 0.8) : it.danger ? t.blocked : t.foreground;
        const lead = it.dot
          ? h_flex().size(S.iconSm).flex_none().items_center().justify_center().child(div().size(7).rounded_full().bg(t[it.dot] ?? it.dot))
          : it.icon ? icon(it.icon, S.iconSm, it.disabled ? alpha(t.dim, 0.8) : it.danger ? t.blocked : t.muted) : div().w(S.iconSm).flex_none();
        return h_flex().id(`mi-${i}`).h(30).flex_none().px(8).gap(9).rounded(S.radius).items_center().text_color(fg)
          .when(Boolean(it.indent), (e) => e.pl(8 + 23))
          .when(i === cur, (e) => e.bg(it.danger ? alpha(t.blocked, 0.14) : t.selected))
          .when(!it.disabled, (e) => e.cursor_pointer()
            .hover((s) => s.bg(it.danger ? alpha(t.blocked, 0.14) : t.hover))
            .on_hover((h, cx) => { if (!h) return; const k = pick.findIndex(([, j]) => j === i); if (k >= 0 && k !== this.at) { this.at = k; cx.notify(); } })
            .on_click((_e, cx) => this.choose(i, cx)))
          .child(lead)
          .child(div().flex_1().min_w(0).truncate().child(String(it.label ?? "")))
          .when(Boolean(it.hint), (e) => e.child(div().flex_none().max_w(120).truncate().text_size(S.textXs).text_color(t.dim).child(String(it.hint))))
          .when(Boolean(it.checked), (e) => e.child(icon("check", S.iconSm, t.accent)))
          .when(Boolean(it.kbd), (e) => e.child(kbd(it.kbd)));
      }));
  }
}
