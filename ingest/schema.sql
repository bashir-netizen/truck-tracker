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
    place_id           INTEGER PRIMARY KEY,
    label              TEXT,        -- override (places.yaml) or auto from geocode
    lat                REAL,        -- centroid
    lon                REAL,
    radius_m           INTEGER,
    visit_count        INTEGER,
    visit_time_total_s INTEGER,     -- total dwell (parkings) at this place
    needs_label        INTEGER,     -- 1 = weak auto-name, owner should label it
    type               TEXT,        -- depot|destination|transit|customer|workshop (places.yaml)
    median_dwell_s     INTEGER,     -- dwell distribution (Part B)
    p25_dwell_s        INTEGER,
    p75_dwell_s        INTEGER,
    longest_dwell_s    INTEGER,
    shortest_dwell_s   INTEGER,
    dwell_pattern_hint TEXT,        -- brief|medium|long|overnight
    suggested_type_from_dwell TEXT, -- transit?|rest?|customer?|depot?|overnight?
    -- Journey-role signal (Part 3, enrich/place_roles.py): where the place sits in trips.
    total_visits       INTEGER,
    loading_visits     INTEGER,
    destination_visits INTEGER,
    via_visits         INTEGER,
    loading_share      REAL,
    destination_share  REAL,
    suggested_role     TEXT,         -- loading|destination|transit|mixed_use|ambiguous
    role_context       TEXT,         -- JSON: loading -> dests reached, etc.
    yaml_labeled       INTEGER,      -- 1 = matched a places.yaml entry (owner-classified)
    terminus_visits    INTEGER,      -- truck reversed toward home here (Task 11)
    throughpass_visits INTEGER,      -- truck continued away from home past here
    terminus_share     REAL,
    type_confidence    TEXT,         -- high|medium|low (places.yaml; default low when labelled)
    type_reasoning     TEXT          -- why the owner gave this type (places.yaml)
);

-- Journeys: trip legs stitched across short gaps; the real A->B runs.
CREATE TABLE IF NOT EXISTS journeys (
    journey_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id         INTEGER NOT NULL,
    start_ts        INTEGER NOT NULL,
    end_ts          INTEGER,
    origin_lat      REAL,
    origin_lon      REAL,
    dest_lat        REAL,
    dest_lon        REAL,
    origin_place_id INTEGER,
    dest_place_id   INTEGER,
    leg_count       INTEGER,
    distance_m      INTEGER,
    duration_s      INTEGER,
    fuel_l          REAL,
    l_per_100km     REAL,
    is_local        INTEGER,        -- 1 = local/yard, 0 = route
    journey_character TEXT,         -- long_haul | regional | local | yard
    night_seconds   INTEGER,        -- driving time in the 19:00-05:00 local window
    UNIQUE (unit_id, start_ts)
);

-- Each parking mapped to its place, so the dashboard can sum in-range dwell
-- with plain SQL (no geo math in the read layer).
CREATE TABLE IF NOT EXISTS place_visits (
    place_id   INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    duration_s INTEGER,
    PRIMARY KEY (place_id, ts)
);

-- Corridors: journeys aggregated by unordered place pair (route identity).
CREATE TABLE IF NOT EXISTS corridors (
    corridor_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    place_a_id       INTEGER,
    place_b_id       INTEGER,
    journey_count    INTEGER,
    total_distance_m INTEGER,
    total_duration_s INTEGER,
    total_fuel_l     REAL,
    avg_l_per_100km  REAL,
    first_seen_ts    INTEGER,
    last_seen_ts     INTEGER,
    path_geojson     TEXT,           -- [[lon,lat],…] of the most recent journey
    UNIQUE (place_a_id, place_b_id)
);

