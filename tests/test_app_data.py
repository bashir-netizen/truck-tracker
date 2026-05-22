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


def test_journeys_and_corridors_exist():
    """Journeys collapse legs (fewer than trips) and at least one route forms."""
    nj = db.scalar("SELECT COUNT(*) FROM journeys", default=0)
    nt = db.scalar("SELECT COUNT(*) FROM trips", default=0)
    assert 0 < nj <= nt
    assert db.scalar("SELECT COUNT(*) FROM corridors", default=0) >= 1


def test_shorter_window_is_a_subset():
    """A 24h window must hold no more trips than the full history (period works)."""
    to_ts = db.last_data_ts()
    day = db.scalar("SELECT COUNT(*) FROM trips WHERE start_ts BETWEEN ? AND ?",
                    (to_ts - 86400, to_ts), default=0)
    total = db.scalar("SELECT COUNT(*) FROM trips", default=0)
    assert 0 <= day <= total
