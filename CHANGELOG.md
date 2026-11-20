# Changelog

## Unreleased

### Added

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
