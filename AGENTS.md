# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

A terminal UI (Python, standard library `curses`) for macOS and Linux that ports Omarchy's `omarchy.agents` panel: rate limits, reset times, balances and token stats for AI coding subscriptions. It's the terminal sibling of agents-macos (a Swift menu bar app, `~/Work/agents-macos` or github.com/xbonell/agents-macos), and the presentation logic in `agents_tui/present.py` is a port of that app's `Model/Presentation.swift`, itself a port of Omarchy's `shell/plugins/agents/Panel.qml`. The record format is Omarchy's `docs/agent-usage-collectors.md`.

## Commands

```sh
python3 -m unittest discover -s tests -t .              # all tests (~10 s; runs the real collectors and a pty-driven TUI)
bin/agents-tui                                          # the TUI from the clone
bin/agents-tui --usage-dir tests/fixtures --no-collect  # the TUI on sample records, collecting nothing
bin/agents-tui --usage-dir tests/fixtures --no-collect print --width 100 --details   # check rendering without a terminal
python3 -I runner/run_collector.py <id> [--force|--limits-only]   # one collector's record
scripts/check-upstream.sh [--fetch] [--ref <ref>] [omarchy-checkout]   # vendored files vs Omarchy; exit 1 when out of date
scripts/sync-upstream.sh [omarchy-checkout]             # re-copy every collector from Omarchy
./install.sh [--uninstall]                              # symlink bin/agents-tui into $PREFIX/bin (default ~/.local)
```

## Constraints

- **Python 3.9, standard library only.** macOS's `/usr/bin/python3` is 3.9.6 and must keep working, and nothing may need pip. So: `from __future__ import annotations` in every module, `typing.List`/`Optional` where an annotation is evaluated, no `match`, no `X | Y` outside annotations, no `zip(strict=)`, no `datetime.UTC`, and `datetime.fromisoformat` only through `record.parse_iso` (3.9's rejects `Z` and odd fractions). The only Python available here may be newer: syntax-check with `ast.parse(source, feature_version=(3, 9))` and watch for runtime-only features by hand.
- **Any terminal.** Everything the TUI draws goes through `render.py` and must fit the width it's given (`tests/test_render.py` checks widths from 20 to 240, in Unicode and ASCII). Colors are the 8 basic ones on the terminal's default background, so the user's theme decides the palette. ASCII glyphs (`Glyphs.make(True)`) must stay pure ASCII.
- **Two-space indentation**, as in Omarchy's Python.

## Architecture

**Collector side**
- `vendor/omarchy/` mirrors the part of an Omarchy checkout the collectors need (`$OMARCHY_PATH`): `bin/omarchy-agent-usage-*` (every collector except `-update`), `shell/plugins/agents/collectors.py` and `manifest.json`, plus `UPSTREAM_REVISION`. **Vendored unmodified**: never edit these, because `sync-upstream.sh` overwrites them. Collectors load each other through `$OMARCHY_PATH/bin`, which is why all of them are vendored.
- `runner/run_collector.py` is the only way a collector runs. It sets `OMARCHY_PATH`, installs `vendor/tomli` as `tomllib` when Python lacks it, and on macOS only: defaults `XDG_STATE_HOME`/`XDG_CACHE_HOME` to `~/Library/Application Support/agents-tui` and `~/Library/Caches/agents-tui`, and applies `runner/macos_shim.py`. On Linux nothing is patched.
- `runner/macos_shim.py` is agents-macos's shim, copied. It monkeypatches the `collectors` module before the collector script imports from it: `read_json` falls back to the Keychain for Claude Code's `.credentials.json` and cursor-agent's `auth.json`, and `cursor_state_db` points under `~/Library/Application Support`. A fix made here belongs in agents-macos's copy too, and the other way round.

**App side (`agents_tui/`)**
- `paths.py`: every location, per OS. `collector_ids()` globs the vendored collectors and orders them as Omarchy's `manifest.json` lists providers, which is also the cards' order.
- `config.py`: `~/.config/agents-tui/config.toml`, read leniently (a wrong-typed key is ignored). `save_settings` writes only what the settings screen changes, so `--usage-dir`/`--no-collect` never end up in the file.
- `record.py`: the record, parsed leniently: every field optional, a field of the wrong type costs only itself. `has_data` decides whether a provider gets a card (agents-macos's rule: numbers, or a status such as "Waiting for auth").
- `present.py`: SwiftUI-free logic from `Presentation.swift`: windows and titles, expired windows reset to 0, model-scoped windows attached to their parent, the alarm rule (≥ 90%, or a balance ≤ 10%), `notifications_due` (once per window per reset, keyed on the reset minute, rearming below 85%), the sign-in allow-list `SIGN_IN_COMMANDS` (the only commands `l` ever runs; a record's own text never runs), summary phrases, `friendly_model_name`. Port further panel behavior here, not in `render.py`.
- `collect.py`: `update()` replaces Omarchy's bash `omarchy-agent-usage-update`: collectors in parallel via `sys.executable -I runner/run_collector.py`, 120 s timeout, stdout must be a JSON object, atomic write to `<usage dir>/<id>.json`, failures appended to `<cache dir>/collect.log`. `Store` rereads records when a file's mtime or size changes. `Scheduler` ports agents-macos's `Scheduler.swift`: driven by `tick()` from the UI loop, one update at a time in a thread, queued requests collapse into one with the highest `Kind` (NORMAL < LIMITS < FORCE).
- `render.py`: the panel as lines of `(text, style)` segments, shared by the TUI and `print`. Cards go 1 to 3 columns (`columns_for`); `Body.spans` maps each card to its lines for scrolling. Width is measured in terminal cells (`cell_width`).
- `tui.py`: the curses app. A 250 ms `getch` loop polls the store, ticks the scheduler and redraws. Style names map to curses attributes in `_init_attrs`. Sign-in uses `def_prog_mode`/`endwin` to hand the terminal to the CLI's login, then forces a refresh of that provider. Settings and help are overlays drawn in the body area.
- `notify.py`: desktop notifications (`osascript` with the text as arguments on macOS, `notify-send` on a Linux desktop; nothing over SSH or a console). What's been sent is kept in `<state dir>/notified.json`, seeded on the first run so nothing old fires.
- `cli.py`: argparse; the TUI is the default command, then `print`, `status`, `json`, `collect`, `providers`, `doctor`.

## Testing

`tests/fixtures/*.json` are sample records as of `tests/helpers.NOW` (2026-11-09 12:00 UTC); pass `NOW` rather than the clock. `test_collect.py` runs every real collector in an empty temporary home, so each must print a `ready: false` record without failing. `test_tui.py` drives the real TUI in a pseudo-terminal. Add a test only for logic that could regress (parsing, a rule, a layout edge case), not for declarative changes.

Nothing macOS-specific can run on Linux: `macos_shim.py`, the Keychain and `osascript` need checking on a Mac (`python3 -I runner/run_collector.py claude --force` there, and `agents-tui doctor`).

## Adding a provider

Usually nothing: sync from Omarchy and the new collector is picked up. If it has a CLI login, add it to `present.SIGN_IN_COMMANDS`. If it needs something different on macOS, patch it in `runner/macos_shim.py`.
