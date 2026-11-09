import tempfile
import unittest
from pathlib import Path

from agents_tui import config


class ConfigTests(unittest.TestCase):
  def test_round_trip_and_lenience(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = Path(tmp) / "config.toml"
      self.assertEqual(config.load(path), config.Config())
      path.write_text('refresh_interval = 5\ndisabled = ["local", 3]\nnotify = "no"\nascii = true\n')
      cfg = config.load(path)
      self.assertEqual((cfg.refresh_interval, cfg.disabled, cfg.notify, cfg.ascii), (30, ["local"], True, "always"))
      cfg.usage_dir = 'odd "path"\\x'
      config.save(cfg, path)
      self.assertEqual(config.load(path), cfg)
      path.write_text("this is = = not toml")
      self.assertEqual(config.load(path), config.Config())

  def test_settings_leave_overrides_out(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = Path(tmp) / "config.toml"
      cfg = config.Config(usage_dir="/elsewhere", collect=False, disabled=["codex"], refresh_interval=600)
      config.save_settings(cfg, path)
      saved = config.load(path)
      self.assertEqual((saved.usage_dir, saved.collect), ("", True))
      self.assertEqual((saved.disabled, saved.refresh_interval), (["codex"], 600))


if __name__ == "__main__":
  unittest.main()
