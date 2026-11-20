// kit.js: shared look and helpers for every ob-* mod (the Obsidian layout).
// MASTER COPY: kit/kit.js. kit/sync.sh copies it into mods/ob-*/kit.js and fills in MOD.
// Never edit a mod's copy directly: kit/sync.sh overwrites it from kit/kit.js.

import { div, svg, image } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import {
  theme, run, exec, openOverlay, closeOverlay, layout, shared, setShared, keys, spaces, agents,
  terminals, panes, focused, home, appHome, readTextFile, window as appWindow,
} from "herdr";

// This copy's mod folder name (sync.sh writes it).
export const MOD = "ob-bookmarks";
export const LAYOUT = "vaultr";

// Pure agent helpers (kit/agents.js): which agents are main agents, the ones placed in a pane of a tab.
export { placedTerminals, mainAgents } from "./agents.js";

// Pure pane naming (kit/names.js): paneLabel(pane, ctx), shortFolder(folder, home). paneLabel is also used here.
import { paneLabel, cleanTitle } from "./names.js";
export { paneLabel, shortFolder, paneSecondary, cleanTitle } from "./names.js";

// The one fuzzy matcher (kit/fuzzy.js, fzf-style): fuzzy(q, text) -> { score, hits } | null, matchQuery for spans.
export { fuzzy, matchQuery } from "./fuzzy.js";

// Pure feed-age rule (kit/feed_age.js): when the sub-agent feed counts as paused, and the scanner's heartbeat.
export { feedLine, publishDue, FEED_BEAT_MS, FEED_STALE_MS } from "./feed_age.js";

// Pure ticker of running agents for the status row (kit/ticker.js).
export { tickerChips, tickerAction, TICKER_MAX } from "./ticker.js";

// Pure follow rule (kit/follow_target.js): which terminal the right-hand panels show.
export { followTarget } from "./follow_target.js";

// Pure macOS traffic-light inset rule (kit/lights.js): left padding for top-left chrome bars.
export { lightsLeftPad, paneLightsLeftPad } from "./lights.js";

// Provider facade (kit/provider.js): single entry point for provider discovery, transcripts, usage, search, scan.
import { makeProvider } from "./provider.js";
export { makeProvider };

// Pure hidden rules and shared state (kit/hidden.js): hidden machines, spaces, tabs.
export {
  mKeyOf, normHidden, isMachineHidden, isSpaceHidden, isTabHidden, patchHidden,
} from "./hidden.js";
import {
  mKeyOf, normHidden, isMachineHidden, isSpaceHidden, isTabHidden, patchHidden,
} from "./hidden.js";

// ---------------------------------------------------------------- localStorage (per mod copy)
export function lsGet(k, fallback = null) {
  try {
    const raw = localStorage.getItem(k);
    return raw == null ? fallback : JSON.parse(raw) ?? fallback;
  } catch {
    return fallback;
  }
}
export function lsSet(k, v) {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* storage off */
  }
}

export function getHidden() {
  let h = shared("ob.hidden");
  if (!h) {
    h = lsGet("hidden", null);
    if (h) setShared("ob.hidden", h);
  }
  return h ?? { machines: [], spaces: [], tabs: [] };
}

export function updateHidden(mutator) {
  const cur = getHidden();
  const next = typeof mutator === "function" ? mutator(cur) : mutator;
  setShared("ob.hidden", next);
  lsSet("hidden", next);
  return next;
}

// Pure attention rules (kit/attention.js): who needs you, and dismissed "Needs you" entries. A dismissal changes
// attention only (sections, counts, badges, pills); the pane header, Properties and Outline show the real status.
export {
  attentionWord, attentionRank, attentionCounts, isNeedsYou, dismissStamp, normDismissed, isDismissed,
  attentionStatus, patchDismissed, pruneDismissed, isRecordLive, effectiveTermStatus,
} from "./attention.js";
import {
  attentionStatus, dismissStamp, normDismissed, isDismissed, patchDismissed, pruneDismissed,
  isRecordLive, effectiveTermStatus,
} from "./attention.js";

// Dismissals { [terminal address]: stamp }: shared as ob.dismissed and kept in storage, like ob.hidden.
export function getDismissed() {
  let d = shared("ob.dismissed");
  if (!d) {
    d = lsGet("dismissed", null);
    if (d) setShared("ob.dismissed", d);
  }
  return normDismissed(d);
}

export function updateDismissed(mutator) {
  const next = normDismissed(typeof mutator === "function" ? mutator(getDismissed()) : mutator);
  setShared("ob.dismissed", next);
  lsSet("dismissed", next);
  return next;
}

// Dismiss (on) the report `status` of `term` at `address`, or restore it (off).
export function setDismissed(address, on, status = null, term = null) {
  return updateDismissed((d) => patchDismissed(d, address, on ? dismissStamp(status, term) : null));
}

// Drops the dismissals whose terminal is gone or reports something new. current: Map address -> its stamp now.
// An empty map (nothing listed yet) drops nothing.
export function pruneDismissedNow(current) {
  const cur = getDismissed();
  if (!current?.size || !Object.keys(cur).length) return cur;
  const next = pruneDismissed(cur, current);
  return Object.keys(next).length === Object.keys(cur).length ? cur : updateDismissed(next);
}

