"""Enrichment entry point.

Rebuilds every derived table from the raw tables. Reads raw, writes only
derived tables — never modifies raw rows. Run after ingestion:

    python -m enrich.run

Derived tables are dropped and recreated from schema.sql at the start of each
run, so schema changes always apply (the data is fully rebuildable). Raw tables
are never touched.
"""

import sqlite3
import sys
from pathlib import Path

import config
from enrich import (anomalies, corridors, delivery_cycles, driver, eco, journeys,
                    maintenance, metrics, place_roles, places, return_leg, round_trips,
                    trip_paths)

SCHEMA = (Path(__file__).resolve().parents[1] / "ingest" / "schema.sql").read_text()
DERIVED = ["trip_metrics", "journeys", "corridors", "driver_score",
           "service_status", "anomalies", "places", "place_visits", "eco_flags",
           "trip_paths", "round_trips", "delivery_cycles"]


def main():
    con = sqlite3.connect(config.DB_PATH)
    try:
        row = (con.execute("SELECT unit_id FROM trips LIMIT 1").fetchone()
               or con.execute("SELECT unit_id FROM unit_state LIMIT 1").fetchone())
        if not row:
            print("No data to enrich. Run `python -m ingest.run` first.")
            return 1
        unit_id = row[0]

        # Refresh derived-table schema (safe: all rebuilt below).
        for t in DERIVED:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.executescript(SCHEMA)

        n_journeys = journeys.rebuild(con, unit_id)
        n_places = places.rebuild(con, unit_id)
        journeys.assign_places(con, unit_id)
        n_corridors = corridors.rebuild(con, unit_id)
        n_round = round_trips.rebuild(con, unit_id)
        n_roles = place_roles.rebuild(con, unit_id)
        n_cycles = delivery_cycles.rebuild(con, unit_id)
        return_leg.rebuild(con, unit_id)             # classifies each delivery cycle's return leg
        n_paths = trip_paths.rebuild(con, unit_id)
        n_metrics = metrics.rebuild(con, unit_id)
        eco.rebuild(con, unit_id)            # eco_flags (hard-safety) before driver
        n_driver = driver.rebuild(con, unit_id)
        n_services = maintenance.rebuild(con, unit_id)
        n_anom = anomalies.rebuild(con, unit_id)
        con.commit()
    finally:
        con.close()

    print(f"Enriched: journeys={n_journeys} corridors={n_corridors} places={n_places} "
          f"round_trips={n_round} delivery_cycles={n_cycles} role_suggestions={n_roles} "
          f"trip_paths={n_paths} trip_metrics={n_metrics} driver_weeks={n_driver} "
          f"services={n_services} anomalies={n_anom}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
