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

# --- Storage --------------------------------------------------------------

# SQLite file. Committed to the repo while single-truck and small;
# migrate to Turso if it grows past ~50 MB. Override with TRUCK_DB.
DB_PATH = os.environ.get("TRUCK_DB", "data/truck.db")

# --- Vehicle --------------------------------------------------------------

TANK_CAPACITY_L = 550  # observed from fill data on the FAW 6x4

# --- Place clustering (Stage 3, DBSCAN) -----------------------------------

DBSCAN_EPS_M = 100        # endpoints within this radius cluster into one place
DBSCAN_MIN_SAMPLES = 3    # min visits to register a place

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

# --- Dashboard (Stage 4) --------------------------------------------------

ACCENT_COLOR = "#C8501E"  # one warm accent; muted neutrals everywhere else
