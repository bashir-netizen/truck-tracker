"""Read-only, cached access to the SQLite database.

The dashboard NEVER writes and NEVER calls Wialon. Every connection is
opened read-only; results are cached and busted on the database file's
mtime, so a fresh ingestion run shows up without a manual rerun.
"""

import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import config

DB_PATH = str(Path(config.DB_PATH))


def _native(v):
    """Coerce a numpy scalar (e.g. np.int64 from pandas) to a plain Python type.

    Critical for bind parameters: SQLite gives numpy scalars BLOB affinity, so
    `ts BETWEEN ? AND ?` with numpy params silently matches nothing. Native
    int/float bind correctly.
    """
    return v.item() if hasattr(v, "item") else v


def _mtime():
    return os.path.getmtime(DB_PATH) if os.path.exists(DB_PATH) else 0.0


@st.cache_data(show_spinner=False)
def _run(sql, params, db_mtime):
    # db_mtime is part of the cache key (busts when the file changes).
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def q(sql, params=()):
    """Run a read-only query, returning a DataFrame (cached on DB mtime)."""
    return _run(sql, tuple(_native(p) for p in params), _mtime())


def scalar(sql, params=(), default=None):
    df = q(sql, params)
    if df.empty or df.iloc[0, 0] is None:
        return default
    return _native(df.iloc[0, 0])


def has_data():
    return os.path.exists(DB_PATH) and scalar("SELECT COUNT(*) FROM trips", default=0) > 0


def last_data_ts():
    """Most recent moment we have data for (the freshness contract)."""
    return scalar("SELECT MAX(ts) FROM unit_state", default=None) \
        or scalar("SELECT MAX(end_ts) FROM trips", default=None)


def last_ingest_ts():
    return scalar("SELECT MAX(run_ts) FROM ingestion_log", default=None)