// terminals() by address: a dismissal stamp reads the terminal's status_ms and turn.
export function terminalsByAddress(ts = terminals()) {
  const m = new Map();
  for (const t of ts ?? []) if (t?.address) m.set(t.address, t);
  return m;
}

// ---------------------------------------------------------------- sizes (design px at zoom 1)
export const S = {
  strip: 40,        // top strip of every column (icon tabs, tab bar)
  stripSm: 34,      // header strip of a lower stack
  footer: 40,       // left footer (vault row)
  status: 26,       // status bar
  row: 26,          // tree / list row
  rowSm: 22,        // compact row (sub-items)
  header: 28,       // section header inside a panel
  toolbar: 32,      // panel toolbar row (new, sort, collapse...)
  indent: 16,       // tree indent per depth
  pad: 8,           // panel side padding
  icon: 16,         // normal icon
  iconSm: 14,       // icon in rows / chips
  iconXs: 12,       // inline marks
  btn: 26,          // square icon button
  tab: 28,          // strip icon tab (square)
  radius: 4,        // rows, buttons
  radiusLg: 6,      // cards, inputs, popovers' items
  text: 13,         // body
  textSm: 12,       // secondary
  textXs: 11,       // meta, chips, section titles
  xs: 11,           // alias for textXs
  textLg: 15,       // titles in dialogs
};

// ---------------------------------------------------------------- colors
// theme() plus helpers. Use names, never hex, except MARK (the space avatar colors).
export const MARK = { ansi6: "#22a99a", ansi3: "#e3814f", ansi4: "#5b8def", ansi5: "#8b7cf6", ansi2: "#3fae6a", ansi1: "#d9649a" };
export function tc() { return theme(); }
// alpha("#rrggbb", 0.15) -> "#rrggbb26"; works on #rgb, #rrggbb and #rrggbbaa (multiplies).
export function alpha(c, a) {
  if (!c || c[0] !== "#") return c;
  let hex = c.slice(1);
  if (hex.length === 3) hex = hex.split("").map((x) => x + x).join("");
  let base = 1;
  if (hex.length === 8) { base = parseInt(hex.slice(6), 16) / 255; hex = hex.slice(0, 6); }
  const v = Math.max(0, Math.min(255, Math.round(base * a * 255)));
  return `#${hex}${v.toString(16).padStart(2, "0")}`;
}
// The color of an agent status word (working, blocked, done, idle) or a run state.
export function statusColor(t, s) {
  const k = normStatus(s);
  return k === "failed" ? t.blocked : t[k] ?? t.dim;
}

// ---------------------------------------------------------------- icons
// icon("search") draws mods/<this mod>/icons/search.svg tinted with `color` (default muted).
export function iconPath(name) { return `mods/${MOD}/icons/${name}.svg`; }
export function icon(name, size = S.icon, color) {
  const el = svg(iconPath(name)).size(size).flex_none();
  return color ? el.text_color(color) : el;
}
// A program's icon from the app's table (agents(), panes(), terminals() carry `program`).
export function programIcon(p, size = S.iconSm, color) {
  if (!p?.icon) return icon("terminal", size, color);
  return p.tint ? svg(p.icon).size(size).flex_none().text_color(color ?? theme().muted) : image(p.icon).w(size).h(size).flex_none();
}

// ---------------------------------------------------------------- statuses
// One vocabulary for marks. Agent words pass through; run/step words are mapped.
const STATUS_MAP = {
  working: "working", running: "working", queued: "working", busy: "working", starting: "working",
  blocked: "blocked", error: "failed", failed: "failed", lost: "failed",
  done: "done", complete: "ok", completed: "ok", success: "ok", ok: "ok",
  idle: "idle", stopped: "stopped", cancelled: "stopped", canceled: "stopped",
};
export function normStatus(s) { return s == null ? null : STATUS_MAP[s] ?? "idle"; }
export const RANK = { blocked: 5, failed: 4, done: 3, working: 2, ok: 1, idle: 1, stopped: 0 };
export function worst(list) { return list.reduce((m, s) => ((RANK[normStatus(s)] ?? -1) > (RANK[normStatus(m)] ?? -1) ? s : m), null); }

