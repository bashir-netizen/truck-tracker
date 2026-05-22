"""Tests for billing estimates and KES formatting (no rates invented)."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.components.format import format_kes, relative_day  # noqa: E402
from billing import estimate  # noqa: E402


def test_fuel_cost():
    assert estimate.fuel_cost(100, 180) == 18000
    assert estimate.fuel_cost(0, 180) == 0


def test_revenue_excludes_classes_without_a_rate():
    journeys = [("long_haul", 500_000), ("regional", 100_000), ("local", 20_000)]
    total, bd, incl, excl = estimate.revenue_by_class(
        journeys, {"long_haul": 100, "regional": None, "local": None})
    assert incl == ["long_haul"]
    assert set(excl) == {"regional", "local"}
    assert total == 500 * 100
    assert bd["long_haul"]["km"] == 500


def test_revenue_all_none_is_zero_and_empty():
    total, bd, incl, excl = estimate.revenue_by_class(
        [("long_haul", 500_000)], {"long_haul": None, "regional": None, "local": None})
    assert total == 0 and incl == [] and "long_haul" in excl


def test_format_kes():
    assert format_kes(280_000) == "KES 280k"
    assert format_kes(1_250_000) == "KES 1.25M"
    assert format_kes(70_880) == "KES 70.9k"
    assert format_kes(500) == "KES 500"


def test_relative_day():
    now = 1_000_000_000
    assert relative_day(now, now) == "today"
    assert relative_day(now - 86400, now) == "yesterday"
    assert relative_day(now - 3 * 86400, now) == "3 days ago"
    assert "week" in relative_day(now - 14 * 86400, now)
    assert "month" in relative_day(now - 60 * 86400, now)
