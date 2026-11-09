"""The panel as styled text lines, shared by the curses UI and `agents-tui print`.

A line is a list of (text, style) segments. Styles are names the front ends
map to attributes: curses colour pairs in the TUI, ANSI escapes in print.
"""

from __future__ import annotations

import textwrap
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import present
from .record import UsageRecord

Segment = Tuple[str, str]
Line = List[Segment]

# Styles: "" plain, "bold", "dim", "accent", "alarm", "warn", "ok",
# "title" (a card's name), "selected" (the selected card's name and border),
# "bar", "bar_alarm", "bar_empty".


@dataclass
class Glyphs:
  full: str
  partial: str  # 1/8 … 7/8 of a cell, or "" for none
  empty: str
  spark: str
  marker: str
  dot: str
  ellipsis: str
  rule: str
  sub: str
  spinner: str
  box: str  # corners top-left, top-right, bottom-left, bottom-right, then horizontal, vertical

  @classmethod
  def make(cls, ascii_only: bool) -> "Glyphs":
    if ascii_only:
      return cls("#", "", "-", " .:-=+*#", ">", "-", "...", "-", "+", "|/-\\", "++++-|")
    return cls("█", "▏▎▍▌▋▊▉", "░", "▁▂▃▄▅▆▇█", "▌", "·", "…", "─", "↳", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "╭╮╰╯─│")


@dataclass
class View:
  records: List[UsageRecord]
  now: float
  glyphs: Glyphs
  phrase: str = ""
  running: bool = False
  frame: int = 0
  next_refresh: Optional[float] = None  # seconds until the next full refresh
  selected: Optional[str] = None
  expanded: Set[str] = field(default_factory=set)
  errors: Dict[str, str] = field(default_factory=dict)  # provider -> collector failure
  collecting: bool = True
  footer: bool = True
  message: str = ""


# Text measurement

def cell_width(text: str) -> int:
  width = 0
  for ch in text:
    if unicodedata.combining(ch):
      continue
    width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
  return width


def clip_text(text: str, width: int, ellipsis: str = "") -> str:
  if width <= 0:
    return ""
  if cell_width(text) <= width:
    return text
  room = width - cell_width(ellipsis)
  out, used = [], 0
  for ch in text:
    w = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
    if used + w > room:
      break
    out.append(ch)
    used += w
  return "".join(out) + (ellipsis if room >= 0 else "")


def line_width(line: Line) -> int:
  return sum(cell_width(text) for text, _ in line)


def clip(line: Line, width: int) -> Line:
  out: Line = []
  used = 0
  for text, style in line:
    w = cell_width(text)
    if used + w <= width:
      out.append((text, style))
      used += w
      continue
    rest = clip_text(text, width - used)
    if rest:
      out.append((rest, style))
    break
  return out


def pad(line: Line, width: int) -> Line:
  line = clip(line, width)
  gap = width - line_width(line)
  return line + [(" " * gap, "")] if gap > 0 else line


def spread(left: Line, right: Line, width: int) -> Line:
  """`left`, then `right` flush with the right edge when both fit."""
  gap = width - line_width(left) - line_width(right)
  if gap < 1 or not right:
    return clip(left, width)
  return left + [(" " * gap, "")] + right


# Pieces

def meter(fraction: float, width: int, alarm: bool, g: Glyphs) -> Line:
  fraction = min(1.0, max(0.0, fraction))
  width = max(1, width)
  if g.partial:
    eighths = int(round(fraction * width * 8))
    full, part = divmod(eighths, 8)
  else:
    full, part = int(round(fraction * width)), 0
  full = min(full, width)
  style = "bar_alarm" if alarm else "bar"
  out: Line = []
  if full:
    out.append((g.full * full, style))
  used = full
  if part and used < width:
    out.append((g.partial[part - 1], style))
    used += 1
  if used < width:
    out.append((g.empty * (width - used), "bar_empty"))
  return out


def sparkline(values: Sequence[int], g: Glyphs) -> str:
  top = max(values) if values else 0
  if top <= 0:
    return g.spark[0] * len(values)
  steps = len(g.spark) - 1
  return "".join(g.spark[0] if v <= 0 else g.spark[max(1, int(round(v / top * steps)))] for v in values)


def wrap(text: str, width: int, style: str, indent: int) -> List[Line]:
  lines = textwrap.wrap(text.replace("`", ""), max(10, width - indent)) or [""]
  return [[(" " * indent + piece, style)] for piece in lines]


# A card

LABEL_MIN, LABEL_MAX = 7, 12
INDENT = 0  # the box's padding indents a card's lines
RESET_W = 17