// The status for attention (sections, counts, badges, pills): the agent's or pane's own status, idle while its
// current report is dismissed. tmap: terminalsByAddress(); dis: getDismissed(). The pane header, Properties and
// Outline keep reading a.status / p.status.
// Effective status before dismissal: raises an idle/done/ok terminal to "working"/"blocked" when a live record says so.
export function effectiveStatus(raw, addr, tmap = null) {
  const term = addr ? tmap?.get(addr) : null;
  const subs = term?.records ? provider.subagents({ parent: addr }) : null;
  return effectiveTermStatus(raw ?? null, term, subs, normStatus);
}
export function agentAttention(a, tmap = null, dis = null) {
  if (!a) return null;
  const term = tmap?.get(a.address);
  return attentionStatus(dis, a.address, effectiveStatus(a.status ?? null, a.address, tmap), term);
}
export function paneAttention(p, tmap = null, dis = null) {
  if (!p) return null;
  if (!p.terminal) return p.status ?? null;
  const term = tmap?.get(p.terminal);
  return attentionStatus(dis, p.terminal, effectiveStatus(p.status ?? null, p.terminal, tmap), term);
}
// A tab's or space's status for attention: Herdr's own, unless one of its panes has a dismissed report or a live
// sub-agent record raising its status; then the worst of its panes' attention statuses.
const hasAttentionOverride = (mine, tmap, dis) => mine.some((p) => {
  if (!p.terminal) return false;
  const term = tmap?.get(p.terminal);
  const eff = effectiveStatus(p.status ?? null, p.terminal, tmap);
  return eff !== (p.status ?? null) || Boolean(dis && isDismissed(dis, p.terminal, eff, term));
});
export function tabAttention(tab, ps, tmap = null, dis = null) {
  if (!tab) return null;
  const mine = (ps ?? []).filter((p) => p.tab === tab.id);
  if (!hasAttentionOverride(mine, tmap, dis)) return tab.status ?? null;
  return worst(mine.map((p) => paneAttention(p, tmap, dis)).filter(Boolean));
}
export function spaceAttention(space, ps, tmap = null, dis = null) {
  if (!space) return null;
  const tabs = space.tabs ?? [];
  const ids = new Set(tabs.map((tb) => tb.id));
  if (!hasAttentionOverride((ps ?? []).filter((p) => ids.has(p.tab)), tmap, dis)) return space.status ?? null;
  return worst(tabs.map((tb) => tabAttention(tb, ps, tmap, dis)).filter(Boolean));
}

// The status mark (12px box): working = spinning ring, blocked = solid dot that pulses,
// done = solid dot, idle = hollow ring, ok = check, failed = x-circle, stopped = dim ring, null = empty box.
export function statusMark(s, size = S.iconXs) {
  const t = theme();
  const k = normStatus(s);
  const box = (el) => h_flex().size(size).flex_none().items_center().justify_center().child(el);
  const dot = Math.max(5, Math.round(size * 0.55));
  if (k === "working") return svg(iconPath("spinner")).size(size).flex_none().text_color(t.working).spin(900);
  if (k === "blocked") return box(div().size(dot).rounded_full().bg(t.blocked).loop("opacity", { from: 0.45, to: 1, period: 1100 }));
  if (k === "done") return box(div().size(dot).rounded_full().bg(t.done));
  if (k === "idle") return box(div().size(dot).rounded_full().border(1.5).border_color(t.idle));
  if (k === "ok") return icon("check", size, t.ansi2);
  if (k === "failed") return icon("circle-x", size, t.blocked);
  if (k === "stopped") return box(div().size(dot).rounded_full().border(1.5).border_color(t.dim));
  return div().size(size).flex_none();
}
// "Needs you" pill for blocked agents where there is room (rows >= 220px wide).
export function needsYou() {
  const t = theme();
  return h_flex().flex_none().px(6).h(18).rounded(5).bg(alpha(t.blocked, 0.15)).text_size(10.5).font_semibold().text_color(t.blocked).items_center().child("Needs you");
}

// ---------------------------------------------------------------- small parts
// Stops the press so a window_drag strip does not start dragging the window.
// Supports both stop(event, cx) and stop(callback).
export const stop = (fnOrE, maybeCx) => {
  if (typeof fnOrE === "function") {
    return (e, cx) => {
      (cx || e)?.stop_propagation?.();
      fnOrE(e, cx);
    };
  }
  (maybeCx || fnOrE)?.stop_propagation?.();
};

// Square icon button. opts: { id, icon, tip, size, iconSize, active, disabled, color, onClick, onRight }
export function iconButton(o) {
  const t = theme();
  const size = o.size ?? S.btn;
  const fg = o.disabled ? alpha(t.dim, 0.6) : o.active ? t.foreground : o.color ?? t.muted;
  let el = h_flex().id(o.id).size(size).flex_none().items_center().justify_center().rounded(S.radius)
    .text_color(fg)
    .when(Boolean(o.active), (e) => e.bg(t.selected))
    .on_mouse_down("left", stop)
    .child(icon(o.icon, o.iconSize ?? S.icon));
  if (!o.disabled) el = el.cursor_pointer().hover((s) => s.bg(t.hover).text_color(t.foreground));
  if (o.tip) el = el.tooltip(o.tip);
  if (o.onClick && !o.disabled) el = el.on_click((e, cx) => { cx.stop_propagation(); o.onClick(e, cx); });
  if (o.onRight) el = el.on_mouse_down("right", (e, cx) => { cx.stop_propagation(); o.onRight(e, cx); });
  return el;
}

