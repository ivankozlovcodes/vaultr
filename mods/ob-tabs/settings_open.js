// Is the Settings dialog open? (pure, no Herdr imports: test/test_ob_tabs.py runs it under node)
// Shared "ob-settings.open" holds the time of the dialog's last beat while it is open (ob-settings beats every BEAT_MS),
// and false once it closes. A beat older than OPEN_TTL_MS means the dialog died open, or its saved state outlived it.
export const OPEN_TTL_MS = 15000;

export function isSettingsOpen(value, now = Date.now()) {
  return typeof value === "number" && value > 0 && now - value < OPEN_TTL_MS;
}
