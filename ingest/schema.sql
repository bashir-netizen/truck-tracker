-- Truck Tracker schema. Idempotent: safe to run on every ingestion.
--
-- Conventions (enforced everywhere):
--   timestamps  : INTEGER, Unix epoch seconds, UTC
--   lat / lon   : REAL (never strings, never combined)
--   distances   : INTEGER metres (converted to km only for display)
--   fuel        : REAL litres
--   engine hours: INTEGER seconds (displayed as days/hours)
-- Every table carries unit_id so a second truck can be added later
-- without a migration. Raw rows are preserved verbatim (`raw` JSON);
-- filtering/cleaning happens in queries or enrichment, never destructively.

-- ========================================================================
-- RAW tables — written only by ingest/, INSERT OR IGNORE on the PK.
-- ========================================================================

-- Snapshot of the unit's counters + position, captured each run.
CREATE TABLE IF NOT EXISTS unit_state (
    unit_id        INTEGER NOT NULL,
    ts             INTEGER NOT NULL,   -- last-message time
    captured_ts    INTEGER NOT NULL,   -- when this run read it
    lat            REAL,
    lon            REAL,
    speed_kmh      INTEGER,
    odometer_m     INTEGER,            -- cnm (km) * 1000
    engine_hours_s INTEGER,            -- cneh (h) * 3600
    raw            TEXT,
    PRIMARY KEY (unit_id, ts)
);

-- Trips from the tuned (unit-level) trip detector.
-- Keyed on (unit_id, start_ts): a trip starts exactly once. The end and
-- its derived fields are upserted, so an in-progress trip finalizes in
-- place on a later run instead of duplicating.
CREATE TABLE IF NOT EXISTS trips (
    unit_id       INTEGER NOT NULL,
    start_ts      INTEGER NOT NULL,
    end_ts        INTEGER NOT NULL,
    start_lat     REAL,
    start_lon     REAL,
    end_lat       REAL,
    end_lon       REAL,
    distance_m    INTEGER,
    duration_s    INTEGER,
    avg_speed_kmh INTEGER,
    max_speed_kmh INTEGER,
    consumed_l    REAL,
    raw           TEXT,
    PRIMARY KEY (unit_id, start_ts)
);

-- Fuel fill events.
CREATE TABLE IF NOT EXISTS fillings (
    unit_id        INTEGER NOT NULL,
    ts             INTEGER NOT NULL,
    lat            REAL,
    lon            REAL,
    volume_l       REAL,
    level_before_l REAL,
    level_after_l  REAL,
    raw            TEXT,
    PRIMARY KEY (unit_id, ts)
);

-- Fuel consumption rows (per trip/period) from the consumption report.
CREATE TABLE IF NOT EXISTS consumption (
    unit_id    INTEGER NOT NULL,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER NOT NULL,
    consumed_l REAL,
    distance_m INTEGER,
    raw        TEXT,
    PRIMARY KEY (unit_id, start_ts, end_ts)
);

-- Driver-behaviour / eco-driving events.
CREATE TABLE IF NOT EXISTS eco_events (
    unit_id    INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    type       TEXT NOT NULL,   -- harsh_accel|harsh_brake|harsh_corner|speeding|idling
    value      REAL,            -- g-force, km/h over limit, etc.
    duration_s INTEGER,         -- for speeding / idling
    lat        REAL,
    lon        REAL,
    raw        TEXT,
    PRIMARY KEY (unit_id, ts, type)
);
CREATE INDEX IF NOT EXISTS idx_eco_ts ON eco_events (unit_id, ts);

-- Parkings (engine-off stays) from the unit_stays report.
CREATE TABLE IF NOT EXISTS parkings (
    unit_id    INTEGER NOT NULL,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER,
    duration_s INTEGER,
    lat        REAL,
    lon        REAL,
    location   TEXT,
    raw        TEXT,
    PRIMARY KEY (unit_id, start_ts)
);

-- Stops (brief halts during a trip) from the unit_stops report.
CREATE TABLE IF NOT EXISTS stops (
    unit_id    INTEGER NOT NULL,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER,
    duration_s INTEGER,
    lat        REAL,
    lon        REAL,
    location   TEXT,
    raw        TEXT,
    PRIMARY KEY (unit_id, start_ts)
);

-- Decimated GPS track points (the actual road-following route).
CREATE TABLE IF NOT EXISTS positions (
    unit_id   INTEGER NOT NULL,
    ts        INTEGER NOT NULL,
    lat       REAL,
    lon       REAL,
    speed_kmh INTEGER,
    PRIMARY KEY (unit_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions (unit_id, ts);

-- Audit trail of every ingestion run (supports the freshness contract).
CREATE TABLE IF NOT EXISTS ingestion_log (
    run_ts         INTEGER NOT NULL,
    since_ts       INTEGER,
    until_ts       INTEGER,
    trips_added    INTEGER,
    fillings_added INTEGER,
    eco_added      INTEGER,
    status         TEXT,
    detail         TEXT,
    PRIMARY KEY (run_ts)
);

-- ========================================================================
-- DERIVED tables — rebuilt by enrich/. Never modify raw rows.
-- ========================================================================

CREATE TABLE IF NOT EXISTS places (
    place_id    INTEGER PRIMARY KEY,
    label       TEXT,           -- from places.yaml, may be NULL
    lat         REAL,           -- centroid
    lon         REAL,
    radius_m    INTEGER,
    visit_count INTEGER
);

CREATE TABLE IF NOT EXISTS trip_metrics (
    unit_id           INTEGER NOT NULL,
    start_ts          INTEGER NOT NULL,
    end_ts            INTEGER NOT NULL,
    start_place_id    INTEGER,
    end_place_id      INTEGER,
    l_per_100km       REAL,
    harsh_event_count INTEGER,
    idle_s            INTEGER,
    PRIMARY KEY (unit_id, start_ts, end_ts)
);

CREATE TABLE IF NOT EXISTS driver_score (
    unit_id        INTEGER NOT NULL,
    period_start   INTEGER NOT NULL,
    period_end     INTEGER NOT NULL,
    score          REAL,
    distance_m     INTEGER,
    accel_count    INTEGER,
    brake_count    INTEGER,
    corner_count   INTEGER,
    speeding_count INTEGER,
    PRIMARY KEY (unit_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS service_status (
    unit_id                 INTEGER NOT NULL,
    service_type            TEXT NOT NULL,
    interval_km             INTEGER,
    interval_engine_s       INTEGER,
    last_service_odometer_m INTEGER,
    last_service_engine_s   INTEGER,
    current_odometer_m      INTEGER,
    current_engine_s        INTEGER,
    km_remaining            REAL,
    engine_h_remaining      REAL,
    due                     INTEGER,   -- 0/1
    PRIMARY KEY (unit_id, service_type)
);

CREATE TABLE IF NOT EXISTS anomalies (
    unit_id  INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    type     TEXT NOT NULL,   -- fuel_drop|unusual_fill|consumption_drift|device_silent
    severity TEXT,
    detail   TEXT,
    PRIMARY KEY (unit_id, ts, type)
);
