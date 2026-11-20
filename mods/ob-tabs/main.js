// ob-tabs: Obsidian's tab bar for the center column, and the ROUTER of the obsidian layout
// (always shown, so global actions reach views that may be hidden).
//
// Bar (40 px, chrome, bottom hairline; empty space drags the window):
//   [open left sidebar, only while it is hidden] [tabs] [+] [drag space] [tab list] [right sidebar]
//   [window buttons, only while the right sidebar is hidden and window buttons are on]
// Tabs are 32 px tall on the bottom edge, rounded on top, clamp(available / n, 90, 200) wide; the
// active one has the pane color. Click selects, double-click renames, middle-click closes, drag
// reorders, right-click opens the tab menu, the wheel pages through tabs that don't fit.
//
// Commands (ob-tabs.<cmd>):
//   router (5.3): open:<child>[@intent]  toggle:<child>[@intent]  back  forward  last
//                 switcher[:go|move|views|commands]  copy-path  copy-address  daily  bookmark[:<tabId>]
//                 tab-list  new  settings[:<tab>] (ob-settings, on that tab if given)
//   tab bar:      menu:<tabId>  move-to:<tabId>  scroll:<-n|+n>
//
// History (shared "ob.history" = { entries: [{space, tab, pane, terminal, at}], index }): every
// render compares focused() with the entry at `index` and pushes a new entry when it changed,
// unless the change comes from back/forward.

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import {
  spaces, panes, run, layout, nextCommand, setShared, shared as _shared, focused, settings, openOverlay, notify,
  readTextFile, writeTextFile, exec, home, appHome, window as appWindow,
} from "herdr";
import { vaultFor } from "./vault_rules.js";
import { zenPlan } from "./zen.js";
import { isSettingsOpen } from "./settings_open.js";
import { detachItem } from "./detach.js";
import {
  S, NODE, tc, alpha, icon, iconButton, statusMark, tabLabel, findNode, stackOf, isShown, programIcon,
  openMenu, copyText, ago, current, place, toggleBookmark, isBookmarked, chordLabel, bindingFor, stop,
  normHidden, isTabHidden, isSpaceHidden, patchHidden, updateHidden, lightsLeftPad,
} from "./kit.js";

const shared = (k) => (k ? _shared(k) : { "ob.zen": _shared("ob.zen") });
const N = NODE;

const HISTORY_MAX = 50;
const TAB_MIN = 90;
const TAB_MAX = 200;
const NAV_GRACE = 2500; // ms a back/forward jump may take to land before recording resumes

// Which sidebar column holds a view (its stack's side).
const SIDE = (root, child) => (findNode(findNode(root, NODE.left), child) ? NODE.left : NODE.right);
// The node to show so a stack's group is visible (top stacks live inside their group column).
const GROUP = (stackId) => (stackId === NODE.leftTopStack ? NODE.leftTop : stackId === NODE.rightTopStack ? NODE.rightTop : stackId);

// Window buttons: ob.settings.windowButtons "always" | "never" | "auto" (default: what Herdr wants).
function windowButtonsOn() {
  const mode = shared("ob.settings")?.windowButtons ?? "auto";
  return mode === "always" || (mode === "auto" && Boolean(appWindow()?.buttons));
}

// "verb:arg@intent" -> [verb, arg, intent]; the intent is everything after the FIRST "@"
// (a query intent may itself contain "@").
function parseCmd(c) {
  const s = String(c ?? "");
  const i = s.indexOf(":");
  const verb = i < 0 ? s : s.slice(0, i);
  const rest = i < 0 ? "" : s.slice(i + 1);
  const j = rest.indexOf("@");
  return j < 0 ? [verb, rest, null] : [verb, rest.slice(0, j), rest.slice(j + 1) || null];
}

const sameSpot = (a, b) => Boolean(a && b) && a.space === b.space && a.tab === b.tab && a.pane === b.pane;
const tip = (title, action) => { const k = action ? bindingFor(action) : null; return k ? `${title} (${chordLabel(k)})` : title; };

