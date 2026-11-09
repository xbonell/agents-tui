"""Command line: the TUI by default, and print, status, json, collect, doctor, providers."""

from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__, config as config_mod, paths, present, render
from .collect import Kind, Store, update
from .config import Config
from .notify import Notifier

ANSI = {
  "": "", "bold": "1", "dim": "2", "title": "1", "accent": "36", "selected": "1;36",
  "alarm": "1;31", "warn": "33", "ok": "32", "bar": "36", "bar_alarm": "31", "bar_empty": "2",
}


def _utf8() -> bool:
  try:
    locale.setlocale(locale.LC_ALL, "")
  except locale.Error:
    pass
  encoding = (locale.getpreferredencoding(False) or "").lower().replace("-", "")
  return encoding in ("utf8", "utf8mb4")


def _ascii(cfg: Config, args) -> bool:
  if args.ascii or cfg.ascii == "always":
    return True
  if cfg.ascii == "never":
    return False
  return not _utf8()


def _color(cfg: Config, args, stream) -> bool:
  if args.no_color or cfg.color == "never" or "NO_COLOR" in os.environ:
    return False
  if cfg.color == "always":
    return True
  return stream.isatty() and os.environ.get("TERM", "") != "dumb"


def _ansi(line: render.Line, color: bool) -> str:
  if not color:
    return "".join(text for text, _ in line)
  out = []
  for text, style in line:
    code = ANSI.get(style, "")
    out.append(f"\033[{code}m{text}\033[0m" if code else text)
  return "".join(out)


def _load(args) -> Config:
  cfg = config_mod.load(Path(args.config) if args.config else None)
  if args.usage_dir:
    cfg.usage_dir = args.usage_dir
  if args.no_collect:
    cfg.collect = False
  return cfg


def _store(cfg: Config) -> Store:
  store = Store(cfg)
  store.poll()
  return store


def cmd_tui(args, cfg: Config) -> int:
  if not (sys.stdin.isatty() and sys.stdout.isatty()):
    print("agents-tui: not a terminal; `agents-tui print` writes the panel once", file=sys.stderr)
    return 2
  if os.environ.get("TERM", "") in ("", "dumb"):
    print("agents-tui: this terminal ($TERM) can't draw the panel; try `agents-tui print`", file=sys.stderr)
    return 2
  from .tui import App

  cfg_path = Path(args.config) if args.config else paths.config_file()
  return App(cfg, cfg_path, _ascii(cfg, args), _color(cfg, args, sys.stdout)).run()


def cmd_print(args, cfg: Config) -> int:
  if args.refresh and cfg.collect:
    update([p for p in paths.collector_ids() if cfg.enabled(p)], Kind.NORMAL, cfg.records_dir())
  store = _store(cfg)
  records = store.visible()
  width = args.width or (shutil.get_terminal_size((80, 24)).columns if sys.stdout.isatty() else 80)
  phrases = present.summary_phrases(records)
  view = render.View(
    records=records, now=time.time(), glyphs=render.Glyphs.make(_ascii(cfg, args)),
    phrase=phrases[0] if phrases else "", collecting=False, footer=False,
    expanded={r.id for r in records} if args.details else set(),
  )
  head, body, _ = render.screen(view, width)
  color = _color(cfg, args, sys.stdout)
  for line in head + body.lines:
    print(_ansi(line, color).rstrip())
  return 0


def cmd_status(args, cfg: Config) -> int:
  """One line for a tmux status bar or a desktop bar: each agent's fullest window."""
  now = time.time()
  parts = []
  records = _store(cfg).visible()
  for record in records:
    if present.needs_sign_in(record):
      parts.append(f"{record.name} sign-in")
      continue
    window = present.binding_window(record, now)
    if window is not None:
      parts.append(f"{record.name} {round(window.percent * 100)}%")
    elif record.balance is not None:
      parts.append(f"{record.name} {present.format_money(record.balance.remaining, record.balance.currency)}")
  line = " · ".join(parts) if parts else "no agents"
  if present.alarming(records, now):
    line = "! " + line
  print(line)
  return 0


def cmd_json(args, cfg: Config) -> int:
  store = _store(cfg)
  records = store.visible() if not args.all else sorted(store.records.values(), key=lambda r: r.id)
  json.dump([r.raw for r in records], sys.stdout, indent=2 if sys.stdout.isatty() else None)
  print()
  return 0


def cmd_collect(args, cfg: Config) -> int:
  known = paths.collector_ids()
  unknown = [p for p in args.providers if p not in known]
  if unknown:
    print(f"agents-tui: no collector named {', '.join(unknown)} (see `agents-tui providers`)", file=sys.stderr)
    return 2
  ids = args.providers or [p for p in known if cfg.enabled(p)]
  kind = Kind.FORCE if args.force else Kind.LIMITS if args.limits_only else Kind.NORMAL
  results = update(ids, kind, cfg.records_dir())
  status = 0
  for result in results:
    if not result.ok:
      status = 1
      print(f"agents-tui: {result.id} collector failed: {result.error}", file=sys.stderr)
    elif args.verbose:
      print(f"{result.id}: ok ({result.seconds:.1f}s)")
  if args.notify:
    Notifier().evaluate(_store(cfg).visible(), time.time(), cfg.notify)
  return status


def cmd_providers(args, cfg: Config) -> int:
  store = _store(cfg)
  for pid in paths.collector_ids():
    record = store.records.get(pid)
    state = "in use" if record and record.has_data else "not in use"
    enabled = "on " if cfg.enabled(pid) else "off"
    name = record.name if record else ""
    print(f"{enabled}  {pid:<12} {name:<18} {state}")
  return 0


