// ob-strip: Obsidian's sidebar tab header. One icon tab per child of a stack (props.stack),
// read live from layout(); titles/icons from kit VIEWS. Click selects, right-click opens the
// group menu (move a view to another group, hide/show a group, close the sidebar).
// Used as a window_drag block above a top stack and as the `header` of a bottom stack. Hiding a top half hides
// its strip too, so the bottom strip of that side then draws the top strip's window buttons or sidebar toggle.
// props: { stack, side: "left"|"right", place: "top"|"bottom", windowButtons?: bool }
// Commands (ob-strip.<cmd>, every shown copy gets them; each acts only on its own stack):
//   select:<child>   move:<child>@<targetStack>   hide-group:<stack>   show-group:<stack>   overflow:<stack>

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { layout, props, run, nextCommand, settings, agents, shared, window as appWindow } from "herdr";
import {
  S, NODE, icon, iconButton, stripTab, viewInfo, findNode, findParent, openMenu, subagentCounts, alpha, stop, tc,
} from "./kit.js";
import { HALVES, halfAction, standInFor } from "./halves.js";
import { stripView } from "./strip_view.js";

// The four groups of the layout: [stack id, node to hide/show for the group, title].
const GROUPS = [
  [NODE.leftTopStack, NODE.leftTop, "Left sidebar, top"],
  [NODE.leftBottomStack, NODE.leftBottomStack, "Left sidebar, bottom"],
  [NODE.rightTopStack, NODE.rightTop, "Right sidebar, top"],
  [NODE.rightBottomStack, NODE.rightBottomStack, "Right sidebar, bottom"],
];
const groupNode = (stack) => HALVES[stack]?.node ?? stack;
const sideNode = (stack) => (stack === NODE.leftTopStack || stack === NODE.leftBottomStack ? NODE.left : NODE.right);
const siblingGroup = (stack) => ({ [NODE.leftTopStack]: NODE.leftBottomStack, [NODE.leftBottomStack]: NODE.leftTopStack, [NODE.rightTopStack]: NODE.rightBottomStack, [NODE.rightBottomStack]: NODE.rightTopStack })[stack];

