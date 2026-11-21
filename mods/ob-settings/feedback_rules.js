// feedback_rules.js: pure rules for the Feedback settings tab (no Herdr imports),
// so test/test_ob_settings.py runs them directly under node.

const ABSOLUTE = /^([A-Za-z]:[\\/]|\/|\\\\)/;

function stripTrailing(path) {
  if (/^\/+$/.test(path)) return "/";
  if (/^[A-Za-z]:[\\/]+$/.test(path)) return path.slice(0, 3);
  if (/^\\\\+$/.test(path)) return "\\\\";
  return path.replace(/[\\/]+$/, "");
}

// Expand ~ / ~/... against `home` and validate full Unix or Windows paths.
// Returns null on empty or relative paths.
export function expandFeedbackPath(p, home) {
  const s = String(p ?? "").trim();
  if (!s) return null;
  if (s === "~" || s.startsWith("~/") || s.startsWith("~\\")) {
    const h = String(home ?? "").trim();
    if (!h) return null;
    const base = stripTrailing(h);
    if (s === "~") return base;
    const tail = s.slice(1).replace(/^[/\\]+/, "");
    if (!tail) return base;
    const sep = base === "/" || base.endsWith("\\") || base.endsWith("/")
      ? ""
      : (base.includes("\\") && !base.includes("/") ? "\\" : "/");
    return stripTrailing(`${base}${sep}${tail}`);
  }
  if (ABSOLUTE.test(s)) return stripTrailing(s);
  return null;
}

// The value to store for a typed feedback folder: { value } (null removes the key)
// or { error } (not saved).
export function parseFeedbackFolder(s, home = "/") {
  const t = String(s ?? "").trim();
  if (!t) return { value: null };
  return expandFeedbackPath(t, home)
    ? { value: t }
    : { error: "The feedback folder must be a full path: ~/... or /..." };
}

// feedback.json with `folder` set (or removed when value is null/undefined).
// Other keys in the file are kept.
export function mergeFeedbackOwn(own, value) {
  const base = own && typeof own === "object" && !Array.isArray(own) ? own : {};
  const next = { ...base };
  if (value === null || value === undefined) delete next.folder;
  else next.folder = value;
  return next;
}
