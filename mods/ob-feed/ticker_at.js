// ticker_at.js: when a working main Claude agent last did something, for the ticker's newest-first order (pure).
// info: its terminal's entry in the feed's `terms`; touches: the feed's touches for `term:<address>`; now: the fallback.
// The scan's updatedAt when it gives one, else its newest file touch, else now (nothing better is known).
export function mainAgentAt(info, touches, now) {
  if (typeof info?.updatedAt === "number" && info.updatedAt > 0) return info.updatedAt;
  let at = 0;
  for (const t of Array.isArray(touches) ? touches : []) if (typeof t?.at === "number" && t.at > at) at = t.at;
  return at > 0 ? at : now;
}
