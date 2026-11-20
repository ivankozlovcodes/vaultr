// ob-pane: the pane header of the obsidian layout (one copy per pane; props { pane, terminal }).
// Obsidian's view header: back / forward on the left, the breadcrumb
// "machine / space / tab / pane" centered (left-aligned when narrow), and on the right the
// sub-agent badge, the status (or "Needs you"), split / zoom / close on hover and "more" (⋮).
// Every breadcrumb segment opens a menu of its siblings. A click on the header focuses the pane;
// focus follows the pointer (follow.js).
// Mod panes (no terminal) show only their name and a close button.
//
// Commands (ob-pane.<cmd>; every copy gets them, only the one whose pane matches acts):
//   more:<paneId>   crumb:<paneId>@<machine|space|tab>   bookmark:<paneId>

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { panes, spaces, agents, terminals, props, run, nextCommand, shared as _shared, settings, notify } from "herdr";
import {
  S, tc, alpha, icon, iconButton, statusMark, needsYou, paneLabelOf, tabLabel, machineLabel, programIcon, openMenu,
  subagentsOf, isBookmarked, toggleBookmark, bindingFor, chordLabel, tilde, stop,
} from "./kit.js";
import { follow, DELAY } from "./follow.js"; // focus-to-hover

const shared = (k) => (k ? _shared(k) : { "ob.zen": _shared("ob.zen") });

const tip = (title, action) => { const k = action ? bindingFor(action) : null; return k ? `${title} (${chordLabel(k)})` : title; };