def fit_parts(prefix: Line, parts: Sequence[str], sep: str, style: str, width: int) -> Line:
  """`prefix` and as many of `parts` as fit whole."""
  line = list(prefix)
  for i, part in enumerate(parts):
    piece = (sep if i else "") + part
    if line_width(line) + cell_width(piece) > width:
      break
    line.append((piece, style))
  return line


def _stats_parts(record: UsageRecord) -> List[str]:
  parts = []
  if record.today_total_tokens:
    parts.append(present.format_tokens(record.today_total_tokens) + " tokens")
  if record.has_prompt_stats and record.today_prompts:
    parts.append(f"{record.today_prompts:,} prompt" + ("" if record.today_prompts == 1 else "s"))
  if record.has_prompt_stats and record.today_sessions:
    parts.append(f"{record.today_sessions:,} session" + ("" if record.today_sessions == 1 else "s"))
  return parts or ["nothing yet"]


def _has_stats(record: UsageRecord) -> bool:
  return bool(
    record.today_total_tokens or record.total_prompts or any(d.tokens for d in record.recent_days)
  )


def card(record: UsageRecord, width: int, view: View) -> List[Line]:
  """A card's lines inside its box; `frame` draws the box and the name."""
  g, now = view.glyphs, view.now
  lines: List[Line] = []

  if present.needs_sign_in(record):
    line: Line = [(" " * INDENT, ""), ("! Sign-in required", "warn")]
    command = present.SIGN_IN_COMMANDS.get(record.id)
    if command:
      long = line + [(f" {g.dot} press ", "dim"), ("l", "accent"), (" to run " + " ".join(command), "dim")]
      short = line + [(f" {g.dot} ", "dim"), ("l", "accent"), (" to sign in", "dim")]
      line = long if line_width(long) <= width else short
    lines.append(clip(line, width))

  note = present.usage_note(record)
  if note:
    lines += wrap(note, width, "warn", INDENT)
  stale = present.stale_text(record, now)
  if stale:
    lines.append(clip([(" " * INDENT + stale, "dim")], width))
  error = view.errors.get(record.id)
  if error:
    lines += wrap("Collector failed: " + error, width, "alarm", INDENT)

  windows = present.display_windows(record.limits, now)
  labels = [w.title for w in windows] + (["Balance"] if record.balance else [])
  label_w = max([LABEL_MIN] + [min(LABEL_MAX, cell_width(t)) for t in labels])
  resets = [present.reset_text(w, now) for w in windows]
  # A fixed reset column ("resets in 16d 16h") keeps every card's meters
  # the same length, whichever resets each shows.
  reset_w = RESET_W
  pct_w = 5  # " 100%"
  fixed = INDENT + label_w + 1 + pct_w
  inline = width - fixed - (reset_w + 2) >= 12
  bar_w = width - fixed - ((reset_w + 2) if inline else 0)
  bar_w = max(4, min(bar_w, 60))

  for window, reset in zip(windows, resets):
    alarm = window.percent >= present.ALARM
    label = clip_text(window.title, label_w, g.ellipsis).ljust(label_w)
    row: Line = [(" " * INDENT + label + " ", "")]
    row += meter(window.percent, bar_w, alarm, g)
    row.append((f"{round(window.percent * 100):>4d}%", "alarm" if alarm else ""))
    if reset and inline:
      row.append(("  " + reset, "dim"))
    lines.append(clip(row, width))
    if reset and not inline:
      lines.append(clip([(" " * (INDENT + label_w + 1) + reset, "dim")], width))
    if window.scoped:
      text = ", ".join(f"{s.title} {round(s.percent * 100)}%" for s in window.scoped)
      lines.append(clip([(" " * (INDENT + label_w + 1) + g.sub + " " + text, "dim")], width))

  balance = record.balance
  if balance is not None:
    alarm = present.balance_alarming(balance)
    label = "Balance".ljust(label_w)
    left = present.format_money(balance.remaining, balance.currency) + " left"
    row = [(" " * INDENT + label + " ", "")]
    balance_w = min(bar_w, width - INDENT - label_w - 1 - 2 - cell_width(left))
    if balance.funded > 0 and balance_w >= 4:
      row += meter(balance.remaining / balance.funded, balance_w, alarm, g)
      row.append(("  " + left, "alarm" if alarm else ""))
    else:
      row.append((left, "alarm" if alarm else ""))
    lines.append(clip(row, width))
    detail = present.balance_detail(balance)
    if detail:
      lines.append(clip([(" " * (INDENT + label_w + 1) + detail, "dim")], width))

  if not windows and balance is None and not present.needs_sign_in(record) and not note:
    lines.append(clip([(" " * INDENT + "No limits for this plan", "dim")], width))

  if _has_stats(record):
    spark = sparkline([d.tokens for d in record.recent_days[-7:]], g) if record.recent_days else ""
    right = [("7d ", "dim"), (spark, "accent")] if spark else []
    parts = _stats_parts(record)
    prefix: Line = [(" " * INDENT + "Today ", "dim")]
    left = fit_parts(prefix, parts, f" {g.dot} ", "dim", width)
    full = len(left) - len(prefix) == len(parts)
    if not full or line_width(left) + line_width(right) + 3 > width:
      right = []
    lines.append(spread(left, right, width))

  if record.id in view.expanded:
    lines += details(record, width, view)
  return lines