// An icon tab of a strip (Obsidian's sidebar tab header). opts: { id, icon, title, active, badge, onClick, onRight }
export function stripTab(o) {
  const t = theme();
  return h_flex().id(o.id).relative().size(S.tab).flex_none().items_center().justify_center().rounded(S.radius)
    .cursor_pointer().text_color(o.active ? t.foreground : t.dim)
    .when(Boolean(o.active), (e) => e.bg(t.selected))
    .when(!o.active, (e) => e.hover((s) => s.bg(t.hover).text_color(t.muted)))
    .tooltip(o.title)
    .on_mouse_down("left", stop)
    .on_click((e, cx) => { cx.stop_propagation(); o.onClick?.(e, cx); })
    .when(Boolean(o.onRight), (e) => e.on_mouse_down("right", (ev, cx) => { cx.stop_propagation(); o.onRight(ev, cx); }))
    .child(icon(o.icon, S.icon))
    .when(o.badge != null && o.badge !== 0 && o.badge !== "", (e) => e.child(
      div().absolute().top(1).right(0).min_w(13).h(13).px(3).rounded_full().bg(o.badgeColor ?? t.accent)
        .text_size(8.5).font_bold().text_color(t.accent_foreground).flex().items_center().justify_center()
        .child(typeof o.badge === "number" && o.badge > 99 ? "99+" : String(o.badge))));
}

// Count / label chip. tone: a theme color name or hex (default: dim on raised).
export function badge(text, tone) {
  const t = theme();
  const c = tone ? (t[tone] ?? tone) : null;
  return h_flex().flex_none().h(16).px(5).rounded(8).items_center()
    .bg(c ? alpha(c, 0.16) : t.raised).text_size(10.5).font_medium().text_color(c ?? t.muted)
    .child(String(text));
}

// Keyboard chord chips: kbd("ctrl-shift-p") -> [Ctrl][Shift][P].
export function kbd(chord, opts = {}) {
  const t = theme();
  return h_flex().flex_none().gap(3).items_center().children(chordParts(chord).map((p) =>
    h_flex().h(18).min_w(18).px(5).rounded(4).justify_center().items_center()
      .border_1().border_color(t.input).bg(opts.active ? t.selected : t.raised)
      .text_size(10.5).font_medium().text_color(t.muted).child(p)));
}

// Section header inside a panel: chevron (when foldable), TITLE, count, flexible gap, right-side content.
// opts: { id, title, count, open (undefined = not foldable), onToggle, right: [elements], color }
export function sectionHeader(o) {
  const t = theme();
  return h_flex().id(o.id).h(S.header).flex_none().px(S.pad).gap(6).items_center()
    .text_size(S.textXs).font_semibold().text_color(o.color ?? t.dim)
    .when(o.open !== undefined, (e) => e.cursor_pointer().hover((s) => s.text_color(t.muted))
      .on_click((ev, cx) => o.onToggle?.(ev, cx))
      .child(icon(o.open ? "chevron-down" : "chevron-right", S.iconXs)))
    .child(div().truncate().child(o.title))
    .when(o.count != null, (e) => e.child(div().text_color(t.dim).font_normal().child(String(o.count))))
    .child(div().flex_1())
    .children(o.right ?? []);
}

// A tree/list row, Obsidian file-explorer style.
// opts: { id, depth, selected, cursor, chevron: undefined|true(open)|false(closed), onToggle,
//         lead: element (icon/avatar), label, labelColor, bold, after: [elements next to the label],
//         right: [elements at the right], onClick, onDouble, onRight, height, dim, guides: true }
// Indent guides: one 1px line per ancestor level, at x = 8 + level*indent + 7 (under its chevron).
export function treeRow(o) {
  const t = theme();
  const depth = o.depth ?? 0;
  const h = o.height ?? S.row;
  const pl = S.pad + depth * S.indent;
  let el = h_flex().id(o.id).relative().h(h).flex_none().pl(pl).pr(6).gap(5).items_center().rounded(S.radius)
    .text_size(S.text).cursor_pointer()
    .when(Boolean(o.selected), (e) => e.bg(t.selected))
    .when(!o.selected, (e) => e.hover((s) => s.bg(t.hover)))
    .when(Boolean(o.cursor) && !o.selected, (e) => e.bg(t.hover))
    .when(Boolean(o.cursor), (e) => e.border_1().border_color(alpha(t.accent, 0.55)));
  if (o.guides !== false && depth > 0) {
    for (let d = 0; d < depth; d++) el = el.child(div().absolute().top(0).bottom(0).left(S.pad + d * S.indent + 7).w(1).bg(t.border));
  }
  if (o.chevron === undefined) el = el.child(div().w(S.iconXs).flex_none());
  else el = el.child(h_flex().id(`${o.id}-fold`).size(S.iconXs + 4).ml(-2).flex_none().items_center().justify_center().rounded(3)
    .text_color(t.dim).hover((s) => s.text_color(t.foreground).bg(t.hover))
    .on_mouse_down("left", stop)
    .on_click((e, cx) => { cx.stop_propagation(); o.onToggle?.(e, cx); })
    .child(icon(o.chevron ? "chevron-down" : "chevron-right", S.iconXs)));
  if (o.lead) el = el.child(o.lead);
  el = el.child(div().min_w(0).flex_shrink(1).truncate().text_color(o.labelColor ?? (o.dim ? t.muted : t.foreground))
    .when(Boolean(o.bold), (e) => e.font_medium()).child(o.label ?? ""));
  for (const a of o.after ?? []) if (a) el = el.child(a);
  el = el.child(div().flex_1().min_w(4));
  for (const r of o.right ?? []) if (r) el = el.child(r);
  if (o.onClick || o.onDouble) el = el.on_mouse_down("left", (e, cx) => { if (e.click_count === 2 && o.onDouble) o.onDouble(e, cx); });
  if (o.onClick) el = el.on_click((e, cx) => o.onClick(e, cx));
  if (o.onRight) el = el.on_mouse_down("right", (e, cx) => { cx.stop_propagation(); o.onRight(e, cx); });
  return el;
}

