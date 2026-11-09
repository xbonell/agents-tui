"""The interactive panel, drawn with the standard library's curses."""

from __future__ import annotations

import curses
import os
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from . import __version__, config as config_mod, paths, present, render
from .collect import Kind, Scheduler, Store
from .config import INTERVALS, Config
from .notify import Notifier
from .render import Line

PHRASE_SECONDS = 4.0
MESSAGE_SECONDS = 6.0
TICK_MS = 250


class Overlay:
  NONE, HELP, SETTINGS = range(3)


class App:
  def __init__(self, cfg: Config, cfg_path, ascii_only: bool, color: bool):
    self.cfg = cfg
    self.cfg_path = cfg_path
    self.glyphs = render.Glyphs.make(ascii_only)
    self.color = color
    self.store = Store(cfg)
    self.scheduler = Scheduler(self.store, cfg)
    self.notifier = Notifier()
    self.selected: Optional[str] = None
    self.expanded: set = set()
    self.scroll = 0
    self.overlay = Overlay.NONE
    self.settings_cursor = 0
    self.settings_scroll = 0
    self.phrase_index = 0
    self.phrase_at = 0.0
    self.message = ""
    self.message_until = 0.0
    self.frame = 0
    self.attrs: Dict[str, int] = {}
    self.stdscr = None

  # Setup

  def run(self) -> int:
    os.environ.setdefault("ESCDELAY", "25")
    try:
      curses.wrapper(self._main)
    except KeyboardInterrupt:
      pass
    return 0

  def _init_attrs(self) -> None:
    bold, dim = curses.A_BOLD, curses.A_DIM
    a = {"": 0, "bold": bold, "dim": dim, "title": bold}
    if self.color and curses.has_colors():
      curses.start_color()
      try:
        curses.use_default_colors()
        bg = -1
      except curses.error:
        bg = curses.COLOR_BLACK
      for pair, fg in ((1, curses.COLOR_CYAN), (2, curses.COLOR_RED), (3, curses.COLOR_YELLOW), (4, curses.COLOR_GREEN)):
        curses.init_pair(pair, fg, bg)
      accent, red, yellow = curses.color_pair(1), curses.color_pair(2), curses.color_pair(3)
      a.update({
        "accent": accent, "selected": accent | bold, "alarm": red | bold, "warn": yellow,
        "ok": curses.color_pair(4), "bar": accent, "bar_alarm": red, "bar_empty": dim,
      })
    else:
      a.update({
        "accent": bold, "selected": bold | curses.A_UNDERLINE, "alarm": bold, "warn": bold,
        "ok": 0, "bar": 0, "bar_alarm": bold, "bar_empty": dim,
      })
    self.attrs = a

  def _main(self, stdscr) -> None:
    self.stdscr = stdscr
    try:
      curses.curs_set(0)
    except curses.error:
      pass
    self._init_attrs()
    stdscr.timeout(TICK_MS)
    stdscr.keypad(True)
    self.store.poll()
    self._on_records()
    while True:
      now = time.time()
      if self.store.poll():
        self._on_records()
      self.scheduler.tick(now)
      self.frame += 1
      self._draw(now)
      key = stdscr.getch()
      if key == -1:
        continue
      if not self._handle(key):
        return

  # State

  def _visible(self) -> List:
    return self.store.visible()

  def _on_records(self) -> None:
    records = self._visible()
    alerts = self.notifier.evaluate(records, time.time(), self.cfg.notify)
    if alerts:
      self._say(alerts[0].title + (f" ({alerts[0].body})" if alerts[0].body else ""))
      try:
        curses.beep()
      except curses.error:
        pass
    ids = [r.id for r in records]
    if self.selected not in ids:
      self.selected = ids[0] if ids else None

  def _say(self, text: str) -> None:
    self.message = text
    self.message_until = time.time() + MESSAGE_SECONDS

  def _view(self, now: float) -> render.View:
    records = self._visible()
    phrases = present.summary_phrases(records)
    if now - self.phrase_at >= PHRASE_SECONDS:
      self.phrase_at = now
      self.phrase_index += 1
    phrase = phrases[self.phrase_index % len(phrases)] if phrases else ""
    errors = {r.id: r.error for r in self.scheduler.failures()}
    if now > self.message_until:
      self.message = ""
    return render.View(
      records=records, now=now, glyphs=self.glyphs, phrase=phrase,
      running=self.scheduler.running, frame=self.frame,
      next_refresh=max(0.0, self.scheduler.next_full - now) if self.scheduler.next_full else None,
      selected=self.selected, expanded=self.expanded, errors=errors,
      collecting=self.cfg.collect, message=self.message,
    )

  # Drawing

  def _put(self, y: int, line: Line, width: int) -> None:
    x = 0
    for text, style in render.clip(line, width):
      if not text:
        continue
      try:
        self.stdscr.addstr(y, x, text, self.attrs.get(style, 0))
      except curses.error:
        pass  # the bottom-right cell can't be written without scrolling
      x += render.cell_width(text)

  def _draw(self, now: float) -> None:
    scr = self.stdscr
    height, width = scr.getmaxyx()
    scr.erase()
    if height < 4 or width < 20:
      self._put(0, [("Too small", "warn")], width)
      scr.refresh()
      return
    view = self._view(now)
    head, body, foot = render.screen(view, width)
    if self.overlay != Overlay.NONE:
      lines = self._help_lines(width) if self.overlay == Overlay.HELP else self._settings_lines(width)
      if self.glyphs.partial == "":
        lines = render.asciify(lines)
      body = render.Body(lines, {})
    room = max(1, height - len(head) - len(foot))
    total = len(body.lines)
    self._keep_visible(body, room)
    if self.overlay == Overlay.SETTINGS:
      top = self.settings_scroll
    else:
      top = self.scroll if self.overlay == Overlay.NONE else 0
    top = max(0, min(top, max(0, total - room)))
    if total > room:
      # Where the window is, on the rule under the header.
      where = f" {top + 1}-{min(total, top + room)}/{total} "
      rule = self.glyphs.rule * (width - len(where) - 2) + where + self.glyphs.rule * 2
      head = head[:1] + [[(rule, "dim")]]
    for y, line in enumerate(head):
      self._put(y, line, width)
    for i, line in enumerate(body.lines[top:top + room]):
      self._put(len(head) + i, line, width)
    for i, line in enumerate(foot):
      self._put(height - len(foot) + i, line, width)
    scr.refresh()

  def _keep_visible(self, body: render.Body, room: int) -> None:
    if self.overlay == Overlay.SETTINGS:
      cursor_line = self._settings_line_of(self.settings_cursor)
      if cursor_line < self.settings_scroll:
        self.settings_scroll = cursor_line
      elif cursor_line >= self.settings_scroll + room:
        self.settings_scroll = cursor_line - room + 1
      return
    if self.overlay != Overlay.NONE or self.selected not in body.spans:
      return
    start, end = body.spans[self.selected]
    if start < self.scroll:
      self.scroll = start
    elif end > self.scroll + room:
      self.scroll = max(start, end - room) if end - start > room else end - room

  # Overlays

  def _help_lines(self, width: int) -> List[Line]:
    keys = [
      ("q", "Quit"),
      ("r", "Refresh every collector now, reusing nothing"),
      ("↑ ↓ ← →  j k", "Select a card"),
      ("Enter, Space", "Show or hide the selected card's details"),
      ("e", "Show or hide every card's details"),
      ("l", "Sign the selected agent in (runs its CLI's login here)"),
      ("s", "Settings"),
      ("PgUp PgDn  g G", "Scroll"),
      ("Esc", "Close this"),
    ]
    out: List[Line] = [[(f"  agents-tui {__version__}", "bold")], []]
    for key, text in keys:
      out.append([(f"  {key:<16}", "accent"), (text, "")])
    out.append([])
    for label, value in (
      ("Settings", str(self.cfg_path)),
      ("Records", str(self.cfg.records_dir())),
      ("Collector log", str(paths.cache_dir() / "collect.log")),
    ):
      out.append([(f"  {label:<16}", "dim"), (value, "")])
    return out

  def _settings_items(self) -> List[Tuple[str, str]]:
    """(kind, key) rows: the interval, notifications, then each provider."""
    return [("interval", ""), ("notify", "")] + [("provider", p) for p in paths.collector_ids()]

  def _settings_line_of(self, index: int) -> int:
    # Two lines of title, then the two settings, a blank and a heading.
    return 2 + index if index < 2 else 2 + index + 2

  def _provider_name(self, pid: str) -> str:
    record = self.store.records.get(pid)
    return record.name if record else pid

  def _settings_lines(self, width: int) -> List[Line]:
    g = self.glyphs
    out: List[Line] = [[("  Settings", "bold"), (f"  saved to {self.cfg_path}", "dim")], []]
    items = self._settings_items()
    for index, (kind, key) in enumerate(items):
      if kind == "provider" and items[index - 1][0] != "provider":
        out += [[], [("  Providers", "bold"), ("  (Space switches one on or off)", "dim")]]
      cursor = index == self.settings_cursor
      mark = (g.marker if cursor else " ", "selected" if cursor else "")
      style = "selected" if cursor else ""
      if kind == "interval":
        value = present.format_duration(self.cfg.refresh_interval).replace(" 0m", "")
        out.append([mark, (" Refresh every   ", style), ("< ", "dim"), (value, "accent"), (" >", "dim")])
      elif kind == "notify":
        out.append([mark, (" Notify at 90%   ", style), ("on" if self.cfg.notify else "off", "accent")])
      else:
        on = self.cfg.enabled(key)
        box = ("[x] " if on else "[ ] ")
        record = self.store.records.get(key)
        seen = record is not None and record.has_data
        out.append([mark, (" " + box, "accent" if on else "dim"), (self._provider_name(key), style),
                    (f"  {key}" + ("" if seen else f" {g.dot} not in use here"), "dim")])
    return out

  def _settings_key(self, key: int) -> None:
    items = self._settings_items()
    kind, pid = items[self.settings_cursor]
    if key in (curses.KEY_UP, ord("k")):
      self.settings_cursor = max(0, self.settings_cursor - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
      self.settings_cursor = min(len(items) - 1, self.settings_cursor + 1)
    elif kind == "interval" and key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("h"), ord("l"), ord(" ")):
      choices = sorted(set(INTERVALS + [self.cfg.refresh_interval]))
      i = choices.index(self.cfg.refresh_interval)
      step = -1 if key in (curses.KEY_LEFT, ord("h")) else 1
      self.cfg.refresh_interval = choices[max(0, min(len(choices) - 1, i + step))]
      self.scheduler.restart_timer(time.time())
      self._save()
    elif kind == "notify" and key in (ord(" "), 10, 13, curses.KEY_ENTER, curses.KEY_LEFT, curses.KEY_RIGHT):
      self.cfg.notify = not self.cfg.notify
      self._save()
    elif kind == "provider" and key in (ord(" "), 10, 13, curses.KEY_ENTER):
      if self.cfg.enabled(pid):
        self.cfg.disabled.append(pid)
      else:
        self.cfg.disabled = [p for p in self.cfg.disabled if p != pid]
        self.scheduler.request(Kind.NORMAL, only=[pid])
      self._save()
      self._on_records()

  def _save(self) -> None:
    try:
      config_mod.save_settings(self.cfg, self.cfg_path)
    except OSError as error:
      self._say(f"Couldn't save settings: {error}")

  # Keys

  def _move(self, step: int) -> None:
    ids = [r.id for r in self._visible()]
    if not ids:
      return
    index = ids.index(self.selected) if self.selected in ids else 0
    self.selected = ids[max(0, min(len(ids) - 1, index + step))]

  def _handle(self, key: int) -> bool:
    if key == curses.KEY_RESIZE:
      curses.update_lines_cols()
      return True
    if self.overlay != Overlay.NONE:
      if key in (27, ord("q"), ord("?")) or (key == ord("s") and self.overlay == Overlay.SETTINGS):
        self.overlay = Overlay.NONE
      elif self.overlay == Overlay.SETTINGS:
        self._settings_key(key)
      return True

    height, width = self.stdscr.getmaxyx()
    cols = render.columns_for(width, len(self._visible()))
    if key in (ord("q"), ord("Q")):
      return False
    if key in (curses.KEY_DOWN, ord("j")):
      self._move(cols)
    elif key in (curses.KEY_UP, ord("k")):
      self._move(-cols)
    elif key == curses.KEY_RIGHT:
      self._move(1)
    elif key == curses.KEY_LEFT:
      self._move(-1)
    elif key in (ord("g"), curses.KEY_HOME):
      self._move(-10_000)
      self.scroll = 0
    elif key in (ord("G"), curses.KEY_END):
      self._move(10_000)
    elif key == curses.KEY_NPAGE:
      self.scroll += max(1, height - 4)
    elif key == curses.KEY_PPAGE:
      self.scroll = max(0, self.scroll - max(1, height - 4))
    elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
      if self.selected:
        self.expanded ^= {self.selected}
    elif key == ord("e"):
      ids = {r.id for r in self._visible()}
      self.expanded = set() if self.expanded >= ids and ids else ids
    elif key in (ord("r"), ord("R")):
      if self.cfg.collect:
        self.scheduler.request(Kind.FORCE)
        self._say("Refreshing every collector")
      else:
        self.store._seen = {}
        self._say("Reread the records (collecting is off)")
    elif key == ord("l"):
      self._sign_in()
    elif key == ord("s"):
      self.overlay = Overlay.SETTINGS
    elif key in (ord("?"), ord("h"), curses.KEY_F1):
      self.overlay = Overlay.HELP
    return True

  def _sign_in(self) -> None:
    record = self.store.records.get(self.selected or "")
    if record is None:
      return
    command = present.SIGN_IN_COMMANDS.get(record.id)
    if not command:
      help_text = record.auth_help_text.replace("`", "")
      self._say(help_text or f"agents-tui doesn't know how to sign {record.name} in")
      return
    if not shutil.which(command[0]):
      self._say(f"{command[0]} isn't on your PATH")
      return
    curses.def_prog_mode()
    curses.endwin()
    print(f"\nagents-tui: running `{' '.join(command)}` for {record.name}. Ctrl-C cancels.\n", flush=True)
    try:
      subprocess.call(command)
    except KeyboardInterrupt:
      pass
    try:
      input("\nPress Enter to return to agents-tui")
    except (EOFError, KeyboardInterrupt):
      pass
    curses.reset_prog_mode()
    self.stdscr.clear()
    try:
      curses.curs_set(0)
    except curses.error:
      pass
    self.scheduler.request(Kind.FORCE, only=[record.id])