def frame(record: UsageRecord, inner: List[Line], width: int, height: int, view: View) -> List[Line]:
  """`inner` boxed to `width` and `height` rows, the name and plan in the top edge."""
  g = view.glyphs
  tl, tr, bl, br, h, v = g.box
  selected = record.id == view.selected
  edge = "selected" if selected else "dim"
  name_style = "selected" if selected else "title"
  if present.record_alarming(record, view.now):
    name_style = "alarm"
  plan = present.plan_label(record)
  if record.scope == "account" and plan:
    plan += " (account)"

  room = width - 4  # tl, h, and h, tr around the title
  name = clip_text(record.name, room - 2, g.ellipsis)
  left: Line = [(tl + h, edge), (" " + name + " ", name_style)] if name else [(tl + h, edge)]
  right: Line = [(" " + plan + " ", "dim"), (h + tr, edge)] if plan else [(h + tr, edge)]
  if line_width(left) + line_width(right) + 1 > width:
    right = [(h + tr, edge)]
  fill = width - line_width(left) - line_width(right)
  top = clip(left + [(h * max(0, fill), edge)] + right, width)

  out: List[Line] = [top]
  for i in range(height):
    part = inner[i] if i < len(inner) else []
    out.append([(v + " ", edge)] + pad(part, width - 4) + [(" " + v, edge)])
  out.append([(bl + h * (width - 2) + br, edge)])
  return out


def details(record: UsageRecord, width: int, view: View) -> List[Line]:
  g = view.glyphs
  out: List[Line] = []
  sub = INDENT + 2

  week = sum(d.tokens for d in record.recent_days)
  if week:
    out.append(clip([(" " * sub + "Last 7 days ", "dim"), (present.format_tokens(week) + " tokens", "")], width))
  totals = []
  if record.has_prompt_stats and record.total_prompts:
    totals.append(f"{record.total_prompts:,} prompts")
  if record.has_prompt_stats and record.total_sessions:
    totals.append(f"{record.total_sessions:,} sessions")
  if record.active_days:
    totals.append(f"{record.active_days:,} active days")
  if totals:
    out.append(fit_parts([(" " * sub + "All time    ", "dim")], totals, f" {g.dot} ", "", width))

  models = present.models_by_tokens(record)[:6]
  if models:
    out.append([(" " * sub + "Models", "dim")])
    name_w = min(24, max(cell_width(m) for m, _ in models))
    top = models[0][1]
    bar_w = max(4, min(30, width - sub - 2 - name_w - 9))
    for name, tokens in models:
      row: Line = [(" " * (sub + 2) + clip_text(name, name_w, g.ellipsis).ljust(name_w) + " ", "")]
      row.append((f"{present.format_tokens(tokens):>7} ", "dim"))
      row += meter(tokens / top if top else 0, bar_w, False, g)
      out.append(clip(row, width))

  for account in record.accounts:
    who = account.label or account.email or account.id
    windows = present.limit_windows(account.limits, view.now)
    fullest = max((w.percent for w in windows), default=None)
    row = [(" " * sub + (g.marker if account.active else " ") + " " + who, "accent" if account.active else "")]
    if account.plan:
      row.append((f" {g.dot} {account.plan}", "dim"))
    if fullest is not None:
      row.append((f" {g.dot} {round(fullest * 100)}%", "alarm" if fullest >= present.ALARM else "dim"))
    if account.usage_status_text:
      row.append((f" {g.dot} {account.usage_status_text}", "warn"))
    out.append(clip(row, width))

  if record.auth_help_text and present.needs_sign_in(record):
    out += wrap(record.auth_help_text, width, "dim", sub)
  if not out:
    out.append([(" " * sub + "No local stats", "dim")])
  return out


# The screen

@dataclass
class Body:
  lines: List[Line]
  spans: Dict[str, Tuple[int, int]]  # card id -> first line, line after the last


