"""One agent's usage record, as Omarchy's docs/agent-usage-collectors.md defines it.

Every field is read leniently: the format grows over time, and a field this
version doesn't know, or one of an unexpected type, must not cost the rest
of the record.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _str(d: Dict[str, Any], key: str, default: str = "") -> str:
  value = d.get(key)
  return value if isinstance(value, str) else default


def _bool(d: Dict[str, Any], key: str, default: bool = False) -> bool:
  value = d.get(key)
  return value if isinstance(value, bool) else default


def _num(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
  value = d.get(key)
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return default
  if value != value or value in (float("inf"), float("-inf")):
    return default
  return float(value)


def _int(d: Dict[str, Any], key: str, default: int = 0) -> int:
  value = d.get(key)
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return default
  try:
    return int(value)
  except (ValueError, OverflowError):
    return default


def _list(d: Dict[str, Any], key: str) -> List[Any]:
  value = d.get(key)
  return value if isinstance(value, list) else []


def _dicts(d: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
  return [x for x in _list(d, key) if isinstance(x, dict)]


_FRACTION = re.compile(r"\.\d+")


def parse_iso(value: str) -> Optional[float]:
  """Epoch seconds from a collector time, or None.

  Collectors write ISO 8601, sometimes with microseconds or a Z, which
  Python 3.9's fromisoformat doesn't all take.
  """
  if not value:
    return None
  text = _FRACTION.sub("", value.strip())
  if text.endswith(("Z", "z")):
    text = text[:-1] + "+00:00"
  try:
    parsed = dt.datetime.fromisoformat(text)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=dt.timezone.utc)
  return parsed.timestamp()


@dataclass
class UsageLimit:
  label: str = ""
  title: str = ""
  percent: float = 0.0
  resets_at: str = ""

  @classmethod
  def parse(cls, d: Dict[str, Any]) -> "UsageLimit":
    return cls(
      label=_str(d, "label"),
      title=_str(d, "title"),
      percent=min(1.0, max(0.0, _num(d, "percent"))),
      resets_at=_str(d, "resetsAt"),
    )

  @property
  def reset_at(self) -> Optional[float]:
    return parse_iso(self.resets_at)


@dataclass
class Balance:
  remaining: float = 0.0
  funded: float = 0.0
  spent: float = 0.0
  currency: str = "USD"
  estimated: bool = False

  @classmethod
  def parse(cls, d: Dict[str, Any]) -> "Balance":
    return cls(
      remaining=_num(d, "remaining"),
      funded=_num(d, "funded"),
      spent=_num(d, "spent"),
      currency=_str(d, "currency", "USD") or "USD",
      estimated=_bool(d, "estimated"),
    )


@dataclass
class Account:
  id: str = ""
  label: str = ""
  email: str = ""
  plan: str = ""
  active: bool = False
  limits: List[UsageLimit] = field(default_factory=list)
  stale: bool = False
  fetched_at: float = 0.0
  usage_status_text: str = ""
  auth_help_text: str = ""

  @classmethod
  def parse(cls, d: Dict[str, Any]) -> "Account":
    return cls(
      id=_str(d, "id"),
      label=_str(d, "label"),
      email=_str(d, "email"),
      plan=_str(d, "plan"),
      active=_bool(d, "active"),
      limits=[UsageLimit.parse(x) for x in _dicts(d, "limits")],
      stale=_bool(d, "stale"),
      fetched_at=_num(d, "fetchedAt"),
      usage_status_text=_str(d, "usageStatusText"),
      auth_help_text=_str(d, "authHelpText"),
    )


@dataclass
class ModelUsage:
  input_tokens: int = 0
  output_tokens: int = 0
  cache_read: int = 0
  cache_write: int = 0

  @classmethod
  def parse(cls, d: Dict[str, Any]) -> "ModelUsage":
    return cls(
      input_tokens=_int(d, "inputTokens"),
      output_tokens=_int(d, "outputTokens"),
      cache_read=_int(d, "cacheReadInputTokens"),
      cache_write=_int(d, "cacheCreationInputTokens"),
    )

  @property
  def total(self) -> int:
    return self.input_tokens + self.output_tokens + self.cache_read + self.cache_write


@dataclass
class RecentDay:
  date: str = ""
  tokens: int = 0  # the collectors keep tokens in messageCount


@dataclass
class UsageRecord:
  id: str = ""
  name: str = ""
  updated_at: str = ""
  ready: bool = False
  tier_label: str = ""
  usage_status_text: str = ""
  auth_help_text: str = ""
  limits: List[UsageLimit] = field(default_factory=list)
  limits_stale: bool = False
  limits_fetched_at: float = 0.0
  retry_advised: bool = False
  balance: Optional[Balance] = None
  accounts: List[Account] = field(default_factory=list)
  switch_threshold: float = 95.0
  has_local_stats: bool = False
  has_prompt_stats: bool = True
  scope: str = ""
  today_prompts: int = 0
  today_sessions: int = 0
  today_total_tokens: int = 0
  today_tokens_by_model: Dict[str, int] = field(default_factory=dict)
  recent_days: List[RecentDay] = field(default_factory=list)
  total_prompts: int = 0
  total_sessions: int = 0
  active_days: int = 0
  model_usage: Dict[str, ModelUsage] = field(default_factory=dict)
  raw: Dict[str, Any] = field(default_factory=dict, repr=False)

  @classmethod
  def parse(cls, d: Dict[str, Any], fallback_id: str = "") -> "UsageRecord":
    rid = _str(d, "id") or fallback_id
    balance = d.get("balance")
    switch = d.get("accountSwitch")
    by_model = d.get("todayTokensByModel")
    usage = d.get("modelUsage")
    return cls(
      id=rid,
      name=_str(d, "name") or rid,
      updated_at=_str(d, "updatedAt"),
      ready=_bool(d, "ready"),
      tier_label=_str(d, "tierLabel"),
      usage_status_text=_str(d, "usageStatusText"),
      auth_help_text=_str(d, "authHelpText"),
      limits=[UsageLimit.parse(x) for x in _dicts(d, "limits")],
      limits_stale=_bool(d, "limitsStale"),
      limits_fetched_at=_num(d, "limitsFetchedAt"),
      retry_advised=_bool(d, "retryAdvised"),
      balance=Balance.parse(balance) if isinstance(balance, dict) else None,
      accounts=[Account.parse(x) for x in _dicts(d, "accounts")],
      switch_threshold=_num(switch, "threshold", 95.0) if isinstance(switch, dict) else 95.0,
      has_local_stats=_bool(d, "hasLocalStats"),
      has_prompt_stats=_bool(d, "hasPromptStats", True),
      scope=_str(d, "scope"),
      today_prompts=_int(d, "todayPrompts"),
      today_sessions=_int(d, "todaySessions"),
      today_total_tokens=_int(d, "todayTotalTokens"),
      today_tokens_by_model={
        str(k): _int(by_model, k) for k in by_model
      } if isinstance(by_model, dict) else {},
      recent_days=[
        RecentDay(date=_str(x, "date"), tokens=_int(x, "messageCount")) for x in _dicts(d, "recentDays")
      ],
      total_prompts=_int(d, "totalPrompts"),
      total_sessions=_int(d, "totalSessions"),
      active_days=_int(d, "activeDays"),
      model_usage={
        str(k): ModelUsage.parse(v) for k, v in usage.items() if isinstance(v, dict)
      } if isinstance(usage, dict) else {},
      raw=d,
    )

  @property
  def has_data(self) -> bool:
    """Omarchy's providerHasData, plus a record with a status.

    An agent earns a card by having produced numbers, not merely by having a
    record. A collector leaves the status empty for an agent this machine
    doesn't use, so "Waiting for auth" means one that's installed but signed
    out, and its card is where to sign back in.
    """
    return bool(
      self.total_prompts or self.total_sessions or self.active_days or self.today_prompts
      or self.today_sessions or self.limits or self.accounts or self.balance is not None
      or (self.ready and self.tier_label) or self.usage_status_text
    )

  @property
  def updated(self) -> Optional[float]:
    return parse_iso(self.updated_at)


def load_file(path: Path) -> Optional[UsageRecord]:
  try:
    with open(path, encoding="utf-8") as handle:
      data = json.load(handle)
  except (OSError, ValueError, UnicodeDecodeError):
    return None
  if not isinstance(data, dict):
    return None
  return UsageRecord.parse(data, fallback_id=path.stem)
