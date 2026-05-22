"""Fetch stops (brief halts during a trip) from the unit_stops report."""

from ingest import interval_report

TABLE_TYPE = "unit_stops"
LABEL = "Stops"
DEST = "stops"

parse_row = interval_report.parse_row  # exposed for tests


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to):
    return interval_report.fetch_and_store(
        client, con, unit_id, resource_id, ts_from, ts_to, TABLE_TYPE, LABEL, DEST)
