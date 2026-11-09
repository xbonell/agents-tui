import unittest

from agents_tui import render

from .helpers import NOW, fixture_records


def text(lines):
  return ["".join(t for t, _ in line) for line in lines]


class RenderTests(unittest.TestCase):
  def screen(self, width, ascii_only=False, expanded=()):
    records = fixture_records().visible()
    view = render.View(records, NOW, render.Glyphs.make(ascii_only), phrase="17.8M tokens this week",
                       selected="claude", expanded=set(expanded), next_refresh=600)
    head, body, foot = render.screen(view, width)
    return text(head) + text(body.lines) + text(foot), body

  def test_lines_fit_every_width(self):
    for width in (20, 33, 44, 60, 80, 111, 120, 180, 240):
      for ascii_only in (False, True):
        lines, _ = self.screen(width, ascii_only, expanded=["claude", "codex", "openrouter"])
        for line in lines:
          self.assertLessEqual(render.cell_width(line), width, (width, ascii_only, line))

  def test_ascii_mode_is_ascii(self):
    lines, _ = self.screen(80, ascii_only=True, expanded=["claude", "openrouter"])
    records = fixture_records().visible()
    view = render.View(records, NOW, render.Glyphs.make(True), running=True)
    lines += text(render.screen(view, 80)[0])
    for line in lines:
      line.encode("ascii")

  def test_card_contents(self):
    lines, _ = self.screen(100)
    joined = "\n".join(lines)
    self.assertIn("Max 20x", joined)
    self.assertIn(" 91%  resets in 3d 4h", joined)
    self.assertIn("↳ Opus 33%", joined)
    self.assertIn("! Sign-in required · press l to run cursor-agent login", joined)
    self.assertIn("$1.50 left", joined)
    self.assertIn("Last updated 3h 0m ago", joined)
    self.assertNotIn("Kimi", joined)

  def test_columns_and_spans(self):
    _, body = self.screen(120)
    self.assertEqual(render.columns_for(120, 5), 2)
    # Cards side by side share their row's lines.
    self.assertEqual(body.spans["claude"], body.spans["codex"])
    self.assertLess(body.spans["claude"][1], body.spans["cursor"][0] + 1)

  def test_cards_are_boxed(self):
    _, body = self.screen(120)
    lines = text(body.lines)
    start, end = body.spans["claude"]
    self.assertTrue(lines[start].startswith("╭─ Claude Code "))
    self.assertIn(" Max 20x ─╮", lines[start])
    # Side-by-side boxes share their height, so the row closes on one line.
    self.assertEqual(lines[end - 1].count("╰"), 2)
    self.assertTrue(all(len(line) == len(lines[start]) for line in lines[start:end]))
    self.assertEqual(body.lines[start][0], ("╭─", "selected"))
    self.assertEqual(body.lines[start][-1], ("─╮", "dim"))

  def test_meter(self):
    g = render.Glyphs.make(False)
    self.assertEqual(text([render.meter(0.5, 10, False, g)]), ["█████░░░░░"])
    self.assertEqual(text([render.meter(0.55, 10, False, g)]), ["█████▌░░░░"])
    self.assertEqual(text([render.meter(1.2, 4, True, g)]), ["████"])
    a = render.Glyphs.make(True)
    self.assertEqual(text([render.meter(0.25, 8, False, a)]), ["##------"])

  def test_wide_text_is_measured_by_cell(self):
    self.assertEqual(render.cell_width("日本"), 4)
    self.assertEqual(render.clip_text("日本語", 5), "日本")


if __name__ == "__main__":
  unittest.main()
