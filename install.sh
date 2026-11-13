#!/usr/bin/env bash
# install.sh: Install, activate, or uninstall Vaultr layout and mods for Herdr
#
# Usage:
#   ./install.sh             # Sync kit, symlink layouts and mods, merge keybindings
#   ./install.sh --activate  # Install and switch active layout to vaultr
#   ./install.sh --uninstall # Remove vaultr layouts/mods, revert keybindings, switch layout to iv

set -euo pipefail

REPO_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
HERDR_APP_DIR="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"

ACTIVATE=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --activate)
      ACTIVATE=1
      ;;
    --uninstall)
      UNINSTALL=1
      ;;
    -h|--help)
      echo "Usage: $0 [--activate | --uninstall]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--activate | --uninstall]" >&2
      exit 1
      ;;
  esac
done

if [[ "$UNINSTALL" -eq 1 ]]; then
  echo "Uninstalling Vaultr..."

  # 1. Remove vaultr layout files (and any legacy obsidian layout files) and ob-* mods
  for file in "vaultr.json" "vaultr.svg" "obsidian.json" "obsidian.svg"; do
    if [[ -f "$HERDR_APP_DIR/layouts/$file" || -L "$HERDR_APP_DIR/layouts/$file" ]]; then
      rm -f "$HERDR_APP_DIR/layouts/$file"
      echo "removed layout: $HERDR_APP_DIR/layouts/$file"
    fi
  done

  for mod_path in "$HERDR_APP_DIR"/mods/ob-*; do
    if [[ -L "$mod_path" || -d "$mod_path" || -e "$mod_path" ]]; then
      rm -rf "$mod_path"
      echo "removed mod: $mod_path"
    fi
  done

  # 2. Remove vaultr and legacy obsidian keybinding sections from keys.json
  if [[ -f "$HERDR_APP_DIR/keys.json" ]]; then
    python3 - "$HERDR_APP_DIR/keys.json" <<-'PY'
import json, os, sys

keys_file = sys.argv[1]
try:
    with open(keys_file, "r") as f:
        keys = json.load(f)
except Exception as e:
    sys.exit(0)

modified = False
for k in ("layout:vaultr", "layout:obsidian", "mod:ob-sessions"):
    if k in keys:
        del keys[k]
        modified = True

if modified:
    with open(keys_file, "w") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")
PY
    echo "removed vaultr keybindings from $HERDR_APP_DIR/keys.json"
  fi

  # 3. Switch layout back to iv
  herdr-app do layout.switch --name iv >/dev/null 2>&1 || true
  echo "switched layout -> iv"
  echo "Vaultr uninstalled."
  exit 0
fi

echo "Installing Vaultr..."

# 1. Sync kit master into mods/ob-*/ if any exist
has_ob_mods=0
for d in "$REPO_DIR"/mods/ob-*/; do
  if [[ -d "$d" ]]; then
    has_ob_mods=1
    break
  fi
done

if [[ "$has_ob_mods" -eq 1 ]]; then
  echo "Syncing kit to mods..."
  "$REPO_DIR/kit/sync.sh" "$REPO_DIR"
fi

mkdir -p "$HERDR_APP_DIR/layouts" "$HERDR_APP_DIR/mods"

# Clean up any leftover legacy obsidian layout files
for legacy in "obsidian.json" "obsidian.svg"; do
  if [[ -f "$HERDR_APP_DIR/layouts/$legacy" || -L "$HERDR_APP_DIR/layouts/$legacy" ]]; then
    rm -f "$HERDR_APP_DIR/layouts/$legacy"
    echo "cleaned up stale layout: $HERDR_APP_DIR/layouts/$legacy"
  fi
done

# 2. Symlink layouts if present
for file in "vaultr.json" "vaultr.svg"; do
  src="$REPO_DIR/layouts/$file"
  if [[ -f "$src" ]]; then
    ln -sfn "$src" "$HERDR_APP_DIR/layouts/$file"
    echo "linked layout: $HERDR_APP_DIR/layouts/$file -> $src"
  fi
done

# 3. Symlink each mods/ob-* directory
for mod_dir in "$REPO_DIR"/mods/ob-*/; do
  [[ -d "$mod_dir" ]] || continue
  name=$(basename "$mod_dir")
  target="$HERDR_APP_DIR/mods/$name"
  if [[ -L "$target" || -d "$target" || -e "$target" ]]; then
    rm -rf "$target"
  fi
  ln -sfn "$mod_dir" "$target"
  echo "linked mod: $target -> $mod_dir"
done

# 4. Merge vaultr keybindings into keys.json and clean up stale layout:obsidian
if [[ -f "$REPO_DIR/keys/vaultr-keys.json" ]]; then
  python3 - "$REPO_DIR/keys/vaultr-keys.json" "$HERDR_APP_DIR/keys.json" <<-'PY'
import json, os, sys

src_file, dst_file = sys.argv[1], sys.argv[2]
keys = {}
if os.path.exists(dst_file):
    try:
        with open(dst_file, "r") as f:
            keys = json.load(f)
    except Exception as e:
        print(f"Warning: could not read {dst_file}: {e}", file=sys.stderr)

# Clean up stale layout:obsidian
keys.pop("layout:obsidian", None)

with open(src_file, "r") as f:
    vaultr_keys = json.load(f)

for k in ("layout:vaultr", "mod:ob-sessions"):
    if k in vaultr_keys:
        keys[k] = vaultr_keys[k]

with open(dst_file, "w") as f:
    json.dump(keys, f, indent=2)
    f.write("\n")
PY
  echo "merged keybindings into $HERDR_APP_DIR/keys.json"
fi

# 5. Activate if requested
if [[ "$ACTIVATE" -eq 1 ]]; then
  herdr-app do layout.switch --name vaultr >/dev/null 2>&1 || true
  echo "activated layout -> vaultr"
fi

echo "Vaultr installation complete."
