"""Value-level tests for the dashboard data layer.

These assert actual numbers, not just "no exception" — they exist because a
silent-zero bug (numpy bind params giving SQLite BLOB affinity) slipped past
the page smoke tests, which only checked for exceptions.
"""

import pathlib
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "truck.db"

pytestmark = pytest.mark.skipif(
    not DB.exists() or sqlite3.connect(DB).execute(
        "SELECT COUNT(*) FROM trips").fetchone()[0] == 0,
    reason="needs a populated data/truck.db")

from app.components import db  # noqa: E402


def test_scalar_returns_native_python_types():
    ts = db.scalar("SELECT MAX(ts) FROM unit_state")
    assert ts is not None
    assert type(ts) is int  # not numpy.int64 — or bind params silently fail


def test_period_window_returns_all_trips():
    """A 30-day window anchored on the latest data must include the trips."""
    to_ts = db.last_data_ts()
    frm = to_ts - 30 * 86400
    in_window = db.scalar(
        "SELECT COUNT(*) FROM trips WHERE start_ts BETWEEN ? AND ?", (frm, to_ts), default=0)
    total = db.scalar("SELECT COUNT(*) FROM trips", default=0)
    assert in_window == total
    assert in_window > 0
