# Vaultr

Vaultr is an Obsidian-inspired workspace layout and complete mod suite for the [Herdr](https://github.com/herdrdev/herdr-app) desktop app (requires Herdr `0.1.16` or newer). It transforms Herdr into a modular, keyboard-driven workbench featuring collapsible left and right sidebars, tab management, deep agent/subagent inspection, workspace graph visualization, quick switcher, and custom hotkey management.

## Repository Layout

- **`kit/`**: Shared mod foundation. Contains `kit.js` (reusable GPUI components, theme tokens, shell helpers, and SVG icons), `provider.js` (provider index loader, Python script assembly, and unified `provider.*` facade), `sync.sh` (tool to propagate `kit.js`, helper modules, and icons into each `mods/ob-*` folder), and pure rule modules (`agents.js`, `names.js`, `hidden.js`, `attention.js`, `follow_target.js`, `feed_age.js`, `feedback_bundle.js`, `ticker.js`, `fuzzy.js`, `touches.js`, `lights.js`, `obc.js`).
- **`layouts/`**: Herdr workspace layout specifications:
  - `vaultr.json`: A center column between two sidebars, each split into two stacks of tabs. Left top: Sessions, Search, Bookmarks. Left bottom: Agents, Recent. Right top: Quotas, Properties, Files, Changes, Insights, Notes. Right bottom: Graph, Outline.
  - `vaultr.svg`: Layout preview icon.
- **`mods/`**: The 21 mods: 19 Obsidian-style `ob-*` mods (including `mods/ob-feed/providers/` with `index.json`, `scan_core.py`, `reader_main.py`, and per-provider `<id>/` folders), plus `insights` and `obsidian` (origin in `mods/ORIGIN.md`).
- **`keys/`**: Keybinding configurations:
  - `vaultr-keys.json`: Custom keybinding definitions for `layout:vaultr` and `mod:ob-sessions`.
- **`install.sh`**: One-step installer, activator, and uninstaller.

---

## The 21 Vaultr Mods

The layout also uses Herdr's shipped `files` and `changes` mods.

### Chrome & Frame
- **`ob-strip`**: Side ribbons and stack tab strips with tab icons, collapse toggles, and window controls.
- **`ob-menu`**: Application popup menu with workspace actions, theme switcher, and layout controls.
- **`ob-tabs`**: Obsidian-style tab bar supporting drag reordering, pinned tabs, daily notes, and split shortcuts.
- **`ob-pane`**: Two-row terminal and pane header with directory breadcrumbs, status indicators, pane split/close buttons, and a sticky latest-prompt row that opens a full prompt history popup.
- **`ob-status`**: Bottom status bar displaying the visible agent attention overview, feed scanner alerts, and zoom level.
- **`ob-footer`**: Bottom toolbar in the left sidebar: the machine switcher, then feedback (`ob-tabs.feedback`), help, and a settings gear that opens `ob-settings`.

### Left Sidebar (Navigation & Sessions)
- **`ob-sessions`**: File explorer tree representing spaces, tabs, panes, and terminals with git status and context menus.
- **`ob-search`**: Fast workspace-wide search across terminals and agent transcripts. Terms are fuzzy: every word must match; a transcript hit opens its transcript.
- **`ob-bookmarks`**: Obsidian-style bookmarks manager for spaces, tabs, terminal sessions, and subagent runs.
- **`ob-agents`**: Live agent monitor grouped by status priority (Needs you, Done, Working, Idle) or space.
- **`ob-recent`**: Chronological activity timeline of tab visits and agent events (Today, Yesterday, Earlier).

### Right Sidebar (Inspection & Data)
- **`ob-quotas`**: Plan quota monitor for providers with `"quota"` capability (Claude Code 5-hour, weekly, and per-model windows; Antigravity model-group pools) on this computer or the followed/selected remote machine via `provider.quota()`, highlighting the active session's pool and keeping the last good read if a refresh fails.
- **`ob-feed`**: Background scanner assembled in memory from `mods/ob-feed/providers/` via `kit/provider.js` (Claude Code, pi, and Antigravity sessions, pi runs, Claude Code background agents, recent human prompts, and file/artifact touches from transcript tails and the `herdr-artifact` store, never file contents). Publishes `ob.subagents` (`v: 2`) and feeds the stateless working sub-agent record rollup.
- **`ob-outline`**: The active tab's panes, each with the agents that run in its terminal nested under it (`pi` runs, Claude Code agents, `hc` child terminals nested by Herdr's `parent`), with task trees, execution steps, tool call logs, and token metrics. "All" groups every machine by session, with unattached background terminals last.
  - A transcript or log opens scrolled to its end in a popup over the window. **Move to main window** in its header puts it in the main window as a pane.
  - **Attach** (the row button, or the context menu) opens a live `hc` child terminal in a popup you can watch and type into (focused on its header so `Esc` detaches until you click the terminal). **Detach** in its header (or a click outside the popup) closes the popup and leaves the terminal running in the background. **Move to main window** gives it a tab of its own.
  - A terminal that has a pane goes back to the background with **Detach to background** (the pane's `⋮` menu, a right-click on its Outline row, or on its tab when it is the tab's only pane); the header of a child terminal's pane shows a **Detach** button. Close pane ends the program; Detach does not.
  - Subagents never get a tab or pane by themselves: only **Move to main window** puts one on screen.
