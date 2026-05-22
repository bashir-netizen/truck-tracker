"""Tests for the enrichment layer, on synthetic in-memory data."""

import sqlite3
from pathlib import Path

import pytest

import config
from enrich import anomalies, driver, maintenance, metrics, places

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "ingest" / "schema.sql").read_text()
UNIT = 1
A = (-1.4200, 36.9500)   # depot
B = (-1.3300, 36.8700)   # ICD


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


def add_trip(con, start_ts, end_ts, start, end, distance_m, consumed_l):
    con.execute(
        "INSERT INTO trips (unit_id,start_ts,end_ts,start_lat,start_lon,end_lat,end_lon,"
        "distance_m,duration_s,avg_speed_kmh,max_speed_kmh,consumed_l,raw) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'{}')",
        (UNIT, start_ts, end_ts, start[0], start[1], end[0], end[1],
         distance_m, end_ts - start_ts, 40, 80, consumed_l))


def add_fill(con, ts, before, after):
    con.execute(
        "INSERT INTO fillings (unit_id,ts,lat,lon,volume_l,level_before_l,level_after_l,raw) "
        "VALUES (?,?,?,?,?,?,?,'{}')",
        (UNIT, ts, A[0], A[1], round(after - before, 2), before, after))


def add_eco(con, ts, etype):
    con.execute("INSERT INTO eco_events (unit_id,ts,type,value,duration_s,lat,lon,raw) "
                "VALUES (?,?,?,?,?,?,?,'{}')", (UNIT, ts, etype, 60, 1, A[0], A[1]))


# -- places ----------------------------------------------------------------

def test_places_cluster_repeated_endpoints(con):
    for i in range(4):  # 4 trips A->B => 4 points at each => 2 clusters
        add_trip(con, 1000 + i, 2000 + i, A, B, 80000, 30)
    n = places.rebuild(con, UNIT)
    assert n == 2
    pls = places.load_places(con)
    # every centroid is within a few metres of A or B
    for p in pls:
        near = min(places.haversine_m(p["lat"], p["lon"], *A),
                   places.haversine_m(p["lat"], p["lon"], *B))
        assert near < 50


# -- metrics ---------------------------------------------------------------

def test_metrics_economy_and_short_trip_null(con):
    add_trip(con, 1000, 4600, A, B, 100000, 39.0)   # 100 km, 39 L -> 39.0
    add_trip(con, 5000, 5100, A, A, 200, 4.0)        # 0.2 km maneuver -> None
    metrics.rebuild(con, UNIT)
    rows = dict(con.execute("SELECT start_ts, l_per_100km FROM trip_metrics"))
    assert rows[1000] == 39.0
    assert rows[5000] is None


def test_metrics_harsh_count_within_window(con):
    add_trip(con, 1000, 2000, A, B, 50000, 20)
    add_eco(con, 1500, "harsh_brake")
    add_eco(con, 1800, "harsh_corner")
    add_eco(con, 9999, "harsh_accel")  # outside the trip window
    metrics.rebuild(con, UNIT)
    assert con.execute("SELECT harsh_event_count FROM trip_metrics WHERE start_ts=1000").fetchone()[0] == 2


# -- driver score ----------------------------------------------------------

def test_driver_score_bounds_and_counts(con):
    base = driver.week_start(1_700_000_000)
    add_trip(con, base + 100, base + 4000, A, B, 100000, 35)
    for i in range(3):
        add_eco(con, base + 200 + i, "harsh_brake")
    add_eco(con, base + 300, "speeding")
    driver.rebuild(con, UNIT)
    row = con.execute("SELECT score, speeding_count FROM driver_score").fetchone()
    assert 0.0 <= row[0] <= 100.0
    assert row[1] == 1


# -- maintenance -----------------------------------------------------------

def test_maintenance_km_remaining(con):
    add_trip(con, 1000, 2000, A, B, 5_000_000, 1500)  # 5000 km cumulative
    maintenance.rebuild(con, UNIT)
    oil = con.execute(
        "SELECT interval_km, current_odometer_m, km_remaining, due "
        "FROM service_status WHERE service_type='engine_oil'").fetchone()
    assert oil[1] == 5_000_000
    assert oil[2] == pytest.approx(config.MAINTENANCE_INTERVALS["engine_oil"]["km"] - 5000)
    assert oil[3] == 0


def test_maintenance_due_when_exceeded(con):
    add_trip(con, 1000, 2000, A, B, 20_000_000, 6000)  # 20 000 km > 15 000 oil interval
    maintenance.rebuild(con, UNIT)
    assert con.execute("SELECT due FROM service_status WHERE service_type='engine_oil'").fetchone()[0] == 1


# -- anomalies -------------------------------------------------------------

def test_anomaly_fuel_drop_flagged_and_clean(con):
    # missing fuel: after 550, only 30 L consumed, yet next fill starts at 100
    add_fill(con, 1000, 50, 550)
    add_trip(con, 1100, 1200, A, B, 100000, 30)
    add_fill(con, 2000, 100, 550)
    n = anomalies.rebuild(con, UNIT, now=2000)
    drops = con.execute("SELECT COUNT(*) FROM anomalies WHERE type='fuel_drop'").fetchone()[0]
    assert drops == 1

    # clean case: level matches consumption -> no drop
    con.execute("DELETE FROM fillings")
    con.execute("DELETE FROM trips")
    add_fill(con, 1000, 50, 550)
    add_trip(con, 1100, 1200, A, B, 100000, 30)
    add_fill(con, 2000, 520, 550)  # 550 - 30 consumed = 520, matches
    anomalies.rebuild(con, UNIT, now=2000)
    assert con.execute("SELECT COUNT(*) FROM anomalies WHERE type='fuel_drop'").fetchone()[0] == 0


def test_anomaly_unusual_fill(con):
    add_fill(con, 1000, 10, 10 + 600)  # 600 L into a 550 L tank
    anomalies.rebuild(con, UNIT, now=1000)
    assert con.execute("SELECT COUNT(*) FROM anomalies WHERE type='unusual_fill'").fetchone()[0] >= 1


def test_anomaly_device_silent(con):
    con.execute("INSERT INTO unit_state (unit_id,ts,captured_ts,lat,lon,raw) "
                "VALUES (?,?,?,?,?,'{}')", (UNIT, 1000, 1000, A[0], A[1]))
    now = 1000 + (config.DEVICE_SILENT_HOURS + 1) * 3600
    anomalies.rebuild(con, UNIT, now=now)
    assert con.execute("SELECT COUNT(*) FROM anomalies WHERE type='device_silent'").fetchone()[0] == 1
