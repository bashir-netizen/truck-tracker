"""Enrichment entry point.

Rebuilds every derived table from the raw tables. Reads raw, writes only
derived tables — never modifies raw rows. Run after ingestion:

    python -m enrich.run
"""

import sqlite3
import sys

import config
from enrich import anomalies, driver, maintenance, metrics, places


def main():
    con = sqlite3.connect(config.DB_PATH)
    try:
        row = (con.execute("SELECT unit_id FROM trips LIMIT 1").fetchone()
               or con.execute("SELECT unit_id FROM unit_state LIMIT 1").fetchone())
        if not row:
            print("No data to enrich. Run `python -m ingest.run` first.")
            return 1
        unit_id = row[0]

        n_places = places.rebuild(con, unit_id)
        n_metrics = metrics.rebuild(con, unit_id)
        n_driver = driver.rebuild(con, unit_id)
        n_services = maintenance.rebuild(con, unit_id)
        n_anom = anomalies.rebuild(con, unit_id)
        con.commit()
    finally:
        con.close()

    print(f"Enriched: places={n_places} trip_metrics={n_metrics} "
          f"driver_weeks={n_driver} services={n_services} anomalies={n_anom}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
