# Working on Vaultr

Vaultr is a Herdr layout (`layouts/vaultr.json`) plus the mods it shows (`mods/`), for the Herdr desktop app.
The mods share one kit (`kit/`), keys are in `keys/`, and `install.sh` links everything into the Herdr app folder.

The four side stacks: left top is Sessions, Search, Bookmarks (opens on Sessions). Left bottom is Agents, Recent
(opens on Agents). Right top is Properties, Files, Changes, Insights, Notes (opens on Properties). Right bottom is
Graph, Outline (opens on Graph). Outline is the one panel for what runs in each tab: its panes with their agents nested
under them (it replaced the Subagents panel).

## Tests

- Green tests mean no known bugs. If a bug is found, the tests were missing a case: first add a test that fails
  because of the bug (run it and see it fail), then fix the bug until it passes. Commit the test and the fix as
  `test: ...` then `fix: ...`, or together in one `fix:` commit; never the fix without the test.
- Whole suite (about 15 seconds, no Herdr window needed): `python3 -m unittest discover -s test`
- One file: `python3 -m unittest discover -s test -p 'test_layout.py'`
- One class: `cd test && python3 -m unittest test_install.Install`
- Each test file imports `home_guard` first: HOME and HERDR_APP_HOME point at a temp folder, and `herdr-app` is a
  stub that only logs. Keep it that way.
- A mod's own check: `herdr-app check mods/<name>` (it loads the mod and reports errors). Run it after each mod change.
- Where a new test goes: layout rules in `test/test_layout.py`; mod manifests, kit copies, syntax, keys and
  personal-data checks in `test/test_repo.py`; installer behaviour in `test/test_install.py`.

## Trying a change

- `install.sh` links `mods/` into `~/.config/herdr-app`, so a saved mod file is live: the window reloads it. If a
  save does not show, bounce the layout: `herdr-app do layout.switch --name main`, then
  `herdr-app do layout.switch --name vaultr`.
- `install.sh` copies `layouts/vaultr.json` into the app folder; the copy is the person's arrangement (moving a panel
  writes it), so a saved repo layout is not live. To try a layout change, run `./install.sh --link` (symlinks it,
  backing up a differing copy first). A plain `./install.sh` afterwards keeps the copy.
- `herdr-app status` shows errors. A bad layout or mod keeps the last good version and writes `<name>.error`.
- Never edit `~/.config/herdr-app/layouts/.state/`.
- Never start a second herdr-app window, and never run herdr-app or install.sh with a changed HOME. To try the
  installer, use a scratch folder: `HERDR_APP_HOME=<scratch> ./install.sh`.
- Herdr's shipped mods (`files`, `changes`) are read-only. Clone them to change them.

## Kit

- Edit `kit/kit.js` (and the helpers `kit/*.js`, `kit/icons/`) only, then run `kit/sync.sh`.
- Never edit a mod's copy of `kit.js`, helper modules, or its icons: the next sync overwrites them.

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
