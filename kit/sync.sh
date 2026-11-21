#!/bin/sh
# sync.sh [HOME]: copy every kit/*.js and kit/icons/*.svg into every mods/ob-*/ folder.
#   HOME defaults to the repo root. Builders pass their own dev home.
#   kit.js gets `export const MOD = "<folder>"`; icons go to mods/<folder>/icons/;
#   obc.js goes only to ob-* mods whose own files import ./obc.js; ob-probe is skipped.
#   Copies are overwritten: never edit them.
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
  dir_no_slash=${dir%/}
  name=$(basename "$dir_no_slash")
  [ "$name" = ob-probe ] && continue
  needs_obc=0
  if find "$dir_no_slash" -name vendor -prune -o \( -name '*.js' -o -name '*.mjs' \) -type f -print | {
    while IFS= read -r f; do
      case "$f" in "$dir_no_slash/"*/*) ;; *) [ -f "$KIT/$(basename "$f")" ] && continue ;; esac
      if grep -Eq '^(([^/]|/[^/*])*[^[:alnum:]_$])?(from[[:space:]]*|import[[:space:]]+)["'\'']\./obc\.js["'\'']' "$f"; then
        exit 0
      fi
    done
    exit 1
  }; then
    needs_obc=1
  fi
  for k in "$KIT"/*.js; do
    [ -f "$k" ] || continue
    base=$(basename "$k")
    if [ "$base" = kit.js ]; then
      sed "s/^export const MOD = \"__MOD__\";/export const MOD = \"$name\";/" "$k" > "$dir_no_slash/kit.js.tmp"
      # Rewrite only when different, so an unchanged sync doesn't hot-reload every mod.
      if ! cmp -s "$dir_no_slash/kit.js.tmp" "$dir_no_slash/kit.js" 2>/dev/null; then
        mv "$dir_no_slash/kit.js.tmp" "$dir_no_slash/kit.js"
      else
        rm "$dir_no_slash/kit.js.tmp"
      fi
    elif [ "$base" = obc.js ]; then
      if [ "$needs_obc" = 1 ]; then
        cmp -s "$k" "$dir_no_slash/obc.js" 2>/dev/null || cp "$k" "$dir_no_slash/obc.js"
      elif [ -f "$dir_no_slash/obc.js" ]; then
        rm -f "$dir_no_slash/obc.js"
      fi
    else
      cmp -s "$k" "$dir_no_slash/$base" 2>/dev/null || cp "$k" "$dir_no_slash/$base"
    fi
  done
  mkdir -p "$dir_no_slash/icons"
  for f in "$KIT"/icons/*.svg; do
    [ -f "$f" ] || continue
    cmp -s "$f" "$dir_no_slash/icons/$(basename "$f")" 2>/dev/null || cp "$f" "$dir_no_slash/icons/"
  done
  n=$((n + 1))
done
echo "synced kit into $n mods under $HOME_DIR/mods"
