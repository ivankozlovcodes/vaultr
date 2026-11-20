// ob-quotas: Right-sidebar Quotas panel for provider plan limits.
// Collects quotas via provider.quota() (on the followed or selected machine, off the UI path),
// caches per machine in shared("ob.quotas") and localStorage, and highlights the active
// session's pool (matchSessionPool in quotas.js).
//
// Commands (ob-quotas.<cmd>): refresh, refresh:<local|name>, machine:<follow|local|name>,
//   fold:<providerId>, focus.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, ScrollHandle, Scrollbar } from "gpui-base";
import {
  props, nextCommand, settings, layout, focused, panes, spaces, terminals, agents,
  machines, shared, setShared,
} from "herdr";
import {
  S, tc, alpha, icon, iconButton, badge, sectionHeader, emptyState, provider, machineLabel,
  machineOf, ago, takeFocus, isShown, followTarget, lsGet, lsSet,
} from "./kit.js";
import { quotaLevel, mergeMachineQuotas, formatWindow, matchSessionPool } from "./quotas.js";

const TTL = 5 * 60_000;
const RETRY = 60_000;
const POLL_MS = 30_000;
const EXEC_TIMEOUT = 45_000;
const SHARED_KEY = "ob.quotas";

const mkey = (m) => m ?? "local";
const splitCmd = (c) => {
  const s = String(c ?? "");
  const i = s.indexOf(":");
  return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)];
};
const providerIdOf = (p) => p?.id ?? p?.provider ?? "";
const windowLabelOf = (w) => w?.label ?? w?.name ?? "";

function normMachineMode(v) {
  if (v === "follow" || v === "local") return v;
  if (typeof v === "string" && v.startsWith("remote:") && v.length > 7) return v;
  return "follow";
}

function modelFromArgv(argv) {
  const list = Array.isArray(argv) ? argv : [];
  for (let i = 0; i < list.length - 1; i++) {
    if (list[i] === "--model" || list[i] === "-m") return String(list[i + 1] ?? "").trim() || null;
    if (String(list[i]).startsWith("--model=")) return String(list[i]).slice(8).trim() || null;
  }
  return null;
}

function progressBar(t, pctLeft, barColor, height = 5) {
  const track = h_flex().w_full().h(height).flex_none().rounded_full().overflow_hidden().bg(alpha(t.border, 0.7));
  if (pctLeft <= 0) return track;
  if (pctLeft >= 100) return track.child(div().size_full().bg(barColor));
  return track
    .child(div().h_full().flex_grow(pctLeft).bg(barColor))
    .child(div().h_full().flex_grow(100 - pctLeft));
}

function stateLabel(state) {
  if (state === "signed-out") return "signed out";
  if (state === "no-plan") return "no plan";
  return "unavailable";
}

function barColorFor(t, level, isActive) {
  if (level === "over") return t.blocked;
  if (level === "busy") return t.working;
  return isActive ? t.accent : t.ansi2;
}

export default class Quotas extends View {
  init(_p, cx) {
    this.handle = cx.focus_handle();
    this.scroll = ScrollHandle.new();
    this.w = 0;
    this.folded = new Set(lsGet("folded", []));
    this.machineMode = normMachineMode(lsGet("machineMode", "follow"));
    this.lastAgent = null;
    this.lastAny = null;
    this.lastMachine = null;
    this.scheduledFetch = null;
    this.busy = new Set();
    this.failedAt = {};
    const saved = lsGet("cache", {});
    this.localCache = saved && typeof saved === "object" ? saved : {};
    if (!shared(SHARED_KEY) && Object.keys(this.localCache).length) {
      cx.timer.after(0, () => {
        if (!shared(SHARED_KEY) && Object.keys(this.localCache).length) setShared(SHARED_KEY, this.localCache);
      });
    }
    cx.timer.every(POLL_MS, (cx) => {
      if (!isShown(layout(), props()?.slot ?? "ob-quotas")) return;
      const { targetMachine } = this.resolveTarget();
      if (this.shouldFetch(targetMachine, Date.now())) this.fetch(targetMachine, cx, false);
    });
    cx.spawn(async (cx) => {
      for (;;) {
        const c = String(await nextCommand());
        try { this.command(c, cx); } catch (e) { console.log(`ob-quotas: ${c} failed: ${e?.message ?? e}`); }
        try { cx.notify(); } catch { return; }
      }
    });
  }

