"""Project service intervals from actual usage.

Rebuilds `service_status`. Current odometer is the cumulative trip
distance (the truck is new, so this tracks true mileage; the device's
own counter is unreliable). Engine-hours are used only if the counter is
configured in Wialon (currently 0). Last-service baselines come from
services.yaml; absent => assumed serviced from new (0).

services.yaml format:
    engine_oil:
      last_service_km: 0
      last_service_engine_h: 0
"""

from pathlib import Path

import yaml

import config

ROOT = Path(__file__).resolve().parents[1]
SERVICES_YAML = ROOT / "services.yaml"


def _load_baselines():
    if SERVICES_YAML.exists():
        return yaml.safe_load(SERVICES_YAML.read_text()) or {}
    return {}


def rebuild(con, unit_id):
    con.execute("DELETE FROM service_status")

    current_m = con.execute(
        "SELECT COALESCE(SUM(distance_m), 0) FROM trips WHERE unit_id=?",
        (unit_id,)).fetchone()[0]
    row = con.execute(
        "SELECT engine_hours_s FROM unit_state WHERE unit_id=? "
        "ORDER BY ts DESC LIMIT 1", (unit_id,)).fetchone()
    current_es = row[0] if row and row[0] is not None else 0

    baselines = _load_baselines()
    out = []
    for stype, interval in config.MAINTENANCE_INTERVALS.items():
        base = baselines.get(stype, {})
        last_m = int(base.get("last_service_km", 0) * 1000)
        last_es = int(base.get("last_service_engine_h", 0) * 3600)
        iv_km = interval.get("km")
        iv_es = int(interval["engine_h"] * 3600) if interval.get("engine_h") else None

        km_remaining = None
        due = 0
        if iv_km:
            km_remaining = round(iv_km - (current_m - last_m) / 1000.0, 1)
            if km_remaining <= 0:
                due = 1
        eh_remaining = None
        if iv_es:
            eh_remaining = round((iv_es - (current_es - last_es)) / 3600.0, 1)
            if eh_remaining <= 0 and current_es > 0:  # only meaningful if tracked
                due = 1

        out.append((unit_id, stype, iv_km, iv_es, last_m, last_es,
                    current_m, current_es, km_remaining, eh_remaining, due))

    con.executemany(
        "INSERT INTO service_status "
        "(unit_id, service_type, interval_km, interval_engine_s, "
        " last_service_odometer_m, last_service_engine_s, current_odometer_m, "
        " current_engine_s, km_remaining, engine_h_remaining, due) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", out)
    return len(out)
