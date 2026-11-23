# Develop

```text
layouts/vaultr.json          the Herdr layout: four side stacks + center column + 0 px background scanner
layouts/vaultr.svg           layout preview icon
keys/vaultr-keys.json        default keybindings (layout:vaultr, mod:ob-sessions); ctrl maps to cmd on macOS
kit/                         shared mod foundation: kit.js, provider.js, pure rule modules, icons/, sync.sh
mods/ob-*/                   the 19 Vaultr mods (each gets synced copies of kit/*.js and kit/icons/*.svg)
mods/ob-feed/providers/      agent provider folders (<id>/{manifest.json,scan.py,reader.py[,quota.py]}) + index.json
mods/insights/               usage dashboard over local coding-agent transcripts (Node indexer)
mods/obsidian/               Notes panel and daily notes against a configured Obsidian vault
install.sh                   installer, layout updater, key merger, activator, and uninstaller
test/                        Python unittest suite (home_guard.py isolates HOME and HERDR_APP_HOME)
```

## Rules

- **Kit is the single source**: edit `kit/kit.js`, `kit/*.js`, or `kit/icons/`, then run `./kit/sync.sh`. Never edit a
  mod's synced copies directly.
- **Provider boundary**: all provider discovery, Python assembly, script execution, and feed-bucket reads live in
  `kit/provider.js` and `mods/ob-feed/providers/`. Other `kit/*.js` and `mods/ob-*` files never name a provider, invoke
  `python3`/`bash`/`sh`/`node`, or read raw `ob.subagents` buckets (`test/test_provider_boundaries.py`).
- **Draggable panels**: look up views strictly by layout `id` or `mod` name (`findNode`, `stackOf`, `viewInfo`,
  `isShown`, `openPlan`), never by stack id or child index (`test/test_layout.py`).
- **Shared vs panel-local state**: cross-panel state (`ob.hidden`, `ob.dismissed`, `ob.history`, `ob.settings`,
  `ob.bookmarks`, `ob.subagents`, `ob.quotas`) lives in Herdr's `shared` only (`test/test_kit_shared.py`). Panel-local
  view state uses `lsGet`/`lsSet` (`localStorage`). Never call `setShared` inside `render` or state getters.
- **Always-running `0 px` blocks**: keep them explicit and outside hideable nodes
  (`test_always_running_blocks_stay_visible_and_are_explicit` in `test/test_layout.py`, currently `{"ob-feed-scan"}`).
- **Nothing personal**: no personal paths, names, e-mail addresses, host names, or internal-only tool names in code,
  tests, or docs (`test/test_repo.py`). Every external file read or command run by a mod is listed in `README.md`.
- **Commits and tests**: Conventional Commits (`type(scope): description`). For any bug fix, add a failing test first,
  then fix the bug until green.

Detailed checklists for adding a new panel or provider are in [AGENTS.md](../AGENTS.md) and [README.md](../README.md).

## Where data lives

- **Herdr app folder**: `~/.config/herdr-app` (or `$HERDR_APP_HOME`).
  - `layouts/vaultr.json`: user's own editable copy of the layout (never linked unless `./install.sh --link` is used).
  - `vaultr-layout.installed.json`: snapshot of the last installed repo layout, used by `install.sh` to update untouched
    copies in place and insert new repo nodes into customized copies without restoring deleted panels.
  - `vaultr-keys.owned.json`: tracks Vaultr-managed chords in `keys.json` so user edits and removals survive reinstall.
  - `obsidian.json`: user's Obsidian vault path (set in Settings → Vault).
  - `feedback.json`: user's feedback bundle folder (set in Settings → Feedback); staged captures use `data/ob-feedback/`.
  - `antigravity.json` (optional): local overrides (`dir`, `bin`, `name`, `apps`, `bins`) for `providers/antigravity/quota.py`.
  - `shared.json`: Herdr-persisted cross-panel `shared` state.
  - Never edit `~/.config/herdr-app/layouts/.state/`.
- **Test isolation**: every file in `test/` imports `home_guard` first, pointing `HOME` and `HERDR_APP_HOME` at a temp
  folder with a stub `herdr-app` that only logs calls.

## Checks

Run the targeted test file(s) for what you touched, plus `herdr-app check` on modified mods. The full list below
matches `.github/workflows/check.yml` and should pass before tagging a release:

```bash
# Sync kit copies after any kit/ edit
./kit/sync.sh

# Validate JSON manifests, layout, and keys
for f in layouts/*.json keys/*.json mods/*/mod.json; do python3 -m json.tool "$f" >/dev/null; done

# Check individual mods in Herdr
herdr-app check mods/<name>

# Targeted test file
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s test -p 'test_layout.py'

# Full test suite (940+ tests, no Herdr window needed)
PYTHONDONTWRITEBYTECODE=1 python3 -W error::ResourceWarning -m unittest discover -s test

# Installer smoke test in a scratch folder
app_dir="$(mktemp -d)" && HERDR_APP_HOME="$app_dir" ./install.sh && HERDR_APP_HOME="$app_dir" ./install.sh --uninstall && rm -rf "$app_dir"
```

## Trying a change

- `install.sh` symlinks `mods/*` into `~/.config/herdr-app/mods/`, so editing a mod file reloads live in Herdr. If a
  change does not appear, bounce the layout:
  ```bash
  herdr-app do layout.switch --name main && herdr-app do layout.switch --name vaultr
  ```
- To test edits to `layouts/vaultr.json` live, symlink it temporarily (backs up any customized copy first):
  ```bash
  ./install.sh --link
  # afterwards, return to a normal copy:
  ./install.sh
  ```
- Inspect live mod/layout errors with `herdr-app status` (a broken mod keeps the last good version and writes
  `<name>.error`).
- Never start a second `herdr-app` window, and never run `herdr-app` or `install.sh` with a changed `HOME`. Use
  `HERDR_APP_HOME=<scratch> ./install.sh` to test installer behaviour safely.

## Releasing

1. Move entries under `## Unreleased` in [CHANGELOG.md](../CHANGELOG.md) into a new `## X.Y.Z` section.
2. Run the full checks above on a clean `main`.
3. Commit the changelog update, create an annotated tag, and push:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --follow-tags
   ```