- **`ob-props`**: Detailed properties inspector for active terminals, including environment, git repo details, machine stats, and a Usage section for the followed Claude Code or pi session (tokens by kind, context in use, model, turns, subagents' output tokens).
- **`ob-graph`**: Interactive relationship graph visualizing connections between machines, spaces, terminals (the panes of one tab drawn as a small cluster), and subagents. Its layout and view follow Quartz v4's graph (MIT) on d3-force (ISC), vendored in `mods/ob-graph/vendor/`; notices in `mods/ob-graph/NOTICE.md`.
  - **Notes** and **Artifacts** (toolbar switches, off by default, kept per Local/Global view like Active only) add the files your agents touched. A note is a `.md` file in your vault, a small dot linked to each agent that touched it (a note two agents touched joins them). An artifact is a small dot for a `herdr-artifact` you published, or a file an agent wrote or created outside the vault. Reads outside the vault are not shown. Clicking a note opens it in the Notes viewer; an artifact opens with `herdr-artifact open`, a plain file in your editor.
  - What is read for this: the file paths and tool names in each agent's transcript tail (the same tail the feed reads; no file contents and no tool output are kept), the herdr-artifact store (`~/.herdr/artifacts`, or `~/.local/share/shepherdr/artifacts`, which records the terminal that published each artifact), and `obsidian.json` for the vault path (read only). Notes need the vault set; without one the Notes switch is off.
  - Never shown: anything in a `danger/` folder of the vault (the vault's rule: it holds credentials), a hidden folder or file in the vault (`.obsidian`, `.git`, `.trash`), attachments (images, PDFs) in the vault, and a note of another machine.
- **`insights`**: Usage dashboard over local coding-agent session transcripts (pi, Codex, opencode, Claude Code, Antigravity), indexed by a Node process.
- **`obsidian`**: `Notes` tab for browsing and editing notes in an Obsidian vault. The vault must be set once (Settings, Vault tab). There is no fallback to Obsidian's own vault: until one is set, the tab says "No vault set." and the daily-note command asks you to set it.

### Overlays & Dialogs
- **`ob-switcher`**: Quick switcher popup (`Ctrl+P`) for jumping between tabs/sessions. Three modes, shown in the header and cycled with Tab: Everything, Views (sidebar views only), and Commands (`Ctrl+Shift+P`, or `>` typed in any mode: Vaultr's commands and Herdr's app commands, one list).
- **`ob-feedback`**: Feedback dialog opened by `Ctrl+Alt+Shift+F`, the Command Palette (`Submit feedback`), or the footer feedback button. Before opening, `ob-tabs.feedback` captures a live window screenshot (`herdr-app shot`), annotated UI tree dump (`ui-tree.json`), and sanitized diagnostics (`diagnostics.log`) into `data/ob-feedback/`; editing and saving writes a timestamped `<timestamp>-<slug>/` bundle folder containing `feedback.md`, `screenshot.png`, `ui-tree.json`, and `diagnostics.log` inside the folder set in Settings (**Feedback** tab, `feedback.json`).
- **`ob-settings`**: Settings dialog, opened by the footer's gear or `Ctrl+,`, or `Ctrl+Alt+K` (which opens it on Hotkeys). Tabs down the left: **Vault** (the vault folder, saved to `obsidian.json` in the Herdr app folder; set it once. Unset means no vault: the Notes panel and daily notes are off, with no fallback to Obsidian's own vault. Daily notes follow Obsidian's own daily-notes settings in that vault, and the editor is `$VISUAL`, then `$EDITOR`, then vi), **Feedback** (the folder where feedback bundles are saved, stored under `folder` in `feedback.json` in the Herdr app folder; can also be chosen inline in `ob-feedback`), **Hotkeys**: every command with its keys, searchable, with a scope for each `keys.json` section, where you add, remove or restore keys. Its Layout sub-tab holds the window buttons setting and the plain-Ctrl keys the layout takes from terminal programs. **Herdr settings…** sits below the tabs and opens Herdr's own settings.

---

## Keybindings Reference

The tables say `ctrl`. On macOS `install.sh` binds `cmd` in its place (`cmd-p`, `cmd-shift-p`, `cmd-,` and so on), as Herdr's own macOS keys do, and the Hotkeys tab shows those as the defaults. Set `VAULTR_OS=Linux` to keep `ctrl` on a Mac.

### `layout:vaultr`

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `Ctrl+P` | `mod.open:ob-switcher` | Open Quick Switcher |
| `Ctrl+Shift+P` | `ob-tabs.switcher:commands` | Open the switcher in command mode: Vaultr's commands and Herdr's app commands (with `app.palette`, Herdr's own palette, as one entry) |
| `Ctrl+B` | `layout.toggle:ob-left` | Toggle Left Sidebar |
| `Ctrl+Shift+B` | `layout.toggle:ob-right` | Toggle Right Sidebar |
| `Ctrl+\` | `pane.split:right` | Split Pane Right |
| `Ctrl+Shift+\` / `Ctrl+\|` | `pane.split:down` | Split Pane Down |
| `Ctrl+Shift+E` | `ob-tabs.open:ob-sessions@reveal` | Reveal Active Session in Explorer |
| `Ctrl+Shift+M` | `ob-tabs.switcher:move` | Move Tab to Another Space |
| `Ctrl+Shift+C` / `Ctrl+Alt+C` | `ob-tabs.copy-path` | Copy Active Tab Path |
| `Ctrl+Shift+D` | `ob-tabs.daily` | Open / Focus Daily Session |
| `Ctrl+Shift+K` / `Ctrl+Alt+F` | `ob-tabs.open:ob-search` | Open Search in Left Sidebar |
| `Ctrl+Shift+G` | `ob-tabs.open:ob-graph` | Open Graph in Right Sidebar |
| `Ctrl+Shift+A` | `ob-tabs.toggle:ob-outline` | Toggle Outline |
| `Ctrl+Alt+O` | `ob-tabs.open:ob-outline` | Open Outline in Right Sidebar |
| `Ctrl+Alt+I` | `ob-tabs.open:ob-props` | Open Properties in Right Sidebar |
| `Ctrl+Alt+A` | `ob-tabs.open:ob-agents` | Open Agents in Left Sidebar |
| `Ctrl+Alt+B` | `ob-tabs.bookmark` | Bookmark Active Session / Tab |
| `Ctrl+Alt+Left` | `ob-tabs.back` | Navigate History Back |
| `Ctrl+Alt+Right` | `ob-tabs.forward` | Navigate History Forward |
| `Ctrl+9` | `ob-tabs.last` | Focus Last Tab |
| `Ctrl+Alt+K` | `ob-tabs.settings:hotkeys` | Open Settings on Hotkeys |
| `Ctrl+,` | `mod.open:ob-settings` | Open Vaultr Settings (Herdr's own settings: in the dialog) |
| `Ctrl+Alt+T` | `ob-tabs.tab-list` | Open Tab List Menu |
| `Ctrl+Alt+Shift+F` | `ob-tabs.feedback` | Submit Feedback Bundle |
| `Ctrl+Shift+Z` / `Ctrl+Alt+Z` | `ob-tabs.zen` | Toggle Zen Mode |

The settings dialog opens from the gear in the footer. `ob-tabs.settings:<tab>` opens it on a tab (`vault`, `feedback`, or `hotkeys`); with no tab, it opens on the tab used last.

### `mod:ob-sessions`

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `F2` | `ob-sessions.rename` | Rename Selected Session / Tab |
| `Delete` | `ob-sessions.close` | Close Selected Session / Tab |
| `Ctrl+Enter` | `ob-sessions.open-right` | Open Selected Session in Split Pane |

---

## Installation & Usage

### Requirements
- The [Herdr](https://github.com/herdrdev/herdr-app) desktop app (`0.1.16` or newer). `install.sh` switches layouts with its `herdr-app` command, so that command must be on your `PATH`.
- `python3`: used by `install.sh` to merge `keys.json`, and by `ob-feed`, `ob-outline`, `ob-props`, `ob-search`, and `ob-quotas` through `kit/provider.js`.
- `bash` (macOS's 3.2 is enough) and `cmp` for `install.sh`; it uses `readlink -f` where it exists and `python3` otherwise.
- `git` for `ob-sessions`; `node` for `insights` (defaults to `node` on `PATH`, or the path in `mods/insights/runtime.json`). Its Antigravity CLI indexing needs `node:sqlite` and is skipped without it.
- Optional: [`hc`](https://github.com/herdrdev/herdr-core) (from `herdr-core`), for the remote machine list and machine reconnection (`hc machine ls --json`, `hc machine rm`, `hc machine add`) in `ob-sessions` and `ob-footer`, `hc get` terminal inspection in `ob-props`, live child `hc run` / Attach and `hc read` scrollback search in `ob-outline` and `ob-search`; Obsidian, for the `obsidian` mod and daily notes. `obsidian` reads the vault from a `vault` key in `obsidian.json` in the Herdr app folder and nothing else; it does not read Obsidian's own vault list (the Vault tab of `ob-settings` sets that key; `obsidian.json` may still hold `dailyFolder`, `dailyFormat`, `dailyTemplate` and `editor` by hand, and the mod honours them).
- `ob-feed` finds running agents through `/proc` on Linux, and through `ps`, `ps -E` and `lsof` on macOS, assembling its `python3` scanner from `mods/ob-feed/providers/` (`index.json`, `scan_core.py`, and each provider's `manifest.json`, `reader.py`, and `scan.py`).
- The Antigravity provider in `ob-feed` and `ob-outline` (`mods/ob-feed/providers/antigravity/`) reads only `~/.gemini/antigravity-cli`: open `presence/<id>.lock` descriptors (`/proc/<pid>/fd` on Linux, `lsof -p <pid> -Fn` on macOS) to confirm `agy` or `antigravity` processes and their conversation ids, `conversation_summaries.db` (SQLite read-only) for titles and update times, and `brain/<id>/.system_generated/logs/transcript.jsonl` for transcripts.
- `obsidian` runs `rg` to list and search the vault (`find` and `grep` when `rg` is missing), `mkdir -p` for a daily note's folder, `xdg-open` (`open` on macOS, `cmd /c start` on Windows) for `obsidian://` links, and your editor in a new pane (`sh -c` with `$VISUAL`, `$EDITOR` or vi; `notepad` on Windows). It reads the vault's notes and its `.obsidian/daily-notes.json` and `.obsidian/app.json`. For an agent's last reply it reads `~/.claude/sessions/<pid>.json`, finds the session's transcript under `~/.claude/projects` (`sh` with `ls` and `head`) and reads its last 1.5 MB with `tail`; for an agent with no transcript (another agent, another machine) it runs `hc read` for its screen.
- `ob-outline` reads `mods/ob-feed/providers/` (`index.json`, `reader_main.py`, and each provider's `manifest.json` and `reader.py`) from the Herdr app folder to run `python3` in `entries` mode when opening a transcript or finding a Claude Code background agent's transcript (`~/.claude/projects`). It also runs `tail -n 400` to follow run logs, checks `<provider> --help` for `--session` support, and runs `hc run` to open a local run step's child session.
- `ob-search` runs `python3` on this computer with the transcript search reader assembled from `mods/ob-feed/providers/` (`index.json`, `reader_main.py`, and each provider's `manifest.json` and `reader.py`, read from the Herdr app folder), plus `hc read <addr> --lines 1500` on live terminal panes (up to 6 at once, cached 15 s). It reads the transcript files that the sub-agent feed (`ob.subagents`, written by `ob-feed`) names for live agent sessions and sub-agents whose provider has the `"search"` capability: those live under `~/.claude/projects` and `~/.pi/agent/sessions`, or the pi-subagents temp folder. It reads each file's last 3 MiB and changes nothing.
- `ob-props` runs `python3` on this computer, or on the terminal's machine, with the usage reader assembled from `mods/ob-feed/providers/` (`index.json`, `reader_main.py`, and each provider's `manifest.json` and `reader.py`, read from the Herdr app folder) alongside `hc get <addr> --json`, for the followed agent's session file (the transcript path the sub-agent feed names: `~/.claude/projects` or `~/.pi/agent/sessions`). Every 10 seconds while the panel shows it checks the file's size and modification time, and reads its last 32 MiB only when they changed; it changes nothing. It reads no plan or account limits.
- `ob-quotas` reads plan limits through `provider.quota()`, which runs `python3 -c <quota.py>` on this computer or the selected machine for each provider with the `"quota"` capability (`mods/ob-feed/providers/claude/quota.py`, `mods/ob-feed/providers/antigravity/quota.py`). Before running any CLI command, `providers/claude/quota.py` verifies that `$CLAUDE_CONFIG_DIR` (default `~/.claude`) exists and inspects the resolved `claude` executable (and any wrapper target path) for Claude Code package paths or binary markers; unrelated executables named `claude` are never run. It reads `$CLAUDE_CONFIG_DIR/.credentials.json`, `$CLAUDE_CONFIG_DIR/.claude.json`, and `~/.claude.json` (`subscriptionType`, OAuth expiration, `oauthAccount.emailAddress`). When verified and not due for token renewal, it runs `mise which claude` (only for a `mise` shim/wrapper), probes `/usr/bin/bwrap` with `true` on Linux to run `nice -n 19 claude -p /usage --output-format json --no-session-persistence --setting-sources "" --strict-mcp-config` read-only inside `bwrap` (or a throwaway `TMPDIR` if `bwrap` is unavailable), and on macOS reads Keychain entry `"Claude Code-credentials"` via `/usr/bin/security find-generic-password` and runs `claude` inside `/usr/bin/sandbox-exec` (verified with `/bin/sh`, `/usr/bin/touch`, and `/usr/bin/security list-keychains`) against a temp copy of `.credentials.json` stripped of `refreshToken`. `providers/antigravity/quota.py` checks `$ANTIGRAVITY_CLI_DIR` (or `dir` in optional `antigravity.json` in the Herdr app folder, default `~/.gemini/antigravity-cli`), inspects the resolved `agy`/`antigravity` executable (or `$ANTIGRAVITY_BIN` / `bin` in `antigravity.json`) for Antigravity markers before running anything, and runs `nice -n 19 <binary> -p /usage --output-format json`.
- `ob-sessions` offers its worktree actions only when the `worktree` mod is installed; to know that, it looks for `mods/worktree/mod.json` (or `main.js`) in the Herdr app folder.
- `ob-tabs` (`ob-tabs.feedback`), `ob-feedback`, and Settings (**Feedback** tab) run `herdr-app shot`, `herdr-app status`, and `herdr-app ls` (falling back to `~/.local/bin/herdr-app`, `/Applications/Herdr.app/Contents/MacOS/Herdr`, or `~/Applications/Herdr.app/Contents/MacOS/Herdr` when `herdr-app` is missing from `PATH`) plus `mkdir`, `test` (`-d`/`-s`), `cp`, and `rm` (`cmd` on Windows) for directories and binary screenshots outside `fs/promises` roots; read `feedback.json`, `layouts/.state/<layout>.json`, and `*.error` in the Herdr app folder; stage `data/ob-feedback/shot-<timestamp>.png` and `capture.json`; and write `<feedback-folder>/<timestamp>-<slug>/` bundles (`feedback.md`, `screenshot.png`, `ui-tree.json`, and `diagnostics.log`). `ui-tree.json` and `diagnostics.log` filter `shared` to safe keys, summarize feed counts via `provider.sessions()` and `provider.subagents()`, and omit terminal env/argv/labels.

The Herdr app folder is `~/.config/herdr-app`; set `HERDR_APP_HOME` to use another.

### 1. Install & Activate
Clone this repo and run the commands below from its folder. To sync kit assets, copy the layout and link mods into the Herdr app folder, merge keybindings, and switch Herdr to the Vaultr layout:

```bash
./install.sh --activate
```

*(To install without immediately switching layouts, run `./install.sh`)*

The layout is copied, not linked, so the arrangement you make in the app (panel order, sizes, a hidden status row, your theme) stays in your copy and never lands in the repo. `install.sh` records the installed `layouts/vaultr.json` in `vaultr-layout.installed.json` in the Herdr app folder (next to `vaultr-keys.owned.json`, outside `layouts/`). On re-install, an untouched copy (matching `vaultr-layout.installed.json`) is updated to the new repo layout without a backup; a changed copy keeps your arrangement (backed up before writing as `vaultr.json.bak-<date-time>`) and receives new repo nodes whose `id` is absent from both your copy and `vaultr-layout.installed.json` (deleted panels stay deleted, moved panels are not duplicated, and `vaultr.svg` updates whenever it differs). `install.sh` merges every section in `keys/vaultr-keys.json` and leaves alone the keys you changed in Hotkeys: a Vaultr key you removed stays removed (`vaultr-keys.owned.json` records which; `--uninstall`, then a fresh install, brings every key back), and a chord you bound to your own action is not overwritten. If a panel is missing from your layout, `ob-tabs.open` and `ob-tabs.toggle` show a warning toast without leaving Zen mode. To take the repo's layout again, run `./install.sh --reset-layout`: your copy is backed up next to it as `vaultr.json.bak-<date-time>` first. To develop the layout, `./install.sh --link` symlinks the repo file instead (a differing copy is backed up first, and `vaultr-layout.installed.json` is removed).

### 2. Kit Synchronization
When modifying shared components in `kit/` (`kit.js`, helper modules, or icons), synchronize them to all mods:

```bash
./kit/sync.sh
```

### 3. Uninstall
To remove the Vaultr layout and mod links, revert its keybindings in `keys.json`, and switch Herdr to the fallback layout. That is Herdr's `main` layout unless `VAULTR_FALLBACK_LAYOUT` is set. `--uninstall` removes `layouts/vaultr.json` when it matches either the repo file or `vaultr-layout.installed.json` (leaving user-modified copies in place unless `--reset-layout` is passed, after a backup), removes `vaultr-layout.installed.json`, and reverts all key sections from `vaultr-keys.owned.json` or `keys/vaultr-keys.json`. A real folder named `insights` or `obsidian` in the Herdr app folder is left alone:

```bash
./install.sh --uninstall
```

### 4. Tests
The suite needs no Herdr window and runs in about 145 seconds (`930+` tests): `python3 -m unittest discover -s test`. Rules for contributors are in [AGENTS.md](AGENTS.md).

---

## Agent program support

| Program | Session title | Recent prompts | Sub-agent feed | Transcript viewer | Properties usage | Search | Quotas | Insights |
|---|---|---|---|---|---|---|---|---|
| Claude Code | yes | yes | yes | yes | yes | yes | yes | yes |
| pi | — | yes | yes | yes | yes | yes | — | yes |
| Antigravity | yes | — | — | yes | — | — | yes | yes |
| OpenCode | — | — | — | — | — | — | — | yes |
| Codex | — | — | — | — | — | — | — | yes |
| Any program reporting OSC 7501 / `hc` | — | — | yes | — | — | yes | — | — |

- **Provider capabilities**: `Claude Code` enables `["title", "prompts", "transcript", "usage", "search", "touches", "subagents", "quota"]`. `pi` enables `["prompts", "transcript", "usage", "search", "touches", "subagents"]` (pane and tab labels fall back to terminal/process titles when `"title"` is omitted). `Antigravity` enables `["title", "transcript", "quota"]`. `OpenCode` and `Codex` are indexed by `insights` only.
- **OSC 7501 and `hc`**: Any program emitting OSC 7501 or running under [`hc`](https://github.com/herdrdev/herdr-core) gets live status marks in panes, tabs, sessions, and the status bar, live sub-agent record cards (`lastTool`) in the sub-agent feed, `hc` child terminal trees and live `Attach`, and `hc read` terminal screen/scrollback search in `ob-search` on live `hc` panes and child terminals.
- **`insights`**: Keeps its own multi-source local usage adapters outside `mods/ob-feed/providers/`.
- **Test coverage**: Fixture tests in `test/` cover provider folders, boundaries, assembly, pinned outputs, scanner identity, quotas, and Antigravity (`test_provider_folders.py`, `test_provider_boundaries.py`, `test_provider_facade.py`, `test_providers_pinned.py`, `test_provider_scan.py`, `test_provider_quota.py`, `test_provider_antigravity.py`), pane labels and prompts (`test_kit_names.py`, `test_ob_pane.py`), Outline viewer plans, child trees, and Attach/Detach rules (`test_ob_outline.py`), token usage (`test_ob_props.py`), transcript search (`test_ob_search.py`), and Quotas (`test_ob_quotas.py`). `mods/insights/` has no behavioral unit tests in this repository yet (syntax and packaging checks only); live OSC 7501 updates, `hc` Attach, and `hc read` scrollback search need a running Herdr window and are not covered by the automated tests.

## Adding a provider

Vaultr discovers agent providers from `mods/ob-feed/providers/index.json` using `kit/provider.js` (zero program names live in `kit/` or `mods/ob-*` UI mods):

- **Folder layout**: Create `mods/ob-feed/providers/<id>/{manifest.json,scan.py,reader.py}` (plus `quota.py` only when `"quota"` is in `caps`), add `"<id>"` to `mods/ob-feed/providers/index.json` (which must equal the exact set of provider folders), and add synthetic JSONL fixtures under `test/fixtures/providers/<id>/*.jsonl`. `test/test_provider_folders.py` discovers every provider listed in `index.json` and its fixtures automatically.
- **`manifest.json`**: Must contain **exact** keys `"id"`, `"name"`, `"noun"`, and `"caps"`:
  - `id` (string matching `<id>`), `name` (display name), and `noun` (singular run/sub-agent noun).
  - `caps` (non-empty string array from the closed capability set `["title", "prompts", "transcript", "usage", "search", "touches", "subagents", "quota"]`): gates controls across `ob-feed`, `ob-pane`, `ob-outline`, `ob-props`, `ob-search`, and `ob-quotas`.
- **`scan.py` (`register(...)`)**: Calls `register({ "id": ..., "match": ..., "confirm": ..., "sessions": ..., "subagents": ..., "runs": ... })` (and optional `"runs_root"`).
  - `match(comm, argv)` is only a fast pre-filter hint; `confirm(proc)` must verify program-owned on-disk state, lock descriptors, or session/package markers without ever executing an unknown binary (enforced by identity tests).
  - Providers with `"prompts"` must derive recent human turns from normalized reader events via `user_turns_from_events(evs)` rather than parsing transcript JSONL directly in `scan.py`.
  - Snippets are embedded inside wrapper functions by `kit/provider.js`, so multi-line string literals (`"""` / `'''`) are forbidden, Python 3.9 syntax is required, and assembled scanner and reader scripts must stay under `100 KiB`.
- **`reader.py`**: Defines module-level `sniff(first_records)` and `events(records)` (plus optional `find_subagent(agent_id)`), registered by `kit/provider.js` via `register_reader(...)` for `scan_core.py` and `reader_main.py` (`entries`, `usage`, and `search` modes). `events(records)` yields normalized dicts with `"k"` in `{"user", "assistant", "tool", "meta"}` (and `"turn_group"` on `"user"` events when `"prompts"` is enabled).
- **`quota.py`**: Present if and only if `"quota"` is in `caps`. Runs standalone via `python3 -c <quota.py> <json_opts>` from `provider.quota()` and prints a single JSON status object.
- **Boundary rules**: `test/test_provider_boundaries.py` enforces that `kit/*.js` and `mods/ob-*` (outside kit copies and `mods/ob-feed/providers/`) never name any provider id or display name, never run `python3` or provider scripts directly, and never read raw `ob.subagents` feed buckets instead of `provider.*`.

---

## Known limits

- Antigravity support was written from public format references, is tested with synthetic fixtures only and has not been checked against a live Antigravity install; it shows sessions, titles and transcripts only.
- Open session (starting a new `pi --session` terminal from a step) is local only; Attach works on live `hc` terminals on this computer and remote machines.
- The right-hand panels (Properties, Outline's pinned session) follow the last focused main-window pane, or the pin; there is no setting for it. Outline's tab view always shows the active tab's panes.
- macOS support is untested on a real Mac so far. The keys, the installer and the agent scan (`ps`/`lsof` in place of `/proc`) are covered by tests that fake the Mac side. `ps -E` shows only your own processes' environment, so an agent that runs as another user is not found.
- Notes and artifacts (ob-graph) are a proof of concept: a touch comes from the last 64 KiB of each transcript, so an older read or write is not seen, and a Write is a "create" only when no earlier touch of that path is in that tail. pi's file-tool names (read, write, edit) are taken from its session format and not yet checked against a live pi session. Attachments in the vault are skipped; a note or plain file on another machine is not shown (only its published artifacts are); a file an agent wrote into its own project shows as an artifact along with its published ones.
- The editor is set by `$VISUAL`, then `$EDITOR`, then vi; the Vault tab does not set it. The graph opens a plain-file artifact in the `editor` set by hand in `obsidian.json` (a command and its arguments, as the Notes mod reads it), else `$VISUAL`, then `$EDITOR`, then the first of nvim, vim, nano, vi that is installed.
- Search covers transcripts of agent sessions on this computer only; remote machines are not searched yet. It searches only the sessions the feed knows (live agents, their sub-agents, recent pi runs), not every file under `~/.claude/projects`. Tool calls and tool output are not searched. A transcript hit opens the transcript popup at its end, not at the message.

## Credits

- [Quartz](https://github.com/jackyzha0/quartz) (MIT, Jacky Zhao): the graph view that `ob-graph` is ported from.
- [Shepherdr](https://github.com/eliasstravik/shepherdr) (MIT, Elias Stravik): portions of `mods/ob-feed/providers/claude/quota.py` adapted from `mods/tasks/bin/herdr_task/machine.py`.
- [d3-force](https://github.com/d3/d3-force), [d3-quadtree](https://github.com/d3/d3-quadtree) and [d3-dispatch](https://github.com/d3/d3-dispatch) (ISC, Mike Bostock), vendored in `mods/ob-graph/vendor/`.
- [Lucide](https://github.com/lucide-icons/lucide) (ISC, Lucide Contributors; parts from [Feather](https://github.com/feathericons/feather), MIT, Cole Bemis): the icons in `mods/obsidian/` and most of the shared icon set in `kit/icons/` (which `kit/sync.sh` copies into each `ob-*` mod).
- [Simple Icons](https://github.com/simple-icons/simple-icons) (CC0-1.0) and [Lobe Icons](https://github.com/lobehub/lobe-icons) (MIT, LobeHub): the provider logos in `mods/insights/logos/`. The logos are trademarks of their owners.
- [tokscale#713](https://github.com/junhoyeo/tokscale/pull/713) and [openusage#1139](https://github.com/robinebers/openusage/pull/1139): notes on the Antigravity transcript format that `insights` reads.
- [herunan/herdr-over9k](https://github.com/herunan/herdr-over9k) (MIT, `over9k-sidebar/mods/over9k/agy-info.py`), [tokscale#713](https://github.com/junhoyeo/tokscale/pull/713), and [openusage#1139](https://github.com/robinebers/openusage/pull/1139): public format references consulted for `mods/ob-feed/providers/antigravity/` session discovery, titles, and transcripts (written fresh, no code copied).
- Notices and licence texts: [LICENSE](LICENSE) (MIT), [NOTICE](NOTICE), [LICENSE-herdr](LICENSE-herdr) (Apache-2.0 for Herdr-derived mods), [LICENSE-shepherdr](LICENSE-shepherdr) (MIT for Shepherdr-derived code), `mods/ob-graph/NOTICE.md`, `mods/ob-graph/vendor/*/LICENSE`, `mods/obsidian/NOTICE.md`, `mods/insights/NOTICE.md`, `kit/NOTICE.md`, `mods/ORIGIN.md`.
