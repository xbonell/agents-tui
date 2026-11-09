import json
import tempfile
import unittest
from pathlib import Path

from agents_tui.record import UsageRecord, load_file, parse_iso


class RecordTests(unittest.TestCase):
  def test_wrong_types_cost_only_their_field(self):
    record = UsageRecord.parse({
      "id": "x", "name": 3, "ready": "yes", "limits": [{"label": "5-hour", "percent": "high"}, "junk", {"percent": 7}],
      "balance": [], "todayPrompts": True, "totalPrompts": 12.0, "modelUsage": {"m": {"inputTokens": None}, "n": 4},
      "limitsFetchedAt": float("nan"),
    })
    self.assertEqual(record.name, "x")
    self.assertFalse(record.ready)
    self.assertEqual([l.percent for l in record.limits], [0.0, 1.0])  # clamped
    self.assertIsNone(record.balance)
    self.assertEqual(record.today_prompts, 0)
    self.assertEqual(record.total_prompts, 12)
    self.assertEqual(list(record.model_usage), ["m"])
    self.assertEqual(record.limits_fetched_at, 0.0)

  def test_iso_times(self):
    self.assertEqual(parse_iso("2026-11-09T12:00:00Z"), parse_iso("2026-11-09T12:00:00.123456789+00:00"))
    self.assertEqual(parse_iso("2026-11-09T13:00:00+01:00"), parse_iso("2026-11-09T12:00:00"))
    self.assertIsNone(parse_iso("soon"))
    self.assertIsNone(parse_iso(""))

  def test_load_file(self):
    with tempfile.TemporaryDirectory() as tmp:
      good = Path(tmp) / "codex.json"
      good.write_text(json.dumps({"name": "Codex"}))
      bad = Path(tmp) / "bad.json"
      bad.write_text("[1, 2]")
      self.assertEqual(load_file(good).id, "codex")
      self.assertIsNone(load_file(bad))
      self.assertIsNone(load_file(Path(tmp) / "missing.json"))


if __name__ == "__main__":
  unittest.main()
