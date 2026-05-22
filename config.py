"""Central configuration for Truck Tracker.

Thresholds, intervals, and tunables live here — never hardcoded in the
ingestion, enrichment, or display layers. Editing this file changes
behaviour everywhere without touching logic elsewhere.

Secrets (the Wialon token) do NOT live here. They come from the
environment / .env only.
"""

import os

# --- Wialon ---------------------------------------------------------------

WIALON_HOST = "https://hst-api.wialon.eu"

# The unit is matched by name mask against its Wialon "sys_name".
# "KDX 415X" -> "*KDX*" is enough while there is a single truck.
UNIT_NAME_MASK = "*KDX*"

# Display name + vehicle description for the dashboard header.
UNIT_DISPLAY_NAME = "KDX 415X"
UNIT_DESCRIPTION = "FAW 6x4 · Teltonika FMB920"

# --- Storage --------------------------------------------------------------

# SQLite file. Committed to the repo while single-truck and small;
# migrate to Turso if it grows past ~50 MB. Override with TRUCK_DB.
DB_PATH = os.environ.get("TRUCK_DB", "data/truck.db")

# --- Vehicle --------------------------------------------------------------

TANK_CAPACITY_L = 550  # observed from fill data on the FAW 6x4

# --- Place clustering (Stage 3, DBSCAN) -----------------------------------

DBSCAN_EPS_M = 100        # endpoints within this radius cluster into one place
DBSCAN_MIN_SAMPLES = 3    # min visits to register a place

# --- Journeys & places (route view) ---------------------------------------
# A parking/gap at least this long ends one journey and starts the next.
JOURNEY_SPLIT_HOURS = 3
# A journey shorter than this (or returning to its origin) is "local", not a route.
ROUTE_MIN_KM = 5

# Journey "character" buckets (tunable without code changes). A journey is
# long_haul if it covers the distance OR spans the duration.
TRIP_THRESHOLDS = {
    "long_haul_min_distance_m": 300_000,
    "long_haul_min_duration_s": 86_400,
    "regional_min_distance_m": 80_000,
    "local_min_distance_m": 5_000,
}
# Significant-place clustering: town scale, and min_samples=1 so a
# destination visited only once still becomes a place. Only journey endpoints
# and parkings at least PLACE_MIN_DWELL_S long seed a place (keeps out the
# many brief roadside halts).
PLACE_EPS_M = 800
PLACE_MIN_SAMPLES = 1
PLACE_MIN_DWELL_S = 1800

# --- Anomaly thresholds (Stage 3) -----------------------------------------

FUEL_DROP_PCT = 10          # level drop > this % between readings => possible theft
CONSUMPTION_DRIFT_PCT = 20  # period L/100km this % above baseline => drift
DEVICE_SILENT_HOURS = 24    # no eco events during active driving => health anomaly

# --- Maintenance intervals (Stage 3) --------------------------------------
# Per service type: distance (km) and/or engine-hours. None = not tracked
# by that dimension. Last-service baselines come from services.yaml.

MAINTENANCE_INTERVALS = {
    "engine_oil":    {"km": 15000, "engine_h": 500},
    "transmission":  {"km": 60000, "engine_h": None},
    "air_filter":    {"km": 30000, "engine_h": None},
    "major_service": {"km": 90000, "engine_h": None},
}

# --- Driver eco score (Stage 3) -------------------------------------------
# Penalty weight per event, normalised per 100 km when scoring.

ECO_WEIGHTS = {
    "harsh_accel":  1.0,
    "harsh_brake":  1.5,
    "harsh_corner": 1.0,
    "speeding":     2.0,
    "idling":       0.5,
}

# Score = 100 - (weighted events per 100 km) * this scale, clamped to 0..100.
SCORE_PENALTY_SCALE = 2.0

# L/100km is meaningless on near-zero-distance maneuvers; only compute it
# (and judge drift) for trips at least this long.
MIN_ECONOMY_KM = 2
DRIFT_MIN_TRIP_KM = 5
DRIFT_MIN_WEEK_KM = 50   # don't judge a week's economy on too little driving

# --- GPS track (positions) ------------------------------------------------
# Keep a track point only when it is at least this far from the last kept
# point. Drops the many redundant parked points; preserves road shape.
TRACK_MIN_METERS = 25

# --- Rates (billing) ------------------------------------------------------
# The per-km rates MUST stay None until real Genwatt rates are known.
# Placeholder or guessed values are NOT acceptable: the dashboard hides revenue
# entirely until at least one km rate is set here. Only the diesel pump price
# gets a real default — it is public information and easy to keep current.
RATES = {
    "long_haul_kes_per_km": None,
    "regional_kes_per_km": None,
    "local_kes_per_km": None,
    "diesel_kes_per_l": 180,   # current Kenyan pump price; update as it changes
}

# --- Dashboard (Stage 4) --------------------------------------------------

ACCENT_COLOR = "#1F6FEB"  # primary blue (clean professional theme)

# Hide trivial in-traffic stops shorter than this on the map/tables.
STOP_MIN_DISPLAY_S = 180