  cache() {
    const s = shared(SHARED_KEY);
    return (s && typeof s === "object" ? s : this.localCache) ?? {};
  }

  saveCache(next) {
    this.localCache = next;
    lsSet("cache", next);
    setShared(SHARED_KEY, next);
  }

  resolveTarget() {
    const ts = terminals() ?? [];
    const ag = agents() ?? [];
    const ps = panes();
    const sp = spaces();
    const f = focused();
    const agentAddrs = new Set(ag.map((a) => a.address));
    const isAgentAddr = (addr) => Boolean(addr && agentAddrs.has(addr));
    const activeSpace = sp.find((s) => s.id === f?.space) ?? sp.find((s) => s.active) ?? sp[0] ?? null;
    const activeTab = activeSpace?.tabs?.find((x) => x.id === f?.tab) ?? activeSpace?.tabs?.find((x) => x.active) ?? activeSpace?.tabs?.[0] ?? null;
    const tabPanes = activeTab ? ps.filter((p) => p.tab === activeTab.id && p.terminal) : [];
    const tabAgent = tabPanes.find((p) => p.focused && isAgentAddr(p.terminal)) ?? tabPanes.find((p) => isAgentAddr(p.terminal)) ?? null;
    const focusTerminal = f?.terminal && isAgentAddr(f.terminal) ? f.terminal : tabAgent?.terminal ?? null;
    const focusPane = f?.terminal && isAgentAddr(f.terminal) ? f.pane : tabAgent?.pane ?? null;
    const focusObj = focusTerminal ? { pane: focusPane, terminal: focusTerminal, agent: true } : null;
    const rAgent = followTarget({ pinned: null, focused: focusObj, last: this.lastAgent, terminals: ts, wantAgent: true });
    this.lastAgent = rAgent.last;
    const anyFocusObj = f?.terminal ? { pane: f.pane, terminal: f.terminal, agent: false } : (tabPanes[0] ? { pane: tabPanes[0].pane, terminal: tabPanes[0].terminal, agent: false } : null);
    const rAny = rAgent.terminal ? rAgent : followTarget({ pinned: null, focused: anyFocusObj, last: this.lastAny, terminals: ts, wantAgent: false });
    this.lastAny = rAny.last;
    const followedAddr = rAgent.terminal ?? rAny.terminal ?? null;
    const autoMachine = followedAddr
      ? machineOf(followedAddr)
      : (activeSpace?.machine ?? null);

    let targetMachine = autoMachine;
    if (this.machineMode === "local") targetMachine = null;
    else if (this.machineMode.startsWith("remote:")) targetMachine = this.machineMode.slice(7);

    let session = null;
    const addr = rAgent.terminal ?? null;
    if (addr && (machineOf(addr) ?? null) === (targetMachine ?? null)) {
      const term = ts.find((t) => t.address === addr) ?? null;
      const agItem = ag.find((a) => a.address === addr) ?? null;
      const pane = ps.find((p) => p.terminal === addr) ?? null;
      const psess = provider.session(addr);
      const argv = term?.foreground?.argv ?? term?.argv ?? null;
      session = {
        provider: psess?.provider ?? null,
        app: term?.report?.app ?? agItem?.app ?? pane?.app ?? term?.program?.key ?? agItem?.program?.key ?? null,
        model: term?.report?.model ?? agItem?.model ?? modelFromArgv(argv),
        title: psess?.title ?? term?.title ?? agItem?.title ?? pane?.title ?? null,
        argv,
      };
    }
    return { targetMachine, session };
  }

  shouldFetch(machine, now) {
    const k = mkey(machine);
    if (this.busy.has(k)) return false;
    if (machine) {
      const mInfo = machines().find((x) => !x.temporary && x.name === machine);
      if (mInfo && mInfo.layout === "unavailable") return false;
    }
    const failAt = this.failedAt[k] ?? 0;
    if (failAt && now - failAt < RETRY) return false;
    const entry = this.cache()[k];
    if (!entry?.at) return true;
    return now - entry.at >= TTL;
  }

