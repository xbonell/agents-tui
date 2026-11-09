import datetime as dt
from pathlib import Path

from agents_tui import collect, config

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The fixtures are written as of this moment.
NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc).timestamp()


def fixture_records():
  store = collect.Store(config.Config(usage_dir=str(FIXTURES)))
  store.poll()
  return store
