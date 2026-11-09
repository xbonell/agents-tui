"""Run one vendored Omarchy collector on this machine.

  python3 -I runner/run_collector.py <id> [--force] [--limits-only]

Prints the collector's record on stdout, exactly as the collector does. On
Linux the collectors run as Omarchy ships them. On macOS the shim in
macos_shim.py is applied first, and the collectors' XDG folders default to
~/Library, where macOS keeps such things.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR = ROOT / "vendor" / "omarchy"
HOME = Path.home()


def main() -> int:
  if len(sys.argv) < 2:
    print("usage: run_collector.py <id> [--force] [--limits-only]", file=sys.stderr)
    return 2
  agent_id = sys.argv[1]
  script = VENDOR / "bin" / f"omarchy-agent-usage-{agent_id}"
  if agent_id == "update" or not script.is_file():
    print(f"run_collector: no collector named {agent_id}", file=sys.stderr)
    return 2

  # The collectors find their shared module, and each other, through it.
  os.environ["OMARCHY_PATH"] = str(VENDOR)
  darwin = sys.platform == "darwin"
  if darwin:
    os.environ.setdefault("XDG_STATE_HOME", str(HOME / "Library" / "Application Support" / "agents-tui"))
    os.environ.setdefault("XDG_CACHE_HOME", str(HOME / "Library" / "Caches" / "agents-tui"))

  sys.path.insert(0, str(VENDOR / "shell" / "plugins" / "agents"))
  sys.path.insert(0, str(HERE))
  # tomllib is Python 3.11's; on an older Python (macOS ships 3.9) the
  # vendored tomli, which it was upstreamed from, stands in under its name.
  try:
    import tomllib  # noqa: F401
  except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT / "vendor"))
    import tomli

    sys.modules["tomllib"] = tomli

  if darwin:
    import macos_shim

    macos_shim.apply()

  sys.argv = [str(script), *sys.argv[2:]]
  runpy.run_path(str(script), run_name="__main__")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