  fetch(machine, cx, force = false) {
    const k = mkey(machine);
    if (this.busy.has(k)) return;
    if (!force && !this.shouldFetch(machine, Date.now())) return;
    this.busy.add(k);
    cx.notify();
    cx.spawn(async (cx) => {
      try {
        const res = await provider.quota({ machine, timeout: EXEC_TIMEOUT });
        const { ok, reason, error, at, providers: items } = res ?? {};
        if (!ok) {
          if (reason === "unsupported") {
            const cur = this.cache();
            this.saveCache({ ...cur, [k]: mergeMachineQuotas(cur[k], { at: Date.now(), items: [], error: null }) });
            delete this.failedAt[k];
            this.busy.delete(k);
            cx.notify();
            return;
          }
          throw new Error(error || "Could not read quotas");
        }
        const cur = this.cache();
        const payload = { at: at ?? Date.now(), items: items ?? [], error: null };
        const merged = mergeMachineQuotas(cur[k], payload);
        this.saveCache({ ...cur, [k]: merged });
        const allFailed = Array.isArray(payload.items) && payload.items.length > 0 && payload.items.every((p) => p.state === "unknown");
        if (allFailed) this.failedAt[k] = Date.now();
        else delete this.failedAt[k];
      } catch (e) {
        this.failedAt[k] = Date.now();
        const msg = String(e?.message ?? e).split("\n").pop()?.slice(0, 200) || "Could not read quotas";
        const cur = this.cache();
        const merged = mergeMachineQuotas(cur[k], { error: msg });
        this.saveCache({ ...cur, [k]: merged });
      }
      this.busy.delete(k);
      cx.notify();
    });
  }

  setMachineMode(mode, cx) {
    this.machineMode = normMachineMode(mode);
    lsSet("machineMode", this.machineMode);
    const { targetMachine } = this.resolveTarget();
    if (this.shouldFetch(targetMachine, Date.now())) this.fetch(targetMachine, cx, false);
  }

  command(c, cx) {
    const [verb, arg] = splitCmd(c);
    if (verb === "refresh") {
      if (!arg) this.fetch(this.resolveTarget().targetMachine, cx, true);
      else this.fetch(arg === "local" ? null : arg, cx, true);
    } else if (verb === "machine") {
      if (arg === "follow" || arg === "local") this.setMachineMode(arg, cx);
      else if (arg) this.setMachineMode(arg.startsWith("remote:") ? arg : `remote:${arg}`, cx);
    } else if (verb === "fold" && arg) {
      this.folded.has(arg) ? this.folded.delete(arg) : this.folded.add(arg);
      lsSet("folded", [...this.folded]);
    } else if (verb === "focus") {
      this.handle.focus();
    }
  }

  compact() { return this.w > 0 && this.w < 250; }

  header(t, m, entry, reading, now) {
    const age = entry?.at ? ago(entry.at, now) : "";
    const status = reading ? "updating…" : entry?.at ? `${age}${age === "now" ? "" : " ago"}` : "not read yet";
    return h_flex().id("qhead").h(40).flex_none().px(S.pad + 4).gap(8).items_center()
      .child(icon("chart", S.icon, t.muted))
      .child(v_flex().flex_1().min_w(0)
        .child(div().truncate().text_size(S.text).font_semibold().text_color(t.foreground).child("Quotas"))
        .child(div().truncate().text_size(S.textXs).text_color(t.dim).child(`${machineLabel(m)} · ${status}`)))
      .child(iconButton({
        id: "refresh",
        icon: "refresh",
        active: reading,
        tip: "Refresh quotas now",
        onClick: (_e, cx) => this.fetch(m, cx, true),
      }));
  }

