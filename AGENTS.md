# Working on Vaultr

Vaultr is a Herdr layout (`layouts/vaultr.json`) plus the mods it shows (`mods/`), for the [Herdr](https://github.com/herdrdev/herdr-app) desktop app (requires Herdr `0.1.16` or newer).
The mods share one kit (`kit/`), keys are in `keys/`, and `install.sh` links everything into the Herdr app folder.

The four side stacks: left top is Sessions, Search, Bookmarks (opens on Sessions). Left bottom is Agents, Recent
(opens on Agents). Right top is Quotas, Properties, Files, Changes, Insights, Notes (opens on Quotas). Right bottom is
Graph, Outline (opens on Graph). Outline is the one panel for what runs in each tab: its panes with their agents nested
under them (it replaced the Subagents panel).

## Tests

- Green tests mean no known bugs. If a bug is found, the tests were missing a case: first add a test that fails
  because of the bug (run it and see it fail), then fix the bug until it passes. Commit the test and the fix as
  `test: ...` then `fix: ...`, or together in one `fix:` commit; never the fix without the test.
- Whole suite (about 95 seconds across 860+ tests, no Herdr window needed): `python3 -m unittest discover -s test`
- One file: `python3 -m unittest discover -s test -p 'test_layout.py'`
- One class: `cd test && python3 -m unittest test_install.Install`
- Each test file imports `home_guard` first: HOME and HERDR_APP_HOME point at a temp folder, and `herdr-app` is a
  stub that only logs. Keep it that way.
- A mod's own check: `herdr-app check mods/<name>` (it loads the mod and reports errors). Run it after each mod change.
- Where a new test goes: layout rules in `test/test_layout.py`; mod manifests, kit copies, syntax, keys and
  personal-data checks in `test/test_repo.py`; provider folder, boundary, facade, scanner, quota, and pinned-output
  rules in `test/test_provider_*.py` and `test/test_providers_pinned.py`; installer behaviour in `test/test_install.py`.

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
