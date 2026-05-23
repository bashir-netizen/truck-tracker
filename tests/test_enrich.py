"""Tests for the enrichment layer, on synthetic in-memory data."""

import sqlite3
from pathlib import Path

import pytest

import config
from enrich import anomalies, corridors, driver, journeys, maintenance, metrics, places

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


def add_parking(con, start_ts, end_ts, place, location):
    con.execute(
        "INSERT INTO parkings (unit_id,start_ts,end_ts,duration_s,lat,lon,location,raw) "
        "VALUES (?,?,?,?,?,?,?,'{}')",
        (UNIT, start_ts, end_ts, end_ts - start_ts, place[0], place[1], location))


def add_place(con, pid, label, point):
    con.execute(
        "INSERT INTO places (place_id,label,lat,lon,radius_m,visit_count,visit_time_total_s) "
        "VALUES (?,?,?,?,?,?,?)", (pid, label, point[0], point[1], 3000, 1, 0))


# -- journeys --------------------------------------------------------------

def test_journey_character_thresholds():
    assert journeys.character(350_000, 3600) == "long_haul"
    assert journeys.character(50_000, 90_000) == "long_haul"   # >24h spans
    assert journeys.character(150_000, 3600) == "regional"
    assert journeys.character(40_000, 3600) == "local"
    assert journeys.character(2_000, 600) == "yard"


def test_journeys_stitch_and_split(con):
    # two legs <3h apart = one journey; a >3h gap starts a second
    add_trip(con, 0, 1000, A, B, 10000, 4)
    add_trip(con, 1500, 3000, B, A, 10000, 4)            # gap 500s -> same journey
    later = 3000 + config.JOURNEY_SPLIT_HOURS * 3600 + 60
    add_trip(con, later, later + 1000, A, B, 8000, 3)    # >3h gap -> new journey
    n = journeys.rebuild(con, UNIT)
    assert n == 2
    first = con.execute("SELECT leg_count, distance_m FROM journeys ORDER BY start_ts").fetchone()
    assert first[0] == 2 and first[1] == 20000


# -- places ----------------------------------------------------------------

def test_places_from_journeys_and_parkings(con):
    add_trip(con, 0, 3600, A, B, 80000, 30)
    journeys.rebuild(con, UNIT)
    add_parking(con, 0, 7200, A, "Depot Rd, Athi River, Machakos")
    add_parking(con, 9000, 16200, B, "Icd Road, Nairobi, South C Ward")
    n = places.rebuild(con, UNIT)
    assert n == 2
    labels = {p["label"] for p in places.load_places(con)}
    assert labels == {"Athi River", "Nairobi"}


def test_needs_label_flag(con):
    add_trip(con, 0, 3600, A, B, 80000, 30)
    journeys.rebuild(con, UNIT)
    add_parking(con, 0, 7200, A, "Depot, Athi River, Machakos")   # clean -> Athi River
    add_parking(con, 9000, 16200, B, "17 km from Nowhere")        # weak auto-name
    places.rebuild(con, UNIT)
    flags = dict(con.execute("SELECT label, needs_label FROM places"))
    assert flags.get("Athi River") == 0
    assert flags.get("17 km from Nowhere") == 1


def test_short_name():
    assert places._short_name("Icd Road, Nairobi, South C Ward") == "Nairobi"
    assert places._short_name("Marsabit-Moyale Road, Marsabit, X") == "Marsabit"
    assert places._short_name("Solo") == "Solo"
    assert places._short_name("") is None


# -- corridors -------------------------------------------------------------

def test_rdp_collapses_straight_keeps_corner():
    straight = [(36.0, -1.0), (36.001, -1.0), (36.002, -1.0), (36.010, -1.0)]
    assert len(corridors._rdp(straight, 50.0)) == 2
    corner = [(36.0, -1.0), (36.05, -1.0), (36.05, -1.05)]  # a right-angle turn
    assert len(corridors._rdp(corner, 50.0)) == 3


def test_corridors_unordered_merge(con):
    add_place(con, 0, "Nairobi", A)
    add_place(con, 1, "Marsabit", B)
    for sts, o, d in [(100, 0, 1), (10_000, 1, 0)]:  # A->B and B->A
        con.execute(
            "INSERT INTO journeys (unit_id,start_ts,end_ts,origin_place_id,dest_place_id,"
            "distance_m,duration_s,fuel_l,is_local) VALUES (?,?,?,?,?,?,?,?,0)",
            (UNIT, sts, sts + 1000, o, d, 500000, 36000, 150))
    assert corridors.rebuild(con, UNIT) == 1
    row = con.execute("SELECT journey_count, place_a_id, place_b_id FROM corridors").fetchone()
    assert row[0] == 2 and row[1] == 0 and row[2] == 1


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
    assert 0.0 <= row[0] <= 10.0          # Wialon 0-10 eco scale
    assert row[1] == 1


def test_penalties_to_rank_matches_wialon_bands():
    assert driver.penalties_to_rank(0) == 10.0
    assert driver.penalties_to_rank(17) == 9.0
    assert driver.penalties_to_rank(67) == 7.0
    assert driver.penalties_to_rank(1067) == 2.0
    assert driver.penalties_to_rank(5000) >= 1.0   # beyond the table, never below 1
    # monotonic non-increasing as penalties rise
    assert driver.penalties_to_rank(50) > driver.penalties_to_rank(200)


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
