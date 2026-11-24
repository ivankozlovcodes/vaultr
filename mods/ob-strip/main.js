// ob-strip: Obsidian's sidebar tab header. One icon tab per child of a stack (props.stack),
// read live from layout(); titles/icons from kit VIEWS. Click selects, right-click opens the
// group menu (move a view to another group, hide/show a group, close the sidebar).
// Used as a window_drag block above a top stack and as the `header` of a bottom stack. Hiding a top half hides
// its strip too, so the bottom strip of that side then draws the top strip's window buttons or sidebar toggle.
// props: { stack, side: "left"|"right", place: "top"|"bottom", windowButtons?: bool }
// Commands (ob-strip.<cmd>, every shown copy gets them; each acts only on its own stack):
//   select:<child>   move:<child>@<targetStack>   reorder:<from>@<to>   hide-group:<stack>   show-group:<stack>   overflow:<stack>

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { layout, props, run, nextCommand, settings, agents, terminals, shared, setShared, window as appWindow } from "herdr";
import {
  S, NODE, icon, iconButton, stripTab, viewInfo, findNode, openMenu, subagentCounts, alpha, stop, tc,
  agentAttention, attentionCounts, getDismissed, terminalsByAddress, chordLabel, bindingFor, lightsLeftPad,
} from "./kit.js";
import { HALVES, halfAction, standInFor } from "./halves.js";
import { stripView } from "./strip_view.js";
import { reorderStack, moveBetweenStacks, activeStripDrag } from "./reorder.js";