GAP = 1
CARD_MIN = 56


def columns_for(width: int, count: int) -> int:
  return max(1, min(3, count, (width + GAP) // (CARD_MIN + GAP)))


def body(view: View, width: int) -> Body:
  records = view.records
  if not records:
    return Body(empty_message(view, width), {})
  cols = columns_for(width, len(records))
  col_w = (width - GAP * (cols - 1)) // cols
  lines: List[Line] = []
  spans: Dict[str, Tuple[int, int]] = {}
  for start in range(0, len(records), cols):
    row = records[start:start + cols]
    inner = [card(r, col_w - 4, view) for r in row]
    height = max(len(b) for b in inner)
    # Every box in a row gets the row's height, so their edges line up.
    blocks = [frame(r, b, col_w, height, view) for r, b in zip(row, inner)]
    top = len(lines)
    for i in range(height + 2):
      line: Line = []
      for c, block in enumerate(blocks):
        if c:
          line.append((" " * GAP, ""))
        line += block[i]
      lines.append(line)
    for r in row:
      spans[r.id] = (top, top + height + 2)
  return Body(lines, spans)


def empty_message(view: View, width: int) -> List[Line]:
  if view.running:
    return [[("  Looking for agents on this machine" + view.glyphs.ellipsis, "dim")]]
  text = [
    "No agent usage found yet.",
    "",
    "agents-tui shows Claude Code, Codex, Cursor, OpenCode and the other agents Omarchy's",
    "collectors know, once one of them is signed in or has been used on this machine.",
    "",
    "Run `agents-tui doctor` to see what each collector found.",
  ]
  if not view.collecting:
    text.insert(1, "Collecting is off (collect = false); records come from the usage_dir in the config.")
  out: List[Line] = []
  for paragraph in text:
    out += wrap(paragraph, width, "dim", 2) if paragraph else [[]]
  return out


def header(view: View, width: int) -> List[Line]:
  g = view.glyphs
  left: Line = [(" Agents", "bold")]
  if present.alarming(view.records, view.now):
    left = [(" ! ", "alarm")] + [("Agents", "bold")]
  if view.phrase:
    left.append((f"  {view.phrase}", "dim"))
  status = present.updated_text(view.records, view.now, view.running)
  right: Line = []
  if view.running:
    right.append((g.spinner[view.frame % len(g.spinner)] + " ", "accent"))
    right.append((status, "accent"))
  elif status:
    right.append((status, "dim"))
  if not view.running and view.next_refresh is not None and view.collecting:
    right.append((f" {g.dot} next in {present.format_duration(view.next_refresh)}", "dim"))
  right.append((" ", ""))
  if line_width(left) + line_width(right) + 1 > width:
    left = left[:2] if left and left[0][1] == "alarm" else left[:1]
  return [spread(left, right, width), [(g.rule * width, "dim")]]


KEYS = [
  ("q", "quit"), ("r", "refresh"), ("↑↓", "select"), ("⏎", "details"),
  ("l", "sign in"), ("s", "settings"), ("?", "help"),
]


def footer(view: View, width: int) -> List[Line]:
  out: List[Line] = []
  if view.message:
    out.append(clip([(" " + view.message, "warn")], width))
  failures = [p for p, e in view.errors.items()]
  if failures:
    names = ", ".join(sorted(failures))
    out.append(clip([(f" ! {len(failures)} collector{'s' if len(failures) > 1 else ''} failed: {names}", "warn"),
                     ("  (agents-tui doctor)", "dim")], width))
  keys: Line = [(" ", "")]
  ascii_only = view.glyphs.partial == ""
  for key, label in KEYS:
    if ascii_only:
      key = {"↑↓": "j/k", "⏎": "enter"}.get(key, key)
    keys += [(key, "accent"), (f" {label}  ", "dim")]
  out.append(clip(keys, width))
  return out


# Characters that reach the lines from text rather than Glyphs, for ASCII
# terminals; one cell each, so nothing is measured twice.
_ASCII = str.maketrans({"·": "-", "↳": "+", "↑": "^", "↓": "v", "←": "<", "→": ">", "⏎": "~", "…": "."})


def asciify(lines: List[Line]) -> List[Line]:
  return [[(text.translate(_ASCII), style) for text, style in line] for line in lines]


def screen(view: View, width: int) -> Tuple[List[Line], Body, List[Line]]:
  head, main, foot = header(view, width), body(view, width), footer(view, width) if view.footer else []
  if view.glyphs.partial == "":
    head, foot = asciify(head), asciify(foot)
    main = Body(asciify(main.lines), main.spans)
  return head, main, foot
