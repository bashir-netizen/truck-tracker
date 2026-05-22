"""Ingestion entry point.

Stage 1 scope — prove the connection works end to end:
  1. load the token from the environment
  2. create the SQLite database from schema.sql
  3. log in to Wialon
  4. find the unit and print its id + last position
  5. probe token scope (which data blocks came back)

Stage 2 adds the actual data pulls (trips, fillings, eco events,
unit_state snapshot) and the --since backfill flag.

Run:  python -m ingest.run
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

import config
from ingest.wialon import WialonClient, WialonError

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db(db_path):
    """Create the database and all tables if they do not yet exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA_PATH.read_text())
        con.commit()
    finally:
        con.close()


def main():
    load_dotenv()
    token = os.environ.get("WIALON_TOKEN")
    if not token:
        print("ERROR: WIALON_TOKEN is not set.")
        print("  Copy .env.example to .env and paste your Wialon token.")
        return 1

    init_db(config.DB_PATH)
    print(f"Database ready: {config.DB_PATH}")

    client = WialonClient(token, host=config.WIALON_HOST)

    try:
        client.login()
    except WialonError as e:
        print(f"Login failed: {e}")
        if e.code == 8:
            print("  -> Token is invalid or expired. Generate a new one (see README).")
        return 1
    print(f"Logged in (user id {client.user_id}, server time {client.server_time}).")

    try:
        unit = client.find_unit(config.UNIT_NAME_MASK)
    except WialonError as e:
        print(f"Unit search failed: {e}")
        if e.code == 7:
            print("  -> Token scope is too narrow. It needs read access to the unit.")
        return 1

    if not unit:
        print(f"No unit matched mask {config.UNIT_NAME_MASK!r}.")
        print("  Check the unit's name in Wialon and adjust UNIT_NAME_MASK in config.py.")
        return 1

    print(f"Unit found: id={unit['id']} name={unit.get('nm')!r}")

    pos = unit.get("pos") or {}
    if pos:
        # Wialon position: y=lat, x=lon, s=speed (km/h), t=message time.
        print(f"  last position : lat={pos.get('y')}, lon={pos.get('x')}, "
              f"speed={pos.get('s')} km/h, t={pos.get('t')}")
    else:
        print("  last position : (none reported yet)")

    print(f"  odometer      : {unit.get('cnm')} km")
    print(f"  engine hours  : {unit.get('cneh')} h")

    # Scope probe: warn about anything the report layer will need that
    # this token/device did not return.
    missing = [name for name in ("pos", "cnm", "cneh") if not unit.get(name)]
    if missing:
        print(f"  NOTE: missing {missing} — token scope or device reporting may be limited.")
    else:
        print("  Scope OK: position + counters all present.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
