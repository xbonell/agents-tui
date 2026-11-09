"""How the records read: Omarchy's Panel.qml logic, by way of agents-macos.

Limit windows and their titles, durations, statuses, the notification rule
and the header's summary phrases. Nothing here draws; render.py does.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .record import Balance, UsageLimit, UsageRecord

ALARM = 0.9
REARM = 0.85


@dataclass
class Scoped:
  title: str
  percent: float


@dataclass
class LimitWindow:
  title: str
  percent: float
  reset_at: Optional[float]
  # Model-scoped allowances on the same clock ("Opus" on Weekly).
  scoped: List[Scoped] = field(default_factory=list)


# Windows

def window_is_long(text: str) -> bool:
  return any(word in text for word in ("week", "7-day", "seven", "month", "30-day"))


def _first_number(text: str, pattern: str) -> Optional[float]:
  match = re.search(pattern, text)
  if not match:
    return None
  digits = re.match(r"\d+", match.group(0))
  return float(digits.group(0)) if digits else None


def window_span(label: str) -> float:
  text = label.lower()
  if "month" in text or "30-day" in text:
    return 30 * 24 * 3600
  if window_is_long(text):
    return 7 * 24 * 3600
  hours = _first_number(text, r"(\d+)\s*-?\s*h(?:our)?\b")
  if hours is not None:
    return hours * 3600
  minutes = _first_number(text, r"(\d+)\s*-?\s*m(?:in(?:ute)?s?)?\b")
  if minutes is not None:
    return minutes * 60
  return 0


def window_title(label: str) -> str:
  text = label.lower()
  if "month" in text:
    return "Monthly"
  if window_is_long(text):
    return "Weekly"
  if "session" in text or window_span(label) > 0:
    return "Session"
  plain = re.sub(r"\s*\(.*\)\s*", "", label).strip()
  return plain or "Limit"


def limit_windows(limits: Iterable[UsageLimit], now: float) -> List[LimitWindow]:
  """A collector that knows a limit's window says so in `title`, which beats
  reading it out of the label. A window whose reset has passed is untouched
  again, not unknown."""
  out = []
  for limit in limits:
    reset = limit.reset_at
    expired = reset is not None and reset <= now
    out.append(LimitWindow(
      title=limit.title or window_title(limit.label),
      percent=0.0 if expired else limit.percent,
      reset_at=None if expired else reset,
    ))
  return out


_SCOPED = re.compile(r"^(.+) (Session|Weekly|Monthly)$")


def scoped_part(title: str) -> Optional[Tuple[str, str]]:
  match = _SCOPED.match(title)
  return (match.group(1), match.group(2)) if match else None


def display_windows(limits: Iterable[UsageLimit], now: float) -> List[LimitWindow]:
  """A model-scoped window rides on the row of the window it's named for; one
  with nothing to attach to keeps a row of its own."""
  windows = limit_windows(limits, now)
  out = [w for w in windows if scoped_part(w.title) is None]
  for window in windows:
    part = scoped_part(window.title)
    if part is None:
      continue
    parent = next((w for w in out if w.title == part[1]), None)
    if parent is not None:
      parent.scoped.append(Scoped(part[0], window.percent))
    else:
      out.append(window)
  return out


def binding_window(record: UsageRecord, now: float) -> Optional[LimitWindow]:
  """The fullest window: what stops the next prompt."""
  windows = limit_windows(record.limits, now)
  return max(windows, key=lambda w: w.percent) if windows else None


def format_duration(seconds: float) -> str:
  if seconds <= 0:
    return "now"
  minutes = int(seconds / 60)
  hours = minutes // 60
  days = hours // 24
  if days > 0:
    return f"{days}d {hours % 24}h"
  if hours > 0:
    return f"{hours}h {minutes % 60}m"
  return f"{max(1, minutes)}m"


def reset_text(window: LimitWindow, now: float) -> str:
  if window.reset_at is not None and window.reset_at > now:
    return "resets in " + format_duration(window.reset_at - now)
  return ""


def stale_text(record: UsageRecord, now: float) -> str:
  """How old kept numbers are, once a check failed."""
  if not record.limits_stale:
    return ""
  fetched = record.limits_fetched_at
  if fetched <= 0:
    return "Last updated time unavailable"
  age = now - fetched / 1000
  if age > 60:
    return f"Last updated {format_duration(age)} ago"
  return "Last updated less than a minute ago"


# Status

def updated_text(records: Iterable[UsageRecord], now: float, running: bool) -> str:
  if running:
    return "Updating…"
  times = [t for t in (r.updated for r in records) if t is not None]
  if not times:
    return ""
  age = now - max(times)
  return "Updated just now" if age < 60 else f"Updated {format_duration(age)} ago"


# The commands that sign each agent's CLI in again, as its collector's help
# text names them. Only these ever run; a record's own text never does.
SIGN_IN_COMMANDS: Dict[str, List[str]] = {
  "claude": ["claude", "auth", "login"],
  "codex": ["codex", "login"],
  "cursor": ["cursor-agent", "login"],
  "opencode": ["opencode", "auth", "login"],
  "grok": ["grok", "login"],
}


def plan_label(record: UsageRecord) -> str:
  tier = record.tier_label
  return tier[:1].upper() + tier[1:] if tier else ""


def needs_sign_in(record: UsageRecord) -> bool:
  """A lapsed or missing sign-in is the one trouble that has its own line."""
  return record.usage_status_text in ("Sign-in expired", "Waiting for auth")


def usage_note(record: UsageRecord) -> str:
  """Whatever keeps the numbers from being current, said beside the last
  ones known. A failed refresh with numbers kept may say why only in its help."""
  if needs_sign_in(record):
    return ""
  status = record.usage_status_text
  if not status and not (record.limits_stale and record.auth_help_text):
    return ""
  return record.auth_help_text or status


def balance_alarming(balance: Optional[Balance]) -> bool:
  if balance is None or balance.funded <= 0:
    return False
  return balance.remaining / balance.funded <= 0.1


def record_alarming(record: UsageRecord, now: float) -> bool:
  window = binding_window(record, now)
  return (window is not None and window.percent >= ALARM) or balance_alarming(record.balance)


def alarming(records: Iterable[UsageRecord], now: float) -> bool:
  return any(record_alarming(r, now) for r in records)


def near_switch_threshold(records: Iterable[UsageRecord]) -> bool:
  """While an agent with several accounts has its active one within 15
  points of its switch threshold, limits are checked every three minutes."""
  for record in records:
    if len(record.accounts) < 2:
      continue
    start = min(0.8, (record.switch_threshold - 15) / 100)
    if any(limit.percent >= start for limit in record.limits):
      return True
  return False


# Notifications

@dataclass
class LimitAlert:
  key: str
  title: str
  body: str


_PLAIN_WINDOWS = ("Session", "Weekly", "Monthly", "Limit", "Spend limit")


def notifications_due(records: Iterable[UsageRecord], now: float, sent: Set[str]) -> Tuple[List[LimitAlert], Set[str]]:
  """What to notify about, and what stays sent.

  Each window at 90%, and a balance down to its last 10%, once per window
  per reset. A key names the window and its reset to the minute (Claude's
  reset times move in their microseconds between checks). One that stays
  between 85% and 90% stays sent, so a figure hovering at the line doesn't
  repeat; anything lower, reset, or gone drops out and can alert again.
  """
  alerts: List[LimitAlert] = []
  kept: Set[str] = set()

  def consider(key: str, level: float, make) -> None:
    if level >= ALARM:
      if key not in sent:
        alerts.append(make())
      kept.add(key)
    elif level >= REARM and key in sent:
      kept.add(key)

  for record in records:
    for window in limit_windows(record.limits, now):
      minute = str(int(window.reset_at // 60)) if window.reset_at is not None else ""
      key = f"{record.id}|{window.title}|{minute}"

      def make(record=record, window=window, key=key) -> LimitAlert:
        part = scoped_part(window.title)
        if part:
          name = part[0]
        elif window.title in _PLAIN_WINDOWS:
          name = window.title.lower()
        else:
          name = window.title
        body = reset_text(window, now)
        return LimitAlert(key, f"{record.name} {name} at {round(window.percent * 100)}%", body[:1].upper() + body[1:])

      consider(key, window.percent, make)
    balance = record.balance
    if balance is not None and balance.funded > 0:
      key = f"{record.id}|balance"

      def make_balance(record=record, balance=balance, key=key) -> LimitAlert:
        left = format_money(balance.remaining, balance.currency)
        return LimitAlert(key, f"{record.name} balance low", f"{left} left of {format_money(balance.funded, balance.currency)}")

      # Measured as what's spent, so the same "higher is worse" rule applies.
      consider(key, 1 - balance.remaining / balance.funded, make_balance)
  return alerts, kept


def format_money(value: float, currency: str) -> str:
  symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency.upper(), currency.upper() + " ")
  return f"{symbol}{value:,.2f}"


def balance_detail(balance: Balance) -> str:
  if balance.funded <= 0:
    return ""
  text = f"{format_money(balance.spent, balance.currency)} spent of {format_money(balance.funded, balance.currency)} funded"
  return text + " · estimated" if balance.estimated else text


# Summary

def _plural(count: int, noun: str, shown: str) -> str:
  return f"{shown} {noun}{'' if count == 1 else 's'}"


def format_tokens(n: int) -> str:
  if n >= 1e9:
    return f"{n / 1e9:.1f}B"
  if n >= 1e6:
    return f"{n / 1e6:.1f}M"
  if n >= 1e3:
    return f"{n / 1e3:.1f}K"
  return f"{n:,}"


def _day_name(date: str) -> str:
  try:
    return dt.date.fromisoformat(date).strftime("%A")
  except ValueError:
    return date


def _top(counts: Dict[str, int]) -> Optional[Tuple[str, int]]:
  """The largest count, ties going to the first name alphabetically."""
  if not counts:
    return None
  return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def summary_phrases(records: Iterable[UsageRecord]) -> List[str]:
  """What the token counts add up to across every agent: the header's
  rotating line."""
  week = today = prompts = sessions = 0
  by_day: Dict[str, int] = {}
  by_model: Dict[str, int] = {}
  for record in records:
    for day in record.recent_days:
      week += day.tokens
      by_day[day.date] = by_day.get(day.date, 0) + day.tokens
    today += record.today_total_tokens
    if record.has_prompt_stats:
      prompts += record.today_prompts
      sessions += record.today_sessions
    for model_id, usage in record.model_usage.items():
      name = friendly_model_name(model_id)
      by_model[name] = by_model.get(name, 0) + usage.total

  phrases = []
  if week > 0:
    phrases.append(_plural(week, "token", format_tokens(week)) + " this week")
  if today > 0:
    phrases.append(_plural(today, "token", format_tokens(today)) + " today")
  top = _top(by_model)
  if top and top[1] > 0:
    phrases.append(f"Mostly {top[0]}")
  busiest = _top(by_day)
  if busiest and busiest[1] > 0:
    phrases.append(f"Busiest day: {_day_name(busiest[0])}")
  if prompts > 0:
    phrases.append(_plural(prompts, "prompt", f"{prompts:,}") + " today")
  if sessions > 0:
    phrases.append(_plural(sessions, "session", f"{sessions:,}") + " today")
  return phrases


def _word_case(word: str) -> str:
  if word == "gpt":
    return "GPT"
  if word == "deepseek":
    return "DeepSeek"
  return word[:1].upper() + word[1:]


def friendly_model_name(model_id: str) -> str:
  """Model ids arrive hyphenated with the version split across segments
  (`claude-opus-5-5`, `gpt-5.6-sol`): rejoin the numeric run into one
  version and title-case the words around it."""
  if not model_id:
    return "Unknown model"
  name = re.sub(r"-\d{8}$", "", re.sub(r"^claude-", "", model_id))
  words: List[str] = []
  version: List[str] = []
  for part in name.split("-"):
    if not part:
      continue
    if part[0].isdigit():
      version.append(part)
      continue
    if version:
      words.append(".".join(version))
      version = []
    words.append(_word_case(part))
  if version:
    words.append(".".join(version))
  return " ".join(words) if words else "Unknown model"


def models_by_tokens(record: UsageRecord) -> List[Tuple[str, int]]:
  """All-time tokens per friendly model name, largest first."""
  totals: Dict[str, int] = {}
  for model_id, usage in record.model_usage.items():
    name = friendly_model_name(model_id)
    totals[name] = totals.get(name, 0) + usage.total
  return sorted(((k, v) for k, v in totals.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
