#!/bin/sh
# sync.sh [HOME]: copy the kit master (kit.js, obc.js, agents.js, names.js, hidden.js, attention.js, fuzzy.js, follow_target.js, feed_age.js, ticker.js, touches.js, icons/, scan_pi.py) into every mods/ob-*/ folder.
#   HOME defaults to the repo root. Builders pass their own dev home.
#   kit.js gets `export const MOD = "<folder>"`; icons go to mods/<folder>/icons/;
#   obc.js goes to mods/ob-graph/, mods/ob-outline/, and mods/ob-props/ only;
#   scan_pi.py goes to mods/ob-feed/ only. Copies are overwritten: never edit them.
#   Safe to run any time; refuses to touch ~/.config/herdr-app unless OB_SYNC_LIVE=1.
set -eu
KIT=$(cd "$(dirname "$0")" && pwd)
HOME_DIR=${1:-$(cd "$KIT/.." && pwd)}
case "$HOME_DIR" in
  "$HOME/.config/herdr-app"|"$HOME/.config/herdr-app/")
    [ "${OB_SYNC_LIVE:-0}" = 1 ] || { echo "refusing to sync into the live config (set OB_SYNC_LIVE=1)"; exit 2; } ;;
esac
[ -d "$HOME_DIR/mods" ] || { echo "no mods/ in $HOME_DIR"; exit 1; }
n=0
for dir in "$HOME_DIR"/mods/ob-*/; do
  [ -d "$dir" ] || continue
  name=$(basename "$dir")
  [ "$name" = ob-probe ] && continue
  sed "s/^export const MOD = \"__MOD__\";/export const MOD = \"$name\";/" "$KIT/kit.js" > "$dir/kit.js.tmp"
  # Rewrite only when different, so an unchanged sync doesn't hot-reload every mod.
  if ! cmp -s "$dir/kit.js.tmp" "$dir/kit.js" 2>/dev/null; then mv "$dir/kit.js.tmp" "$dir/kit.js"; else rm "$dir/kit.js.tmp"; fi
  cmp -s "$KIT/agents.js" "$dir/agents.js" 2>/dev/null || cp "$KIT/agents.js" "$dir/agents.js"
  cmp -s "$KIT/names.js" "$dir/names.js" 2>/dev/null || cp "$KIT/names.js" "$dir/names.js"
  cmp -s "$KIT/hidden.js" "$dir/hidden.js" 2>/dev/null || cp "$KIT/hidden.js" "$dir/hidden.js"
  cmp -s "$KIT/attention.js" "$dir/attention.js" 2>/dev/null || cp "$KIT/attention.js" "$dir/attention.js"
  cmp -s "$KIT/follow_target.js" "$dir/follow_target.js" 2>/dev/null || cp "$KIT/follow_target.js" "$dir/follow_target.js"
  cmp -s "$KIT/fuzzy.js" "$dir/fuzzy.js" 2>/dev/null || cp "$KIT/fuzzy.js" "$dir/fuzzy.js"
  cmp -s "$KIT/feed_age.js" "$dir/feed_age.js" 2>/dev/null || cp "$KIT/feed_age.js" "$dir/feed_age.js"
  cmp -s "$KIT/ticker.js" "$dir/ticker.js" 2>/dev/null || cp "$KIT/ticker.js" "$dir/ticker.js"
  cmp -s "$KIT/touches.js" "$dir/touches.js" 2>/dev/null || cp "$KIT/touches.js" "$dir/touches.js"
  mkdir -p "$dir/icons"
  for f in "$KIT"/icons/*.svg; do
    cmp -s "$f" "$dir/icons/$(basename "$f")" 2>/dev/null || cp "$f" "$dir/icons/"
  done
  case "$name" in
    ob-graph|ob-outline|ob-props) cmp -s "$KIT/obc.js" "$dir/obc.js" 2>/dev/null || cp "$KIT/obc.js" "$dir/obc.js" ;;
  esac
  if [ "$name" = ob-feed ]; then cmp -s "$KIT/scan_pi.py" "$dir/scan_pi.py" 2>/dev/null || cp "$KIT/scan_pi.py" "$dir/scan_pi.py"; fi
  n=$((n + 1))
done
echo "synced kit into $n mods under $HOME_DIR/mods"
