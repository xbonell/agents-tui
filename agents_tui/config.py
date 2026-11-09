"""The settings file, ~/.config/agents-tui/config.toml.

Every key is optional, and a key of the wrong type is ignored rather than
fatal, so a hand-edited file never stops the panel from starting.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from . import paths

try:
  import tomllib
except ModuleNotFoundError:  # Python < 3.11: tomllib is the vendored tomli
  sys.path.insert(0, str(paths.ROOT / "vendor"))
  import tomli as tomllib  # type: ignore

INTERVALS = [300, 600, 900, 1800, 3600]
MIN_INTERVAL, MAX_INTERVAL = 30, 3600


@dataclass
class Config:
  refresh_interval: int = 900
  disabled: List[str] = field(default_factory=list)
  notify: bool = True
  usage_dir: str = ""
  collect: bool = True
  ascii: str = "auto"  # auto, always, never
  color: str = "auto"  # auto, always, never

  def enabled(self, provider: str) -> bool:
    return provider not in self.disabled

  def records_dir(self) -> Path:
    if self.usage_dir:
      return Path(os.path.expanduser(self.usage_dir))
    return paths.default_usage_dir()


def load(path: Path = None) -> Config:
  path = path or paths.config_file()
  cfg = Config()
  try:
    with open(path, "rb") as handle:
      data = tomllib.load(handle)
  except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
    return cfg
  interval = data.get("refresh_interval")
  if isinstance(interval, int) and not isinstance(interval, bool):
    cfg.refresh_interval = max(MIN_INTERVAL, min(MAX_INTERVAL, interval))
  disabled = data.get("disabled")
  if isinstance(disabled, list):
    cfg.disabled = [str(x) for x in disabled if isinstance(x, str)]
  for key in ("notify", "collect"):
    if isinstance(data.get(key), bool):
      setattr(cfg, key, data[key])
  if isinstance(data.get("usage_dir"), str):
    cfg.usage_dir = data["usage_dir"]
  for key in ("ascii", "color"):
    value = data.get(key)
    if isinstance(value, bool):
      setattr(cfg, key, "always" if value else "never")
    elif value in ("auto", "always", "never"):
      setattr(cfg, key, value)
  return cfg


def dump(cfg: Config) -> str:
  q = json.dumps  # a JSON string is a valid TOML basic string
  return "\n".join([
    "# agents-tui settings. Every key is optional.",
    "",
    "# Seconds between full refreshes (30 to 3600).",
    f"refresh_interval = {cfg.refresh_interval}",
    "# Providers not to collect or show, by id (`agents-tui providers` lists them).",
    "disabled = [" + ", ".join(q(x) for x in cfg.disabled) + "]",
    "# Desktop notification and bell when a limit reaches 90%.",
    f"notify = {str(cfg.notify).lower()}",
    "# Where records are read from; empty for agents-tui's own folder. Point it",
    "# at another tool's records and set collect = false to only display them.",
    f"usage_dir = {q(cfg.usage_dir)}",
    f"collect = {str(cfg.collect).lower()}",
    "# Block characters and colors: auto, always or never.",
    f"ascii = {q(cfg.ascii)}",
    f"color = {q(cfg.color)}",
    "",
  ])


def save(cfg: Config, path: Path = None) -> None:
  path = path or paths.config_file()
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
      handle.write(dump(cfg))
    os.replace(tmp, path)
  except BaseException:
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise


def save_settings(cfg: Config, path: Path = None) -> None:
  """Saves what the settings screen changes, and nothing a command-line
  option overrode for this run (--usage-dir, --no-collect)."""
  path = path or paths.config_file()
  saved = load(path)
  saved.refresh_interval = cfg.refresh_interval
  saved.disabled = list(cfg.disabled)
  saved.notify = cfg.notify
  save(saved, path)