// Space avatar (18px rounded square, first letter) in the space's stored color.
export function avatar(space, size = 16) {
  const t = theme();
  const color = (shared("space.colors") ?? {})[space?.id] ?? "ansi6";
  const fill = color.startsWith("#") ? color : (MARK[color] ?? t[color] ?? t.accent);
  return h_flex().size(size).flex_none().rounded(4).bg(fill).items_center().justify_center()
    .text_size(Math.round(size * 0.6)).font_bold().text_color("#ffffff")
    .child(([...(space?.name ?? "?")][0] ?? "?").toUpperCase());
}

// Empty state, centered in its panel. opts: { icon, title, body, action: { id, label, onClick } }
export function emptyState(o) {
  const t = theme();
  return v_flex().flex_1().w_full().min_h(120).p(20).gap(8).items_center().justify_center()
    .when(Boolean(o.icon), (e) => e.child(icon(o.icon, 28, t.dim)))
    .child(div().text_size(S.text).font_medium().text_color(t.muted).text_center().child(o.title ?? ""))
    .when(Boolean(o.body), (e) => e.child(div().max_w(260).text_size(S.textSm).text_color(t.dim).text_center().child(o.body)))
    .when(Boolean(o.action), (e) => e.child(h_flex().id(o.action.id).mt(4).h(26).px(10).rounded(S.radius).items_center()
      .border_1().border_color(t.input).text_size(S.textSm).text_color(t.foreground).cursor_pointer()
      .hover((s) => s.bg(t.hover)).on_click((ev, cx) => o.action.onClick(ev, cx)).child(o.action.label)));
}

// A one-line filter input frame around an `Input.new(state)` element (the mod owns the InputState).
export function inputFrame(id, inputEl, opts = {}) {
  const t = theme();
  return h_flex().id(id).h(opts.height ?? 28).mx(opts.mx ?? S.pad).px(8).gap(6).flex_none().items_center().rounded(S.radiusLg)
    .bg(t.background).border_1().border_color(opts.focused ? alpha(t.accent, 0.8) : t.input)
    .child(icon(opts.icon ?? "search", S.iconSm, t.dim))
    .child(div().flex_1().min_w(0).child(inputEl))
    .children(opts.right ?? []);
}

// ---------------------------------------------------------------- menus (ob-menu)
// openMenu(items, opts): a popup context menu drawn by the ob-menu mod, at the pointer.
// item: { label, icon?, kbd?, command?: "<app command>" | "<mod>.<cmd>[:payload]", args?: {},
//         copy?: "text to clipboard", overlay?: OverlaySpec, danger?, disabled?, checked?, separator?: true, hint? }
// The first matching action runs: copy, then overlay, then command. The menu closes itself.
export function openMenu(items, opts = {}) {
  const rows = items.filter(Boolean);
  const h = rows.reduce((n, it) => n + (it.separator ? 9 : 30), 10) + (opts.title ? 26 : 0);
  return openOverlay({
    mod: "ob-menu", kind: "popup", width: opts.width ?? 230, height: Math.min(h, 560),
    ...(opts.at ? { at: opts.at } : {}),
    props: { items: rows, title: opts.title ?? null },
  });
}

// Copy text with a toast-free confirmation left to the caller. cx: any handler/task cx.
export function copyText(cx, text) { cx.write_to_clipboard(String(text ?? "")); }

// ---------------------------------------------------------------- text and numbers
export function ago(ms, now = Date.now()) {
  if (!ms) return "";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 45) return "now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.round(h / 24);
  return d < 30 ? `${d}d` : `${Math.round(d / 30)}mo`;
}
export function dur(ms) {
  if (ms == null || ms < 0) return "";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}
