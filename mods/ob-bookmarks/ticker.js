// Pure: the status row's ticker of running agents (copied into each mod by kit/sync.sh; kit.js re-exports
// it). No Herdr or gpui imports, so test/test_ticker.py runs it under node.
//
// An item is a live agent: { key, title, live, at, tool: { tool, args } | null, turns, target }. The chip says
// the title and the latest action: "Claude Code · Edit main.js", "Fix hotkeys · Bash: python3 …", "pi · turn 12".
// Arguments come from the scanner already brief; they are cut to ARG_MAX again here. Output is never an input.

export const TICKER_MAX = 3;   // chips at most
export const ARG_MAX = 40;     // characters of a tool argument

const cut = (s, n = ARG_MAX) => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

// The latest action of one agent, or "" when it has none yet.
export function tickerAction(item) {
  const t = item?.tool;
  if (t?.tool) {
    const args = cut(t.args);
    if (t.tool === "Bash") return args ? `Bash: ${args}` : "Bash";
    return args ? `${t.tool} ${args}` : t.tool;
  }
  if (item?.turns) return `turn ${item.turns}`;
  return "";
}

// The chips for the running agents: newest first, at most `max`. A chip carries its target (what a click does).
export function tickerChips(items, max = TICKER_MAX) {
  return (items ?? [])
    .filter((x) => x && x.live)
    .slice()
    .sort((a, b) => (b.at ?? 0) - (a.at ?? 0))
    .slice(0, max)
    .map((x) => {
      const action = tickerAction(x);
      const text = action ? `${x.title} · ${action}` : String(x.title ?? "");
      return { key: x.key, text, target: x.target ?? null };
    });
}
