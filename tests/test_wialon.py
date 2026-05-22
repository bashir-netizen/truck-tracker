"""Tests for the ingestion layer.

Everything runs against recorded fixtures (tests/fixtures/*.json) and an
in-memory SQLite database. The live Wialon API is never called.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from ingest import eco_events, fillings, trips, unit_state, wialon

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
SCHEMA = (ROOT / "ingest" / "schema.sql").read_text()
UNIT_ID = 601635106


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


class FakeClient:
    """Stands in for WialonClient; returns canned rows for any report."""

    def __init__(self, rows):
        self.rows = rows

    def run_table_report(self, *args, **kwargs):
        return self.rows


# -- cell + value helpers --------------------------------------------------

def test_num_parses_units_and_nullish():
    assert wialon.num("16.18 km") == 16.18
    assert wialon.num("55 km/h") == 55.0
    assert wialon.num("329.52 l") == 329.52
    assert wialon.num("-----") is None
    assert wialon.num("") is None
    assert wialon.num({"t": "60 km/h"}) == 60.0  # dict cell


def test_hms_to_seconds():
    assert wialon.hms_to_seconds("0:31:13") == 31 * 60 + 13
    assert wialon.hms_to_seconds("2 days 19:27:31") == 2 * 86400 + 19 * 3600 + 27 * 60 + 31
    assert wialon.hms_to_seconds("-----") is None


def test_cell_helpers():
    cell = {"t": "2026-05-15 18:35:28", "v": 1778870128, "y": -1.42, "x": 36.95}
    assert wialon.cell_epoch(cell) == 1778870128
    assert wialon.cell_xy(cell) == (-1.42, 36.95)
    assert wialon.cell_text("0:31:13") == "0:31:13"
    assert wialon.cell_epoch("plain") is None


def test_eco_classify():
    assert eco_events.classify("Harsh acceleration") == "harsh_accel"
    assert eco_events.classify("Harsh braking") == "harsh_brake"
    assert eco_events.classify("Sharp turn") == "harsh_corner"
    assert eco_events.classify("Speeding: mild") == "speeding"
    assert eco_events.classify("Idling") == "idling"
    assert eco_events.classify("Something else") == "other"


# -- row parsing against real fixtures -------------------------------------

def test_parse_trip_row_shapes():
    row = load("trips_rows")[0]
    t = trips.parse_row(UNIT_ID, row)
    assert t is not None
    unit_id, start_ts, end_ts, slat, slon, elat, elon, dist, dur, avg, mx, raw = t
    assert unit_id == UNIT_ID
    assert isinstance(start_ts, int) and isinstance(end_ts, int) and end_ts >= start_ts
    assert isinstance(slat, float) and isinstance(slon, float)
    assert dist is None or isinstance(dist, int)
    assert json.loads(raw)  # raw is valid JSON


def test_parse_filling_after_level_is_before_plus_filled():
    row = load("fillings_rows")[0]
    f = fillings.parse_row(UNIT_ID, row)
    _, ts, lat, lon, vol, before, after, raw = f
    assert isinstance(ts, int)
    if vol is not None and before is not None:
        assert after == round(before + vol, 2)


def test_parse_eco_rows_have_known_types():
    valid = {"harsh_accel", "harsh_brake", "harsh_corner", "speeding", "idling", "other"}
    for row in load("eco_rows"):
        e = eco_events.parse_row(UNIT_ID, row)
        assert e is not None
        assert e[2] in valid


# -- write paths: idempotency + open-trip finalize -------------------------

def test_trips_idempotent(con):
    rows = load("trips_rows")
    client = FakeClient(rows)
    first = trips.fetch_and_store(client, con, UNIT_ID, 0, 0, 0)
    second = trips.fetch_and_store(client, con, UNIT_ID, 0, 0, 0)
    assert first > 0
    assert second == 0  # re-running the same window adds nothing
    n = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    assert n == first


def test_open_trip_finalizes_in_place(con):
    base = load("trips_rows")[0]
    trips.fetch_and_store(FakeClient([base]), con, UNIT_ID, 0, 0, 0)
    start = trips.parse_row(UNIT_ID, base)[1]
    # same start, later end -> should update the row, not add one
    extended = json.loads(json.dumps(base))
    extended["c"][1] = {"t": "x", "v": trips.parse_row(UNIT_ID, base)[2] + 600,
                        "y": -1.3, "x": 36.9}
    added = trips.fetch_and_store(FakeClient([extended]), con, UNIT_ID, 0, 0, 0)
    assert added == 0
    rows = con.execute("SELECT COUNT(*), MAX(end_ts) FROM trips WHERE start_ts=?", (start,)).fetchone()
    assert rows[0] == 1
    assert rows[1] == trips.parse_row(UNIT_ID, base)[2] + 600


def test_fillings_and_eco_idempotent(con):
    fc, ec = FakeClient(load("fillings_rows")), FakeClient(load("eco_rows"))
    assert fillings.fetch_and_store(fc, con, UNIT_ID, 0, 0, 0) > 0
    assert fillings.fetch_and_store(fc, con, UNIT_ID, 0, 0, 0) == 0
    assert eco_events.fetch_and_store(ec, con, UNIT_ID, 0, 0, 0) > 0
    assert eco_events.fetch_and_store(ec, con, UNIT_ID, 0, 0, 0) == 0


def test_unit_state_snapshot(con):
    unit = load("unit")
    added = unit_state.snapshot(con, unit)
    assert added == 1
    row = con.execute("SELECT lat, lon, odometer_m FROM unit_state").fetchone()
    assert row[0] == unit["pos"]["y"]
    # cnm (km) stored as metres
    if unit.get("cnm") is not None:
        assert row[2] == round(unit["cnm"] * 1000)
