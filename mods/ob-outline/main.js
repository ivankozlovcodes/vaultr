// ob-outline: an outline of the active tab's panes, processes, and agent tasks.
// Lists each pane in the current tab with its title, command/program, working directory,
// status, and any active subagents or tasks. Clicking a pane focuses it.
//
// Commands (herdr-app do ob-outline.<cmd>): focus, next, prev, open.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import { panes, spaces, focused, run, theme, props, nextCommand, settings } from "herdr";
import {
  S, alpha, icon, programIcon, iconButton, treeRow, sectionHeader, emptyState, statusMark,
  takeFocus, paneName, tabLabel, subagentsOf, openView,
} from "./kit.js";

function shortenPath(p) {
  if (!p) return "";
  const s = String(p);
  const home = typeof process !== "undefined" && process?.env?.HOME ? process.env.HOME : "/home/iv";
  return s.startsWith(home) ? "~" + s.slice(home.length) : s;
}

export default class Outline extends View {
  init(_p, cx) {
    this.w = 300;
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.cursor = 0;
    this.kbd = false;
    this.items = []; // [{ kind: 'pane'|'task', id, pane }]

    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { this.command(c); } catch (e) { console.log(`ob-outline: ${c} failed: ${e}`); }
        cx.notify();
      }
    });
  }

  command(c) {
    const s = String(c ?? "").trim();
    switch (s) {
      case "focus":
        this.handle.focus();
        this.kbd = true;
        if (this.cursor < 0 && this.items.length) this.cursor = 0;
        break;
      case "next": this.step(1); break;
      case "prev": this.step(-1); break;
      case "open":
        if (this.items[this.cursor]) this.openItem(this.items[this.cursor]);
        break;
      default:
        console.log(`ob-outline: unknown command ${c}`);
    }
  }

  step(d) {
    if (!this.items.length) return;
    this.cursor = this.cursor < 0 ? 0 : Math.max(0, Math.min(this.items.length - 1, this.cursor + d));
    this.kbd = true;
    const ri = this.rowIndex?.get(this.cursor);
    if (ri != null) this.scroll.scroll_to_item(ri);
  }

  openItem(it) {
    if (!it) return;
    if (it.kind === "pane" && it.pane) {
      this.focusPane(it.pane);
    } else if (it.kind === "run" && it.id) {
      openView("ob-subagents", `run:${it.id}`);
    } else if (it.kind === "claude" && it.id) {
      openView("ob-subagents", `claude:${it.id}`);
    }
  }

  focusPane(p) {
    const paneId = typeof p === "string" ? p : p?.pane;
    if (!paneId) return;
    if (typeof app !== "undefined" && typeof app.focusPane === "function") {
      try { app.focusPane(paneId); } catch {}
    }
    run("pane.focus", { pane: paneId });
  }

  render(cx) {
    const t = theme();
    takeFocus(this, cx, props()?.slot ?? "ob-outline", this.handle, () => {
      this.kbd = true;
      if (this.cursor < 0 && this.items.length) this.cursor = 0;
    });

    const f = focused();
    const sp = spaces(), ps = panes();
    const curSpace = sp.find((s) => s.id === f?.space) ?? sp[0];
    const curTab = curSpace?.tabs?.find((x) => x.id === f?.tab) ?? curSpace?.tabs?.[0];

    const tabPanes = curTab ? ps.filter((p) => p.tab === curTab.id) : [];
    const items = [];
    const rows = [];
    this.rowIndex = new Map();

    const compact = this.w < 220;

    if (curTab && tabPanes.length) {
      const headerTitle = `${curSpace?.name ?? "Space"} / ${tabLabel(curTab, ps)}`;
      rows.push(
        sectionHeader({
          id: `tab-sec-${curTab.id}`,
          title: headerTitle.toUpperCase(),
          count: tabPanes.length,
          open: true,
        })
      );

      for (const p of tabPanes) {
        const itemIndex = items.length;
        items.push({ kind: "pane", id: p.pane, pane: p });
        this.rowIndex.set(itemIndex, rows.length);

        const isCur = this.kbd && this.cursor === itemIndex;
        const isSelected = p.focused || p.pane === f?.pane;
        const pTitle = paneName(p) || p.title || (p.terminal ? "Terminal" : "Pane");
        const progName = p.program?.name || (p.terminal ? "shell" : "pane");
        const cwdStr = shortenPath(p.cwd);

        const after = [];
        if (p.branch && !compact) {
          after.push(
            h_flex().flex_none().gap(3).items_center().text_size(10).text_color(t.dim)
              .child(icon("git-branch", 10, t.dim))
              .child(p.branch)
          );
        }
        if (cwdStr && this.w >= 240) {
          after.push(
            div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(cwdStr)
          );
        }

        const right = [];
        if (p.zoomed) {
          right.push(icon("maximize", S.iconXs, t.accent));
        }
        if (p.status && p.status !== "idle") {
          right.push(statusMark(p.status, S.iconSm));
        }

        const lead = p.program
          ? programIcon(p.program, S.iconSm, t.muted)
          : icon(p.terminal ? "terminal" : "file-text", S.iconSm, t.muted);

        rows.push(
          treeRow({
            id: `pane-row-${p.pane}`,
            depth: 0,
            selected: isSelected,
            cursor: isCur,
            lead,
            label: pTitle,
            labelColor: isSelected ? t.foreground : t.muted,
            after: after.length ? after : undefined,
            right: right.length ? right : undefined,
            onClick: (_e, cx) => {
              this.cursor = itemIndex;
              this.kbd = false;
              this.focusPane(p);
              cx.notify();
            },
          })
        );

        // Subagents or runs under this pane's terminal
        if (p.terminal) {
          const sa = subagentsOf(p.terminal);
          for (const r of sa.runs) {
            const taskIndex = items.length;
            items.push({ kind: "run", id: r.key, pane: p });
            this.rowIndex.set(taskIndex, rows.length);

            const isTaskCur = this.kbd && this.cursor === taskIndex;
            const chain = (r.steps ?? []).map((s) => s.agent).filter(Boolean);
            const rLabel = chain.length > 2 ? `${r.mode ?? "workflow"} (${chain.length})` : chain.join(" → ") || r.mode || "run";
            const lastTask = (r.steps ?? []).at(-1)?.task;

            rows.push(
              treeRow({
                id: `run-row-${r.key}`,
                depth: 1,
                height: S.rowSm,
                cursor: isTaskCur,
                lead: icon("subagents", S.iconXs, t.dim),
                label: rLabel,
                labelColor: t.muted,
                after: lastTask && this.w >= 260
                  ? [div().min_w(0).flex_shrink(100).truncate().text_size(S.textXs).text_color(t.dim).child(lastTask)]
                  : undefined,
                right: [statusMark(r.live ? "working" : r.state ?? "idle", S.iconXs)],
                onClick: (_e, cx) => {
                  this.cursor = taskIndex;
                  this.openItem(items[taskIndex]);
                  cx.notify();
                },
              })
            );
          }

          for (const c of sa.claude) {
            const claudeIndex = items.length;
            items.push({ kind: "claude", id: c.key, pane: p });
            this.rowIndex.set(claudeIndex, rows.length);

            const isClaudeCur = this.kbd && this.cursor === claudeIndex;
            rows.push(
              treeRow({
                id: `claude-row-${c.key}`,
                depth: 1,
                height: S.rowSm,
                cursor: isClaudeCur,
                lead: icon("bot", S.iconXs, t.dim),
                label: c.desc || c.type || "agent",
                labelColor: t.muted,
                right: [statusMark(c.live ? "working" : "idle", S.iconXs)],
                onClick: (_e, cx) => {
                  this.cursor = claudeIndex;
                  this.openItem(items[claudeIndex]);
                  cx.notify();
                },
              })
            );
          }
        }
      }
    }

    this.items = items;
    if (this.cursor >= items.length) this.cursor = items.length - 1;

    const body = !tabPanes.length
      ? emptyState({
          icon: "list",
          title: "No panes in active tab",
          body: "Panes, processes, and agent tasks in your current tab show up here.",
        })
      : div().relative().flex_1().min_h(0)
          .child(
            v_flex().id("list").size_full().px(4).pb(10).overflow_y_scroll().track_scroll(this.scroll).children(rows)
          )
          .child(Scrollbar.vertical("list").absolute().inset_0());

    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_size(S.text)
      .on_size_change((s, cx) => {
        const w = s.width / (settings().zoom ?? 1);
        if (Math.abs(w - this.w) > 1) {
          this.w = w;
          cx.notify();
        }
      })
      .on_key_down((e, cx) => {
        if (e.key === "down") this.step(1);
        else if (e.key === "up") this.step(-1);
        else if (e.key === "enter") {
          if (this.items[this.cursor]) this.openItem(this.items[this.cursor]);
        } else if (e.key === "escape") {
          this.kbd = false;
        } else {
          return;
        }
        cx.stop_propagation();
        cx.notify();
      })
      .child(
        h_flex().h(28).flex_none().pl(S.pad + 4).pr(S.pad).items_center().text_size(S.textXs).text_color(t.dim)
          .child(
            div().flex_1().min_w(0).truncate().child(
              tabPanes.length
                ? `${tabPanes.length} pane${tabPanes.length === 1 ? "" : "s"} in tab`
                : "Outline"
            )
          )
      )
      .child(body);
  }
}
