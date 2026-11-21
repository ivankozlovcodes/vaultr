#!/usr/bin/env bash
# install.sh: Install, activate, or uninstall Vaultr layout and mods for Herdr
#
# Usage:
#   ./install.sh             # Sync kit, copy the layout, symlink mods, merge keybindings
#   ./install.sh --link      # As above, but symlink the layout to the repo (development)
#   ./install.sh --reset-layout  # Replace your layout copy with the repo's (backed up first)
#   ./install.sh --activate  # Install and switch active layout to vaultr
#   ./install.sh --uninstall # Remove vaultr layouts/mods, revert keybindings, switch layout to $VAULTR_FALLBACK_LAYOUT (default main)
#                            # A layout copy you changed stays unless --reset-layout is passed

set -euo pipefail

# The script's real path. `readlink -f` is missing on macOS before 12.3; python3 is required anyway (keys merge).
resolve() { readlink -f -- "$1" 2>/dev/null || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
REPO_DIR=$(cd -- "$(dirname -- "$(resolve "$0")")" && pwd)
HERDR_APP_DIR="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
# The OS the keys are for: on Darwin (macOS) Vaultr's Ctrl keys install as Cmd (see mods/ob-settings/platform_keys.js).
VAULTR_OS="${VAULTR_OS:-$(uname -s)}"
# Layout that Herdr switches back to on uninstall (and after --activate bounce)
FALLBACK_LAYOUT="${VAULTR_FALLBACK_LAYOUT:-main}"

ACTIVATE=0
UNINSTALL=0
LINK=0
RESET=0

for arg in "$@"; do
  case "$arg" in
    --activate)
      ACTIVATE=1
      ;;
    --link)
      LINK=1
      ;;
    --reset-layout)
      RESET=1
      ;;
    --uninstall)
      UNINSTALL=1
      ;;
    -h|--help)
      echo "Usage: $0 [--activate | --uninstall | --link | --reset-layout]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--activate | --uninstall | --link | --reset-layout]" >&2
      exit 1
      ;;
  esac
done

# Mods under mods/ that are not ob-* but ship with Vaultr; linked like the ob-* mods
EXTRA_MODS="insights obsidian"

# Link mods/<name> into $HERDR_APP_DIR/mods. A symlink to another checkout's
# mods/<name> is replaced; a real folder or an unrecognised symlink is left alone.
link_extra_mod() {
  local name=$1
  local src="$REPO_DIR/mods/$name"
  local target="$HERDR_APP_DIR/mods/$name"
  [[ -d "$src" ]] || return 0
  if [[ -L "$target" ]]; then
    local dest
    dest=$(readlink -- "$target")
    if [[ "$dest" != */mods/"$name" ]]; then
      echo "skipped mod: $target is a symlink to $dest (not recognised); remove it to link $name" >&2
      return 0
    fi
    rm -f -- "$target"
  elif [[ -e "$target" ]]; then
    echo "skipped mod: $target is a real folder; move it aside to link $name" >&2
    return 0
  fi
  ln -sfn "$src" "$target"
  echo "linked mod: $target -> $src"
}

# Back up a layout copy next to itself before it is replaced: <file>.bak-<date-time>.
backup_layout() {
  local target=$1 stamp
  stamp=$(date +%Y%m%d-%H%M%S)
  cp -- "$target" "$target.bak-$stamp"
  echo "backed up: $target.bak-$stamp"
}

# Put layouts/<file> into the Herdr app folder as a copy. The copy is the person's arrangement once they move
# panels: a copy that differs from the repo is replaced when it still matches the last installed record, otherwise
# new nodes from the repo are added in place (unless --reset-layout, which backs it up and replaces it). An old
# symlink into this repo, or into another checkout's layouts/, becomes a copy of what it holds; a dangling one is
# replaced. --link symlinks the repo file instead (development).
# a Vaultr checkout has its installer and kit sync script at the top
is_checkout() { [[ -f "$1/install.sh" && -f "$1/kit/sync.sh" ]]; }