export default class Tabs extends View {
  init(_p, cx) {
    this.w = 0;
    this.first = 0;          // first tab shown when they don't all fit
    this.lastActive = null;  // the active tab id the window was last fitted to
    this.paged = false;      // the person paged the tabs (wheel, arrows) since the active tab changed
    this.hovered = null;     // tab id under the pointer (close button)
    this.pressed = null;     // tab id pressed (drag to reorder)
    this.over = null;        // tab id the drag is over
    this.nav = null;         // { space, tab, pane, until }: a back/forward jump in flight
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        try { await this.command(c, cx); } catch (e) { console.log(`ob-tabs: ${c} failed: ${e?.message ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
    // Working times on tabs ("3m") are data: refresh them twice a minute while something works.
    cx.timer.every(30000, (cx) => { if (this.anyWorking) cx.notify(); });
  }

  // ------------------------------------------------------------------ history
  history() {
    const h = shared("ob.history");
    return h && Array.isArray(h.entries) ? h : { entries: [], index: -1 };
  }

  writeHistory(h) {
    setShared("ob.history", h);
  }

  // Called from render: record the focused spot (deferred out of render with a 0 ms timer).
  track(cx) {
    const f = focused();
    if (!f?.space || !f?.tab) return;
    const spot = { space: f.space, tab: f.tab, pane: f.pane ?? null, terminal: f.terminal ?? null };
    if (this.nav) {
      // A back/forward jump: the focus changes it causes are not recorded.
      const n = this.nav;
      if (spot.space === n.space && (!n.tab || spot.tab === n.tab) && (!n.pane || spot.pane === n.pane)) {
        this.nav = null;
        // Landed somewhere other than the stored spot (its pane is gone): that entry becomes where we are.
        const h0 = this.history();
        if (!sameSpot(spot, h0.entries[h0.index])) cx.timer.after(0, () => {
          const h1 = this.history();
          if (!h1.entries[h1.index]) return;
          const entries = h1.entries.slice();
          entries[h1.index] = { ...spot, at: Date.now() };
          this.writeHistory({ entries, index: h1.index });
        });
        return;
      }
      if (Date.now() < n.until) return;
      this.nav = null;
    }
    const h = this.history();
    if (sameSpot(spot, h.entries[h.index]) || sameSpot(spot, this.queued)) return;
    this.queued = spot;
    // setShared re-renders every mod: do it after this render, not inside it.
    cx.timer.after(0, () => {
      this.queued = null;
      const h2 = this.history();
      if (sameSpot(spot, h2.entries[h2.index])) return;
      const entries = [...h2.entries.slice(0, h2.index + 1), { ...spot, at: Date.now() }].slice(-HISTORY_MAX);
      this.writeHistory({ entries, index: entries.length - 1 });
    });
  }

  // Back/forward: the nearest entry in that direction whose space still exists.
  go(step) {
    const h = this.history();
    const sp = spaces();
    const ps = panes();
    for (let i = h.index + step; i >= 0 && i < h.entries.length; i += step) {
      const e = h.entries[i];
      const space = sp.find((s) => s.id === e.space);
      if (!space) continue;
      const tab = space.tabs.find((t) => t.id === e.tab);
      const pane = tab && e.pane ? ps.find((p) => p.pane === e.pane) : null;
      // Land on what still exists: the pane, else its tab, else the space.
      this.nav = { space: space.id, tab: tab?.id ?? null, pane: pane?.pane ?? null, until: Date.now() + NAV_GRACE };
      run("space.select", { id: space.id });
      if (tab) run("tab.select", { id: tab.id });
      if (pane) run("pane.focus", { pane: pane.pane });
      this.writeHistory({ ...h, index: i });
      return;
    }
  }

  // ------------------------------------------------------------------ commands
  async command(c, cx) {
    const [verb, arg, intent] = parseCmd(c);
    const root = layout();
    if (verb === "open" || verb === "toggle") return this.open(root, verb, arg, intent);
    if (verb === "back") return this.go(-1);
    if (verb === "forward") return this.go(1);
    if (verb === "last") {
      const h = normHidden(shared("ob.hidden"));
      const tabs = (current().space?.tabs ?? []).filter((t) => !isTabHidden(h, t, current().space));
      if (tabs.length) run("tab.select", { id: tabs[tabs.length - 1].id });
      return;
    }
    if (verb === "hide-tab") {
      const sp = spaces().find((s) => (s.tabs ?? []).some((x) => x.id === arg));
      const h = normHidden(shared("ob.hidden"));
      const visible = (sp?.tabs ?? []).filter((x) => !isTabHidden(h, x, sp));
      if (sp && visible.length <= 1) {
        updateHidden((cur) => patchHidden(cur, "space", sp.id, true));
        const f = focused();
        if (f?.space === sp.id) {
          const nextH = normHidden(shared("ob.hidden"));
          const nextSpace = spaces().find((s) => s.id !== sp.id && !isSpaceHidden(nextH, s));
          if (nextSpace) run("space.select", { id: nextSpace.id });
        }
      } else {
        updateHidden((cur) => patchHidden(cur, "tab", arg, true));
        run("tab.settle", { id: arg });
      }
      return;
    }
    if (verb === "show-tab") {
      updateHidden((cur) => patchHidden(cur, "tab", arg, false));
      run("tab.unsettle", { id: arg });
      return;
    }
    if (verb === "switcher") return this.switcher(arg || "go");
    if (verb === "zen") return this.zen(arg);
    if (verb === "copy-path") {
      const c0 = current();
      const path = c0.cwd || (c0.space ? place(c0.space, panes()) : "");
      if (!path) return notify({ title: "No path to copy", level: "warning", timeout: 1500 });
      copyText(cx, path);
      return notify({ title: "Copied path", body: path, level: "info", timeout: 1500 });
    }
    if (verb === "copy-address") {
      const addr = focused()?.terminal;
      if (!addr) return notify({ title: "No terminal focused", level: "warning", timeout: 1500 });
      copyText(cx, addr);
      return notify({ title: "Copied address", body: addr, level: "info", timeout: 1500 });
    }
    if (verb === "daily") return this.daily();
    if (verb === "bookmark") return this.bookmark(arg);
    if (verb === "tab-list") return this.tabList();
    if (verb === "new") return openOverlay({ mod: "new-menu", kind: "popup", width: 250, height: 512 });
    if (verb === "settings") return this.settings(arg);
    if (verb === "menu") { const t = this.findTab(arg); if (t) this.tabMenu(t.space, t.tab); return; }
    if (verb === "move-to") {
      const t = this.findTab(arg);
      if (!t) return;
      if (!t.tab.active) run("tab.select", { id: t.tab.id });
      return this.switcher("move");
    }
    if (verb === "scroll") { this.first = Math.max(0, this.first + (Number(arg) || 0)); this.paged = true; return; }
    console.log(`ob-tabs: unknown command "${c}"`);
  }

  // ob-settings opens on the tab named in shared "ob-settings.tab" (it clears that once read). An open
  // dialog is not toggled shut by mod.open: it takes the request as it is, so only a closed one is opened. "Open" is a
  // beat the dialog keeps up (settings_open.js), so one that died open, or an ob-tabs that reloaded, needs no clean-up.
  settings(tab) {
    if (tab) setShared("ob-settings.tab", tab);
    if (isSettingsOpen(shared("ob-settings.open"))) return;
    run("mod.open", { name: "ob-settings" });
  }

  zen(mode) {
    const root = layout();
    const plan = zenPlan({
      prev: shared()?.["ob.zen"], mode, now: Date.now(),
      hidden: { left: findNode(root, N.left)?.hidden, right: findNode(root, N.right)?.hidden, statusrow: findNode(root, N.statusrow)?.hidden },
    });
    const id = { left: N.left, right: N.right, statusrow: N.statusrow };
    setShared("ob.zen", plan.state);
    for (const k of plan.hide) run("layout.hide", { id: id[k] });
    for (const k of plan.show) run("layout.show", { id: id[k] });
    if (plan.tabbar !== null) run("layout.resize", { id: N.tabbar, px: plan.tabbar });
  }

  open(root, verb, child, intent) {
    if (shared()?.["ob.zen"]?.active) {
      run("layout.resize", { id: N.tabbar, px: 40 });
      if (!shared()?.["ob.zen"]?.statusHidden) run("layout.show", { id: N.statusrow });
      setShared("ob.zen", { active: false, at: Date.now() });
    }
    const st = stackOf(root, child);
    if (!st) { console.log(`ob-tabs: no view "${child}" in this layout`); return; }
    if (verb === "toggle" && isShown(root, child)) { run("layout.hide", { id: SIDE(root, child) }); return; }
    run("layout.show", { id: SIDE(root, child) });
    const group = findNode(root, GROUP(st.id));
    if (group?.hidden) run("layout.show", { id: group.id });
    run("layout.select", { stack: st.id, child });
    // term:<address> means "inspect that terminal": the right sidebar views read ob.inspect.
    if (intent && intent.startsWith("term:") && intent.length > 5) setShared("ob.inspect", { terminal: intent.slice(5), at: Date.now() });
    setShared("ob.focus", { child, intent, at: Date.now() });
  }

  // The quick switcher, at the top center of the window like Obsidian's.
  // An already-open switcher keeps its state and ignores new props, so the mode is also sent to it as a command.
  switcher(mode) {
    const m = ["go", "move", "views", "commands"].includes(mode) ? mode : "go";
    openOverlay({ mod: "ob-switcher", kind: "popup", at: "top", offset: 48, width: 660, height: 0.72, props: { mode: m } });
    run(`ob-switcher.mode:${m}`);
  }

  findTab(id) {
    for (const space of spaces()) {
      const tab = space.tabs.find((t) => t.id === id);
      if (tab) return { space, tab };
    }
    return null;
  }

  bookmark(tabId) {
    const t = tabId ? this.findTab(tabId) : (() => { const c0 = current(); return c0.tab ? { space: c0.space, tab: c0.tab } : null; })();
    if (!t) return notify({ title: "No tab to bookmark", level: "warning", timeout: 1500 });
    const label = tabLabel(t.tab, panes());
    const added = toggleBookmark({ kind: "tab", id: t.tab.id, label, machine: t.space.machine ?? null });
    notify({ title: added ? "Bookmarked" : "Bookmark removed", body: label, level: "info", timeout: 1500 });
  }

  // The tabs of this space, then the other spaces (Obsidian's tab list chevron).
  tabList() {
    const c0 = current();
    const ps = panes();
    const items = [];
    const tabs = c0.space?.tabs ?? [];
    const h = normHidden(shared("ob.hidden"));
    if (tabs.length) items.push({ header: c0.space.name || "Tabs" });
    for (const tab of tabs) {
      items.push({
        label: tabLabel(tab, ps), icon: "tab", checked: tab.active,
        hint: isTabHidden(h, tab, c0.space) ? "hidden" : tab.status && tab.status !== "idle" ? tab.status : undefined,
        command: "tab.select", args: { id: tab.id },
      });
    }
    const others = spaces().filter((s) => s.id !== c0.space?.id);
    if (others.length) {
      if (items.length) items.push({ separator: true });
      items.push({ header: "Spaces" });
      for (const s of others.slice(0, 12)) {
        const shownTab = s.tabs.find((x) => x.active) ?? s.tabs[0];
        const hint = [shownTab ? tabLabel(shownTab, ps) : null, s.machine].filter(Boolean).join(" · ");
        items.push({ label: s.name || "space", icon: s.machine ? "server" : "monitor", hint: hint || undefined, command: "space.select", args: { id: s.id } });
      }
    }
    if (!items.length) items.push({ label: "No tabs yet", disabled: true });
    openMenu(items, { width: 280 });
  }

  // Right-click menu of one tab.
  tabMenu(space, tab) {
    const ps = panes();
    const all = space.tabs ?? [];
    const h = normHidden(shared("ob.hidden"));
    const visibleTabs = all.filter((t) => !isTabHidden(h, t, space));
    const onlyTab = visibleTabs.length <= 1;
    const isHidden = isTabHidden(h, tab, space);
    const i = all.findIndex((t) => t.id === tab.id);
    const lead = ps.find((p) => p.tab === tab.id && p.focused) ?? ps.find((p) => p.tab === tab.id && p.cwd);
    const path = lead?.cwd || place(space, ps);
    const marked = isBookmarked("tab", tab.id);
    const hideItems = onlyTab
      ? [{ label: "Hide space", icon: "eye-off", command: `ob-sessions.hide-space:${space.id}` }]
      : [
          isHidden
            ? { label: "Show tab", icon: "eye", command: `ob-tabs.show-tab:${tab.id}` }
            : { label: "Hide tab", icon: "eye-off", hint: "hide from tab bar and Sessions", command: `ob-tabs.hide-tab:${tab.id}` },
          { label: "Hide space", icon: "eye-off", command: `ob-sessions.hide-space:${space.id}` },
        ];
    openMenu([
      { label: "Rename…", icon: "rename", command: "tab.rename", args: { id: tab.id }, kbd: bindingFor("tab.rename") ?? undefined },
      { label: marked ? "Remove bookmark" : "Bookmark", icon: marked ? "bookmark" : "bookmark-plus", command: `ob-tabs.bookmark:${tab.id}` },
      path ? { label: "Copy path", icon: "copy", copy: path } : null,
      { separator: true },
      ...hideItems,
      i > 0 ? { label: "Move left", icon: "arrow-left", command: "tab.move", args: { id: tab.id, index: i } } : null,
      i < all.length - 1 ? { label: "Move right", icon: "arrow-right", command: "tab.move", args: { id: tab.id, index: i + 2 } } : null,
      { label: "Move to space…", icon: "move", command: `ob-tabs.move-to:${tab.id}` },
      { separator: true },
      { label: "New tab", icon: "plus", command: "tab.new", args: { space: space.id }, kbd: bindingFor("tab.new") ?? undefined },
      detachItem(ps, tab.id),
      { label: "Close tab", icon: "x", danger: true, command: "tab.close", args: { id: tab.id }, kbd: bindingFor("tab.close") ?? undefined },
    ], { width: 250, title: tabLabel(tab, ps) });
  }

  // ------------------------------------------------------------------ daily note
  async daily() {
    let vault;
    try { vault = await findVault(); }
    catch (e) { return notify({ title: "Can't read obsidian.json", body: String(e?.message ?? e), level: "error", timeout: 5000 }); }
    if (vault.error) return notify({ title: vault.unset ? "No vault set" : "Vault path refused", body: vault.error, level: vault.unset ? "warning" : "error", timeout: 5000 });
    const dn = parseJSON(await readTextFile(`${vault.root}/.obsidian/daily-notes.json`).catch(() => null)) ?? {};
    const trim = (p) => String(p ?? "").replace(/^\/+|\/+$/g, "");
    const folder = trim(vault.own.dailyFolder ?? dn.folder);
    const format = vault.own.dailyFormat ?? (dn.format || "YYYY-MM-DD");
    const template = trim(vault.own.dailyTemplate ?? dn.template);
    const name = formatDate(format);
    const rel = `${folder ? folder + "/" : ""}${name}.md`;
    const abs = `${vault.root}/${rel}`;
    if ((await readTextFile(abs).catch(() => null)) === null) {
      let body = "";
      if (template) {
        const tpl = await readTextFile(`${vault.root}/${template.replace(/\.md$/i, "")}.md`).catch(() => null);
        body = (tpl ?? "")
          .replace(/\{\{date:([^}]+)\}\}/g, (_m, f) => formatDate(f.trim()))
          .replace(/\{\{time:([^}]+)\}\}/g, (_m, f) => formatDate(f.trim()))
          .replace(/\{\{date\}\}/g, name).replace(/\{\{time\}\}/g, formatDate("HH:mm")).replace(/\{\{title\}\}/g, name);
      }
      const dir = abs.slice(0, abs.lastIndexOf("/"));
      await exec("mkdir", ["-p", dir], { timeout: 5000 }).catch(() => null);
      try { await writeTextFile(abs, body, null); } catch (e) { return notify({ title: "Could not create today's note", body: String(e?.message ?? e), level: "error", timeout: 5000 }); }
    }
    const f = focused();
    if (f?.pane) run("pane.split", { direction: "right", pane: f.pane, mod: "obsidian", props: { note: rel } });
    else run("tab.new", { name, mod: "obsidian", props: { note: rel } });
  }

  // ------------------------------------------------------------------ render
  render(cx) {
    const t = tc();
    const root = layout();
    this.track(cx);
    const c0 = current();
    const space = c0.space;
    const ps = panes();
    const leftNode = findNode(root, NODE.left);
    const leftHidden = Boolean(leftNode?.hidden);
    const rightHidden = Boolean(findNode(root, NODE.right)?.hidden);
    const winButtons = rightHidden && windowButtonsOn();
    const w = appWindow();
    const zoom = settings().zoom || 1;
    const leftWidth = leftHidden ? 0 : (leftNode?.size?.px ?? 300);
    const leftPad = lightsLeftPad(8, w, root, zoom, leftWidth);
    const all = space?.tabs ?? [];
    const h = normHidden(shared("ob.hidden"));
    // Hidden tabs live in Sessions; the active one always shows (selecting a hidden tab brings it back).
    const tabs = all.filter((x) => !isTabHidden(h, x, space) || x.active);
    this.anyWorking = tabs.some((x) => x.status === "working");

    // Room for tabs: the bar minus its buttons and a strip of drag space.
    const fixed = leftPad + 6 + (leftHidden ? 30 : 0) + 30 /* + */ + 48 /* drag */ + 30 /* list */ + 30 /* right */ + (winButtons ? 90 : 0);
    const avail = Math.max(TAB_MIN, (this.w || 1200) - fixed);
    const fit = Math.max(1, Math.floor(avail / TAB_MIN));
    const over = tabs.length > fit;
    const navW = over ? 2 * 24 : 0;
    const shownCount = over ? Math.max(1, Math.floor((avail - navW) / TAB_MIN)) : tabs.length;
    const activeIdx = tabs.findIndex((x) => x.active);
    // Keep the active tab inside the shown window when it changes; the wheel may page away from it.
    if (activeIdx >= 0 && this.lastActive !== tabs[activeIdx].id) { this.lastActive = tabs[activeIdx].id; this.paged = false; }
    if (activeIdx >= 0 && !this.paged) {
      if (activeIdx < this.first) this.first = activeIdx;
      else if (activeIdx >= this.first + shownCount) this.first = activeIdx - shownCount + 1;
    }
    this.first = Math.max(0, Math.min(this.first, Math.max(0, tabs.length - shownCount)));
    const start = over ? this.first : 0;
    const shown = tabs.slice(start, start + shownCount);
    const tabW = shown.length ? Math.max(TAB_MIN, Math.min(TAB_MAX, Math.floor((avail - navW) / Math.max(shown.length, 1)))) : 0;
    const hiddenLeft = start;
    const hiddenRight = Math.max(0, tabs.length - (start + shown.length));

    const bottomButton = (el) => h_flex().h(32).flex_none().items_center().child(el);
    const pressedIdx = tabs.findIndex((x) => x.id === this.pressed);

    const tabEl = (tab, k) => {
      const i = start + k;
      const active = tab.active;
      const hovered = this.hovered === tab.id;
      const lead = ps.find((p) => p.tab === tab.id && p.program?.agent) ?? ps.find((p) => p.tab === tab.id && p.focused) ?? ps.find((p) => p.tab === tab.id);
      const label = tabLabel(tab, ps);
      const next = shown[k + 1];
      const sep = !active && !hovered && next && !next.active && this.hovered !== next.id;
      const working = tab.status === "working" && tab.working_since && Date.now() - tab.working_since > 60000;
      const showClose = (active || hovered) && tabW >= 110;
      const dragging = this.pressed === tab.id && this.over && this.over !== tab.id;
      const dropHere = this.pressed && this.over === tab.id && this.pressed !== tab.id;
      return h_flex().id(`tab-${tab.id}`).relative().h(32).w(tabW).flex_none().pl(10).pr(showClose ? 5 : 10).gap(7).items_center()
        .rounded_t(6).text_size(S.textSm).cursor_pointer()
        .when(active, (e) => e.bg(t.background).text_color(t.foreground))
        .when(!active, (e) => e.text_color(t.muted).hover((s) => s.bg(alpha(t.hover, 0.7)).text_color(t.foreground)))
        .when(Boolean(dragging), (e) => e.opacity(0.5))
        .tooltip(label + (tab.zoomed ? " (zoomed)" : ""))
        .on_hover((h, cx) => { const v = h ? tab.id : this.hovered === tab.id ? null : this.hovered; if (v !== this.hovered) { this.hovered = v; cx.notify(); } })
        .on_mouse_down("left", (e, cx) => {
          cx.stop_propagation();
          if (e.click_count === 2) { this.pressed = null; run("tab.rename", { id: tab.id }); return; }
          this.pressed = tab.id; this.over = tab.id;
        })
        .on_mouse_move((_e, cx) => { if (this.pressed && this.over !== tab.id) { this.over = tab.id; cx.notify(); } })
        .on_mouse_up("left", (_e, cx) => {
          const from = this.pressed;
          this.pressed = null; this.over = null;
          if (from && from !== tab.id) {
            const target = space.tabs.findIndex((x) => x.id === tab.id);
            if (target >= 0) run("tab.move", { id: from, index: target + 1 });
          } else run("tab.select", { id: tab.id });
          cx.notify();
        })
        .on_mouse_down("middle", (_e, cx) => { cx.stop_propagation(); run("tab.close", { id: tab.id }); })
        .on_mouse_down("right", (_e, cx) => { cx.stop_propagation(); this.tabMenu(space, tab); })
        .child(lead?.terminal ? programIcon(lead.program, S.iconSm, active ? t.foreground : t.muted) : icon(lead?.mod ? "file-text" : "terminal", S.iconSm, active ? t.foreground : t.muted))
        .child(div().flex_1().min_w(0).truncate().child(label))
        .when(Boolean(tab.zoomed), (e) => e.child(icon("maximize", S.iconXs, t.dim)))
        .when(Boolean(working) && tabW >= 130, (e) => e.child(div().flex_none().text_size(S.textXs).text_color(t.dim).child(ago(tab.working_since))))
        .when(tab.status != null && !(tab.status === "idle" && showClose), (e) => e.child(statusMark(tab.status)))
        .when(showClose, (e) => e.child(h_flex().id(`close-${tab.id}`).size(18).flex_none().items_center().justify_center().rounded(S.radius)
          .text_color(t.dim).hover((s) => s.bg(t.hover).text_color(t.foreground))
          .tooltip(tip("Close tab", "tab.close"))
          .on_mouse_down("left", stop)
          .on_click((_e, cx) => { cx.stop_propagation(); run("tab.close", { id: tab.id }); })
          .child(icon("x", S.iconXs))))
        .when(Boolean(sep), (e) => e.child(div().absolute().right(0).top(9).bottom(9).w(1).bg(t.border)))
        .when(Boolean(dropHere), (e) => e.child(div().absolute().top(4).bottom(0).w(2).bg(t.accent)
          .when(pressedIdx < i, (l) => l.right(0)).when(pressedIdx > i, (l) => l.left(0))));
    };

    return h_flex().id("root").relative().size_full().min_w(0).pl(leftPad).pr(6).gap(2).items_end().bg(t.chrome)
      .on_size_change((s, cx) => { const w0 = s.width / (settings().zoom || 1); if (Math.abs(w0 - this.w) > 1) { this.w = w0; cx.notify(); } })
      .on_mouse_up("left", (_e, cx) => { if (this.pressed) { this.pressed = null; this.over = null; cx.notify(); } })
      .on_hover((h, cx) => { if (!h && (this.hovered || this.pressed)) { this.hovered = null; this.pressed = null; this.over = null; cx.notify(); } })
      .on_scroll_wheel((e, cx) => {
        if (!over) return;
        const d = Math.abs(e.delta.y) >= Math.abs(e.delta.x) ? e.delta.y : e.delta.x;
        if (Math.abs(d) < 1) return;
        this.first = Math.max(0, Math.min(tabs.length - shownCount, this.first + (d > 0 ? -1 : 1)));
        this.paged = true;
        cx.notify();
      })
      // The hairline under the bar; the active tab paints over it so it joins the pane area.
      .child(div().absolute().left(0).right(0).bottom(0).h(1).bg(t.border))
      .when(leftHidden, (e) => e.child(bottomButton(iconButton({ id: "show-left", icon: "panel-left", tip: tip("Open left sidebar", "layout.toggle:ob-left"), onClick: () => run("layout.show", { id: NODE.left }) }))))
      .when(hiddenLeft > 0, (e) => e.child(bottomButton(iconButton({ id: "tabs-prev", icon: "chevron-left", size: 22, iconSize: S.iconXs, tip: `${hiddenLeft} more`, onClick: (_e, cx) => { this.first = Math.max(0, this.first - 1); this.paged = true; cx.notify(); } }))))
      .children(shown.map(tabEl))
      .when(hiddenRight > 0, (e) => e.child(bottomButton(iconButton({ id: "tabs-next", icon: "chevron-right", size: 22, iconSize: S.iconXs, tip: `${hiddenRight} more`, onClick: (_e, cx) => { this.first = Math.min(tabs.length - shownCount, this.first + 1); this.paged = true; cx.notify(); } }))))
      .child(bottomButton(iconButton({ id: "new", icon: "plus", tip: tip("New tab", "tab.new"), onClick: () => openOverlay({ mod: "new-menu", kind: "popup", width: 250, height: 512 }) })).ml(2))
      .child(div().id("drag").flex_1().min_w(8).h_full())
      .child(bottomButton(iconButton({ id: "tab-list", icon: "chevron-down", tip: tip("Tab list", "ob-tabs.tab-list"), onClick: () => this.tabList() })))
      .child(bottomButton(iconButton({ id: "toggle-right", icon: "panel-right", active: !rightHidden, tip: tip(rightHidden ? "Open right sidebar" : "Close right sidebar", "layout.toggle:ob-right"), onClick: () => run("layout.toggle", { id: NODE.right }) })))
      .when(winButtons, (e) => e
        .child(div().w(6).flex_none())
        .child(bottomButton(iconButton({ id: "win-min", icon: "win-min", tip: "Minimize", onClick: () => run("window.minimize") })))
        .child(bottomButton(iconButton({ id: "win-max", icon: w?.maximized ? "win-restore" : "win-max", tip: w?.maximized ? "Restore" : "Maximize", onClick: () => run("window.maximize") })))
        .child(bottomButton(iconButton({ id: "win-close", icon: "x", tip: "Close window", onClick: () => run("window.close") }))));
  }
}

// ------------------------------------------------------------------ vault + dates
function parseJSON(text) { if (text == null) return null; try { return JSON.parse(text); } catch { return null; } }

// The vault the obsidian mod uses: appHome()/obsidian.json {vault}, and nothing else. No fallback to Obsidian's
// own vault list. The rule is ./vault_rules.js (the same as mods/obsidian/config.js).
async function findVault() {
  const text = await readTextFile(`${appHome()}/obsidian.json`).catch(() => null);
  const own = (text == null ? null : JSON.parse(text)) ?? {};
  return { ...vaultFor(own, home()), own };
}

// moment.js tokens Obsidian's daily notes use; [text] is literal. (Same as mods/obsidian/vault.js.)
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const pad = (n, w = 2) => String(n).padStart(w, "0");
const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 >= 11 && n % 100 <= 13) || n % 10 > 3 ? 0 : n % 10]);
function formatDate(format, d = new Date()) {
  const tokens = {
    YYYY: () => d.getFullYear(), YY: () => pad(d.getFullYear() % 100),
    MMMM: () => MONTHS[d.getMonth()], MMM: () => MONTHS[d.getMonth()].slice(0, 3),
    MM: () => pad(d.getMonth() + 1), M: () => d.getMonth() + 1,
    Do: () => ordinal(d.getDate()), DD: () => pad(d.getDate()), D: () => d.getDate(),
    dddd: () => DAYS[d.getDay()], ddd: () => DAYS[d.getDay()].slice(0, 3),
    HH: () => pad(d.getHours()), H: () => d.getHours(), mm: () => pad(d.getMinutes()), ss: () => pad(d.getSeconds()),
  };
  return format.replace(/\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|Do|DD|D|dddd|ddd|HH|H|mm|ss/g, (tk, literal) => literal ?? String(tokens[tk]()));
}
