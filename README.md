# Vaultr

Vaultr is an Obsidian-inspired workspace layout and complete mod suite for the [Herdr](https://github.com/herdr/herdr) desktop app. It transforms Herdr into a modular, keyboard-driven workbench featuring collapsible left and right sidebars, tab management, deep agent/subagent inspection, workspace graph visualization, quick switcher, and custom hotkey management.

## Repository Layout

- **`kit/`**: Shared mod foundation. Contains `kit.js` (reusable GPUI components, theme tokens, shell helpers, and SVG icons), `sync.sh` (tool to propagate `kit.js` and icons into each `mods/ob-*` folder), and agent scan utilities.
- **`layouts/`**: Herdr workspace layout specifications:
  - `obsidian.json`: Three-column layout tree with collapsible sidebars and multi-tab stacks.
  - `obsidian.svg`: Layout preview icon.
- **`mods/`**: The complete suite of 18 Obsidian-style UI mods.
- **`keys/`**: Keybinding configurations:
  - `obsidian-keys.json`: Custom keybinding definitions for `layout:obsidian` and `mod:ob-sessions`.
- **`install.sh`**: One-step installer, activator, and uninstaller.

---

## The 18 Vaultr Mods

### Chrome & Frame
- **`ob-strip`**: Side ribbons and stack tab strips with tab icons, collapse toggles, and window controls.
- **`ob-menu`**: Application popup menu with workspace actions, theme switcher, and layout controls.
- **`ob-tabs`**: Obsidian-style tab bar supporting drag reordering, pinned tabs, daily notes, and split shortcuts.
- **`ob-pane`**: Terminal and pane header with directory breadcrumbs, status indicators, and pane split/close buttons.
- **`ob-status`**: Bottom status bar displaying active terminal details, agent statuses, word/char counts, and clock.
- **`ob-footer`**: Bottom utility toolbar in the left sidebar providing quick access to settings, hotkeys, and help.

### Left Sidebar (Navigation & Sessions)
- **`ob-sessions`**: File explorer tree representing spaces, tabs, panes, and terminals with git status and context menus.
- **`ob-search`**: Fast workspace-wide search across active tabs, terminals, and outputs.
- **`ob-bookmarks`**: Obsidian-style bookmarks manager for spaces, tabs, terminal sessions, and subagent runs.
- **`ob-agents`**: Live agent monitor grouped by status priority (Needs you, Done, Working, Idle) or space.
- **`ob-recent`**: Chronological activity timeline of tab visits and agent events (Today, Yesterday, Earlier).

### Right Sidebar (Inspection & Data)
- **`ob-feed`**: Background scanner for Pi runs and Claude Code agent transcripts.
- **`ob-subagents`**: Deep subagent inspector with task trees, execution steps, tool call logs, and token metrics.
- **`ob-props`**: Detailed properties inspector for active terminals, including environment, git repo details, and machine stats.
- **`ob-graph`**: Interactive relationship graph visualizing connections between spaces, tabs, terminals, and subagents.
- **`ob-outline`**: Tab outline showing active panes, running processes, current directories, and subagent tasks.

### Overlays & Dialogs
- **`ob-switcher`**: Quick switcher popup (`Ctrl+P`) for jumping between tabs/sessions, and command palette (`Ctrl+Shift+P` or `>`).
- **`ob-hotkeys`**: Full-screen hotkey manager dialog (`Ctrl+Alt+K`) to search, customize, and reset keyboard shortcuts.

---

## Keybindings Reference

### `layout:obsidian`

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `Ctrl+P` | `mod.open:ob-switcher` | Open Quick Switcher |
| `Ctrl+Shift+P` | `app.palette` | Open Command Palette |
| `Ctrl+B` | `layout.toggle:ob-left` | Toggle Left Sidebar |
| `Ctrl+Shift+B` | `layout.toggle:ob-right` | Toggle Right Sidebar |
| `Ctrl+\` | `pane.split:right` | Split Pane Right |
| `Ctrl+Shift+\` / `Ctrl+\|` | `pane.split:down` | Split Pane Down |
| `Ctrl+Shift+E` | `ob-tabs.open:ob-sessions@reveal` | Reveal Active Session in Explorer |
| `Ctrl+Shift+M` | `ob-tabs.switcher:move` | Move Tab to Another Space |
| `Ctrl+Shift+C` / `Ctrl+Alt+C` | `ob-tabs.copy-path` | Copy Active Tab Path |
| `Ctrl+Shift+D` | `ob-tabs.daily` | Open / Focus Daily Session |
| `Ctrl+Shift+F` / `Ctrl+Alt+F` | `ob-tabs.open:ob-search` | Open Search in Left Sidebar |
| `Ctrl+Shift+G` | `ob-tabs.open:ob-graph` | Open Graph in Right Sidebar |
| `Ctrl+Shift+A` | `ob-tabs.toggle:ob-subagents` | Toggle Subagent Inspector |
| `Ctrl+Alt+O` | `ob-tabs.open:ob-outline` | Open Outline in Right Sidebar |
| `Ctrl+Alt+I` | `ob-tabs.open:ob-props` | Open Properties in Right Sidebar |
| `Ctrl+Alt+A` | `ob-tabs.open:ob-agents` | Open Agents in Left Sidebar |
| `Ctrl+Alt+B` | `ob-tabs.bookmark` | Bookmark Active Session / Tab |
| `Ctrl+Alt+Left` | `ob-tabs.back` | Navigate History Back |
| `Ctrl+Alt+Right` | `ob-tabs.forward` | Navigate History Forward |
| `Ctrl+9` | `ob-tabs.last` | Focus Last Tab |
| `Ctrl+Alt+K` | `mod.open:ob-hotkeys` | Open Hotkey Manager |
| `Ctrl+Alt+T` | `ob-tabs.tab-list` | Open Tab List Menu |

### `mod:ob-sessions`

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `F2` | `ob-sessions.rename` | Rename Selected Session / Tab |
| `Delete` | `ob-sessions.close` | Close Selected Session / Tab |
| `Ctrl+Enter` | `ob-sessions.open-right` | Open Selected Session in Split Pane |

---

## Installation & Usage

### 1. Install & Activate
To sync kit assets, link layouts and mods into `~/.config/herdr-app`, merge keybindings, and switch Herdr to the Obsidian layout:

```bash
./install.sh --activate
```

*(To install without immediately switching layouts, run `./install.sh`)*

### 2. Kit Synchronization
When modifying shared components in `kit/` (`kit.js`, icons, or scanners), synchronize them to all mods:

```bash
./kit/sync.sh
```

### 3. Uninstall
To cleanly remove all Vaultr symlinks, revert `keys.json`, and switch Herdr back to the default `iv` layout:

```bash
./install.sh --uninstall
```
