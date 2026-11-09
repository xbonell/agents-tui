# Contributing

Thanks for helping. agents-tui is a small port of Omarchy's agents panel, so
most of the rules below are about keeping it close to upstream and running
anywhere. For how it's put together, read [AGENTS.md](AGENTS.md) first; it's
written for coding agents, but it's the architecture guide for people too.

## Setup

- Python 3.9 or later with `curses`, and `rg`. Nothing to install from pip,
  and there never will be: agents-tui runs on the standard library alone.
- `bin/agents-tui` runs it straight from the clone.
- No AI subscriptions needed for UI work: `tests/fixtures/` holds made-up
  records for a few providers.
  ```sh
  bin/agents-tui --usage-dir tests/fixtures --no-collect
  bin/agents-tui --usage-dir tests/fixtures --no-collect print --width 100 --details
  ```

## Constraints

- **Python 3.9.** macOS's `/usr/bin/python3` is 3.9.6 and must keep working.
  Every module has `from __future__ import annotations`; no `match`, no
  `X | Y` outside annotations, no `zip(strict=)`, no `datetime.UTC`, and ISO
  times go through `record.parse_iso`. If your Python is newer, check syntax
  with `ast.parse(source, feature_version=(3, 9))`. AGENTS.md has the full
  list.
- **Any terminal.** Everything drawn goes through `render.py` and has to fit
  the width it's given, from about 20 columns up, in both Unicode and
  `--ascii`. Colors are the 8 basic ones, so the user's theme decides the
  palette.
- **Two-space indentation**, as in Omarchy's Python.

## Where a fix goes

- **Never edit `vendor/`.** Those are Omarchy's files, vendored unmodified,
  and `scripts/sync-upstream.sh` overwrites them.
  - A collector bug that also happens on Omarchy belongs upstream, in
    [omacom/omarchy](https://github.com/omacom/omarchy). It comes back here
    with the next sync.
  - A difference that only matters on macOS goes in `runner/macos_shim.py`,
    and the same fix belongs in
    [agents-macos](https://github.com/xbonell/agents-macos)'s copy of it.
- Panel logic (windows, statuses, the alarm and notification rules) goes in
  `agents_tui/present.py`, kept in step with agents-macos's
  `Presentation.swift`. `render.py` only lays it out.
- A new provider usually needs nothing: sync from Omarchy. A CLI login goes
  in `present.SIGN_IN_COMMANDS`, which is the only list of commands `l` will
  ever run.

## Checking a change

```sh
python3 -m unittest discover -s tests -t .
```

The suite takes about 10 seconds. It runs every real collector in an empty
home, and the real TUI in a pseudo-terminal. Run it with the oldest Python
you can, ideally `/usr/bin/python3` on a Mac. Add a test for logic that could
regress (parsing, a rule, a layout edge case), not for declarative changes.

For rendering changes, also look at `print --width` output at a narrow and a
wide width, with and without `--ascii`, and paste it into the pull request.
For macOS-only code (the shim, the Keychain, `osascript`), say that you
checked it on a Mac: `python3 -I runner/run_collector.py <id> --force` and
`agents-tui doctor`.

## Style

- Match the code around you: its naming, its idiom, and how much it
  comments. Comments say why, not what.
- One change per pull request.
- Commit messages have a short imperative subject and, when there's more to
  say, a body wrapped at 72 columns that explains why. `git log` has
  examples.
- If the change affects what AGENTS.md or the README describe, update them in
  the same pull request.

## Reporting issues

Include your OS and terminal, `python3 -V`, which providers you use, what you
expected, and what happened. `agents-tui doctor` output and the collector
failure log (see "Where things live" in the README) help.

**Before pasting `doctor`, `json` output or logs, read through them** and
remove anything that identifies you: access tokens, account emails,
organization names.

## Security

agents-tui reads credentials, so please report anything that could leak or
misuse them privately, through
[GitHub's private vulnerability reporting](https://github.com/xbonell/agents-tui/security/advisories/new),
not in a public issue.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
