"""Fetch parkings (engine-off stays) from the unit_stays report."""

from ingest import interval_report

TABLE_TYPE = "unit_stays"
LABEL = "Parkings"
DEST = "parkings"

parse_row = interval_report.parse_row  # exposed for tests


def fetch_and_store(client, con, unit_id, resource_id, ts_from, ts_to):
    return interval_report.fetch_and_store(
        client, con, unit_id, resource_id, ts_from, ts_to, TABLE_TYPE, LABEL, DEST)
