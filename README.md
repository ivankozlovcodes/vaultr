# Vaultr

Vaultr is an Obsidian-inspired workspace layout and complete mod suite for the [Herdr](https://github.com/herdr/herdr) desktop app. It transforms Herdr into a modular, keyboard-driven workbench featuring collapsible left and right sidebars, tab management, deep agent/subagent inspection, workspace graph visualization, quick switcher, and custom hotkey management.

## Repository Layout

- **`kit/`**: Shared mod foundation. Contains `kit.js` (reusable GPUI components, theme tokens, shell helpers, and SVG icons), `sync.sh` (tool to propagate `kit.js` and icons into each `mods/ob-*` folder), and agent scan utilities.
- **`layouts/`**: Herdr workspace layout specifications:
  - `vaultr.json`: A center column between two sidebars, each split into two stacks of tabs. Left top: Sessions, Search, Bookmarks. Left bottom: Agents, Recent. Right top: Properties, Files, Changes, Insights, Notes. Right bottom: Graph, Outline.
  - `vaultr.svg`: Layout preview icon.
- **`mods/`**: The 19 mods: 17 Obsidian-style `ob-*` mods, plus `insights` and `obsidian` (origin in `mods/ORIGIN.md`).
- **`keys/`**: Keybinding configurations:
  - `vaultr-keys.json`: Custom keybinding definitions for `layout:vaultr` and `mod:ob-sessions`.
- **`install.sh`**: One-step installer, activator, and uninstaller.

---

## The 19 Vaultr Mods

The layout also uses Herdr's shipped `files` and `changes` mods.

### Chrome & Frame
- **`ob-strip`**: Side ribbons and stack tab strips with tab icons, collapse toggles, and window controls.
- **`ob-menu`**: Application popup menu with workspace actions, theme switcher, and layout controls.
- **`ob-tabs`**: Obsidian-style tab bar supporting drag reordering, pinned tabs, daily notes, and split shortcuts.
- **`ob-pane`**: Terminal and pane header with directory breadcrumbs, status indicators, and pane split/close buttons.
- **`ob-status`**: Bottom status bar displaying active terminal details, agent statuses, word/char counts, and clock.
- **`ob-footer`**: Bottom toolbar in the left sidebar: the machine switcher, then help and a settings gear that opens `ob-settings`.

### Left Sidebar (Navigation & Sessions)
- **`ob-sessions`**: File explorer tree representing spaces, tabs, panes, and terminals with git status and context menus.
- **`ob-search`**: Fast workspace-wide search across terminals and agent transcripts. Terms are fuzzy: every word must match; a transcript hit opens its transcript.
- **`ob-bookmarks`**: Obsidian-style bookmarks manager for spaces, tabs, terminal sessions, and subagent runs.
- **`ob-agents`**: Live agent monitor grouped by status priority (Needs you, Done, Working, Idle) or space.
- **`ob-recent`**: Chronological activity timeline of tab visits and agent events (Today, Yesterday, Earlier).

### Right Sidebar (Inspection & Data)
- **`ob-feed`**: Background scanner for Pi runs and Claude Code agent transcripts. It also lists the files each agent touched (paths and tool names from the transcript tail, never contents) and the artifacts it published (from the herdr-artifact store), for the graph's notes and artifacts.
- **`ob-outline`**: The active tab's panes, each with the agents that run in its terminal nested under it (pi runs, Claude Code agents, child terminals), with task trees, execution steps, tool call logs, and token metrics. "All" groups every machine by session, with unattached background terminals last.
  - A transcript or log opens in a popup over the window. **Move to main window** in its header puts it in the main window as a pane.
  - **Attach** (the row button, or the context menu) opens a live local `hc` child terminal in a popup you can watch and type into. **Move to main window** gives it a tab of its own.
  - Subagents never get a tab or pane by themselves: only **Move to main window** puts one on screen.
- **`ob-props`**: Detailed properties inspector for active terminals, including environment, git repo details, machine stats, and a Usage section for the followed Claude Code or pi session (tokens by kind, context in use, model, turns, subagents' output tokens).
- **`ob-graph`**: Interactive relationship graph visualizing connections between machines, spaces, terminals (the panes of one tab drawn as a small cluster), and subagents. Its layout and view follow Quartz v4's graph (MIT) on d3-force (ISC), vendored in `mods/ob-graph/vendor/`; notices in `mods/ob-graph/NOTICE.md`.
  - **Notes** and **Artifacts** (toolbar switches, off by default, kept per Local/Global view like Active only) add the files your agents touched. A note is a `.md` file in your vault, a small light dot linked to each agent that touched it (a note two agents touched joins them). An artifact is a square: a `herdr-artifact` you published, or a file an agent wrote or created outside the vault. Reads outside the vault are not shown. Clicking a note opens it in the Notes viewer; an artifact opens with `herdr-artifact open`, a plain file in your editor.
  - What is read for this: the file paths and tool names in each agent's transcript tail (the same tail the feed reads; no file contents and no tool output are kept), the herdr-artifact store (`~/.herdr/artifacts`, or `~/.local/share/shepherdr/artifacts`, which records the terminal that published each artifact), and `obsidian.json` for the vault path (read only). Notes need the vault set; without one the Notes switch is off.
  - Never shown: anything in a `danger/` folder of the vault (the vault's rule: it holds credentials), a hidden folder or file in the vault (`.obsidian`, `.git`, `.trash`), attachments (images, PDFs) in the vault, and a note of another machine.
- **`insights`**: Usage dashboard over local coding-agent session transcripts (pi, Codex, opencode, Claude Code, Antigravity), indexed by a Node process.
- **`obsidian`**: `Notes` tab for browsing and editing notes in an Obsidian vault. The vault must be set once (Settings, Vault tab). There is no fallback to Obsidian's own vault: until one is set, the tab says "No vault set." and the daily-note command asks you to set it.

### Overlays & Dialogs
- **`ob-switcher`**: Quick switcher popup (`Ctrl+P`) for jumping between tabs/sessions. Three modes, shown in the header and cycled with Tab: Everything, Views (sidebar views only), and Commands (`Ctrl+Shift+P`, or `>` typed in any mode: Vaultr's commands and Herdr's app commands, one list).
- **`ob-settings`**: Settings dialog, opened by the footer's gear or `Ctrl+,`, or `Ctrl+Alt+K` (which opens it on Hotkeys). Tabs down the left: **Vault** (the vault folder, saved to `obsidian.json` in the Herdr app folder; set it once. Unset means no vault: the Notes panel and daily notes are off, with no fallback to Obsidian's own vault. Daily notes follow Obsidian's own daily-notes settings in that vault, and the editor is `$VISUAL`, then `$EDITOR`, then vi), **Hotkeys**: every command with its keys, searchable, with a scope for each `keys.json` section, where you add, remove or restore keys. Its Layout sub-tab holds the window buttons setting and the plain-Ctrl keys the layout takes from terminal programs. **Herdr settings…** sits below the tabs and opens Herdr's own settings.

---

## Keybindings Reference

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
| `Ctrl+Shift+Z` / `Ctrl+Alt+Z` | `ob-tabs.zen` | Toggle Zen Mode |

The settings dialog opens from the gear in the footer. `ob-tabs.settings:<tab>` opens it on a tab (`vault` or `hotkeys`); with no tab, it opens on the tab used last.

### `mod:ob-sessions`

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `F2` | `ob-sessions.rename` | Rename Selected Session / Tab |
| `Delete` | `ob-sessions.close` | Close Selected Session / Tab |
| `Ctrl+Enter` | `ob-sessions.open-right` | Open Selected Session in Split Pane |

---

## Installation & Usage

### Requirements
- The [Herdr](https://github.com/herdr/herdr) desktop app. `install.sh` switches layouts with its `herdr-app` command, so that command must be on your `PATH`.
- `python3`: used by `install.sh` to merge `keys.json`, and by `ob-feed` to scan for agents.
- `bash`, `readlink -f` and `cmp` for `install.sh`.
- `git` for `ob-sessions`; `node` for `insights` (defaults to `node` on `PATH`, or the path in `mods/insights/runtime.json`). Its Antigravity indexing needs `node:sqlite` and is skipped without it.
- Optional: `hc`, for the remote machine list in `ob-sessions` and `ob-footer`; Obsidian, for the `obsidian` mod and daily notes. `obsidian` reads the vault from a `vault` key in `obsidian.json` in the Herdr app folder and nothing else; it does not read Obsidian's own vault list (the Vault tab of `ob-settings` sets that key; `obsidian.json` may still hold `dailyFolder`, `dailyFormat`, `dailyTemplate` and `editor` by hand, and the mod honours them).
- `ob-feed` reads `/proc`, so it only finds running agents on Linux.
- `obsidian` runs `rg` to list and search the vault (`find` and `grep` when `rg` is missing), `mkdir -p` for a daily note's folder, `xdg-open` (`open` on macOS, `cmd /c start` on Windows) for `obsidian://` links, and your editor in a new pane (`sh -c` with `$VISUAL`, `$EDITOR` or vi; `notepad` on Windows). It reads the vault's notes and its `.obsidian/daily-notes.json` and `.obsidian/app.json`. For an agent's last reply it reads `~/.claude/sessions/<pid>.json`, finds the session's transcript under `~/.claude/projects` (`sh` with `ls` and `head`) and reads its last 1.5 MB with `tail`; for an agent with no transcript (another agent, another machine) it runs `hc read` for its screen.
- `ob-search` runs `python3` with `mods/ob-search/transcript_search.py` (read from the Herdr app folder) on this computer. It reads the transcript files that the sub-agent feed (`ob.subagents`, written by `ob-feed`) names for live agent sessions and their sub-agents: those live under `~/.claude/projects` and `~/.pi/agent/sessions`, or the pi-subagents temp folder. It reads each file's last 3 MiB and changes nothing.
- `ob-props` runs `python3` with `mods/ob-props/usage.py` (read from the Herdr app folder) on this computer, or on the terminal's machine, for the followed agent's session file (the transcript path the sub-agent feed names: `~/.claude/projects` or `~/.pi/agent/sessions`). It reads the file's last 32 MiB, every 10 seconds while the panel shows, and changes nothing. It reads no plan or account limits.

The Herdr app folder is `~/.config/herdr-app`; set `HERDR_APP_HOME` to use another.

### 1. Install & Activate
Clone this repo and run the commands below from its folder. To sync kit assets, copy the layout and link mods into the Herdr app folder, merge keybindings, and switch Herdr to the Vaultr layout:

```bash
./install.sh --activate
```

*(To install without immediately switching layouts, run `./install.sh`)*

The layout is copied, not linked, so the arrangement you make in the app (panel order, sizes, a hidden status row, your theme) stays in your copy and never lands in the repo. A re-install keeps a copy that differs from the repo. To take the repo's layout again, run `./install.sh --reset-layout`: your copy is backed up next to it as `vaultr.json.bak-<date-time>` first. To develop the layout, `./install.sh --link` symlinks the repo file instead (a differing copy is backed up first).

### 2. Kit Synchronization
When modifying shared components in `kit/` (`kit.js`, icons, or scanners), synchronize them to all mods:

```bash
./kit/sync.sh
```

### 3. Uninstall
To remove the Vaultr layout and mod links, revert its keybindings in `keys.json`, and switch Herdr to the fallback layout. That is Herdr's `main` layout unless `VAULTR_FALLBACK_LAYOUT` is set. A layout copy you changed is left in place and the script says so; `--reset-layout` removes it too, after a backup. A real folder named `insights` or `obsidian` in the Herdr app folder is left alone:

```bash
./install.sh --uninstall
```

### 4. Tests
The checks run in seconds and need no Herdr window: `python3 -m unittest discover -s test`. Rules for contributors are in [AGENTS.md](AGENTS.md).

---

## Known limits

- Attach is local only: it opens `hc` terminals on this computer, not on other machines.
- The right-hand panels (Properties, Outline's pinned session) follow the last focused main-window pane, or the pin; there is no setting for it. Outline's tab view always shows the active tab's panes.
- The transcript scanner (`ob-feed/scan_pi.py`) reads Linux `/proc`, so it finds no running agents on macOS.
- Notes and artifacts (ob-graph) are a proof of concept: a touch comes from the last 64 KiB of each transcript, so an older read or write is not seen, and a Write is a "create" only when no earlier touch of that path is in that tail. pi's file-tool names (read, write, edit) are taken from its session format and not yet checked against a live pi session. Attachments in the vault are skipped; a note or plain file on another machine is not shown (only its published artifacts are); a file an agent wrote into its own project shows as an artifact along with its published ones.
- The editor is set by `$VISUAL`, then `$EDITOR`, then vi; the Vault tab does not set it. The graph opens a plain-file artifact in `$VISUAL`, then `$EDITOR`, then the first of nvim, vim, nano, vi that is installed.
- Search covers transcripts of agent sessions on this computer only; remote machines are not searched yet. It searches only the sessions the feed knows (live agents, their sub-agents, recent pi runs), not every file under `~/.claude/projects`. Tool calls and tool output are not searched. A transcript hit opens the transcript popup at its end, not at the message.

## Credits

- [Quartz](https://github.com/jackyzha0/quartz) (MIT, Jacky Zhao): the graph view that `ob-graph` is ported from.
- [d3-force](https://github.com/d3/d3-force), [d3-quadtree](https://github.com/d3/d3-quadtree) and [d3-dispatch](https://github.com/d3/d3-dispatch) (ISC, Mike Bostock), vendored in `mods/ob-graph/vendor/`.
- Notices and licence texts: `mods/ob-graph/NOTICE.md`, `mods/ob-graph/vendor/*/LICENSE`, `mods/ORIGIN.md`.
