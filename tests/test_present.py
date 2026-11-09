import unittest

from agents_tui import present
from agents_tui.record import UsageLimit, UsageRecord

from .helpers import NOW, fixture_records


def limit(label, percent, hours=None, title=""):
  import datetime as dt
  resets = "" if hours is None else dt.datetime.fromtimestamp(NOW + hours * 3600, dt.timezone.utc).isoformat()
  return UsageLimit(label=label, title=title, percent=percent, resets_at=resets)


class WindowTests(unittest.TestCase):
  def test_titles_from_labels(self):
    self.assertEqual(present.window_title("Session (5-hour)"), "Session")
    self.assertEqual(present.window_title("Weekly (7-day)"), "Weekly")
    self.assertEqual(present.window_title("5h limit"), "Session")
    self.assertEqual(present.window_title("Monthly"), "Monthly")
    self.assertEqual(present.window_title("Credits (pool)"), "Credits")
    self.assertEqual(present.window_title(""), "Limit")

  def test_expired_window_reads_untouched(self):
    [window] = present.limit_windows([limit("5-hour", 0.7, hours=-1)], NOW)
    self.assertEqual(window.percent, 0)
    self.assertIsNone(window.reset_at)

  def test_scoped_window_rides_on_its_parent(self):
    windows = present.display_windows([
      limit("Weekly (7-day)", 0.5, 10), limit("", 0.3, 10, title="Opus Weekly"), limit("", 0.2, 10, title="Fable Monthly"),
    ], NOW)
    self.assertEqual([w.title for w in windows], ["Weekly", "Fable Monthly"])
    self.assertEqual([(s.title, s.percent) for s in windows[0].scoped], [("Opus", 0.3)])

  def test_durations(self):
    self.assertEqual(present.format_duration(0), "now")
    self.assertEqual(present.format_duration(30), "1m")
    self.assertEqual(present.format_duration(3 * 3600 + 60 * 5), "3h 5m")
    self.assertEqual(present.format_duration(3 * 86400 + 4 * 3600), "3d 4h")


class StatusTests(unittest.TestCase):
  def test_sign_in_and_notes(self):
    store = fixture_records()
    self.assertTrue(present.needs_sign_in(store.records["cursor"]))
    self.assertEqual(present.usage_note(store.records["cursor"]), "")
    # Kept limits explain themselves through the help text.
    self.assertIn("didn't answer", present.usage_note(store.records["zai"]))
    self.assertEqual(present.usage_note(store.records["claude"]), "")

  def test_alarm_rule(self):
    store = fixture_records()
    self.assertTrue(present.record_alarming(store.records["claude"], NOW))  # 91% weekly
    self.assertTrue(present.record_alarming(store.records["openrouter"], NOW))  # 7.5% left
    self.assertFalse(present.record_alarming(store.records["codex"], NOW))

  def test_hidden_without_data(self):
    store = fixture_records()
    self.assertNotIn("kimi", [r.id for r in store.visible()])
    self.assertEqual([r.id for r in store.visible()][:3], ["claude", "codex", "cursor"])


class NotificationTests(unittest.TestCase):
  def record(self, percent, hours=5):
    return UsageRecord(id="claude", name="Claude Code", limits=[limit("Weekly (7-day)", percent, hours)])

  def test_once_per_window_until_it_drops(self):
    alerts, sent = present.notifications_due([self.record(0.92)], NOW, set())
    self.assertEqual([a.title for a in alerts], ["Claude Code weekly at 92%"])
    self.assertEqual(alerts[0].body, "Resets in 5h 0m")
    # Still high, or hovering between 85% and 90%: nothing new.
    self.assertEqual(present.notifications_due([self.record(0.95)], NOW, sent)[0], [])
    alerts, kept = present.notifications_due([self.record(0.87)], NOW, sent)
    self.assertEqual((alerts, kept), ([], sent))
    # Below the rearm point it can alert again.
    self.assertEqual(present.notifications_due([self.record(0.5)], NOW, sent)[1], set())

  def test_a_new_reset_is_a_new_window(self):
    _, sent = present.notifications_due([self.record(0.92, hours=5)], NOW, set())
    alerts, _ = present.notifications_due([self.record(0.92, hours=170)], NOW, sent)
    self.assertEqual(len(alerts), 1)

  def test_low_balance(self):
    store = fixture_records()
    alerts, _ = present.notifications_due([store.records["openrouter"]], NOW, set())
    self.assertEqual([a.title for a in alerts], ["OpenRouter balance low"])
    self.assertEqual(alerts[0].body, "$1.50 left of $20.00")


class SummaryTests(unittest.TestCase):
  def test_friendly_model_names(self):
    self.assertEqual(present.friendly_model_name("claude-opus-5-5"), "Opus 5.5")
    self.assertEqual(present.friendly_model_name("claude-sonnet-5-5-20260101"), "Sonnet 5.5")
    self.assertEqual(present.friendly_model_name("gpt-5.6-sol"), "GPT 5.6 Sol")
    self.assertEqual(present.friendly_model_name("deepseek-v4"), "DeepSeek V4")
    self.assertEqual(present.friendly_model_name(""), "Unknown model")

  def test_tokens(self):
    self.assertEqual(present.format_tokens(999), "999")
    self.assertEqual(present.format_tokens(1234567), "1.2M")
    self.assertEqual(present.format_tokens(2_500_000_000), "2.5B")

  def test_phrases(self):
    phrases = present.summary_phrases(fixture_records().visible())
    self.assertEqual(phrases[0], "17.8M tokens this week")
    self.assertIn("Mostly Opus 5.5", phrases)
    self.assertIn("39 prompts today", phrases)


if __name__ == "__main__":
  unittest.main()