-- Per-trip GPS paths (RDP-simplified) for the Map's multi-trip view + playback.
-- Built over ALL trips. A trip with no GPS in its window gets point_count=0 and a
-- NULL path (logged, never dropped); the Map falls back to a dashed straight line
-- (start->end from `trips`). Display colour is derived at render time (date->palette),
-- not stored here, so the palette can change without re-enriching.
CREATE TABLE IF NOT EXISTS trip_paths (
    unit_id       INTEGER NOT NULL,
    start_ts      INTEGER NOT NULL,
    end_ts        INTEGER NOT NULL,
    journey_class TEXT,            -- long_haul|regional|local|yard (journey containing the trip)
    point_count   INTEGER,         -- RDP-simplified point count; 0 = no GPS (NULL path)
    path_geojson  TEXT,            -- [[lon,lat],…] RDP-simplified, or NULL
    PRIMARY KEY (unit_id, start_ts)
);

-- Round trips: consecutive journeys that leave a depot and return to one (the
-- owner's unit of work). Derived from `journeys`; depots from places.yaml flags.
CREATE TABLE IF NOT EXISTS round_trips (
    round_trip_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id                  INTEGER NOT NULL,
    start_ts                 INTEGER NOT NULL,   -- depart depot
    end_ts                   INTEGER NOT NULL,   -- return to depot
    primary_destination_id   INTEGER,            -- farthest-from-depot named place
    primary_destination_name TEXT,
    journey_class            TEXT NOT NULL,      -- highest class among constituents
    total_distance_km        REAL,
    total_duration_s         INTEGER,            -- depot-to-depot wall time
    constituent_journey_ids  TEXT,               -- JSON array
    via_places               TEXT,               -- JSON array (outbound, named)
    return_via_places        TEXT                -- JSON array (return, named)
);
CREATE INDEX IF NOT EXISTS idx_round_trips_unit_start ON round_trips (unit_id, start_ts);

-- Delivery cycles (Task 10): the hauler's operational unit — load at an anchor (depot OR a
-- loading customer) -> deliver -> arrive at the next anchor. Anchored on loading customers,
-- where round_trips is depot-anchored. Both views coexist.
CREATE TABLE IF NOT EXISTS delivery_cycles (
    cycle_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id                 INTEGER NOT NULL,
    cycle_start_ts          INTEGER NOT NULL,  -- arrival at the loading anchor
    cycle_end_ts            INTEGER,           -- arrival at the next anchor (NULL = incomplete)
    origin_place_id         INTEGER,
    origin_place_name       TEXT,
    destination_place_id    INTEGER,
    destination_place_name  TEXT,
    cycle_type              TEXT,              -- delivery | positioning | incomplete
    total_distance_km       REAL,
    total_duration_s        INTEGER,
    constituent_journey_ids TEXT,              -- JSON array
    via_places              TEXT,              -- JSON array (named intermediates)
    return_leg_type         TEXT,              -- populated in Task 12
    return_leg_confidence   TEXT               -- populated in Task 12
);
CREATE INDEX IF NOT EXISTS idx_delivery_cycles_unit_start
    ON delivery_cycles (unit_id, cycle_start_ts);

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
    unit_id           INTEGER NOT NULL,
    period_start      INTEGER NOT NULL,
    period_end        INTEGER NOT NULL,
    score             REAL,         -- Wialon 0-10 rank (reference)
    distance_m        INTEGER,
    accel_count       INTEGER,
    brake_count       INTEGER,
    corner_count      INTEGER,
    speeding_count    INTEGER,
    hard_safety_count INTEGER,      -- genuine safety events (road-condition agnostic)
    PRIMARY KEY (unit_id, period_start, period_end)
);

-- Per-event derived flags for the Driver page (raw eco_events untouched).
CREATE TABLE IF NOT EXISTS eco_flags (
    unit_id           INTEGER NOT NULL,
    ts                INTEGER NOT NULL,
    type              TEXT,
    severity          TEXT,
    journey_character TEXT,
    hard_safety       INTEGER,
    PRIMARY KEY (unit_id, ts, type)
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