export default class Strip extends View {
  init(_p, cx) {
    this.width = 0;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { await this.command(c, cx); } catch (e) { console.log(`ob-strip: ${c} failed: ${e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
  }

  mine() { return props()?.stack; }

  async command(c, cx) {
    const [verb, arg = ""] = splitCmd(c);
    const root = layout();
    const stack = findNode(root, this.mine());
    if (!stack) return;
    if (verb === "select") {
      if (stack.children?.some((ch) => ch.id === arg)) run("layout.select", { stack: stack.id, child: arg });
    } else if (verb === "move") {
      const [child, target] = arg.split("@");
      if (stack.children?.some((ch) => ch.id === child)) await moveView(child, target);
    } else if (verb === "hide-group" && arg === stack.id) {
      run("layout.hide", { id: groupNode(stack.id) });
    } else if (verb === "show-group" && arg === siblingGroup(stack.id)) {
      run("layout.show", { id: groupNode(arg) });
    } else if (verb === "overflow" && arg === stack.id) {
      this.overflowMenu(stack, 9999);
    }
  }

  // The group menu: switch to any view, move this view elsewhere, hide/show groups.
  menu(stack, child) {
    const root = layout();
    const items = [];
    if (child) {
      const info = viewInfo(child);
      items.push({ label: info.title, icon: info.icon, disabled: true });
      for (const [sid, , title] of GROUPS) {
        if (sid === stack.id || !findNode(root, sid)) continue;
        items.push({ label: `Move to ${title.toLowerCase()}`, icon: "move", command: `ob-strip.move:${child.id}@${sid}` });
      }
      items.push({ separator: true });
    }
    const sib = siblingGroup(stack.id);
    const sibNode = findNode(root, groupNode(sib));
    if (sibNode?.hidden) items.push({ label: "Show the other group", icon: "split-down", command: `ob-strip.show-group:${sib}` });
    else if (sibNode) items.push({ label: "Hide this group", icon: "minimize", command: `ob-strip.hide-group:${stack.id}` });
    const side = sideNode(stack.id);
    items.push({ label: side === NODE.left ? "Close left sidebar" : "Close right sidebar", icon: side === NODE.left ? "panel-left" : "panel-right", command: "layout.hide", args: { id: side } });
    openMenu(items, { width: 240 });
  }

  overflowMenu(stack, fit) {
    const kids = (stack.children ?? []).filter((c) => !c.hidden);
    const rest = kids.slice(fit === 9999 ? 0 : fit);
    openMenu(rest.map((c) => ({ label: viewInfo(c).title, icon: viewInfo(c).icon, checked: c.id === (stack.active ?? kids[0]?.id), command: "layout.select", args: { stack: stack.id, child: c.id } })), { width: 200 });
  }

  badge(id) {
    if (id === "ob-outline") { const n = subagentCounts().live; return n ? { n } : null; }
    if (id === "ob-agents") { const n = agents().filter((a) => a.status === "blocked").length; return n ? { n, color: tc().blocked } : null; }
    return null;
  }

  render() {
    const t = tc();
    const p = props() ?? {};
    const root = layout();
    const stack = findNode(root, p.stack);
    const top = p.place !== "bottom";
    const zoom = settings().zoom ?? 1;
    const avail = this.width / zoom;
    const kids = (stack?.children ?? []).filter((c) => !c.hidden);
    const active = stack?.active ?? kids[0]?.id;
    const w = appWindow();
    // Window buttons: this strip asks for them (props) and ob.settings allows them (auto = what Herdr wants).
    const wbMode = shared("ob.settings")?.windowButtons ?? "auto";
    // This strip's half: collapse its own, or restore the other one when that is hidden (halves.js decides).
    const half = halfAction(root, p.stack);
    // A bottom strip whose top half is hidden draws the top strip's controls too (halves.js: standInFor).
    const lent = standInFor(root, p.stack);
    const winButtons = Boolean(p.windowButtons || lent?.windowButtons) && (wbMode === "always" || (wbMode === "auto" && Boolean(w?.buttons)));
    const sideToggle = (top || Boolean(lent)) && p.side === "left";
    // Room: 8 padding + tabs (28 + 2 gap) + right-side buttons.
    const fixed = 16 + (sideToggle ? 31 : 0) + (half ? 31 : 0) + (winButtons ? 3 * 31 : 0);
    const fit = this.width ? Math.max(1, Math.floor((avail - fixed - 31) / 31)) : kids.length;
    const shown = kids.length > fit ? kids.slice(0, fit) : kids;
    // Keep the active tab visible when it would overflow: swap it into the last slot.
    if (kids.length > fit && !shown.some((c) => c.id === active)) shown[shown.length - 1] = kids.find((c) => c.id === active);
    // The view decides the label, tooltips and the half control (strip_view.js); this draws them as a bar.
    const named = (list) => list.map((c) => ({ id: c.id, ...viewInfo(c) }));
    const view = stripView({ kids: named(kids), shown: named(shown), active, half });
    return h_flex().id("strip").size_full().px(S.pad).gap(3).items_center().bg(t.raised)
      .border_b(1).border_color(t.border)
      .on_size_change((size, cx) => { if (Math.abs(size.width - this.width) > 1) { this.width = size.width; cx.notify(); } })
      .when(!stack, (e) => e.child(div().text_size(S.textXs).text_color(t.dim).child(`ob-strip: no stack "${p.stack}"`)))
      .children(view.tabs.map((tab) => {
        const c = kids.find((k) => k.id === tab.id);
        const b = this.badge(c.id);
        return stripTab({
          id: `tab-${c.id}`, icon: tab.icon, title: tab.tip, active: tab.active,
          badge: b?.n, badgeColor: b?.color,
          onClick: () => run("layout.select", { stack: stack.id, child: c.id }),
          onRight: () => this.menu(stack, c),
        }).when(tab.active, (e) => e.child(div().absolute().left(6).right(6).bottom(0).h(2).rounded(S.radius).bg(t.accent)));
      }))
      .when(kids.length > shown.length, (e) => e.child(iconButton({ id: "overflow", icon: "chevron-down", size: S.tab, tip: "More views", onClick: () => this.overflowMenu(stack, fit) })))
      // Empty strip: drags the window (top strips are window_drag blocks); right-click: group menu.
      .child(h_flex().id("strip-fill").flex_1().min_w(0).h_full().items_center().px(4)
        .when(Boolean(stack), (e) => e.on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.menu(stack, null); }))
        .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).font_semibold().text_color(t.foreground).child(view.label)))
      .when(sideToggle, (e) => e.child(iconButton({ id: "toggle-left", icon: "panel-left", size: S.tab, tip: "Close left sidebar (Ctrl+B)", onClick: () => run("layout.hide", { id: NODE.left }) })))
      .when(half?.kind === "collapse", (e) => e.child(iconButton({ id: "half-collapse", icon: "minimize", size: S.tab, tip: view.half.tip, onClick: () => run("layout.hide", { id: half.node }) })))
      .when(half?.kind === "restore", (e) => e.child(iconButton({ id: "half-restore", icon: "split-down", size: S.tab, tip: view.half.tip, onClick: () => run("layout.show", { id: half.node }) })))
      .when(winButtons, (e) => e
        .child(iconButton({ id: "win-min", icon: "win-min", size: S.tab, tip: "Minimize", onClick: () => run("window.minimize") }))
        .child(iconButton({ id: "win-max", icon: w?.maximized ? "win-restore" : "win-max", size: S.tab, tip: w?.maximized ? "Restore" : "Maximize", onClick: () => run("window.maximize") }))
        .child(iconButton({ id: "win-close", icon: "x", size: S.tab, tip: "Close window", onClick: () => run("window.close") })));
  }
}

// "move:a@b" -> ["move", "a@b"]; "select" -> ["select", ""].
function splitCmd(c) {
  const i = String(c).indexOf(":");
  return i < 0 ? [String(c), ""] : [c.slice(0, i), c.slice(i + 1)];
}

// Move a view (stack child) to another stack by rewriting the personal layout file through
// layout.set (verified: replaces the tree of a personal layout and rewrites its file).
// The live tree (layout(): the file merged with clicks: sizes, hidden, active) is the base, so the
// rewrite keeps what the person sees; a tree read from the file would reset every stack's active child.
async function moveView(childId, targetStack) {
  const tree = JSON.parse(JSON.stringify(layout()));
  const from = findParent(tree, childId);
  const to = findNode(tree, targetStack);
  if (!from || from.type !== "stack" || !to || to.type !== "stack" || from === to) return;
  const node = from.children.find((c) => c.id === childId);
  from.children = from.children.filter((c) => c.id !== childId);
  if (from.active === childId) from.active = from.children[0]?.id;
  to.children = [...(to.children ?? []), node];
  to.active = childId;
  run("layout.set", { layout: tree });
}
