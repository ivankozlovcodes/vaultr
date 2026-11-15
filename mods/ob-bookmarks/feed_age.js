// Pure feed-age rules shared by the ob-* mods (copied into each mod by kit/sync.sh; kit.js re-exports them).
// No Herdr or gpui imports, so test/test_feed_age.py runs them under node.
//
// The scanner (ob-feed) publishes shared "ob.subagents" with `at`: when it last published. It publishes when
// the content changes and, with the same content, once a beat (FEED_BEAT_MS) so a quiet system stays fresh.
// If the scanner stops (its block was unloaded, or Herdr paused it), `at` stops moving and the feed is stale.

export const FEED_BEAT_MS = 60000;   // the scanner's heartbeat with unchanged content
export const FEED_STALE_MS = 120000; // older than this: the feed is paused

// True when the feed is paused: it has a payload and its last publish is older than FEED_STALE_MS. No payload is not paused.
export function feedPaused(at, now = Date.now()) {
  return typeof at === "number" && at !== 0 && now - at > FEED_STALE_MS;
}

// The line to show under a feed consumer, or null while the feed is fresh (or there is no payload yet).
export function feedLine(at, now = Date.now()) {
  if (!at || typeof at !== "number") return null;
  const age = now - at;
  if (!feedPaused(at, now)) return null;
  const m = Math.floor(age / 60000);
  const when = m < 60 ? `${m}m` : `${Math.floor(m / 60)}h`;
  return `feed paused · last scan ${when} ago`;
}

// Whether the scanner should publish now: the content changed, or the heartbeat is due.
export function publishDue({ same, now, beatAt }) {
  return !same || now - beatAt >= FEED_BEAT_MS;
}
