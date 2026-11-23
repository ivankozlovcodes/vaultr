# Working on Vaultr

Vaultr is a Herdr layout (`layouts/vaultr.json`) plus the mods it shows (`mods/`), for the [Herdr](https://github.com/herdrdev/herdr-app) desktop app (requires Herdr `0.1.16` or newer).
The mods share one kit (`kit/`), keys are in `keys/`, and `install.sh` links everything into the Herdr app folder.
Quick-reference architecture, data paths, checks, and release workflow: [docs/develop.md](docs/develop.md).

The four side stacks: left top is Sessions, Search, Bookmarks (opens on Sessions). Left bottom is Agents, Recent
(opens on Agents). Right top is Quotas, Properties, Files, Changes, Insights, Notes (opens on Quotas). Right bottom is
Graph, Outline (opens on Graph). Outline is the one panel for what runs in each tab: its panes with their agents nested
under them (it replaced the Subagents panel).

## Tests

- Green tests mean no known bugs. If a bug is found, the tests were missing a case: first add a test that fails
  because of the bug (run it and see it fail), then fix the bug until it passes. Commit the test and the fix as
  `test: ...` then `fix: ...`, or together in one `fix:` commit; never the fix without the test.
- Whole suite (about 115 seconds across 910+ tests, no Herdr window needed): `python3 -m unittest discover -s test`
- One file: `python3 -m unittest discover -s test -p 'test_layout.py'`
- One class: `cd test && python3 -m unittest test_install.Install`
- Each test file imports `home_guard` first: HOME and HERDR_APP_HOME point at a temp folder, and `herdr-app` is a
  stub that only logs. Keep it that way.
- A mod's own check: `herdr-app check mods/<name>` (it loads the mod and reports errors). Run it after each mod change.
- Where a new test goes: layout rules (`VIEWS`/`NODE`, view resolution, always-running `0 px` blocks) in
  `test/test_layout.py`; mod manifests, kit copies, syntax (including untracked non-ignored files walked by
  `tracked()` before `git add`), key/palette target checks, and personal-data checks in `test/test_repo.py`;
  Hotkeys/keys agreement in `test/test_keys.py`; static imports, icons, and mod commands in `test/test_references.py`;
  `shared`-only cross-panel state in `test/test_kit_shared.py`; provider folder, boundary, facade, scanner, quota,
  and pinned-output rules in `test/test_provider_*.py` and `test/test_providers_pinned.py`; installer behaviour in
  `test/test_install.py`.

## Trying a change

- `install.sh` links `mods/` into `~/.config/herdr-app`, so a saved mod file is live: the window reloads it. If a
  save does not show, bounce the layout: `herdr-app do layout.switch --name main`, then
  `herdr-app do layout.switch --name vaultr`.
- `install.sh` copies `layouts/vaultr.json` into the app folder and records the installed repo layout in
  `vaultr-layout.installed.json` (next to `vaultr-keys.owned.json`, outside `layouts/`); the copy holds the person's
  arrangement (moving a panel writes it), so a saved repo layout is not live. On re-install, an untouched copy
  matching `vaultr-layout.installed.json` is updated in place when `layouts/vaultr.json` changes in the repo, and
  newly added repo nodes are inserted into a changed copy without restoring user-removed nodes or duplicating moved
  views (`--reset-layout` replaces a changed copy after a backup). To try a layout change, run `./install.sh --link`
  (symlinks it, backing up a differing copy first, and removes `vaultr-layout.installed.json`). A plain `./install.sh`
  afterwards turns the link back into a copy.
- `herdr-app status` shows errors. A bad layout or mod keeps the last good version and writes `<name>.error`.
- Never edit `~/.config/herdr-app/layouts/.state/`.
- Never start a second herdr-app window, and never run herdr-app or install.sh with a changed HOME. To try the
  installer, use a scratch folder: `HERDR_APP_HOME=<scratch> ./install.sh`.
- Herdr's shipped mods (`files`, `changes`) are read-only. Clone them to change them.

## Kit

- Edit `kit/kit.js` (and the helpers `kit/*.js`, `kit/icons/`) only, then run `kit/sync.sh`.
- `kit/sync.sh` copies every `kit/*.js` and `kit/icons/*.svg` into every `mods/ob-*` folder except `ob-probe` (`MOD`
  filled in `kit.js`; `obc.js` copied only into `ob-*` mods whose own files import `./obc.js`), so adding a kit
  module requires no edits to `kit/sync.sh` or `test/test_repo.py`.
- Never edit a mod's copy of `kit.js`, helper modules, or its icons: the next sync overwrites them.

## Adding a panel

- **Registrations and guarding tests**:
  - Create `mods/ob-<name>/{mod.json,main.js}` and run `./kit/sync.sh` (`test/test_repo.py` parses and scans untracked
    non-ignored files walked by `tracked()` before `git add`; `test/test_references.py` checks relative
    `import`/`export ... from` targets and bindings, string-literal icon names against `kit/icons/*.svg`, and Vaultr
    mod commands against `nextCommand(` loops and verb literals).
  - Add the stack child block in `layouts/vaultr.json` (`props.slot` set to the child `id`) and its entry in `VIEWS`
    of `kit/kit.js`, then run `./kit/sync.sh` (`test_view_tables_agree_with_the_layout` in `test/test_layout.py`
    checks stack children against `VIEWS` and `NODE` values against layout node ids;
    `test_side_stacks_hold_the_listed_panels` checks the shipped default side stacks).
  - For a hotkey or command: bind in `keys/vaultr-keys.json` and add the matching default row to `OB` (or `SESSIONS`)
    in `mods/ob-settings/registry.js` (`test_installed_keys_and_hotkeys_defaults_agree_both_ways` in
    `test/test_keys.py` checks both directions). Add palette entries to `VAULTR_COMMANDS` in
    `mods/ob-switcher/commands.js` and panel title mappings to `PANEL_NAMES` in `mods/ob-settings/keysfile.js` when
    applicable. Targets of `ob-tabs.open:` and `ob-tabs.toggle:` (before `@`) must be stack child ids in
    `layouts/vaultr.json`, and targets of `layout.toggle:` must be layout node ids (`test/test_repo.py`).
    `install.sh` merges and uninstalls every section in `keys/vaultr-keys.json` automatically without editing
    `install.sh`.
- **View lookup (draggable panels)**:
  - Identify views strictly by layout `id` or `mod` name (`findNode`, `stackOf`, `viewInfo`, `isShown` in `kit/kit.js`,
    and `openPlan` in `mods/ob-tabs/open.js` tested in `test/test_ob_tabs.py`), never by stack id, child index, or
    stack count
    (`test_views_resolve_wherever_they_sit` in `test/test_layout.py`). Never add checks that pin a user's layout
    arrangement.
- **Always-running blocks and performance**:
  - Herdr starts a stack child's mod instance only when its slot is first shown, then keeps its timers alive while
    hidden. Do not add hidden always-running copies casually: every `0 px` block must sit outside hideable nodes and
    be added deliberately to `expected_ids` in `test_always_running_blocks_stay_visible_and_are_explicit`
    (`test/test_layout.py`, currently `{"ob-feed-scan"}`), documenting what it polls and how often. Poll gently,
    call `setShared` only when data changes (each write re-renders all mounted mods), and never call `setShared` inside
    `render` or state getters.
- **State (`shared` vs `localStorage`)**:
  - Cross-panel state (`ob.hidden`, `ob.dismissed`, `ob.history`, `ob.settings`, `ob.bookmarks`, `ob.subagents`,
    `ob.quotas`) lives in `shared` only (persisted by Herdr `0.1.16` in `shared.json`; `test/test_kit_shared.py`),
    never mirrored in `localStorage`. Panel-local view settings use `lsGet` / `lsSet` (`localStorage`); because Herdr
    hashes non-empty block `props` into the store filename, changing a block's `props` in `layouts/vaultr.json`
    resets that panel's saved `localStorage` settings.
- **Host I/O and boundaries**:
  - `mods/ob-*` files (outside kit copies and `mods/ob-feed/providers/`) run no script interpreters (`python`,
    `python3`, `bash`, `sh`, `node`), name no agent providers, and read no raw feed buckets
    (`test/test_provider_boundaries.py`). Read local or remote files via Herdr's `readTextFile(path, { on })`, or
    expose agent-program data through `kit/provider.js`. List any new external files read or commands run in
    `README.md`.

## Adding a provider

- Put each agent program in its own folder under `mods/ob-feed/providers/<id>/` (`manifest.json`, `scan.py`,
  `reader.py`, and `quota.py` only when `"quota"` is in `caps`), add `"<id>"` to `mods/ob-feed/providers/index.json`
  (kept equal to the set of provider folders), and add synthetic JSONL fixtures under `test/fixtures/providers/<id>/`.
- `manifest.json` holds exactly `{ "id", "name", "noun", "caps" }`, with `caps` from the closed set `title`,
  `prompts`, `transcript`, `usage`, `search`, `touches`, `subagents`, `quota`.
- Keep all provider assembly, script execution, and feed-bucket reads inside `kit/provider.js` (`provider.*` facade).
  Mods and other `kit/*.js` files must never name a provider, invoke `python3` or provider scripts, or read raw feed
  buckets (`test/test_provider_boundaries.py`).
- Provider Python files must parse under Python 3.9, contain zero multi-line string literals (`"""` / `'''`), confirm
  processes by program-owned on-disk evidence in `confirm(proc)`, and stay under 100 KiB assembled
  (`test/test_provider_folders.py`). List any new external files read or commands run in `README.md`.

## Names

- Mod names, layout node ids, shared-state keys (`ob.settings`, `ob-settings.tab`) and `keys/` contexts
  (`layout:vaultr`, `mod:ob-sessions`) are what people's saved state and keys hang on. Change them with care,
  and say so in the commit message and the done summary.

## Sharing

- This repo is shared. No personal paths, names, e-mail addresses or host names in code, tests or docs.
- Anything a mod runs, or reads from outside its own folder, is listed in `README.md`.

## Commits

- Conventional Commits 1.0.0: `type(scope): description`. Types: feat, fix, docs, test, refactor, chore.
  Scope is the mod name, or `layout`, `install`, `kit` or `keys`.
- Atomic commits. Never push, and never merge to `main`, without the human's yes.
