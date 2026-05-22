"""Ingestion entry point.

One job per run: log in, find the unit, pull trips / fillings / eco
events for the window, snapshot the unit's counters, write an audit row,
and exit. Idempotent — re-running over the same period adds nothing.

Usage:
    python -m ingest.run                 # last 30 days
    python -m ingest.run --since 90       # last 90 days
    python -m ingest.run --since 2026-01-01
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import config
from ingest import (eco_events, fillings, parkings, positions, stops, trips,
                    unit_state)
from ingest.wialon import WialonClient, WialonError

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
WINDOW_DAYS = 30  # report interval per exec; backfills are chunked into these


def init_db(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA_PATH.read_text())
        con.commit()
    finally:
        con.close()


def parse_since(value, now):
    """A '--since' value to an epoch. Accepts days-back or YYYY-MM-DD."""
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return now - int(value) * 86400


def windows(ts_from, ts_to, step_days=WINDOW_DAYS):
    """Yield (start, end) chunks of at most step_days covering the range."""
    step = step_days * 86400
    start = ts_from
    while start < ts_to:
        yield start, min(start + step, ts_to)
        start += step


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pull truck data from Wialon into SQLite.")
    parser.add_argument("--since", default="30",
                        help="days back (e.g. 30) or a date (YYYY-MM-DD). Default 30.")
    args = parser.parse_args(argv)

    load_dotenv()
    token = os.environ.get("WIALON_TOKEN")
    if not token:
        print("ERROR: WIALON_TOKEN is not set. Copy .env.example to .env and add your token.")
        return 1

    init_db(config.DB_PATH)
    client = WialonClient(token, host=config.WIALON_HOST)

    try:
        client.login()
    except WialonError as e:
        print(f"Login failed: {e}")
        if e.code == 8:
            print("  -> Token is invalid or expired (see README to generate one).")
        return 1

    now = client.server_time or int(time.time())
    ts_from = parse_since(args.since, now)
    ts_to = now

    try:
        unit = client.find_unit(config.UNIT_NAME_MASK)
        if not unit:
            print(f"No unit matched mask {config.UNIT_NAME_MASK!r}. Check config.py.")
            return 1
        resource_id = client.find_resource_id()
        if not resource_id:
            print("No resource available to run reports under.")
            return 1
    except WialonError as e:
        print(f"Setup failed: {e}")
        if e.code == 7:
            print("  -> Token scope is too narrow (needs unit + report access).")
        return 1

    unit_id = unit["id"]
    fmt = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    print(f"Unit {unit_id} ({unit.get('nm')!r}); pulling {fmt(ts_from)} .. {fmt(ts_to)}")

    con = sqlite3.connect(config.DB_PATH)
    added = {k: 0 for k in ("trips", "fillings", "eco", "parkings", "stops",
                            "positions", "unit_state")}
    status, detail = "ok", ""
    try:
        for w_from, w_to in windows(ts_from, ts_to):
            added["trips"] += trips.fetch_and_store(client, con, unit_id, resource_id, w_from, w_to)
            added["fillings"] += fillings.fetch_and_store(client, con, unit_id, resource_id, w_from, w_to)
            added["eco"] += eco_events.fetch_and_store(client, con, unit_id, resource_id, w_from, w_to)
            added["parkings"] += parkings.fetch_and_store(client, con, unit_id, resource_id, w_from, w_to)
            added["stops"] += stops.fetch_and_store(client, con, unit_id, resource_id, w_from, w_to)
            # messages-based; cleans up reports first, so it runs last in the window
            added["positions"] += positions.fetch_and_store(client, con, unit_id, w_from, w_to)
        added["unit_state"] = unit_state.snapshot(con, unit)
        con.commit()
    except WialonError as e:
        status, detail = "error", str(e)
        con.rollback()
        print(f"Ingestion error: {e}")
    finally:
        if status == "ok":
            detail = (f"parkings={added['parkings']} stops={added['stops']} "
                      f"positions={added['positions']}")
        con.execute(
            "INSERT OR REPLACE INTO ingestion_log "
            "(run_ts, since_ts, until_ts, trips_added, fillings_added, eco_added, status, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (int(time.time()), ts_from, ts_to, added["trips"], added["fillings"],
             added["eco"], status, detail),
        )
        con.commit()
        con.close()

    print(f"Added: trips={added['trips']} fillings={added['fillings']} "
          f"eco={added['eco']} parkings={added['parkings']} stops={added['stops']} "
          f"positions={added['positions']} unit_state={added['unit_state']}  status={status}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