export function fmtTokens(n) {
  if (n == null) return "";
  if (n < 1000) return String(n);
  if (n < 1e6) return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k`;
  return `${(n / 1e6).toFixed(1)}M`;
}
export function fmtCost(usd) {
  if (usd == null) return "";
  return usd < 0.01 ? `$${usd.toFixed(3)}` : `$${usd.toFixed(2)}`;
}
export function tilde(path) {
  if (!path) return "";
  const h = home();
  return path === h ? "~" : path.startsWith(h + "/") ? "~" + path.slice(h.length) : path;
}
export const base = (p) => String(p ?? "").replace(/\/+$/, "").split("/").pop();

// Text with matched letters highlighted (accent, semibold). Returns an h_flex of spans.
export function highlight(text, hits, color) {
  const t = theme();
  const set = new Set(hits ?? []);
  const parts = [];
  let cur = "", on = false;
  [...String(text ?? "")].forEach((ch, i) => {
    const h = set.has(i);
    if (h !== on && cur) { parts.push([cur, on]); cur = ""; }
    on = h; cur += ch;
  });
  if (cur) parts.push([cur, on]);
  return h_flex().min_w(0).overflow_hidden().children(parts.map(([s, h]) =>
    div().flex_none().whitespace_nowrap().text_color(h ? t.accent : color ?? t.foreground).when(h, (e) => e.font_semibold()).child(s)));
}

// ---------------------------------------------------------------- layout tree
export function findNode(node, id) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const c of node.children ?? []) { const f = findNode(c, id); if (f) return f; }
  return null;
}
export function findParent(node, id, parent = null) {
  if (!node) return null;
  if (node.id === id) return parent;
  for (const c of node.children ?? []) { const f = findParent(c, id, node); if (f) return f; }
  return null;
}
// The stack whose children include `childId`, or null.
export function stackOf(root, childId) {
  const p = findParent(root, childId);
  return p?.type === "stack" ? p : null;
}
// Is node `id` shown: it and every ancestor not hidden, and every stack ancestor has it active.
export function isShown(root, id) {
  const path = [];
  const walk = (n) => { if (!n) return false; path.push(n); if (n.id === id) return true; for (const c of n.children ?? []) if (walk(c)) return true; path.pop(); return false; };
  if (!walk(root)) return false;
  for (let i = 0; i < path.length; i++) {
    const n = path[i];
    if (n.hidden) return false;
    if (n.type === "stack" && path[i + 1] && (n.active ?? n.children?.[0]?.id) !== path[i + 1].id) return false;
  }
  return true;
}
// The node ids of layouts/vaultr.json. Use these, never string literals.
export const NODE = {
  left: "ob-left", leftTop: "ob-lt", leftTopStrip: "ob-lt-strip", leftTopStack: "ob-lt-stack",
  leftBottomStack: "ob-lb-stack", footer: "ob-footer",
  center: "ob-center", tabbar: "ob-tabbar", main: "ob-main", statusrow: "ob-statusrow", status: "ob-status",
  right: "ob-right", rightTop: "ob-rt", rightTopStrip: "ob-rt-strip", rightTopStack: "ob-rt-stack", rightBottomStack: "ob-rb-stack",
};
// Every sidebar view (a stack child id = its slot): title and icon for ob-strip, the switcher and menus.
// A child the table doesn't know shows its mod name and the "layers" icon.
export const VIEWS = {
  "ob-sessions": { title: "Sessions", icon: "sessions" },
  "ob-search": { title: "Search", icon: "search" },
  "ob-bookmarks": { title: "Bookmarks", icon: "bookmark" },
  "ob-agents": { title: "Agents", icon: "bot" },
  "ob-recent": { title: "Recent", icon: "history" },
  "ob-quotas": { title: "Quotas", icon: "chart" },
  "ob-props": { title: "Properties", icon: "info" },
  "ob-files": { title: "Files", icon: "files" },
  "ob-changes": { title: "Changes", icon: "git-compare" },
  "ob-insights": { title: "Insights", icon: "chart" },
  "ob-notes": { title: "Notes", icon: "file-text" },
  "ob-graph": { title: "Graph", icon: "graph" },
  "ob-outline": { title: "Outline", icon: "list" },
};
export async function hasMod(name) {
  try {
    const dir = `${appHome()}/mods/${name}`;
    return (await readTextFile(`${dir}/mod.json`)) !== null || (await readTextFile(`${dir}/main.js`)) !== null;
  } catch {
    return false;
  }
}
export function viewInfo(node) {
  const v = VIEWS[node?.id];
  if (v) return v;
  const m = node?.content?.mod ?? node?.id ?? "view";
  return { title: m.charAt(0).toUpperCase() + m.slice(1), icon: "layers" };
}
// Opening a sidebar view by its child id goes through the always-shown router (ob-tabs):
export function openView(childId, intent) { run(`ob-tabs.open:${childId}${intent ? "@" + intent : ""}`); }

// Focus requests: the router (ob-tabs.open:<child>[@<intent>]) sets shared "ob.focus" =
// { child, intent, at }; the target calls this at the top of render(cx) with its own slot
// (props().slot) and its FocusHandle; `then(cx, intent)` runs after focusing (e.g. intent "reveal").
// Verified: setShared re-renders every mod, and cx.timer.after(0) from render can call handle.focus().
export function takeFocus(view, cx, slot, handle, then) {
  const f = shared("ob.focus");
  if (!f || f.child !== slot || f.at === view.__obFocusAt) return;
  view.__obFocusAt = f.at;
  if (Date.now() - f.at > 4000) return;
  cx.timer.after(0, (cx) => { handle?.focus(); then?.(cx, f.intent ?? null); cx.notify(); });
}

// ---------------------------------------------------------------- keys
const isMac = () => { const p = appWindow()?.platform; return p ? p === "macos" : String(home() ?? "").startsWith("/Users/"); };
// "ctrl-shift-p" -> ["Ctrl", "Shift", "P"]; "ctrl--" -> ["Ctrl", "-"]; mac symbols on macOS.
export function chordParts(k) {
  if (!k) return [];
  const mac = isMac();
  const raw = k.endsWith("--") ? [...k.slice(0, -2).split("-"), "-"] : k.split("-");
  const NAMES = mac
    ? { cmd: "⌘", ctrl: "⌃", shift: "⇧", alt: "⌥", option: "⌥", secondary: "⌘" }
    : { cmd: "Super", ctrl: "Ctrl", shift: "Shift", alt: "Alt", option: "Alt", secondary: "Ctrl" };
  const KEYS = { left: "←", right: "→", up: "↑", down: "↓", enter: "Enter", escape: "Esc", space: "Space", backspace: "⌫", tab: "Tab", pageup: "PgUp", pagedown: "PgDn", "\\": "\\" };
  return raw.map((p) => NAMES[p.toLowerCase()] ?? KEYS[p.toLowerCase()] ?? (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)));
}
export function chordLabel(k) { return chordParts(k).join(isMac() ? "" : "+"); }
// The chord that runs `action` in this layout: layout:vaultr first, then global (terminal keys
// only when inTerminal). `action` is the keys.json string ("app.palette", "ob-tabs.open:ob-search").
// An action may hold one chord per platform ("ctrl-b" and "cmd-b"), and keys() lists a section's
// chords by name ("cmd-b" first), so within a section the chord for this keyboard wins: one with
// ⌘ on macOS, one without ⌘/Super elsewhere.
export function bindingFor(action, inTerminal = false) {
  const all = keys();
  const mac = isMac();
  const order = [...(inTerminal ? ["terminal"] : []), `layout:${LAYOUT}`, "global"];
  for (const sec of order) {
    const mine = all.filter((b) => b.section === sec && b.action === action);
    const k = mine.find((b) => /(^|-)(cmd|super|win)-/.test(b.keys) === mac) ?? mine[0];
    if (k) return k.keys;
  }
  return null;
}

// ---------------------------------------------------------------- machines, spaces, agents
// Addresses: "t7" on this machine, "<machine>/t7" on another. Ids of remote spaces/tabs/panes have the same prefix.
export const machineOf = (addr) => (String(addr ?? "").includes("/") ? String(addr).split("/")[0] : null);
export const localId = (addr) => String(addr ?? "").split("/").pop();
export const addrOn = (machine, id) => (machine ? `${machine}/${id}` : id);
export const machineLabel = (m) => m ?? "This computer";
// Parent terminal address of `t` (ignoring self-loops).
export function parentAddrOf(t) {
  return t?.parent && t.parent !== t.address ? t.parent : null;
}
export function isChildTerminalOf(t, parentAddr) {
  if (!t || t.state !== "live" || !parentAddr || t.address === parentAddr) return false;
  return parentAddrOf(t) === parentAddr;
}
// Where a space is now: its first terminal's live folder, else where it was made. ps = panes() read once.
export function place(space, ps) {
  const tabs = new Set((space?.tabs ?? []).map((c) => c.id));
  return ps.find((p) => tabs.has(p.tab) && p.cwd)?.cwd || space?.folder || "";
}
// A pane's name: an agent by its session title or program name, a shell by its clean title or folder, a mod by its view title.
export function paneName(p) {
  if (!p) return "";
  if (p.mod) return VIEWS[p.mod]?.title || cleanTitle(p.title) || p.mod;
  const sess = p.terminal ? sessionTitleOf(p.terminal) : null;
  if (sess) return cleanTitle(sess);
  if (p.program?.agent) return p.program.name;
  const t = cleanTitle(p.title);
  if (p.program?.shell) return t || (p.cwd ? base(p.cwd) : p.program.name);
  return p.program?.name || t || "terminal";
}
// A tab's display name: its name if named, else "<n> · <lead pane name>".
export function tabLabel(tab, ps) {
  if (!tab) return "";
  if (tab.named) return tab.name;
  const mine = ps.filter((p) => p.tab === tab.id);
  const lead = mine.find((p) => p.program?.agent) ?? mine.find((p) => p.focused) ?? mine[0];
  return lead ? paneName(lead) : tab.name;
}
// An agent's session title: the feed's name for its session, else none. The
// agent's terminal title is left out: it is a task line that changes ("bash in src"), not the session.
export function sessionTitleOf(address) {
  const named = provider.session(address)?.title;
  return typeof named === "string" && named.trim() ? named.trim() : null;
}
// A pane's label (kit/names.js paneLabel): an agent by its session title, a shell by its folder, a mod by its panel's
// name. tabName: the tab's own name, so the pane does not repeat it.
export function paneLabelOf(p, tabName = "") {
  return paneLabel(p, {
    sessionTitle: p?.terminal ? sessionTitleOf(p.terminal) : null, folder: p?.cwd, home: home(),
    panelName: p?.mod ? VIEWS[p.mod]?.title ?? null : null, tabName,
  });
}
// The context the user is in: { space, tab, pane, terminal, machine } (objects, may be null).
export function current() {
  const f = focused();
  const sp = spaces();
  const space = sp.find((s) => s.id === f?.space) ?? sp.find((s) => s.active) ?? null;
  const tab = space?.tabs.find((x) => x.id === f?.tab) ?? space?.tabs.find((x) => x.active) ?? null;
  const pane = f?.pane ? panes().find((p) => p.pane === f.pane) ?? null : null;
  return { space, tab, pane, terminal: f?.terminal ?? null, machine: space?.machine ?? null, cwd: f?.cwd ?? pane?.cwd ?? null };
}
// Go to a terminal/pane/tab/space (and record nothing: ob-tabs records history from focus changes).
export function reveal(target) {
  if (target.terminal) { run("agent.focus", { terminal: target.terminal }); return; }
  if (target.space) run("space.select", { id: target.space });
  if (target.tab) run("tab.select", { id: target.tab });
  if (target.pane) run("pane.focus", { pane: target.pane });
}

// ---------------------------------------------------------------- bookmarks (shared "ob.bookmarks")
// item: { kind: "space"|"tab"|"terminal"|"run", id, label, machine, at }. id: space/tab id, address, or run id.
export function bookmarks() { return shared("ob.bookmarks") ?? []; }
export function isBookmarked(kind, id) { return bookmarks().some((b) => b.kind === kind && b.id === id); }
export function toggleBookmark(item) {
  const list = bookmarks();
  const has = list.some((b) => b.kind === item.kind && b.id === item.id);
  setShared("ob.bookmarks", has ? list.filter((b) => !(b.kind === item.kind && b.id === item.id)) : [...list, { ...item, at: Date.now() }]);
  return !has;
}

// ---------------------------------------------------------------- sub-agents (shared "ob.subagents")
// Written only by mods/ob-feed/main.js. Readers use `provider` or these helpers, never raw buckets.
// feed(): { v: 2, at, providers, machines: { [name|"local"]: { ok, at, error, ms } }, runs, subagents, terms, touches, scriptError } or null.
export function feed() {
  const f = shared("ob.subagents");
  return f && f.v === 2 ? f : null;
}
export const provider = makeProvider({ feed, exec, readTextFile, appHome });
// Live sub-agent ids per parent address, from herdr itself (no polling): terminals()[].records.
export function liveRecords() {
  const out = new Map();
  for (const t of terminals()) {
    const r = t.records;
    if (r && typeof r === "object" && Object.keys(r).length) out.set(t.address, r);
  }
  return out;
}
// Everything known about sub-agents of one parent terminal address.
// -> { runs: Run[], agents: SubAgent[], live: number, total: number, worst: status|null }
export function subagentsOf(address) {
  const subs = provider.subagents({ parent: address });
  const runs = subs.filter((x) => x.kind === "run");
  const agents = subs.filter((x) => x.kind === "agent").map((c) => ({ ...c }));
  const term = terminalsByAddress().get(address);
  const termLive = !term?.state || term.state === "live";
  const recs = term?.records && typeof term.records === "object" ? term.records : {};
  for (const [id, r] of Object.entries(recs)) {
    if (/^subagents\/[0-9a-f]{12}(\.|$)/i.test(id)) continue;
    const live = isRecordLive(address, id, r, subs, normStatus, termLive);
    const c = agents.find((x) => x.id === id);
    if (c) {
      if (!c.ended) { c.live = Boolean(c.live) || live; c.state = r?.state; }
    } else if (live || (termLive && r?.state)) {
      agents.push({ kind: "agent", key: `${address}#${id}`, machine: machineOf(address), parent: address, id, type: r.app, desc: r.title, live, state: r.state });
    }
  }
  const live = runs.filter((r) => r.live).length + agents.filter((c) => c.live).length;
  return { runs, agents, live, total: runs.length + agents.length, worst: worst([...runs.map((r) => r.state), ...agents.map((c) => (c.live ? "working" : "ok"))]) };
}
// Counts for badges: { live, total, byParent: Map(address -> { live, total }) }.
export function subagentCounts() {
  const subs = provider.subagents();
  const tmap = terminalsByAddress();
  const byParent = new Map();
  const bump = (p, live) => { if (!p) return; const c = byParent.get(p) ?? { live: 0, total: 0 }; c.total++; if (live) c.live++; byParent.set(p, c); };
  const seen = new Set();
  for (const x of subs) {
    if (x.kind === "agent" && x.id) seen.add(`${x.parent}#${x.id}`);
    const term = x.parent ? tmap.get(x.parent) : null;
    const termLive = !term?.state || term.state === "live";
    const rec = x.kind === "agent" && x.id ? term?.records?.[x.id] : null;
    const rLive = rec ? isRecordLive(x.parent, x.id, rec, subs, normStatus, termLive) : false;
    bump(x.parent, Boolean(x.live) || (!x.ended && rLive));
  }
  for (const [addr, recs] of liveRecords()) {
    const term = tmap.get(addr);
    const termLive = !term?.state || term.state === "live";
    for (const [id, r] of Object.entries(recs)) {
      if (/^subagents\/[0-9a-f]{12}(\.|$)/i.test(id)) continue;
      if (!seen.has(`${addr}#${id}`)) {
        const live = isRecordLive(addr, id, r, subs, normStatus, termLive);
        if (live || (termLive && r?.state)) bump(addr, live);
      }
    }
  }
  let live = 0, total = 0;
  for (const c of byParent.values()) { live += c.live; total += c.total; }
  return { live, total, byParent };
}