install_layout() {
  local file=$1
  local src="$REPO_DIR/layouts/$file"
  local target="$HERDR_APP_DIR/layouts/$file"
  local record="$HERDR_APP_DIR/vaultr-layout.installed.json"
  [[ -f "$src" ]] || return 0
  if [[ -L "$target" ]]; then
    local dest
    dest=$(readlink -- "$target")
    if [[ ! -e "$target" ]]; then
      # dangling (the repo was moved): nothing to keep
      rm -f -- "$target"
      echo "removed dangling layout link: $target -> $dest"
    elif [[ "$(resolve "$target")" == "$(resolve "$src")" ]]; then
      if [[ "$LINK" -eq 0 ]]; then
        cp -L -- "$target" "$target.tmp"
        mv -f -- "$target.tmp" "$target"
        echo "replaced the link to the repo with a copy: $target"
      fi
    elif [[ "$(resolve "$target")" == */layouts/"$file" ]] && is_checkout "$(dirname "$(dirname "$(resolve "$target")")")"; then
      # another Vaultr checkout's layout: keep the arrangement it holds as a copy, then go on as for any copy
      cp -L -- "$target" "$target.tmp"
      mv -f -- "$target.tmp" "$target"
      echo "replaced the link to another checkout ($dest) with a copy: $target"
    else
      echo "skipped layout: $target is a symlink to $dest (not recognised); remove it to install $file" >&2
      return 0
    fi
  fi
  if [[ "$LINK" -eq 1 ]]; then
    if [[ -f "$target" ]] && ! cmp -s -- "$src" "$target"; then
      backup_layout "$target"
    fi
    ln -sfn -- "$src" "$target"
    echo "linked layout: $target -> $src"
    if [[ "$file" == "vaultr.json" ]]; then
      rm -f -- "$record"
    fi
    return 0
  fi
  if [[ "$file" != "vaultr.json" ]]; then
    if [[ ! -e "$target" ]]; then
      cp -- "$src" "$target"
      echo "copied layout: $target"
    elif ! cmp -s -- "$src" "$target"; then
      cp -- "$src" "$target"
      echo "updated layout: $target"
    fi
    return 0
  fi
  if [[ ! -e "$target" ]]; then
    cp -- "$src" "$target"
    echo "copied layout: $target"
  elif cmp -s -- "$src" "$target"; then
    :
  elif [[ "$RESET" -eq 1 ]]; then
    backup_layout "$target"
    cp -- "$src" "$target"
    echo "replaced layout with the repo's: $target"
  elif [[ -f "$record" ]] && cmp -s -- "$record" "$target"; then
    cp -- "$src" "$target"
    echo "updated layout: $target (unchanged since the last install)"
  else
    rm -f -- "$target.tmp"
    local merge_out
    merge_out=$(python3 - "$src" "$target" "$record" "$target.tmp" <<-'PY'
import copy, json, os, sys

src_path, dst_path, rec_path, out_path = sys.argv[1:5]
with open(src_path, "r", encoding="utf-8") as f:
    repo = json.load(f)
try:
    with open(dst_path, "r", encoding="utf-8") as f:
        user = json.load(f)
except Exception:
    print(f"kept your layout: {dst_path} differs from the repo (pass --reset-layout to replace it, after a backup)")
    sys.exit(0)

rec = None
if rec_path and os.path.isfile(rec_path):
    try:
        with open(rec_path, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        rec = None


def collect_ids(node):
    ids = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            nid = n.get("id")
            if isinstance(nid, str) and nid:
                ids.add(nid)
            kids = n.get("children")
            if isinstance(kids, list):
                stack.extend(kids)
    return ids


def find_node(node, nid):
    if not isinstance(node, dict):
        return None
    if node.get("id") == nid:
        return node
    for c in node.get("children") or []:
        hit = find_node(c, nid)
        if hit is not None:
            return hit
    return None


def prune_existing(node, existing_ids):
    out = copy.deepcopy(node)

    def strip(n):
        kids = n.get("children")
        if not isinstance(kids, list):
            return
        kept = []
        for c in kids:
            cid = c.get("id") if isinstance(c, dict) else None
            if isinstance(cid, str) and cid in existing_ids:
                continue
            strip(c)
            kept.append(c)
        n["children"] = kept

    strip(out)
    return out


orig_copy_ids = collect_ids(user)
copy_ids = set(orig_copy_ids)
rec_ids = collect_ids(rec) if rec is not None else set()

added = []
not_added = []


def walk_stripped_existing(node):
    if not isinstance(node, dict):
        return
    for c in node.get("children") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if isinstance(cid, str) and cid in orig_copy_ids:
            walk_repo(c)
        else:
            walk_stripped_existing(c)


def walk_repo(node):
    if not isinstance(node, dict):
        return
    parent_id = node.get("id")
    kids = node.get("children")
    if not isinstance(kids, list):
        return
    for idx, child in enumerate(kids):
        if not isinstance(child, dict):
            continue
        cid = child.get("id")
        if isinstance(cid, str) and cid and cid not in copy_ids and cid not in rec_ids:
            target_parent = find_node(user, parent_id) if isinstance(parent_id, str) and parent_id else None
            if target_parent is None:
                not_added.append((cid, parent_id or ""))
            else:
                subtree = prune_existing(child, copy_ids)
                prev_id = None
                if idx > 0 and isinstance(kids[idx - 1], dict):
                    pid = kids[idx - 1].get("id")
                    if isinstance(pid, str) and pid:
                        prev_id = pid
                dest_kids = target_parent.get("children")
                if not isinstance(dest_kids, list):
                    dest_kids = []
                    target_parent["children"] = dest_kids
                pos = None
                if prev_id is not None:
                    for j, dk in enumerate(dest_kids):
                        if isinstance(dk, dict) and dk.get("id") == prev_id:
                            pos = j + 1
                            break
                if pos is None:
                    dest_kids.append(subtree)
                else:
                    dest_kids.insert(pos, subtree)
                copy_ids.update(collect_ids(subtree))
                added.append((cid, parent_id))
            walk_stripped_existing(child)
        else:
            walk_repo(child)


walk_repo(repo)

if added:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(user, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for cid, pid in added:
        print(f"added to your layout: {cid} (in {pid})")
    for cid, pid in not_added:
        print(f"not added: {cid} (your layout has no {pid}; --reset-layout takes the repo's layout, after a backup)")
elif not_added:
    for cid, pid in not_added:
        print(f"not added: {cid} (your layout has no {pid}; --reset-layout takes the repo's layout, after a backup)")
else:
    print(f"kept your layout: {dst_path} differs from the repo (pass --reset-layout to replace it, after a backup)")
PY
)
    if [[ -f "$target.tmp" ]]; then
      backup_layout "$target"
      mv -f -- "$target.tmp" "$target"
    fi
    if [[ -n "$merge_out" ]]; then
      printf '%s\n' "$merge_out"
    fi
    warn_missing_mods "$target"
  fi
  if ! cmp -s -- "$src" "$record" 2>/dev/null; then
    cp -- "$src" "$record"
  fi
}

# Warn when a kept layout copy names a mod that is neither in this repo, nor in the app's mods folder, nor one of
# Herdr's shipped mods (e.g. a mod since removed from Vaultr): that block would show an error.
warn_missing_mods() {
  [[ "$1" == *.json ]] || return 0
  python3 - "$1" "$REPO_DIR/mods" "$HERDR_APP_DIR/mods" <<-'PY'
import json, os, sys

layout, repo_mods, app_mods = sys.argv[1], sys.argv[2], sys.argv[3]
SHIPPED = {"files", "changes"}
try:
    with open(layout) as f:
        data = json.load(f)
except Exception:
    sys.exit(0)
names = set()
stack = [data]
while stack:
    x = stack.pop()
    if isinstance(x, dict):
        if isinstance(x.get("mod"), str):
            names.add(x["mod"])
        stack.extend(x.values())
    elif isinstance(x, list):
        stack.extend(x)
missing = sorted(n for n in names if n not in SHIPPED and "/" not in n
                 and not os.path.isdir(os.path.join(repo_mods, n)) and not os.path.isdir(os.path.join(app_mods, n)))
if missing:
    print(f"warning: your layout {layout} names mods that are not installed: {', '.join(missing)} "
          "(pass --reset-layout to take the repo's layout, after a backup)", file=sys.stderr)
PY
}

# Remove an installed layout copy. Unchanged from the repo or the last installed record, or --reset-layout
# (backed up first), removes it; a differing copy is the person's and stays.
uninstall_layout() {
  local file=$1
  local src="$REPO_DIR/layouts/$file"
  local target="$HERDR_APP_DIR/layouts/$file"
  local record="$HERDR_APP_DIR/vaultr-layout.installed.json"
  if [[ -L "$target" ]]; then
    rm -f -- "$target"
    echo "removed layout: $target"
  elif [[ -f "$target" ]]; then
    if cmp -s -- "$src" "$target" || { [[ "$file" == "vaultr.json" && -f "$record" ]] && cmp -s -- "$record" "$target"; }; then
      rm -f -- "$target"
      echo "removed layout: $target"
    elif [[ "$RESET" -eq 1 ]]; then
      backup_layout "$target"
      rm -f -- "$target"
      echo "removed layout (backed up): $target"
    else
      echo "left your layout: $target differs from the repo (pass --reset-layout to remove it, after a backup)"
    fi
  fi
}

if [[ "$UNINSTALL" -eq 1 ]]; then
  echo "Uninstalling Vaultr..."

  # 1. Remove vaultr layout files (and any legacy obsidian layout files) and ob-* mods
  for file in "vaultr.json" "vaultr.svg"; do
    uninstall_layout "$file"
  done
  rm -f -- "$HERDR_APP_DIR/vaultr-layout.installed.json"
  for file in "obsidian.json" "obsidian.svg"; do
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

  # Remove only symlinks that point at a mods/<name> folder; real folders are kept
  for name in $EXTRA_MODS; do
    target="$HERDR_APP_DIR/mods/$name"
    if [[ -L "$target" && "$(readlink -- "$target")" == */mods/"$name" ]]; then
      rm -f -- "$target"
      echo "removed mod: $target"
    elif [[ -L "$target" || -e "$target" ]]; then
      echo "left alone: $target (not a Vaultr link)"
    fi
  done

  # 2. Remove the keys Vaultr installed (recorded in vaultr-keys.owned.json) and the legacy obsidian section;
  #    a key the person added to a Vaultr section stays. Without a record, the repo's keys sections go as before.
  if [[ -f "$HERDR_APP_DIR/keys.json" ]]; then
    python3 - "$HERDR_APP_DIR/keys.json" "$HERDR_APP_DIR/vaultr-keys.owned.json" "$REPO_DIR/keys/vaultr-keys.json" <<-'PY'
import json, os, sys

keys_file, owned_file, src_file = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(keys_file, "r") as f:
        keys = json.load(f)
except Exception:
    sys.exit(0)
owned = {}
if os.path.exists(owned_file):
    try:
        with open(owned_file, "r") as f:
            owned = json.load(f)
    except Exception:
        owned = {}
repo_keys = {}
if os.path.exists(src_file):
    try:
        with open(src_file, "r") as f:
            repo_keys = json.load(f)
    except Exception:
        repo_keys = {}

sections = [k for k in owned if k != "_removed" and isinstance(owned[k], list)]
for k in repo_keys:
    if k != "_removed" and k not in owned and isinstance(repo_keys[k], dict):
        sections.append(k)

modified = False
if "layout:obsidian" in keys:
    del keys["layout:obsidian"]
    modified = True
for k in sections:
    if k not in keys:
        continue
    if k in owned:
        if isinstance(keys[k], dict):
            for key in owned[k]:
                keys[k].pop(key, None)
        if not keys[k]:
            del keys[k]
    else:
        del keys[k]
    modified = True

if modified:
    with open(keys_file, "w") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")
if os.path.exists(owned_file):
    os.remove(owned_file)
PY
    echo "removed vaultr keybindings from $HERDR_APP_DIR/keys.json"
  else
    rm -f -- "$HERDR_APP_DIR/vaultr-keys.owned.json"
  fi

  # 3. Switch layout back to the fallback layout
  herdr-app do layout.switch --name "$FALLBACK_LAYOUT" >/dev/null 2>&1 || true
  echo "switched layout -> $FALLBACK_LAYOUT"
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

# 2. Copy the layout into the app folder (see install_layout)
for file in "vaultr.json" "vaultr.svg"; do
  install_layout "$file"
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

# 3a. Prune links into this repo whose mod was removed from it (a dangling link would show as a broken mod)
for target in "$HERDR_APP_DIR"/mods/*; do
  [[ -L "$target" ]] || continue
  name=$(basename -- "$target")
  dest=$(readlink -- "$target")
  dest=${dest%/}
  if [[ "$dest" == "$REPO_DIR/mods/$name" && ! -e "$dest" ]]; then
    rm -f -- "$target"
    echo "removed link to removed mod: $target"
  fi
done

# 3b. Symlink the non-ob-* mods shipped in mods/
for name in $EXTRA_MODS; do
  link_extra_mod "$name"
done

# 4. Merge vaultr keybindings into keys.json and clean up stale layout:obsidian.
#    Vaultr owns only the keys it installed (recorded in vaultr-keys.owned.json): a key dropped from the repo file is
#    removed, and a key the person added to the same section is kept. A section with no record (first install, or an
#    install from before the record existed) is replaced as a whole, as before.
if [[ -f "$REPO_DIR/keys/vaultr-keys.json" ]]; then
  python3 - "$REPO_DIR/keys/vaultr-keys.json" "$HERDR_APP_DIR/keys.json" "$HERDR_APP_DIR/vaultr-keys.owned.json" "$VAULTR_OS" <<-'PY'
import json, os, re, sys

src_file, dst_file, owned_file, os_name = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]


def for_platform(chord):
    """The repo's keys are written with Ctrl; macOS gets Cmd in its place, stroke by stroke (platform_keys.js)."""
    if os_name != "Darwin":
        return chord
    out = []
    for stroke in chord.split(" "):
        m = re.match(r"^((?:[a-z]+-)*)(.+)$", stroke)
        if m and m.group(1):
            stroke = "-".join("cmd" if w == "ctrl" else w for w in m.group(1).split("-")) + m.group(2)
        out.append(stroke)
    return " ".join(out)
keys = {}
if os.path.exists(dst_file):
    try:
        with open(dst_file, "r") as f:
            keys = json.load(f)
    except Exception as e:
        print(f"Warning: could not read {dst_file}: {e}", file=sys.stderr)
owned = {}
if os.path.exists(owned_file):
    try:
        with open(owned_file, "r") as f:
            owned = json.load(f)
    except Exception:
        owned = {}

# Clean up stale layout:obsidian
keys.pop("layout:obsidian", None)

with open(src_file, "r") as f:
    vaultr_keys = json.load(f)

# "_removed" in the record: per section, the Vaultr chords the person deleted (they were installed, and are gone from
# keys.json). They are not put back. Older records have no "_removed". Uninstall deletes the record, so a fresh install
# brings every key back (also what to do after restoring an old keys.json).
removed = dict(owned.get("_removed", {}))
new_owned = dict(owned)
sections = [k for k in vaultr_keys if k != "_removed" and isinstance(vaultr_keys[k], dict)]
for k in owned:
    if k != "_removed" and k not in vaultr_keys and isinstance(owned[k], list):
        sections.append(k)
for k in sections:
    if k in vaultr_keys:
        repo = {for_platform(key): val for key, val in vaultr_keys[k].items()}
        if k in owned:
            cur = {key: val for key, val in keys.get(k, {}).items() if key not in owned[k] or key in repo}
            # a chord the person bound themselves (in the section, not installed by Vaultr) is theirs: leave it
            theirs = {key for key in repo if key in cur and key not in owned[k]}
            # a chord Vaultr installed that is gone from keys.json was deleted by the person (Settings > Hotkeys drops the
            # whole section with its last key); one it had removed before stays out, unless it is back
            gone = set(removed.get(k, [])) & set(repo)
            gone |= {key for key in owned[k] if key in repo and key not in keys.get(k, {})}
            gone -= set(cur)
            # a removed chord that is back with Vaultr's own action (Hotkeys > restore) is Vaultr's again
            theirs -= {key for key in removed.get(k, []) if key in cur and cur[key] == repo.get(key)}
        else:
            cur = {}
            theirs = set()
            gone = set()
        for key in sorted(key for key in theirs if cur[key] != repo[key]):
            print(f"kept your key: {k} {key} = {cur[key]} (Vaultr's {repo[key]} not installed)")
        for key in sorted(gone):
            print(f"left out the key you removed: {k} {key} (uninstall, then install, brings it back)")
        cur.update({key: val for key, val in repo.items() if key not in theirs and key not in gone})
        if cur:
            keys[k] = cur
        else:
            keys.pop(k, None)
        new_owned[k] = sorted(key for key in repo if key not in theirs and key not in gone)
        if gone:
            removed[k] = sorted(gone)
        else:
            removed.pop(k, None)
    else:
        if isinstance(keys.get(k), dict):
            cur = {key: val for key, val in keys[k].items() if key not in owned[k]}
            if cur:
                keys[k] = cur
            else:
                keys.pop(k, None)
        new_owned.pop(k, None)
        removed.pop(k, None)
if removed:
    new_owned["_removed"] = removed
else:
    new_owned.pop("_removed", None)

with open(dst_file, "w") as f:
    json.dump(keys, f, indent=2)
    f.write("\n")
with open(owned_file, "w") as f:
    json.dump(new_owned, f, indent=2)
    f.write("\n")
PY
  echo "merged keybindings into $HERDR_APP_DIR/keys.json"
fi

# 5. Activate if requested
if [[ "$ACTIVATE" -eq 1 ]]; then
  # Bounce layout through the fallback to force full reload if vaultr was already active
  herdr-app do layout.switch --name "$FALLBACK_LAYOUT" >/dev/null 2>&1 || true
  herdr-app do layout.switch --name vaultr >/dev/null 2>&1 || true
  echo "activated layout -> vaultr"
fi

echo "Vaultr installation complete."
