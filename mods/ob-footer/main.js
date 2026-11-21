// ob-footer: the left sidebar's bottom row, Obsidian's vault switcher (40 px).
// Left: the focused space's machine ("This computer") with a chevron; click opens the machine
// menu: each machine with its connection dot (click: go to its first space) and "New space there",
// then Add machine and Machines settings. Right: feedback, help, and the settings gear (opens ob-settings).
// Connection states come from `hc machine ls --json` (every 15 s) and machines() (live).
// Commands (ob-footer.<cmd>): machines

import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { run, nextCommand, machines, spaces, settings, hc } from "herdr";
import { S, tc, icon, iconButton, current, machineLabel, openMenu, bindingFor, chordLabel } from "./kit.js";

const tip = (title, action) => { const k = action ? bindingFor(action) : null; return k ? `${title} (${chordLabel(k)})` : title; };

export default class Footer extends View {
  init(_p, cx) {
    this.w = 0;
    this.hcMachines = []; // [{ name, state, temporary }] from hc
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { if (c === "machines") this.menu(); } catch (e) { console.log(`ob-footer: ${c} failed: ${e?.message ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
    this.poll(cx);
    cx.timer.every(15000, (cx) => this.poll(cx));
  }

  poll(cx) {
    if (this.polling) return;
    this.polling = true;
    cx.spawn(async (cx) => {
      try {
        const r = await hc(["machine", "ls", "--json"]);
        const list = JSON.parse(r?.stdout || "{}").machines;
        if (Array.isArray(list)) {
          const next = list.filter((m) => m && !m.temporary && m.name).map((m) => ({ name: m.name, state: String(m.state ?? "") }));
          if (JSON.stringify(next) !== JSON.stringify(this.hcMachines)) { this.hcMachines = next; cx.notify(); }
        }
      } catch { /* hc missing or slow: machines() still lists them */ }
      this.polling = false;
    });
  }

  // Every machine: this computer first, then the others by name. state: ok | connecting | away | login
  list() {
    const live = machines();
    const names = new Set([null, ...live.map((m) => m.name ?? null), ...this.hcMachines.map((m) => m.name)]);
    return [...names].sort((a, b) => (a === null ? -1 : b === null ? 1 : a.localeCompare(b))).map((name) => {
      if (name === null) return { name, state: "ok" };
      const layoutState = live.find((m) => m.name === name)?.layout;
      const hcState = this.hcMachines.find((m) => m.name === name)?.state ?? "";
      let state = "ok";
      if (/login|auth|password/i.test(hcState)) state = "login";
      else if (layoutState === "unavailable" || (hcState && !/connected/i.test(hcState))) state = "away";
      else if (layoutState === "loading") state = "connecting";
      return { name, state, hcState };
    });
  }

  menu() {
    const all = spaces();
    const cur = current().machine ?? null;
    const items = [];
    const DOT = { ok: "ansi2", connecting: "working", away: "dim", login: "blocked" };
    const WORD = { ok: "", connecting: "connecting", away: "unavailable", login: "needs login" };
    for (const m of this.list()) {
      const mine = all.filter((s) => (s.machine ?? null) === m.name);
      const n = mine.length;
      const usable = m.state === "ok" || m.state === "connecting";
      items.push({
        label: machineLabel(m.name), dot: DOT[m.state], checked: m.name === cur,
        hint: WORD[m.state] || (n ? `${n} space${n === 1 ? "" : "s"}` : "no spaces"),
        disabled: !n, command: "space.select", args: { id: mine[0]?.id },
      });
      if (usable) items.push({ label: "New space there", icon: "folder-plus", indent: true, command: "space.new", args: { machine: m.name ?? "" } });
      else if (m.state === "login") items.push({ label: `Copy: hc machine login ${m.name}`, icon: "copy", indent: true, copy: `hc machine login ${m.name}` });
    }
    items.push({ separator: true });
    items.push({ label: "Add machine…", icon: "plus", command: "mod.open", args: { name: "machine-add" } });
    items.push({ label: "Machines settings", icon: "settings", command: "app.settings", args: { section: "machines" } });
    openMenu(items, { width: 260, title: "Machines" });
  }

  render() {
    const t = tc();
    const c = current();
    const m = c.machine ?? null;
    const rail = this.w > 0 && this.w < 160;
    const state = m ? this.list().find((x) => x.name === m)?.state : "ok";
    return h_flex().id("root").size_full().min_w(0).px(S.pad).gap(2).items_center().bg(t.chrome).border_t(1).border_color(t.border)
      .on_size_change((s, cx) => { const w0 = s.width / (settings().zoom || 1); if (Math.abs(w0 - this.w) > 1) { this.w = w0; cx.notify(); } })
      .child(h_flex().id("vault").flex_1().min_w(0).h(28).px(6).gap(8).items_center().rounded(S.radius).cursor_pointer()
        .hover((s) => s.bg(t.hover)).tooltip("Switch machine")
        .on_click(() => this.menu())
        .child(icon("chevron-up", S.iconXs, t.dim))
        .child(icon(m ? "server" : "monitor", S.iconSm, t.muted))
        .when(!rail, (e) => e.child(div().min_w(0).truncate().text_size(S.text).font_medium().text_color(t.foreground).child(machineLabel(m))))
        .when(state && state !== "ok", (e) => e.child(div().size(6).flex_none().rounded_full().bg(state === "login" ? t.blocked : state === "connecting" ? t.working : t.dim))))
      .child(iconButton({ id: "feedback", icon: "square-pen", tip: tip("Submit feedback", "ob-tabs.feedback"), onClick: () => run("ob-tabs.feedback") }))
      .child(iconButton({ id: "help", icon: "help", tip: tip("Help", "app.help"), onClick: () => run("app.help") }))
      .child(iconButton({ id: "settings", icon: "settings", tip: tip("Settings", "mod.open:ob-settings"), onClick: () => run("mod.open", { name: "ob-settings" }) }));
  }
}