  machineBar(t, remoteMachines) {
    const pill = (id, label, mode, tip) => {
      const on = this.machineMode === mode;
      return h_flex().id(`qm-${id}`).h(22).px(8).flex_none().items_center().rounded(S.radius).cursor_pointer()
        .text_size(S.textXs).font_medium()
        .text_color(on ? t.foreground : t.dim)
        .when(on, (e) => e.bg(t.selected))
        .when(!on, (e) => e.bg(t.raised).hover((s) => s.bg(t.hover).text_color(t.muted)))
        .tooltip(tip)
        .on_click((_e, cx) => { this.setMachineMode(mode, cx); cx.notify(); })
        .child(label);
    };
    return h_flex().id("q-machines").flex_none().flex_wrap().gap(4).px(S.pad + 2).py(6).border_b(1).border_color(t.border)
      .child(pill("follow", "Follow", "follow", "Follow the focused session's machine"))
      .child(pill("local", "Local", "local", "This computer"))
      .children(remoteMachines.map((name) => pill(`r-${name}`, name, `remote:${name}`, `Show quotas on ${name}`)));
  }

  calloutCard(t, highlight, now) {
    const fmt = formatWindow(highlight.window, now);
    const barColor = barColorFor(t, fmt.level, true);
    const modelLabel = String(highlight.modelLabel || highlight.provider.name).replace(/-\d{8}$/, "");
    return v_flex().id("q-active").flex_none().mx(S.pad).my(4).p(9).gap(6).rounded(S.radiusLg)
      .bg(t.background).border_1().border_color(alpha(t.accent, 0.5))
      .child(h_flex().gap(6).items_center()
        .child(badge(modelLabel, "accent"))
        .child(div().flex_1().min_w(0).truncate().text_size(S.textSm).font_medium().text_color(t.foreground)
          .child(`${highlight.provider.name} · ${windowLabelOf(highlight.window)}`))
        .child(div().flex_none().text_size(S.textSm).font_bold().text_color(barColor).child(`${fmt.pctLeft}% left`)))
      .child(progressBar(t, fmt.pctLeft, barColor, 6))
      .child(div().truncate().text_size(S.textXs).text_color(fmt.expired ? t.working : t.dim).child(fmt.subLabel));
  }

  providerSection(t, p, activeWindowKeys, now, rows) {
    const pid = providerIdOf(p);
    const open = !this.folded.has(pid);
    const title = p.plan ? `${p.name.toUpperCase()} · ${String(p.plan).toUpperCase()}` : p.name.toUpperCase();
    const windows = Array.isArray(p.windows) ? p.windows : [];
    let count = stateLabel(p.state);
    if (p.state === "ok" && windows.length) {
      const minLeft = Math.min(...windows.map((w) => formatWindow(w, now).pctLeft));
      count = `${minLeft}% min`;
    }
    rows.push(sectionHeader({
      id: `qsec-${pid}`,
      title,
      count,
      open,
      onToggle: (_e, cx) => {
        open ? this.folded.add(pid) : this.folded.delete(pid);
        lsSet("folded", [...this.folded]);
        cx.notify();
      },
      right: [!this.compact() && p.account ? div().min_w(0).flex_shrink(1).truncate().max_w(130).text_size(S.textXs).font_normal().text_color(t.dim).child(p.account) : null].filter(Boolean),
    }));
    if (!open) return;
    if (p.state === "ok" && windows.length) {
      windows.forEach((w, idx) => {
        const wLabel = windowLabelOf(w);
        const wKey = `${pid}:${w.id ?? (wLabel || idx)}`;
        const isActive = activeWindowKeys.has(wKey);
        const fmt = formatWindow(w, now);
        const barColor = barColorFor(t, fmt.level, isActive);
        const pctColor = fmt.level === "ok" ? (isActive ? t.accent : t.foreground) : barColor;
        rows.push(v_flex().id(`qw-${pid}-${idx}`).flex_none().px(S.pad + 2).py(5).gap(4).mx(4).rounded(S.radius)
          .when(isActive, (e) => e.bg(alpha(t.accent, 0.08)))
          .child(h_flex().gap(6).items_center()
            .child(div().min_w(0).flex_shrink(1).truncate().text_size(S.textSm).font_medium()
              .text_color(isActive ? t.foreground : t.muted).child(wLabel))
            .when(isActive, (e) => e.child(badge("active", "accent")))
            .child(div().flex_1().min_w(4))
            .child(div().flex_none().text_size(S.textSm).font_semibold().text_color(pctColor).child(`${fmt.pctLeft}% left`)))
          .child(progressBar(t, fmt.pctLeft, barColor, 5))
          .child(div().truncate().text_size(S.textXs).text_color(fmt.expired ? t.working : t.dim).child(fmt.subLabel)));
      });
      if (p.failed) {
        rows.push(h_flex().id(`qfail-${pid}`).flex_none().px(S.pad + 2).py(3).gap(5).items_start()
          .child(icon("alert", S.iconXs, t.working))
          .child(div().flex_1().min_w(0).whitespace_normal().text_size(S.textXs).text_color(t.dim)
            .child(`Last refresh failed: ${p.failed}`)));
      }
      return;
    }
    const msg = p.state === "signed-out"
      ? "Not signed in on this machine"
      : p.state === "no-plan"
        ? "No subscription plan limits (API key billing)"
        : (p.why || p.error || "Could not read limits");
    rows.push(div().id(`qst-${pid}`).px(S.pad + 4).py(6).text_size(S.textSm).text_color(t.dim).whitespace_normal().child(msg));
  }

