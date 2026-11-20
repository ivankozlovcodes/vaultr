// Pure quota arithmetic, formatting, stale-cache merging, and generic active session pool matching.
// Zero Herdr/gpui imports and zero provider names so test/ can run it directly under node.

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WRAPPERS = new Set(["env", "nice", "ionice", "node", "bun", "npx", "pnpx", "sh", "bash", "zsh"]);

const providerIdOf = (p) => p?.id ?? p?.provider ?? null;
const windowLabelOf = (w) => String(w?.label ?? w?.name ?? "");

export function quotaLevel(remainingPct) {
  if (remainingPct == null || !Number.isFinite(Number(remainingPct))) return "ok";
  const r = Number(remainingPct);
  if (r <= 10) return "over";
  if (r <= 25) return "busy";
  return "ok";
}

export function nextProviderRead(prev, fresh) {
  if (fresh?.state === "unknown" && prev?.state === "ok") {
    return { ...prev, failed: fresh.why || fresh.error || "Refresh failed" };
  }
  return fresh;
}

export function mergeMachineQuotas(prevMachine, freshPayload) {
  const incoming = Array.isArray(freshPayload?.items)
    ? freshPayload.items
    : (Array.isArray(freshPayload) ? freshPayload : null);
  if (!incoming) {
    return {
      at: prevMachine?.at ?? null,
      items: prevMachine?.items ?? [],
      error: freshPayload?.error ?? null,
    };
  }
  const prevById = new Map(
    (prevMachine?.items ?? [])
      .filter((p) => providerIdOf(p))
      .map((p) => [providerIdOf(p), p]),
  );
  const items = incoming
    .filter(Boolean)
    .map((p) => nextProviderRead(prevById.get(providerIdOf(p)), p));
  return {
    at: freshPayload?.at ?? prevMachine?.at ?? Date.now(),
    items,
    error: freshPayload?.error ?? null,
  };
}

export function formatSpan(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "0m";
  const totalMin = Math.round(ms / 60000);
  if (totalMin < 1) return "<1m";
  if (totalMin < 60) return `${totalMin}m`;
  const totalHours = Math.floor(totalMin / 60);
  const remMin = totalMin % 60;
  if (totalHours < 24) return remMin ? `${totalHours}h ${remMin}m` : `${totalHours}h`;
  const days = Math.floor(totalHours / 24);
  const remHours = totalHours % 24;
  return remHours ? `${days}d ${remHours}h` : `${days}d`;
}

export function formatWhen(ms) {
  if (!Number.isFinite(ms)) return "";
  const d = new Date(ms);
  const day = DAYS[d.getDay()];
  const h24 = d.getHours();
  const min = d.getMinutes();
  const ampm = h24 >= 12 ? "pm" : "am";
  const h12 = h24 % 12 || 12;
  return min ? `${day} ${h12}:${String(min).padStart(2, "0")}${ampm}` : `${day} ${h12}${ampm}`;
}

export function formatWindow(w, now = Date.now()) {
  const usedRaw = w?.usedPct ?? w?.used;
  const remRaw = w?.remainingPct ?? w?.remaining ?? (usedRaw != null ? 100 - Number(usedRaw) : 100);
  const rawLeft = Number(remRaw);
  const pctLeft = Number.isFinite(rawLeft) ? Math.max(0, Math.min(100, Math.round(rawLeft))) : 100;
  const rawUsed = Number(usedRaw ?? (100 - pctLeft));
  const pctUsed = Number.isFinite(rawUsed) ? Math.max(0, Math.min(100, Math.round(rawUsed))) : (100 - pctLeft);
  const level = quotaLevel(remRaw ?? pctLeft);
  const resetAt = w?.resetAt ?? w?.resets_at ?? null;
  if (resetAt && resetAt <= now) {
    return { pctLeft, pctUsed, level, expired: true, subLabel: "Refilled · refresh to update" };
  }
  if (resetAt) {
    return {
      pctLeft,
      pctUsed,
      level,
      expired: false,
      subLabel: `Refills in ${formatSpan(resetAt - now)} · ${formatWhen(resetAt)} · ${pctUsed}% used`,
    };
  }
  if (w?.resets) {
    return { pctLeft, pctUsed, level, expired: false, subLabel: `Resets ${w.resets} · ${pctUsed}% used` };
  }
  return { pctLeft, pctUsed, level, expired: false, subLabel: `${pctUsed}% used` };
}

function argvCommand(argv) {
  const list = Array.isArray(argv) ? argv : typeof argv === "string" ? argv.trim().split(/\s+/) : [];
  let wrapped = false;
  for (let i = 0; i < Math.min(list.length, 6); i++) {
    const tok = String(list[i] ?? "").trim();
    if (!tok) continue;
    if (tok.startsWith("-")) {
      if (wrapped && i + 1 < list.length && /^\d+$/.test(String(list[i + 1] ?? "").trim())) i++;
      continue;
    }
    const lower = tok.toLowerCase();
    const base = lower.split("/").pop();
    if (WRAPPERS.has(base)) {
      wrapped = true;
      continue;
    }
    return { lower, base };
  }
  return null;
}