def _check(ok: bool, label: str, detail: str = "") -> None:
  mark = "ok " if ok else "!! "
  print(f"  {mark} {label}" + (f": {detail}" if detail else ""))


def cmd_doctor(args, cfg: Config) -> int:
  print(f"agents-tui {__version__} on {platform.system()} {platform.release()} ({platform.machine()})")
  print()
  version = ".".join(str(x) for x in sys.version_info[:3])
  _check(sys.version_info >= (3, 9), "Python", f"{version} at {sys.executable}")
  try:
    import curses  # noqa: F401
    _check(True, "curses")
  except ImportError as error:
    _check(False, "curses", f"{error} (install your distribution's python3 curses package)")
  encoding = locale.getpreferredencoding(False)
  _check(True, "Locale", f"{encoding}" + ("" if _utf8() else " (ASCII meters; set a UTF-8 locale for block characters)"))
  _check(os.environ.get("TERM", "") not in ("", "dumb"), "TERM", os.environ.get("TERM", "(unset)"))
  rg = shutil.which("rg")
  _check(bool(rg), "ripgrep (rg)", rg or "missing: the collectors use it to find local session logs")
  for tool in ("claude", "codex", "cursor-agent", "opencode"):
    found = shutil.which(tool)
    print(f"  {'·  '} {tool}: {found or 'not on PATH'}")
  print()
  _check(True, "Settings", str(Path(args.config) if args.config else paths.config_file()))
  directory = cfg.records_dir()
  writable = os.access(directory if directory.exists() else directory.parent, os.W_OK) or not directory.parent.exists()
  _check(writable or not cfg.collect, "Records", f"{directory}" + ("" if cfg.collect else " (collect = false)"))
  print(f"  {'·  '} Collector caches: {paths.collector_env().get('XDG_CACHE_HOME', str(Path.home() / '.cache'))}/omarchy/agent-usage")
  print(f"  {'·  '} Collector log: {paths.cache_dir() / 'collect.log'}")
  revision = (paths.VENDOR / "UPSTREAM_REVISION").read_text().strip() if (paths.VENDOR / "UPSTREAM_REVISION").exists() else "unknown"
  print(f"  {'·  '} Omarchy collectors: {len(paths.collector_ids())} at {revision[:7]}")
  print()

  if cfg.collect and not args.no_run:
    print("Running every enabled collector once…")
    ids = [p for p in paths.collector_ids() if cfg.enabled(p)]
    results = {r.id: r for r in update(ids, Kind.NORMAL, cfg.records_dir())}
  else:
    results = {}
  store = _store(cfg)
  for pid in paths.collector_ids():
    record = store.records.get(pid)
    result = results.get(pid)
    if not cfg.enabled(pid):
      print(f"  off {pid}")
      continue
    if result is not None and not result.ok:
      _check(False, pid, f"collector failed: {result.error}")
      continue
    if record is None:
      print(f"  ·   {pid}: no record yet")
      continue
    if not record.has_data:
      print(f"  ·   {pid}: not in use on this machine")
      continue
    status = record.usage_status_text or ("limits kept from an earlier check" if record.limits_stale else "ok")
    help_text = f" ({record.auth_help_text.replace('`', '')})" if record.auth_help_text else ""
    _check(not record.usage_status_text, f"{pid} ({record.name})", status + help_text)
  return 0


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="agents-tui",
    description="Rate limits, reset times and token counts for your AI coding subscriptions.",
  )
  parser.add_argument("--version", action="version", version=f"agents-tui {__version__}")
  parser.add_argument("--config", help="settings file (default: ~/.config/agents-tui/config.toml)")
  parser.add_argument("--usage-dir", help="read and write records here instead")
  parser.add_argument("--no-collect", action="store_true", help="only display records; never run collectors")
  parser.add_argument("--ascii", action="store_true", help="plain ASCII meters")
  parser.add_argument("--no-color", action="store_true", help="no colors (NO_COLOR works too)")
  sub = parser.add_subparsers(dest="command", metavar="command")

  sub.add_parser("tui", help="the interactive panel (the default)")
  p = sub.add_parser("print", help="write the panel once and exit")
  p.add_argument("--width", type=int, default=0)
  p.add_argument("--details", action="store_true", help="every card's details")
  p.add_argument("--refresh", action="store_true", help="run the collectors first")
  sub.add_parser("status", help="one line: each agent's fullest limit")
  p = sub.add_parser("json", help="the records as a JSON array")
  p.add_argument("--all", action="store_true", help="agents not in use too")
  p = sub.add_parser("collect", help="run the collectors and write their records")
  p.add_argument("providers", nargs="*", help="only these (default: every enabled one)")
  group = p.add_mutually_exclusive_group()
  group.add_argument("--force", action="store_true", help="reuse no cached scans or limits")
  group.add_argument("--limits-only", action="store_true", help="fresh limits, cached local scans")
  p.add_argument("--notify", action="store_true", help="send the near-limit notifications that are due")
  p.add_argument("-v", "--verbose", action="store_true")
  sub.add_parser("providers", help="list the collectors and whether each is on")
  p = sub.add_parser("doctor", help="check this machine's setup and what each collector finds")
  p.add_argument("--no-run", action="store_true", help="don't run the collectors")
  return parser


def main(argv: Optional[List[str]] = None) -> int:
  args = build_parser().parse_args(argv)
  cfg = _load(args)
  command = args.command or "tui"
  handler = {
    "tui": cmd_tui, "print": cmd_print, "status": cmd_status, "json": cmd_json,
    "collect": cmd_collect, "providers": cmd_providers, "doctor": cmd_doctor,
  }[command]
  try:
    return handler(args, cfg)
  except BrokenPipeError:
    return 0
