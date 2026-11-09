"""Running the collectors, watching their records, and deciding when to refresh.

`update` replaces Omarchy's bash omarchy-agent-usage-update: it runs the
collectors in parallel, checks each printed a JSON object, and writes it
atomically to <usage dir>/<id>.json. `Scheduler` ports Main.qml's refresh
logic, and `Store` reads the records back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from . import paths
from .config import Config
from .present import near_switch_threshold
from .record import UsageRecord, load_file

TIMEOUT_SECONDS = 120
RETRY_SECONDS = 30
NEAR_LIMIT_SECONDS = 180


class Kind(IntEnum):
  """How fresh an update must be; a higher kind outranks a lower one."""

  NORMAL = 0
  LIMITS = 1  # reuse local scans, ask for limits
  FORCE = 2  # reuse nothing

  @property
  def flags(self) -> List[str]:
    return {Kind.NORMAL: [], Kind.LIMITS: ["--limits-only"], Kind.FORCE: ["--force"]}[self]


@dataclass
class Result:
  id: str
  ok: bool
  error: str = ""
  seconds: float = 0.0


def _write_atomic(directory: Path, name: str, text: str) -> None:
  fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=f".{name}.")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
      handle.write(text)
    os.replace(tmp, directory / name)
  except BaseException:
    try:
      os.unlink(tmp)
    except OSError:
      pass
    raise


def _last_line(text: str) -> str:
  lines = [line.strip() for line in text.splitlines() if line.strip()]
  return lines[-1][:300] if lines else ""


def run_one(provider: str, kind: Kind, usage_dir: Path, env: Dict[str, str]) -> Result:
  started = time.monotonic()
  command = [sys.executable, "-I", str(paths.RUNNER), provider, *kind.flags]
  try:
    done = subprocess.run(
      command, capture_output=True, text=True, env=env, timeout=TIMEOUT_SECONDS,
      stdin=subprocess.DEVNULL,
    )
  except subprocess.TimeoutExpired:
    return Result(provider, False, f"timed out after {TIMEOUT_SECONDS}s", time.monotonic() - started)
  except OSError as error:
    return Result(provider, False, str(error), time.monotonic() - started)
  elapsed = time.monotonic() - started
  if done.returncode != 0:
    return Result(provider, False, _last_line(done.stderr) or f"exited with {done.returncode}", elapsed)
  try:
    record = json.loads(done.stdout)
  except ValueError:
    record = None
  if not isinstance(record, dict):
    return Result(provider, False, "printed no JSON record", elapsed)
  _write_atomic(usage_dir, f"{provider}.json", json.dumps(record, separators=(",", ":")) + "\n")
  return Result(provider, True, "", elapsed)


def log_results(results: Sequence[Result]) -> None:
  """Failures go to <cache dir>/collect.log, kept short."""
  failures = [r for r in results if not r.ok]
  if not failures:
    return
  log = paths.cache_dir() / "collect.log"
  try:
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = log.read_text(encoding="utf-8").splitlines()[-400:] if log.exists() else []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    lines += [f"{stamp} {r.id}: {r.error}" for r in failures]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
  except OSError:
    pass


def update(providers: Sequence[str], kind: Kind, usage_dir: Path) -> List[Result]:
  usage_dir.mkdir(parents=True, exist_ok=True)
  env = paths.collector_env()
  # Collectors forced together read the Codex rollouts they share once
  # between them, by knowing when this refresh began.
  env["OMARCHY_AGENT_USAGE_REFRESH_AT"] = f"{time.time():.6f}"
  if not providers:
    return []
  workers = min(len(providers), max(4, (os.cpu_count() or 2) * 2))
  with ThreadPoolExecutor(max_workers=workers) as pool:
    results = list(pool.map(lambda p: run_one(p, kind, usage_dir, env), providers))
  log_results(results)
  return results


class Store:
  """The records in the usage dir, reread when a file there changes."""

  def __init__(self, cfg: Config):
    self.cfg = cfg
    self.records: Dict[str, UsageRecord] = {}
    self._seen: Dict[str, float] = {}
    self.generation = 0

  @property
  def directory(self) -> Path:
    return self.cfg.records_dir()

  def poll(self) -> bool:
    """Rereads changed records; True when anything changed."""
    seen: Dict[str, float] = {}
    try:
      entries = list(os.scandir(self.directory))
    except OSError:
      entries = []
    for entry in entries:
      if entry.name.startswith(".") or not entry.name.endswith(".json"):
        continue
      try:
        stat = entry.stat()
      except OSError:
        continue
      seen[entry.name] = stat.st_mtime_ns + stat.st_size
    if seen == self._seen:
      return False
    records: Dict[str, UsageRecord] = {}
    for name in seen:
      if self._seen.get(name) == seen[name] and name[:-5] in self.records:
        records[name[:-5]] = self.records[name[:-5]]
        continue
      record = load_file(self.directory / name)
      if record is not None:
        records[name[:-5]] = record
    self._seen = seen
    self.records = records
    self.generation += 1
    return True

  def visible(self) -> List[UsageRecord]:
    rank = paths.provider_rank()
    shown = [r for r in self.records.values() if r.has_data and self.cfg.enabled(r.id)]
    return sorted(shown, key=lambda r: (rank.get(r.id, len(rank)), r.name.lower()))


class Scheduler:
  """Main.qml's refresh rules, driven by `tick` from the UI loop.

  A full update every refresh_interval, the first at start; every three
  minutes near an account switch threshold; one 30 s limits retry for the
  agents whose endpoint couldn't be reached. Only one update runs at a
  time; requests made meanwhile collapse into one rerun, a forced refresh
  outranking the cheaper kinds.
  """

  def __init__(self, store: Store, cfg: Config, on_done: Optional[Callable[[List[Result]], None]] = None):
    self.store = store
    self.cfg = cfg
    self.on_done = on_done
    self.running = False
    self.last_results: Dict[str, Result] = {}
    self.next_full: float = 0.0  # run at the first tick
    self._pending: Optional[Kind] = None
    self._retry_at: Optional[float] = None
    self._retry_ids: List[str] = []
    self._lock = threading.Lock()
    self._seen_generation = -1

  def providers(self) -> List[str]:
    return [p for p in paths.collector_ids() if self.cfg.enabled(p)]

  def request(self, kind: Kind, only: Optional[Sequence[str]] = None) -> None:
    if not self.cfg.collect:
      return
    with self._lock:
      if self.running:
        self._pending = kind if self._pending is None else max(self._pending, kind)
        return
      self.running = True
    ids = [p for p in (only if only is not None else self.providers()) if self.cfg.enabled(p)]
    threading.Thread(target=self._run, args=(kind, ids), daemon=True).start()

  def _run(self, kind: Kind, ids: List[str]) -> None:
    try:
      results = update(ids, kind, self.store.directory)
    except Exception as error:  # an unwritable usage dir, say
      results = [Result(p, False, str(error)) for p in ids]
    for result in results:
      self.last_results[result.id] = result
    with self._lock:
      self.running = False
      pending, self._pending = self._pending, None
    if self.on_done:
      self.on_done(results)
    if pending is not None:
      self.request(pending)

  def restart_timer(self, now: float) -> None:
    """A new interval starts a new wait, without an extra run of its own."""
    self.next_full = now + self.cfg.refresh_interval

  def failures(self) -> List[Result]:
    return [r for r in self.last_results.values() if not r.ok and self.cfg.enabled(r.id)]

  def tick(self, now: float) -> None:
    if not self.cfg.collect:
      return
    records = list(self.store.records.values())
    if now >= self.next_full:
      near = near_switch_threshold(records)
      self.request(Kind.LIMITS if near else Kind.NORMAL)
      interval = min(NEAR_LIMIT_SECONDS, self.cfg.refresh_interval) if near else self.cfg.refresh_interval
      self.next_full = now + interval
    # Only the advising agents rerun, so an outage at one provider doesn't
    # put every collector on a 30-second treadmill.
    if self.store.generation != self._seen_generation:
      self._seen_generation = self.store.generation
      advising = [r.id for r in records if r.retry_advised and self.cfg.enabled(r.id)]
      self._retry_ids = advising
      self._retry_at = now + RETRY_SECONDS if advising else None
    if self._retry_at is not None and now >= self._retry_at:
      self._retry_at = None
      self.request(Kind.LIMITS, only=self._retry_ids)
