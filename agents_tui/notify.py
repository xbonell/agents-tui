"""Near-limit alerts: a desktop notification where the system has one.

What's been sent is remembered in <state dir>/notified.json, seeded on the
first run so nothing old fires, and tracked even while alerts are off.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set

from . import paths
from .present import LimitAlert, notifications_due
from .record import UsageRecord


def _desktop_command(title: str, body: str) -> Optional[List[str]]:
  if paths.DARWIN:
    # The text goes in as arguments, never into the script itself.
    return [
      "osascript",
      "-e", "on run argv",
      "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
      "-e", "end run",
      title, body,
    ]
  if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
    return None  # a console or SSH session has no desktop to notify
  if shutil.which("notify-send"):
    return ["notify-send", "--app-name=agents-tui", title, body]
  return None


def post(alert: LimitAlert) -> bool:
  command = _desktop_command(alert.title, alert.body)
  if command is None:
    return False
  try:
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  except OSError:
    return False
  return True


class Notifier:
  def __init__(self, path: Optional[Path] = None):
    self.path = path or paths.state_dir() / "notified.json"
    self.sent: Optional[Set[str]] = self._load()

  def _load(self) -> Optional[Set[str]]:
    try:
      with open(self.path, encoding="utf-8") as handle:
        data = json.load(handle)
      return {str(x) for x in data.get("sent", [])}
    except (OSError, ValueError, AttributeError):
      return None

  def _save(self) -> None:
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      tmp = self.path.with_name(self.path.name + ".tmp")
      tmp.write_text(json.dumps({"sent": sorted(self.sent or ())}), encoding="utf-8")
      os.replace(tmp, self.path)
    except OSError:
      pass

  def evaluate(self, records: Iterable[UsageRecord], now: float, enabled: bool) -> List[LimitAlert]:
    """The alerts due now, posted when enabled; returns them for the bell."""
    first_run = self.sent is None
    alerts, kept = notifications_due(list(records), now, self.sent or set())
    changed = kept != self.sent
    self.sent = kept
    if changed:
      self._save()
    if first_run or not enabled:
      return []
    for alert in alerts:
      post(alert)
    return alerts