function detectProvider(providers, session) {
  if (!session || typeof session !== "object") return null;
  if (typeof session.provider === "string" && session.provider.trim()) {
    return session.provider.trim();
  }
  const app = String(session.app ?? "").trim().toLowerCase();
  if (app) {
    for (const p of providers) {
      const pid = providerIdOf(p);
      if (!pid) continue;
      const apps = new Set(
        [pid, p.name, ...(Array.isArray(p.match?.apps) ? p.match.apps : [])]
          .filter(Boolean)
          .map((x) => String(x).trim().toLowerCase()),
      );
      if (apps.has(app)) return pid;
    }
  }
  const cmd = argvCommand(session.argv);
  if (cmd) {
    for (const p of providers) {
      const pid = providerIdOf(p);
      if (!pid) continue;
      const bins = (Array.isArray(p.match?.bins) ? p.match.bins : [pid]).map((x) => String(x).toLowerCase());
      const pkgs = (Array.isArray(p.match?.pkgTokens) ? p.match.pkgTokens : []).map((x) => String(x).toLowerCase());
      if (bins.includes(cmd.base) || pkgs.some((tok) => cmd.lower.includes(tok))) return pid;
    }
  }
  const model = String(session.model ?? "").trim().toLowerCase();
  if (model) {
    for (const p of providers) {
      const pid = providerIdOf(p);
      if (!pid) continue;
      const models = (Array.isArray(p.match?.models) ? p.match.models : []).map((x) => String(x).toLowerCase());
      if (models.some((tag) => model.includes(tag))) return pid;
    }
  }
  return null;
}

function windowModelTags(w) {
  if (Array.isArray(w?.models) && w.models.length) {
    return w.models.map((m) => String(m).trim().toLowerCase()).filter(Boolean);
  }
  return [];
}

function windowIdOf(w, idx) {
  return String(w?.id ?? w?.label ?? w?.name ?? idx);
}

function remainingNum(w) {
  const used = w?.usedPct ?? w?.used ?? 0;
  const rem = w?.remainingPct ?? w?.remaining ?? (100 - used);
  const r = Number(rem);
  return Number.isFinite(r) ? r : 100;
}

function pickTightest(windows, now) {
  if (!windows.length) return null;
  const live = windows.filter((w) => {
    const resetAt = w?.resetAt ?? w?.resets_at ?? null;
    return !resetAt || resetAt > now;
  });
  const pool = live.length ? live : windows;
  return pool.reduce((best, cur) => (remainingNum(cur) < remainingNum(best) ? cur : best), pool[0]);
}

export function matchSessionPool(providers, session = null, now = Date.now()) {
  const list = Array.isArray(providers) ? providers.filter(Boolean) : [];
  const activeProviderId = detectProvider(list, session);
  const activeWindowKeys = new Set();
  if (!activeProviderId) {
    return { activeProviderId: null, activeWindowKeys, highlight: null, orderedProviders: [...list] };
  }
  const provider = list.find((p) => providerIdOf(p) === activeProviderId) ?? null;
  if (!provider) {
    return { activeProviderId, activeWindowKeys, highlight: null, orderedProviders: [...list] };
  }
  const pid = providerIdOf(provider);
  const orderedWindows = Array.isArray(provider.windows) ? [...provider.windows] : [];
  let highlight = null;
  if (provider.state === "ok" && orderedWindows.length > 0) {
    const sessionModel = String(session?.model ?? "").trim().toLowerCase();
    const matched = sessionModel
      ? orderedWindows.filter((w) => {
          const tags = windowModelTags(w);
          return tags.some((tag) => sessionModel.includes(tag));
        })
      : [];
    let selectedWindows = matched;
    if (!selectedWindows.length) {
      const general = orderedWindows.filter((w) => windowModelTags(w).length === 0);
      const tightest = pickTightest(general.length ? general : orderedWindows, now);
      if (tightest) selectedWindows = [tightest];
    }
    const selectedSet = new Set(selectedWindows);
    orderedWindows.forEach((w, idx) => {
      if (selectedSet.has(w)) activeWindowKeys.add(`${pid}:${windowIdOf(w, idx)}`);
    });
    const highlightWin = pickTightest(selectedWindows, now) ?? selectedWindows[0] ?? null;
    const providerCopy = {
      ...provider,
      windows: [
        ...orderedWindows.filter((w) => selectedSet.has(w)),
        ...orderedWindows.filter((w) => !selectedSet.has(w)),
      ],
    };
    if (highlightWin) {
      highlight = {
        provider: providerCopy,
        window: highlightWin,
        modelLabel: session?.model || provider.plan || session?.app || provider.name,
      };
    }
    const orderedProviders = [providerCopy, ...list.filter((p) => p !== provider)];
    return { activeProviderId, activeWindowKeys, highlight, orderedProviders };
  }
  const orderedProviders = [provider, ...list.filter((p) => p !== provider)];
  return { activeProviderId, activeWindowKeys, highlight: null, orderedProviders };
}
