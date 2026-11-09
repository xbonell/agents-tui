"""Every location agents-tui reads or writes, for macOS and Linux alike."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "omarchy"
RUNNER = ROOT / "runner" / "run_collector.py"
MANIFEST = VENDOR / "shell" / "plugins" / "agents" / "manifest.json"
DARWIN = sys.platform == "darwin"
HOME = Path.home()


def _xdg(name: str, default: Path) -> Path:
  value = os.environ.get(name, "")
  # The XDG spec ignores a relative path.
  return Path(value) if value and os.path.isabs(value) else default


def config_file() -> Path:
  """Settings live in ~/.config on both systems, where terminal tools keep theirs."""
  return _xdg("XDG_CONFIG_HOME", HOME / ".config") / "agents-tui" / "config.toml"


def state_dir() -> Path:
  if DARWIN:
    return HOME / "Library" / "Application Support" / "agents-tui"
  return _xdg("XDG_STATE_HOME", HOME / ".local" / "state") / "agents-tui"


def cache_dir() -> Path:
  if DARWIN:
    return HOME / "Library" / "Caches" / "agents-tui"
  return _xdg("XDG_CACHE_HOME", HOME / ".cache") / "agents-tui"


def default_usage_dir() -> Path:
  return state_dir() / "usage"


def collector_env() -> Dict[str, str]:
  """The environment collectors run in.

  On Linux they keep their caches where Omarchy's own would be
  (~/.cache/omarchy/agent-usage), which is safe to share: every cache there
  is written under a lock. On macOS the XDG folders move under ~/Library.
  """
  env = dict(os.environ)
  if DARWIN:
    env.setdefault("XDG_STATE_HOME", str(state_dir()))
    env.setdefault("XDG_CACHE_HOME", str(cache_dir()))
  return env


def _manifest_order() -> List[str]:
  try:
    with open(MANIFEST, encoding="utf-8") as handle:
      data = json.load(handle)
    return list(data["barWidget"]["defaults"]["providers"].keys())
  except (OSError, ValueError, KeyError, TypeError, AttributeError):
    return []


def collector_ids() -> List[str]:
  """Every vendored collector, in the order Omarchy's panel lists them."""
  prefix = "omarchy-agent-usage-"
  found = sorted(
    p.name[len(prefix):]
    for p in (VENDOR / "bin").glob(prefix + "*")
    if p.is_file() and p.name != prefix + "update"
  )
  order = [i for i in _manifest_order() if i in found]
  return order + [i for i in found if i not in order]


def provider_rank() -> Dict[str, int]:
  return {pid: index for index, pid in enumerate(collector_ids())}
