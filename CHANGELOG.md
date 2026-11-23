# Changelog

## 0.1.0

### Added

- **Antigravity plan-quota collector (`mods/ob-feed/providers/antigravity/quota.py`, `manifest.json`)**:
  Adds `"quota"` capability to the Antigravity provider, verifying the state
  directory and binary markers before running `<binary> -p /usage --output-format json`,
  supporting `$ANTIGRAVITY_CLI_DIR` / `$ANTIGRAVITY_BIN` and optional
  `antigravity.json` overrides in the Herdr app folder, with unit tests in
  `test/test_provider_antigravity.py`.
- **Developer guide (`docs/develop.md`)**: Documents repository layout,
  architectural rules, data paths, check commands, live testing, and release
  tagging.
- **Feedback bundles (`mods/ob-feedback/`, `kit/feedback_bundle.js`, `mods/ob-settings/feedback.js`, `ob-tabs`, `ob-footer`, `keys/vaultr-keys.json`)**:
  Captures an unobstructed window screenshot (`herdr-app shot`), annotated UI
  tree dump, and sanitized diagnostics (`data/ob-feedback/`) before opening
  the Markdown feedback dialog (`Ctrl+Alt+Shift+F`, Command Palette, or
  footer button), writes `<timestamp>-<slug>/` bundle folders (`feedback.md`,
  `screenshot.png`, `ui-tree.json`, `diagnostics.log`) into the folder
  configured in Settings' **Feedback** tab (`feedback.json`), and adds unit
  and end-to-end tests (`test/test_ob_feedback.py`, `test/test_ob_settings.py`).
- **Installed-layout record and node delivery (`install.sh`)**: Records the
  installed `layouts/vaultr.json` in `vaultr-layout.installed.json` (next to
  `vaultr-keys.owned.json`), updates untouched copies in place, and adds new
  repo nodes to changed copies without restoring user-deleted panels or
  duplicating moved views (`test/test_install.py`).
- **Layout, reference, and shared-state tests (`test/test_layout.py`, `test/test_keys.py`, `test/test_references.py`, `test/test_repo.py`, `test/test_kit_shared.py`)**:
  Verifies `VIEWS` and `NODE` alignment, view resolution by id across
  rearranged stacks, explicit `0 px` always-running blocks, bidirectional
  Hotkeys/keys default agreement, static import/re-export/icon/command
  resolution, untracked non-ignored file scanning in `tracked()`, and
  `shared`-only cross-panel state.
- **Panel-authoring guide (`AGENTS.md`)**: Documents panel registrations and
  guarding tests, draggable-view lookup, `0 px` always-running blocks and
  polling rules, `shared` vs `localStorage` state, and host I/O boundaries.
- **Check workflow (`.github/workflows/check.yml`)**: Validates
  `layouts/*.json`, `keys/*.json`, and `mods/*/mod.json`, runs the Python test
  suite with `ResourceWarning` treated as an error (which also compares kit
  copies against `kit/` in `test/test_repo.py`), and smoke-tests `install.sh`
  install and uninstall in GitHub Actions.
- **Notices and third-party license texts (`NOTICE`, `LICENSE-herdr`, `LICENSE-shepherdr`)**:
  Adds root attribution notices with Apache-2.0 (`LICENSE-herdr`) for
  Herdr-derived code in `mods/ob-agents`, `mods/ob-sessions`,
  `mods/ob-settings/registry_rules.js`, and `mods/ob-switcher/commands.js`, and
  MIT (`LICENSE-shepherdr`) for Shepherdr-derived code in
  `mods/ob-feed/providers/claude/quota.py`.
- **Needs-you dismissals (`kit/attention.js`, `ob-agents`, `ob-status`, `ob-strip`, `ob-sessions`, `ob-bookmarks`)**:
  Adds `ob.dismissed` stamp rules and Dismiss/Restore controls in Agents so
  acknowledged blocked or failed sessions clear from attention counts until their
  status or turn changes.
- **Provider folders and facade (`mods/ob-feed/providers/`, `kit/provider.js`)**:
  Splits Claude Code and pi scanner and transcript readers into per-provider
  folders listed in `providers/index.json` behind `kit/provider.js` (`list`,
  `of`, `sessions`, `session`, `subagents`, `transcript`, `usage`, `search`,
  `quota`, `scan`, `dropCache`), upgrades `ob.subagents` to version 2 with a
  neutral `subagents` bucket, and counts a live parent terminal with an active
  sub-agent record as working or blocked.
- **Recent prompts (`mods/ob-feed/providers/`, `ob-pane`, `layouts/vaultr.json`)**:
  Derives recent human prompts from normalized reader events for providers with
  the `prompts` capability and shows a latest-prompt row in the pane header that
  opens a prompt history dialog (`Copy`, `Copy latest`, `Transcript`, and
  `Escape` to close).
- **Quotas panel (`mods/ob-quotas/`, `mods/ob-feed/providers/claude/quota.py`, `layouts/vaultr.json`)**:
  Adds the Quotas panel at the top of the right sidebar stack, reading Claude
  Code plan limits in a read-only sandbox through `provider.quota()`, following
  the active session's pool, and keeping the last good read in `ob.quotas` when a
  refresh fails.
- **Antigravity provider (`mods/ob-feed/providers/antigravity/`)**: Adds session
  discovery from open `presence/<id>.lock` descriptors, read-only SQLite titles
  from `conversation_summaries.db`, and transcript viewing from
  `transcript.jsonl` under `~/.gemini/antigravity-cli`.