  render(cx) {
    const t = tc();
    takeFocus(this, cx, props()?.slot ?? "ob-quotas", this.handle);
    const { targetMachine: m, session } = this.resolveTarget();
    const k = mkey(m);
    const now = Date.now();
    const shown = isShown(layout(), props()?.slot ?? "ob-quotas");
    if (k !== this.lastMachine) this.lastMachine = k;
    if (shown && this.shouldFetch(m, now) && this.scheduledFetch !== k) {
      this.scheduledFetch = k;
      cx.timer.after(0, (cx) => {
        this.scheduledFetch = null;
        const { targetMachine } = this.resolveTarget();
        if (this.shouldFetch(targetMachine, Date.now())) this.fetch(targetMachine, cx, false);
      });
    }
    const entry = this.cache()[k] ?? null;
    const reading = this.busy.has(k);
    const remoteMachines = machines().filter((x) => !x.temporary && x.name).map((x) => x.name);
    const showMachineBar = remoteMachines.length > 0 || this.machineMode !== "follow";

    const pool = matchSessionPool(entry?.items ?? [], session, now);
    const rows = [];
    if (entry?.error) {
      rows.push(h_flex().id("q-err").flex_none().mx(S.pad).my(4).p(8).gap(6).items_start().rounded(S.radius)
        .bg(alpha(t.blocked, 0.1)).border_1().border_color(alpha(t.blocked, 0.4))
        .child(icon("alert", S.iconXs, t.blocked))
        .child(div().flex_1().min_w(0).whitespace_normal().text_size(S.textXs).text_color(t.blocked).child(entry.error)));
    }
    if (pool.highlight) rows.push(this.calloutCard(t, pool.highlight, now));
    for (const p of pool.orderedProviders) this.providerSection(t, p, pool.activeWindowKeys, now, rows);

    let body;
    if (!entry && reading) {
      body = emptyState({ icon: "chart", title: "Reading quotas…", body: "Checking provider plan limits." });
    } else if (!entry && !reading) {
      body = emptyState({
        icon: "chart",
        title: "Quotas not read yet",
        body: "Read provider plan limits on this machine.",
        action: { id: "q-read", label: "Read quotas", onClick: (_e, cx) => this.fetch(m, cx, true) },
      });
    } else if (!pool.orderedProviders.length && !entry?.error) {
      body = emptyState({
        icon: "chart",
        title: "No CLI plans found",
        body: "No provider plan limits found on this machine.",
        action: { id: "q-retry", label: "Check again", onClick: (_e, cx) => this.fetch(m, cx, true) },
      });
    } else {
      body = div().id("qlist-wrap").relative().flex_1().min_h(0)
        .child(v_flex().id("qlist").size_full().py(4).overflow_y_scroll().track_scroll(this.scroll).children(rows).child(div().h(8).flex_none()))
        .child(Scrollbar.vertical("qlist").absolute().inset_0());
    }

    return v_flex().id("root").track_focus(this.handle).size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
      .on_size_change((s, cx) => { const w = s.width / (settings().zoom || 1); if (Math.abs(w - this.w) > 1) { this.w = w; cx.notify(); } })
      .child(this.header(t, m, entry, reading, now))
      .child(div().h(1).flex_none().bg(t.border))
      .when(showMachineBar, (e) => e.child(this.machineBar(t, remoteMachines)))
      .child(body);
  }
}
