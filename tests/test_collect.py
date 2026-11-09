"""Runs the real vendored collectors, in a home with nothing signed in."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agents_tui import collect, config, paths


class CollectTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    home = Path(self.tmp.name)
    env = {
      "HOME": str(home), "XDG_STATE_HOME": str(home / "state"), "XDG_CACHE_HOME": str(home / "cache"),
      "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
    }
    self.env = mock.patch.dict(os.environ, env)
    self.env.start()
    self.usage = home / "usage"

  def tearDown(self):
    self.env.stop()
    self.tmp.cleanup()

  def test_every_collector_writes_a_record(self):
    ids = paths.collector_ids()
    self.assertIn("claude", ids)
    self.assertNotIn("update", ids)
    results = collect.update(ids, collect.Kind.FORCE, self.usage)
    failed = {r.id: r.error for r in results if not r.ok}
    self.assertEqual(failed, {})
    for pid in ids:
      record = json.loads((self.usage / f"{pid}.json").read_text())
      self.assertEqual(record["schemaVersion"], 1)
      self.assertFalse(record["ready"], pid)
    self.assertEqual([p.name for p in self.usage.iterdir() if p.name.startswith(".")], [])

  def test_unknown_collector_fails_cleanly(self):
    [result] = collect.update(["nope"], collect.Kind.NORMAL, self.usage)
    self.assertFalse(result.ok)
    self.assertFalse((self.usage / "nope.json").exists())

  def test_scheduler_collapses_requests(self):
    cfg = config.Config(usage_dir=str(self.usage))
    store = collect.Store(cfg)
    calls = []

    def fake_update(ids, kind, usage_dir):
      calls.append(kind)
      time.sleep(0.2)
      return []

    with mock.patch.object(collect, "update", fake_update):
      scheduler = collect.Scheduler(store, cfg)
      scheduler.tick(time.time())  # the first full refresh
      scheduler.request(collect.Kind.LIMITS)
      scheduler.request(collect.Kind.FORCE)
      scheduler.request(collect.Kind.NORMAL)
      deadline = time.time() + 3
      while (scheduler.running or len(calls) < 2) and time.time() < deadline:
        time.sleep(0.05)
    self.assertEqual(calls, [collect.Kind.NORMAL, collect.Kind.FORCE])


if __name__ == "__main__":
  unittest.main()