// Append the live chord from keys.json (e.g. "(Ctrl+B)" or "(⌘B)" on macOS) to a tooltip title.
const tip = (title, action) => { const k = bindingFor(action); return k ? `${title} (${chordLabel(k)})` : title; };

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
    this.pressed = null;
    this.pressPos = null;
    this.over = null;
    this.hoverStrip = false;
    this.dragPublished = false;
    this.dragToken = 0;
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { await this.command(c, cx); } catch (e) { console.log(`ob-strip: ${c} failed: ${e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
  }

  activeDrag() {
    const ext = activeStripDrag(shared("ob.stripDrag"));
    if (ext) return ext;
    return this.pressed ? { fromStack: this.mine(), childId: this.pressed } : null;
  }

  publishDrag(stackId, childId) {
    if (this.dragPublished || !stackId || !childId) return;
    this.dragPublished = true;
    setShared("ob.stripDrag", { fromStack: stackId, childId, at: Date.now() });
  }

  clearDrag(clearShared = true) {
    this.pressed = null;
    this.pressPos = null;
    this.over = null;
    this.hoverStrip = false;
    const wasPublished = this.dragPublished;
    this.dragPublished = false;
    if (clearShared && (wasPublished || shared("ob.stripDrag"))) {
      setShared("ob.stripDrag", null);
    }
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
      const [child, target, before = null] = arg.split("@");
      if (stack.children?.some((ch) => ch.id === child)) moveView(child, target, before || null);
    } else if (verb === "reorder") {
      const [fromId, toId] = arg.split("@");
      if (fromId && toId) reorderInStack(stack.id, fromId, toId);
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
    if (id === "ob-agents") {
      // The agents that need you, by the same rule as the Agents panel and the status bar (kit/attention.js).
      const tmap = terminalsByAddress(terminals());
      const dis = getDismissed();
      const n = attentionCounts(agents().map((a) => agentAttention(a, tmap, dis))).blocked;
      return n ? { n, color: tc().blocked } : null;
    }
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
    const topLeft = p.side === "left" && (top || Boolean(lent));
    const leftPad = topLeft ? lightsLeftPad(S.pad, w, root, zoom, 0) : S.pad;
    // Room: padding + tabs (28 + 2 gap) + right-side buttons.
    const fixed = leftPad + S.pad + (sideToggle ? 31 : 0) + (half ? 31 : 0) + (winButtons ? 3 * 31 : 0);
    const fit = this.width ? Math.max(1, Math.floor((avail - fixed - 31) / 31)) : kids.length;
    const shown = kids.length > fit ? kids.slice(0, fit) : kids;
    // Keep the active tab visible when it would overflow: swap it into the last slot.
    if (kids.length > fit && !shown.some((c) => c.id === active)) shown[shown.length - 1] = kids.find((c) => c.id === active);
    // The view decides the label, tooltips and the half control (strip_view.js); this draws them as a bar.
    const named = (list) => list.map((c) => ({ id: c.id, ...viewInfo(c) }));
    const view = stripView({ kids: named(kids), shown: named(shown), active, half });
    const drag = this.activeDrag();
    const isCrossTarget = Boolean(drag && stack && drag.fromStack !== stack.id && this.hoverStrip);
    const pressedIdx = view.tabs.findIndex((x) => x.id === (drag?.fromStack === stack?.id ? drag.childId : null));
    return h_flex().id("strip").size_full().pl(leftPad).pr(S.pad).gap(3).items_center()
      .bg(isCrossTarget ? alpha(t.accent, 0.10) : t.raised)
      .border_b(isCrossTarget ? 2 : 1).border_color(isCrossTarget ? t.accent : t.border)
      .on_size_change((size, cx) => { if (Math.abs(size.width - this.width) > 1) { this.width = size.width; cx.notify(); } })
      .on_mouse_move((_e, cx) => {
        const d = this.activeDrag();
        if (d && stack && d.fromStack !== stack.id && !this.hoverStrip) {
          this.hoverStrip = true;
          cx.notify();
        }
      })
      .on_window_mouse_move((e, cx) => {
        if (!this.pressed || this.dragPublished || !stack) return;
        const pos = e?.position;
        if (!this.pressPos || !pos || Math.hypot(pos.x - this.pressPos.x, pos.y - this.pressPos.y) >= 4) {
          this.publishDrag(stack.id, this.pressed);
          cx.notify();
        }
      })
      .on_mouse_up("left", (_e, cx) => {
        const d = this.activeDrag();
        if (d && stack && d.fromStack !== stack.id && this.hoverStrip) {
          moveView(d.childId, stack.id, null);
          this.clearDrag(true);
          cx.notify();
          return;
        }
        if (this.pressed || this.hoverStrip || this.over) {
          this.clearDrag(true);
          cx.notify();
        }
      })
      .on_window_mouse_up("left", (_e, cx) => {
        if (!this.pressed && !this.hoverStrip && !this.over && !this.dragPublished) return;
        const token = this.dragToken;
        // Defer cleanup one tick so a target strip's on_mouse_up always reads ob.stripDrag first.
        const finish = (cx2) => {
          if (this.dragToken !== token) return;
          const ownShared = activeStripDrag(shared("ob.stripDrag"))?.fromStack === stack?.id;
          this.clearDrag(this.dragPublished || ownShared);
          cx2?.notify?.();
        };
        if (typeof cx?.timer?.after === "function") cx.timer.after(0, finish);
        else finish(cx);
      })
      .on_hover((h, cx) => {
        if (!h) {
          const had = Boolean(this.over || this.hoverStrip);
          this.over = null;
          this.hoverStrip = false;
          if (this.pressed && stack) this.publishDrag(stack.id, this.pressed);
          if (had) cx.notify();
          return;
        }
        const d = this.activeDrag();
        if (d && stack && d.fromStack !== stack.id && !this.hoverStrip) {
          this.hoverStrip = true;
          cx.notify();
        }
      })
      .when(!stack, (e) => e.child(div().text_size(S.textXs).text_color(t.dim).child(`ob-strip: no stack "${p.stack}"`)))
      .children(view.tabs.map((tab, i) => {
        const c = kids.find((k) => k.id === tab.id);
        const b = this.badge(c.id);
        const dragging = Boolean(drag && drag.childId === c.id && (drag.fromStack !== stack.id || this.dragPublished || (this.over && this.over !== c.id)));
        const dropHere = Boolean(drag && drag.childId !== c.id && this.over === c.id);
        const crossDropHere = Boolean(dropHere && drag.fromStack !== stack.id);
        return stripTab({
          id: `tab-${c.id}`, icon: tab.icon, title: tab.tip, active: tab.active,
          badge: b?.n, badgeColor: b?.color,
          onRight: () => this.menu(stack, c),
        })
          .when(dragging, (e) => e.opacity(0.45))
          .on_hover((h, cx) => {
            if (!h) {
              if (this.pressed === c.id && stack) this.publishDrag(stack.id, c.id);
              if (this.over === c.id) { this.over = null; cx.notify(); }
            }
          })
          .on_mouse_down("left", (e, cx) => {
            cx.stop_propagation();
            this.dragToken += 1;
            this.pressed = c.id;
            this.pressPos = e?.position ? { x: e.position.x, y: e.position.y } : null;
            this.over = c.id;
            this.dragPublished = false;
          })
          .on_mouse_move((_e, cx) => {
            const d = this.activeDrag();
            if (!d) return;
            if (this.pressed && this.pressed !== c.id && stack) this.publishDrag(stack.id, this.pressed);
            let changed = false;
            if (d.fromStack !== stack.id && !this.hoverStrip) { this.hoverStrip = true; changed = true; }
            if (this.over !== c.id) { this.over = c.id; changed = true; }
            if (changed) cx.notify();
          })
          .on_mouse_up("left", (_e, cx) => {
            cx.stop_propagation();
            const d = this.activeDrag();
            const fromPressed = this.pressed;
            const over = this.over;
            if (d && d.fromStack !== stack.id) {
              moveView(d.childId, stack.id, c.id);
              this.clearDrag(true);
              cx.notify();
              return;
            }
            this.clearDrag(true);
            if (fromPressed && fromPressed !== c.id && over === c.id) reorderInStack(stack.id, fromPressed, c.id);
            else if (fromPressed === c.id && over === c.id) run("layout.select", { stack: stack.id, child: c.id });
            cx.notify();
          })
          .when(tab.active, (e) => e.child(div().absolute().left(6).right(6).bottom(0).h(2).rounded(S.radius).bg(t.accent)))
          .when(dropHere, (e) => e.child(div().absolute().top(4).bottom(4).w(2).rounded(1).bg(t.accent)
            .when(crossDropHere || pressedIdx > i, (l) => l.left(0))
            .when(!crossDropHere && pressedIdx >= 0 && pressedIdx < i, (l) => l.right(0))));
      }))
      .when(isCrossTarget && !this.over, (e) => e.child(div().id("strip-drop-end").w(2).h(20).rounded(1).flex_none().bg(t.accent)))
      .when(kids.length > shown.length, (e) => e.child(iconButton({ id: "overflow", icon: "chevron-down", size: S.tab, tip: "More views", onClick: () => this.overflowMenu(stack, fit) })))
      // Empty strip: drags the window (top strips are window_drag blocks); right-click: group menu.
      .child(h_flex().id("strip-fill").flex_1().min_w(0).h_full().items_center().px(4)
        .when(Boolean(stack), (e) => e.on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.menu(stack, null); }))
        .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).font_semibold().text_color(t.foreground).child(view.label)))
      .when(sideToggle, (e) => e.child(iconButton({ id: "toggle-left", icon: "panel-left", size: S.tab, tip: tip("Close left sidebar", "layout.toggle:ob-left"), onClick: () => run("layout.hide", { id: NODE.left }) })))
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

// Move a view (stack child) to another stack (optionally before `beforeChildId`) by rewriting the personal layout
// through layout.set. The live tree (layout()) is the base so every stack's active child and sizes are preserved.
function moveView(childId, targetStack, beforeChildId = null) {
  const tree = moveBetweenStacks(layout(), childId, targetStack, beforeChildId);
  if (tree) run("layout.set", { layout: tree });
}

function reorderInStack(stackId, fromId, toId) {
  const tree = reorderStack(layout(), stackId, fromId, toId);
  if (tree) run("layout.set", { layout: tree });
}