- **Documentation (`RECIPE.md`, `CHANGELOG.md`, `README.md`, `AGENTS.md`)**: Adds
  the Herdr six-part recipe brief, this changelog, the agent program support
  table, and instructions for adding a provider on Herdr `0.1.16`+.

### Changed

- **Shared-only cross-panel state (`kit/kit.js`, `mods/ob-sessions/`, `mods/ob-tabs/`)**:
  Stores `ob.hidden`, `ob.dismissed`, and `ob.history` in `shared` only without
  `localStorage` mirrors or getter `setShared` writes (keeping only the one-time
  `machines.hidden` and settled-tab migration in `ob-sessions` `init`).
- **Rule-based kit sync (`kit/sync.sh`, `test/test_repo.py`)**: Syncs every
  `kit/*.js` module into `mods/ob-*` (except `ob-probe`) by rule—filling `MOD`
  in `kit.js` and copying `obc.js` only where own files import `./obc.js`.
- **Dynamic keys section handling (`install.sh`)**: Merges and uninstalls
  every section in `keys/vaultr-keys.json` or `vaultr-keys.owned.json` rather
  than listing sections by hand.
- **Shared `obc.js` sync (`kit/obc.js`, `kit/sync.sh`)**: Manages `obc.js` from
  `kit/` across `ob-graph`, `ob-outline`, and `ob-props`, and replaces dangling
  external spec comments with repository references.
- **Graph styling and ring layout (`mods/ob-graph/`)**: Restyles graph nodes as
  round accent dots with cutout borders and lit hover links, places the force
  layout in concentric rings from a common center, culls overlapping labels, adds
  a `Local` depth toggle, and hides an empty local root node.
- **Pane and tab titles (`kit/names.js`, `ob-pane`, `ob-agents`, `ob-switcher`, `ob-tabs`)**:
  Shows session titles on shell-wrapped agent panes and routes pane and tab
  labels through `paneLabelOf` and `cleanTitle`.
- **Session hiding (`kit/hidden.js`, `mods/ob-sessions/`)**: Unifies Hide
  (`ob.hidden`) across machines, spaces, and tabs in Sessions.
- **Status bar overview (`mods/ob-status/`, `layouts/vaultr.json`)**: Simplifies
  the status bar to a right-aligned agent attention overview, feed scanner alert
  icon, and non-default zoom reset button.

### Fixed

- **macOS installer tests (`test/test_install.py`)**: Default `VAULTR_OS=Linux`
  in `run()` and canonicalize symlink targets with `os.path.realpath()` so the
  full test suite passes natively on macOS as well as Linux.
- **Layout table cleanup (`kit/kit.js`)**: Drops unused `NODE.feed` and
  `NODE.statusRow` entries.
- **Settings default hotkey (`mods/ob-settings/registry.js`)**: Adds the `Open
  settings` (`ctrl-,`) default entry to `OB`.
- **Target checks for panel and layout commands (`test/test_repo.py`)**: Checks
  `ob-tabs.open:` and `ob-tabs.toggle:` targets (before `@`) against layout
  stack child ids and `layout.toggle:` targets against layout node ids across
  `keys/vaultr-keys.json`, `OB`, and `VAULTR_COMMANDS`.
- **Missing-panel warning toast (`mods/ob-tabs/main.js`, `mods/ob-tabs/open.js`, `test/test_ob_tabs.py`)**:
  Decides via pure `openPlan` before mutating Zen or layout state and posts a
  warning toast via `notify()` when a panel is missing from the layout.
- **Open test files and `on_mouse_down` button argument (`test/`, `kit/kit.js`, `mods/ob-*`)**:
  Closes files opened in tests so the suite runs cleanly under
  `-W error::ResourceWarning`, and removes the `on_mouse_down` prototype patch by
  passing the explicit mouse button at each call site.
- **Graph follow and sub-agent liveness (`kit/obc.js`, `mods/ob-graph/`)**:
  Aligns `obc.js` follow-target and sub-agent liveness rules with Outline.
- **Outline Attach, Detach, child trees, and transcript scroll (`mods/ob-outline/`, `ob-pane`, `ob-tabs`)**:
  Enables remote child terminal Attach and child terminal transcripts, adds
  Detach to park panes in the background without ending the program, focuses the
  Attach header on open so `Escape` detaches, scopes `This tab` strictly to
  active-tab panes, nests `hc` child subtrees by `parent` with a button to reveal
  the main tab, opens transcripts scrolled to the end, shows sub-agent record
  messages and working child tools, hides empty record transcripts and redundant
  Go buttons, and shortens the home folder to `~` in pane rows.
- **Switcher, Hotkeys, and overlay key contexts (`ob-switcher`, `ob-settings`, `ob-menu`, `ob-sessions`, `ob-strip`)**:
  Lists runnable Vaultr and parameterized Herdr commands in the switcher, drops
  bare argument-required actions and normalizes chords in Hotkeys, caches `canon`
  and `effectivePairs` in Hotkeys, prefers `cmd` chords and `cmd-backspace` on
  macOS, gates worktree menu items on `hasMod("worktree")`, and binds overlay
  keys through `key_context` (`ObSwitcher`, `ObSettings`, `ObMenu`).
- **macOS traffic-light insets (`kit/lights.js`, `ob-strip`, `ob-tabs`, `ob-pane`)**:
  Insets top-left bars and the top-left Zen-mode pane header to clear the macOS
  window buttons.
- **Provider process confirmation (`mods/ob-feed/providers/`)**: Confirms agent
  processes by program-owned on-disk or open-lock evidence rather than process
  name alone.
