# Origin of `insights`, `obsidian` and `ob-graph`

On 2026-11-13 `insights` and `obsidian` were moved into this repo from the author's dotfiles repo. Vaultr is now their only source; edit them here.

- **`insights`**: right-sidebar usage dashboard. Indexes local coding-agent session transcripts (pi, Codex, opencode, Claude Code, Antigravity) with a Node indexer.
- **`obsidian`**: Notes popup (`Notes` tab) that browses and edits notes in an Obsidian vault.
- **`ob-graph`**: the Graph panel's layout and view are a port of Quartz v4's graph view (jackyzha0/quartz, MIT,
  commit `d25a6eab`), on the vendored d3-force 3.0.0 (ISC; with d3-quadtree 3.0.1 and d3-dispatch 3.0.1). Quartz's
  defaults, forces and formulas are used; the notices are in `mods/ob-graph/NOTICE.md`.
