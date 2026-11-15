// platform_keys.js: keys/vaultr-keys.json is written with Ctrl; on macOS Vaultr uses Cmd in its place, as Herdr's own
// macOS keys do. Pure (no herdr imports) so it runs under node. install.sh applies the same rule when it merges keys.
//   chordForPlatform("ctrl-shift-p", "macos") -> "cmd-shift-p"; "ctrl-k ctrl-s" -> "cmd-k cmd-s"; other platforms keep it.

// One stroke: a `ctrl` modifier word becomes `cmd`. The last part is the key itself and is left alone ("ctrl" alone,
// a bare modifier, stays). "ctrl--" (ctrl + minus) keeps its key.
function strokeForMac(stroke) {
  const m = /^((?:[a-z]+-)*)(.+)$/.exec(stroke);
  if (!m || !m[1]) return stroke;
  return m[1].split("-").map((w) => (w === "ctrl" ? "cmd" : w)).join("-") + m[2];
}

export function chordForPlatform(chord, platform) {
  if (platform !== "macos" || typeof chord !== "string") return chord;
  return chord.split(" ").map(strokeForMac).join(" ");
}
