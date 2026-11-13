# Vaultr

An Obsidian-inspired workspace layout and mod suite for the [Herdr](https://github.com/herdr/herdr) desktop app.

## Repository Structure

- **`kit/`**: The shared mod foundation. Contains `kit.js` (reusable GPUI components, Obsidian theme tokens, icons, and shell helpers), `sync.sh` (tool to propagate `kit.js` and icons into each `mods/ob-*` folder), icon generators, and agent scanners.
- **`layouts/`**: Herdr layout specifications (`obsidian.json`, `obsidian.svg`) defining the workspace panels, sidebars, ribbons, and stacks.
- **`mods/`**: Obsidian-inspired UI mods (`ob-*`), including panels, tabs, switchers, footers, and overlays.
- **`keys/`**: Keybinding definitions (`obsidian-keys.json`), containing bindings for `"layout:obsidian"` and `"mod:ob-sessions"`.

## Installation & Setup

To install Vaultr into your live Herdr environment (`~/.config/herdr-app`):

```bash
# Link layouts and mods, merge keybindings:
./install.sh

# Link layouts and mods, merge keybindings, and switch active layout to Obsidian immediately:
./install.sh --activate
```

## Uninstallation

To cleanly remove Vaultr mods, layout definitions, and keybindings:

```bash
./install.sh --uninstall
```

This reverts `keys.json` by removing the Obsidian sections and switches the active layout back to `iv`.