export default class PaneHeader extends View {
  init(_p, cx) {
    this.w = 0;
    this.hovered = false;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(String(c)); } catch (e) { console.log(`ob-pane: ${c} failed: ${e?.message ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
  }

  // Everything this header is about, or null when the pane is gone.
  ctx() {
    const id = props()?.pane;
    const ps = panes();
    const p = ps.find((x) => x.pane === id);
    if (!p) return null;
    const space = spaces().find((s) => s.tabs.some((x) => x.id === p.tab)) ?? null;
    const tab = space?.tabs.find((x) => x.id === p.tab) ?? null;
    return { p, ps, space, tab, addr: p.terminal ?? null };
  }

  command(c) {
    const i = c.indexOf(":");
    const verb = i < 0 ? c : c.slice(0, i);
    const arg = i < 0 ? "" : c.slice(i + 1);
    const j = arg.indexOf("@");
    const paneId = j < 0 ? arg : arg.slice(0, j);
    if (paneId !== props()?.pane) return; // another pane's header
    const x = this.ctx();
    if (!x) return;
    if (verb === "more") this.moreMenu(x);
    else if (verb === "crumb") this.crumbMenu(x, j < 0 ? "tab" : arg.slice(j + 1));
    else if (verb === "bookmark") this.bookmark(x);
  }

  bookmark(x) {
    if (!x.addr) return;
    const tName = x.tab ? tabLabel(x.tab, x.ps) : "";
    const pName = paneLabelOf(x.p, tName);
    const label = `${tName}${tName ? " · " : ""}${pName}`;
    const added = toggleBookmark({ kind: "terminal", id: x.addr, label, machine: x.space?.machine ?? null });
    notify({ title: added ? "Bookmarked" : "Bookmark removed", body: label, level: "info", timeout: 1500 });
  }

  crumbMenu(x, seg) {
    const { p, ps, space, tab } = x;
    if (seg === "machine") {
      const m = space?.machine ?? null;
      const mine = spaces().filter((s) => (s.machine ?? null) === m);
      openMenu([
        ...mine.map((s) => ({ label: s.name || "space", icon: "layers", checked: s.id === space?.id, hint: `${s.tabs.length} tab${s.tabs.length === 1 ? "" : "s"}`, command: "space.select", args: { id: s.id } })),
        { separator: true },
        { label: "New space here", icon: "folder-plus", command: "space.new", args: { machine: m ?? "" } },
      ], { title: machineLabel(m), width: 250 });
    } else if (seg === "space") {
      if (!space) return;
      openMenu([
        ...space.tabs.map((t) => ({ label: tabLabel(t, ps), icon: "tab", checked: t.id === tab?.id, hint: t.settled ? "settled" : undefined, command: "tab.select", args: { id: t.id } })),
        { separator: true },
        { label: "New tab here", icon: "plus", command: "tab.new", args: { space: space.id }, kbd: bindingFor("tab.new") ?? undefined },
      ], { title: space.name || "Space", width: 250 });
    } else {
      if (!tab) return;
      const tName = tabLabel(tab, ps);
      const mine = ps.filter((q) => q.tab === tab.id);
      openMenu([
        ...mine.map((q) => ({ label: paneLabelOf(q, tName), icon: q.terminal ? "terminal" : "file-text", checked: q.pane === p.pane, hint: q.status && q.status !== "idle" ? q.status : undefined, command: "pane.focus", args: { pane: q.pane } })),
        { separator: true },
        { label: "Split right", icon: "split-right", command: "pane.split", args: { direction: "right", pane: p.pane } },
        { label: "Split down", icon: "split-down", command: "pane.split", args: { direction: "down", pane: p.pane } },
      ], { title: tName, width: 250 });
    }
  }

  moreMenu(x) {
    const { p, ps, tab, addr } = x;
    const pTitle = paneLabelOf(p, tab ? tabLabel(tab, ps) : "");
    const zenActive = Boolean(shared()?.["ob.zen"]?.active);
    const zenItem = {
      label: zenActive ? "Exit Zen mode" : "Enter Zen mode",
      icon: zenActive ? "minimize" : "maximize",
      command: "ob-tabs.zen",
      kbd: bindingFor("ob-tabs.zen") ?? undefined,
    };
    if (!addr) {
      openMenu([
        { label: p.zoomed ? "Unzoom" : "Zoom", icon: p.zoomed ? "minimize" : "maximize", command: "pane.zoom", args: { pane: p.pane } },
        zenItem,
        { separator: true },
        { label: "Close pane", icon: "x", danger: true, command: "pane.close", args: { pane: p.pane } },
      ], { width: 240, title: pTitle });
      return;
    }
    const agent = agents().find((a) => a.address === addr);
    const term = terminals().find((t) => t.address === addr);
    const labels = term?.labels && typeof term.labels === "object" ? term.labels : {};
    const toProgram = labels["herdr.right-click"] === "program";
    const marked = isBookmarked("terminal", addr);
    openMenu([
      tab ? { label: "Rename tab…", icon: "rename", command: "tab.rename", args: { id: tab.id }, kbd: bindingFor("tab.rename") ?? undefined } : null,
      { label: marked ? "Remove bookmark" : "Bookmark", icon: marked ? "bookmark" : "bookmark-plus", command: `ob-pane.bookmark:${p.pane}` },
      { separator: true },
      { label: "Show properties", icon: "info", command: `ob-tabs.open:ob-props@term:${addr}` },
      { label: "Show subagents", icon: "subagents", command: `ob-tabs.open:ob-outline@term:${addr}` },
      { label: "Copy address", icon: "copy", copy: addr, hint: addr },
      p.cwd ? { label: "Copy path", icon: "copy", copy: p.cwd, hint: tilde(p.cwd) } : null,
      agent ? { label: agent.pinned ? "Unpin agent" : "Pin agent to the top", icon: agent.pinned ? "pin-off" : "pin", command: "terminal.pin", args: { terminal: addr, pinned: !agent.pinned } } : null,
      { label: toProgram ? "Right-clicks to Herdr's menu" : "Right-clicks to the program", icon: "terminal", command: "terminal.right_click", args: { to: toProgram ? "menu" : "program", terminal: addr } },
      { separator: true },
      { label: "Split right", icon: "split-right", command: "pane.split", args: { direction: "right", pane: p.pane } },
      { label: "Split down", icon: "split-down", command: "pane.split", args: { direction: "down", pane: p.pane } },
      { label: p.zoomed ? "Unzoom" : "Zoom", icon: p.zoomed ? "minimize" : "maximize", command: "pane.zoom", args: { pane: p.pane } },
      zenItem,
      { separator: true },
      { label: "Close pane", icon: "x", danger: true, command: "pane.close", args: { pane: p.pane } },
    ], { width: 260, title: pTitle });
  }

  render(cx) {
    const zenActive = Boolean(shared()?.["ob.zen"]?.active);
    const pr = props() ?? {};
    return follow(this, pr.pane, this.header(cx, zenActive), pr.delay ?? DELAY);
  }

  header(cx, zenActive = Boolean(shared()?.["ob.zen"]?.active)) {
    const t = tc();
    const x = this.ctx();
    if (!x) return div().size_full().bg(t.background);
    const { p, ps, space, tab, addr } = x;
    const w = this.w || 800;
    const wide = w >= 360;
    const small = (id, ic, tipText, onClick, o = {}) => iconButton({ id, icon: ic, size: 24, iconSize: S.iconSm, tip: tipText, onClick, ...o });
    const h = shared("ob.history");
    const canBack = Boolean(h && h.index > 0);
    const canFwd = Boolean(h && Array.isArray(h.entries) && h.index < h.entries.length - 1);
    const raw = paneLabelOf(p, tab ? tabLabel(tab, ps) : "");
    const name = p.mod && raw === p.mod ? raw.charAt(0).toUpperCase() + raw.slice(1) : raw;

    // Right side.
    const right = [];
    let rightW = 0;
    if (zenActive) {
      rightW += 52;
      right.push(
        h_flex().id("zen-pill").flex_none().h(20).px(6).gap(4).rounded(4).items_center().cursor_pointer()
          .bg(alpha(t.accent, 0.14)).hover((s) => s.bg(alpha(t.accent, 0.24)))
          .text_size(S.xs).font_medium().text_color(t.accent)
          .tooltip(tip("Exit Zen mode", "ob-tabs.zen"))
          .on_mouse_down("left", stop(() => run("ob-tabs.zen")))
          .child(icon("minimize", 11, t.accent))
          .child("Zen")
      );
    }
    if (addr) {
      const sub = subagentsOf(addr);
      const kids = terminals().filter((tm) => tm.parent === addr && tm.state === "live").length;
      const live = sub.live + kids;
      const total = sub.total + kids;
      if (total > 0 && w >= 260) {
        rightW += live ? 64 : 40;
        right.push(h_flex().id("subagents").h(20).px(6).gap(4).flex_none().items_center().rounded(10).cursor_pointer()
          .bg(live ? alpha(t.working, 0.14) : t.raised).text_size(S.textXs).font_medium().text_color(live ? t.working : t.muted)
          .hover((s) => s.bg(live ? alpha(t.working, 0.22) : t.hover))
          .tooltip(live ? `${live} sub-agent${live === 1 ? "" : "s"} running, ${total} in all` : `${total} finished sub-agent${total === 1 ? "" : "s"}`)
          .on_mouse_down("left", stop)
          .on_click((_e, cx) => { cx.stop_propagation(); run(`ob-tabs.open:ob-outline@term:${addr}`); })
          .child(icon("subagents", S.iconXs))
          .child(live ? `${live} live` : String(total)));
      }
      if (p.status === "blocked" && w >= 300) { right.push(needsYou()); rightW += 70; }
      else if (p.status) { right.push(h_flex().w(18).flex_none().justify_center().child(statusMark(p.status)).tooltip(p.status)); rightW += 18; }
    }
    if (this.hovered && w >= 300) {
      if (addr) {
        right.push(small(`split-r-${p.pane}`, "split-right", tip("Split right", "pane.split:right"), () => run("pane.split", { direction: "right", pane: p.pane })));
        right.push(small(`split-d-${p.pane}`, "split-down", tip("Split down", "pane.split:down"), () => run("pane.split", { direction: "down", pane: p.pane })));
      }
      right.push(small(`zoom-${p.pane}`, p.zoomed ? "minimize" : "maximize", tip(p.zoomed ? "Unzoom" : "Zoom", "pane.zoom"), () => run("pane.zoom", { pane: p.pane })));
      rightW += (addr ? 3 : 1) * 26;
    }
    if (!addr || this.hovered) { right.push(small(`close-${p.pane}`, "x", tip("Close pane", "pane.close"), () => run("pane.close", { pane: p.pane }))); rightW += 26; }
    if (addr) { right.push(small(`more-${p.pane}`, "more", "More options", () => this.moreMenu(this.ctx() ?? x))); rightW += 26; }

    // The breadcrumb: machine / space / tab / pane, dropping from the left as the header narrows.
    const seg = (key, label, menuOf) => h_flex().id(`crumb-${key}`).h(22).px(5).min_w(0).max_w(190).flex_shrink(1).items_center().rounded(S.radius)
      .text_color(t.dim).cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.muted))
      .on_mouse_down("left", stop)
      .on_click((_e, cx) => { cx.stop_propagation(); const y = this.ctx(); if (y) this.crumbMenu(y, menuOf); })
      .child(div().min_w(0).truncate().child(label));
    const slash = () => div().flex_none().text_color(alpha(t.dim, 0.7)).child("/");
    // Room for the crumb: centered between equal side gutters when wide, else after the arrows.
    const leftW = addr ? 52 : 0;
    const side = Math.max(leftW, rightW) + 12;
    const room = wide ? w - 2 * side : w - leftW - rightW - 20;
    const textW = (str) => Math.ceil(String(str).length * 6.4);
    let used = 20 + Math.min(wide ? 320 : 999, textW(name)) + (p.zoomed ? 50 : 0);
    const crumbs = [];
    if (addr) {
      // Nearest first (tab, space, machine), each only while it fits whole.
      const parts = [
        tab ? ["tab", tabLabel(tab, ps), "tab"] : null,
        space ? ["space", space.name || "space", "space"] : null,
        ["machine", machineLabel(space?.machine ?? null), "machine"],
      ].filter(Boolean);
      for (const [key, label, menuOf] of parts) {
        const need = Math.min(textW(label), 180) + 10 + 14;
        if (used + need > room) break;
        used += need;
        crumbs.unshift(seg(key, label, menuOf), slash());
      }
    }
    const title = h_flex().ml(addr ? 4 : 0).flex_shrink(0).min_w(0).max_w(wide ? 320 : 999).gap(6).items_center()
      .child(p.terminal ? programIcon(p.program, S.iconSm, p.focused ? t.foreground : t.muted) : icon("file-text", S.iconSm, t.muted))
      .child(div().min_w(0).truncate().font_medium().text_color(p.focused ? t.foreground : t.muted).child(name))
      .when(Boolean(p.zoomed), (e) => e.child(div().flex_none().text_size(S.textXs).text_color(t.dim).child("zoomed")));
    const crumbRow = h_flex().min_w(0).gap(1).items_center().text_size(S.textSm).children(crumbs).child(title);

    return h_flex().id("root").relative().size_full().px(6).gap(2).items_center().bg(t.background).border_b(1).border_color(t.border)
      .text_size(S.textSm)
      .on_size_change((s, cx) => { const w0 = s.width / (settings().zoom || 1); if (Math.abs(w0 - this.w) > 1) { this.w = w0; cx.notify(); } })
      .on_hover((hv, cx) => { if (hv !== this.hovered) { this.hovered = hv; cx.notify(); } })
      .on_click(() => { if (!p.focused) run("pane.focus", { pane: p.pane }); })
      // Wide: the crumb sits centered over the whole header, clear of both sides (Obsidian's view title).
      .when(wide, (e) => e.child(h_flex().absolute().top(0).bottom(0).left(side).right(side).items_center().justify_center().child(crumbRow)))
      .when(Boolean(addr), (e) => e
        .child(small("back", "arrow-left", tip("Navigate back", "ob-tabs.back"), () => run("ob-tabs.back"), { disabled: !canBack }))
        .child(small("forward", "arrow-right", tip("Navigate forward", "ob-tabs.forward"), () => run("ob-tabs.forward"), { disabled: !canFwd })))
      .when(!wide, (e) => e.child(h_flex().flex_1().min_w(0).pl(4).child(crumbRow)))
      .when(wide, (e) => e.child(div().flex_1()))
      .child(h_flex().flex_none().gap(2).items_center().children(right));
  }
}
