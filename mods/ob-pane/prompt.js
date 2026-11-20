// Pure helpers for reading a session's recent prompts from the provider facade.

export function promptTurns(session) {
  const raw = Array.isArray(session) ? session : session?.prompts;
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const t of raw) {
    if (!t || typeof t !== "object") continue;
    const text = typeof t.text === "string" ? t.text.trim() : "";
    if (!text) continue;
    const full = typeof t.full === "string" && t.full.trim() ? t.full.trim() : text;
    out.push({
      step: typeof t.step === "number" && Number.isFinite(t.step) ? t.step : null,
      text,
      full,
      ts: t.ts ?? null,
    });
  }
  return out;
}

export function latestPrompt(session) {
  const items = promptTurns(session);
  if (!items.length) return null;
  const last = items[items.length - 1];
  return {
    text: last.text,
    full: last.full,
    ts: last.ts,
    step: last.step,
    count: items.length,
    history: [...items].reverse(),
  };
}
